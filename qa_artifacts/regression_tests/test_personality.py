"""Personality & dialogue behaviour tests (Integration Prompt, Phase 8).

Covers: corpus schema validation, bounded deterministic retrieval, mode
selection incl. distress/safety rules, persona versioning in the prompt,
humour suppression over distress, language adaptation, and concise-vs-detailed
mode wording. These assert behaviour, not exact reply wording.
"""

from __future__ import annotations

import json

import pytest

from personality import build_system_block, select_mode
from personality.config import PersonalityConfig, load_personality_config
from personality.corpus import (CorpusError, format_examples, load_corpus,
                                select_examples)
from personality.humor import ConversationalHumor
from personality.modes import (MODE_PROFILES, all_modes_block, humour_for,
                               is_distress, is_safety_sensitive, mode_block)


# ── corpus: loading + schema validation ────────────────────────────────────

def test_corpus_loads_and_is_well_formed():
    data = load_corpus()
    assert data, "corpus file missing"
    assert len(data["categories"]) >= 18
    total = sum(len(c["examples"]) for c in data["categories"])
    assert total >= 146
    ids = [e["id"] for c in data["categories"] for e in c["examples"]]
    assert len(ids) == len(set(ids)), "example ids must be unique"


def test_corpus_rejects_bad_json_with_clear_error(tmp_path):
    bad = tmp_path / "corpus.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(CorpusError) as exc:
        load_corpus(path=bad)
    assert "corpus.json" in str(exc.value)
    assert "JSON" in str(exc.value)


def test_corpus_rejects_missing_schema_with_clear_error(tmp_path):
    bad = tmp_path / "corpus.json"
    bad.write_text(json.dumps({"title": "x", "categories": [
        {"id": "c1", "title": "t", "examples": [{"id": "a", "user": "hi"}]},
    ]}), encoding="utf-8")
    with pytest.raises(CorpusError) as exc:
        load_corpus(path=bad)
    message = str(exc.value)
    assert "assistant" in message and "c1" in message


def test_missing_corpus_file_degrades_to_empty(tmp_path):
    assert load_corpus(path=tmp_path / "nope.json") == {}


# ── retrieval: bounded, deterministic, relevant ────────────────────────────

def test_retrieval_is_bounded_to_one_to_four_examples():
    for k in (0, 1, 3, 99):
        picked = select_examples(text="review my python code", k=k)
        assert 1 <= len(picked) <= 4
        assert len(picked) <= max(1, min(4, k or 3))


def test_retrieval_is_deterministic():
    a = select_examples(text="fix this bug", mode="developer", k=3)
    b = select_examples(text="fix this bug", mode="developer", k=3)
    assert [e["id"] for e in a] == [e["id"] for e in b]


def test_retrieval_prefers_the_mode_family():
    picked = select_examples(text="bugs errors exceptions", mode="developer", k=3)
    assert picked, "developer mode should retrieve examples"
    families = {e["id"].rsplit("_", 1)[0] for e in picked}
    assert families & {"05_coding_and_development_partner",
                       "06_debugging_and_recovery",
                       "11_failures_limits_and_honest_recovery"}


def test_examples_are_marked_as_calibration_not_scripts():
    block = format_examples(select_examples(text="hello", k=2))
    assert "calibration" in block.lower()
    assert "never copy" in block.lower()


def test_language_filter_separates_hindi_and_english():
    from personality.corpus import _language_of
    hindi = select_examples(text="hindi baat karo", language="hi", k=4)
    assert hindi, "corpus has Hindi/Hinglish examples"
    for example in hindi:
        assert _language_of(example) == "hi"
    assert all(e["id"].startswith("16_") for e in hindi), \
        "Hindi replies live in the multilingual family"
    english = select_examples(text="hello there", language="en", k=4)
    assert english
    for example in english:
        assert _language_of(example) == "en"


# ── mode selection ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,want", [
    ("I'm exhausted and I failed again", "coach"),
    ("delete these files please", "focus"),
    ("debug this traceback in my code", "developer"),
    ("research the latest sources for this claim", "research"),
    ("open the folder and take a screenshot", "operator"),
    ("give me a bold brand voice idea", "creative"),
    ("Hey, Keys.", "companion"),
    ("", "companion"),
])
def test_mode_for_turn(text, want):
    assert mode_for_safe(text) == want


def mode_for_safe(text: str) -> str:
    return select_mode(text)


def test_mode_for_respects_brain_intent():
    assert select_mode("whatever", intent="CODING") == "developer"
    assert select_mode("whatever", intent="WEB_RESEARCH") == "research"


def test_distress_and_safety_patterns():
    assert is_distress("I'm overwhelmed and hopeless")
    assert is_distress("everything is going wrong")
    assert not is_distress("open the browser")
    assert is_safety_sensitive("delete the project folder")
    assert is_safety_sensitive("send it to everyone")
    assert not is_safety_sensitive("what's the weather")


def test_humour_drops_to_zero_for_distress_and_safety():
    assert humour_for(select_mode("I failed again and I'm exhausted")) == 0
    assert humour_for(select_mode("wipe the disk")) == 0
    assert humour_for("companion") <= 2  # baseline dial is 2/5


def test_mode_blocks_are_distinct_concise_vs_detailed():
    focus = mode_block("focus")
    research = mode_block("research")
    assert focus and research and focus != research
    assert "shortest" in focus.lower() or "no preamble" in focus.lower()
    assert "source" in research.lower()
    assert "Humour: 0/5" in focus
    listing = all_modes_block()
    for profile in MODE_PROFILES.values():
        assert profile["title"] in listing
    assert "distress" in listing.lower()


# ── prompt assembly ────────────────────────────────────────────────────────

def test_persona_version_and_tool_truth_in_block():
    block = build_system_block(user_text="debug this error")
    assert "PERSONA VERSION 1.0.0" in block
    assert "TOOL TRUTH" in block
    assert "Distinguish drafted from sent" in block


def test_per_turn_block_carries_mode_and_few_examples():
    block = build_system_block(user_text="my code is a mess, help me refactor")
    assert "CURRENT MODE — Developer" in block
    assert "STYLE EXAMPLES" in block
    # bounded: never the whole book
    assert block.count("- User:") <= 4


def test_session_block_lists_modes_but_injects_no_examples():
    block = build_system_block()
    assert "MODES (switch naturally" in block
    assert "STYLE EXAMPLES" not in block


def test_disabled_personality_returns_empty_block():
    assert build_system_block(PersonalityConfig({"enabled": False})) == ""


def test_persona_config_defaults_are_versioned():
    persona = load_personality_config().persona()
    assert persona["version"] == "1.0.0"
    assert 0 <= int(persona["humour_dial"]) <= 5
    assert 1 <= int(persona["example_count"]) <= 4


def test_reasoning_seam_passes_the_turn_text():
    from brain.reasoning import ReasoningEngine
    merged = ReasoningEngine._with_personality("BASE", "debug this bug")
    assert merged.startswith("BASE")
    assert "CURRENT MODE — Developer" in merged


# ── humour engine: distress gate ───────────────────────────────────────────

class _Resp:
    def __init__(self, text, status="COMPLETED"):
        self.text = text
        self.status = status


class _Ctx:
    def __init__(self, request):
        self.current_request = request
        self.references = {}


def _forced_humor(monkeypatch):
    """Make the engine deterministic: generate() always returns a remark."""
    monkeypatch.setattr(ConversationalHumor, "generate",
                        lambda self, text, decision, app="": "[remark]")
    engine = ConversationalHumor()
    monkeypatch.setattr(engine, "enabled", lambda: True)
    monkeypatch.setattr(engine, "_level", lambda: "HIGH")
    return engine


def test_humour_is_suppressed_over_distress(monkeypatch):
    engine = _forced_humor(monkeypatch)
    resp = _Resp("That sounds rough. We can shrink the scope.")
    engine.postprocess(resp, _Ctx("I failed again and I'm exhausted"))
    assert resp.text == "That sounds rough. We can shrink the scope."


def test_humour_is_suppressed_for_safety_turns(monkeypatch):
    engine = _forced_humor(monkeypatch)
    resp = _Resp("I will delete the listed files after you confirm.")
    engine.postprocess(resp, _Ctx("delete these files"))
    assert "[remark]" not in resp.text


def test_humour_still_applies_on_ordinary_turns(monkeypatch):
    engine = _forced_humor(monkeypatch)
    resp = _Resp("Opened VS Code. Workspace ready.")
    engine.postprocess(resp, _Ctx("open vs code"))
    assert "[remark]" in resp.text


def test_humour_never_touches_failures_or_questions(monkeypatch):
    engine = _forced_humor(monkeypatch)
    failed = _Resp("The command failed: exit code 1.", status="FAILED")
    engine.postprocess(failed, _Ctx("run it"))
    assert "[remark]" not in failed.text
    question = _Resp("Which file should I open?")
    engine.postprocess(question, _Ctx("open the file"))
    assert "[remark]" not in question.text
