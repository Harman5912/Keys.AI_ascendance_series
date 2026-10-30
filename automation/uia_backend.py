"""Backend #1 — Windows UI Automation (pywinauto / uiautomation).

The DEFAULT interaction layer: discovers windows and controls through their
automation properties (name, control type, automation id, value, state) instead
of screen coordinates. Falls back to coordinate input only when an element
cannot be reached through its automation API (e.g. invoke pattern missing).

Dependencies: pywinauto (Windows). The `uiautomation` package is used as a
fast secondary reader when installed — otherwise pywinauto's uia backend.
"""

from __future__ import annotations

import platform
from typing import Optional

from automation.base import Backend, Element, Rect, WindowInfo


def _is_windows() -> bool:
    return platform.system() == "Windows"


class UiaBackend(Backend):
    name = "uia"
    priority = 1

    def __init__(self) -> None:
        self._pywinauto = None
        self._uiauto = None

    def available(self) -> bool:
        if not _is_windows():
            return False
        try:
            import pywinauto  # noqa: F401
            self._pywinauto = True
            return True
        except Exception:
            return False

    # ── window discovery ────────────────────────────────────────────────
    def list_windows(self) -> list[WindowInfo]:
        if not self.available():
            raise RuntimeError("pywinauto is not available")
        from pywinauto import Desktop

        out: list[WindowInfo] = []
        try:
            desktop = Desktop(backend="uia")
            for w in desktop.windows():
                try:
                    rect = w.rectangle()
                    out.append(WindowInfo(
                        title=w.window_text() or "(untitled)",
                        handle=int(w.handle),
                        rect=Rect(int(rect.left), int(rect.top),
                                  int(rect.width()), int(rect.height())),
                        process=w.process_id() and str(w.process_id()) or "",
                        pid=int(w.process_id() or 0),
                    ))
                except Exception:
                    continue
        except Exception:
            pass
        return out

    # ── component enumeration ──────────────────────────────────────────
    def list_elements(self, window_title: str = "") -> list[Element]:
        """Enumerate the interactive controls of a window (or the active one).
        Returns up to 300 elements with name / type / automation id / rect / state.
        """
        if not self.available():
            return []
        try:
            from pywinauto import Desktop
            desktop = Desktop(backend="uia")
            wins = desktop.windows()
        except Exception:
            return []

        # Pick the target window: by title fragment, else the active/foreground one.
        target = None
        if window_title:
            for w in wins:
                try:
                    if window_title.lower() in (w.window_text() or "").lower():
                        target = w
                        break
                except Exception:
                    continue
        else:
            for w in wins:
                try:
                    if w.is_active() or w.has_focus():
                        target = w
                        break
                except Exception:
                    continue
        if target is None and wins:
            target = wins[0]
        if target is None:
            return []

        _INTEREST = ("Button", "Edit", "CheckBox", "RadioButton", "ComboBox",
                     "ListItem", "MenuItem", "TabItem", "Hyperlink", "Slider",
                     "TreeItem", "DataItem", "SplitButton", "Spinner", "ToolBar")
        out: list[Element] = []
        try:
            _visited = 0
            for ctrl in target.descendants():
                _visited += 1
                if _visited > 5000:      # never let one window stall the tool call
                    break
                try:
                    info = ctrl.element_info
                    ctype = info.control_type or ""
                    if ctype not in _INTEREST:
                        continue
                    name = (info.name or ctrl.window_text() or "").strip()
                    if not name and ctype not in ("Edit", "Slider", "Spinner"):
                        continue
                    try:
                        rect = ctrl.rectangle()
                        r = Rect(int(rect.left), int(rect.top),
                                 int(rect.width()), int(rect.height()))
                    except Exception:
                        r = None
                    el = Element(name=name, control_type=ctype,
                                 automation_id=info.automation_id or "",
                                 rect=r, backend="uia", handle=ctrl)
                    try:
                        el.enabled = bool(ctrl.is_enabled())
                    except Exception:
                        pass
                    out.append(el)
                except Exception:
                    continue
        except Exception:
            pass
        return out[:300]

    def get_value(self, element: Element) -> str:
        """Read an element's current value via the UIA ValuePattern."""
        if not element or element.handle is None:
            return ""
        try:
            wrapper = element.handle
            try:
                v = wrapper.get_value()
                if v not in (None, ""):
                    return str(v)
            except Exception:
                pass
            try:
                vp = wrapper.element_info.get_value_pattern()
                if vp is not None:
                    v = vp.Value()
                    if v not in (None, ""):
                        return str(v)
            except Exception:
                pass
        except Exception:
            pass
        return ""

    # ── element search ──────────────────────────────────────────────────
    def find(self, description: str, control_type: str = "", window_title: str = "") -> Optional[Element]:
        if not self.available():
            return None
        return self.retry(lambda: self._find_once(description, control_type, window_title),
                          attempts=2, delay=0.3)

    def _find_once(self, description, control_type, window_title):
        try:
            from pywinauto import Desktop
            desktop = Desktop(backend="uia")
            windows = desktop.windows()
        except Exception:
            return None

        desc = (description or "").strip()
        for w in windows:
            try:
                title = w.window_text() or ""
            except Exception:
                continue
            if window_title and window_title.lower() not in title.lower():
                continue

            # 1) direct name match on the window itself
            if desc and desc.lower() == title.lower():
                return self._wrap(w, desc, control_type)

            # 2) search descendants by name / automation id / control type
            try:
                kwargs = {"title": desc} if desc else {}
                if control_type:
                    kwargs["control_type"] = control_type
                found = w.child_window(**kwargs) if kwargs else None
                if found is not None and found.exists(timeout=0.5):
                    return self._wrap(found, desc, control_type)
            except Exception:
                pass

            # 3) text-field / button value search fallback
            if desc:
                try:
                    for ctrl in w.descendants():
                        try:
                            nm = ctrl.window_text() or ctrl.element_info.name or ""
                            ctype = ctrl.element_info.control_type or ""
                        except Exception:
                            continue
                        if (desc.lower() in nm.lower()
                                and (not control_type or ctype == control_type)):
                            return self._wrap(ctrl, nm, ctype)
                        # automation id match
                        try:
                            aid = ctrl.element_info.automation_id or ""
                        except Exception:
                            aid = ""
                        if aid and desc.lower() in aid.lower():
                            return self._wrap(ctrl, nm or aid, ctype or control_type)
                except Exception:
                    continue
        return None

    @staticmethod
    def _wrap(handle, name: str, control_type: str) -> Element:
        try:
            rect = handle.rectangle()
            r = Rect(int(rect.left), int(rect.top),
                     int(rect.width()), int(rect.height()))
        except Exception:
            r = None
        try:
            aid = handle.element_info.automation_id or ""
        except Exception:
            aid = ""
        return Element(name=name, control_type=control_type,
                       automation_id=aid, rect=r, backend="uia", handle=handle)

    # ── interaction ─────────────────────────────────────────────────────
    def click(self, element: Element) -> bool:
        if not element or element.handle is None:
            return False
        try:
            wrapper = element.handle
            # Prefer the Invoke / Toggle pattern; fall back to physical click.
            try:
                patterns = wrapper.element_info.patterns or {}
                if any(p in patterns for p in ("Invoke", "Toggle", "ExpandCollapse", "SelectionItem")):
                    try:
                        wrapper.invoke()
                        return True
                    except Exception:
                        pass
            except Exception:
                pass
            if element.rect and element.rect.center:
                wrapper.click_input()
                return True
            wrapper.set_focus()
            wrapper.click_input()
            return True
        except Exception:
            return False

    def type_text(self, element: Optional[Element], text: str) -> bool:
        try:
            if element and element.handle is not None:
                wrapper = element.handle
                try:
                    wrapper.set_edit_text(text)
                    return True
                except Exception:
                    pass
                try:
                    wrapper.select()
                    wrapper.type_keys(text)
                    return True
                except Exception:
                    pass
            # Focus element, then send keys via its window
            if element and element.handle is not None:
                try:
                    element.handle.set_focus()
                except Exception:
                    pass
            from pywinauto.keyboard import send_keys
            send_keys(text, with_spaces=True, pause=0.01)
            return True
        except Exception:
            return False

    def get_text(self, element: Element) -> str:
        if not element or element.handle is None:
            return ""
        try:
            wrapper = element.handle
            for attr in ("window_text",):
                try:
                    v = wrapper.window_text()
                    if v:
                        return v
                except Exception:
                    pass
            try:
                return wrapper.element_info.name or ""
            except Exception:
                return ""
        except Exception:
            return ""

    def focus_window(self, title: str) -> bool:
        if not self.available():
            return False
        try:
            from pywinauto import Desktop
            windows = Desktop(backend="uia").windows()
            for w in windows:
                try:
                    if title.lower() in (w.window_text() or "").lower():
                        w.set_focus()
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return False
