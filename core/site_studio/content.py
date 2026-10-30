"""core/site_studio/content.py — content model for the multi-studio site engine.

Every site is data first: copy, sections and interactions. The studio renderer
turns that data into a complete page. Ten curated sites live here so the
showcase is reproducible without a model, and ``plan_to_content`` adapts the
planner output used by the live Crown Code site pipeline.
"""

from __future__ import annotations

import hashlib
import re

# ── Curated showcase sites ────────────────────────────────────────────────
# Each one is a different industry, voice, palette, layout and motion system.
# The same schema feeds model-planned sites through plan_to_content().

SAMPLE_SITES: list[dict] = [
    {
        "id": "01",
        "folder": "01_halcyon_aurora",
        "studio": "aurora",
        "category": "SaaS · AI",
        "brand": "Halcyon",
        "title": "Halcyon — observability for AI systems",
        "kicker": "AI observability",
        "headline": "See what your models are thinking.",
        "deck": "Trace every prompt, score every answer and catch regressions before your users do. Halcyon turns noisy model behaviour into a signal your team can ship on.",
        "cta": ("Start free", "Read the docs"),
        "nav": [("Product", "#features"), ("How it works", "#flow"),
                ("Pricing", "#stats"), ("FAQ", "#faq")],
        "stats": [{"value": "38M", "label": "traces / day"},
                  {"value": "99.98%", "label": "ingest uptime"},
                  {"value": "−63%", "label": "time to first fix"},
                  {"value": "4.9/5", "label": "developer rating"}],
        "sections": [
            {"id": "features", "kind": "cards", "eyebrow": "The platform",
             "heading": "One surface for the whole model lifecycle",
             "lead": "Instrument once, then watch quality, latency and spend move together.",
             "items": [
                 {"title": "Trace every prompt", "text": "Span-level replay of retrieval, tools and tokens. Filter by latency, cost, user or evaluation score.",
                  "meta": "01 · Tracing", "tags": ["Tracing"]},
                 {"title": "Evals in CI", "text": "Run golden-set evals on every deploy. Fail the build when groundedness or tone drops below the line.",
                  "meta": "02 · Quality", "tags": ["Evals"]},
                 {"title": "Cost guardrails", "text": "Per-feature budgets with hard stops. Know which prompt template is quietly burning your margin.",
                  "meta": "03 · Spend", "tags": ["Cost"]},
                 {"title": "Incident replay", "text": "Rewind a bad hour of traffic, diff two model versions and share a read-only report with the room.",
                  "meta": "04 · Debugging", "tags": ["Replay"]},
             ]},
            {"id": "flow", "kind": "steps", "eyebrow": "How it works",
             "heading": "Live in an afternoon",
             "lead": "Drop in the SDK, point at your gateway, and keep your existing tooling.",
             "items": [
                 {"title": "Instrument", "text": "One middleware wraps your provider calls. No proxy required."},
                 {"title": "Score", "text": "Attach evaluators to a sample of traffic and watch the distribution."},
                 {"title": "Ship", "text": "Gate deploys on the metrics you chose, then replay any incident."},
             ]},
            {"id": "voices", "kind": "testimonials", "eyebrow": "Teams",
             "heading": "Trusted where answers matter",
             "lead": "Support, research and platform teams share one view of model quality.",
             "items": [
                 {"title": "Ravi Shah", "meta": "Head of Platform, Northwind", "text": "We cut our mean time to diagnose a bad response from two days to nineteen minutes."},
                 {"title": "Elena Duarte", "meta": "Staff ML Engineer, Klar", "text": "The eval gate is the first tool our model reviewers actually asked to keep."},
             ]},
            {"id": "faq", "kind": "faq", "eyebrow": "Answers",
             "heading": "Before you start", "lead": "", "items": []},
            {"id": "contact", "kind": "contact", "eyebrow": "Get started",
             "heading": "Put your models under a lens", "lead": "Tell us what you are running and we will set up a workspace with your data.", "items": []},
        ],
        "faq": [
            {"q": "Does Halcyon proxy my traffic?", "a": "No. The SDK sends spans asynchronously to our collector; requests go straight to your provider."},
            {"q": "Which providers are supported?", "a": "OpenAI, Anthropic, Google, Bedrock and any OpenAI-compatible endpoint, including local Ollama."},
            {"q": "Can I keep data in my region?", "a": "Yes. EU and US collectors are available on the team plan, with 30-day retention by default."},
        ],
        "contact": {"heading": "Start a workspace", "lead": "No credit card. 200k spans included each month.",
                    "fields": [("Work email", "email", "email", "you@company.com"),
                               ("Team size", "size", "select", "1–10"),
                               ("What are you building?", "message", "textarea", "RAG assistant, support agent…")],
                    "submit": "Request access",
                    "note": "We reply within one working day."},
        "footer": "Halcyon Labs, Inc. — observability for systems that talk back.",
        "note": "Aurora/glass studio · drifting lightfield, bento grid, animated counters.",
    },
    {
        "id": "02",
        "folder": "02_quiet_index_editorial",
        "studio": "editorial",
        "category": "Media · Culture",
        "brand": "The Quiet Index",
        "title": "The Quiet Index — Issue 14",
        "kicker": "Issue 14 · Autumn 2026",
        "headline": "The luxury of paying attention.",
        "deck": "A quarterly print magazine about the people who choose depth over noise — craftsmen, archivists, night-shift nurses and one very patient lighthouse keeper.",
        "cta": ("Read the issue", "Subscribe"),
        "nav": [("Essays", "#essays"), ("Interviews", "#interviews"),
                ("Archive", "#archive"), ("Subscribe", "#subscribe")],
        "stats": [{"value": "14", "label": "issues published"},
                  {"value": "22k", "label": "print readers"},
                  {"value": "0", "label": "advertisers"}],
        "sections": [
            {"id": "essays", "kind": "articles", "eyebrow": "The issue",
             "heading": "What we could not stop thinking about",
             "lead": "Four pieces from the new issue, printed here in full for the first two weeks.",
             "items": [
                 {"title": "The last lighthouse keeper", "meta": "Essay · 18 min", "tags": ["Coast"],
                  "text": "Ewan has logged every ship that passed his window since 1994. What happens when the light becomes automatic?"},
                 {"title": "A room for mending", "meta": "Report · 11 min", "tags": ["Craft"],
                  "text": "Inside a repair café in Lisbon where broken lamps arrive with letters explaining their history."},
                 {"title": "Night shift", "meta": "Interview · 9 min", "tags": ["Work"],
                  "text": "Nurse Amara Okafor on the small rituals that make a twelve-hour shift feel human."},
                 {"title": "Index of quiet places", "meta": "Archive · 6 min", "tags": ["Maps"],
                  "text": "Eleven reading rooms, three ferries and one library that opens at 3 a.m."},
             ]},
            {"id": "interviews", "kind": "quote", "eyebrow": "From the interview",
             "heading": "“Attention is the only thing you cannot automate.”",
             "lead": "Mira Halvorsen, bookbinder, Oslo",
             "items": []},
            {"id": "archive", "kind": "list", "eyebrow": "Archive",
             "heading": "Selected back issues",
             "lead": "Every issue is printed on 90 gsm uncoated paper and never reprinted.",
             "items": [
                 {"title": "Issue 13 — The long walk", "meta": "Summer 2026", "text": "Pilgrimage, boredom and the case for walking nowhere in particular."},
                 {"title": "Issue 12 — Tools of the trade", "meta": "Spring 2026", "text": "Nine makers on the object they would rescue from a fire."},
                 {"title": "Issue 11 — After the algorithm", "meta": "Winter 2025", "text": "Culture after the feed: slower, stranger, more alive."},
             ]},
            {"id": "faq", "kind": "faq", "eyebrow": "Reader notes", "heading": "About the magazine", "lead": "", "items": []},
            {"id": "subscribe", "kind": "contact", "eyebrow": "Subscribe",
             "heading": "Four issues, one quiet year", "lead": "Print worldwide, digital included, cancel whenever.", "items": []},
        ],
        "faq": [
            {"q": "How often does it arrive?", "a": "Four issues a year, posted in the first week of March, June, September and December."},
            {"q": "Do you ship outside Europe?", "a": "Yes — worldwide shipping is included in the annual price, with tracked delivery."},
            {"q": "Is there a digital edition?", "a": "Every subscriber gets a DRM-free PDF and access to the full online archive."},
        ],
        "contact": {"heading": "One quiet year", "lead": "€48 for four print issues, posted anywhere.",
                    "fields": [("Name", "name", "text", "Your name"),
                               ("Email", "email", "email", "you@example.com"),
                               ("Where should we post it?", "address", "text", "Street, city, postcode")],
                    "submit": "Subscribe",
                    "note": "You will receive a confirmation, not a newsletter."},
        "footer": "The Quiet Index · Printed in Ghent · ISSN 2776-0142",
        "note": "Editorial studio · paper palette, masthead, numbered story rows, drop caps.",
    },
    {
        "id": "03",
        "folder": "03_studio_loud_brutalist",
        "studio": "brutalist",
        "category": "Design · Studio",
        "brand": "STUDIO LOUD",
        "title": "Studio Loud — Independent design practice",
        "kicker": "Independent design practice · est. 2019",
        "headline": "WE MAKE BRANDS THAT SHOUT INDOORS.",
        "deck": "Identity, packaging and digital for companies that would rather be remembered than liked. Six people, one studio, no account managers.",
        "cta": ("START A PROJECT", "SEE THE WORK"),
        "nav": [("WORK", "#work"), ("SERVICES", "#services"),
                ("ABOUT", "#about"), ("CONTACT", "#contact")],
        "stats": [{"value": "41", "label": "brands launched"},
                  {"value": "6", "label": "people, no more"},
                  {"value": "12", "label": "design awards"}],
        "sections": [
            {"id": "work", "kind": "index", "eyebrow": "Selected work",
             "heading": "PROJECTS WITH A PULSE",
             "lead": "A small list, because we only take four projects a year.",
             "items": [
                 {"title": "GUT PUNCH — energy drink", "meta": "2026 · Identity + packaging", "tags": ["Identity"],
                  "text": "A drinks brand for people who hate wellness. Shelf impact up 210% in eight weeks."},
                 {"title": "NO FUN — record label", "meta": "2025 · Identity + web", "tags": ["Digital"],
                  "text": "A label site that plays the record instead of describing it. 9,000 pre-orders."},
                 {"title": "HARD HAT — workwear", "meta": "2025 · Brand + retail", "tags": ["Retail"],
                  "text": "Rebuilt around a single warning-stripe system. Footfall up 38%."},
                 {"title": "LOUD HOUSE — festival", "meta": "2024 · Campaign", "tags": ["Campaign"],
                  "text": "Four hundred posters, one font size. Sold out in eleven days."},
             ]},
            {"id": "services", "kind": "rows", "eyebrow": "What we do",
             "heading": "FOUR THINGS. DONE PROPERLY.",
             "lead": "",
             "items": [
                 {"title": "BRAND STRATEGY", "meta": "01", "text": "Positioning, naming, tone of voice. The argument before the artwork."},
                 {"title": "VISUAL IDENTITY", "meta": "02", "text": "Logo, type, colour, motion. A system your team can actually run."},
                 {"title": "PACKAGING", "meta": "03", "text": "Structural and surface design, from dieline to shelf test."},
                 {"title": "DIGITAL", "meta": "04", "text": "Sites that load fast, read clearly and refuse to look like everyone else's."},
             ]},
            {"id": "about", "kind": "quote", "eyebrow": "No manifesto",
             "heading": "“IF IT CAN BE MISTAKEN FOR ANYONE ELSE, IT IS NOT FINISHED.”",
             "lead": "— pinned above the studio door", "items": []},
            {"id": "faq", "kind": "faq", "eyebrow": "THE SMALL PRINT", "heading": "QUESTIONS", "lead": "", "items": []},
            {"id": "contact", "kind": "contact", "eyebrow": "Say hello",
             "heading": "TELL US THE PROBLEM.", "lead": "Not the brief. The problem. We will write the brief.", "items": []},
        ],
        "faq": [
            {"q": "HOW MUCH DOES A PROJECT COST?", "a": "Identity projects start at £18k. Full brand and digital programmes start at £45k. We quote fixed fees, not hours."},
            {"q": "HOW LONG DOES IT TAKE?", "a": "Six to ten weeks for identity, ten to sixteen for brand plus digital. We do not run more than four projects at once."},
            {"q": "DO YOU WORK WITH STARTUPS?", "a": "Yes, if there is a real product and a real decision-maker. We have a shorter sprint format for early teams."},
        ],
        "contact": {"heading": "Start the argument", "lead": "We reply to every serious enquiry within two working days.",
                    "fields": [("Name", "name", "text", "Who are you?"),
                               ("Email", "email", "email", "you@company.com"),
                               ("The problem", "message", "textarea", "What is broken, and why now?")],
                    "submit": "SEND IT",
                    "note": "No newsletters. No decks. No account managers."},
        "footer": "STUDIO LOUD · 14B VYNER STREET, LONDON · +44 20 7946 0912",
        "note": "Brutalist studio · acid yellow, hard shadows, marquee, index table.",
    },
    {
        "id": "04",
        "folder": "04_muller_swiss",
        "studio": "swiss",
        "category": "Architecture · Studio",
        "brand": "Müller & Co.",
        "title": "Müller & Co. — Architecture and urbanism",
        "kicker": "Architecture & urbanism · Zürich",
        "headline": "Build less. Build better. Leave room.",
        "deck": "We design civic buildings, housing and public rooms that age well: low-carbon structures, honest materials and floor plans people can change themselves.",
        "cta": ("View projects", "Meet the studio"),
        "nav": [("Projects", "#projects"), ("Approach", "#approach"),
                ("Studio", "#about"), ("Contact", "#contact")],
        "stats": [{"value": "1994", "label": "founded"},
                  {"value": "68", "label": "built works"},
                  {"value": "31", "label": "people"}],
        "sections": [
            {"id": "projects", "kind": "rows", "eyebrow": "Selected works",
             "heading": "Projects",
             "lead": "A selection of completed work, 2019–2026.",
             "items": [
                 {"title": "Werkhof Housing", "meta": "Zürich · 2025", "text": "142 timber-framed apartments around a shared courtyard. 38% below the embodied-carbon baseline."},
                 {"title": "Halle Nord", "meta": "Basel · 2024", "text": "A former freight hall reopened as a public market, workshop and winter garden."},
                 {"title": "Schule am Bach", "meta": "Winterthur · 2023", "text": "A primary school with classrooms that open directly onto the landscape."},
                 {"title": "Haus K", "meta": "Lucerne · 2021", "text": "A compact family house built from reclaimed brick and local spruce."},
             ]},
            {"id": "approach", "kind": "steps", "eyebrow": "Approach",
             "heading": "Four commitments",
             "lead": "Written into every contract before the first sketch.",
             "items": [
                 {"title": "Measure twice", "text": "Every project starts with a carbon and cost budget, not a mood board."},
                 {"title": "Keep the structure", "text": "Where a building can be reused, we reuse it. Demolition is a last resort."},
                 {"title": "Design for change", "text": "Rooms, services and facades are planned for a second and third life."},
                 {"title": "Stay on site", "text": "A partner attends every site meeting from first pour to handover."},
             ]},
            {"id": "about", "kind": "quote", "eyebrow": "Studio",
             "heading": "“The most sustainable building is the one you do not have to replace.”",
             "lead": "Anna Müller, founding partner", "items": []},
            {"id": "faq", "kind": "faq", "eyebrow": "Enquiries", "heading": "Working with us", "lead": "", "items": []},
            {"id": "contact", "kind": "contact", "eyebrow": "Contact",
             "heading": "Start with a site", "lead": "Send the address, the brief and the budget range. We answer within five working days.", "items": []},
        ],
        "faq": [
            {"q": "Do you take competitions?", "a": "Yes, roughly one in three of our projects begins as an open or invited competition."},
            {"q": "What is your fee model?", "a": "The Swiss SIA scale, adjusted to the scope. We publish the fee in the first proposal."},
            {"q": "Can you work with an existing architect?", "a": "For conversions and extensions, often. We prefer to join before the feasibility stage."},
        ],
        "contact": {"heading": "Send a site", "lead": "Müller & Co., Limmatstrasse 118, 8005 Zürich",
                    "fields": [("Name", "name", "text", "Your name"),
                               ("Email", "email", "email", "you@example.com"),
                               ("Site and brief", "message", "textarea", "Address, use, budget range")],
                    "submit": "Send enquiry",
                    "note": "We read everything; we cannot answer every speculative brief."},
        "footer": "Müller & Co. Architekten ETH SIA · Limmatstrasse 118, 8005 Zürich",
        "note": "Swiss studio · strict grid, hairline rules, red index numbers.",
    },
    {
        "id": "05",
        "folder": "05_ferry_terminal",
        "studio": "terminal",
        "category": "Developer tool",
        "brand": "ferry",
        "title": "ferry — deploys that tell the truth",
        "kicker": "Open source · v2.4.0",
        "headline": "ship without the ceremony",
        "deck": "A single-binary deploy tool for small teams. Reads your Dockerfile, builds a release, streams the logs and rolls back in one command.",
        "cta": ("Install ferry", "Read the docs"),
        "nav": [("install", "#install"), ("commands", "#commands"),
                ("how", "#flow"), ("faq", "#faq")],
        "stats": [{"value": "2.4 MB", "label": "single binary"},
                  {"value": "0", "label": "config files"},
                  {"value": "11s", "label": "median deploy"}],
        "sections": [
            {"id": "install", "kind": "code", "eyebrow": "Install",
             "heading": "One line. Then you are done.",
             "lead": "Linux, macOS and Windows. No daemon, no account, no YAML.",
             "items": [
                 {"title": "curl -fsSL https://ferry.dev/install.sh | sh", "meta": "install", "text": "Downloads the binary and verifies the checksum."},
                 {"title": "ferry init", "meta": "setup", "text": "Detects your Dockerfile and writes a single ferry.toml."},
                 {"title": "ferry up", "meta": "deploy", "text": "Builds, pushes and streams health checks until the new release is serving."},
             ]},
            {"id": "commands", "kind": "rows", "eyebrow": "Commands",
             "heading": "Small surface area",
             "lead": "Eight commands. Every one does what its name says.",
             "items": [
                 {"title": "ferry up", "meta": "01", "text": "Build and deploy the current directory."},
                 {"title": "ferry logs", "meta": "02", "text": "Stream logs from the active release."},
                 {"title": "ferry rollback", "meta": "03", "text": "Return to the previous healthy release in seconds."},
                 {"title": "ferry doctor", "meta": "04", "text": "Check the host, the image and the health endpoint."},
             ]},
            {"id": "flow", "kind": "steps", "eyebrow": "How it works",
             "heading": "No hidden control plane",
             "lead": "ferry talks to your server over SSH. That is the whole architecture.",
             "items": [
                 {"title": "Build", "text": "A local BuildKit build, cached between releases."},
                 {"title": "Ship", "text": "The image is streamed to the host and started behind a health gate."},
                 {"title": "Verify", "text": "If the check fails, the previous release is restored automatically."},
             ]},
            {"id": "faq", "kind": "faq", "eyebrow": "FAQ", "heading": "Reasonable questions", "lead": "", "items": []},
            {"id": "contact", "kind": "contact", "eyebrow": "Community",
             "heading": "Get the weekly build note", "lead": "Release notes, one migration story and a short tip. No marketing.", "items": []},
        ],
        "faq": [
            {"q": "Does it need Kubernetes?", "a": "No. ferry targets one or more plain servers. If you already run Kubernetes, you probably do not need it."},
            {"q": "How does rollback work?", "a": "Every release keeps its previous image and health check result. `ferry rollback` swaps the symlink and waits for a healthy response."},
            {"q": "Is there a hosted version?", "a": "Not yet. The binary is MIT licensed and works with any SSH-accessible host."},
        ],
        "contact": {"heading": "Subscribe to the changelog", "lead": "One email a week, written by the maintainer.",
                    "fields": [("Email", "email", "email", "you@example.com"),
                               ("What do you deploy?", "stack", "text", "Go, Rails, Next.js…")],
                    "submit": "Subscribe",
                    "note": "Unsubscribe with one click. No tracking pixels."},
        "footer": "ferry is MIT licensed · maintained by four people in three time zones",
        "note": "Terminal studio · phosphor green, typed hero, boot log, command table.",
    },
    {
        "id": "06",
        "folder": "06_fern_flint_organic",
        "studio": "organic",
        "category": "Retail · Plants",
        "brand": "Fern & Flint",
        "title": "Fern & Flint — plants for real rooms",
        "kicker": "Plant shop · Bristol",
        "headline": "Plants that forgive you.",
        "deck": "Low-light ferns, unkillable pothos and the pots that suit them. Grown slowly in our Bristol glasshouse, delivered on a bicycle.",
        "cta": ("Shop the collection", "Plant care guide"),
        "nav": [("Shop", "#shop"), ("Care", "#care"),
                ("Glasshouse", "#about"), ("Visit", "#contact")],
        "stats": [{"value": "63", "label": "species in stock"},
                  {"value": "2 yr", "label": "growth guarantee"},
                  {"value": "0", "label": "peat in our soil"}],
        "sections": [
            {"id": "shop", "kind": "products", "eyebrow": "In the glasshouse",
             "heading": "Six that thrive on neglect",
             "lead": "Each plant ships in a 14 cm pot with a care card and a two-year guarantee.",
             "items": [
                 {"title": "Bird's nest fern", "meta": "£24", "tags": ["Low light"],
                  "text": "Happy in a bathroom. Water when the top inch feels dry."},
                 {"title": "Marble pothos", "meta": "£18", "tags": ["Trailing"],
                  "text": "Grows a metre a year and tells you when it is thirsty."},
                 {"title": "ZZ plant", "meta": "£32", "tags": ["Low light"],
                  "text": "The office plant that survives a forgotten fortnight."},
                 {"title": "String of hearts", "meta": "£21", "tags": ["Bright"],
                  "text": "Loves a sunny shelf and a small pot. Flowers if you are lucky."},
                 {"title": "Hart's tongue fern", "meta": "£26", "tags": ["Shade"],
                  "text": "Native, evergreen and happier in a north-facing corner."},
                 {"title": "Rubber fig", "meta": "£38", "tags": ["Statement"],
                  "text": "A floor plant with dark leaves and a serious silhouette."},
             ]},
            {"id": "care", "kind": "steps", "eyebrow": "Care",
             "heading": "Three rules, no gadgets",
             "lead": "Most houseplants die of kindness. Here is the short version.",
             "items": [
                 {"title": "Feel the soil", "text": "Water only when the top two centimetres are dry. Your finger is the best moisture meter."},
                 {"title": "Follow the light", "text": "Move the plant to the window it wants, not the one that looks best."},
                 {"title": "Repot in spring", "text": "One size up, fresh soil, then leave it alone for a month."},
             ]},
            {"id": "about", "kind": "split", "eyebrow": "The glasshouse",
             "heading": "Grown here, not flown in",
             "lead": "We propagate two-thirds of our stock on site and buy the rest from three growers we visit every year.",
             "items": [
                 {"title": "Peat-free from day one", "text": "Our mix is bark, coir and worm castings. It holds water without mining a bog."},
                 {"title": "Delivered by bicycle", "text": "Within Bristol, orders arrive by cargo bike. Further afield goes by rail where we can."},
             ]},
            {"id": "faq", "kind": "faq", "eyebrow": "Help", "heading": "Plant questions", "lead": "", "items": []},
            {"id": "contact", "kind": "contact", "eyebrow": "Visit",
             "heading": "Come and get your hands dirty", "lead": "The glasshouse is open Wednesday to Sunday, 10–5. Care workshops on Saturdays.", "items": []},
        ],
        "faq": [
            {"q": "What if the plant dies?", "a": "Send a photo within two years and we will replace it once, no argument. Keep the pot."},
            {"q": "Do you ship outside the UK?", "a": "No. Live plants need a phytosanitary certificate per order, which costs more than the plant."},
            {"q": "Are the pots included?", "a": "Every plant ships in a nursery pot with a recycled-fibre cover pot. Ceramic pots are sold separately."},
        ],
        "contact": {"heading": "Plan a visit", "lead": "42 Mina Road, Bristol BS2 9XW · hello@fernandflint.co.uk",
                    "fields": [("Name", "name", "text", "Your name"),
                               ("Email", "email", "email", "you@example.com"),
                               ("What do you need?", "message", "textarea", "A plant for a dark hallway…")],
                    "submit": "Send a note",
                    "note": "We answer between Watering Wednesday and Sunday."},
        "footer": "Fern & Flint · 42 Mina Road, Bristol · Grown peat-free since 2017",
        "note": "Organic studio · warm paper, serif headings, leaf blobs, product cards.",
    },
    {
        "id": "07",
        "folder": "07_casa_aurelia_luxury",
        "studio": "luxury",
        "category": "Hospitality · Hotel",
        "brand": "Casa Aurelia",
        "title": "Casa Aurelia — Lago di Como",
        "kicker": "Lago di Como · Since 1908",
        "headline": "A house that keeps its own time.",
        "deck": "Nine suites, a lemon terrace and a kitchen that cooks what the lake gives that morning. No lobby music. No televisions. A boat, if you want one.",
        "cta": ("Enquire about a stay", "Explore the house"),
        "nav": [("The house", "#house"), ("Suites", "#suites"),
                ("Table", "#table"), ("Enquire", "#contact")],
        "stats": [{"value": "9", "label": "suites"},
                  {"value": "1908", "label": "the villa"},
                  {"value": "1", "label": "boat"}],
        "sections": [
            {"id": "suites", "kind": "frames", "eyebrow": "The suites",
             "heading": "Nine rooms, no two alike",
             "lead": "Original shutters, linen sheets and a view that has not changed in a century.",
             "items": [
                 {"title": "La Terrazza", "meta": "From €780 / night", "tags": ["Terrace"],
                  "text": "A corner suite with a private lemon terrace and a freestanding bath."},
                 {"title": "Il Lago", "meta": "From €640 / night", "tags": ["Lake view"],
                  "text": "Two windows over the water, a writing desk and a very good chair."},
                 {"title": "La Torre", "meta": "From €920 / night", "tags": ["Tower"],
                  "text": "The old watchtower, three floors, a roof terrace and a long staircase."},
             ]},
            {"id": "house", "kind": "split", "eyebrow": "The house",
             "heading": "Run like a home, not a hotel",
             "lead": "Breakfast is whenever you wake. The kitchen closes when the last guest leaves the table.",
             "items": [
                 {"title": "The lemon terrace", "text": "Breakfast under the trees, coffee until noon, nothing scheduled."},
                 {"title": "The boat", "text": "A 1962 Riva available to guests for a morning on the lake, skipper included."},
             ]},
            {"id": "table", "kind": "quote", "eyebrow": "The table",
             "heading": "“We cook what the lake gives us. Today it gave us perch.”",
             "lead": "Nico Beretta, chef", "items": []},
            {"id": "faq", "kind": "faq", "eyebrow": "Practical", "heading": "Before you arrive", "lead": "", "items": []},
            {"id": "contact", "kind": "contact", "eyebrow": "Enquire",
             "heading": "Tell us when", "lead": "We answer personally, usually within a day. Minimum two nights from May to September.", "items": []},
        ],
        "faq": [
            {"q": "How do we arrive?", "a": "Milan Malpensa is 75 minutes by car. We can arrange a driver; the ferry from Como is also lovely and slower."},
            {"q": "Is the house suitable for children?", "a": "Yes, though the terraces and the lake demand attention. Cots and a babysitter are available."},
            {"q": "What is included?", "a": "Breakfast, the boat for one morning, the garden and a very large amount of silence."},
        ],
        "contact": {"heading": "Request a stay", "lead": "Via Aurelia 4, Torno, Lago di Como",
                    "fields": [("Name", "name", "text", "Your name"),
                               ("Email", "email", "email", "you@example.com"),
                               ("Dates and party", "message", "textarea", "12–16 June, two guests")],
                    "submit": "Send enquiry",
                    "note": "We do not use an booking engine. A person reads this."},
        "footer": "Casa Aurelia · Via Aurelia 4, 22020 Torno, Italia · +39 031 419 208",
        "note": "Luxury studio · ink and gold, framed hero, serif display, slow reveals.",
    },
    {
        "id": "08",
        "folder": "08_mochi_pop",
        "studio": "pop",
        "category": "Food · Dessert",
        "brand": "Mochi & Co.",
        "title": "Mochi & Co. — small batches, loud flavours",
        "kicker": "Dessert shop · Leeds",
        "headline": "Squishy on purpose.",
        "deck": "Hand-rolled mochi, six rotating flavours and a freezer full of ice-cream sandwiches. Walk in, point at what looks good, leave happy.",
        "cta": ("See today's flavours", "Book a party"),
        "nav": [("Flavours", "#flavours"), ("Party", "#party"),
                ("Shop", "#about"), ("Find us", "#contact")],
        "stats": [{"value": "6", "label": "flavours a week"},
                  {"value": "18", "label": "minutes to make"},
                  {"value": "1.4k", "label": "mochi a day"}],
        "sections": [
            {"id": "flavours", "kind": "products", "eyebrow": "This week's box",
             "heading": "Pick your squish",
             "lead": "Boxes of six, mixed or matched. Everything is made the morning you get it.",
             "items": [
                 {"title": "Strawberry milk", "meta": "£3.20", "tags": ["Classic"],
                  "text": "Freeze-dried strawberries folded into cold cream. Pink, obviously."},
                 {"title": "Matcha white choc", "meta": "£3.60", "tags": ["Vegan"],
                  "text": "Ceremonial matcha, oat cream, a shard of white chocolate."},
                 {"title": "Mango sticky rice", "meta": "£3.80", "tags": ["New"],
                  "text": "Sticky rice ice cream, mango curd, toasted sesame."},
                 {"title": "Salted caramel", "meta": "£3.20", "tags": ["Classic"],
                  "text": "Burnt caramel, sea salt, a little too much cream."},
                 {"title": "Yuzu cheesecake", "meta": "£3.80", "tags": ["Vegan"],
                  "text": "Sharp yuzu curd, biscuit crumb, whipped cashew."},
                 {"title": "Black sesame", "meta": "£3.60", "tags": ["Nutty"],
                  "text": "Toasted sesame paste, honey, a pinch of salt."},
             ]},
            {"id": "party", "kind": "steps", "eyebrow": "Big orders",
             "heading": "Mochi for a crowd",
             "lead": "Birthdays, launches, weddings and one very memorable hen do.",
             "items": [
                 {"title": "Choose a box", "text": "24, 48 or 96 pieces. Pick up to four flavours."},
                 {"title": "Tell us when", "text": "48 hours notice for boxes, one week for catering."},
                 {"title": "Eat them cold", "text": "We deliver in a chilled box with a two-hour window."},
             ]},
            {"id": "about", "kind": "quote", "eyebrow": "The shop",
             "heading": "“If it does not squish, it does not leave the kitchen.”",
             "lead": "Iris, founder and chief squisher", "items": []},
            {"id": "faq", "kind": "faq", "eyebrow": "Good to know", "heading": "Mochi questions", "lead": "", "items": []},
            {"id": "contact", "kind": "contact", "eyebrow": "Find us",
             "heading": "Come say hi", "lead": "17 Kirkgate Market, Leeds · Thursday to Sunday, 10–4.", "items": []},
        ],
        "faq": [
            {"q": "Are there vegan options?", "a": "Four of the six weekly flavours are vegan, and the ice-cream sandwiches are always dairy-free."},
            {"q": "How long do they keep?", "a": "Two days in the fridge, three weeks in the freezer. Best eaten the same day, obviously."},
            {"q": "Can I book a party?", "a": "Yes — 24 pieces minimum, 48 hours notice, and we can bring the mochi to you within Leeds."},
        ],
        "contact": {"heading": "Book a mochi party", "lead": "Or just ask what is in the freezer today.",
                    "fields": [("Name", "name", "text", "Your name"),
                               ("Email", "email", "email", "you@example.com"),
                               ("What is the occasion?", "message", "textarea", "Birthday, 30 people, 12 May")],
                    "submit": "Send it",
                    "note": "We reply with flavours and a quote, usually same day."},
        "footer": "Mochi & Co. · 17 Kirkgate Market, Leeds · Made in small batches",
        "note": "Pop studio · sticker badges, chunky cards, candy palette, bouncy hover.",
    },
    {
        "id": "09",
        "folder": "09_nightfall_cinematic",
        "studio": "cinematic",
        "category": "Festival · Film",
        "brand": "NIGHTFALL",
        "title": "Nightfall Film Festival 2026",
        "kicker": "14—18 October 2026 · Lisbon",
        "headline": "Five nights. Nineteen films. No daylight.",
        "deck": "A small festival in a hundred-year-old cinema. Restorations, first features and one film projected on the harbour wall at midnight.",
        "cta": ("Get tickets", "Full programme"),
        "nav": [("Programme", "#programme"), ("Venues", "#venues"),
                ("Tickets", "#tickets"), ("Contact", "#contact")],
        "stats": [{"value": "19", "label": "films"},
                  {"value": "5", "label": "nights"},
                  {"value": "1", "label": "harbour wall"}],
        "sections": [
            {"id": "programme", "kind": "films", "eyebrow": "The programme",
             "heading": "Nineteen reasons to stay up",
             "lead": "Scroll the strip. Every screening is introduced by the programmer.",
             "items": [
                 {"title": "The Salt Line", "meta": "Wed 14 · 21:00 · Opening", "tags": ["First feature"],
                  "text": "A family returns to the coast after twenty years. Shot on 16 mm."},
                 {"title": "Harbour, 3 a.m.", "meta": "Thu 15 · 23:30 · Waterfront", "tags": ["Projection"],
                  "text": "Silent documentary with a live score, projected on the harbour wall."},
                 {"title": "Nocturne for a Lift", "meta": "Fri 16 · 19:00", "tags": ["Restoration"],
                  "text": "A 1974 Lisbon film restored frame by frame from the director's print."},
                 {"title": "Blue Hour", "meta": "Sat 17 · 21:30", "tags": ["Competition"],
                  "text": "Two strangers share a night shift in a hotel that is closing."},
                 {"title": "Last Light", "meta": "Sun 18 · 20:00 · Closing", "tags": ["Award"],
                  "text": "The closing film, followed by the audience award and a very long drink."},
             ]},
            {"id": "venues", "kind": "split", "eyebrow": "Venues",
             "heading": "One cinema, one wall, one bar",
             "lead": "Everything is within a ten-minute walk of Praça do Comércio.",
             "items": [
                 {"title": "Cinema Ideal", "text": "A 210-seat cinema from 1928, with the original velvet and a new 4K projector."},
                 {"title": "The harbour wall", "text": "300 folding chairs, blankets at the door and the best sound in the city."},
             ]},
            {"id": "tickets", "kind": "steps", "eyebrow": "Tickets",
             "heading": "Three ways in",
             "lead": "Prices include the introduction and a drink at the late bar.",
             "items": [
                 {"title": "Single screening", "text": "€9, or €7 for students and over-65s. Available at the door."},
                 {"title": "Night pass", "text": "€22 for every film on one night, including the harbour projection."},
                 {"title": "Full festival", "text": "€78 for all nineteen screenings and the closing party."},
             ]},
            {"id": "faq", "kind": "faq", "eyebrow": "Practical", "heading": "Before the lights go down", "lead": "", "items": []},
            {"id": "contact", "kind": "contact", "eyebrow": "Newsletter",
             "heading": "Be first to the programme", "lead": "One email when the programme drops, and one reminder before the festival.", "items": []},
        ],
        "faq": [
            {"q": "Are the films subtitled?", "a": "Every non-English film screens with English subtitles. The harbour projection has live subtitles on a side screen."},
            {"q": "Is the harbour screening weather-proof?", "a": "Yes. If it rains we move to the Cinema Ideal and everyone keeps their seat."},
            {"q": "Can I buy a ticket at the door?", "a": "If there are seats left. The harbour wall is the only venue where you can always turn up."},
        ],
        "contact": {"heading": "Join the list", "lead": "No spam. One email per festival, maybe two.",
                    "fields": [("Email", "email", "email", "you@example.com"),
                               ("Your city", "city", "text", "Lisbon")],
                    "submit": "Join the list",
                    "note": "You can leave the list whenever you like."},
        "footer": "Nightfall · Cinema Ideal, Rua do Loreto 12, Lisboa · A festival with no red carpet",
        "note": "Cinematic studio · full-bleed lightfield, letterboxing, filmstrip drag.",
    },
    {
        "id": "10",
        "folder": "10_meridian_newsroom",
        "studio": "newsroom",
        "category": "Media · Business",
        "brand": "The Meridian",
        "title": "The Meridian — markets, business, the long view",
        "kicker": "Friday 19 October 2026 · London",
        "headline": "The quiet squeeze on Europe's mid-sized manufacturers.",
        "deck": "Order books are full. Margins are not. A four-month investigation into the factories holding up the continent's supply chain — and the finance directors deciding what to cut next.",
        "cta": ("Read the investigation", "See the markets"),
        "nav": [("Markets", "#markets"), ("Companies", "#stories"),
                ("Opinion", "#opinion"), ("Subscribe", "#subscribe")],
        "stats": [{"value": "FTSE 100", "label": "8,412.6  +0.4%"},
                  {"value": "EUR/GBP", "label": "0.8612  −0.1%"},
                  {"value": "Brent", "label": "$74.18  +1.2%"}],
        "sections": [
            {"id": "stories", "kind": "columns", "eyebrow": "Latest",
             "heading": "The long view",
             "lead": "Reporting from London, Frankfurt and Milan.",
             "items": [
                 {"title": "Why the mid-cap squeeze is not easing", "meta": "Investigation · 14 min", "tags": ["Manufacturing"],
                  "text": "Full order books, thin margins and a generation of owners with no obvious successor."},
                 {"title": "The quiet return of the company town", "meta": "Analysis · 8 min", "tags": ["Property"],
                  "text": "Employers are buying housing again — and discovering why the model collapsed."},
                 {"title": "A bank that decided to shrink", "meta": "Profile · 11 min", "tags": ["Finance"],
                  "text": "Inside the strategy that made a regional lender the most trusted name in the sector."},
                 {"title": "Gridlock at the port of Antwerp", "meta": "Report · 6 min", "tags": ["Logistics"],
                  "text": "What a two-day strike reveals about the fragility of just-in-time Europe."},
             ]},
            {"id": "markets", "kind": "chart", "eyebrow": "Markets",
             "heading": "The week in one line",
             "lead": "Meridian Composite, five sessions. Hover the line for the close.",
             "items": [
                 {"title": "Meridian Composite", "meta": "+1.8% on the week", "text": "7412,7488,7390,7530,7612,7580,7664"},
             ]},
            {"id": "opinion", "kind": "quote", "eyebrow": "Opinion",
             "heading": "“The next industrial policy will be written by CFOs, not ministers.”",
             "lead": "Marta Lindqvist, columnist", "items": []},
            {"id": "faq", "kind": "faq", "eyebrow": "The paper", "heading": "About The Meridian", "lead": "", "items": []},
            {"id": "subscribe", "kind": "contact", "eyebrow": "Subscribe",
             "heading": "Read the whole argument", "lead": "Unlimited access to every investigation, profile and market note.", "items": []},
        ],
        "faq": [
            {"q": "What do I get with a subscription?", "a": "Every investigation, the full archive, the Friday markets note and the morning briefing."},
            {"q": "Do you take advertising?", "a": "No. The Meridian is funded entirely by readers."},
            {"q": "Can I cancel at any time?", "a": "Yes, from your account page. There is no retention call."},
        ],
        "contact": {"heading": "Start a subscription", "lead": "£12 a month, or £110 for the year.",
                    "fields": [("Name", "name", "text", "Your name"),
                               ("Email", "email", "email", "you@example.com"),
                               ("What do you read first?", "message", "textarea", "Markets, opinion, investigations…")],
                    "submit": "Subscribe",
                    "note": "Your card is charged monthly. Cancel in two clicks."},
        "footer": "The Meridian · 8 Finsbury Circus, London EC2M 7EB · Readers, not advertisers",
        "note": "Newsroom studio · masthead, ticker, article columns, inline SVG chart.",
    },
]

# ── Brief → studio selection ──────────────────────────────────────────────

# Keyword affinity. A brief can match several studios; the hash breaks ties so
# two similar briefs do not always land on the same design.
_STUDIO_WORDS = {
    "aurora": ("saas", "ai", "platform", "dashboard", "startup", "analytics",
               "developer", "api", "cloud", "data", "product"),
    "editorial": ("magazine", "writer", "editorial", "journal", "culture",
                  "essay", "publication", "author", "newsletter", "photography"),
    # "portfolio" is a page type, not a brutalist style cue: it made every
    # portfolio brief (photographers included) tie into this raw theme by
    # default. Keep the words that actually ask for that aesthetic.
    "brutalist": ("brutalist", "agency", "creative", "designer", "music", "label",
                  "fashion", "bold", "experimental", "protest"),
    "swiss": ("architect", "architecture", "consultancy", "law", "finance",
              "minimal", "engineering", "urban", "institute"),
    "terminal": ("cli", "developer", "open source", "devops", "terminal",
                 "infrastructure", "engineer", "code", "tool", "security"),
    "organic": ("plant", "food", "organic", "cafe", "restaurant", "nature",
                "wellness", "farm", "garden", "shop", "florist"),
    "luxury": ("hotel", "luxury", "jewel", "spa", "property", "interior",
               "travel", "resort", "estate", "winery", "private"),
    "pop": ("playful", "kids", "candy", "dessert", "game", "festival", "colour",
            "colorful", "ice cream", "bakery", "party", "fun"),
    "cinematic": ("film", "cinema", "photographer", "video", "photography",
                  "festival", "music", "theatre", "gallery", "visual"),
    "newsroom": ("news", "media", "journalism", "markets", "business",
                 "report", "finance", "sport", "politics", "investigation"),
}

TYPE_AFFINITY = {
    "portfolio": ("editorial", "cinematic", "swiss", "brutalist", "aurora"),
    "website": ("aurora", "organic", "luxury", "newsroom", "pop", "swiss"),
    "webapp": ("terminal", "aurora", "swiss", "newsroom"),
}


def score_studios(brief: str, kind: str = "website") -> list[tuple[int, str]]:
    text = (brief or "").lower()
    scores: list[tuple[int, str]] = []
    for studio, words in _STUDIO_WORDS.items():
        score = sum(2 for w in words if re.search(rf"\b{re.escape(w)}\b", text))
        if studio in TYPE_AFFINITY.get(kind, ()):
            score += 1
        scores.append((score, studio))
    return scores


def choose_studio(brief: str, kind: str = "website", seed: str = "") -> str:
    """Pick a studio for this brief, deterministically but not always the same.

    The best keyword match wins; among equally plausible studios the brief's
    own hash decides, so two portfolios written the same way still get
    different design systems.
    """
    scores = score_studios(brief, kind)
    best = max(s for s, _ in scores)
    tied = [name for score, name in scores if score == best]
    if best == 0:
        tied = list(TYPE_AFFINITY.get(kind, tuple(_STUDIO_WORDS)))
    digest = hashlib.sha256((brief + "|" + seed).encode("utf-8")).hexdigest()
    return tied[int(digest[:8], 16) % len(tied)]


# ── Plan adapter (live pipeline) ──────────────────────────────────────────

_KIND_MAP = {
    "projects": "cards", "cards": "cards", "gallery": "gallery",
    "about": "split", "skills": "chips", "text": "text",
    "faq": "faq", "contact": "contact", "metrics": "stats",
}


def plan_to_content(plan: dict, kind: str = "website", brief: str = "") -> dict:
    """Adapt a planner plan into the studio content model."""
    plan = plan or {}
    sections = []
    for i, sec in enumerate(plan.get("sections") or []):
        k = str(sec.get("kind") or "text").lower()
        mapped = _KIND_MAP.get(k, "text")
        items = []
        for it in sec.get("items") or []:
            if isinstance(it, str):
                it = {"title": it}
            if not isinstance(it, dict):
                continue
            items.append({
                "title": str(it.get("title") or ""),
                "text": str(it.get("text") or ""),
                "meta": str(it.get("meta") or ""),
                "tags": [str(t) for t in (it.get("tags") or [])][:5],
            })
        sections.append({
            "id": sec.get("id") or f"s{i}",
            "kind": mapped,
            "eyebrow": str(sec.get("eyebrow") or k),
            "heading": str(sec.get("heading") or "Section"),
            "lead": str(sec.get("lead") or ""),
            "items": items,
        })

    has_faq = any(s["kind"] == "faq" for s in sections)
    if not has_faq and plan.get("faq"):
        sections.append({"id": "faq", "kind": "faq", "eyebrow": "Questions",
                         "heading": "Good to know", "lead": "", "items": []})
    has_contact = any(s["kind"] == "contact" for s in sections)
    if not has_contact:
        sections.append({"id": "contact", "kind": "contact", "eyebrow": "Contact",
                         "heading": "Get in touch", "lead": "", "items": []})

    brand = str(plan.get("brand") or "Studio")
    metrics = []
    for m in plan.get("metrics") or []:
        if isinstance(m, dict) and m.get("value"):
            metrics.append({"value": str(m["value"]), "label": str(m.get("label") or "")})

    nav = [(s["heading"], "#" + s["id"]) for s in sections
           if s["kind"] not in ("contact", "faq")][:4]

    return {
        "id": "live",
        "folder": "live",
        "studio": "",
        "category": kind.title(),
        "brand": brand,
        "title": str(plan.get("title") or brand),
        "kicker": str(plan.get("eyebrow") or kind),
        "headline": str(plan.get("headline") or f"{brand}"),
        "deck": str(plan.get("tagline") or ""),
        "cta": (str(plan.get("cta_primary") or "See the work"),
                str(plan.get("cta_secondary") or "Get in touch")),
        "nav": nav or [("Work", "#main")],
        "stats": metrics,
        "sections": sections,
        "faq": [{"q": str(f.get("q") or ""), "a": str(f.get("a") or "")}
                for f in (plan.get("faq") or []) if isinstance(f, dict)],
        "contact": {
            "heading": next((s["heading"] for s in sections if s["kind"] == "contact"),
                            "Get in touch"),
            "lead": next((s["lead"] for s in sections if s["kind"] == "contact"), ""),
            "fields": [("Name", "name", "text", "Your name"),
                       ("Email", "email", "email", "you@example.com"),
                       ("Message", "message", "textarea", "What are you building?")],
            "submit": "Send message",
            "note": "We reply within two working days.",
        },
        "footer": str(plan.get("footer") or f"© {brand}"),
        "note": "Rendered by the Crown Code studio engine.",
        "brief": brief,
    }


def all_samples() -> list[dict]:
    return SAMPLE_SITES
