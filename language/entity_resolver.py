"""
ENTITY RESOLVER — BLINK-inspired mention → candidate entities → ranking →
best match, done locally for Keys.ai.

A persistent entity registry (config/entities.json, auto-seeded, user-editable)
stores people, projects, companies, websites and files the user cares about.
Resolution combines:
    1. exact / case-insensitive alias match
    2. longest-alias specificity bonus
    3. fuzzy spelling (edit distance <= 2) for person-name variants
    4. context boost (recently-mentioned entities win ties)

Ambiguity handling (spec): when a mention plausibly matches MULTIPLE entities
(e.g. two "Rahul"s), the resolver returns an `ask` clarification instead of
silently guessing. When only one candidate exists, it resolves without asking.

The resolver NEVER substitutes when it is not confident, and it protects
matched names from the spell corrector.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from language.dictionaries import APP_NAMES, COMMAND_WORDS
from language.normalizer import normalize

# words that are definitely NOT contact names (apps, commands, common
# vocabulary) — a phonetic name run must never start on one of these, so
# "open chrome" can't be misread as "did you mean Sharma?"
_KNOWN_WORDS = frozenset(w.lower() for w in (APP_NAMES | COMMAND_WORDS))

# A phonetic "sounds like a contact" hit must be STRONG before it may
# interrupt the user. Scores cluster at ≈0.77 (weak) and ≈0.92 (strong):
# the weak bucket matches ordinary English words — 'form', 'from', 'forum',
# 'norm' all "sound like" Sharma/Verma — so a low floor let "Now add a
# contact form." be hijacked into "I couldn't match 'form'. Did you mean
# Rahul?". Genuine name typos clear this floor on their own:
# 'dhanuj' → Dhananjay 0.92, 'harrman' → Harman 0.92, 'sadhwni' → 0.92.
_PHONETIC_FALLBACK_MIN = 0.85


def _aligned_fold(text: str) -> tuple:
    """Fold text like the normalizer while remembering each output char's
    ORIGINAL index. Whitespace runs collapse to a single space and combining
    marks are stripped, but every emitted char points back at its source
    char, so spans never misalign with the original input (safe for
    slicing, substitution and capitalization checks)."""
    if not text:
        return "", []
    out: list[str] = []
    orig: list[int] = []
    prev_space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if prev_space:
                continue
            prev_space = True
            out.append(" ")
            orig.append(i)
            continue
        prev_space = False
        for d in unicodedata.normalize("NFKD", ch.lower()):
            if not unicodedata.combining(d):
                out.append(d)
                orig.append(i)
    return "".join(out), orig


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


REGISTRY_PATH = _base_dir() / "config" / "entities.json"

# ── seed registry (auto-created on first run; extend in config/entities.json)
SEED: dict = {
    "people": [
        {"name": "Harman Sadhwani", "aliases": ["harman", "harman sadhwani"],
         "note": "Keys.ai creator"},
        {"name": "Rishabh Kumar Gond",
         "aliases": ["rishab", "rishabh", "rishab kumar", "rishabh kumar",
                     "rishabh kumar gond", "rishab gond"],
         "note": "known contact"},
        {"name": "Dhananjay", "aliases": ["dhananjey", "dhananjay"],
         "note": "known contact"},
        {"name": "Rahul Sharma", "aliases": ["rahul", "rahul sharma"],
         "note": "known contact (ambiguous first name)"},
        {"name": "Rahul Verma", "aliases": ["rahul", "rahul verma"],
         "note": "known contact (ambiguous first name)"},
    ],
    "projects": [
        {"name": "Keys.ai", "aliases": ["keys ai", "keysai"],
         "note": "this assistant"},
        {"name": "ReviewBot", "aliases": ["reviewbot"],
         "note": "AI-powered GitHub code review assistant"},
        {"name": "Drop of Hope", "aliases": ["drop of hope", "dropofhope"],
         "note": "blood donation platform"},
        {"name": "BharatHealth", "aliases": ["bharathealth"],
         "note": "AI-assisted healthcare platform"},
    ],
    "companies": [],
    "websites": [],
    "files": [],
}


@dataclass
class Entity:
    category: str
    name: str
    aliases: list
    note: str = ""

    def __post_init__(self):
        self.aliases = [a for a in (self.aliases or []) if a]


@dataclass
class EntityMatch:
    entity: Entity
    mention: str
    confidence: float
    start: int = 0
    end: int = 0

    def to_dict(self) -> dict:
        return {"category": self.entity.category,
                "name": self.entity.name,
                "mention": self.mention,
                "confidence": round(self.confidence, 2)}


@dataclass
class Resolution:
    text: str
    matches: list = field(default_factory=list)
    ask: str | None = None
    # structured clarification info (so a follow-up answer can be resolved):
    ask_mention: str = ""
    ask_candidates: list = field(default_factory=list)


def _empty_registry() -> dict:
    return {"people": [], "projects": [], "companies": [], "websites": [],
            "files": []}


class EntityResolver:
    def __init__(self, memory_layer=None):
        self._entities: list[Entity] = []
        self._load()
        self._seed_from_memory(memory_layer)

    # ── registry loading ──────────────────────────────────────────────────
    def _load(self) -> None:
        try:
            if not REGISTRY_PATH.exists():
                REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
                REGISTRY_PATH.write_text(
                    json.dumps(SEED, indent=2, ensure_ascii=False),
                    encoding="utf-8")
                data = SEED
            else:
                data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception as e:
            print(f"[EntityResolver] ⚠️ Registry load error: {e}")
            data = {}
        for category in ("people", "projects", "companies", "websites",
                         "files"):
            for item in data.get(category, []) or []:
                if isinstance(item, dict) and item.get("name"):
                    self._entities.append(Entity(
                        category, str(item["name"]),
                        item.get("aliases") or [], str(item.get("note", ""))))

    def _seed_from_memory(self, memory_layer) -> None:
        """Fold long-term memory into the registry: relationships → people,
        projects → projects. Never overrides existing registry entries."""
        if memory_layer is None:
            return
        try:
            mem = memory_layer._memory() if hasattr(memory_layer, "_memory") \
                else {}
            rels = mem.get("relationships", {}) or {}
            for key, entry in rels.items():
                val = entry.get("value") if isinstance(entry, dict) else entry
                if val and str(key).strip():
                    self._entities.append(Entity(
                        "people", str(key),
                        [str(key), str(val).split()[0] if val else str(key)],
                        "from long-term memory"))
            projects = mem.get("projects", {}) or {}
            for key, entry in projects.items():
                val = entry.get("value") if isinstance(entry, dict) else entry
                if val:
                    self._entities.append(Entity(
                        "projects", str(key), [str(key)],
                        "from long-term memory"))
        except Exception:
            pass

    # ── mention matching ──────────────────────────────────────────────────
    def _all_matches(self, folded: str, orig: list[int]) -> list:
        """Return every (start, end, alias_len, entity, conf) match.
        Confidence: an exact alias hit is a strong match (1.0); longer aliases
        get a small specificity bonus so full names beat first names in ties.
        Spans are mapped to ORIGINAL-text coordinates via the fold map."""
        matches = []
        for ent in self._entities:
            for alias in ent.aliases:
                fa = normalize(alias)
                if not fa:
                    continue
                pat = re.compile(r"(?<![A-Za-z])" + re.escape(fa) +
                                 r"(?![A-Za-z])")
                for m in pat.finditer(folded):
                    if m.end() - 1 >= len(orig):
                        continue
                    s = orig[m.start()]
                    e = orig[m.end() - 1] + 1
                    specificity = 1.0 + 0.02 * (len(fa.split()) - 1)
                    conf = min(1.0, specificity)
                    matches.append((s, e, len(fa.split()), ent,
                                    round(conf, 3)))
        return matches

    # ── fuzzy matching (misspellings / variants of known names) ──────────
    def _fuzzy_matches(self, folded: str, orig: list[int], text: str,
                       exact_spans) -> list:
        """Fuzzy matching for people + projects (single-token AND
        multi-token full-name aware). Returns (start, end, alias_len,
        entity, conf) tuples in ORIGINAL-text coordinates.

        Handles: single-word typos ("Rishbh" → Rishabh), truncations
        ("Dhananj" → Dhananjay), transpositions ("Dhannajay"), and full-name
        typos ("Harman Sadhwni" → Harman Sadhwani). Only accepted in a
        NAME POSITION (after messaging/open verbs, before 's, or a
        capitalized proper noun) so casual words are never absorbed."""
        from language.spell_corrector import damerau_levenshtein
        out = []
        # (folded_start, folded_end, orig_start, orig_end, token) — keep both
        # coordinate spaces: prefix/possessive checks use folded text while
        # slicing + capitalization use original indices, never misaligning.
        tokens = []
        for m in re.finditer(r"[a-zğüşöçı]{2,}", folded):
            fs, fe = m.start(), m.end()
            if fs >= len(orig) or fe - 1 >= len(orig):
                continue
            tokens.append((fs, fe, orig[fs], orig[fe - 1] + 1, m.group(0)))

        for ent in self._entities:
            if ent.category not in ("people", "projects"):
                continue
            for alias in ent.aliases:
                fa = normalize(alias)
                if not fa or len(fa) < 3:
                    continue
                fa_toks = fa.split()
                n = len(fa_toks)

                # ── single-word alias: compare each input token ───────────
                if n == 1:
                    for (fs, fe, ts, te, tok) in tokens:
                        if any(s <= ts and te <= e for s, e, *_ in
                               exact_spans):
                            continue
                        if not self._in_name_position(folded, fs, fe, ts,
                                                      text):
                            continue
                        d = damerau_levenshtein(tok, fa, max_dist=2)
                        if d == 0:
                            continue
                        if d <= 2 and (len(fa) - d) >= 3:
                            conf = max(0.72, 0.95 - 0.09 * d)
                            out.append((ts, te, 1, ent, round(conf, 3)))
                        elif len(tok) >= 4 and (len(fa) - len(tok)) <= 2 and \
                                fa.startswith(tok):
                            # truncation: "dhananj" → "dhananjay"
                            out.append((ts, te, 1, ent, 0.85))
                    continue

                # ── multi-word alias: sliding window of n tokens ──────────
                joined = fa.replace(" ", "")
                for i in range(len(tokens) - n + 1):
                    win = tokens[i:i + n]
                    ws, we = win[0][2], win[-1][3]
                    if any(s <= ws and we <= e for s, e, *_ in exact_spans):
                        continue
                    if not self._in_name_position(folded, win[0][0],
                                                  win[-1][1], ws, text):
                        continue
                    wj = " ".join(t for *_, t in win)
                    d = damerau_levenshtein(wj, fa, max_dist=3)
                    if d == 0 or d > 2:
                        continue
                    if (len(fa) - d) < 4:
                        continue
                    conf = max(0.8, 0.97 - 0.08 * d)
                    out.append((ws, we, n, ent, round(conf, 3)))

                # ── compacted form: "dropofhop" vs "drop of hope" ────────
                if n > 1 and len(joined) >= 4:
                    for (fs, fe, ts, te, tok) in tokens:
                        if any(s <= ts and te <= e for s, e, *_ in
                               exact_spans):
                            continue
                        if not self._in_name_position(folded, fs, fe, ts,
                                                      text):
                            continue
                        dc = damerau_levenshtein(tok, joined, max_dist=2)
                        if 0 < dc <= 2:
                            out.append((ts, te, 1, ent, 0.82))
        return out

    @staticmethod
    def _in_name_position(folded: str, folded_start: int, folded_end: int,
                          orig_start: int, text: str) -> bool:
        """True when the span sits where a name plausibly occurs: after a
        messaging/open verb, before a possessive 's, or capitalized.
        Prefix/possessive checks use the folded string; the capitalization
        check reads the ORIGINAL text so folding never misaligns it."""
        before = folded[:folded_start].rstrip()
        if re.search(r"(?:^|[\s,;:(])(?:message|email|call|text|tell|contact|"
                     r"ping|to|from|for|with|about|open|launch|start|close|"
                     r"send|add|invite|reply|meet)\s*$", before):
            return True
        if folded[folded_end:folded_end + 2].startswith(("'s", "’s")):
            return True
        if orig_start < len(text) and \
                text[orig_start:orig_start + 1].isupper():
            return True
        return False

    # ── phonetic fallback (last resort, contacts only) ───────────────────
    # When the exact/fuzzy matchers cannot place a name-position mention at
    # all, pronunciation matching kicks in: people whose names SOUND like the
    # typed word are offered as numbered options ("Did you mean 1) … 2) …?").
    _STOP = frozenset(
        "a an the to for with about from of and or on in at by this that "
        "these those my your our his her its their me him us them is are was "
        "were be been do does did can could would should will shall may might "
        "must have has had not no yes so but as if then than please tell send "
        "message email call text open run start close stop fix check review "
        "show save create write read give set make get go know want need "
        "hello hi hey now later soon today tomorrow yesterday here there home "
        "office work school college evening morning afternoon night weekend "
        "monday tuesday wednesday thursday friday saturday sunday january "
        "february march april june july august september october november "
        "december week month year".split())

    @staticmethod
    def _numbered_names(names: list) -> str:
        if len(names) == 1:
            return f"1) {names[0]}"
        return (", ".join(f"{i}) {n}"
                        for i, n in enumerate(names[:-1], 1))
                + f", or {len(names)}) {names[-1]}")

    def _phonetic_options(self, mention: str, mk: str | None = None) -> list:
        """Rank people entities whose pronunciation is close to `mention`.
        Compares the mention's key against every alias AND each individual
        name token (so "Kumar" can surface "Rishabh Kumar Gond"). Returns
        [(Entity, confidence)] deduped, best first, max 3."""
        from language.phonetics import phonetic_key
        from language.spell_corrector import damerau_levenshtein
        if mk is None:
            mk = phonetic_key(mention)
        if not mk:
            return []
        options = []
        for ent in self._entities:
            if ent.category != "people":
                continue
            best_d = None
            for alias in ent.aliases or []:
                for piece in (alias, *alias.split()):
                    ak = phonetic_key(piece)
                    if not ak:
                        continue
                    d = damerau_levenshtein(mk, ak, max_dist=2)
                    if d <= 1 and (best_d is None or d < best_d):
                        best_d = d
            if best_d is not None:
                conf = max(0.6, 0.92 - 0.15 * best_d)
                options.append((ent, round(conf, 3)))
        seen = {}
        for ent, conf in options:
            if ent.name not in seen or conf > seen[ent.name][1]:
                seen[ent.name] = (ent, conf)
        ranked = sorted(seen.values(), key=lambda t: (-t[1], t[0].name.lower()))
        return ranked[:3]

    def _phonetic_matches_any(self, phrase: str) -> bool:
        """True when a (possibly multi-token) phrase still sounds like some
        known person — used to decide whether a name run should extend."""
        from language.phonetics import phonetic_key
        from language.spell_corrector import damerau_levenshtein
        pk = phonetic_key(phrase)
        if not pk:
            return False
        for ent in self._entities:
            if ent.category != "people":
                continue
            for alias in ent.aliases or []:
                ak = phonetic_key(alias)
                if ak and damerau_levenshtein(pk, ak, max_dist=2) <= 1:
                    return True
        return False

    def _name_runs(self, folded: str, orig: list[int],
                   text: str) -> list:
        """Find contiguous runs of name-position tokens. A run starts at a
        token in name position (after a verb / capitalized / possessive 's)
        and extends over adjacent non-stopword tokens while they are
        capitalized or the combined phrase still sounds like a known person.
        Returns [(fs, fe, os, oe, token), ...] runs (original coordinates)."""
        tokens = []
        for m in re.finditer(r"[a-zğüşöçı]{2,}", folded):
            fs, fe = m.start(), m.end()
            if fs >= len(orig) or fe - 1 >= len(orig):
                continue
            tokens.append((fs, fe, orig[fs], orig[fe - 1] + 1, m.group(0)))
        runs: list = []
        i = 0
        n = len(tokens)
        while i < n:
            fs, fe, os, oe, tok = tokens[i]
            if tok in self._STOP or tok in _KNOWN_WORDS or \
                    not self._in_name_position(folded, fs, fe, os, text):
                i += 1
                continue
            run = [tokens[i]]
            j = i + 1
            while j < n and tokens[j][2] == run[-1][3] and \
                    tokens[j][4] not in self._STOP and \
                    tokens[j][4] not in _KNOWN_WORDS:
                os_j = tokens[j][2]
                capped = os_j < len(text) and text[os_j].isupper()
                if not capped:
                    phrase = " ".join(t[4] for t in run + [tokens[j]])
                    if not self._phonetic_matches_any(phrase):
                        break
                run.append(tokens[j])
                j += 1
            runs.append(run)
            i = j
        return runs

    def _phonetic_fallback(self, text: str, folded: str,
                           orig: list[int]) -> Resolution:
        """Last resort: offer pronunciation-similar people as options.
        Never silently substitutes — always asks, exactly per spec.
        Tries the full name run first, then progressively shorter leading
        sub-runs, so a capitalized trailing word ("Dhanuj Kumar") can never
        hide a valid match on the leading token ("Dhanuj" → Dhananjay)."""
        best = None
        for run in self._name_runs(folded, orig, text):
            for k in range(len(run), 0, -1):
                sub = run[:k]
                mention = text[sub[0][2]:sub[-1][3]]
                opts = self._phonetic_options(mention)
                if opts and opts[0][1] >= _PHONETIC_FALLBACK_MIN:
                    if best is None or opts[0][1] > best[1]:
                        best = (mention, opts[0][1], opts)
                    break  # longest matching sub-run for this run
        if not best:
            return Resolution(text)
        mention, _, opts = best
        names = [ent.name for ent, _ in opts]
        ask = (f"I couldn't match '{mention}'. Did you mean "
               f"{self._numbered_names(names)}?")
        return Resolution(text, ask=ask, ask_mention=mention,
                          ask_candidates=names)

    # ── public API ────────────────────────────────────────────────────────
    def scan(self, text: str) -> list[EntityMatch]:
        """Find entity mentions (exact + fuzzy + phonetic protection)
        without substituting. Used to protect names from the spell
        corrector."""
        folded, orig = _aligned_fold(text)
        if not folded or not orig:
            return []
        exact = self._all_matches(folded, orig)
        fuzzy = self._fuzzy_matches(
            folded, orig, text, [(s, e) for s, e, *_ in exact])
        merged = exact + fuzzy
        if not merged:
            # nothing placed by the matchers: protect the raw mention span
            # so the phonetic fallback (used later in resolve) sees it intact
            protections = []
            for run in self._name_runs(folded, orig, text):
                for k in range(len(run), 0, -1):
                    sub = run[:k]
                    mention = text[sub[0][2]:sub[-1][3]]
                    opts = self._phonetic_options(mention)
                    if not opts:
                        continue
                    ent, conf = opts[0]
                    protections.append(EntityMatch(
                        ent, mention, conf, sub[0][2], sub[-1][3]))
                    break
            return protections
        # longest span first, then earliest; non-overlapping greedy pick
        merged.sort(key=lambda t: (-(t[1] - t[0]), t[0], -t[2]))
        picked: list = []
        taken = []
        for start, end, _, ent, conf in merged:
            if any(s < end and start < e for s, e, *_ in taken):
                continue
            picked.append(EntityMatch(ent, text[start:end], conf, start, end))
            taken.append((start, end))
        return picked

    def resolve(self, text: str) -> Resolution:
        folded, orig = _aligned_fold(text)
        if not folded or not orig:
            return Resolution(text)
        exact = self._all_matches(folded, orig)
        fuzzy = self._fuzzy_matches(
            folded, orig, text, [(s, e) for s, e, *_ in exact])
        matches = exact + fuzzy
        if not matches:
            # spelling not understood → pronunciation-similar options
            return self._phonetic_fallback(text, folded, orig)

        # ── ambiguity: same mention matched by ≥2 DISTINCT entities ──────
        span_groups: dict = {}
        for start, end, _, ent, conf in matches:
            group = span_groups.setdefault((start, end), {})
            # several aliases of the SAME entity are one candidate, not two
            if ent.name not in group or conf > group[ent.name]:
                group[ent.name] = conf
        asks = []
        first_ask_mention = ""
        first_ask_candidates: list = []
        all_spans = sorted(span_groups)
        for (start, end), cand_map in span_groups.items():
            cands = sorted(cand_map.items(), key=lambda c: c[1], reverse=True)
            if len(cands) < 2 or cands[0][1] - cands[1][1] >= 0.05:
                continue
            # skip spans fully contained inside a longer, unambiguous span
            # (handles shared-start spans like "rahul" inside "rahul sharma")
            if any((s, e) != (start, end) and s <= start and end <= e and
                   len(span_groups[(s, e)]) == 1 for s, e in all_spans):
                continue
            names = sorted({n for n, _ in cands})
            mention = text[start:end]
            asks.append(f"Which {mention} do you mean — {' or '.join(names)}?")
            if not first_ask_mention:
                first_ask_mention = mention
                first_ask_candidates = names
        if asks:
            return Resolution(text, ask=" ".join(asks),
                              ask_mention=first_ask_mention,
                              ask_candidates=first_ask_candidates)

        # ── greedy non-overlapping best matches + substitution ────────────
        # longest span first so a fuzzy full-name match absorbs its parts
        matches.sort(key=lambda t: (-(t[1] - t[0]), t[0], -t[2]))
        picked = []
        taken = []
        for start, end, _, ent, conf in matches:
            if any(s < end and start < e for s, e in taken):
                continue
            picked.append((start, end, ent, conf))
            taken.append((start, end))
        return self._substitute(text, picked)

    def _substitute(self, text: str, matches) -> Resolution:
        picked = [EntityMatch(ent, text[s:e], conf, s, e)
                  for s, e, ent, conf in matches]
        pieces = []
        last = 0
        for m in sorted(picked, key=lambda m: m.start):
            pieces.append(text[last:m.start])
            pieces.append(m.entity.name)
            last = m.end
        pieces.append(text[last:])
        return Resolution("".join(pieces), picked)

    def protected_words(self) -> list[str]:
        words = []
        for ent in self._entities:
            words.append(ent.name)
            words.extend(ent.aliases)
        return words


def load_entities() -> list[Entity]:
    return EntityResolver()._entities
