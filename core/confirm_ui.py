"""
core/confirm_ui.py — wires core/confirm.py to the Keys.ai HUD.

The confirmation token must be issued by the interface, never by the model
(see core/confirm.py). This module binds that gate to the interface using
the SAME confirm panel Agent Control Mode already shows — no new visuals,
no new dependency: the existing CONFIRM / CANCEL / TAKE CONTROL dialog,
centred over the HUD.

Threading: core.confirm.request() runs on executor threads while the HUD
lives on the Qt thread, so every visual hop goes through MainWindow's
signals (they marshal onto the Qt thread for us).

If the main window is hidden (mini-overlay-only mode) there is no surface
to press a button on, so showing raises and the gate refuses the action
honestly rather than performing something irreversible unconfirmed.
"""

from __future__ import annotations

from core import confirm as confirm_gate


def install(main_window, log=None) -> None:
    """Bind core.confirm to the HUD. `main_window` is the MainWindow —
    it must expose _confirm_show_sig / _confirm_hide_sig signals (added
    alongside this feature) and live on the Qt thread."""
    def _show(title: str, detail: str) -> None:
        main_window._confirm_show_sig.emit(str(title), str(detail))

    def _hide() -> None:
        try:
            main_window._confirm_hide_sig.emit()
        except Exception:
            pass

    confirm_gate.bind(show=_show, hide=_hide, log=log or (lambda msg: None))
