"""
Tests for the Keys.ai INTELLIGENCE CORE upgrade (personality, humour engine,
spelling correction, entity/name resolution, semantic parsing, pipeline).

All tests run OFFLINE — no network, no real tools, no real desktop.

Run:  python -m unittest test_intelligence -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from brain.brain import BrainResponse, KeysBrain
from brain.config import BrainConfig
from brain.context import ContextManager
from brain.intent import APP_CONTROL
from brain.memory import MemoryLayer
from brain.state import BrainStatus
from language.entity_resolver import EntityResolver
from language.semantic_parser import SemanticParser
from language.spell_corrector import SmartCorrector
from personality.humor import ConversationalHumor


class FakeProvider:
    name = "fake"

    def __init__(self, generate_text="fake answer", structured=None,
                 fail=False):
        self._gen = generate_text
        self._structured = structured
        self._fail = fail

    def generate(self, prompt, system=None, temperature=0.2, max_tokens=None):
        if self._fail:
            raise RuntimeError("boom")
        return self._gen

    def structured_output(self, prompt, system=None, temperature=0.0):
        if self._fail:
            raise RuntimeError("boom")
        return self._structured

    def available(self):
        return True


class FakeRegistry:
    def __init__(self):
        self.calls = []

    def names(self):
        return ["open_app", "web_search", "send_message", "system_status",
                "weather_report", "code_helper"]

    def has(self, name):
        return name in self.names()

    def descriptions(self, max_tools=40):
        return "- open_app: opens an app\n- web_search: searches the web"

    def execute(self, name, args, ui=None, speak=None):
        self.calls.append((name, dict(args)))
        return {"ok": True, "tool": name, "result": f"{name} done: {args}",
                "error": None}


def make_config(**overrides):
    base = {
        "enabled": True, "provider": "fake", "max_iterations": 10,
        "max_retries": 2, "autonomous_mode": True, "confirm_moderate": True,
        "confirm_dangerous": True, "polish_response": False,
        "memory": {"enabled": True, "long_term": True, "llm_extract": False},
        "intent": {"llm_refine": False}, "context": {"max_history": 12},
        "logging": {"level": "info"},
        "language": {"enabled": True, "spell": True, "entities": True,
                     "semantic": True, "situation": False},
        "personality": {"enabled": True}, "humor": {"enabled": True},
        "skills": {"enabled": True}, "session": {"persist": False},
        "permissions": {
            "DANGEROUS": ["file_controller"],
            "MODERATE": ["send_message"],
            "SAFE": ["open_app", "web_search", "system_status",
                     "weather_report", "code_helper"],
        },
        "blocked_tools": [],
    }

    def _merge(a, b):
        for k, v in b.items():
            if isinstance(v, dict) and isinstance(a.get(k), dict):
                _merge(a[k], v)
            else:
                a[k] = v

    _merge(base, overrides)
    return BrainConfig(base)


class _SpyUI:
    def write_log(self, text):
        pass

    def set_state(self, state):
        pass

    def show_content(self, title, text):
        pass

    def stop_camera_stream(self):
        pass


class TestSpellCorrection(unittest.TestCase):
    def setUp(self):
        self.sc = SmartCorrector()

    def test_open_vs_cod(self):
        self.assertEqual(self.sc.correct("open vs cod").text, "open VS Code")

    def test_open_googl(self):
        self.assertEqual(self.sc.correct("open googl").text, "open Google")

    def test_send_mesage(self):
        self.assertEqual(self.sc.correct("send mesage").text,
                         "send message")

    def test_open_my_repositry(self):
        self.assertEqual(self.sc.correct("open my repositry").text,
                         "open my repository")

    def test_proper_noun_never_mangled(self):
        self.assertEqual(self.sc.correct("open Vinayak").text,
                         "open Vinayak")

    def test_name_position_never_corrected(self):
        # "kasim" sits in a recipient position — it must not be turned into
        # some unrelated dictionary word, but app-name aliases still work
        self.assertEqual(self.sc.correct("message kasim").text,
                         "message kasim")
        self.assertEqual(self.sc.correct("email dhananjay").text,
                         "email dhananjay")
        self.assertEqual(self.sc.correct("open rishab's repo").text,
                         "open rishab's repo")
        self.assertEqual(self.sc.correct("open googl").text, "open Google")

    def test_verb_typos_corrected(self):
        self.assertEqual(
            self.sc.correct("remmeber that I prefere Python").text,
            "remember that I prefer Python")

    def test_known_words_untouched(self):
        self.assertEqual(
            self.sc.correct("what is the capital of Turkey?").text,
            "what is the capital of Turkey?")

    def test_open_chrome_untouched(self):
        self.assertEqual(self.sc.correct("open chrome").text, "open chrome")


class TestEntityResolution(unittest.TestCase):
    def setUp(self):
        self.er = EntityResolver()

    def test_harman_resolves(self):
        r = self.er.resolve("send a message to Harman")
        self.assertIn("Harman Sadhwani", r.text)
        self.assertIsNone(r.ask)

    def test_rishab_variants(self):
        for name in ("Rishab", "Rishabh", "Rishab Kumar"):
            r = self.er.resolve("message " + name)
            self.assertIn("Rishabh Kumar Gond", r.text, name)

    def test_dhananjey_resolves(self):
        r = self.er.resolve("open Dhananjey's project")
        self.assertIn("Dhananjay", r.text)
        self.assertIsNone(r.ask)

    def test_ambiguity_asks(self):
        r = self.er.resolve("message Rahul")
        self.assertIsNotNone(r.ask)
        self.assertIn("Rahul Sharma", r.ask)
        self.assertIn("Rahul Verma", r.ask)

    def test_ambiguity_ask_carries_candidates(self):
        r = self.er.resolve("message Rahul")
        self.assertEqual(r.ask_mention, "Rahul")
        self.assertEqual(r.ask_candidates, ["Rahul Sharma", "Rahul Verma"])

    def test_ambiguity_resolved_by_full_name(self):
        r = self.er.resolve("message Rahul Sharma")
        self.assertIsNone(r.ask)
        self.assertIn("Rahul Sharma", r.text)

    def test_project_entity(self):
        r = self.er.resolve("open keys ai")
        self.assertIn("Keys.ai", r.text)
        self.assertIsNone(r.ask)

    # ── misspelled-name regression tests ─────────────────────────────────
    def test_typo_full_name_resolves(self):
        # surname typo in a full name: "Harman Sadhwni" → "Harman Sadhwani"
        r = self.er.resolve("message Harman Sadhwni")
        self.assertIn("Harman Sadhwani", r.text)
        self.assertIsNone(r.ask)

    def test_dropped_vowel_resolves(self):
        for name in ("Rishbh", "Rishab", "Risabh"):
            r = self.er.resolve("message " + name)
            self.assertIn("Rishabh Kumar Gond", r.text, name)
            self.assertIsNone(r.ask, name)

    def test_doubled_consonant_resolves(self):
        r = self.er.resolve("message Rishabh Kummar")
        self.assertIn("Rishabh Kumar Gond", r.text)
        self.assertIsNone(r.ask)

    def test_multi_token_typo_resolves(self):
        r = self.er.resolve("message Rishbh Kumar")
        self.assertIn("Rishabh Kumar Gond", r.text)
        self.assertIsNone(r.ask)

    def test_truncated_name_resolves(self):
        r = self.er.resolve("message Dhananj")
        self.assertIn("Dhananjay", r.text)
        self.assertIsNone(r.ask)

    def test_unknown_name_never_absorbed(self):
        # a misspelled UNKNOWN name must not be force-matched to an entity
        r = self.er.resolve("message Xyzzy Plugh")
        self.assertIsNone(r.ask)
        self.assertEqual(r.text, "message Xyzzy Plugh")

    def test_fuzzy_mention_protected_in_scan(self):
        # scan() must surface fuzzy mentions too, so preprocess can protect
        # the typo'd name from the spell corrector before resolution
        hits = self.er.scan("message Harman Sadhwni")
        mentions = [m.mention.lower() for m in hits]
        self.assertTrue(any("sadhwni" in m for m in mentions))

    def test_fuzzy_project_name_resolves(self):
        r = self.er.resolve("open reviwbot")
        self.assertIn("ReviewBot", r.text)
        self.assertIsNone(r.ask)

    def test_double_space_never_misaligns(self):
        # normalize() collapses whitespace; spans must stay aligned to the
        # ORIGINAL text so substitution never corrupts the output
        r = self.er.resolve("message  Harman")
        self.assertIn("Harman Sadhwani", r.text)
        self.assertIsNone(r.ask)
        r2 = self.er.resolve("open  dhananjey's  project")
        self.assertIn("Dhananjay", r2.text)
        self.assertIsNone(r2.ask)


class TestPhonetics(unittest.TestCase):
    def test_same_pronunciation_same_key(self):
        from language.phonetics import phonetic_key
        pairs = [("Harman", "Harmen"), ("Harman", "Harman"),
                 ("Rishabh", "Rishab"), ("Dhananjay", "Dhananjey"),
                 ("Rahul", "Rahool"), ("Verma", "Berma"),
                 ("Sharma", "Sarma")]
        for a, b in pairs:
            self.assertEqual(phonetic_key(a), phonetic_key(b),
                             f"{a} vs {b}")

    def test_key_drops_vowels_and_collapses(self):
        from language.phonetics import phonetic_key
        self.assertEqual(phonetic_key("Harman"), "hrmn")
        self.assertEqual(phonetic_key("Rishabh"), "rsb")
        self.assertEqual(phonetic_key("Dhananjay"), "dnj")
        self.assertEqual(phonetic_key(""), "")
        self.assertEqual(phonetic_key("!!!"), "")

    def test_phonetic_fallback_offers_options(self):
        er = EntityResolver()
        r = er.resolve("message Dhanuj")
        self.assertIsNotNone(r.ask)
        self.assertIn("Dhananjay", r.ask)
        self.assertEqual(r.ask_mention, "Dhanuj")
        self.assertEqual(r.ask_candidates, ["Dhananjay"])

    def test_phonetic_fallback_never_silently_substitutes(self):
        er = EntityResolver()
        r = er.resolve("message Dhanuj")
        self.assertEqual(r.text, "message Dhanuj")

    def test_phonetic_no_false_positives(self):
        er = EntityResolver()
        for t in ("message them", "message tomorrow", "call mother",
                  "message Xyzzy", "tell me a joke"):
            r = er.resolve(t)
            self.assertIsNone(r.ask, t)
            self.assertEqual(r.text, t, t)

    def test_common_nouns_are_never_mistaken_for_contacts(self):
        """Regression: 'form' sounded 0.77 like Sharma/Verma and hijacked
        real requests into a contact question ('Now add a contact form.' →
        'Did you mean Rahul Sharma?'). Weak phonetic hits must stay silent."""
        er = EntityResolver()
        for t in ("Now add a contact form.",
                  "the contact form is broken",
                  "send the form to the team"):
            r = er.resolve(t)
            self.assertIsNone(r.ask, t)
            self.assertEqual(r.text, t, t)

    def test_strong_name_typos_still_reach_the_fallback(self):
        """The confidence floor must not blunt genuine misspellings: a bad
        typo still surfaces the right person, by asking OR by resolving."""
        er = EntityResolver()
        r = er.resolve("message Dhanuj")            # fallback asks …
        self.assertIsNotNone(r.ask)
        self.assertIn("Dhananjay", r.ask)
        r2 = er.resolve("message Hrrman")           # … the strong path resolves
        self.assertIn("Harman", (r2.text or "") + (r2.ask or ""))

    def test_close_spellings_still_resolve_silently(self):
        er = EntityResolver()
        self.assertIn("Harman Sadhwani",
                      er.resolve("message Hrmnn").text)
        self.assertIn("Rishabh Kumar Gond",
                      er.resolve("message Rishuv").text)

    def test_scan_protects_phonetic_mention(self):
        er = EntityResolver()
        hits = er.scan("message Dhanuj")
        mentions = [m.mention.lower() for m in hits]
        self.assertIn("dhanuj", mentions)

    def test_phonetic_options_ranked_deduped(self):
        er = EntityResolver()
        opts = er._phonetic_options("Rahool")
        names = [e.name for e, _ in opts]
        self.assertIn("Rahul Sharma", names)
        self.assertIn("Rahul Verma", names)
        self.assertEqual(len(names), len(set(names)))

    def test_capitalized_tail_word_cannot_hide_match(self):
        # "Dhanuj Kumar" must still surface Dhananjay from the leading
        # token even though the capitalized tail extends the name run
        er = EntityResolver()
        r = er.resolve("message Dhanuj Kumar")
        self.assertIsNotNone(r.ask)
        self.assertIn("Dhananjay", r.ask)
        self.assertEqual(r.ask_mention, "Dhanuj")

    def test_name_token_matching(self):
        # a surname-only mention can surface a contact with that name part
        er = EntityResolver()
        r = er.resolve("message Kummar")
        self.assertIsNotNone(r.ask)
        self.assertIn("Rishabh Kumar Gond", r.ask)

    def test_stop_words_never_ask(self):
        er = EntityResolver()
        for t in ("message saturday", "message office", "message home"):
            r = er.resolve(t)
            self.assertIsNone(r.ask, t)


class TestSemanticParsing(unittest.TestCase):
    def setUp(self):
        self.sp = SemanticParser()

    def test_can_you_get_x_open(self):
        p = self.sp.parse("can you get VS Code open?")
        self.assertEqual(p.semantic, "open VS Code")
        self.assertEqual(p.intent_hint, "OPEN_APPLICATION")

    def test_why_dont_you_open(self):
        p = self.sp.parse("why don't you open Chrome for me?")
        self.assertEqual(p.semantic, "open Chrome for me")
        self.assertEqual(p.intent_hint, "OPEN_APPLICATION")

    def test_i_need_to_work_on(self):
        p = self.sp.parse("I need to work on ReviewBot")
        self.assertEqual(p.semantic, "open ReviewBot")
        self.assertEqual(p.intent_hint, "OPEN_APPLICATION")

    def test_please_prefix(self):
        p = self.sp.parse("please open Chrome")
        self.assertEqual(p.semantic, "open Chrome")

    def test_open_my_project_asks_without_context(self):
        p = self.sp.parse("open my repository")
        self.assertIsNotNone(p.ask)

    def test_open_my_project_uses_context(self):
        ctx = ContextManager()
        ctx.note_reference("project", "ReviewBot")
        p = self.sp.parse("open my repository", context=ctx)
        self.assertEqual(p.semantic, "open ReviewBot")
        self.assertIsNone(p.ask)


class TestHumor(unittest.TestCase):
    def _humor(self, **settings):
        h = ConversationalHumor(make_config())
        s = {"professional_mode": False, "humour_level": "HIGH",
             "dark_humour": False}
        s.update(settings)
        h._agent_settings = lambda: s
        return h

    def test_disabled_on_errors(self):
        h = self._humor()
        d = h.decide("I couldn't open the file: error 500",
                     "FAILED", "COMPUTER_ACTION")
        self.assertEqual(d, "HUMOR_NOT_APPROPRIATE")

    def test_disabled_on_questions_to_user(self):
        h = self._humor()
        d = h.decide("Which project should I open?", "WAITING_FOR_USER", "")
        self.assertEqual(d, "HUMOR_NOT_APPROPRIATE")

    def test_disabled_on_confirmation(self):
        h = self._humor()
        d = h.decide("I need your confirmation before I send the message. "
                     "Say yes or no.", "WAITING_FOR_USER", "")
        self.assertEqual(d, "HUMOR_NOT_APPROPRIATE")

    def test_disabled_on_sensitive(self):
        h = self._humor()
        d = h.decide("The API key is invalid.", "COMPLETED", "")
        self.assertEqual(d, "HUMOR_NOT_APPROPRIATE")

    def test_disabled_on_code_output(self):
        h = self._humor()
        d = h.decide("```\nprint('hi')\n```", "COMPLETED", "CODING")
        self.assertEqual(d, "HUMOR_NOT_APPROPRIATE")

    def test_allowed_on_action_success(self):
        h = self._humor()
        d = h.decide("Chrome is open.", "COMPLETED", "COMPUTER_ACTION")
        self.assertEqual(d, "HUMOR_ALLOWED")

    def test_professional_mode_kills_all(self):
        h = self._humor(professional_mode=True)
        self.assertEqual(h.decide("Chrome is open.", "COMPLETED",
                                  "COMPUTER_ACTION"),
                         "HUMOR_NOT_APPROPRIATE")

    def test_off_level_kills_all(self):
        h = self._humor(humour_level="OFF")
        self.assertEqual(h.decide("Chrome is open.", "COMPLETED",
                                  "COMPUTER_ACTION"),
                         "HUMOR_NOT_APPROPRIATE")

    def test_postprocess_appends_remark(self):
        import random
        random.seed(42)
        h = self._humor()
        resp = BrainResponse("Chrome is open.", "COMPLETED")
        h.postprocess(resp, intent="COMPUTER_ACTION")
        self.assertNotEqual(resp.text, "Chrome is open.")
        self.assertIn("Chrome is open.", resp.text)

    def test_postprocess_never_breaks_error(self):
        h = self._humor()
        resp = BrainResponse("I couldn't open the file.", "FAILED")
        h.postprocess(resp, intent="COMPUTER_ACTION")
        self.assertEqual(resp.text, "I couldn't open the file.")


class TestIntelligencePipeline(unittest.TestCase):
    def make_brain(self, provider=None):
        cfg = make_config()
        ui = _SpyUI()
        mem = MemoryLayer(memory_path=Path(tempfile.mkdtemp()) / "mem.json")
        brain = KeysBrain(ui=ui, speak=lambda t: None, config=cfg,
                          provider=provider or FakeProvider(),
                          tool_registry=FakeRegistry(), memory_layer=mem)
        return brain

    def test_open_googl_routes_to_google(self):
        brain = self.make_brain()
        resp = brain.process("open googl")
        self.assertTrue(resp.used_brain)
        self.assertEqual(resp.intent, APP_CONTROL)
        self.assertIn("Google", resp.text)
        called = [c for c in brain.tools.calls if c[0] == "open_app"]
        self.assertTrue(called)
        self.assertEqual(called[0][1]["app_name"], "Google")

    def test_open_vs_cod_routes(self):
        brain = self.make_brain()
        resp = brain.process("open vs cod")
        self.assertTrue(resp.used_brain)
        self.assertIn("VS Code", resp.text)

    def test_send_mesage_entity(self):
        brain = self.make_brain()
        resp = brain.process("send mesage to Dhananjay: hello")
        self.assertEqual(resp.status, BrainStatus.WAITING_FOR_USER.value)
        called = [c for c in brain.tools.calls if c[0] == "send_message"]
        self.assertEqual(called, [])

    def test_ambiguity_asks_instead_of_guessing(self):
        brain = self.make_brain()
        resp = brain.process("message Rahul")
        self.assertEqual(resp.status, BrainStatus.WAITING_FOR_USER.value)
        self.assertIn("Rahul Sharma", resp.text)
        self.assertIn("Rahul Verma", resp.text)

    def test_ask_followup_completes_request(self):
        brain = self.make_brain()
        r1 = brain.process("send a message to Rahul: hello")
        self.assertEqual(r1.status, BrainStatus.WAITING_FOR_USER.value)
        self.assertIn("Rahul Sharma", r1.text)
        # the user's answer completes the original request → the tool then
        # needs its normal confirmation gate before it executes
        r2 = brain.process("Sharma")
        self.assertEqual(r2.status, BrainStatus.WAITING_FOR_USER.value)
        r3 = brain.process("yes")
        sent = [c for c in brain.tools.calls if c[0] == "send_message"]
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][1]["receiver"], "Rahul Sharma")

    def test_ask_followup_full_name(self):
        brain = self.make_brain()
        r1 = brain.process("send a message to Rahul: hello")
        self.assertEqual(r1.status, BrainStatus.WAITING_FOR_USER.value)
        r2 = brain.process("Rahul Verma")
        self.assertEqual(r2.status, BrainStatus.WAITING_FOR_USER.value)
        brain.process("yes")
        sent = [c for c in brain.tools.calls if c[0] == "send_message"]
        self.assertEqual(sent[0][1]["receiver"], "Rahul Verma")

    def test_ask_followup_unrelated_clears(self):
        brain = self.make_brain()
        brain.process("send a message to Rahul: hello")
        # an unrelated request clears the pending clarification
        resp = brain.process("open chrome")
        self.assertNotIn("Rahul", resp.text)
        self.assertNotIn("Which Rahul", resp.text)

    def test_phonetic_ask_numbered_followup_completes(self):
        # spelling not understood → pronunciation options → pick by number
        brain = self.make_brain()
        r1 = brain.process("send a message to Dhanuj: hello")
        self.assertEqual(r1.status, BrainStatus.WAITING_FOR_USER.value)
        self.assertIn("Dhananjay", r1.text)
        r2 = brain.process("1")
        self.assertEqual(r2.status, BrainStatus.WAITING_FOR_USER.value)
        r3 = brain.process("yes")
        sent = [c for c in brain.tools.calls if c[0] == "send_message"]
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][1]["receiver"], "Dhananjay")

    def test_phonetic_ask_ordinal_followup(self):
        from brain.intelligence import IntelligenceCore
        core = IntelligenceCore(make_config())
        core._pending_ask = {
            "original": "message Dhanuj",
            "mention": "Dhanuj",
            "candidates": ["Harman Sadhwani", "Dhananjay"],
        }
        self.assertEqual(core._resolve_followup("2nd"),
                         "message Dhananjay")
        self.assertEqual(core._resolve_followup("the first one"),
                         "message Harman Sadhwani")
        self.assertEqual(core._resolve_followup("Dhananjay"),
                         "message Dhananjay")
        self.assertEqual(core._resolve_followup("Sadhwani"),
                         "message Harman Sadhwani")
        self.assertIsNone(core._resolve_followup("nobody"))

    def test_control_typos_stop_and_pause(self):
        from brain.intent import PAUSE, STOP
        brain = self.make_brain()
        resp = brain.process("stp")
        self.assertEqual(resp.status, BrainStatus.STOPPED.value)
        self.assertEqual(resp.intent, STOP)
        resp = brain.process("paus")
        self.assertEqual(resp.status, BrainStatus.PAUSED.value)
        self.assertEqual(resp.intent, PAUSE)

    def test_control_typo_resume(self):
        from brain.intent import RESUME
        brain = self.make_brain()
        resp = brain.process("contine")
        self.assertEqual(resp.intent, RESUME)

    def test_memory_stores_corrected_text(self):
        brain = self.make_brain()
        brain.process("remmeber that I prefere Python")
        hits = brain.memory.search("python", top_k=3)
        self.assertTrue(hits)
        self.assertEqual(hits[0]["value"], "Python")
        self.assertNotIn("prefere", str(hits[0]["value"]))

    def test_chat_question_unaffected(self):
        brain = self.make_brain(provider=FakeProvider(
            generate_text="Ankara is the capital of Turkey."))
        resp = brain.process("what is the capital of Turkey?")
        self.assertTrue(resp.used_brain)
        self.assertIn("Ankara", resp.text)

    def test_semantic_polite_open(self):
        brain = self.make_brain()
        resp = brain.process("can you get chrome open?")
        self.assertTrue(resp.used_brain)
        self.assertIn("Chrome", resp.text)

    def test_proper_noun_not_corrected(self):
        brain = self.make_brain()
        resp = brain.process("open Vinayak")
        self.assertNotIn("Google", resp.text)
        self.assertNotIn("Chrome", resp.text)

    def test_pipeline_misspelled_full_name(self):
        # end-to-end: typo'd name survives spell correction, resolves to the
        # canonical person, and reaches the tool with the right receiver
        brain = self.make_brain()
        resp = brain.process("send a message to Harman Sadhwni: hello")
        self.assertEqual(resp.status, BrainStatus.WAITING_FOR_USER.value)
        brain.process("yes")
        sent = [c for c in brain.tools.calls if c[0] == "send_message"]
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][1]["receiver"], "Harman Sadhwani")

    def test_pipeline_dropped_vowel(self):
        brain = self.make_brain()
        resp = brain.process("send a message to Rishbh: hello")
        self.assertEqual(resp.status, BrainStatus.WAITING_FOR_USER.value)
        brain.process("yes")
        sent = [c for c in brain.tools.calls if c[0] == "send_message"]
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][1]["receiver"], "Rishabh Kumar Gond")


class TestSessionPersistence(unittest.TestCase):
    def test_save_restore_roundtrip(self):
        tmp = Path(tempfile.mkdtemp()) / "session.json"
        ctx = ContextManager()
        ctx.note_reference("app", "WhatsApp")
        ctx.note_reference("project", "ReviewBot")
        ctx.save_state(tmp)
        ctx2 = ContextManager()
        ok = ctx2.restore_state(tmp)
        self.assertTrue(ok)
        self.assertEqual(ctx2.references.get("last_app"), "WhatsApp")
        self.assertEqual(ctx2.references.get("last_project"), "ReviewBot")

    def test_the_project_resolution(self):
        ctx = ContextManager()
        ctx.note_reference("project", "ReviewBot")
        self.assertEqual(ctx.resolve_references("run the project"),
                         "run ReviewBot")

    def test_file_from_earlier_resolution(self):
        ctx = ContextManager()
        ctx.note_reference("file", "brain.py")
        self.assertEqual(ctx.resolve_references("open the file from earlier"),
                         "open brain.py")
        self.assertEqual(ctx.resolve_references("the file from earlier"),
                         "brain.py")
        self.assertEqual(ctx.resolve_references("run it"), "run brain.py")

    def test_temporal_reference_forms(self):
        ctx = ContextManager()
        ctx.note_reference("app", "VS Code")
        ctx.note_reference("file", "brain.py")
        ctx.note_reference("project", "Keys.ai")
        # verb-prefixed + bare forms, no dangling temporal tail
        self.assertEqual(ctx.resolve_references("that app we had open"),
                         "VS Code")
        self.assertEqual(ctx.resolve_references("open that file from earlier"),
                         "open brain.py")
        self.assertEqual(ctx.resolve_references("the project we were on"),
                         "Keys.ai")
        self.assertEqual(
            ctx.resolve_references("the project we were working on"),
            "Keys.ai")
        # no false positives
        self.assertEqual(ctx.resolve_references("tell me a joke"),
                         "tell me a joke")
        self.assertEqual(ctx.resolve_references("check the weather"),
                         "check the weather")


class TestWorkspaceDocs(unittest.TestCase):
    def test_workspace_block_loaded(self):
        from personality.workspace import load_workspace_block
        block = load_workspace_block()
        self.assertIn("SOUL", block)
        self.assertIn("AGENTS", block)

    def test_personality_block_includes_skills_and_workspace(self):
        from personality import build_system_block
        block = build_system_block()
        self.assertIn("AVAILABLE SKILLS", block)
        self.assertIn("SOUL", block)

    def test_workspace_missing_files_are_skipped(self):
        import personality.workspace as ws
        block = ws.load_workspace_block()
        # must not raise even though files may be absent in other setups
        self.assertIsInstance(block, str)

    def test_situation_conservative(self):
        ctx = ContextManager()
        ctx.note_reference("app", "WhatsApp")
        ctx.note_situation(app="Chrome")
        self.assertEqual(ctx.references.get("last_app"), "WhatsApp")


if __name__ == "__main__":
    unittest.main()

