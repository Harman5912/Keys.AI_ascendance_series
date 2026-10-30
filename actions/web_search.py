#web_search.py
import json
import re
import sys
from pathlib import Path

def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = _get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def _get_api_key() -> str:
    """The configured Gemini key, through the app's config layer.

    Reads used to go straight to api_keys.json, which bypassed the merge/atomic
    path and raised KeyError when no Gemini key was stored at all.
    """
    try:
        from core.api_config import get_api_key
        return get_api_key("gemini") or ""
    except Exception:
        try:
            with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f).get("gemini_api_key", "")
        except Exception:
            return ""


def _gemini_model() -> str:
    """The catalog's Gemini model, not a literal baked into this file."""
    try:
        from core.model_catalog import default_model_for
        return default_model_for("gemini") or "gemini-2.5-flash"
    except Exception:
        return "gemini-2.5-flash"


def _gemini_search(query: str) -> str:
    """Grounded search — Google Search grounding is a Gemini-only capability.

    Plain text completion goes through core.llm_client (and therefore the
    user's provider choice); this stays on Gemini on purpose, because no other
    configured provider can attach Google Search results to the answer. When no
    Gemini key exists the caller's DuckDuckGo path is used instead.
    """
    from google import genai

    key = _get_api_key()
    if not key:
        raise RuntimeError("no gemini_api_key configured")
    client   = genai.Client(api_key=key)
    response = client.models.generate_content(
        model=_gemini_model(),
        contents=query,
        config={"tools": [{"google_search": {}}]},
    )

    text = ""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            text += part.text

    text = text.strip()
    if not text:
        raise ValueError("Gemini returned an empty response.")
    return text


def _ddg_search(query: str, max_results: int = 6) -> list[dict]:
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append({
                "title":   r.get("title",  ""),
                "snippet": r.get("body",   ""),
                "url":     r.get("href",   ""),
            })
    return results


def _bing_rss(query: str, max_results: int = 6) -> list[dict]:
    """Keyless fallback: Bing's RSS output.

    DuckDuckGo rate-limits this machine's IP (empty results, HTTP 403), and a
    Gemini daily quota can be exhausted. Bing's RSS endpoint needs no key and
    no HTML parsing, so a search still returns real results when both of the
    other backends are unavailable.
    """
    import urllib.parse
    import urllib.request
    import xml.etree.ElementTree as ET

    url = ("https://www.bing.com/search?q="
           + urllib.parse.quote(query or "") + "&format=rss")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/rss+xml, application/xml;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=12) as resp:  # noqa: S310
        xml = resp.read().decode("utf-8", "replace")
    root = ET.fromstring(xml)
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = re.sub(r"<[^>]+>", "", item.findtext("description") or "").strip()
        if title or desc:
            out.append({"title": title, "snippet": desc, "url": link})
        if len(out) >= max_results:
            break
    return out


def _web_results(query: str, max_results: int = 6) -> list[dict]:
    """Real search results from whichever keyless backend answers.

    Order: DuckDuckGo (best snippets) → Bing RSS (reliable when DDG throttles).
    """
    try:
        results = _ddg_search(query, max_results=max_results)
        if results:
            return results
    except Exception as e:
        print(f"[WebSearch] ⚠️ DDG text failed ({e})")
    try:
        results = _bing_rss(query, max_results=max_results)
        if results:
            return results
    except Exception as e:
        print(f"[WebSearch] ⚠️ Bing RSS failed ({e})")
    return []


def _ddg_news(query: str, max_results: int = 8) -> list[dict]:
    """DDG news search — returns actual articles, not website homepages."""
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.news(query, max_results=max_results):
                results.append({
                    "title":   r.get("title",  ""),
                    "snippet": r.get("body",   ""),
                    "url":     r.get("url",    ""),
                    "source":  r.get("source", ""),
                })
    except Exception as e:
        print(f"[WebSearch] ⚠️ DDG news() failed ({e}) — falling back to text search")
        results = _ddg_search(query, max_results=max_results)
    return results


def _format_ddg(query: str, results: list[dict]) -> str:
    if not results:
        return f"No results found for: {query}"

    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        if r.get("title"):   lines.append(f"{i}. {r['title']}")
        if r.get("snippet"): lines.append(f"   {r['snippet']}")
        if r.get("url"):     lines.append(f"   Source: {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_news(query: str, results: list[dict]) -> str:
    if not results:
        return f"No news found for: {query}"

    lines = [f"Latest news: {query}\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        if not title:
            continue
        src = f"  [{r['source']}]" if r.get("source") else ""
        lines.append(f"{i}. {title}{src}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet'][:140]}")
        if r.get("url"):
            lines.append(f"   {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


# ── Briefing helper ────────────────────────────────────────────────────────────

def _gemini_headlines(n: int = 5) -> tuple[list[str], str]:
    """
    Fetches current headlines via Gemini grounded search.
    Optimised for speed: minimal prompt + strict token cap.
    Returns (headline_list, raw_text_for_display).
    """
    import re
    from google import genai

    client = genai.Client(api_key=_get_api_key())
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"Current world news: {n} headlines. Numbered list, titles only.",
        config={"tools": [{"google_search": {}}]},
    )

    raw = ""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            raw += part.text

    headlines = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Only accept lines that begin with a number — skips preamble/closing sentences
        if not re.match(r'^[\d]+[.\)\-]', line):
            continue
        clean = re.sub(r'^[\d]+[.\)\-]\s*', '', line)
        clean = re.sub(r'^\*+\s*',          '', clean).strip()
        if clean and len(clean) > 10:
            headlines.append(clean)

    return headlines[:n], raw.strip()


# ── Modes ──────────────────────────────────────────────────────────────────────

def _bounded(fn, seconds: float):
    """Run fn() but stop waiting after `seconds`.

    Grounded Gemini answers are the best results, but a slow grounding pass
    used to hang the whole search for 25-45 s before the DDG fallback was even
    tried. The caller now gets the fallback on time; the abandoned request is
    a daemon thread and cannot hold the process open.
    """
    import threading

    box: dict = {}

    def run():
        try:
            box["result"] = fn()
        except Exception as e:  # noqa: BLE001 - surfaced by the caller
            box["error"] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    if box.get("result"):
        return box["result"]
    if box.get("error"):
        raise box["error"]
    raise TimeoutError(f"search backend exceeded {seconds:.0f}s")


def _search(query: str) -> str:
    """Default search — Gemini grounded, bounded so DDG can answer in time."""
    try:
        return _bounded(lambda: _gemini_search(query), 12.0)
    except Exception as e:
        print(f"[WebSearch] ⚠️ Gemini failed/bounded ({e}) — trying DDG/Bing...")
        results = _web_results(query)
        if not results:
            # One retry with a shorter query often clears a transient throttle.
            short = " ".join((query or "").split()[:6])
            results = _web_results(short) if short != query else []
        return _format_ddg(query, results)


def _news(query: str) -> str:
    """
    Runs Gemini grounded search AND DDG news in parallel.
    Returns whichever delivers a valid result first; cancels the other.
    """
    import threading

    gemini_query = f"latest news today: {query}" if query else "top world news today"
    ddg_query    = query if query else "world news today"

    result_box  = [None]   # first valid result lands here
    lock        = threading.Lock()
    done_evt    = threading.Event()
    failures    = [0]

    def _store(r: str) -> None:
        if r and len(r) > 60:
            with lock:
                if result_box[0] is None:
                    result_box[0] = r
            done_evt.set()
        else:
            with lock:
                failures[0] += 1
                if failures[0] >= 2:   # both failed — unblock caller
                    done_evt.set()

    def _try_gemini():
        try:
            _store(_gemini_search(gemini_query))
        except Exception as e:
            print(f"[WebSearch] ⚠️ Gemini news failed ({e})")
            _store("")

    def _try_ddg():
        try:
            results = _ddg_news(ddg_query, max_results=8)
            _store(_format_news(ddg_query, results))
        except Exception as e:
            print(f"[WebSearch] ⚠️ DDG news failed ({e})")
            _store("")

    threading.Thread(target=_try_gemini, daemon=True).start()
    threading.Thread(target=_try_ddg,    daemon=True).start()

    done_evt.wait(timeout=10.0)
    if result_box[0] is None:
        # Gemini grounding was still mid-flight at 10 s — give it a short grace
        # period instead of returning an empty news list.
        done_evt.wait(timeout=8.0)
    if result_box[0] is None:
        # Last resort: plain text results beat "no news found".
        try:
            results = _web_results(ddg_query, max_results=8)
            if results:
                return _format_ddg(ddg_query, results)
        except Exception as e:
            print(f"[WebSearch] ⚠️ last-resort news search failed ({e})")
    return result_box[0] or f"No news found for: {query}"


def _research(query: str) -> str:
    """
    Deep dive — asks Gemini for a comprehensive answer with context.
    Falls back to a wider DDG fetch.
    """
    research_query = (
        f"Comprehensive, detailed explanation of: {query}. "
        "Include background context, key facts, current state, and important nuances."
    )
    try:
        return _bounded(lambda: _gemini_search(research_query), 25.0)
    except Exception as e:
        print(f"[WebSearch] ⚠️ Research Gemini failed ({e}) — DDG/Bing fallback...")
        results = _web_results(query, max_results=10)
        return _format_ddg(query, results)


def _price(query: str) -> str:
    """Product price lookup — searches for current market prices."""
    price_query = f"current price of {query} — how much does it cost today"
    try:
        return _bounded(lambda: _gemini_search(price_query), 12.0)
    except Exception as e:
        print(f"[WebSearch] ⚠️ Price Gemini failed ({e}) — DDG/Bing fallback...")
        results = _web_results(f"{query} price buy", max_results=6)
        return _format_ddg(query, results)


def _compare(items: list[str], aspect: str) -> str:
    query = (
        f"Compare {', '.join(items)} in terms of {aspect}. "
        "Give specific facts and data."
    )
    try:
        return _bounded(lambda: _gemini_search(query), 22.0)
    except Exception as e:
        print(f"[WebSearch] ⚠️ Gemini compare failed: {e} — falling back to DDG")

    all_results: dict[str, list] = {}
    for item in items:
        try:
            all_results[item] = _web_results(f"{item} {aspect}", max_results=3)
        except Exception:
            all_results[item] = []

    lines = [f"Comparison — {aspect.upper()}", "─" * 40]
    for item in items:
        lines.append(f"\n▸ {item}")
        for r in all_results.get(item, [])[:2]:
            if r.get("snippet"):
                lines.append(f"  • {r['snippet']}")
            if r.get("url"):
                lines.append(f"    {r['url']}")
    return "\n".join(lines)


# ── Public entry point ─────────────────────────────────────────────────────────

def web_search(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    query  = params.get("query", "").strip()
    mode   = params.get("mode",  "search").lower().strip()
    items  = params.get("items", [])
    aspect = params.get("aspect", "general").strip() or "general"

    if not query and not items:
        return "Please provide a search query."

    if items and mode not in ("compare",):
        mode = "compare"

    if player:
        player.write_log(f"[Search:{mode}] {query or ', '.join(items)}")

    print(f"[WebSearch] 🔍 mode={mode!r}  query={query!r}")

    try:
        if mode == "compare" and items:
            return _compare(items, aspect)
        if mode == "news":
            return _news(query)
        if mode == "research":
            return _research(query)
        if mode == "price":
            return _price(query)
        return _search(query)

    except Exception as e:
        print(f"[WebSearch] ❌ All backends failed: {e}")
        return f"Search failed: {e}"
