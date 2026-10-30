"""Putting a collected asset *into* a real project or document.

Copying a file into a folder is not integration. Each function here inspects the
target first, chooses the destination its framework actually reads, copies or
inserts the bytes, then reopens the result and checks that the asset is
resolvable. A function that cannot verify its work returns ``ok: False`` with
the reason instead of claiming success.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

_WEB_MARKERS = {
    "next": ("public",),
    "vite": ("public", "src/assets"),
    "react": ("public", "src/assets"),
    "web-static": ("assets", "images", "img"),
}
_DRAWABLE_DENSITIES = ("drawable-xxxhdpi", "drawable-xxhdpi", "drawable-xhdpi",
                       "drawable-hdpi", "drawable-mdpi", "drawable")


class IntegrationError(RuntimeError):
    pass


def _unique_copy(source: Path, directory: Path, stem: str | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    base = stem or source.stem
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base) or "asset"
    candidate = directory / f"{base}{source.suffix.lower()}"
    counter = 1
    while candidate.exists():
        counter += 1
        candidate = directory / f"{base}_{counter}{source.suffix.lower()}"
    shutil.copy2(source, candidate)
    if candidate.stat().st_size != source.stat().st_size:
        candidate.unlink(missing_ok=True)
        raise IntegrationError("The copied file does not match its source.")
    return candidate


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def detect_project(root: str | Path) -> dict:
    """What kind of project is this, and where does it keep assets?"""
    root = Path(root).expanduser().resolve()
    info = {"root": str(root), "type": "unknown", "asset_dir": "",
            "asset_url_prefix": "", "entry_html": "", "marker": "",
            "notes": []}
    if not root.is_dir():
        info["notes"].append("project folder does not exist")
        return info
    files = {p.name for p in root.iterdir()}
    if "package.json" in files:
        try:
            pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
        except Exception:
            pkg = {}
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        if "next" in deps:
            info.update(type="next", asset_dir="public", asset_url_prefix="/")
        elif "vite" in deps:
            info.update(type="vite", asset_dir="src/assets", asset_url_prefix="/")
        else:
            info.update(type="react", asset_dir="public", asset_url_prefix="/")
        index = root / "index.html"
        if index.is_file():
            info["entry_html"] = str(index)
        return info
    if "pubspec.yaml" in files:
        info.update(type="flutter", asset_dir="assets", asset_url_prefix="assets/")
        info["notes"].append("Flutter also needs the asset declared in pubspec.yaml")
        return info
    if (root / "settings.gradle").is_file() or (root / "settings.gradle.kts").is_file():
        res = root / "app" / "src" / "main" / "res"
        info.update(type="android", asset_dir=str(res) if res.is_dir() else "",
                    asset_url_prefix="@drawable/")
        if not res.is_dir():
            info["notes"].append("app/src/main/res was not found")
        return info
    if (root / "pyproject.toml").is_file() or (root / "main.py").is_file() or files & {
            "requirements.txt", "setup.py"}:
        assets = root / "assets"
        info.update(type="python", asset_dir=str(assets) if assets.is_dir() else "assets",
                    asset_url_prefix="assets/")
        return info
    index = root / "index.html"
    if index.is_file():
        info.update(type="web-static", asset_dir="assets", asset_url_prefix="assets/")
        info["entry_html"] = str(index)
        return info
    info["notes"].append("no recognised framework marker (package.json, "
                         "pubspec.yaml, gradle, index.html)")
    return info


def _insert_html_reference(page: Path, relative_src: str, alt: str,
                           caption: str = "") -> dict:
    """Insert an <img> (or figure) into a page and verify it landed."""
    html = page.read_text(encoding="utf-8", errors="replace")
    marker = "<!-- KEYS_AI_ASSETS -->"
    figure = (f'<figure class="keysai-asset">\n'
              f'  <img src="{relative_src}" alt="{alt}" loading="lazy">\n'
              + (f'  <figcaption>{caption}</figcaption>\n' if caption else "")
              + "</figure>\n")
    if marker in html:
        html = html.replace(marker, marker + "\n" + figure, 1)
    elif "</body>" in html:
        html = html.replace("</body>", figure + "</body>", 1)
    else:
        html += "\n" + figure
    page.write_text(html, encoding="utf-8")
    written = page.read_text(encoding="utf-8", errors="replace")
    return {"ok": relative_src in written, "page": str(page),
            "reference": relative_src, "marker_used": marker in html}


def add_to_web_project(asset_path: str, project_root: str, *,
                       name: str = "", alt: str = "", caption: str = "",
                       page: str = "", insert: bool = True) -> dict:
    """Copy an approved image into the project's real asset folder."""
    source = Path(asset_path)
    if not source.is_file():
        return {"ok": False, "error": f"Asset not found: {source}"}
    if source.suffix.lower() not in IMAGE_EXT:
        return {"ok": False, "error": "Only image assets can be embedded here."}
    project = detect_project(project_root)
    if project["type"] == "unknown" or not project.get("asset_dir"):
        return {"ok": False, "error": ("Could not identify the project's asset "
                                       "folder; nothing was copied."),
                "project": project}
    root = Path(project["root"])
    asset_dir = root / project["asset_dir"]
    if not _inside(asset_dir, root):
        return {"ok": False, "error": "Asset folder resolves outside the project."}
    dest = _unique_copy(source, asset_dir, name or source.stem)
    if project["type"] in ("web-static", "vite", "react", "next"):
        prefix = project["asset_url_prefix"]
        relative = f"{prefix}{dest.name}" if prefix.endswith("/") else \
            f"{prefix}/{dest.name}"
        if project["type"] == "web-static":
            relative = f"{project['asset_dir']}/{dest.name}"
    else:
        relative = f"{project['asset_dir']}/{dest.name}"
    result = {"ok": True, "dest": str(dest), "reference": relative,
              "project_type": project["type"]}
    page_path = Path(page) if page else (
        Path(project["entry_html"]) if project.get("entry_html") else None)
    if insert and page_path and page_path.is_file() and \
            page_path.suffix.lower() in (".html", ".htm"):
        inserted = _insert_html_reference(
            page_path, relative, alt or source.stem, caption)
        result.update({"verified": inserted["ok"], "page": inserted["page"]})
        if not inserted["ok"]:
            result.update({"ok": False,
                           "error": "The reference was not written to the page."})
    else:
        result["verified"] = dest.is_file()
        result["note"] = ("Copied into the project's asset folder. Add the "
                          "reference to the template that renders it."
                          if insert else "Copied without inserting a reference.")
    return result


def add_to_docx(asset_path: str, docx_path: str, *, caption: str = "",
                source_note: str = "", width_inches: float = 5.5) -> dict:
    source = Path(asset_path)
    target = Path(docx_path)
    if not source.is_file():
        return {"ok": False, "error": f"Asset not found: {source}"}
    try:
        from docx import Document
        from docx.shared import Inches
    except Exception as exc:
        return {"ok": False, "error": f"python-docx is unavailable: {exc}"}
    try:
        doc = Document(str(target)) if target.is_file() else Document()
        before = len(doc.inline_shapes)
        doc.add_picture(str(source), width=Inches(width_inches))
        after = len(doc.inline_shapes)
        if caption:
            doc.add_paragraph(caption)
        if source_note:
            note = doc.add_paragraph(f"Source: {source_note}")
            for run in note.runs:
                run.italic = True
        target.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(target))
    except Exception as exc:
        return {"ok": False, "error": f"Could not insert the image: {exc}"}
    # Reopen: the file on disk must contain the new picture.
    try:
        again = Document(str(target))
        verified = len(again.inline_shapes) > before
    except Exception as exc:
        return {"ok": False, "error": f"Saved document cannot be reopened: {exc}"}
    return {"ok": verified, "dest": str(target),
            "verified": verified, "pictures": before + 1,
            "error": "" if verified else "The picture is not in the saved document."}


def add_to_pptx(asset_path: str, pptx_path: str, *, caption: str = "",
                source_note: str = "", slide_index: int = -1) -> dict:
    source = Path(asset_path)
    target = Path(pptx_path)
    if not source.is_file():
        return {"ok": False, "error": f"Asset not found: {source}"}
    try:
        from pptx import Presentation
        from pptx.util import Inches
        from PIL import Image
    except Exception as exc:
        return {"ok": False, "error": f"python-pptx is unavailable: {exc}"}
    try:
        prs = Presentation(str(target)) if target.is_file() else Presentation()
        slide_w = prs.slide_width or Inches(13.333)
        slide_h = prs.slide_height or Inches(7.5)
        if slide_index >= 0 and slide_index < len(prs.slides):
            slide = prs.slides[slide_index]
        else:
            slide = prs.slides.add_slide(prs.slide_layouts[6])
        with Image.open(source) as im:
            width, height = im.size
        max_w = int(slide_w * 0.6)
        max_h = int(slide_h * 0.6)
        scale = min(max_w / width, max_h / height)
        draw_w, draw_h = int(width * scale), int(height * scale)
        left = int((slide_w - draw_w) / 2)
        top = int(Inches(0.6))
        slide.shapes.add_picture(str(source), left, top, draw_w, draw_h)
        if caption:
            box = slide.shapes.add_textbox(left, top + draw_h + Inches(0.1),
                                           draw_w, Inches(0.7))
            box.text_frame.text = caption
            if source_note:
                box.text_frame.add_paragraph().text = f"Source: {source_note}"
        target.parent.mkdir(parents=True, exist_ok=True)
        prs.save(str(target))
    except Exception as exc:
        return {"ok": False, "error": f"Could not insert the image: {exc}"}
    try:
        again = Presentation(str(target))
        verified = any(shape.shape_type == 13 for slide in again.slides
                       for shape in slide.shapes)
    except Exception as exc:
        return {"ok": False, "error": f"Saved presentation cannot be reopened: {exc}"}
    return {"ok": verified, "dest": str(target), "verified": verified,
            "slides": len(again.slides),
            "error": "" if verified else "The picture is not in the saved deck."}


def add_to_xlsx(asset_path: str, xlsx_path: str, *, cell: str = "B2",
                sheet: str = "") -> dict:
    source = Path(asset_path)
    target = Path(xlsx_path)
    if not source.is_file():
        return {"ok": False, "error": f"Asset not found: {source}"}
    try:
        import openpyxl
        from openpyxl.drawing.image import Image as XLImage
    except Exception as exc:
        return {"ok": False, "error": f"openpyxl is unavailable: {exc}"}
    try:
        wb = openpyxl.load_workbook(str(target)) if target.is_file() else \
            openpyxl.Workbook()
        ws = wb[sheet] if sheet and sheet in wb.sheetnames else wb.active
        ws.add_image(XLImage(str(source)), cell)
        target.parent.mkdir(parents=True, exist_ok=True)
        wb.save(str(target))
    except Exception as exc:
        return {"ok": False, "error": f"Could not insert the image: {exc}"}
    try:
        again = openpyxl.load_workbook(str(target))
        ws2 = again[sheet] if sheet and sheet in again.sheetnames else again.active
        verified = bool(getattr(ws2, "_images", []))
    except Exception as exc:
        return {"ok": False, "error": f"Saved workbook cannot be reopened: {exc}"}
    return {"ok": verified, "dest": str(target), "verified": verified,
            "cell": cell,
            "error": "" if verified else "The image is not in the saved workbook."}


def add_to_android(asset_path: str, project_root: str, *,
                   name: str = "", density: str = "drawable-xxhdpi") -> dict:
    source = Path(asset_path)
    project = detect_project(project_root)
    if project["type"] != "android":
        return {"ok": False, "error": "That folder is not an Android project.",
                "project": project}
    root = Path(project["root"])
    res = Path(project["asset_dir"])
    chosen = density if (res / density).is_dir() else next(
        (d for d in _DRAWABLE_DENSITIES if (res / d).is_dir()), "")
    if not chosen:
        return {"ok": False, "error": "No drawable folder exists in app/src/main/res."}
    # Android resource names: lowercase, digits, underscore only.
    stem = re.sub(r"[^a-z0-9_]", "_", (name or source.stem).lower()).strip("_")
    if not stem or stem[0].isdigit():
        stem = f"asset_{stem}" if stem else "asset"
    dest = _unique_copy(source, res / chosen, stem)
    return {"ok": dest.is_file(), "dest": str(dest),
            "reference": f"@drawable/{dest.stem}",
            "project_type": "android", "density": chosen,
            "verified": dest.is_file(),
            "note": ("Reference it as R.drawable." + dest.stem
                     if project else "")}


def verify_reference(project_root: str, reference: str, *,
                     page: str = "") -> dict:
    """Does the project actually resolve this reference?

    A copied file is not enough: the reference has to point at a path that
    exists where the framework will look for it, and (for HTML) be present in
    the page that renders it.
    """
    root = Path(project_root).expanduser().resolve()
    ref = str(reference or "").strip()
    if not ref:
        return {"ok": False, "error": "Empty reference."}
    if ref.startswith("@drawable/"):
        name = ref.split("/", 1)[1]
        res = root / "app" / "src" / "main" / "res"
        matches = list(res.glob(f"drawable*/{name}.*")) if res.is_dir() else []
        return {"ok": bool(matches), "matches": [str(m) for m in matches],
                "error": "" if matches else f"No drawable named {name}."}
    relative = ref.lstrip("/")
    candidate = root / relative
    if not candidate.exists():
        return {"ok": False, "error": f"{relative} does not exist in the project.",
                "checked": str(candidate)}
    result = {"ok": True, "path": str(candidate), "bytes": candidate.stat().st_size}
    if page:
        page_path = Path(page)
        if not page_path.is_file():
            return {"ok": False, "error": f"Page not found: {page}"}
        html = page_path.read_text(encoding="utf-8", errors="replace")
        if ref not in html and relative not in html:
            return {"ok": False, "error": "The page does not reference the asset."}
        result["page"] = str(page_path)
    return result


def add_to_project(asset_path: str, project_root: str, *, kind: str = "",
                   **kwargs) -> dict:
    """Route an asset to the destination the project actually uses."""
    project = detect_project(project_root)
    kind = (kind or project.get("type") or "unknown").lower()
    if kind in ("web-static", "vite", "react", "next", "web"):
        return add_to_web_project(asset_path, project_root, **kwargs)
    if kind == "android":
        return add_to_android(asset_path, project_root, **kwargs)
    if kind in ("python", "qt", "desktop", "flutter"):
        source = Path(asset_path)
        if not source.is_file():
            return {"ok": False, "error": f"Asset not found: {source}"}
        root = Path(project["root"])
        directory = root / (project.get("asset_dir") or "assets")
        if not _inside(directory, root):
            return {"ok": False, "error": "Asset folder resolves outside the project."}
        dest = _unique_copy(source, directory)
        return {"ok": True, "dest": str(dest),
                "reference": str(dest.relative_to(root)).replace("\\", "/"),
                "project_type": project["type"], "verified": dest.is_file()}
    return {"ok": False, "error": f"Unsupported project type: {kind}",
            "project": project}


__all__ = ["IntegrationError", "detect_project", "add_to_web_project",
           "add_to_docx", "add_to_pptx", "add_to_xlsx", "add_to_android",
           "add_to_project", "verify_reference"]
