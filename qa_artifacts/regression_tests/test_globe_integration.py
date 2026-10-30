"""Regression tests for the God's Eye View integration.

These cover the deterministic parts — intent routing, coordinate handling,
layer vocabulary, install validation and honest result reporting. The live
page behaviour (does the camera actually fly to Kanpur?) is verified by
``globe_live_probe.py``, which needs the running app and a window; a unit test
cannot honestly claim that.

    python -m unittest qa_artifacts.regression_tests.test_globe_integration -v
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from globe import install as globe_install          # noqa: E402
from globe import intents                            # noqa: E402
from globe.service import _from_runner, _js_str, _runner_script   # noqa: E402


class TestGlobeIntents(unittest.TestCase):
    """Explicit globe requests route; everything else is left alone."""

    def test_open_variants(self):
        for text in (
            "Open globe.",
            "open the globe",
            "Could you open the globe for me?",
            "Keys, open the globe",
            "Show me the Earth.",
            "Open GRO.",
            "Launch the globe view",
            "open world view",
        ):
            with self.subTest(text=text):
                command = intents.try_parse(text)
                self.assertIsNotNone(command, text)
                self.assertEqual(command.action, intents.OPEN_GLOBE, text)

    def test_close(self):
        for text in ("Close the globe.", "close globe", "hide the globe please"):
            with self.subTest(text=text):
                command = intents.try_parse(text)
                self.assertIsNotNone(command, text)
                self.assertEqual(command.action, intents.CLOSE_GLOBE, text)

    def test_named_places(self):
        cases = {
            "Take me to Kanpur.": "Kanpur",
            "Navigate to Kanpur, Uttar Pradesh.": "Kanpur, Uttar Pradesh",
            "show New Delhi on the globe": "New Delhi",
            "open the globe and show India": "India",
            "show me the geographical location of the Taj Mahal": "Taj Mahal",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                command = intents.try_parse(text)
                self.assertIsNotNone(command, text)
                self.assertEqual(command.action, intents.NAVIGATE_TO_LOCATION, text)
                self.assertIn(expected.lower(), command.location.lower(), text)

    def test_coordinates_are_never_geocoded(self):
        command = intents.try_parse("Show 26.4499, 80.3319")
        self.assertIsNotNone(command)
        self.assertEqual(command.action, intents.NAVIGATE_TO_LOCATION)
        self.assertAlmostEqual(command.latitude, 26.4499)
        self.assertAlmostEqual(command.longitude, 80.3319)
        self.assertEqual(command.location, "")

        geo = intents.try_parse("geo:39.7392,-104.9903")
        self.assertIsNotNone(geo)
        self.assertAlmostEqual(geo.latitude, 39.7392)
        self.assertAlmostEqual(geo.longitude, -104.9903)

    def test_invalid_coordinates_are_rejected(self):
        self.assertIsNone(intents.parse_coordinates("lat 999, lon 999"))
        self.assertIsNone(intents.parse_coordinates("0.0, 0.0"))
        self.assertIsNone(intents.parse_coordinates("no numbers here"))

    def test_zoom(self):
        self.assertEqual(intents.try_parse("Zoom out.").action, intents.ZOOM_OUT)
        self.assertEqual(intents.try_parse("zooming in").action, intents.ZOOM_IN)
        command = intents.try_parse("zoom in a lot")
        self.assertEqual(command.action, intents.ZOOM_IN)
        self.assertEqual(command.amount, "lot")

    def test_reset(self):
        for text in ("Reset the globe.", "show me the whole world",
                     "zoom out to the whole Earth", "go back to the globe view"):
            with self.subTest(text=text):
                command = intents.try_parse(text)
                self.assertIsNotNone(command, text)
                self.assertEqual(command.action, intents.RESET_GLOBE, text)

    def test_layers(self):
        command = intents.try_parse("turn on the satellite layer")
        self.assertEqual(command.action, intents.TOGGLE_DATA_LAYER)
        self.assertEqual(command.layer, "satellites")
        self.assertTrue(command.enabled)

        command = intents.try_parse("turn off aircraft")
        self.assertEqual(command.action, intents.TOGGLE_DATA_LAYER)
        self.assertEqual(command.layer, "flights")
        self.assertFalse(command.enabled)

        # Real layer ids from the app's own manifest resolve too.
        self.assertEqual(intents.try_parse("show the cctv layer").layer, "cctv")
        self.assertEqual(intents.try_parse("enable submarine cables").layer,
                         "telegeography-submarine-cables")

    def test_research_and_comparison_are_not_globe_commands(self):
        for text in (
            "Research the best 3D globe libraries.",
            "Compare Cesium and Three.js for globes",
            "What is the best globe library?",
            "Explain how a globe view works",
            "Write documentation for the globe",
        ):
            with self.subTest(text=text):
                self.assertIsNone(intents.try_parse(text), text)

    def test_ordinary_speech_is_not_a_globe_command(self):
        for text in (
            "Tell me a joke",
            "Grow the tomato plants",
            "Go to the settings page",
            "Take me to the settings page",
            "Open the downloads folder",
            "What time is it?",
            "",
            "   ",
        ):
            with self.subTest(text=text):
                self.assertIsNone(intents.try_parse(text), text)

    def test_status(self):
        command = intents.try_parse("is the globe ready?")
        self.assertIsNotNone(command)
        self.assertEqual(command.action, intents.GET_GLOBE_STATUS)

    def test_describe_is_truthful(self):
        command = intents.GlobeCommand(action=intents.NAVIGATE_TO_LOCATION,
                                       location="Kanpur")
        self.assertEqual(intents.describe(command), "Flying to Kanpur.")


class TestNodeRange(unittest.TestCase):
    """The repository's declared engine range, enforced honestly."""

    def test_supported(self):
        self.assertTrue(globe_install.node_in_range("v26.5.0"))
        self.assertTrue(globe_install.node_in_range("v24.14.0"))
        self.assertTrue(globe_install.node_in_range("v24.20.1"))
        self.assertTrue(globe_install.node_in_range("v26.0.0"))

    def test_unsupported(self):
        self.assertFalse(globe_install.node_in_range("v25.3.0"), "Node 25 is EOL")
        self.assertFalse(globe_install.node_in_range("v27.0.0"))
        self.assertFalse(globe_install.node_in_range("v24.13.9"))
        self.assertFalse(globe_install.node_in_range("v20.11.0"))
        self.assertFalse(globe_install.node_in_range(""))

    def test_vendored_checkout_is_valid(self):
        status = globe_install.check()
        self.assertTrue(status.present, status.problems)
        self.assertTrue(status.manifest, status.problems)
        self.assertEqual(status.version, "0.3.0")
        self.assertTrue(status.installed, "run `npm ci` in "
                        f"{status.path}")


class TestJavascriptBuilders(unittest.TestCase):
    """The adapter may only send validated actions and safe arguments."""

    def test_js_string_escapes_injection(self):
        hostile = "a'); window.pwned = 1; //"
        literal = _js_str(hostile)
        self.assertTrue(literal.startswith("'") and literal.endswith("'"))
        self.assertNotIn("');", literal.replace("\\'", ""))
        self.assertIn("\\'", literal)

    def test_runner_script_refuses_nothing_itself_but_is_bounded(self):
        script = _runner_script("fly_to_location", '{"query": "Kanpur"}', "t1")
        self.assertIn("voiceCommands.runner", script)
        self.assertIn("__keysaiGlobeSlots", script)
        self.assertIn("'t1'", script)

    def test_from_runner_preserves_failure(self):
        self.assertFalse(_from_runner({"ok": False, "error": "nope"})["ok"])
        self.assertTrue(_from_runner({"ok": True, "action": "x"})["ok"])


class TestGlobeToolReporting(unittest.TestCase):
    """The tool never claims success it did not observe."""

    def test_unknown_action_is_reported_as_failure(self):
        from globe.tools import globe
        message = globe({"action": "teleport"})
        self.assertIn("Globe:", message)
        self.assertIn("Unknown globe action", message)

    def test_result_descriptions(self):
        from globe.tools import _describe_result
        self.assertIn("flew to Kanpur",
                      _describe_result({"ok": True, "action": "NAVIGATE_TO_LOCATION",
                                        "result": {"label": "Kanpur"}}))
        self.assertIn("Zoomed in", _describe_result({"ok": True, "action": "ZOOM_IN"}))
        self.assertIn("Reset the globe",
                      _describe_result({"ok": True, "action": "RESET_GLOBE"}))
        failure = _describe_result({"ok": False, "error": "server is not running",
                                    "hints": ["Run npm ci"]})
        self.assertIn("server is not running", failure)
        self.assertIn("Run npm ci", failure)


class TestReducedMotionSafety(unittest.TestCase):
    """The layer vocabulary must only contain ids the app really toggles."""

    def test_no_invented_layer_ids(self):
        known_prefixes = {
            "flights", "military", "ais-live-vessels", "satellites",
            "rocket-launches", "earthquakes", "local-firms", "fire-perimeters",
            "weather-cyclones", "weather-radar", "weather-satellite",
            "weather-lightning", "wind", "air-quality", "traffic", "transit",
            "bikeshare", "cctv", "alpr-cameras", "radio", "street-level",
            "recent-imagery", "directions", "military-installations",
            "local-datacenters", "local-dams",
            "telegeography-submarine-cables", "military-awareness",
            "gnss-integrity", "s2-ghostmaps", "local-adsb",
        }
        manifest = _ROOT / "integrations" / "gods_eye_view" / "src" / "voice" / "layerManifest.js"
        if not manifest.exists():
            self.skipTest("vendored app is not present")
        source = manifest.read_text(encoding="utf-8", errors="replace")
        for alias, layer_id in intents.LAYER_ALIASES.items():
            with self.subTest(alias=alias, layer=layer_id):
                self.assertIn(layer_id, known_prefixes)
                self.assertIn(f"id: '{layer_id}'", source,
                              f"{layer_id} is not a layer the app defines")


class _StubUI:
    def __init__(self):
        self.lines = []

    def write_log(self, line):
        self.lines.append(line)


def _drive_router(router, target, utterance):
    """Call the router the way the receive loop does, then drain its task."""
    return asyncio.run(_drive_router_async(router, target, utterance))


async def _drive_router_async(router, target, utterance):
    router(target, utterance)
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


class TestVoiceRoutingGlue(unittest.TestCase):
    """The voice path: recognised speech -> main.py guard -> globe.

    `_receive_audio` hands the recognised transcript to `_route_globe_utterance`
    on every `turn_complete`. These drive that method with synthetic transcripts,
    which is what the checklist asks for when a microphone cannot be automated.
    They are NOT a live-microphone test and are not reported as one.
    """

    def setUp(self):
        try:
            import main as keysai_main
        except Exception as exc:                     # pragma: no cover
            self.skipTest(f"main.py cannot be imported here: {exc}")
        self.router = keysai_main.KeysAILive._route_globe_utterance

    def _target(self, tool_called=False):
        target = mock.Mock()
        target._globe_tool_called = tool_called
        target.ui = _StubUI()
        target.speak = mock.Mock()
        target._session_log = []
        return target

    def test_recognised_speech_opens_the_globe(self):
        for utterance in ("open the globe", "Open GRO.", "show me the Earth",
                          "take me to Kanpur"):
            with self.subTest(utterance=utterance):
                target = self._target()
                with mock.patch("globe.tools.handle_utterance",
                                return_value="The globe is open.") as handler:
                    _drive_router(self.router, target, utterance)
                handler.assert_called_once()
                self.assertEqual(handler.call_args[0][0], utterance)
                self.assertIn("Keys.ai: The globe is open.", target.ui.lines)

    def test_ordinary_speech_is_not_hijacked(self):
        for utterance in ("what is the capital of France",
                          "grow the plant taller",
                          "write a python script",
                          "how do I go home"):
            with self.subTest(utterance=utterance):
                target = self._target()
                with mock.patch("globe.tools.handle_utterance") as handler:
                    _drive_router(self.router, target, utterance)
                handler.assert_not_called()
                self.assertEqual(target.ui.lines, [])

    def test_model_already_handled_it_is_not_run_twice(self):
        target = self._target(tool_called=True)
        with mock.patch("globe.tools.handle_utterance") as handler:
            _drive_router(self.router, target, "open the globe")
        handler.assert_not_called()
        self.assertFalse(target._globe_tool_called,
                         "the flag must reset so the next turn is not suppressed")

    def test_a_globe_failure_does_not_kill_the_voice_loop(self):
        target = self._target()
        with mock.patch("globe.tools.handle_utterance",
                        side_effect=RuntimeError("server died")):
            _drive_router(self.router, target, "open the globe")   # must not raise
        self.assertEqual(target.ui.lines, [])

    def test_receive_loop_still_calls_the_guard(self):
        """Guards the wiring itself: the transcript must reach this method."""
        import inspect
        import main as keysai_main
        source = inspect.getsource(keysai_main.KeysAILive._receive_audio)
        self.assertIn("_route_globe_utterance(full_in)", source,
                      "voice transcripts no longer reach the globe guard")


if __name__ == "__main__":
    unittest.main(verbosity=2)
