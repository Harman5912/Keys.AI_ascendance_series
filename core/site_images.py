"""Real, licensed imagery for generated pages — offline-safe and cached.

The page renderers are deliberately offline: a build must not depend on a
network call. A photography or product site with no photographs is not
finished either, so imagery is fetched as an *optional enrichment*:

    * Wikimedia Commons is searched for Creative Commons photos (no API key);
    * failures fall back to Lorem Picsum's fixed photo set;
    * images are downloaded into ``<workspace>/assets/`` and normalised to JPEG,
      so the finished page works with no network afterwards;
    * anything that fails (offline, rate limit, odd format) returns ``[]`` and
      the page renders exactly as it did before this module existed.

Nothing here raises. A build must never fail because a photo did not arrive.
"""

from __future__ import annotations

import html
import io
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

COMMONS = "https://commons.wikimedia.org/w/api.php"
PICSUM = "https://picsum.photos/id/{id}/1400/1000"
PICSUM_IDS = (1005, 1011, 1015, 1025, 1035, 1039, 1043, 1050, 1060, 1062)
UA = "KeysAI-site-builder/1.0"
MAX_BYTES = 5_000_000
MAX_EDGE = 1600
CACHE = "images.json"


def _get(url: str, timeout: float = 10.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json,image/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read()


def _clean(value: str) -> str:
    """Strip the HTML that Commons returns inside metadata values."""
    text = re.sub(r"<[^>]+>", " ", value or "")
    return " ".join(html.unescape(text).split())[:160]


def search(query: str, count: int = 6, timeout: float = 10.0) -> list[dict]:
    """CC-photo candidates for ``query`` (``[]`` when the network is down)."""
    params = urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}"[:240], "gsrnamespace": "6",
        "gsrlimit": str(max(1, min(count * 3, 24))), "prop": "imageinfo",
        "iiprop": "url|extmetadata", "iiurlwidth": str(MAX_EDGE),
    })
    try:
        data = json.loads(_get(f"{COMMONS}?{params}", timeout=timeout).decode("utf-8"))
    except Exception:
        return []
    results = []
    for page in (data.get("query", {}).get("pages") or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url") or ""
        if not url.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png")):
            continue
        meta = info.get("extmetadata") or {}
        title = _clean((meta.get("ImageDescription") or {}).get("value") or page.get("title", ""))
        title = re.sub(r"^File:\s*", "", title)
        results.append({
            "url": url,
            "title": title or query,
            "creator": _clean((meta.get("Artist") or {}).get("value") or ""),
            "license": _clean((meta.get("LicenseShortName") or {}).get("value") or "CC"),
            "source": info.get("descriptionurl") or "",
        })
    return results


def _save_jpeg(raw: bytes, dest: Path) -> bool:
    """Store as a reasonably sized JPEG; reject anything that is not an image."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw))
        img.load()
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        if max(img.size) > MAX_EDGE:
            scale = MAX_EDGE / max(img.size)
            img = img.resize((max(1, int(img.width * scale)),
                              max(1, int(img.height * scale))), Image.LANCZOS)
        img.save(dest, "JPEG", quality=82, optimize=True, progressive=True)
        return dest.stat().st_size > 4000
    except Exception:
        return False


def fetch_for(query: str, workspace: Path, count: int = 6,
              timeout: float = 10.0) -> list[dict]:
    """Download photos for ``query`` into ``workspace/assets``.

    Returns ``[{path, alt, credit, source}]`` — ``path`` is relative to the
    workspace, ready to be used as an ``<img src>``. ``[]`` when unavailable.
    """
    assets = Path(workspace) / "assets"
    try:
        cached = json.loads((assets / CACHE).read_text(encoding="utf-8"))
        if cached and all((assets / item["file"]).exists() for item in cached):
            return cached
    except Exception:
        pass

    try:
        assets.mkdir(parents=True, exist_ok=True)
    except Exception:
        return []

    candidates = search(query, count=count, timeout=timeout)
    if not candidates:
        candidates = [{"url": PICSUM.format(id=i), "title": "Photograph",
                       "creator": "Lorem Picsum", "license": "Unsplash License",
                       "source": "https://picsum.photos"}
                      for i in PICSUM_IDS[:count]]

    got: list[dict] = []
    for result in candidates:
        if len(got) >= count:
            break
        name = f"photo{len(got) + 1}.jpg"
        try:
            raw = _get(result["url"], timeout=max(8.0, timeout))
        except Exception:
            continue
        if not raw or len(raw) > MAX_BYTES:
            continue
        if not _save_jpeg(raw, assets / name):
            continue
        got.append({
            "file": name,
            "path": f"assets/{name}",
            "alt": (result["title"] or query)[:120],
            "credit": " · ".join(x for x in (result["creator"], result["license"]) if x),
            "source": result["source"],
        })

    if got:
        try:
            (assets / CACHE).write_text(json.dumps(got, indent=2), encoding="utf-8")
        except Exception:
            pass
    return got


def photo_query(brief: str, plan: dict | None = None) -> str:
    """A search phrase that finds photos fitting the brief."""
    text = f"{brief or ''} {json.dumps(plan or {})}".lower()
    for word, phrase in (
        ("photograph", "portrait photography"),
        ("interior", "modern interior design"),
        ("restaurant", "restaurant food"),
        ("hotel", "luxury hotel"),
        ("jewel", "jewellery"),
        ("fashion", "fashion editorial"),
        ("agency", "creative studio workspace"),
        ("architect", "modern architecture"),
        ("product", "product photography"),
        ("coffee", "specialty coffee"),
        ("fitness", "fitness training"),
        ("travel", "travel landscape"),
        ("music", "concert stage"),
        ("art", "art gallery"),
    ):
        if word in text:
            return phrase
    words = [w for w in (brief or "").split() if len(w) > 3][:6]
    return " ".join(words) or "abstract texture"


__all__ = ["search", "fetch_for", "photo_query"]
