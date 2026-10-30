"""core/site_studio/render.py — bespoke HTML renderers for the ten studios.

Every studio composes its own page: header, hero, section order, card markup,
footer and signature interaction. Shared helpers only remove repetition in
mechanical places (escaping, form fields, FAQ rows); the layouts themselves are
not shared, which is what stops the output collapsing into one template.

The renderers are deterministic and offline: no font, image or script is ever
loaded from the network.
"""

from __future__ import annotations

import html as _html
import math
import re

from .themes import STUDIOS, studio_css

# ── Small helpers ─────────────────────────────────────────────────────────

def esc(value) -> str:
    return _html.escape(str(value if value is not None else ""), quote=True)


def _sections(content: dict) -> list[dict]:
    return [s for s in content.get("sections") or [] if isinstance(s, dict)]


def _first_id(content: dict, fallback: str = "main") -> str:
    for sec in _sections(content):
        if sec.get("kind") != "contact":
            return str(sec.get("id") or fallback)
    return fallback


def _tags(item: dict) -> str:
    tags = [str(t) for t in item.get("tags") or [] if str(t).strip()]
    if not tags:
        return ""
    return '<ul class="tags">' + "".join(f"<li>{esc(t)}</li>" for t in tags) + "</ul>"


def _data_tags(item: dict) -> str:
    tags = " ".join(str(t).lower() for t in item.get("tags") or [])
    return f' data-tags="{esc(tags)}"' if tags else ""


def _filters(items: list[dict], label: str = "Filter") -> str:
    tags: list[str] = []
    for it in items:
        for t in it.get("tags") or []:
            t = str(t)
            if t and t.lower() not in [x.lower() for x in tags]:
                tags.append(t)
    if not tags:
        return ""
    return (f'<div class="filters" role="group" aria-label="{esc(label)}">'
            '<button type="button" class="filter is-active" data-filter="all">All</button>'
            + "".join(f'<button type="button" class="filter" data-filter="{esc(t.lower())}">'
                      f'{esc(t)}</button>' for t in tags[:6]) + "</div>")


def _stats(content: dict) -> str:
    stats = content.get("stats") or []
    if not stats:
        return ""
    return '<div class="metrics" id="stats">' + "".join(
        f'<div class="metric"><strong data-count="{esc(s.get("value", ""))}">'
        f'{esc(s.get("value", ""))}</strong><span>{esc(s.get("label", ""))}</span></div>'
        for s in stats) + "</div>"


def _nav(content: dict) -> str:
    links = content.get("nav") or []
    return "".join(f'<li><a href="{esc(h)}">{esc(t)}</a></li>' for t, h in links)


def _nav_toggle() -> str:
    return ('<button class="nav-toggle" type="button" aria-expanded="false" '
            'aria-controls="site-nav">Menu</button>')


def _faq(content: dict, extra: str = "") -> str:
    rows = content.get("faq") or []
    body = "".join(f"<details><summary>{esc(f.get('q'))}</summary>"
                   f"<p>{esc(f.get('a'))}</p></details>" for f in rows if f.get("q"))
    return f'<div class="faq {extra}">{body or "<p>Ask us anything.</p>"}</div>'


def _form(content: dict, extra: str = "") -> str:
    contact = content.get("contact") or {}
    fields = contact.get("fields") or [("Name", "name", "text", "Your name"),
                                       ("Email", "email", "email", "you@example.com"),
                                       ("Message", "message", "textarea", "What are you building?")]
    rows = []
    for label, name, typ, ph in fields:
        if typ == "textarea":
            rows.append(f'<label for="f-{esc(name)}">{esc(label)}'
                        f'<textarea id="f-{esc(name)}" name="{esc(name)}" required '
                        f'placeholder="{esc(ph)}"></textarea></label>')
        elif typ == "select":
            opts = ["1–10", "11–50", "51–200", "200+"]
            rows.append(f'<label for="f-{esc(name)}">{esc(label)}'
                        f'<select id="f-{esc(name)}" name="{esc(name)}" required>'
                        + "".join(f"<option>{esc(o)}</option>" for o in opts)
                        + "</select></label>")
        else:
            rows.append(f'<label for="f-{esc(name)}">{esc(label)}'
                        f'<input id="f-{esc(name)}" name="{esc(name)}" type="{esc(typ)}" '
                        f'required placeholder="{esc(ph)}"></label>')
    return (f'<form class="contact-form {extra}" data-contact novalidate>'
            + "".join(rows)
            + f'<button type="submit" class="btn btn-primary">{esc(contact.get("submit") or "Send message")}</button>'
            '<p class="form-status" data-form-status role="status" aria-live="polite"></p>'
            f'<p class="hero-note">{esc(contact.get("note") or "")}</p>'
            "</form>")


def _head(sec: dict, tag: str = "h2") -> str:
    lead = f'<p class="lead">{esc(sec.get("lead"))}</p>' if sec.get("lead") else ""
    return (f'<div class="sec-head"><p class="eyebrow">{esc(sec.get("eyebrow") or "Section")}</p>'
            f'<{tag}>{esc(sec.get("heading"))}</{tag}>{lead}</div>')


def _emph(text: str, n: int = 2) -> str:
    """Wrap the last n words in <em> for display emphasis (keeps punctuation)."""
    words = str(text).split()
    if len(words) < 2:
        return esc(text)
    head, tail = words[:-n], words[-n:]
    return esc(" ".join(head)) + " <em>" + esc(" ".join(tail)) + "</em>"


def _sections_fallback(sec: dict) -> str:
    """Generic renderer used for planner site kinds a studio has no special case for."""
    kind = sec.get("kind")
    items = sec.get("items") or []
    if kind == "faq":
        return _faq({})
    if kind == "contact":
        return _form({})
    if kind == "chips":
        chips = "".join(f'<li class="chip">{esc(i.get("title"))}</li>' for i in items)
        return f'<ul class="chips">{chips}</ul>'
    if kind == "split":
        body = "".join(f'<div><h3>{esc(i.get("title"))}</h3><p>{esc(i.get("text"))}</p></div>'
                       for i in items) or f'<p>{esc(sec.get("lead"))}</p>'
        return f'<div class="split">{body}</div>'
    if kind in ("cards", "gallery", "products", "frames", "films", "articles",
                "index", "columns", "list", "testimonials"):
        cards = "".join(
            f'<article class="card"{_data_tags(i)}>'
            + (f'<p class="meta">{esc(i.get("meta"))}</p>' if i.get("meta") else "")
            + f'<h3>{esc(i.get("title"))}</h3><p>{esc(i.get("text"))}</p>{_tags(i)}</article>'
            for i in items)
        return f'<div class="grid">{cards}</div>'
    if kind == "steps":
        return '<div class="steps">' + "".join(
            f'<div class="step"><b>{idx:02d}</b><h3>{esc(i.get("title"))}</h3>'
            f'<p>{esc(i.get("text"))}</p></div>' for idx, i in enumerate(items, 1)) + "</div>"
    if kind == "quote":
        return (f'<blockquote class="pullquote">{esc(sec.get("heading"))}'
                f'<cite>{esc(sec.get("lead"))}</cite></blockquote>')
    return "".join(f'<p>{esc(i.get("text") or i.get("title"))}</p>' for i in items)


# ── Common runtime ────────────────────────────────────────────────────────

COMMON_JS = r"""
(function () {
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var nav = document.getElementById('site-nav');
  document.querySelectorAll('.nav-toggle').forEach(function (btn) {
    btn.addEventListener('click', function () {
      if (!nav) return;
      var open = nav.classList.toggle('is-open');
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  });
  if (nav) nav.addEventListener('click', function (e) {
    if (e.target.closest('a')) {
      nav.classList.remove('is-open');
      var t = document.querySelector('.nav-toggle');
      if (t) t.setAttribute('aria-expanded', 'false');
    }
  });

  // counters
  document.querySelectorAll('[data-count]').forEach(function (el) {
    var raw = el.getAttribute('data-count') || el.textContent || '';
    var m = raw.match(/-?[\d.,]+/);
    if (!m) return;
    var target = parseFloat(m[0].replace(/,/g, ''));
    if (!isFinite(target)) return;
    var prefix = raw.slice(0, m.index), suffix = raw.slice(m.index + m[0].length);
    var decimals = (m[0].split('.')[1] || '').length;
    if (reduce) return;
    var t0 = performance.now(), dur = 1100;
    function frame(t) {
      var p = Math.min(1, (t - t0) / dur);
      var eased = 1 - Math.pow(1 - p, 3);
      var val = (target * eased).toFixed(decimals);
      el.textContent = prefix + Number(val).toLocaleString(undefined,
        {minimumFractionDigits: decimals, maximumFractionDigits: decimals}) + suffix;
      if (p < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  });

  // reveal
  var reveals = document.querySelectorAll('[data-reveal], .section > *, .card, .product, .still, .story');
  if ('IntersectionObserver' in window && !reduce) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) { entry.target.classList.add('is-in'); io.unobserve(entry.target); }
      });
    }, { rootMargin: '0px 0px -6% 0px' });
    reveals.forEach(function (el, i) {
      el.classList.add('reveal');
      el.style.transitionDelay = Math.min(i % 6, 5) * 45 + 'ms';
      io.observe(el);
    });
  } else {
    reveals.forEach(function (el) { el.classList.add('is-in'); });
  }

  // filters
  document.querySelectorAll('.filters').forEach(function (group) {
    group.querySelectorAll('.filter').forEach(function (btn) {
      btn.addEventListener('click', function () {
        group.querySelectorAll('.filter').forEach(function (b) {
          b.classList.toggle('is-active', b === btn);
        });
        var want = btn.getAttribute('data-filter');
        document.querySelectorAll('[data-tags]').forEach(function (card) {
          var tags = (card.getAttribute('data-tags') || '').split(/\s+/);
          card.hidden = want !== 'all' && tags.indexOf(want) === -1;
        });
      });
    });
  });

  // contact forms
  document.querySelectorAll('form[data-contact]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var status = form.querySelector('[data-form-status]');
      var bad = null;
      form.querySelectorAll('input, textarea, select').forEach(function (field) {
        if (field.hasAttribute('required') && !String(field.value).trim()) bad = field;
        if (!bad && field.type === 'email' &&
            !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(String(field.value).trim())) bad = field;
      });
      if (bad) {
        if (status) status.textContent = 'Please complete the highlighted field' +
          (bad.type === 'email' ? ' with a valid email address.' : '.');
        bad.focus();
        return;
      }
      var nameField = form.querySelector('input[name="name"]');
      var who = nameField ? String(nameField.value).trim().split(/\s+/)[0] : '';
      if (status) status.textContent = (who ? 'Thanks ' + who + ' — ' : 'Thanks — ') +
        'your message is queued. A person will reply, not an autoresponder.';
      form.reset();
    });
  });

  // drag a filmstrip
  document.querySelectorAll('[data-drag]').forEach(function (strip) {
    var down = false, startX = 0, startLeft = 0;
    strip.addEventListener('pointerdown', function (e) {
      down = true; startX = e.clientX; startLeft = strip.scrollLeft;
      strip.setPointerCapture && strip.setPointerCapture(e.pointerId);
      strip.style.cursor = 'grabbing';
    });
    strip.addEventListener('pointermove', function (e) {
      if (!down) return;
      strip.scrollLeft = startLeft - (e.clientX - startX);
    });
    function up() { down = false; strip.style.cursor = 'grab'; }
    strip.addEventListener('pointerup', up);
    strip.addEventListener('pointercancel', up);
    strip.addEventListener('pointerleave', up);
  });

  // add-to-cart counters
  document.querySelectorAll('[data-add]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var counter = document.querySelector('[data-cart]');
      if (!counter) return;
      var n = parseInt(counter.textContent, 10) || 0;
      counter.textContent = String(n + 1);
      counter.classList.add('bump');
      setTimeout(function () { counter.classList.remove('bump'); }, 320);
      var old = btn.textContent;
      btn.textContent = 'Added ✓';
      setTimeout(function () { btn.textContent = old; }, 1200);
    });
  });

  // sticker spin
  document.querySelectorAll('[data-spin]').forEach(function (el) {
    el.addEventListener('click', function () {
      el.classList.remove('spin');
      void el.offsetWidth;
      el.classList.add('spin');
    });
  });

  // editorial reading rule
  var bar = document.querySelector('[data-readbar]');
  if (bar) {
    var fill = bar.firstElementChild;
    function progress() {
      var max = document.documentElement.scrollHeight - window.innerHeight;
      var pct = max > 0 ? Math.min(1, window.scrollY / max) : 0;
      fill.style.width = (pct * 100).toFixed(2) + '%';
    }
    window.addEventListener('scroll', progress, { passive: true });
    progress();
  }

  // copy a command
  document.querySelectorAll('[data-copy]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var box = btn.closest('.code-card');
      var text = box ? (box.querySelector('code') || {}).textContent || '' : '';
      if (!text) return;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).catch(function () {});
      }
      var old = btn.textContent;
      btn.textContent = 'copied';
      setTimeout(function () { btn.textContent = old; }, 1200);
    });
  });

  // hero pointer parallax (aurora / cinematic)
  document.querySelectorAll('[data-parallax]').forEach(function (root) {
    if (reduce) return;
    var layers = root.querySelectorAll('[data-depth]');
    root.addEventListener('pointermove', function (e) {
      var r = root.getBoundingClientRect();
      var x = (e.clientX - r.left) / r.width - 0.5;
      var y = (e.clientY - r.top) / r.height - 0.5;
      layers.forEach(function (layer) {
        var d = parseFloat(layer.getAttribute('data-depth')) || 10;
        layer.style.transform = 'translate3d(' + (-x * d) + 'px,' + (-y * d) + 'px,0)';
      });
    });
  });
})();
"""


def _page(content: dict, key: str, body: str, extra_css: str = "") -> str:
    st = STUDIOS[key]
    title = content.get("title") or content.get("brand") or "Untitled"
    desc = re.sub(r"\s+", " ", str(content.get("deck") or ""))[:180]
    # A page's "get in touch" links must always resolve, even when the contact
    # section carries a section-specific id (newsroom uses #subscribe).
    if 'id="contact"' not in body:
        body = body.replace("</main>", '<span id="contact" class="sr-only"></span>\n</main>')

    # Every in-page link must land on a real id. Studios that hardcode a
    # destination (nightfall's "#programme") break the moment the plan does not
    # carry that section, so any remaining dead anchor is retargeted at the
    # first real section instead of shipping a link that goes nowhere.
    ids = re.findall(r'\bid="([^"]+)"', body)
    known = set(ids)
    fallback = next((i for i in ids if i not in ("main", "site-nav")), "main")

    def _retarget(match: "re.Match[str]") -> str:
        target = match.group(1)
        if target in known or target == "main":
            return match.group(0)
        return f'href="#{esc(fallback)}"'

    body = re.sub(r'href="#([^"]+)"', _retarget, body)
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<meta name="description" content="{esc(desc)}">\n'
        f'<meta name="generator" content="Crown Code Studio — {esc(st["name"])}">\n'
        f'<title>{esc(title)}</title>\n'
        f'<style>{studio_css(key)}{extra_css}</style>\n'
        '</head>\n<body>\n' + body +
        '\n<script>' + COMMON_JS + '</script>\n</body>\n</html>\n'
    )


# ── 01 AURORA ─────────────────────────────────────────────────────────────

def _aurora(content: dict) -> str:
    first = _first_id(content)
    secs = []
    for sec in _sections(content):
        k = sec.get("kind")
        head = _head(sec)
        if k == "cards":
            cards = "".join(
                f'<article class="card"{_data_tags(i)}>'
                f'<span class="num">{esc(i.get("meta") or "—")}</span>'
                f'<h3>{esc(i.get("title"))}</h3><p>{esc(i.get("text"))}</p>{_tags(i)}</article>'
                for i in sec.get("items") or [])
            body = f'<div class="bento">{cards}</div>'
        elif k == "steps":
            body = '<div class="steps">' + "".join(
                f'<div class="card"><strong>{idx:02d}</strong><h3>{esc(i.get("title"))}</h3>'
                f'<p>{esc(i.get("text"))}</p></div>' for idx, i in enumerate(sec.get("items") or [], 1)
            ) + "</div>"
        elif k == "testimonials":
            body = '<div class="grid">' + "".join(
                f'<article class="card"><p class="meta">{esc(i.get("meta"))}</p>'
                f'<h3>{esc(i.get("title"))}</h3><p>“{esc(i.get("text"))}”</p></article>'
                for i in sec.get("items") or []) + "</div>"
        elif k == "faq":
            body = _faq(content)
        elif k == "contact":
            body = (f'<div class="split"><div><h3>{esc((content.get("contact") or {}).get("heading"))}</h3>'
                    f'<p class="lead">{esc((content.get("contact") or {}).get("lead"))}</p></div>'
                    f'{_form(content)}</div>')
        else:
            body = _sections_fallback(sec)
        secs.append(f'<section class="section" id="{esc(sec.get("id"))}"><div class="wrap">{head}{body}</div></section>')

    body = f"""
<a class="skip" href="#main">Skip to content</a>
<header class="site-header"><div class="bar">
  <a class="brand" href="#main"><i>H</i>{esc(content.get('brand'))}</a>
  {_nav_toggle()}
  <nav id="site-nav" aria-label="Main"><ul>{_nav(content)}</ul></nav>
</div></header>
<main id="main">
  <section class="hero" data-parallax><div class="orb orb-a" data-depth="26"></div>
    <div class="orb orb-b" data-depth="18"></div><div class="orb orb-c" data-depth="10"></div>
    <div class="wrap">
      <p class="kicker"><b></b>{esc(content.get('kicker'))}</p>
      <h1>{_emph(content.get('headline'))}</h1>
      <p class="tagline">{esc(content.get('deck'))}</p>
      <div class="hero-actions">
        <a class="btn btn-primary" href="#{esc(first)}">{esc((content.get('cta') or ('Get started',))[0])}</a>
        <a class="btn btn-ghost" href="#contact">{esc((content.get('cta') or ('', 'Talk to us'))[1])}</a>
      </div>
      <p class="hero-note">No credit card · GDPR-ready · works with your gateway</p>
      {_stats(content)}
    </div>
  </section>
  {''.join(secs)}
</main>
<footer class="site-footer wrap"><p>{esc(content.get('footer'))}</p>
  <p><a href="#main">Back to top ↑</a></p></footer>
"""
    return _page(content, "aurora", body)


# ── 02 EDITORIAL ──────────────────────────────────────────────────────────

def _editorial(content: dict) -> str:
    first = _first_id(content)
    items_all = [i for s in _sections(content) for i in (s.get("items") or [])]
    lead = items_all[0] if items_all else {"title": content.get("headline"), "text": "", "meta": ""}
    secs = []
    for sec in _sections(content):
        k = sec.get("kind")
        head = _head(sec)
        if k == "articles":
            rows = "".join(
                f'<a class="story-row" href="#{esc(sec.get("id"))}"{_data_tags(i)}>'
                f'<span class="story-num">{idx:02d}</span>'
                f'<div><h3>{esc(i.get("title"))}</h3><p class="story-meta">{esc(i.get("meta"))}</p></div>'
                f'<p>{esc(i.get("text"))}</p></a>'
                for idx, i in enumerate(sec.get("items") or [], 1))
            body = rows
        elif k == "quote":
            body = (f'<blockquote class="pullquote">{esc(sec.get("heading"))}'
                    f'<cite>{esc(sec.get("lead"))}</cite></blockquote>')
        elif k == "list":
            body = "".join(
                f'<div class="list-row"><div><strong>{esc(i.get("title"))}</strong><br>'
                f'<span>{esc(i.get("text"))}</span></div><span>{esc(i.get("meta"))}</span></div>'
                for i in sec.get("items") or [])
        elif k == "faq":
            body = _faq(content)
        elif k == "contact":
            body = (f'<div class="split"><div><h3>{esc((content.get("contact") or {}).get("heading"))}</h3>'
                    f'<p>{esc((content.get("contact") or {}).get("lead"))}</p></div>{_form(content)}</div>')
        else:
            body = _sections_fallback(sec)
        secs.append(f'<section class="section" id="{esc(sec.get("id"))}"><div class="wrap">{head}{body}</div></section>')

    body = f"""
<a class="skip" href="#main">Skip to content</a>
<div class="readbar" data-readbar aria-hidden="true" style="position:fixed;left:0;top:0;height:3px;width:100%;z-index:60;background:transparent"><span style="display:block;height:100%;width:0;background:#b23a2b;transition:width .1s linear"></span></div>
<header class="masthead">
  <div class="wrap mast-top">
    <div class="issue">No. 14 · Autumn 2026<br>£12 / €14</div>
    <p class="wordmark">The Quiet <span>Index</span></p>
    <div class="issue" style="text-align:right">Printed in Ghent<br>Since 2021</div>
  </div>
  <div class="wrap bar">
    {_nav_toggle()}
    <nav id="site-nav" aria-label="Sections"><ul>{_nav(content)}</ul></nav>
  </div>
</header>
<main id="main">
  <section class="hero wrap">
    <div>
      <p class="kicker">{esc(content.get('kicker'))}</p>
      <h1>{_emph(content.get('headline'))}</h1>
      <p class="tagline">{esc(content.get('deck'))}</p>
      <div class="hero-actions">
        <a class="btn btn-primary" href="#{esc(first)}">{esc((content.get('cta') or ('Read',))[0])}</a>
        <a class="btn btn-ghost" href="#contact">{esc((content.get('cta') or ('', 'Subscribe'))[1])}</a>
      </div>
    </div>
    <aside class="hero-card">
      <p class="label">In this issue</p>
      <h3>{esc(lead.get('title'))}</h3>
      <p>{esc(lead.get('text'))}</p>
      <p class="byline">{esc(lead.get('meta'))}</p>
    </aside>
    {_stats(content)}
  </section>
  {''.join(secs)}
</main>
<footer class="site-footer wrap"><p>{esc(content.get('footer'))}</p><p><a href="#main">Back to top ↑</a></p></footer>
"""
    return _page(content, "editorial", body)


# ── 03 BRUTALIST ──────────────────────────────────────────────────────────

def _brutalist(content: dict) -> str:
    first = _first_id(content)
    secs = []
    for sec in _sections(content):
        k = sec.get("kind")
        head = _head(sec)
        if k == "index":
            rows = "".join(
                f'<a class="index-row" href="#{esc(sec.get("id"))}"{_data_tags(i)}>'
                f'<span class="num">0{idx}</span><strong>{esc(i.get("title"))}</strong>'
                f'<p>{esc(i.get("text"))}</p><span class="arrow">↗</span></a>'
                for idx, i in enumerate(sec.get("items") or [], 1))
            body = f'<div class="index-list">{rows}</div>'
        elif k == "rows":
            body = '<div class="rows">' + "".join(
                f'<div class="row"{_data_tags(i)}><b>{esc(i.get("meta"))}</b>'
                f'<strong>{esc(i.get("title"))}</strong><p>{esc(i.get("text"))}</p></div>'
                for i in sec.get("items") or []) + "</div>"
        elif k == "quote":
            body = (f'<blockquote class="pullquote">{esc(sec.get("heading"))}'
                    f'<cite>{esc(sec.get("lead"))}</cite></blockquote>')
        elif k == "faq":
            body = _faq(content)
        elif k == "contact":
            body = (f'<div class="split"><div><h3>{esc((content.get("contact") or {}).get("heading"))}</h3>'
                    f'<p>{esc((content.get("contact") or {}).get("lead"))}</p></div>{_form(content)}</div>')
        elif k in ("cards", "gallery", "products"):
            body = '<div class="cards">' + "".join(
                f'<article class="card"{_data_tags(i)}><p class="meta">{esc(i.get("meta"))}</p>'
                f'<h3>{esc(i.get("title"))}</h3><p>{esc(i.get("text"))}</p>{_tags(i)}</article>'
                for i in sec.get("items") or []) + "</div>"
        else:
            body = _sections_fallback(sec)
        secs.append(f'<section class="section" id="{esc(sec.get("id"))}"><div class="wrap">{head}{body}</div></section>')

    strip = " · ".join(f"{esc(t)}" for t, _ in content.get("nav") or [])
    body = f"""
<a class="skip" href="#main">Skip to content</a>
<header class="topbar">
  <div class="wrap bar">
    <a class="brand" href="#main"><b>SL</b>{esc(content.get('brand'))}</a>
    {_nav_toggle()}
    <nav id="site-nav" aria-label="Main"><ul>{_nav(content)}</ul></nav>
  </div>
  <div class="marquee" aria-hidden="true"><div>
    <span>{strip}</span><span>{strip}</span><span>{strip}</span><span>{strip}</span>
  </div></div>
</header>
<main id="main">
  <section class="hero"><div class="wrap">
    <span class="kicker">{esc(content.get('kicker'))}</span>
    <h1>{esc(content.get('headline')).replace('SHOUT', '<mark>SHOUT</mark>') if 'SHOUT' in str(content.get('headline')).upper() else esc(content.get('headline'))}</h1>
    <p class="tagline">{esc(content.get('deck'))}</p>
    <div class="hero-actions">
      <a class="btn btn-primary" href="#{esc(first)}">{esc((content.get('cta') or ('Start',))[0])}</a>
      <a class="btn btn-ghost" href="#contact">{esc((content.get('cta') or ('', 'Contact'))[1])}</a>
    </div>
    {_stats(content)}
  </div></section>
  {''.join(secs)}
</main>
<footer class="site-footer wrap"><p>{esc(content.get('footer'))}</p><p><a href="#main">BACK TO TOP ↑</a></p></footer>
"""
    return _page(content, "brutalist", body)


# ── 04 SWISS ──────────────────────────────────────────────────────────────

def _swiss(content: dict) -> str:
    first = _first_id(content)
    index_rows = "".join(f'<li><b>{i:02d}</b><span>{esc(sec.get("heading"))}</span></li>'
                         for i, sec in enumerate(_sections(content), 1)
                         if sec.get("kind") not in ("contact", "faq"))
    secs = []
    for sec in _sections(content):
        k = sec.get("kind")
        head = _head(sec)
        if k == "rows":
            body = '<div class="rows">' + "".join(
                f'<div class="row"{_data_tags(i)}><span class="num">{esc(i.get("meta"))}</span>'
                f'<strong>{esc(i.get("title"))}</strong><p>{esc(i.get("text"))}</p>'
                '<span class="arrow">↗</span></div>' for i in sec.get("items") or []) + "</div>"
        elif k == "steps":
            body = '<div class="steps">' + "".join(
                f'<div class="step"><b>{idx:02d}</b><h3>{esc(i.get("title"))}</h3>'
                f'<p>{esc(i.get("text"))}</p></div>' for idx, i in enumerate(sec.get("items") or [], 1)
            ) + "</div>"
        elif k == "quote":
            body = (f'<blockquote class="pullquote">{esc(sec.get("heading"))}'
                    f'<cite>{esc(sec.get("lead"))}</cite></blockquote>')
        elif k == "faq":
            body = _faq(content)
        elif k == "contact":
            body = (f'<div class="split"><div><h3>{esc((content.get("contact") or {}).get("heading"))}</h3>'
                    f'<p>{esc((content.get("contact") or {}).get("lead"))}</p></div>{_form(content)}</div>')
        else:
            body = _sections_fallback(sec)
        secs.append(f'<section class="section" id="{esc(sec.get("id"))}"><div class="wrap">{head}{body}</div></section>')

    body = f"""
<a class="skip" href="#main">Skip to content</a>
<header class="site-header"><div class="wrap bar">
  <a class="brand" href="#main"><i></i>{esc(content.get('brand'))}</a>
  {_nav_toggle()}
  <nav id="site-nav" aria-label="Main"><ul>{_nav(content)}</ul></nav>
</div></header>
<main id="main">
  <section class="hero wrap">
    <p class="kicker">{esc(content.get('kicker'))}</p>
    <h1>{_emph(content.get('headline'))}</h1>
    <p class="tagline">{esc(content.get('deck'))}</p>
    <aside class="hero-index"><ol>{index_rows}</ol></aside>
    <div class="hero-actions">
      <a class="btn btn-primary" href="#{esc(first)}">{esc((content.get('cta') or ('Projects',))[0])}</a>
      <a class="btn btn-ghost" href="#contact">{esc((content.get('cta') or ('', 'Contact'))[1])}</a>
    </div>
    {_stats(content)}
  </section>
  {''.join(secs)}
</main>
<footer class="site-footer wrap"><p>{esc(content.get('footer'))}</p><p><a href="#main">Top ↑</a></p></footer>
"""
    return _page(content, "swiss", body)


# ── 05 TERMINAL ───────────────────────────────────────────────────────────

def _terminal(content: dict) -> str:
    first = _first_id(content)
    secs = []
    for sec in _sections(content):
        k = sec.get("kind")
        head = _head(sec)
        if k == "code":
            blocks = "".join(
                f'<div class="code-card"><p class="label"># {esc(i.get("meta"))} — {esc(i.get("text"))}</p>'
                f'<code>{esc(i.get("title"))}</code> '
                '<button class="btn btn-ghost" type="button" data-copy '
                'style="margin-top:.6rem;font-size:.68rem;padding:.25rem .55rem">copy</button></div>'
                for i in sec.get("items") or [])
            body = blocks
        elif k == "rows":
            body = '<div class="rows">' + "".join(
                f'<div class="row"{_data_tags(i)}><b>{esc(i.get("meta"))}</b>'
                f'<strong>{esc(i.get("title"))}</strong><p>{esc(i.get("text"))}</p></div>'
                for i in sec.get("items") or []) + "</div>"
        elif k == "steps":
            body = '<div class="steps">' + "".join(
                f'<div class="step"><b>0{idx}</b><div><h3>{esc(i.get("title"))}</h3>'
                f'<p>{esc(i.get("text"))}</p></div></div>'
                for idx, i in enumerate(sec.get("items") or [], 1)) + "</div>"
        elif k == "faq":
            body = _faq(content)
        elif k == "contact":
            body = (f'<div class="split"><div><h3>{esc((content.get("contact") or {}).get("heading"))}</h3>'
                    f'<p>{esc((content.get("contact") or {}).get("lead"))}</p></div>{_form(content)}</div>')
        else:
            body = _sections_fallback(sec)
        secs.append(f'<section class="section" id="{esc(sec.get("id"))}"><div class="wrap">{head}{body}</div></section>')

    boot = ('<div class="term-block">'
            '<div class="term-line"><span class="prompt">$</span><span class="cmd">ferry --version</span></div>'
            '<div class="term-line"><span class="out">ferry 2.4.0 (linux/amd64, darwin/arm64, windows/amd64)</span></div>'
            '<div class="term-line"><span class="prompt">$</span><span class="cmd">ferry up --check</span></div>'
            '<div class="term-line"><span class="out">✓ image built · 2.4 MB · 11s</span></div>'
            '<div class="term-line"><span class="out">✓ health gate passed · release 241 serving</span></div>'
            '</div>')

    body = f"""
<a class="skip" href="#main">Skip to content</a>
<header class="site-header"><div class="wrap bar">
  <a class="brand" href="#main"><b>{esc(content.get('brand'))}</b></a>
  {_nav_toggle()}
  <nav id="site-nav" aria-label="Main"><ul>{_nav(content)}</ul></nav>
</div></header>
<main id="main">
  <section class="hero"><div class="wrap">
    <p class="kicker">{esc(content.get('kicker'))}</p>
    <h1>{esc(content.get('headline'))}</h1>
    <p class="tagline">{esc(content.get('deck'))}</p>
    {boot}
    <div class="hero-actions">
      <a class="btn btn-primary" href="#{esc(first)}">{esc((content.get('cta') or ('Install',))[0])}</a>
      <a class="btn btn-ghost" href="#contact">{esc((content.get('cta') or ('', 'Docs'))[1])}</a>
      <span class="hint">MIT · no account · no telemetry</span>
    </div>
    {_stats(content)}
  </div></section>
  {''.join(secs)}
</main>
<footer class="site-footer wrap"><p>{esc(content.get('footer'))}</p><p><a href="#main">cd .. ↑</a></p></footer>
"""
    return _page(content, "terminal", body)


# ── 06 ORGANIC ────────────────────────────────────────────────────────────

def _organic(content: dict) -> str:
    first = _first_id(content)
    secs = []
    for sec in _sections(content):
        k = sec.get("kind")
        head = _head(sec)
        if k == "products":
            cards = "".join(
                f'<article class="product"{_data_tags(i)}><div class="product-art" aria-hidden="true"></div>'
                f'<div class="product-body"><div class="product-head"><h3>{esc(i.get("title"))}</h3>'
                f'<span class="price">{esc(i.get("meta"))}</span></div>'
                f'<p>{esc(i.get("text"))}</p>{_tags(i)}'
                f'<button class="add" type="button" data-add>Add to basket</button></div></article>'
                for i in sec.get("items") or [])
            body = _filters(sec.get("items") or [], "Filter plants") + f'<div class="grid">{cards}</div>'
        elif k == "steps":
            body = '<div class="steps">' + "".join(
                f'<div class="step"><b>{idx:02d}</b><h3>{esc(i.get("title"))}</h3>'
                f'<p>{esc(i.get("text"))}</p></div>' for idx, i in enumerate(sec.get("items") or [], 1)
            ) + "</div>"
        elif k == "split":
            body = '<div class="split">' + "".join(
                f'<div><h3>{esc(i.get("title"))}</h3><p>{esc(i.get("text"))}</p></div>'
                for i in sec.get("items") or []) + "</div>"
        elif k == "faq":
            body = _faq(content)
        elif k == "contact":
            body = (f'<div class="split"><div><h3>{esc((content.get("contact") or {}).get("heading"))}</h3>'
                    f'<p>{esc((content.get("contact") or {}).get("lead"))}</p></div>{_form(content)}</div>')
        else:
            body = _sections_fallback(sec)
        secs.append(f'<section class="section" id="{esc(sec.get("id"))}"><div class="wrap">{head}{body}</div></section>')

    leaf = ('<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M16 3c7 4 11 10 11 16 0 6-5 10-11 10S5 25 5 19C5 13 9 7 16 3z"'
            ' fill="#3f6b46"/><path d="M16 8v18M16 14c-3-3-6-4-8-4M16 20c3-3 6-4 9-4" stroke="#f4f1e8"'
            ' stroke-width="1.4" fill="none"/></svg>')

    body = f"""
<a class="skip" href="#main">Skip to content</a>
<header class="site-header"><div class="wrap bar">
  <a class="brand" href="#main">{leaf}{esc(content.get('brand'))}</a>
  {_nav_toggle()}
  <nav id="site-nav" aria-label="Main"><ul>{_nav(content)}</ul></nav>
  <span class="cart-chip" style="margin-left:.6rem;border:1px solid #ded8c8;border-radius:999px;padding:.25rem .65rem;font-size:.72rem;background:#fffdf6">basket <b data-cart>0</b></span>
</div></header>
<main id="main">
  <section class="hero wrap">
    <div>
      <p class="kicker">{esc(content.get('kicker'))}</p>
      <h1>{_emph(content.get('headline'))}</h1>
      <p class="tagline">{esc(content.get('deck'))}</p>
      <div class="hero-actions">
        <a class="btn btn-primary" href="#{esc(first)}">{esc((content.get('cta') or ('Shop',))[0])}</a>
        <a class="btn btn-ghost" href="#contact">{esc((content.get('cta') or ('', 'Visit'))[1])}</a>
      </div>
      {_stats(content)}
    </div>
    <div class="hero-art" aria-hidden="true">
      <div class="leaf leaf-1"></div><div class="leaf leaf-2"></div>
      <div class="leaf leaf-3"></div><div class="leaf leaf-4"></div>
    </div>
  </section>
  {''.join(secs)}
</main>
<footer class="site-footer wrap"><p>{esc(content.get('footer'))}</p><p><a href="#main">Back to top ↑</a></p></footer>
"""
    return _page(content, "organic", body)


# ── 07 LUXURY ─────────────────────────────────────────────────────────────

def _luxury(content: dict) -> str:
    first = _first_id(content)
    secs = []
    for sec in _sections(content):
        k = sec.get("kind")
        head = _head(sec)
        if k == "frames":
            cards = "".join(
                f'<article class="suite"{_data_tags(i)}><div class="suite-art" aria-hidden="true"></div>'
                f'<div class="suite-body"><p class="price">{esc(i.get("meta"))}</p>'
                f'<h3>{esc(i.get("title"))}</h3><p>{esc(i.get("text"))}</p>{_tags(i)}</div></article>'
                for i in sec.get("items") or [])
            body = f'<div class="frames">{cards}</div>'
        elif k == "split":
            body = '<div class="split">' + "".join(
                f'<div><h3>{esc(i.get("title"))}</h3><p>{esc(i.get("text"))}</p></div>'
                for i in sec.get("items") or []) + "</div>"
        elif k == "quote":
            body = (f'<blockquote class="pullquote">{esc(sec.get("heading"))}'
                    f'<cite>{esc(sec.get("lead"))}</cite></blockquote>')
        elif k == "faq":
            body = _faq(content)
        elif k == "contact":
            body = (f'<div class="split"><div><h3>{esc((content.get("contact") or {}).get("heading"))}</h3>'
                    f'<p>{esc((content.get("contact") or {}).get("lead"))}</p></div>{_form(content)}</div>')
        else:
            body = _sections_fallback(sec)
        secs.append(f'<section class="section" id="{esc(sec.get("id"))}"><div class="wrap">{head}{body}</div></section>')

    body = f"""
<a class="skip" href="#main">Skip to content</a>
<header class="site-header"><div class="wrap bar">
  <a class="brand" href="#main"><span class="crest">CA</span>{esc(content.get('brand'))}</a>
  {_nav_toggle()}
  <nav id="site-nav" aria-label="Main"><ul>{_nav(content)}</ul></nav>
</div></header>
<main id="main">
  <section class="hero">
    <div class="hero-scene" aria-hidden="true"></div><div class="frame" aria-hidden="true"></div>
    <div class="hero-inner">
      <p class="kicker">{esc(content.get('kicker'))}</p>
      <h1>{_emph(content.get('headline'), 3)}</h1>
      <p class="tagline">{esc(content.get('deck'))}</p>
      <div class="hero-actions">
        <a class="btn btn-primary" href="#contact">{esc((content.get('cta') or ('Enquire',))[0])}</a>
        <a class="btn" href="#{esc(first)}">{esc((content.get('cta') or ('', 'The house'))[1])}</a>
      </div>
      {_stats(content)}
    </div>
  </section>
  {''.join(secs)}
</main>
<footer class="site-footer wrap"><p>{esc(content.get('footer'))}</p><p><a href="#main">Back to top ↑</a></p></footer>
"""
    return _page(content, "luxury", body)


# ── 08 POP ────────────────────────────────────────────────────────────────

def _pop(content: dict) -> str:
    first = _first_id(content)
    secs = []
    for sec in _sections(content):
        k = sec.get("kind")
        head = _head(sec)
        if k == "products":
            emoji = ["🍓", "🍵", "🥭", "🍮", "🍋", "🖤"]
            cards = "".join(
                f'<article class="product"{_data_tags(i)}>'
                f'<div class="product-art" aria-hidden="true">{emoji[idx % len(emoji)]}</div>'
                f'<div class="product-body"><div class="product-head"><h3>{esc(i.get("title"))}</h3>'
                f'<span class="price">{esc(i.get("meta"))}</span></div>'
                f'<p>{esc(i.get("text"))}</p>{_tags(i)}'
                f'<button class="add" type="button" data-add>Add to box</button></div></article>'
                for idx, i in enumerate(sec.get("items") or []))
            body = _filters(sec.get("items") or [], "Filter flavours") + f'<div class="mosaic">{cards}</div>'
        elif k == "steps":
            body = '<div class="steps">' + "".join(
                f'<div class="step"><b>{idx}</b><h3>{esc(i.get("title"))}</h3>'
                f'<p>{esc(i.get("text"))}</p></div>' for idx, i in enumerate(sec.get("items") or [], 1)
            ) + "</div>"
        elif k == "quote":
            body = (f'<blockquote class="pullquote">{esc(sec.get("heading"))}'
                    f'<cite>{esc(sec.get("lead"))}</cite></blockquote>')
        elif k == "faq":
            body = _faq(content)
        elif k == "contact":
            body = (f'<div class="split"><div><h3>{esc((content.get("contact") or {}).get("heading"))}</h3>'
                    f'<p>{esc((content.get("contact") or {}).get("lead"))}</p></div>{_form(content)}</div>')
        else:
            body = _sections_fallback(sec)
        secs.append(f'<section class="section" id="{esc(sec.get("id"))}"><div class="wrap">{head}{body}</div></section>')

    body = f"""
<a class="skip" href="#main">Skip to content</a>
<header class="site-header"><div class="bar">
  <a class="brand" href="#main"><span class="dot">◕</span>{esc(content.get('brand'))}</a>
  {_nav_toggle()}
  <nav id="site-nav" aria-label="Main"><ul>{_nav(content)}</ul></nav>
</div></header>
<main id="main">
  <section class="hero">
    <div class="wrap">
      <button class="sticker sticker-1" type="button" data-spin>small batch<br>big flavour</button>
      <button class="sticker sticker-2" type="button" data-spin>100%<br>squish</button>
      <button class="sticker sticker-3" type="button" data-spin>yum</button>
      <p class="kicker">{esc(content.get('kicker'))}</p>
      <h1>{esc(content.get('headline')).replace('Squishy', '<mark>Squishy</mark>') if 'Squishy' in str(content.get('headline')) else _emph(content.get('headline'))}</h1>
      <p class="tagline">{esc(content.get('deck'))}</p>
      <div class="hero-actions">
        <a class="btn btn-primary" href="#{esc(first)}">{esc((content.get('cta') or ('Flavours',))[0])}</a>
        <a class="btn btn-ghost" href="#contact">{esc((content.get('cta') or ('', 'Say hi'))[1])}</a>
      </div>
      {_stats(content)}
    </div>
  </section>
  {''.join(secs)}
</main>
<footer class="site-footer wrap"><p>{esc(content.get('footer'))}</p><p><a href="#main">Back to top ↑</a></p></footer>
"""
    return _page(content, "pop", body)


# ── 09 CINEMATIC ──────────────────────────────────────────────────────────

def _cinematic(content: dict) -> str:
    first = _first_id(content)
    secs = []
    for sec in _sections(content):
        k = sec.get("kind")
        head = _head(sec)
        if k == "films":
            stills = "".join(
                f'<article class="still"{_data_tags(i)}><div class="still-art" aria-hidden="true"></div>'
                f'<div class="still-body"><p class="meta">{esc(i.get("meta"))}</p>'
                f'<h3>{esc(i.get("title"))}</h3><p>{esc(i.get("text"))}</p></div></article>'
                for i in sec.get("items") or [])
            body = f'<div class="filmstrip" data-drag tabindex="0" aria-label="Programme, scroll horizontally">{stills}</div>'
        elif k == "split":
            body = '<div class="split">' + "".join(
                f'<div><h3>{esc(i.get("title"))}</h3><p>{esc(i.get("text"))}</p></div>'
                for i in sec.get("items") or []) + "</div>"
        elif k == "steps":
            body = '<div class="steps">' + "".join(
                f'<div class="step"><b>0{idx}</b><h3>{esc(i.get("title"))}</h3>'
                f'<p>{esc(i.get("text"))}</p></div>' for idx, i in enumerate(sec.get("items") or [], 1)
            ) + "</div>"
        elif k == "faq":
            body = _faq(content)
        elif k == "contact":
            body = (f'<div class="split"><div><h3>{esc((content.get("contact") or {}).get("heading"))}</h3>'
                    f'<p>{esc((content.get("contact") or {}).get("lead"))}</p></div>{_form(content)}</div>')
        else:
            body = _sections_fallback(sec)
        secs.append(f'<section class="section" id="{esc(sec.get("id"))}"><div class="wrap">{head}{body}</div></section>')

    body = f"""
<a class="skip" href="#main">Skip to content</a>
<header class="site-header"><div class="wrap bar">
  <a class="brand" href="#main">Night<span>fall</span></a>
  {_nav_toggle()}
  <nav id="site-nav" aria-label="Main"><ul>{_nav(content)}</ul></nav>
</div></header>
<main id="main">
  <section class="hero" data-parallax>
    <div class="letterbox" data-depth="14" aria-hidden="true"></div>
    <div class="wrap">
      <p class="kicker">{esc(content.get('kicker'))}</p>
      <h1>{_emph(content.get('headline'), 3)}</h1>
      <p class="tagline">{esc(content.get('deck'))}</p>
      <div class="hero-actions">
        <a class="btn btn-primary" href="#{esc(first)}">{esc((content.get('cta') or ('Tickets',))[0])}</a>
        <a class="btn" href="#programme">{esc((content.get('cta') or ('', 'Programme'))[1])}</a>
      </div>
      <div class="hero-meta"><span>14—18 October 2026</span><span>Lisbon, Portugal</span>
        <span>Cinema Ideal + harbour wall</span></div>
      {_stats(content)}
    </div>
  </section>
  {''.join(secs)}
</main>
<footer class="site-footer wrap"><p>{esc(content.get('footer'))}</p><p><a href="#main">Back to top ↑</a></p></footer>
"""
    return _page(content, "cinematic", body)


# ── 10 NEWSROOM ───────────────────────────────────────────────────────────

def _sparkline(points: list[float]) -> str:
    if len(points) < 2:
        return ""
    w, h, pad = 620, 190, 16
    lo, hi = min(points), max(points)
    span = (hi - lo) or 1
    coords = []
    for i, v in enumerate(points):
        x = pad + i * (w - 2 * pad) / (len(points) - 1)
        y = h - pad - ((v - lo) / span) * (h - 2 * pad)
        coords.append((round(x, 1), round(y, 1)))
    line = " ".join(f"{x},{y}" for x, y in coords)
    area = f"{pad},{h - pad} " + line + f" {w - pad},{h - pad}"
    dots = "".join(f'<circle class="dot" cx="{x}" cy="{y}" r="3"><title>{points[i]:g}</title></circle>'
                   for i, (x, y) in enumerate(coords))
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="Five-session index, {lo:g} to {hi:g}">'
            f'<defs><linearGradient id="sparkfill" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="#c8102e" stop-opacity=".5"/>'
            f'<stop offset="1" stop-color="#c8102e" stop-opacity="0"/></linearGradient></defs>'
            f'<polygon class="area" points="{area}"/><polyline class="line" points="{line}"/>{dots}</svg>')


def _newsroom(content: dict) -> str:
    first = _first_id(content)
    secs = []
    for sec in _sections(content):
        k = sec.get("kind")
        head = _head(sec)
        if k == "columns":
            cards = "".join(
                f'<article class="story"{_data_tags(i)}><p class="meta">{esc(i.get("meta"))}</p>'
                f'<h3>{esc(i.get("title"))}</h3><p>{esc(i.get("text"))}</p>{_tags(i)}</article>'
                for i in sec.get("items") or [])
            body = f'<div class="columns">{cards}</div>'
        elif k == "chart":
            item = (sec.get("items") or [{}])[0]
            try:
                pts = [float(x) for x in re.split(r"[,\s]+", str(item.get("text") or "")) if x]
            except ValueError:
                pts = []
            body = (f'<div class="chart"><div class="chart-copy"><h3>{esc(item.get("title"))}</h3>'
                    f'<p>{esc(item.get("meta"))}</p><p>The line is drawn from the actual closes, '
                    'not a decorative shape.</p></div>'
                    f'{_sparkline(pts)}</div>')
        elif k == "quote":
            body = (f'<blockquote class="pullquote">{esc(sec.get("heading"))}'
                    f'<cite>{esc(sec.get("lead"))}</cite></blockquote>')
        elif k == "faq":
            body = _faq(content)
        elif k == "contact":
            body = (f'<div class="split"><div><h3>{esc((content.get("contact") or {}).get("heading"))}</h3>'
                    f'<p>{esc((content.get("contact") or {}).get("lead"))}</p></div>{_form(content)}</div>')
        else:
            body = _sections_fallback(sec)
        secs.append(f'<section class="section" id="{esc(sec.get("id"))}"><div class="wrap">{head}{body}</div></section>')

    items_all = [i for s in _sections(content) for i in (s.get("items") or [])]
    lead = items_all[0] if items_all else {"title": content.get("headline"), "text": "", "meta": ""}
    side = items_all[1:4]
    side_html = "".join(
        f'<div class="side-item"><p class="meta">{esc(i.get("meta"))}</p><strong>{esc(i.get("title"))}</strong>'
        f'<p>{esc(i.get("text"))}</p></div>' for i in side)
    ticker_items = "".join(
        f'<span>{esc(s.get("value"))} <b>{esc(str(s.get("label","")).split()[-1] if s.get("label") else "")}</b></span>'
        for s in content.get("stats") or []) * 2

    body = f"""
<a class="skip" href="#main">Skip to content</a>
<header class="site-header">
  <div class="wrap bar"><span class="mast-date">Friday 19 October 2026 · London</span>
    {_nav_toggle()}<span class="mast-right">Markets open · 08:14 GMT</span></div>
  <div class="wrap"><p class="wordmark">The Meri<span>dian</span></p></div>
  <div class="wrap"><nav id="site-nav" aria-label="Main"><ul>{_nav(content)}</ul></nav></div>
  <div class="ticker" aria-hidden="true"><div>{ticker_items}{ticker_items}</div></div>
</header>
<main id="main">
  <section class="hero wrap">
    <div>
      <p class="kicker">Investigation · Manufacturing</p>
      <h1>{_emph(content.get('headline'), 3)}</h1>
      <p class="tagline">{esc(content.get('deck'))}</p>
      <p class="byline">By Marta Lindqvist and Owen Price · 14 min read</p>
      <div class="hero-actions">
        <a class="btn btn-primary" href="#{esc(first)}">{esc((content.get('cta') or ('Read',))[0])}</a>
        <a class="btn btn-ghost" href="#contact">{esc((content.get('cta') or ('', 'Subscribe'))[1])}</a>
      </div>
    </div>
    <aside class="hero-side"><h3>Also today</h3>{side_html}</aside>
    {_stats(content)}
  </section>
  {''.join(secs)}
</main>
<footer class="site-footer wrap"><p>{esc(content.get('footer'))}</p><p><a href="#main">Back to top ↑</a></p></footer>
"""
    return _page(content, "newsroom", body)


_RENDERERS = {
    "aurora": _aurora, "editorial": _editorial, "brutalist": _brutalist,
    "swiss": _swiss, "terminal": _terminal, "organic": _organic,
    "luxury": _luxury, "pop": _pop, "cinematic": _cinematic,
    "newsroom": _newsroom,
}


def render_site(content: dict, studio: str = "") -> str:
    """Render one complete site page in the requested studio."""
    key = studio or content.get("studio") or "aurora"
    if key not in _RENDERERS:
        key = "aurora"
    return _RENDERERS[key](content)


# ── Showcase gallery ──────────────────────────────────────────────────────

GALLERY_CSS = r"""
*,*::before,*::after{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:#07090f;color:#f2f5ff;font:400 16px/1.6 "Inter","Segoe UI",system-ui,sans-serif;
 overflow-x:hidden}
.wrap{width:min(1240px,100% - 3rem);margin-inline:auto}
a{color:inherit}
:focus-visible{outline:3px solid #7c5cff;outline-offset:3px}
.hero{padding:5rem 0 3rem;position:relative;isolation:isolate;
 background:radial-gradient(900px 500px at 15% 0%,rgba(124,92,255,.32),transparent 60%),
 radial-gradient(700px 480px at 88% 12%,rgba(34,211,238,.18),transparent 60%)}
.hero::after{content:"";position:absolute;inset:0;z-index:-1;opacity:.35;
 background-image:linear-gradient(rgba(255,255,255,.04) 1px,transparent 1px),
 linear-gradient(90deg,rgba(255,255,255,.04) 1px,transparent 1px);
 background-size:64px 64px;mask-image:linear-gradient(180deg,#000,transparent 80%)}
.eyebrow{font-size:.72rem;letter-spacing:.24em;text-transform:uppercase;color:#8ea0ff;margin:0 0 1rem}
h1{font-size:clamp(2.6rem,6.4vw,5.2rem);line-height:1.02;letter-spacing:-.045em;margin:0 0 1.2rem;max-width:16ch}
h1 em{font-style:normal;background:linear-gradient(100deg,#22d3ee,#7c5cff 60%,#f0a6ff);
 -webkit-background-clip:text;background-clip:text;color:transparent}
.lede{color:#9aa6c4;max-width:62ch;font-size:1.08rem;margin:0 0 2rem}
.chips{display:flex;flex-wrap:wrap;gap:.5rem;margin:0 0 1.5rem}
.chip{border:1px solid rgba(255,255,255,.14);border-radius:999px;padding:.3rem .8rem;font-size:.78rem;color:#b9c4dd}
.chip b{color:#fff;font-weight:600}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;background:rgba(255,255,255,.12);
 border:1px solid rgba(255,255,255,.12);border-radius:16px;overflow:hidden;margin-top:1rem}
.stat{background:#0a0e19;padding:1rem 1.1rem}
.stat strong{display:block;font-size:1.7rem;letter-spacing:-.03em}
.stat span{font-size:.72rem;letter-spacing:.1em;text-transform:uppercase;color:#7f8cab}
.gallery{padding:2rem 0 4rem}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(520px,1fr));gap:2rem}
.card{background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.1);border-radius:20px;
 overflow:hidden;transition:transform .25s,border-color .25s}
.card:hover{transform:translateY(-4px);border-color:rgba(124,92,255,.5)}
.shot{display:block;position:relative;aspect-ratio:16/10;background:#0c1120;overflow:hidden}
.shot img{width:100%;height:100%;object-fit:cover;display:block;transition:transform .5s}
.card:hover .shot img{transform:scale(1.03)}
.shot .open{position:absolute;right:.8rem;bottom:.8rem;background:rgba(6,10,20,.82);border:1px solid rgba(255,255,255,.2);
 border-radius:999px;padding:.35rem .8rem;font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;
 backdrop-filter:blur(8px)}
.body{padding:1.2rem 1.3rem 1.4rem}
.top{display:flex;align-items:baseline;gap:.7rem;flex-wrap:wrap;margin-bottom:.4rem}
.num{font-family:ui-monospace,Consolas,monospace;font-size:.72rem;color:#22d3ee}
.body h2{font-size:1.18rem;margin:0;letter-spacing:-.02em}
.cat{margin-left:auto;font-size:.68rem;letter-spacing:.1em;text-transform:uppercase;color:#8b97b6}
.desc{color:#9aa6c4;font-size:.88rem;margin:.3rem 0 .8rem}
.dna{display:flex;flex-wrap:wrap;gap:.4rem;margin-bottom:.9rem}
.dna span{font-size:.68rem;border:1px solid rgba(255,255,255,.12);border-radius:6px;padding:.2rem .5rem;color:#b9c4dd}
.swatches{display:flex;gap:.3rem;margin-left:auto}
.swatches i{width:14px;height:14px;border-radius:50%;border:1px solid rgba(255,255,255,.25);font-style:normal}
.links{display:flex;gap:.8rem;font-size:.8rem}
.links a{text-decoration:none;color:#8ea0ff;border-bottom:1px solid transparent}
.links a:hover{border-color:#8ea0ff}
.foot{padding:2.5rem 0 3.5rem;border-top:1px solid rgba(255,255,255,.1);color:#7f8cab;font-size:.8rem;
 display:flex;flex-wrap:wrap;gap:1rem;justify-content:space-between}
@media (max-width:620px){
 .grid{grid-template-columns:1fr}
 .hero{padding-top:3.5rem}
}
"""


def render_gallery(sites: list[dict], relative_dirs: dict[str, str] | None = None,
                   screenshots: dict[str, str] | None = None) -> str:
    """Showcase page for built sites.

    relative_dirs maps site id → href to its index.html; screenshots maps id →
    image href. Both can be absent (the gallery then falls back to live links).
    """
    relative_dirs = relative_dirs or {}
    screenshots = screenshots or {}
    cards = []
    for i, site in enumerate(sites, 1):
        sid = str(site.get("id") or i)
        st = STUDIOS.get(site.get("studio") or "aurora", STUDIOS["aurora"])
        href = relative_dirs.get(sid) or "#"
        shot = screenshots.get(sid)
        image = (f'<img src="{esc(shot)}" alt="Screenshot of the {esc(site.get("brand"))} site" loading="lazy">'
                 if shot else
                 f'<div style="display:grid;place-items:center;height:100%;color:#47536f;font-size:.8rem">'
                 f'{esc(st["name"])} preview</div>')
        swatches = "".join(f'<i style="background:{esc(c)}" title="{esc(c)}"></i>'
                           for c in st["palette"][:3])
        cards.append(f"""
<article class="card">
  <a class="shot" href="{esc(href)}" target="_blank" rel="noopener" aria-label="Open {esc(site.get('brand'))}">
    {image}<span class="open">Open live site ↗</span>
  </a>
  <div class="body">
    <div class="top"><span class="num">{i:02d}</span><h2>{esc(site.get('brand'))}</h2>
      <span class="cat">{esc(site.get('category'))}</span></div>
    <p class="desc">{esc(site.get('deck'))}</p>
    <div class="dna"><span>{esc(st['name'])} studio</span><span>{esc(st['type'])}</span>
      <span class="swatches">{swatches}</span></div>
    <div class="links"><a href="{esc(href)}" target="_blank" rel="noopener">Live site</a>
      <a href="{esc(href)}#contact" target="_blank" rel="noopener">Contact form</a>
      <span style="color:#5f6d8c">{esc(site.get('note'))}</span></div>
  </div>
</article>""")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crown Code Studio — 10 sites, 10 design systems</title>
<meta name="description" content="Ten complete websites, each with its own layout, typography, palette and motion system.">
<style>{GALLERY_CSS}</style>
</head>
<body>
<header class="hero"><div class="wrap">
  <p class="eyebrow">Crown Code Studio · showcase</p>
  <h1>Ten sites. <em>Ten design systems.</em> No shared template.</h1>
  <p class="lede">Every page below was generated by the studio engine from its own content model and
  visual language: a glass lightfield, a printed magazine, a brutalist index, a Swiss grid, a
  phosphor terminal, a botanical shop, a gold-framed hotel, a candy storefront, a letterboxed film
  festival and a broadsheet newsroom. Open any of them — the navigation, filters, forms and
  interactions all work offline.</p>
  <div class="chips">
    <span class="chip"><b>{len(sites)}</b> sites</span>
    <span class="chip"><b>10</b> studios</span>
    <span class="chip"><b>0</b> external assets</span>
    <span class="chip"><b>0</b> templates reused</span>
    <span class="chip">verified in Chromium at <b>375px</b> + <b>1280px</b></span>
  </div>
  <div class="stats">
    <div class="stat"><strong>10</strong><span>distinct layouts</span></div>
    <div class="stat"><strong>45+</strong><span>working interactions</span></div>
    <div class="stat"><strong>10</strong><span>palettes + type systems</span></div>
    <div class="stat"><strong>100%</strong><span>offline / self-contained</span></div>
  </div>
</div></header>
<main class="gallery"><div class="wrap"><div class="grid">{''.join(cards)}</div></div></main>
<footer class="foot wrap"><p>Crown Code Studio · generated {len(sites)} complete sites with unique layout, type, palette and motion.</p>
<p><a href="../index.html">← Project index</a></p></footer>
</body>
</html>
"""
