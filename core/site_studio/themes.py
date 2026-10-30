"""core/site_studio/themes.py — ten independent design systems.

Each studio owns its palette, typography, layout rules, decoration and motion.
They share only BASE_CSS, which exists for correctness and accessibility
(box-sizing, focus rings, reduced motion). Nothing aesthetic is shared, so two
sites never look like the same template with a different accent colour.
"""

from __future__ import annotations

BASE_CSS = r"""
/* functional foundation — identical in every studio, aesthetics are not */
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
body{margin:0;max-width:100%;overflow-x:hidden}
img,svg,video,canvas{max-width:100%;height:auto;display:block}
a{color:inherit}
button,input,select,textarea{font:inherit}
:focus-visible{outline:3px solid var(--crown-focus,#ffd166);outline-offset:3px}
a:focus-visible,button:focus-visible,input:focus-visible,textarea:focus-visible,select:focus-visible{outline:3px solid var(--crown-focus,#ffd166);outline-offset:3px}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}
.skip{position:absolute;left:-9999px;top:0}
.skip:focus{left:1rem;top:1rem;z-index:99;padding:.6rem 1rem;border-radius:6px;background:#111;color:#fff}
.reveal{opacity:0;transform:translateY(18px);transition:opacity .7s ease,transform .7s cubic-bezier(.2,.7,.2,1)}
.reveal.is-in{opacity:1;transform:none}
@media (prefers-reduced-motion:reduce){
  html{scroll-behavior:auto}
  *,*::before,*::after{animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}
  .reveal{opacity:1;transform:none}
}
"""

# ── 01 AURORA — dark glass, drifting lightfield, bento ─────────────────────
CSS_AURORA = r"""
:root{--bg:#070b16;--surface:rgba(255,255,255,.055);--ink:#f4f7ff;--muted:#9aa6c4;
--accent:#7c5cff;--accent2:#22d3ee;--line:rgba(255,255,255,.12);--crown-focus:#7c5cff;
--font:"Inter","Segoe UI",system-ui,sans-serif;--mono:ui-monospace,"Cascadia Code",Consolas,monospace}
body{background:
 radial-gradient(1200px 700px at 12% -8%,rgba(124,92,255,.28),transparent 60%),
 radial-gradient(900px 600px at 88% 4%,rgba(34,211,238,.18),transparent 55%),
 var(--bg);color:var(--ink);font:400 17px/1.65 var(--font);letter-spacing:-.01em}
.wrap{width:min(1180px,100% - 3rem);margin-inline:auto}
.site-header{position:sticky;top:1rem;z-index:30;width:min(1180px,100% - 3rem);margin:1rem auto 0;
 background:rgba(10,14,26,.62);border:1px solid var(--line);border-radius:999px;
 backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px)}
.bar{display:flex;align-items:center;gap:1rem;padding:.7rem .9rem .7rem 1.2rem}
.brand{display:flex;align-items:center;gap:.6rem;font-weight:800;letter-spacing:-.03em;
 font-size:1.05rem;text-decoration:none}
.brand i{display:grid;place-items:center;width:26px;height:26px;border-radius:9px;
 background:linear-gradient(135deg,var(--accent),var(--accent2));color:#06101c;
 font-style:normal;font-size:.85rem;font-weight:900;box-shadow:0 0 24px rgba(124,92,255,.55)}
nav{margin-inline-start:auto}
nav ul{display:flex;gap:.25rem;list-style:none;margin:0;padding:0}
nav a{padding:.5rem .8rem;border-radius:999px;text-decoration:none;color:var(--muted);
 font-size:.9rem;transition:color .2s,background .2s}
nav a:hover{color:var(--ink);background:rgba(255,255,255,.08)}
.nav-toggle{display:none;margin-inline-start:auto;background:rgba(255,255,255,.08);color:var(--ink);
 border:1px solid var(--line);border-radius:999px;padding:.45rem .85rem;font-size:.85rem;cursor:pointer}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:.5rem;border-radius:999px;
 padding:.85rem 1.4rem;font-weight:650;font-size:.95rem;text-decoration:none;cursor:pointer;
 border:1px solid transparent;transition:transform .2s,box-shadow .2s,background .2s}
.btn:hover{transform:translateY(-2px)}
.btn-primary{background:linear-gradient(135deg,var(--accent),#9a7bff);color:#fff;
 box-shadow:0 10px 30px rgba(124,92,255,.38)}
.btn-ghost{border-color:var(--line);color:var(--ink);background:rgba(255,255,255,.04)}
.hero{position:relative;padding:clamp(4rem,10vw,8rem) 0 3rem;isolation:isolate;overflow:hidden}
.orb{position:absolute;border-radius:50%;filter:blur(60px);pointer-events:none;z-index:-1;opacity:.65}
.orb-a{width:420px;height:420px;left:-120px;top:-40px;background:#5b3cff;animation:drift 18s ease-in-out infinite alternate}
.orb-b{width:360px;height:360px;right:-80px;top:120px;background:#0e7490;animation:drift 24s ease-in-out infinite alternate-reverse}
.orb-c{width:260px;height:260px;left:42%;bottom:-160px;background:#c026d3;opacity:.28;animation:drift 21s ease-in-out infinite alternate}
@keyframes drift{from{transform:translate3d(0,0,0) scale(1)}to{transform:translate3d(60px,40px,0) scale(1.12)}}
.hero .kicker{display:inline-flex;align-items:center;gap:.5rem;border:1px solid var(--line);
 border-radius:999px;padding:.3rem .8rem;color:var(--muted);font-size:.78rem;letter-spacing:.08em;text-transform:uppercase}
.hero .kicker b{width:6px;height:6px;border-radius:50%;background:var(--accent2);box-shadow:0 0 10px var(--accent2)}
h1{font-size:clamp(2.6rem,7vw,5.4rem);line-height:1.02;letter-spacing:-.045em;margin:1rem 0 1.2rem;max-width:15ch}
h1 em{font-style:normal;background:linear-gradient(100deg,var(--accent2),var(--accent) 60%,#f0a6ff);
 -webkit-background-clip:text;background-clip:text;color:transparent}
.tagline{color:var(--muted);font-size:clamp(1rem,2vw,1.2rem);max-width:56ch}
.hero-actions{display:flex;flex-wrap:wrap;gap:.8rem;margin-top:2rem}
.hero-note{margin-top:1rem;color:#7380a0;font-size:.82rem}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;
 margin-top:4rem;background:var(--line);border:1px solid var(--line);border-radius:20px;overflow:hidden}
.metric{background:rgba(10,15,28,.7);padding:1.3rem 1.4rem}
.metric strong{display:block;font-size:1.9rem;letter-spacing:-.04em;
 background:linear-gradient(120deg,#fff,#a8b6ff);-webkit-background-clip:text;background-clip:text;color:transparent}
.metric span{color:var(--muted);font-size:.8rem;letter-spacing:.04em;text-transform:uppercase}
.section{padding:clamp(4rem,9vw,7rem) 0}
.sec-head{max-width:62ch;margin-bottom:2.4rem}
.eyebrow{text-transform:uppercase;letter-spacing:.2em;font-size:.72rem;color:var(--accent2);margin:0 0 .7rem;font-weight:700}
h2{font-size:clamp(1.8rem,4.2vw,3rem);line-height:1.08;letter-spacing:-.035em;margin:0 0 .7rem}
h3{margin:0 0 .4rem;font-size:1.08rem;letter-spacing:-.01em}
.lead{color:var(--muted);max-width:60ch}
.bento{display:grid;grid-template-columns:repeat(6,1fr);gap:1rem}
.bento .card{grid-column:span 2}
.bento .card:nth-child(1){grid-column:span 4}
.bento .card:nth-child(2){grid-column:span 2}
.bento .card:nth-child(3){grid-column:span 2}
.bento .card:nth-child(4){grid-column:span 4}
.card{position:relative;background:var(--surface);border:1px solid var(--line);border-radius:20px;
 padding:1.6rem;overflow:hidden;transition:transform .25s,border-color .25s}
.card::after{content:"";position:absolute;inset:0;border-radius:inherit;padding:1px;
 background:linear-gradient(140deg,rgba(255,255,255,.18),transparent 40%);
 -webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);
 -webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none}
.card:hover{transform:translateY(-4px);border-color:rgba(124,92,255,.45)}
.card .num{font-family:var(--mono);font-size:.75rem;color:var(--accent2);letter-spacing:.12em}
.card p{color:var(--muted);margin:.5rem 0 0;font-size:.95rem}
.tags{display:flex;flex-wrap:wrap;gap:.4rem;list-style:none;padding:0;margin:1rem 0 0}
.tags li{font-size:.72rem;border:1px solid var(--line);border-radius:999px;padding:.15rem .6rem;color:var(--muted)}
.filters{display:flex;flex-wrap:wrap;gap:.5rem;margin:0 0 1.5rem}
.filter{background:rgba(255,255,255,.04);color:var(--muted);border:1px solid var(--line);
 border-radius:999px;padding:.42rem .9rem;font-size:.85rem;cursor:pointer}
.filter.is-active{background:var(--accent);border-color:var(--accent);color:#fff}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1rem}
.meta{font-size:.74rem;color:var(--accent2);text-transform:uppercase;letter-spacing:.14em;margin:0}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1px;background:var(--line);
 border:1px solid var(--line);border-radius:20px;overflow:hidden}
.steps .card{border:0;border-radius:0;background:#0a0f1d}
.steps .card strong{display:block;font-size:2rem;color:rgba(124,92,255,.5);line-height:1;margin-bottom:.7rem}
.quote-band{border-block:1px solid var(--line);padding:3rem 0}
.pullquote{font-size:clamp(1.3rem,3vw,2rem);line-height:1.35;letter-spacing:-.02em;max-width:34ch;margin:0}
.pullquote cite{display:block;margin-top:1rem;font-style:normal;color:var(--muted);font-size:.9rem}
.split{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:2rem;align-items:start}
.split h3{color:var(--accent2)}
.chips{list-style:none;display:flex;flex-wrap:wrap;gap:.5rem;padding:0;margin:1rem 0 0}
.chip{border:1px solid var(--line);border-radius:999px;padding:.45rem 1rem;font-size:.9rem;background:rgba(255,255,255,.04)}
.faq details{border-bottom:1px solid var(--line);padding:1.15rem 0}
.faq summary{cursor:pointer;font-weight:600;list-style:none;display:flex;justify-content:space-between;gap:1rem}
.faq summary::-webkit-details-marker{display:none}
.faq summary::after{content:"+";color:var(--accent2);font-weight:400}
.faq details[open] summary::after{content:"−"}
.faq p{color:var(--muted);max-width:70ch;margin:.8rem 0 0}
.contact-form{display:grid;gap:1rem;max-width:600px;background:var(--surface);
 border:1px solid var(--line);border-radius:20px;padding:1.6rem}
.contact-form label{display:grid;gap:.4rem;font-size:.82rem;color:var(--muted)}
.contact-form input,.contact-form textarea,.contact-form select{background:rgba(6,9,18,.7);color:var(--ink);
 border:1px solid var(--line);border-radius:12px;padding:.75rem .9rem;width:100%}
.contact-form textarea{min-height:7rem;resize:vertical}
.form-status{min-height:1.4rem;color:var(--accent2);font-size:.9rem}
.site-footer{border-top:1px solid var(--line);padding:2.5rem 0;color:var(--muted);font-size:.85rem;
 display:flex;flex-wrap:wrap;gap:1rem;justify-content:space-between;align-items:center}
.site-footer a{color:var(--ink);text-decoration:none}
@media (max-width:820px){
 nav{position:absolute;inset:calc(100% + .6rem) 0 auto;background:rgba(9,13,24,.97);border:1px solid var(--line);
  border-radius:18px;display:none;padding:.6rem}
 nav.is-open{display:block}
 nav ul{flex-direction:column}
 nav a{display:block}
 .nav-toggle{display:inline-flex}
 .bento{grid-template-columns:1fr}
 .bento .card,.bento .card:nth-child(n){grid-column:span 1}
 h1{max-width:none}
}
"""

# ── 02 EDITORIAL — paper, masthead, story rows ─────────────────────────────
CSS_EDITORIAL = r"""
:root{--paper:#f4efe6;--surface:#fffdf8;--ink:#1a1713;--muted:#6b6257;--accent:#b23a2b;
--accent2:#1f4e46;--line:#d9d0c1;--crown-focus:#b23a2b;
--serif:Georgia,"Iowan Old Style","Times New Roman",serif;--sans:"Segoe UI",system-ui,sans-serif;
--mono:"Courier New",Courier,monospace}
body{background:var(--paper);color:var(--ink);font:400 18px/1.7 var(--serif)}
body::before{content:"";position:fixed;inset:0;pointer-events:none;opacity:.35;z-index:0;
 background-image:radial-gradient(rgba(26,23,19,.12) .6px,transparent .6px);background-size:4px 4px}
.wrap{width:min(1160px,100% - 3rem);margin-inline:auto;position:relative;z-index:1}
.masthead{padding:1.2rem 0 0;border-bottom:3px double var(--ink)}
.mast-top{display:flex;align-items:flex-end;justify-content:space-between;gap:1rem;padding-bottom:.7rem}
.issue{font:400 .72rem/1.4 var(--mono);letter-spacing:.16em;text-transform:uppercase;color:var(--muted)}
.wordmark{font-family:var(--serif);font-size:clamp(2rem,5.5vw,3.7rem);line-height:.9;letter-spacing:-.03em;
 font-style:italic;margin:0;text-align:center;flex:1}
.wordmark span{color:var(--accent)}
.bar{display:flex;align-items:center;gap:1rem;padding:.6rem 0;border-top:1px solid var(--line)}
.brand{display:none}
nav ul{display:flex;flex-wrap:wrap;gap:1.4rem;list-style:none;margin:0;padding:0;width:100%}
nav a{font:400 .74rem/1 var(--mono);letter-spacing:.16em;text-transform:uppercase;text-decoration:none;
 color:var(--ink);padding-bottom:.3rem;border-bottom:1px solid transparent}
nav a:hover{border-color:var(--accent);color:var(--accent)}
.nav-toggle{display:none;background:none;border:0;font:700 .78rem var(--mono);letter-spacing:.12em;cursor:pointer}
.btn{display:inline-block;font:600 .78rem/1 var(--mono);letter-spacing:.12em;text-transform:uppercase;
 padding:.8rem 1.2rem;text-decoration:none;border:1px solid var(--ink);transition:background .2s,color .2s}
.btn-primary{background:var(--ink);color:var(--paper)}
.btn-primary:hover{background:var(--accent);border-color:var(--accent)}
.btn-ghost{color:var(--ink);border-color:var(--line)}
.btn-ghost:hover{border-color:var(--ink)}
.hero{padding:3.5rem 0 3rem;display:grid;grid-template-columns:1.35fr .8fr;gap:3rem;align-items:start;
 border-bottom:1px solid var(--ink)}
.kicker{font:400 .72rem/1.6 var(--mono);letter-spacing:.18em;text-transform:uppercase;color:var(--accent);
 margin:0 0 1rem}
h1{font-size:clamp(2.4rem,5.6vw,4.6rem);line-height:1.02;letter-spacing:-.035em;margin:0 0 1.2rem;font-weight:400}
h1 em{font-style:italic;color:var(--accent)}
.tagline{font-size:1.15rem;line-height:1.6;color:var(--muted);max-width:48ch;margin:0 0 1.8rem}
.tagline::first-letter{float:left;font-size:3.4rem;line-height:.8;padding:.15rem .45rem 0 0;color:var(--accent);animation:ink-in .8s ease both}
@keyframes ink-in{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:none}}
.hero-actions{display:flex;flex-wrap:wrap;gap:.7rem}
.hero-card{background:var(--surface);border:1px solid var(--line);padding:1.4rem}
.hero-card .label{font:400 .68rem/1 var(--mono);letter-spacing:.16em;text-transform:uppercase;color:var(--accent);margin:0 0 .8rem}
.hero-card h3{font-size:1.35rem;line-height:1.25;margin:0 0 .5rem;font-weight:400}
.hero-card p{font-size:.9rem;line-height:1.6;color:var(--muted);margin:0}
.hero-card .byline{font:400 .72rem var(--mono);color:var(--ink);margin-top:.9rem;letter-spacing:.06em}
.metrics{display:flex;flex-wrap:wrap;gap:2rem;padding:1.2rem 0;border-top:1px solid var(--line);margin-top:2.5rem}
.metric strong{display:block;font-size:1.6rem;font-weight:400;line-height:1}
.metric span{font:400 .68rem/1.6 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.section{padding:3.5rem 0;border-bottom:1px solid var(--line)}
.sec-head{display:flex;align-items:baseline;justify-content:space-between;gap:1rem;
 border-bottom:1px solid var(--ink);padding-bottom:.6rem;margin-bottom:0}
.eyebrow{font:400 .7rem/1 var(--mono);letter-spacing:.18em;text-transform:uppercase;color:var(--accent);margin:0}
h2{font-size:clamp(1.6rem,3.2vw,2.2rem);font-weight:400;letter-spacing:-.02em;margin:0;line-height:1.2}
.sec-lead{color:var(--muted);font-size:.95rem;margin:.8rem 0 0;max-width:60ch}
.story-row{display:grid;grid-template-columns:4rem 1fr 1.1fr;gap:1.5rem;padding:1.4rem 0;
 border-bottom:1px solid var(--line);align-items:baseline}
.story-num{font:400 .8rem var(--mono);color:var(--accent)}
.story-row h3{font-size:1.5rem;line-height:1.25;font-weight:400;margin:0}
.story-row .story-meta{font:400 .68rem/1.8 var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin:.3rem 0 0}
.story-row p{color:var(--muted);font-size:.95rem;margin:0}
.story-row:hover h3{color:var(--accent)}
.grid{display:grid;gap:0}
.card{border-bottom:1px solid var(--line);padding:1.2rem 0}
.card h3{font-weight:400;font-size:1.2rem;margin:0 0 .3rem}
.card p{color:var(--muted);font-size:.92rem;margin:0}
.meta{font:400 .68rem/1.8 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--accent);margin:0}
.tags{display:none}
.filters{display:flex;gap:.6rem;flex-wrap:wrap;margin:1rem 0 0}
.filter{font:400 .7rem var(--mono);letter-spacing:.12em;text-transform:uppercase;background:none;
 border:1px solid var(--line);padding:.4rem .7rem;cursor:pointer}
.filter.is-active{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.pullquote{font-size:clamp(1.8rem,4.2vw,3.2rem);line-height:1.18;letter-spacing:-.02em;font-style:italic;
 margin:0;max-width:24ch;font-weight:400}
.pullquote cite{display:block;font:400 .75rem/1.8 var(--mono);letter-spacing:.14em;text-transform:uppercase;
 font-style:normal;color:var(--muted);margin-top:1.4rem}
.split{display:grid;grid-template-columns:1fr 1fr;gap:3rem}
.split h3{font-weight:400;font-size:1.15rem;margin:0 0 .3rem}
.split p{font-size:.95rem;color:var(--muted);margin:0 0 1.2rem}
.list-row{display:flex;justify-content:space-between;gap:1rem;padding:.9rem 0;border-bottom:1px solid var(--line)}
.list-row strong{font-weight:400;font-size:1.05rem}
.list-row > div{min-width:0}
.list-row > span{font:400 .7rem var(--mono);letter-spacing:.1em;color:var(--muted);white-space:nowrap}
.list-row > div span{font-size:.9rem;color:var(--muted);white-space:normal}
.chips{list-style:none;display:flex;flex-wrap:wrap;gap:.4rem;padding:0;margin:1rem 0 0}
.chip{font:400 .72rem var(--mono);border:1px solid var(--line);padding:.3rem .6rem;text-transform:uppercase;letter-spacing:.1em}
.faq details{border-bottom:1px solid var(--line);padding:1rem 0}
.faq summary{cursor:pointer;font-size:1.05rem;list-style:none;display:flex;justify-content:space-between;gap:1rem}
.faq summary::-webkit-details-marker{display:none}
.faq summary::after{content:"+";font-family:var(--mono);color:var(--accent)}
.faq details[open] summary::after{content:"−"}
.faq p{color:var(--muted);max-width:70ch;margin:.7rem 0 0;font-size:.95rem}
.contact-form{display:grid;gap:1rem;max-width:620px}
.contact-form label{display:grid;gap:.35rem;font:400 .7rem var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.contact-form input,.contact-form textarea,.contact-form select{background:var(--surface);color:var(--ink);
 border:1px solid var(--line);border-radius:0;padding:.7rem .8rem;font-family:var(--serif);font-size:1rem;width:100%}
.contact-form textarea{min-height:7rem;resize:vertical}
.form-status{min-height:1.4rem;font:400 .8rem var(--mono);color:var(--accent2)}
.site-footer{padding:2rem 0 3rem;display:flex;flex-wrap:wrap;gap:1rem;justify-content:space-between;
 font:400 .7rem/1.8 var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
@media (max-width:820px){
 .hero{grid-template-columns:1fr;gap:2rem}
 nav{display:none;width:100%}
 nav.is-open{display:block}
 nav ul{flex-direction:column;gap:.7rem;padding-top:.7rem}
 .nav-toggle{display:inline-block;margin-inline-start:auto}
 .bar{flex-wrap:wrap}
 .story-row{grid-template-columns:2.4rem 1fr}
 .story-row p{grid-column:2}
 .split{grid-template-columns:1fr;gap:1.6rem}
 .mast-top{flex-wrap:wrap;justify-content:center}
 .issue{display:none}
}
"""

# ── 03 BRUTALIST — acid, hard shadows, index table ─────────────────────────
CSS_BRUTALIST = r"""
:root{--acid:#e8ff00;--ink:#0a0a0a;--paper:#f5f5f0;--hot:#ff3b00;--line:#0a0a0a;
--muted:#3d3d3a;--crown-focus:#ff3b00;
--display:"Arial Black","Helvetica Neue",Impact,sans-serif;--body:Arial,Helvetica,sans-serif;
--mono:"Courier New",Courier,monospace}
body{background:var(--paper);color:var(--ink);font:400 17px/1.5 var(--body)}
.wrap{width:min(1200px,100% - 2.5rem);margin-inline:auto}
.topbar{background:var(--acid);border-bottom:3px solid var(--line);position:sticky;top:0;z-index:30}
.bar{display:flex;align-items:center;gap:1rem;padding:.8rem 0}
.brand{font-family:var(--display);font-size:1.2rem;letter-spacing:-.03em;text-decoration:none;
 text-transform:uppercase;display:flex;align-items:center;gap:.5rem}
.brand b{display:inline-block;background:var(--ink);color:var(--acid);padding:.15rem .4rem;
 transform:rotate(-3deg)}
nav{margin-inline-start:auto}
nav ul{display:flex;gap:1.2rem;list-style:none;margin:0;padding:0}
nav a{font:700 .78rem/1 var(--mono);letter-spacing:.1em;text-transform:uppercase;text-decoration:none;
 padding:.3rem 0;border-bottom:2px solid transparent}
nav a:hover{border-color:var(--hot);color:var(--hot)}
.nav-toggle{display:none;background:var(--ink);color:var(--acid);border:0;padding:.5rem .8rem;
 font:700 .8rem var(--mono);cursor:pointer}
.marquee{background:var(--ink);color:var(--acid);overflow:hidden;border-bottom:3px solid var(--line)}
.marquee div{display:flex;gap:2rem;white-space:nowrap;padding:.5rem 0;
 font:700 .74rem var(--mono);letter-spacing:.14em;text-transform:uppercase;
 animation:slide 22s linear infinite;width:max-content}
.marquee span::before{content:"✳";margin-right:2rem;color:var(--hot)}
@keyframes slide{to{transform:translateX(-50%)}}
.hero{padding:3.5rem 0 3rem;position:relative}
.kicker{display:inline-block;border:2px solid var(--line);padding:.3rem .6rem;font:700 .7rem var(--mono);
 letter-spacing:.12em;text-transform:uppercase;background:#fff;transform:rotate(-1deg)}
h1{font-family:var(--display);font-size:clamp(2.7rem,9vw,7.2rem);line-height:.9;letter-spacing:-.045em;
 text-transform:uppercase;margin:1.2rem 0 1.4rem;max-width:16ch}
h1 mark{background:var(--hot);color:#fff;padding:0 .15em;box-decoration-break:clone;-webkit-box-decoration-break:clone}
.tagline{font-size:1.1rem;max-width:52ch;border-left:5px solid var(--ink);padding-left:1rem;margin:0 0 2rem}
.hero-actions{display:flex;flex-wrap:wrap;gap:.8rem}
.btn{display:inline-block;font:700 .82rem var(--mono);letter-spacing:.08em;text-transform:uppercase;
 padding:.9rem 1.2rem;border:3px solid var(--line);background:#fff;color:var(--ink);text-decoration:none;
 box-shadow:6px 6px 0 var(--ink);transition:transform .12s,box-shadow .12s;cursor:pointer}
.btn:hover{transform:translate(3px,3px);box-shadow:3px 3px 0 var(--ink)}
.btn-primary{background:var(--acid)}
.btn-ghost{background:var(--paper)}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:0;margin-top:3rem;
 border:3px solid var(--line);background:#fff}
.metric{padding:1.2rem;border-right:3px solid var(--line)}
.metric:last-child{border-right:0}
.metric strong{display:block;font-family:var(--display);font-size:2.2rem;line-height:1}
.metric span{font:700 .68rem var(--mono);letter-spacing:.1em;text-transform:uppercase;background:var(--acid);
 display:inline-block;margin-top:.4rem;padding:.1rem .3rem}
.section{padding:3.5rem 0;border-top:3px solid var(--line)}
.sec-head{display:grid;grid-template-columns:auto 1fr;align-items:end;column-gap:1rem;row-gap:.6rem;
 margin-bottom:1.5rem}
/* A grid item stretches by default, which turned this label into a black bar
   across the whole column. Keep it a label; let the heading take the space. */
.eyebrow{font:700 .7rem var(--mono);letter-spacing:.14em;text-transform:uppercase;background:var(--ink);
 color:var(--acid);display:inline-block;justify-self:start;align-self:start;padding:.25rem .5rem;margin:0}
/* The lead belongs to the whole head, not to the narrow label column. */
.sec-head .lead{grid-column:1 / -1;justify-self:start;margin:.2rem 0 0;max-width:60ch}
.sec-head h2{justify-self:start;min-width:0}
h2{font-family:var(--display);font-size:clamp(1.8rem,5vw,3.6rem);line-height:.95;letter-spacing:-.03em;
 text-transform:uppercase;margin:0}
h3{font-family:var(--display);font-size:1.05rem;text-transform:uppercase;letter-spacing:-.01em;margin:0 0 .4rem}
.lead{font-size:1rem;max-width:55ch;margin:1rem 0 0}
.index-list{border-top:3px solid var(--line)}
.index-row{display:grid;grid-template-columns:3.5rem 1.3fr 1fr auto;gap:1.2rem;align-items:baseline;
 border-bottom:3px solid var(--line);padding:1.2rem .4rem;text-decoration:none;transition:background .15s}
.index-row:hover{background:var(--acid)}
.index-row .num{font:700 .8rem var(--mono);color:var(--hot)}
.index-row strong{font-family:var(--display);font-size:1.25rem;text-transform:uppercase;line-height:1.1}
.index-row p{margin:0;font-size:.9rem;color:var(--muted)}
.index-row .arrow{font-size:1.4rem;font-weight:700}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1.2rem}
.card{border:3px solid var(--line);background:#fff;padding:1.3rem;box-shadow:6px 6px 0 var(--ink)}
.card:hover{background:#fffef2}
.card p{font-size:.92rem;margin:.4rem 0 0;color:var(--muted)}
.meta{font:700 .68rem var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--hot);margin:0}
.tags{display:flex;gap:.35rem;flex-wrap:wrap;list-style:none;padding:0;margin:.8rem 0 0}
.tags li{font:700 .64rem var(--mono);text-transform:uppercase;border:2px solid var(--line);padding:.1rem .35rem}
.rows{display:grid;gap:0;border-top:3px solid var(--line)}
.row{display:grid;grid-template-columns:3rem 1fr 1.2fr;gap:1rem;padding:1.1rem .2rem;border-bottom:3px solid var(--line)}
.row b{font:700 .8rem var(--mono);color:var(--hot)}
.row strong{font-family:var(--display);text-transform:uppercase;font-size:1.05rem}
.row p{margin:0;color:var(--muted);font-size:.9rem}
.quote-band{background:var(--ink);color:var(--acid);padding:3.5rem 0;border-block:3px solid var(--line)}
.pullquote{font-family:var(--display);font-size:clamp(1.7rem,4.6vw,3.6rem);line-height:1;text-transform:uppercase;
 letter-spacing:-.03em;margin:0;max-width:20ch}
.pullquote cite{display:block;font:700 .72rem var(--mono);letter-spacing:.12em;margin-top:1.3rem;color:#fff}
.split{display:grid;grid-template-columns:1fr 1fr;gap:2rem}
.split h3{font-size:1.2rem}
.chips{list-style:none;display:flex;flex-wrap:wrap;gap:.5rem;padding:0;margin:1rem 0 0}
.chip{border:2px solid var(--line);background:#fff;padding:.35rem .7rem;font:700 .72rem var(--mono);
 text-transform:uppercase}
.faq details{border-bottom:3px solid var(--line);padding:1.1rem 0}
.faq summary{cursor:pointer;font-family:var(--display);text-transform:uppercase;font-size:1.05rem;
 list-style:none;display:flex;justify-content:space-between;gap:1rem}
.faq summary::-webkit-details-marker{display:none}
.faq summary::after{content:"+";color:var(--hot)}
.faq details[open] summary::after{content:"−"}
.faq p{max-width:70ch;margin:.7rem 0 0}
.contact-form{display:grid;gap:1rem;max-width:620px;border:3px solid var(--line);background:#fff;
 padding:1.4rem;box-shadow:8px 8px 0 var(--ink)}
.contact-form label{display:grid;gap:.3rem;font:700 .7rem var(--mono);letter-spacing:.1em;text-transform:uppercase}
.contact-form input,.contact-form textarea,.contact-form select{border:3px solid var(--line);
 padding:.65rem .7rem;background:var(--paper);width:100%}
.contact-form textarea{min-height:7rem;resize:vertical}
.form-status{min-height:1.4rem;font:700 .78rem var(--mono);text-transform:uppercase}
.site-footer{border-top:3px solid var(--line);padding:1.5rem 0;display:flex;flex-wrap:wrap;gap:1rem;
 justify-content:space-between;font:700 .7rem var(--mono);text-transform:uppercase;letter-spacing:.06em}
@media (max-width:820px){
 nav{display:none;position:absolute;left:0;right:0;top:100%;background:var(--acid);
 border-bottom:3px solid var(--line);padding:1rem}
 nav.is-open{display:block}
 nav ul{flex-direction:column;gap:.8rem}
 .nav-toggle{display:block}
 .index-row{grid-template-columns:2.6rem 1fr}
 .index-row p{grid-column:2}
 .index-row .arrow{display:none}
 .row{grid-template-columns:2.4rem 1fr}
 .row p{grid-column:2}
 .split{grid-template-columns:1fr}
 .metrics{grid-template-columns:1fr 1fr}
 .metric{border-bottom:3px solid var(--line)}
}
"""

# ── 04 SWISS — strict grid, hairlines, red index ───────────────────────────
CSS_SWISS = r"""
:root{--paper:#f7f7f4;--ink:#111;--muted:#6d6d6d;--red:#e0002b;--line:#d8d8d2;--crown-focus:#e0002b;
--sans:"Helvetica Neue",Helvetica,Arial,sans-serif;--mono:"Roboto Mono",Consolas,monospace}
body{background:var(--paper);color:var(--ink);font:400 17px/1.6 var(--sans);letter-spacing:-.01em}
.wrap{width:min(1240px,100% - 3rem);margin-inline:auto}
.site-header{border-bottom:1px solid var(--ink)}
.bar{display:flex;align-items:center;gap:1rem;padding:1rem 0}
.brand{font-weight:700;letter-spacing:-.04em;font-size:1rem;text-decoration:none;display:flex;align-items:center;gap:.55rem}
.brand i{width:10px;height:10px;background:var(--red);display:inline-block;font-style:normal}
nav{margin-inline-start:auto}
nav ul{display:flex;gap:1.8rem;list-style:none;margin:0;padding:0}
nav a{font-size:.8rem;letter-spacing:.02em;text-decoration:none;color:var(--muted);padding-bottom:.2rem;
 border-bottom:1px solid transparent}
nav a:hover{color:var(--ink);border-color:var(--red)}
.nav-toggle{display:none;margin-inline-start:auto;background:none;border:1px solid var(--ink);
 padding:.4rem .7rem;font-size:.8rem;cursor:pointer}
.hero{padding:4.5rem 0 3rem;display:grid;grid-template-columns:repeat(12,1fr);gap:1.5rem;align-items:start}
.hero .kicker{grid-column:1/-1;display:flex;align-items:center;gap:.6rem;
 font:400 .72rem var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin:0 0 1rem}
.hero .kicker::before{content:"";width:22px;height:22px;background:var(--red);animation:square-in .6s cubic-bezier(.2,.8,.2,1) both}
@keyframes square-in{from{transform:scale(0);opacity:0}to{transform:scale(1);opacity:1}}
h1{grid-column:1/10;font-size:clamp(2.4rem,6.4vw,5.2rem);line-height:.98;letter-spacing:-.055em;margin:0 0 1.4rem;font-weight:500}
h1 em{font-style:normal;color:var(--red)}
.tagline{grid-column:1/6;color:var(--muted);font-size:1.05rem;margin:0 0 2rem;max-width:44ch}
.hero-actions{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:.6rem;margin-top:.5rem}
.hero-index{grid-column:10/13;grid-row:1/4;border-top:1px solid var(--ink);padding-top:.7rem}
.hero-index ol{list-style:none;margin:0;padding:0;display:grid;gap:.9rem}
.hero-index li{display:grid;grid-template-columns:1.4rem 1fr;gap:.6rem;font-size:.78rem;color:var(--muted)}
.hero-index b{color:var(--red);font-family:var(--mono);font-weight:400}
.btn{display:inline-block;font-size:.78rem;letter-spacing:.03em;padding:.75rem 1.1rem;text-decoration:none;
 border:1px solid var(--ink);background:none;color:var(--ink);cursor:pointer;transition:background .15s,color .15s}
.btn:hover{background:var(--ink);color:var(--paper)}
.btn-primary{background:var(--red);border-color:var(--red);color:#fff}
.btn-primary:hover{background:var(--ink);border-color:var(--ink)}
.metrics{grid-column:1/-1;display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
 border-top:1px solid var(--ink);margin-top:2.5rem}
.metric{padding:1rem 0;border-right:1px solid var(--line)}
.metric:last-child{border-right:0}
.metric strong{display:block;font-size:1.7rem;font-weight:500;letter-spacing:-.03em;line-height:1}
.metric span{font-size:.7rem;font-family:var(--mono);text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.section{padding:3.5rem 0;border-top:1px solid var(--line)}
.sec-head{display:grid;grid-template-columns:repeat(12,1fr);gap:1.5rem;margin-bottom:2.2rem}
.eyebrow{grid-column:1/3;font:400 .7rem var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--red);margin:0}
h2{grid-column:3/10;font-size:clamp(1.6rem,3vw,2.4rem);line-height:1.1;letter-spacing:-.04em;margin:0;font-weight:500}
.lead{grid-column:3/8;color:var(--muted);font-size:.95rem;margin:.6rem 0 0;max-width:52ch}
h3{font-size:1rem;font-weight:600;margin:0 0 .3rem;letter-spacing:-.01em}
.rows{display:grid;border-top:1px solid var(--ink)}
.row{display:grid;grid-template-columns:5rem 1.1fr 1.4fr 2rem;gap:1.2rem;padding:1.2rem 0;
 border-bottom:1px solid var(--line);align-items:baseline}
.row .num{font:400 .78rem var(--mono);color:var(--red)}
.row strong{font-size:1.15rem;font-weight:500;letter-spacing:-.02em}
.row p{color:var(--muted);font-size:.9rem;margin:0}
.row .arrow{font-size:1rem;color:var(--red)}
.row:hover strong{color:var(--red)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1px;background:var(--line);
 border:1px solid var(--line)}
.card{background:var(--paper);padding:1.5rem}
.card p{color:var(--muted);font-size:.9rem;margin:.4rem 0 0}
.meta{font:400 .68rem var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--red);margin:0}
.tags{display:flex;flex-wrap:wrap;gap:.4rem;list-style:none;padding:0;margin:.9rem 0 0}
.tags li{font-size:.68rem;border:1px solid var(--line);padding:.1rem .4rem;color:var(--muted)}
.filters{display:flex;flex-wrap:wrap;gap:.4rem;margin:0 0 1.2rem}
.filter{background:none;border:1px solid var(--line);padding:.35rem .7rem;font-size:.75rem;cursor:pointer}
.filter.is-active{background:var(--red);border-color:var(--red);color:#fff}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:0;border-top:1px solid var(--ink)}
.step{border-right:1px solid var(--line);padding:1.4rem 1.2rem 1.4rem 0}
.step b{display:block;font:400 .75rem var(--mono);color:var(--red);margin-bottom:.8rem}
.step p{color:var(--muted);font-size:.9rem;margin:.3rem 0 0}
.pullquote{font-size:clamp(1.6rem,3.6vw,2.8rem);line-height:1.15;letter-spacing:-.04em;margin:0;max-width:26ch;font-weight:400}
.pullquote cite{display:block;font:400 .72rem var(--mono);letter-spacing:.08em;text-transform:uppercase;
 color:var(--muted);font-style:normal;margin-top:1.2rem}
.split{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:2rem}
.split h3{color:var(--ink)}
.split p{color:var(--muted);font-size:.92rem}
.chips{list-style:none;display:flex;flex-wrap:wrap;gap:.4rem;padding:0;margin:1rem 0 0}
.chip{border:1px solid var(--line);padding:.35rem .7rem;font-size:.78rem}
.faq details{border-bottom:1px solid var(--line);padding:1rem 0}
.faq summary{cursor:pointer;font-weight:500;list-style:none;display:flex;justify-content:space-between;gap:1rem}
.faq summary::-webkit-details-marker{display:none}
.faq summary::after{content:"+";color:var(--red);font-family:var(--mono)}
.faq details[open] summary::after{content:"−"}
.faq p{color:var(--muted);max-width:70ch;margin:.7rem 0 0;font-size:.92rem}
.contact-form{display:grid;gap:1rem;max-width:600px}
.contact-form label{display:grid;gap:.3rem;font:400 .7rem var(--mono);text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.contact-form input,.contact-form textarea,.contact-form select{border:0;border-bottom:1px solid var(--ink);
 background:transparent;padding:.6rem 0;width:100%;border-radius:0}
.contact-form textarea{min-height:6rem;resize:vertical}
.form-status{min-height:1.4rem;font-size:.82rem;color:var(--red)}
.site-footer{border-top:1px solid var(--ink);padding:1.5rem 0 2.5rem;display:flex;flex-wrap:wrap;gap:1rem;
 justify-content:space-between;font-size:.72rem;color:var(--muted);font-family:var(--mono)}
@media (max-width:860px){
 h1{grid-column:1/-1}
 .tagline{grid-column:1/-1}
 .hero-index{grid-column:1/-1;grid-row:auto}
 .sec-head{grid-template-columns:1fr}
 .eyebrow,h2,.lead{grid-column:1/-1}
 nav{display:none;width:100%}
 nav.is-open{display:block}
 nav ul{flex-direction:column;gap:.7rem;padding-top:.8rem}
 .nav-toggle{display:block}
 .bar{flex-wrap:wrap}
 .row{grid-template-columns:2.6rem 1fr;gap:.6rem}
 .row p,.row .arrow{grid-column:2}
 .step{border-right:0;border-bottom:1px solid var(--line);padding-right:0}
 .metrics{grid-template-columns:1fr 1fr}
}
"""

# ── 05 TERMINAL — phosphor, scanlines, typed hero ──────────────────────────
CSS_TERMINAL = r"""
:root{--bg:#050806;--panel:#0a120c;--ink:#b8ffc8;--muted:#4d7a5b;--accent:#41ff7e;
--accent2:#ffcf4d;--line:rgba(65,255,126,.22);--crown-focus:#41ff7e;
--mono:"Cascadia Code","SFMono-Regular",Consolas,"Courier New",monospace}
body{background:var(--bg);color:var(--ink);font:400 15px/1.7 var(--mono)}
body::after{content:"";position:fixed;inset:0;pointer-events:none;z-index:50;
 background:repeating-linear-gradient(0deg,rgba(0,0,0,.18) 0 1px,transparent 1px 3px);opacity:.45}
.wrap{width:min(1080px,100% - 2.5rem);margin-inline:auto}
.site-header{border-bottom:1px dashed var(--line);position:sticky;top:0;background:rgba(5,8,6,.92);z-index:30;
 backdrop-filter:blur(6px)}
.bar{display:flex;align-items:center;gap:1rem;padding:.7rem 0;font-size:.8rem}
.brand{text-decoration:none;color:var(--accent);display:flex;align-items:center;gap:.5rem;font-weight:700}
.brand::before{content:">_";color:var(--muted)}
.brand b{color:var(--ink)}
nav{margin-inline-start:auto}
nav ul{display:flex;gap:1.4rem;list-style:none;margin:0;padding:0}
nav a{text-decoration:none;color:var(--muted);font-size:.78rem}
nav a::before{content:"./";color:rgba(65,255,126,.35)}
nav a:hover{color:var(--accent);text-shadow:0 0 12px rgba(65,255,126,.6)}
.nav-toggle{display:none;margin-inline-start:auto;background:transparent;color:var(--accent);
 border:1px solid var(--line);padding:.35rem .6rem;font-family:var(--mono);font-size:.75rem;cursor:pointer}
.btn{display:inline-block;font-family:var(--mono);font-size:.82rem;padding:.65rem 1rem;text-decoration:none;
 border:1px solid var(--accent);color:var(--accent);background:rgba(65,255,126,.06);cursor:pointer;
 transition:background .15s,box-shadow .15s}
.btn:hover{background:rgba(65,255,126,.16);box-shadow:0 0 24px rgba(65,255,126,.25)}
.btn-primary{background:var(--accent);color:#04140a;font-weight:700}
.btn-ghost{border-color:var(--line);color:var(--ink)}
.hero{padding:3.5rem 0 2.5rem}
.kicker{font-size:.75rem;color:var(--accent2);margin:0 0 1rem;letter-spacing:.04em}
.kicker::before{content:"/* ";color:var(--muted)}
.kicker::after{content:" */";color:var(--muted)}
h1{font-size:clamp(2rem,5.4vw,3.8rem);line-height:1.1;letter-spacing:-.04em;margin:0 0 1rem;font-weight:600;
 text-shadow:0 0 28px rgba(65,255,126,.28)}
h1::after{content:"▌";color:var(--accent);animation:blink 1.1s step-end infinite;margin-left:.1em}
@keyframes blink{50%{opacity:0}}
.tagline{color:var(--muted);max-width:62ch;font-size:.95rem;border-left:2px solid var(--line);padding-left:1rem}
.tagline strong{color:var(--ink);font-weight:400}
.hero-actions{display:flex;flex-wrap:wrap;gap:.7rem;margin-top:1.8rem}
.hero-actions .hint{font-size:.72rem;color:var(--muted);align-self:center}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:1px;margin-top:2.5rem;
 background:var(--line);border:1px solid var(--line)}
.metric{background:var(--panel);padding:1rem 1.1rem}
.metric strong{display:block;color:var(--accent);font-size:1.5rem;line-height:1.1}
.metric span{font-size:.7rem;color:var(--muted);text-transform:lowercase}
.section{padding:2.8rem 0;border-top:1px dashed var(--line)}
.sec-head{margin-bottom:1.6rem}
.eyebrow{color:var(--accent2);font-size:.72rem;letter-spacing:.08em;margin:0 0 .5rem;text-transform:lowercase}
.eyebrow::before{content:"## ";color:var(--muted)}
h2{font-size:clamp(1.4rem,3.2vw,2.1rem);letter-spacing:-.03em;margin:0 0 .4rem;color:var(--ink);font-weight:600}
h3{font-size:.95rem;margin:0 0 .3rem;color:var(--ink)}
.lead{color:var(--muted);font-size:.85rem;max-width:64ch}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:1rem}
.card{background:var(--panel);border:1px solid var(--line);padding:1.1rem;position:relative;
 transition:border-color .15s,transform .15s}
.card:hover{border-color:var(--accent);transform:translateY(-2px)}
.card::before{content:"+";position:absolute;right:.6rem;top:.4rem;color:var(--muted);font-size:.8rem}
.card p{color:var(--muted);font-size:.82rem;margin:.4rem 0 0}
.meta{color:var(--accent2);font-size:.68rem;margin:0;text-transform:lowercase}
.tags{display:flex;gap:.35rem;flex-wrap:wrap;list-style:none;padding:0;margin:.7rem 0 0}
.tags li{font-size:.64rem;border:1px solid var(--line);padding:.05rem .35rem;color:var(--muted)}
.term-block{background:#020503;border:1px solid var(--line);padding:1rem 1.1rem;margin:0 0 1rem;
 box-shadow:inset 0 0 40px rgba(65,255,126,.05)}
.term-line{display:flex;gap:.7rem;font-size:.82rem;padding:.2rem 0}
.term-line .prompt{color:var(--accent);user-select:none}
.term-line .cmd{color:var(--ink)}
.term-line .out{color:var(--muted)}
.rows{border-top:1px solid var(--line);margin-top:1rem}
.row{display:grid;grid-template-columns:2.5rem 1fr 1.4fr;gap:1rem;padding:.8rem 0;border-bottom:1px solid var(--line);
 font-size:.82rem;align-items:baseline}
.row b{color:var(--accent2);font-weight:400}
.row strong{color:var(--accent);font-weight:400}
.row p{margin:0;color:var(--muted)}
.code-card{background:#020503;border:1px solid var(--line);padding:1rem;margin:0 0 .8rem;overflow-x:auto}
.code-card code{font-family:var(--mono);color:var(--accent);font-size:.8rem;white-space:pre}
.code-card .label{font-size:.68rem;color:var(--muted);margin:0 0 .4rem}
.steps{display:grid;gap:.7rem}
.step{display:grid;grid-template-columns:2rem 1fr;gap:.8rem;font-size:.85rem}
.step b{color:var(--accent2);font-weight:400}
.step p{margin:0;color:var(--muted)}
.pullquote{font-size:clamp(1.2rem,2.6vw,1.8rem);line-height:1.4;margin:0;color:var(--ink);max-width:40ch;font-weight:400}
.pullquote::before{content:"“";color:var(--accent)}
.pullquote::after{content:"”";color:var(--accent)}
.pullquote cite{display:block;font-size:.72rem;color:var(--muted);font-style:normal;margin-top:.8rem}
.pullquote cite::before{content:"— "}
.split{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1.5rem}
.split h3{color:var(--accent)}
.split p{color:var(--muted);font-size:.85rem}
.chips{list-style:none;display:flex;flex-wrap:wrap;gap:.4rem;padding:0;margin:1rem 0 0}
.chip{border:1px solid var(--line);padding:.25rem .55rem;font-size:.72rem;color:var(--muted)}
.faq details{border-bottom:1px dashed var(--line);padding:.9rem 0}
.faq summary{cursor:pointer;list-style:none;color:var(--ink);font-size:.88rem;display:flex;gap:.5rem}
.faq summary::before{content:"?";color:var(--accent2)}
.faq summary::-webkit-details-marker{display:none}
.faq p{color:var(--muted);margin:.6rem 0 0 .9rem;font-size:.82rem;max-width:70ch}
.contact-form{display:grid;gap:.8rem;max-width:600px;border:1px solid var(--line);padding:1.2rem;background:var(--panel)}
.contact-form label{display:grid;gap:.25rem;font-size:.72rem;color:var(--muted)}
.contact-form input,.contact-form textarea,.contact-form select{background:#020503;border:1px solid var(--line);
 color:var(--ink);padding:.6rem .7rem;font-family:var(--mono);font-size:.82rem;width:100%}
.contact-form textarea{min-height:6rem;resize:vertical}
.form-status{min-height:1.4rem;color:var(--accent2);font-size:.78rem}
.site-footer{border-top:1px dashed var(--line);padding:1.5rem 0;display:flex;flex-wrap:wrap;gap:1rem;
 justify-content:space-between;color:var(--muted);font-size:.72rem}
@media (max-width:820px){
 nav{display:none;width:100%;order:5}
 nav.is-open{display:block;padding-top:.6rem}
 nav ul{flex-direction:column;gap:.6rem}
 .nav-toggle{display:block}
 .bar{flex-wrap:wrap}
 .row{grid-template-columns:2rem 1fr}
 .row p{grid-column:2}
}
"""

# ── 06 ORGANIC — warm paper, blobs, product cards ──────────────────────────
CSS_ORGANIC = r"""
:root{--paper:#f4f1e8;--surface:#fffdf6;--ink:#22301f;--muted:#6a7761;--green:#3f6b46;
--clay:#d98c5f;--line:#ded8c8;--crown-focus:#3f6b46;
--serif:"Palatino Linotype",Palatino,Georgia,serif;--sans:"Segoe UI",system-ui,sans-serif}
body{background:var(--paper);color:var(--ink);font:400 17px/1.75 var(--sans)}
.wrap{width:min(1140px,100% - 2.8rem);margin-inline:auto}
.site-header{position:sticky;top:0;z-index:30;background:rgba(244,241,232,.9);backdrop-filter:blur(10px);
 border-bottom:1px solid var(--line)}
.bar{display:flex;align-items:center;gap:1rem;padding:1rem 0}
.brand{display:flex;align-items:center;gap:.6rem;text-decoration:none;font-family:var(--serif);
 font-size:1.25rem;letter-spacing:-.02em}
.brand svg{width:26px;height:26px}
nav{margin-inline-start:auto}
nav ul{display:flex;gap:1.4rem;list-style:none;margin:0;padding:0}
nav a{font-size:.85rem;text-decoration:none;color:var(--muted);padding-bottom:.25rem;border-bottom:1px solid transparent}
nav a:hover{color:var(--green);border-color:var(--clay)}
.nav-toggle{display:none;margin-inline-start:auto;background:var(--surface);border:1px solid var(--line);
 border-radius:999px;padding:.45rem .8rem;font-size:.8rem;cursor:pointer}
.btn{display:inline-flex;align-items:center;gap:.45rem;font-family:var(--sans);font-size:.9rem;
 padding:.8rem 1.3rem;border-radius:999px;text-decoration:none;border:1px solid transparent;cursor:pointer;
 transition:transform .2s,background .2s}
.btn:hover{transform:translateY(-2px)}
.btn-primary{background:var(--green);color:#fffdf6}
.btn-ghost{border-color:var(--line);color:var(--ink);background:var(--surface)}
.hero{position:relative;padding:4.5rem 0 3rem;display:grid;grid-template-columns:1.1fr .9fr;gap:3rem;align-items:center}
.kicker{display:inline-block;font-size:.72rem;letter-spacing:.16em;text-transform:uppercase;color:var(--green);
 background:#e6ead9;padding:.3rem .7rem;border-radius:999px;margin:0 0 1rem}
h1{font-family:var(--serif);font-size:clamp(2.4rem,5.6vw,4.4rem);line-height:1.02;letter-spacing:-.04em;
 margin:0 0 1.1rem;font-weight:400}
h1 em{font-style:italic;color:var(--green)}
.tagline{color:var(--muted);font-size:1.05rem;max-width:48ch;margin:0 0 1.8rem}
.hero-actions{display:flex;flex-wrap:wrap;gap:.7rem}
.hero-art{position:relative;aspect-ratio:1/1;max-width:420px;justify-self:end;width:100%}
.leaf{position:absolute;border-radius:62% 38% 55% 45%/48% 55% 45% 52%;
 background:linear-gradient(145deg,#5f8a5f,#2f5238);box-shadow:0 24px 50px rgba(47,82,56,.22);
 animation:sway 9s ease-in-out infinite alternate}
.leaf-1{inset:6% 18% 34% 6%;transform:rotate(-12deg)}
.leaf-2{inset:28% 4% 8% 38%;background:linear-gradient(145deg,#e3b48f,#c17a4b);
 animation-delay:-3s;transform:rotate(9deg)}
.leaf-3{inset:52% 46% 6% 14%;background:linear-gradient(145deg,#8fa87c,#4e6b4e);
 animation-delay:-6s;transform:rotate(-4deg)}
.leaf-4{width:48px;height:48px;right:16%;top:8%;border-radius:50%;background:var(--clay);opacity:.7}
@keyframes sway{from{transform:translateY(0) rotate(-2deg)}to{transform:translateY(-14px) rotate(3deg)}}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1.2rem;margin-top:3rem;
 border-top:1px solid var(--line);padding-top:1.6rem}
.metric strong{display:block;font-family:var(--serif);font-size:2rem;line-height:1;color:var(--green)}
.metric span{font-size:.78rem;color:var(--muted)}
.section{padding:3.5rem 0;border-top:1px solid var(--line)}
.sec-head{max-width:60ch;margin-bottom:2rem}
.eyebrow{font-size:.72rem;letter-spacing:.16em;text-transform:uppercase;color:var(--clay);margin:0 0 .6rem}
h2{font-family:var(--serif);font-size:clamp(1.7rem,3.8vw,2.7rem);line-height:1.1;letter-spacing:-.03em;
 margin:0 0 .5rem;font-weight:400}
h3{font-family:var(--serif);font-size:1.15rem;margin:0 0 .3rem;font-weight:400}
.lead{color:var(--muted);max-width:58ch}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:1.2rem}
.card{background:var(--surface);border:1px solid var(--line);border-radius:24px;padding:1.5rem;
 box-shadow:0 10px 30px rgba(34,48,31,.05);transition:transform .25s,box-shadow .25s}
.card:hover{transform:translateY(-4px);box-shadow:0 18px 40px rgba(34,48,31,.1)}
.card p{color:var(--muted);font-size:.92rem;margin:.4rem 0 0}
.product{display:flex;flex-direction:column;background:var(--surface);border:1px solid var(--line);
 border-radius:26px;overflow:hidden;transition:transform .25s}
.product:hover{transform:translateY(-4px)}
.product-art{height:150px;background:
 radial-gradient(circle at 50% 38%,#7ba36f 0 22%,transparent 23%),
 radial-gradient(circle at 34% 56%,#4e7a4e 0 26%,transparent 27%),
 radial-gradient(circle at 66% 58%,#5f8f5c 0 24%,transparent 25%),
 linear-gradient(160deg,#ece7d7,#d9d2bc)}
.product:nth-child(2) .product-art{background:
 radial-gradient(circle at 46% 40%,#e8a0a8 0 20%,transparent 21%),
 radial-gradient(circle at 58% 58%,#d97b86 0 26%,transparent 27%),
 linear-gradient(160deg,#f4e6dc,#e2cfc0)}
.product:nth-child(3) .product-art{background:
 radial-gradient(circle at 50% 46%,#8bab72 0 25%,transparent 26%),
 radial-gradient(circle at 36% 64%,#6b8f58 0 22%,transparent 23%),
 linear-gradient(160deg,#e9ecd9,#d3d9bd)}
.product-body{padding:1.1rem 1.2rem 1.3rem;display:flex;flex-direction:column;gap:.3rem}
.product .price{margin-left:auto;font-family:var(--serif);color:var(--green);font-size:1.1rem}
.product-head{display:flex;align-items:baseline;gap:.5rem}
.product p{font-size:.85rem;color:var(--muted);margin:0}
.product .add{margin-top:.8rem;align-self:flex-start;border:1px solid var(--line);background:transparent;
 border-radius:999px;padding:.35rem .8rem;font-size:.75rem;color:var(--green);cursor:pointer}
.product .add:hover{background:var(--green);color:#fff;border-color:var(--green)}
.tags{display:flex;gap:.35rem;flex-wrap:wrap;list-style:none;padding:0;margin:.3rem 0 0}
.tags li{font-size:.65rem;background:#e9ecdd;color:var(--green);border-radius:999px;padding:.12rem .5rem}
.filters{display:flex;flex-wrap:wrap;gap:.5rem;margin:0 0 1.3rem}
.filter{background:transparent;border:1px solid var(--line);border-radius:999px;padding:.35rem .8rem;
 font-size:.78rem;color:var(--muted);cursor:pointer}
.filter.is-active{background:var(--green);border-color:var(--green);color:#fff}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1.2rem}
.steps .step{position:relative;padding-left:2.2rem}
.steps .step::before{content:"";position:absolute;left:0;top:.35rem;width:12px;height:12px;
 border-radius:50%;background:var(--green);box-shadow:0 0 0 5px #dfe6d1}
.steps .step b{display:block;font-size:.72rem;letter-spacing:.12em;color:var(--clay);text-transform:uppercase;margin-bottom:.3rem}
.step p{color:var(--muted);font-size:.9rem;margin:.2rem 0 0}
.split{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:2rem}
.split h3{color:var(--green)}
.split p{color:var(--muted);font-size:.92rem}
.pullquote{font-family:var(--serif);font-size:clamp(1.6rem,3.6vw,2.6rem);line-height:1.25;letter-spacing:-.02em;
 margin:0;max-width:28ch;font-style:italic}
.pullquote cite{display:block;font:400 .8rem var(--sans);font-style:normal;color:var(--muted);margin-top:1rem}
.chips{list-style:none;display:flex;flex-wrap:wrap;gap:.5rem;padding:0;margin:1rem 0 0}
.chip{background:#e9ecdd;color:var(--green);border-radius:999px;padding:.35rem .8rem;font-size:.8rem}
.faq details{border-bottom:1px solid var(--line);padding:1.1rem 0}
.faq summary{cursor:pointer;font-family:var(--serif);font-size:1.05rem;list-style:none;
 display:flex;justify-content:space-between;gap:1rem}
.faq summary::-webkit-details-marker{display:none}
.faq summary::after{content:"＋";color:var(--clay)}
.faq details[open] summary::after{content:"−"}
.faq p{color:var(--muted);max-width:70ch;margin:.7rem 0 0;font-size:.92rem}
.contact-form{display:grid;gap:1rem;max-width:600px;background:var(--surface);border:1px solid var(--line);
 border-radius:26px;padding:1.5rem}
.contact-form label{display:grid;gap:.35rem;font-size:.8rem;color:var(--muted)}
.contact-form input,.contact-form textarea,.contact-form select{background:var(--paper);border:1px solid var(--line);
 border-radius:14px;padding:.7rem .9rem;width:100%;color:var(--ink)}
.contact-form textarea{min-height:7rem;resize:vertical}
.form-status{min-height:1.4rem;color:var(--green);font-size:.85rem}
.site-footer{border-top:1px solid var(--line);padding:2rem 0 2.5rem;display:flex;flex-wrap:wrap;gap:1rem;
 justify-content:space-between;color:var(--muted);font-size:.78rem}
@media (max-width:840px){
 .hero{grid-template-columns:1fr;gap:2rem}
 .hero-art{max-width:300px;justify-self:center}
 nav{display:none;width:100%;order:5}
 nav.is-open{display:block;padding-top:.7rem}
 nav ul{flex-direction:column;gap:.7rem}
 .nav-toggle{display:block}
 .bar{flex-wrap:wrap}
}
"""

# ── 07 LUXURY — ink and gold, framed, slow ─────────────────────────────────
CSS_LUXURY = r"""
:root{--ink:#0c0f14;--panel:#12161e;--cream:#f3eee4;--gold:#c9a227;--gold-soft:#e8d9b5;
--muted:#a49a86;--line:rgba(201,162,39,.28);--crown-focus:#c9a227;
--display:"Didot","Bodoni MT","Playfair Display",Georgia,serif;
--sans:"Optima","Segoe UI",system-ui,sans-serif}
body{background:var(--ink);color:var(--cream);font:400 16px/1.75 var(--sans);letter-spacing:.02em}
.wrap{width:min(1120px,100% - 3rem);margin-inline:auto}
.site-header{position:absolute;top:0;left:0;right:0;z-index:20}
.bar{display:flex;align-items:center;gap:1rem;padding:1.3rem 0;border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:.7rem;text-decoration:none;font-family:var(--display);
 font-size:1.15rem;letter-spacing:.24em;text-transform:uppercase;color:var(--gold-soft)}
.brand .crest{width:30px;height:30px;border:1px solid var(--gold);display:grid;place-items:center;
 font-size:.65rem;color:var(--gold);font-family:var(--sans);letter-spacing:.1em}
nav{margin-inline-start:auto}
nav ul{display:flex;gap:2rem;list-style:none;margin:0;padding:0}
nav a{font-size:.7rem;letter-spacing:.2em;text-transform:uppercase;text-decoration:none;color:var(--muted);
 padding-bottom:.3rem;border-bottom:1px solid transparent}
nav a:hover{color:var(--gold);border-color:var(--gold)}
.nav-toggle{display:none;margin-inline-start:auto;background:transparent;border:1px solid var(--line);
 color:var(--gold-soft);padding:.4rem .7rem;font-size:.68rem;letter-spacing:.16em;text-transform:uppercase;cursor:pointer}
.hero{position:relative;min-height:92vh;display:grid;place-items:center;text-align:center;padding:8rem 0 5rem;
 overflow:hidden;border-bottom:1px solid var(--line)}
.hero-scene{position:absolute;inset:0;z-index:0;
 background:
  radial-gradient(900px 500px at 72% 12%,rgba(201,162,39,.16),transparent 60%),
  radial-gradient(700px 500px at 20% 88%,rgba(80,96,120,.25),transparent 65%),
  linear-gradient(180deg,#0a0d12,#121722 55%,#0a0d12)}
.hero-scene::after{content:"";position:absolute;inset:0;opacity:.25;
 background-image:repeating-linear-gradient(90deg,rgba(201,162,39,.14) 0 1px,transparent 1px 120px),
 repeating-linear-gradient(0deg,rgba(201,162,39,.08) 0 1px,transparent 1px 120px)}
.hero .frame{position:absolute;inset:2rem;border:1px solid var(--line);pointer-events:none;z-index:1;animation:frame-in 1.4s ease both}
@keyframes frame-in{from{opacity:0;transform:scale(1.02)}to{opacity:1;transform:none}}
.hero-inner{position:relative;z-index:2;max-width:820px}
.kicker{font-size:.68rem;letter-spacing:.34em;text-transform:uppercase;color:var(--gold);margin:0 0 1.6rem}
h1{font-family:var(--display);font-size:clamp(2.6rem,6.6vw,5.4rem);line-height:1.04;letter-spacing:-.02em;
 font-weight:400;margin:0 0 1.4rem}
h1 em{font-style:italic;color:var(--gold-soft)}
.tagline{color:var(--muted);font-size:1rem;max-width:58ch;margin:0 auto 2.4rem;line-height:1.9}
.hero-actions{display:flex;flex-wrap:wrap;gap:1rem;justify-content:center}
.btn{display:inline-block;font-size:.68rem;letter-spacing:.24em;text-transform:uppercase;text-decoration:none;
 padding:.95rem 1.6rem;border:1px solid var(--gold);color:var(--gold);background:transparent;cursor:pointer;
 transition:background .3s,color .3s}
.btn:hover{background:var(--gold);color:#0c0f14}
.btn-primary{background:var(--gold);color:#0c0f14}
.btn-primary:hover{background:var(--gold-soft);border-color:var(--gold-soft)}
.metrics{display:flex;justify-content:center;flex-wrap:wrap;gap:3.5rem;margin-top:4rem;
 padding-top:2rem;border-top:1px solid var(--line);max-width:640px;margin-inline:auto}
.metric{text-align:center}
.metric strong{display:block;font-family:var(--display);font-size:1.7rem;color:var(--gold-soft);font-weight:400;line-height:1}
.metric span{font-size:.62rem;letter-spacing:.22em;text-transform:uppercase;color:var(--muted)}
.section{padding:5rem 0;border-bottom:1px solid var(--line)}
.sec-head{max-width:640px;margin:0 auto 3rem;text-align:center}
.eyebrow{font-size:.64rem;letter-spacing:.32em;text-transform:uppercase;color:var(--gold);margin:0 0 1rem}
h2{font-family:var(--display);font-size:clamp(1.8rem,4vw,3rem);font-weight:400;letter-spacing:-.01em;margin:0 0 .8rem}
h3{font-family:var(--display);font-size:1.25rem;font-weight:400;margin:0 0 .3rem}
.lead{color:var(--muted);font-size:.95rem;line-height:1.9;margin:0 auto;max-width:54ch}
.frames{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1.5rem}
.suite{border:1px solid var(--line);background:var(--panel);overflow:hidden;transition:border-color .3s}
.suite:hover{border-color:var(--gold)}
.suite-art{aspect-ratio:4/3;background:
 radial-gradient(120% 80% at 20% 10%,rgba(232,217,181,.35),transparent 55%),
 linear-gradient(145deg,#1b2330,#0e1218 60%,#2a2115)}
.suite:nth-child(2) .suite-art{background:
 radial-gradient(120% 80% at 80% 10%,rgba(201,162,39,.32),transparent 55%),
 linear-gradient(145deg,#232a2f,#101418 60%,#1c2a2c)}
.suite-body{padding:1.4rem 1.5rem 1.6rem}
.suite .price{font-size:.66rem;letter-spacing:.2em;text-transform:uppercase;color:var(--gold);margin:0 0 .5rem}
.suite p{font-size:.88rem;color:var(--muted);margin:.3rem 0 0}
.split{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:3rem;align-items:start}
.split h3{color:var(--gold-soft)}
.split p{color:var(--muted);font-size:.92rem;line-height:1.9}
.pullquote{font-family:var(--display);font-size:clamp(1.7rem,4vw,2.9rem);font-weight:400;line-height:1.3;
 letter-spacing:-.01em;margin:0;max-width:30ch;font-style:italic}
.pullquote cite{display:block;font-family:var(--sans);font-style:normal;font-size:.64rem;letter-spacing:.28em;
 text-transform:uppercase;color:var(--gold);margin-top:1.6rem}
.chips{list-style:none;display:flex;flex-wrap:wrap;gap:.6rem;padding:0;margin:1rem 0 0;justify-content:center}
.chip{border:1px solid var(--line);padding:.4rem .9rem;font-size:.68rem;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1.5rem}
.card{border:1px solid var(--line);padding:1.6rem;background:rgba(255,255,255,.015)}
.card p{color:var(--muted);font-size:.88rem;margin:.4rem 0 0}
.meta{font-size:.64rem;letter-spacing:.2em;text-transform:uppercase;color:var(--gold);margin:0}
.tags{display:flex;flex-wrap:wrap;gap:.4rem;list-style:none;padding:0;margin:.8rem 0 0}
.tags li{font-size:.6rem;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);border:1px solid var(--line);padding:.1rem .45rem}
.filters{display:flex;flex-wrap:wrap;gap:.6rem;margin:0 0 1.6rem;justify-content:center}
.filter{background:transparent;border:1px solid var(--line);color:var(--muted);padding:.35rem .8rem;
 font-size:.64rem;letter-spacing:.16em;text-transform:uppercase;cursor:pointer}
.filter.is-active{border-color:var(--gold);color:var(--gold)}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:2rem;text-align:center}
.steps .step b{display:block;font-family:var(--display);font-size:1.8rem;color:var(--gold);font-weight:400;margin-bottom:.6rem}
.step p{color:var(--muted);font-size:.88rem;margin:.3rem 0 0}
.faq details{border-bottom:1px solid var(--line);padding:1.2rem 0}
.faq summary{cursor:pointer;font-family:var(--display);font-size:1.1rem;list-style:none;display:flex;
 justify-content:space-between;gap:1rem;letter-spacing:.02em}
.faq summary::-webkit-details-marker{display:none}
.faq summary::after{content:"+";color:var(--gold);font-family:var(--sans)}
.faq details[open] summary::after{content:"−"}
.faq p{color:var(--muted);max-width:70ch;margin:.8rem 0 0;font-size:.9rem}
.contact-form{display:grid;gap:1.2rem;max-width:560px;margin:0 auto}
.contact-form label{display:grid;gap:.4rem;font-size:.62rem;letter-spacing:.2em;text-transform:uppercase;color:var(--muted)}
.contact-form input,.contact-form textarea,.contact-form select{background:transparent;color:var(--cream);
 border:0;border-bottom:1px solid var(--line);padding:.6rem 0;width:100%;border-radius:0;font-family:var(--sans)}
.contact-form textarea{min-height:6rem;resize:vertical}
.contact-form input:focus,.contact-form textarea:focus{outline:none;border-color:var(--gold)}
.form-status{min-height:1.4rem;font-size:.76rem;color:var(--gold);text-align:center}
.site-footer{padding:2.5rem 0;display:flex;flex-wrap:wrap;gap:1rem;justify-content:space-between;
 font-size:.62rem;letter-spacing:.18em;text-transform:uppercase;color:var(--muted)}
@media (max-width:840px){
 nav{display:none;position:absolute;left:0;right:0;top:100%;background:#0c0f14;border-bottom:1px solid var(--line);
 padding:1rem 1.5rem}
 nav.is-open{display:block}
 nav ul{flex-direction:column;gap:1rem}
 .nav-toggle{display:block}
 .hero{min-height:auto;padding:7rem 0 4rem}
 .hero .frame{inset:1rem}
 .metrics{gap:2rem}
}
"""

# ── 08 POP — candy palette, stickers, bouncy ───────────────────────────────
CSS_POP = r"""
:root{--cream:#fff7ec;--ink:#17141f;--pink:#ff4d6d;--lime:#b8ff3d;--violet:#7c3aed;
--blue:#3b82f6;--yellow:#ffd23f;--muted:#6b6577;--line:#17141f;--crown-focus:#7c3aed;
--display:"Arial Rounded MT Bold","Trebuchet MS","Segoe UI",sans-serif;
--body:"Trebuchet MS","Segoe UI",sans-serif}
body{background:var(--cream);color:var(--ink);font:400 17px/1.6 var(--body)}
body::before{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;opacity:.5;
 background-image:radial-gradient(var(--pink) 1.5px,transparent 1.6px),
  radial-gradient(var(--violet) 1.5px,transparent 1.6px);
 background-size:48px 48px,48px 48px;background-position:0 0,24px 24px;
 -webkit-mask-image:linear-gradient(180deg,#000,transparent 55%);mask-image:linear-gradient(180deg,#000,transparent 55%)}
.wrap{width:min(1140px,100% - 2.6rem);margin-inline:auto;position:relative;z-index:1}
.site-header{position:sticky;top:1rem;z-index:30;width:min(1140px,100% - 2.6rem);margin:1rem auto 0;
 background:#fff;border:2px solid var(--line);border-radius:20px;box-shadow:5px 5px 0 var(--ink)}
.bar{display:flex;align-items:center;gap:1rem;padding:.7rem 1rem}
.brand{display:flex;align-items:center;gap:.55rem;text-decoration:none;font-family:var(--display);
 font-size:1.15rem;letter-spacing:-.02em}
.brand .dot{width:26px;height:26px;border-radius:50%;background:var(--pink);border:2px solid var(--ink);
 display:grid;place-items:center;font-size:.8rem;color:#fff;transform:rotate(-8deg)}
nav{margin-inline-start:auto}
nav ul{display:flex;gap:.3rem;list-style:none;margin:0;padding:0}
nav a{display:block;text-decoration:none;font-size:.85rem;padding:.4rem .7rem;border-radius:999px;
 border:2px solid transparent}
nav a:hover{background:var(--lime);border-color:var(--ink)}
.nav-toggle{display:none;margin-inline-start:auto;background:var(--yellow);border:2px solid var(--ink);
 border-radius:999px;padding:.4rem .8rem;font-size:.8rem;cursor:pointer;box-shadow:3px 3px 0 var(--ink)}
.btn{display:inline-flex;align-items:center;gap:.4rem;font-family:var(--display);font-size:.9rem;
 padding:.8rem 1.3rem;border-radius:999px;border:2px solid var(--ink);text-decoration:none;cursor:pointer;
 box-shadow:4px 4px 0 var(--ink);transition:transform .12s,box-shadow .12s}
.btn:hover{transform:translate(2px,2px);box-shadow:2px 2px 0 var(--ink)}
.btn-primary{background:var(--pink);color:#fff}
.btn-ghost{background:#fff;color:var(--ink)}
.hero{padding:4rem 0 2.5rem;text-align:center;position:relative}
.kicker{display:inline-block;background:var(--lime);border:2px solid var(--ink);border-radius:999px;
 padding:.3rem .9rem;font-family:var(--display);font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;
 transform:rotate(-2deg);margin:0 0 1.2rem;box-shadow:3px 3px 0 var(--ink)}
h1{font-family:var(--display);font-size:clamp(2.6rem,7.5vw,5.4rem);line-height:.98;letter-spacing:-.045em;
 margin:0 0 1.2rem}
h1 mark{background:var(--yellow);padding:0 .12em;border-radius:8px;box-decoration-break:clone;
 -webkit-box-decoration-break:clone;box-shadow:inset 0 -.18em 0 var(--pink)}
.tagline{color:var(--muted);font-size:1.05rem;max-width:52ch;margin:0 auto 2rem}
.hero-actions{display:flex;flex-wrap:wrap;gap:.8rem;justify-content:center}
.sticker{position:absolute;font-family:var(--display);font-size:.72rem;background:var(--violet);color:#fff;
 border:2px solid var(--ink);border-radius:50%;width:88px;height:88px;display:grid;place-items:center;
 text-align:center;line-height:1.15;box-shadow:4px 4px 0 var(--ink);cursor:pointer;user-select:none}
.sticker-1{left:4%;top:22%;transform:rotate(-14deg);background:var(--blue)}
.sticker-2{right:5%;top:14%;transform:rotate(11deg);background:var(--pink)}
.sticker-3{right:9%;bottom:8%;transform:rotate(-6deg);background:var(--violet);width:72px;height:72px}
.sticker.spin{animation:spin .6s cubic-bezier(.3,1.6,.4,1)}
@keyframes spin{to{transform:rotate(360deg) scale(1.08)}}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1rem;margin-top:3rem}
.metric{background:#fff;border:2px solid var(--ink);border-radius:18px;padding:1rem;box-shadow:4px 4px 0 var(--ink)}
.metric:nth-child(2){background:#e8f9c8}
.metric:nth-child(3){background:#ffe7ec}
.metric:nth-child(4){background:#e6e0ff}
.metric strong{display:block;font-family:var(--display);font-size:1.9rem;line-height:1;letter-spacing:-.03em}
.metric span{font-size:.75rem;color:var(--muted)}
.section{padding:3.5rem 0}
.sec-head{max-width:600px;margin:0 auto 2rem;text-align:center}
.eyebrow{display:inline-block;font-family:var(--display);font-size:.72rem;letter-spacing:.08em;
 text-transform:uppercase;color:var(--violet);margin:0 0 .6rem}
h2{font-family:var(--display);font-size:clamp(1.7rem,4vw,2.8rem);line-height:1.05;letter-spacing:-.035em;margin:0 0 .6rem}
h3{font-family:var(--display);font-size:1.08rem;margin:0 0 .3rem;letter-spacing:-.01em}
.lead{color:var(--muted);max-width:56ch;margin:0 auto}
.mosaic{display:grid;grid-template-columns:repeat(6,1fr);gap:1rem}
.product{grid-column:span 2;background:#fff;border:2px solid var(--ink);border-radius:22px;overflow:hidden;
 box-shadow:5px 5px 0 var(--ink);transition:transform .18s}
.product:hover{transform:translateY(-5px) rotate(-.5deg)}
.product:nth-child(1){background:#ffe7ec}
.product:nth-child(2){background:#fff}
.product:nth-child(3){background:#f0eaff}
.product:nth-child(4){background:#e8f9c8}
.product:nth-child(5){background:#fff6d6}
.product:nth-child(6){background:#e3f2ff}
.product-art{height:120px;display:grid;place-items:center;font-size:2.8rem;border-bottom:2px solid var(--ink)}
.product-body{padding:1rem 1.1rem 1.2rem}
.product-head{display:flex;align-items:baseline;gap:.5rem}
.product .price{margin-left:auto;font-family:var(--display);font-size:1rem;background:#fff;border:2px solid var(--ink);
 border-radius:999px;padding:.05rem .45rem}
.product p{font-size:.85rem;color:var(--muted);margin:.3rem 0 0}
.product .add{margin-top:.7rem;border:2px solid var(--ink);background:var(--yellow);border-radius:999px;
 padding:.3rem .7rem;font-family:var(--display);font-size:.75rem;cursor:pointer;box-shadow:2px 2px 0 var(--ink)}
.product .add:hover{background:var(--pink);color:#fff}
.tags{display:flex;gap:.3rem;flex-wrap:wrap;list-style:none;padding:0;margin:.4rem 0 0}
.tags li{font-size:.62rem;border:1.5px solid var(--ink);border-radius:999px;padding:.05rem .4rem;background:#fff}
.filters{display:flex;flex-wrap:wrap;gap:.5rem;margin:0 0 1.4rem;justify-content:center}
.filter{background:#fff;border:2px solid var(--ink);border-radius:999px;padding:.35rem .8rem;
 font-family:var(--display);font-size:.75rem;cursor:pointer;box-shadow:2px 2px 0 var(--ink)}
.filter.is-active{background:var(--lime)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:1.1rem}
.card{background:#fff;border:2px solid var(--ink);border-radius:22px;padding:1.4rem;box-shadow:5px 5px 0 var(--ink)}
.card:nth-child(2n){background:#fff6d6}
.card p{color:var(--muted);font-size:.9rem;margin:.3rem 0 0}
.meta{font-family:var(--display);font-size:.7rem;color:var(--violet);text-transform:uppercase;letter-spacing:.06em;margin:0}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;counter-reset:step}
.steps .step{background:#fff;border:2px solid var(--ink);border-radius:22px;padding:1.2rem;box-shadow:5px 5px 0 var(--ink)}
.steps .step b{display:grid;place-items:center;width:32px;height:32px;border-radius:50%;background:var(--pink);
 color:#fff;border:2px solid var(--ink);font-family:var(--display);margin-bottom:.7rem}
.step p{color:var(--muted);font-size:.88rem;margin:.2rem 0 0}
.split{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:1.2rem}
.split h3{color:var(--violet)}
.split p{color:var(--muted);font-size:.9rem}
.pullquote{font-family:var(--display);font-size:clamp(1.6rem,4vw,2.8rem);line-height:1.06;letter-spacing:-.03em;
 margin:0;max-width:24ch;text-align:center;margin-inline:auto}
.pullquote cite{display:block;font-family:var(--body);font-size:.85rem;font-style:normal;color:var(--muted);
 margin-top:1rem;letter-spacing:0}
.chips{list-style:none;display:flex;flex-wrap:wrap;gap:.5rem;padding:0;margin:1rem 0 0;justify-content:center}
.chip{background:#fff;border:2px solid var(--ink);border-radius:999px;padding:.3rem .7rem;font-size:.78rem;
 box-shadow:2px 2px 0 var(--ink)}
.faq details{background:#fff;border:2px solid var(--ink);border-radius:16px;padding:1rem 1.1rem;margin-bottom:.7rem;
 box-shadow:4px 4px 0 var(--ink)}
.faq summary{cursor:pointer;font-family:var(--display);font-size:1rem;list-style:none;display:flex;
 justify-content:space-between;gap:1rem}
.faq summary::-webkit-details-marker{display:none}
.faq summary::after{content:"+";color:var(--pink);font-size:1.2rem;line-height:1}
.faq details[open] summary::after{content:"−"}
.faq p{color:var(--muted);margin:.6rem 0 0;font-size:.9rem}
.contact-form{display:grid;gap:.9rem;max-width:560px;margin:0 auto;background:#fff;border:2px solid var(--ink);
 border-radius:24px;padding:1.4rem;box-shadow:6px 6px 0 var(--ink)}
.contact-form label{display:grid;gap:.3rem;font-family:var(--display);font-size:.75rem;color:var(--muted)}
.contact-form input,.contact-form textarea,.contact-form select{border:2px solid var(--ink);border-radius:12px;
 padding:.6rem .7rem;background:var(--cream);width:100%}
.contact-form textarea{min-height:6rem;resize:vertical}
.form-status{min-height:1.4rem;font-size:.82rem;color:var(--violet);font-weight:700}
.site-footer{border-top:2px solid var(--ink);margin-top:2rem;padding:1.5rem 0 2rem;display:flex;flex-wrap:wrap;
 gap:1rem;justify-content:space-between;font-size:.78rem;color:var(--muted)}
@media (max-width:840px){
 nav{display:none;position:absolute;left:0;right:0;top:calc(100% + .6rem);background:#fff;
 border:2px solid var(--ink);border-radius:18px;padding:.8rem;box-shadow:4px 4px 0 var(--ink)}
 nav.is-open{display:block}
 nav ul{flex-direction:column;gap:.2rem}
 .nav-toggle{display:block}
 .mosaic{grid-template-columns:1fr 1fr}
 .product{grid-column:span 1}
 .sticker{display:none}
}
"""

# ── 09 CINEMATIC — full-bleed stills, letterbox, filmstrip ─────────────────
CSS_CINEMATIC = r"""
:root{--black:#050505;--panel:#0d0d0f;--ink:#f5f3ef;--muted:#9a9791;--amber:#e8c547;
--ember:#ff5a36;--line:rgba(245,243,239,.16);--crown-focus:#e8c547;
--display:Impact,Haettenschweiler,"Arial Narrow Bold",sans-serif;
--body:"Segoe UI",system-ui,sans-serif;--mono:"Courier New",monospace}
body{background:var(--black);color:var(--ink);font:400 16px/1.7 var(--body)}
.wrap{width:min(1200px,100% - 3rem);margin-inline:auto}
.site-header{position:absolute;top:0;left:0;right:0;z-index:20;border-bottom:1px solid var(--line);
 background:linear-gradient(180deg,rgba(5,5,5,.85),transparent)}
.bar{display:flex;align-items:center;gap:1rem;padding:1.1rem 0}
.brand{text-decoration:none;font-family:var(--display);font-size:1.3rem;letter-spacing:.2em;text-transform:uppercase}
.brand span{color:var(--amber)}
nav{margin-inline-start:auto}
nav ul{display:flex;gap:1.7rem;list-style:none;margin:0;padding:0}
nav a{text-decoration:none;font-size:.68rem;letter-spacing:.2em;text-transform:uppercase;color:var(--muted);
 padding-bottom:.25rem;border-bottom:1px solid transparent}
nav a:hover{color:var(--amber);border-color:var(--amber)}
.nav-toggle{display:none;margin-inline-start:auto;background:transparent;border:1px solid var(--line);
 color:var(--ink);padding:.4rem .7rem;font-size:.68rem;letter-spacing:.14em;text-transform:uppercase;cursor:pointer}
.hero{position:relative;min-height:100svh;display:flex;align-items:flex-end;padding:9rem 0 4.5rem;overflow:hidden}
.letterbox{position:absolute;inset:0;z-index:0;animation:ken 26s ease-in-out infinite alternate;
 background:
  radial-gradient(1100px 600px at 70% 18%,rgba(232,197,71,.22),transparent 55%),
  radial-gradient(900px 700px at 18% 88%,rgba(255,90,54,.24),transparent 60%),
  radial-gradient(700px 500px at 50% 55%,rgba(62,80,120,.35),transparent 65%),
  linear-gradient(180deg,#060608,#0c0d12 50%,#140d0a)}
@keyframes ken{from{transform:scale(1)}to{transform:scale(1.08)}}
.letterbox::before{content:"";position:absolute;inset:0;opacity:.5;
 background-image:radial-gradient(rgba(255,255,255,.22) .5px,transparent .6px);background-size:3px 3px}
.letterbox::after{content:"";position:absolute;inset:0;
 background:linear-gradient(0deg,var(--black) 2%,transparent 42%),linear-gradient(180deg,var(--black) 0%,transparent 25%)}
.hero .wrap{position:relative;z-index:2}
.kicker{display:flex;align-items:center;gap:.8rem;font-size:.68rem;letter-spacing:.26em;text-transform:uppercase;
 color:var(--amber);margin:0 0 1.2rem}
.kicker::before{content:"";width:44px;height:1px;background:var(--amber)}
h1{font-family:var(--display);font-size:clamp(2.8rem,8.5vw,7rem);line-height:.92;letter-spacing:.01em;
 text-transform:uppercase;margin:0 0 1.4rem;max-width:15ch}
h1 em{font-style:normal;color:var(--amber)}
.tagline{color:#cfcbc4;max-width:52ch;font-size:1rem;margin:0 0 2rem}
.hero-actions{display:flex;flex-wrap:wrap;gap:.7rem}
.btn{display:inline-block;font-size:.7rem;letter-spacing:.2em;text-transform:uppercase;text-decoration:none;
 padding:.85rem 1.4rem;border:1px solid var(--line);color:var(--ink);cursor:pointer;transition:background .2s,color .2s}
.btn:hover{border-color:var(--amber);color:var(--amber)}
.btn-primary{background:var(--amber);border-color:var(--amber);color:#0a0a0a}
.btn-primary:hover{background:var(--ink);border-color:var(--ink);color:#0a0a0a}
.hero-meta{display:flex;gap:2.5rem;flex-wrap:wrap;margin-top:3rem;padding-top:1.2rem;border-top:1px solid var(--line);
 font-size:.66rem;letter-spacing:.16em;text-transform:uppercase;color:var(--muted)}
.metrics{display:flex;flex-wrap:wrap;gap:3rem;margin-top:2.5rem}
.metric strong{display:block;font-family:var(--display);font-size:2.2rem;letter-spacing:.02em;line-height:1;color:var(--amber)}
.metric span{font-size:.6rem;letter-spacing:.18em;text-transform:uppercase;color:var(--muted)}
.section{padding:4.5rem 0;border-top:1px solid var(--line)}
.sec-head{display:flex;align-items:flex-end;justify-content:space-between;gap:2rem;margin-bottom:2rem}
.eyebrow{font-size:.64rem;letter-spacing:.24em;text-transform:uppercase;color:var(--amber);margin:0 0 .8rem}
h2{font-family:var(--display);font-size:clamp(1.9rem,4.6vw,3.4rem);line-height:.95;text-transform:uppercase;
 letter-spacing:.01em;margin:0}
h3{font-family:var(--display);font-size:1.2rem;letter-spacing:.04em;text-transform:uppercase;margin:0 0 .3rem}
.lead{color:var(--muted);font-size:.9rem;max-width:40ch;margin:0}
.filmstrip{display:flex;gap:1.2rem;overflow-x:auto;padding-bottom:1.4rem;scroll-snap-type:x mandatory;
 cursor:grab;scrollbar-width:thin}
.filmstrip::-webkit-scrollbar{height:4px}
.filmstrip::-webkit-scrollbar-thumb{background:var(--amber)}
.still{flex:0 0 320px;scroll-snap-align:start;border:1px solid var(--line);background:var(--panel)}
.still-art{aspect-ratio:16/10;position:relative;overflow:hidden;
 background:linear-gradient(140deg,#2a1c12,#0e1218 62%,#1b2430)}
.still:nth-child(2) .still-art{background:linear-gradient(140deg,#1b2430,#0c1014 62%,#2b2114)}
.still:nth-child(3) .still-art{background:linear-gradient(140deg,#301c1c,#12100e 62%,#222a1d)}
.still:nth-child(4) .still-art{background:linear-gradient(140deg,#20202c,#0b0f16 62%,#2c2416)}
.still:nth-child(5) .still-art{background:linear-gradient(140deg,#16242a,#0a0f12 62%,#2a1d12)}
.still-art::after{content:"";position:absolute;inset:0;
 background:radial-gradient(120% 90% at 50% 120%,rgba(232,197,71,.22),transparent 55%)}
.still-body{padding:1rem 1.1rem 1.2rem}
.still .meta{font-size:.62rem;letter-spacing:.16em;text-transform:uppercase;color:var(--amber);margin:0 0 .4rem}
.still p{font-size:.84rem;color:var(--muted);margin:.3rem 0 0}
.tags{display:none}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:2rem}
.steps .step{border-top:1px solid var(--line);padding-top:1rem}
.steps .step b{display:block;font-family:var(--display);font-size:1.7rem;color:var(--amber);margin-bottom:.5rem}
.step p{color:var(--muted);font-size:.86rem;margin:.2rem 0 0}
.split{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:3rem}
.split h3{color:var(--amber)}
.split p{color:var(--muted);font-size:.9rem}
.pullquote{font-family:var(--display);font-size:clamp(1.8rem,5vw,3.8rem);line-height:1;text-transform:uppercase;
 letter-spacing:.01em;margin:0;max-width:22ch}
.pullquote cite{display:block;font-family:var(--body);font-style:normal;font-size:.64rem;letter-spacing:.2em;
 text-transform:uppercase;color:var(--amber);margin-top:1.4rem}
.chips{list-style:none;display:flex;flex-wrap:wrap;gap:.5rem;padding:0;margin:1rem 0 0}
.chip{border:1px solid var(--line);font-size:.64rem;letter-spacing:.14em;text-transform:uppercase;
 padding:.35rem .7rem;color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1.2rem}
.card{border:1px solid var(--line);padding:1.4rem;background:var(--panel)}
.card p{color:var(--muted);font-size:.86rem;margin:.3rem 0 0}
.meta{font-size:.62rem;letter-spacing:.16em;text-transform:uppercase;color:var(--amber);margin:0}
.filters{display:flex;flex-wrap:wrap;gap:.5rem;margin:0 0 1.4rem}
.filter{background:transparent;border:1px solid var(--line);color:var(--muted);padding:.4rem .8rem;
 font-size:.62rem;letter-spacing:.16em;text-transform:uppercase;cursor:pointer}
.filter.is-active{border-color:var(--amber);color:var(--amber)}
.faq details{border-bottom:1px solid var(--line);padding:1.1rem 0}
.faq summary{cursor:pointer;font-size:.95rem;list-style:none;display:flex;justify-content:space-between;gap:1rem;
 letter-spacing:.02em}
.faq summary::-webkit-details-marker{display:none}
.faq summary::after{content:"+";color:var(--amber)}
.faq details[open] summary::after{content:"−"}
.faq p{color:var(--muted);max-width:70ch;margin:.7rem 0 0;font-size:.88rem}
.contact-form{display:grid;gap:1rem;max-width:560px}
.contact-form label{display:grid;gap:.35rem;font-size:.62rem;letter-spacing:.16em;text-transform:uppercase;color:var(--muted)}
.contact-form input,.contact-form textarea,.contact-form select{background:var(--panel);border:1px solid var(--line);
 color:var(--ink);padding:.7rem .8rem;width:100%;border-radius:0}
.contact-form textarea{min-height:6rem;resize:vertical}
.form-status{min-height:1.4rem;font-size:.8rem;color:var(--amber)}
.site-footer{border-top:1px solid var(--line);padding:2rem 0;display:flex;flex-wrap:wrap;gap:1rem;
 justify-content:space-between;font-size:.64rem;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
@media (max-width:840px){
 nav{display:none;position:absolute;left:0;right:0;top:100%;background:#070707;border-bottom:1px solid var(--line);
 padding:1rem 1.5rem}
 nav.is-open{display:block}
 nav ul{flex-direction:column;gap:1rem}
 .nav-toggle{display:block}
 .hero{min-height:auto;padding:7rem 0 3.5rem}
 .filmstrip .still{flex-basis:78vw}
 .sec-head{flex-direction:column;align-items:flex-start;gap:.6rem}
}
"""

# ── 10 NEWSROOM — masthead, ticker, columns, sparkline ─────────────────────
CSS_NEWSROOM = r"""
:root{--paper:#fbfaf7;--surface:#fff;--ink:#141414;--muted:#5f5f5f;--red:#c8102e;--navy:#003366;
--line:#d6d3cb;--crown-focus:#c8102e;
--display:"Franklin Gothic Medium","Arial Narrow",Impact,sans-serif;--body:Georgia,"Times New Roman",serif;
--sans:"Segoe UI",system-ui,sans-serif;--mono:"Courier New",monospace}
body{background:var(--paper);color:var(--ink);font:400 17px/1.65 var(--body)}
.wrap{width:min(1220px,100% - 2.6rem);margin-inline:auto}
.site-header{border-bottom:1px solid var(--ink);background:var(--paper)}
.bar{display:flex;align-items:center;gap:1rem;padding:.5rem 0;border-bottom:1px solid var(--line)}
.brand{display:none}
.mast-date{font:400 .68rem/1.6 var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.mast-right{margin-left:auto;font:400 .68rem/1.6 var(--mono);text-transform:uppercase;color:var(--muted)}
nav ul{display:flex;gap:1.6rem;list-style:none;margin:0;padding:.55rem 0;flex-wrap:wrap}
nav a{font:600 .72rem/1 var(--sans);letter-spacing:.04em;text-transform:uppercase;text-decoration:none;
 color:var(--ink);padding-bottom:.3rem;border-bottom:2px solid transparent}
nav a:hover{color:var(--red);border-color:var(--red)}
.nav-toggle{display:none;margin-inline-start:auto;background:none;border:1px solid var(--ink);
 padding:.35rem .6rem;font:600 .68rem var(--sans);letter-spacing:.06em;text-transform:uppercase;cursor:pointer}
.ticker{background:var(--ink);color:var(--paper);overflow:hidden;border-bottom:1px solid var(--ink)}
.ticker div{display:flex;gap:2.4rem;width:max-content;padding:.55rem 0;white-space:nowrap;
 animation:ticker 32s linear infinite;font:400 .7rem/1 var(--mono);letter-spacing:.04em}
.ticker b{color:#7dffb2;font-weight:400}
.ticker i{color:#ff8f9c;font-style:normal}
@keyframes ticker{to{transform:translateX(-50%)}}
.wordmark{font-family:var(--display);font-size:clamp(2.4rem,7vw,5rem);line-height:1;text-align:center;
 letter-spacing:-.02em;margin:1.2rem 0 .2rem;text-transform:uppercase}
.wordmark span{color:var(--red)}
.mast-tag{text-align:center;font:400 .66rem var(--mono);letter-spacing:.16em;text-transform:uppercase;
 color:var(--muted);margin:0 0 1rem}
.hero{display:grid;grid-template-columns:1.7fr .9fr;gap:2.2rem;padding:1.5rem 0 2rem;border-bottom:1px solid var(--ink)}
.kicker{display:flex;align-items:center;gap:.6rem;font:700 .68rem var(--sans);letter-spacing:.1em;
 text-transform:uppercase;color:var(--red);margin:0 0 .7rem}
.kicker::before{content:"";width:7px;height:7px;background:var(--red)}
h1{font-family:var(--display);font-size:clamp(2rem,4.6vw,3.7rem);line-height:1.02;letter-spacing:-.025em;
 margin:0 0 1rem;font-weight:500}
h1 em{font-style:normal;background:linear-gradient(transparent 62%,#ffe08a 62%);padding:0 .05em}
.tagline{font-size:1.08rem;line-height:1.6;color:var(--muted);max-width:56ch;margin:0 0 1.4rem}
.byline{font:400 .68rem var(--mono);text-transform:uppercase;letter-spacing:.08em;color:var(--muted);
 padding-top:.8rem;border-top:1px solid var(--line)}
.hero-actions{display:flex;flex-wrap:wrap;gap:.6rem;margin-top:1.3rem}
.btn{display:inline-block;font:600 .72rem var(--sans);letter-spacing:.05em;text-transform:uppercase;
 padding:.7rem 1rem;border:1px solid var(--ink);background:none;color:var(--ink);text-decoration:none;cursor:pointer}
.btn-primary{background:var(--red);border-color:var(--red);color:#fff}
.btn-ghost:hover{background:var(--ink);color:var(--paper)}
.hero-side{border-left:1px solid var(--line);padding-left:1.6rem}
.hero-side h3{font-family:var(--display);font-size:1.05rem;text-transform:uppercase;letter-spacing:.02em;
 margin:0 0 .6rem;padding-bottom:.4rem;border-bottom:2px solid var(--ink)}
.side-item{padding:.75rem 0;border-bottom:1px solid var(--line)}
.side-item:last-child{border-bottom:0}
.side-item .meta{font:700 .62rem var(--sans);text-transform:uppercase;letter-spacing:.08em;color:var(--red);margin:0 0 .2rem}
.side-item strong{font-family:var(--body);font-size:.98rem;line-height:1.35;font-weight:700;display:block}
.side-item p{margin:.2rem 0 0;font-size:.82rem;color:var(--muted)}
.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:0;border-bottom:1px solid var(--ink)}
.metric{padding:.9rem 1rem .9rem 0;border-right:1px solid var(--line)}
.metric:last-child{border-right:0}
.metric strong{display:block;font:600 1.1rem var(--mono);line-height:1.2}
.metric span{font:400 .62rem var(--sans);text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.section{padding:2.5rem 0;border-bottom:1px solid var(--ink)}
.sec-head{display:flex;align-items:baseline;justify-content:space-between;gap:1rem;
 border-bottom:2px solid var(--ink);padding-bottom:.5rem;margin-bottom:1.4rem}
.eyebrow{font:700 .66rem var(--sans);letter-spacing:.12em;text-transform:uppercase;color:var(--red);margin:0}
h2{font-family:var(--display);font-size:clamp(1.5rem,3vw,2.2rem);letter-spacing:-.02em;margin:0;font-weight:500}
.lead{color:var(--muted);font-size:.88rem;margin:.6rem 0 0;max-width:60ch}
.columns{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:0}
.story{padding:0 1.3rem;border-right:1px solid var(--line)}
.story:first-child{padding-left:0}
.story:last-child{border-right:0;padding-right:0}
.story .meta{font:700 .62rem var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--red);margin:0 0 .35rem}
.story h3{font-family:var(--body);font-size:1.22rem;line-height:1.25;font-weight:700;margin:0 0 .35rem}
.story p{font-size:.9rem;color:var(--muted);margin:0}
.story:hover h3{text-decoration:underline;text-decoration-color:var(--red);text-underline-offset:3px}
.chart{display:grid;grid-template-columns:1fr 2fr;gap:2rem;align-items:center}
.chart-copy h3{font-family:var(--display);font-size:1.3rem;margin:0 0 .3rem}
.chart-copy p{color:var(--muted);font-size:.86rem;margin:0 0 .8rem}
.spark{width:100%;height:auto;border-left:1px solid var(--line);border-bottom:1px solid var(--ink)}
.spark .line{fill:none;stroke:var(--red);stroke-width:2.5}
.spark .area{fill:url(#sparkfill);opacity:.35}
.spark .dot{fill:var(--red)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1.2rem}
.card{background:var(--surface);border:1px solid var(--line);padding:1.2rem}
.card p{color:var(--muted);font-size:.88rem;margin:.3rem 0 0}
.meta{font:700 .62rem var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--red);margin:0}
.tags{display:flex;flex-wrap:wrap;gap:.4rem;list-style:none;padding:0;margin:.7rem 0 0}
.tags li{font:400 .62rem var(--mono);text-transform:uppercase;border:1px solid var(--line);padding:.1rem .4rem;color:var(--muted)}
.filters{display:flex;flex-wrap:wrap;gap:.4rem;margin:0 0 1.2rem}
.filter{background:none;border:1px solid var(--line);padding:.35rem .7rem;font:600 .66rem var(--sans);
 text-transform:uppercase;letter-spacing:.05em;cursor:pointer}
.filter.is-active{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1.4rem}
.steps .step{border-top:3px solid var(--ink);padding-top:.8rem}
.steps .step b{display:block;font-family:var(--display);font-size:1.1rem;margin-bottom:.3rem}
.step p{color:var(--muted);font-size:.88rem;margin:.2rem 0 0}
.split{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:2rem}
.split h3{font-family:var(--display);font-size:1.1rem}
.split p{color:var(--muted);font-size:.9rem}
.pullquote{font-family:var(--display);font-size:clamp(1.5rem,3.6vw,2.6rem);line-height:1.15;letter-spacing:-.02em;
 margin:0;max-width:28ch;font-weight:500}
.pullquote cite{display:block;font:400 .64rem var(--mono);letter-spacing:.1em;text-transform:uppercase;
 font-style:normal;color:var(--muted);margin-top:1rem}
.chips{list-style:none;display:flex;flex-wrap:wrap;gap:.4rem;padding:0;margin:1rem 0 0}
.chip{font:400 .66rem var(--mono);text-transform:uppercase;border:1px solid var(--line);padding:.25rem .5rem;color:var(--muted)}
.faq details{border-bottom:1px solid var(--line);padding:1rem 0}
.faq summary{cursor:pointer;font-family:var(--body);font-weight:700;font-size:1rem;list-style:none;
 display:flex;justify-content:space-between;gap:1rem}
.faq summary::-webkit-details-marker{display:none}
.faq summary::after{content:"+";color:var(--red);font-family:var(--mono)}
.faq details[open] summary::after{content:"−"}
.faq p{color:var(--muted);max-width:70ch;margin:.6rem 0 0;font-size:.9rem}
.contact-form{display:grid;gap:.9rem;max-width:560px}
.contact-form label{display:grid;gap:.3rem;font:700 .64rem var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.contact-form input,.contact-form textarea,.contact-form select{background:var(--surface);border:1px solid var(--line);
 padding:.6rem .7rem;width:100%;border-radius:0;font-family:var(--body)}
.contact-form textarea{min-height:6rem;resize:vertical}
.form-status{min-height:1.4rem;font:400 .8rem var(--sans);color:var(--red)}
.site-footer{padding:1.6rem 0 2.4rem;display:flex;flex-wrap:wrap;gap:1rem;justify-content:space-between;
 font:400 .66rem var(--mono);text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
@media (max-width:840px){
 .hero{grid-template-columns:1fr}
 .hero-side{border-left:0;border-top:1px solid var(--ink);padding-left:0;padding-top:1rem}
 nav{display:none;width:100%}
 nav.is-open{display:block}
 nav ul{flex-direction:column;gap:.5rem}
 .nav-toggle{display:block}
 .bar{flex-wrap:wrap}
 .story{border-right:0;padding:0 0 1rem;border-bottom:1px solid var(--line)}
 .story:last-child{border-bottom:0}
 .columns{grid-template-columns:1fr}
 .chart{grid-template-columns:1fr;gap:1rem}
 .metrics{grid-template-columns:1fr 1fr}
}
"""

STUDIOS: dict[str, dict] = {
    "aurora": {
        "key": "aurora", "name": "Aurora", "label": "Glass / lightfield",
        "summary": "Dark glass surfaces, drifting colour fields and an asymmetric bento grid.",
        "motion": "Drifting light orbs, staggered reveals, animated counters.",
        "palette": ["#070b16", "#7c5cff", "#22d3ee", "#f4f7ff"],
        "type": "Inter · tight display, gradient emphasis",
        "css": CSS_AURORA,
    },
    "editorial": {
        "key": "editorial", "name": "Editorial", "label": "Paper / magazine",
        "summary": "Masthead, double rules, numbered story rows and a drop-cap opener.",
        "motion": "Reading progress rule, clip reveals, no bounce.",
        "palette": ["#f4efe6", "#b23a2b", "#1f4e46", "#1a1713"],
        "type": "Georgia · italic display, small-caps mono labels",
        "css": CSS_EDITORIAL,
    },
    "brutalist": {
        "key": "brutalist", "name": "Brutalist", "label": "Acid / protest",
        "summary": "Acid yellow, 3 px borders, hard offset shadows and an index table.",
        "motion": "Infinite marquee, hard-cut hovers, no easing theatre.",
        "palette": ["#e8ff00", "#ff3b00", "#f5f5f0", "#0a0a0a"],
        "type": "Arial Black · all caps, mono metadata",
        "css": CSS_BRUTALIST,
    },
    "swiss": {
        "key": "swiss", "name": "Swiss", "label": "Grid / reduction",
        "summary": "Strict 12-column grid, hairline rules, red index numbers, no radius.",
        "motion": "Hairline draws, restrained fades, precise hovers.",
        "palette": ["#f7f7f4", "#e0002b", "#111111", "#d8d8d2"],
        "type": "Helvetica Neue · medium display, mono figures",
        "css": CSS_SWISS,
    },
    "terminal": {
        "key": "terminal", "name": "Terminal", "label": "Phosphor / CLI",
        "summary": "Phosphor green on black, scanlines, typed hero and a command table.",
        "motion": "Caret blink, typed prompt, terminal hover glow.",
        "palette": ["#050806", "#41ff7e", "#ffcf4d", "#b8ffc8"],
        "type": "Cascadia Code · everything monospace",
        "css": CSS_TERMINAL,
    },
    "organic": {
        "key": "organic", "name": "Organic", "label": "Botanical / warm",
        "summary": "Warm paper, serif headlines, swaying leaf shapes and soft product cards.",
        "motion": "Slow leaf sway, gentle reveal, soft hover lift.",
        "palette": ["#f4f1e8", "#3f6b46", "#d98c5f", "#22301f"],
        "type": "Palatino · serif display, humanist body",
        "css": CSS_ORGANIC,
    },
    "luxury": {
        "key": "luxury", "name": "Luxury", "label": "Ink / gold",
        "summary": "Full-height framed hero, ink and gold, serif display, generous space.",
        "motion": "Slow fades, gold hairline sweeps, no bounce.",
        "palette": ["#0c0f14", "#c9a227", "#e8d9b5", "#f3eee4"],
        "type": "Didot · display serif, wide-tracked sans labels",
        "css": CSS_LUXURY,
    },
    "pop": {
        "key": "pop", "name": "Pop", "label": "Candy / playful",
        "summary": "Candy palette, 2 px outlines, sticker badges and a mosaic product grid.",
        "motion": "Bouncy hover, sticker spin on click, spring shadows.",
        "palette": ["#fff7ec", "#ff4d6d", "#b8ff3d", "#7c3aed"],
        "type": "Arial Rounded · chunky display, friendly body",
        "css": CSS_POP,
    },
    "cinematic": {
        "key": "cinematic", "name": "Cinematic", "label": "Film / full-bleed",
        "summary": "Full-viewport lightfield, letterboxed display type and a draggable filmstrip.",
        "motion": "Slow ken-burns field, filmstrip drag, dot-grain texture.",
        "palette": ["#050505", "#e8c547", "#ff5a36", "#f5f3ef"],
        "type": "Impact · condensed caps, sans body",
        "css": CSS_CINEMATIC,
    },
    "newsroom": {
        "key": "newsroom", "name": "Newsroom", "label": "Broadsheet / data",
        "summary": "Masthead, live ticker, column rules, a lead story and an SVG sparkline.",
        "motion": "Ticker crawl, headline underline, no bounce.",
        "palette": ["#fbfaf7", "#c8102e", "#003366", "#141414"],
        "type": "Franklin Gothic · condensed display, Georgia body",
        "css": CSS_NEWSROOM,
    },
}

ORDER = ["aurora", "editorial", "brutalist", "swiss", "terminal",
         "organic", "luxury", "pop", "cinematic", "newsroom"]


def studio_css(key: str) -> str:
    return BASE_CSS + "\n" + STUDIOS.get(key, STUDIOS["aurora"])["css"]


def studio(key: str) -> dict:
    return STUDIOS.get(key, STUDIOS["aurora"])
