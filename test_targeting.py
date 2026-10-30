"""Unit tests for the missile-style targeting used by screen control.

Covers automation/targeting.py (missile waypoints + Targeter) and the
one-shot multi-box primitive actions.computer_control._screen_find_boxes.

Run: python test_targeting.py
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from automation.targeting import (  # noqa: E402
    Targeter,
    center,
    missile_waypoints,
)


class MissileWaypointsTests(unittest.TestCase):

    def test_waypoints_bend_and_taper_to_the_target(self):
        wp = missile_waypoints((0, 0), (400, 0), arc=0.2, bends=2)
        self.assertEqual(len(wp), 2)
        # both bends sit on the same perpendicular side (deterministic)
        self.assertTrue(wp[0][1] > 0 and wp[1][1] > 0)
        # the first bend bows more than the second (tapering homing arc)
        self.assertGreater(abs(wp[0][1]), abs(wp[1][1]))
        # x keeps moving toward the target
        self.assertGreater(wp[1][0], wp[0][0])

    def test_waypoints_empty_when_points_coincide(self):
        self.assertEqual(missile_waypoints((50, 50), (55, 52)), [])

    def test_center(self):
        self.assertEqual(center((10, 20, 110, 120)), (60, 70))


class FakeMotion:
    def __init__(self):
        self.pos = (0, 0)
        self.moves = []
        self.streamed = []

    def position(self):
        return self.pos

    def move_to(self, x, y, duration=None, easing="ease_out_cubic",
                waypoints=None, task="move", on_move=None):
        self.moves.append({"x": x, "y": y, "easing": easing,
                           "waypoints": waypoints, "duration": duration})
        if on_move is not None:
            self.streamed.append((int(x), int(y)))
            on_move(int(x), int(y))
        return True


class MinimalMotion:
    """No position()/move_to() — engage() must degrade gracefully."""

    def click(self, x, y):
        return True


class TargeterTests(unittest.TestCase):

    def test_first_engage_launches_from_cursor_box(self):
        reticles = []
        t = Targeter(on_reticle=lambda f, to, s: reticles.append((f, to, s)))
        motion = FakeMotion()
        cx, cy = t.engage(motion, (100, 200, 150, 230), seconds=0.5)
        self.assertEqual((cx, cy), (125, 215))
        # reticle flew from a 48x48 launch box around the cursor (0,0)
        self.assertEqual(reticles[0][0], (-24, -24, 24, 24))
        self.assertEqual(reticles[0][1], (100, 200, 150, 230))
        self.assertEqual(reticles[0][2], 0.5)
        # mouse followed the missile arc
        self.assertEqual(motion.moves[0]["easing"], "missile")
        self.assertTrue(motion.moves[0]["waypoints"])
        self.assertEqual(t.last_rect, (100, 200, 150, 230))

    def test_consecutive_engages_glide_from_the_last_selection(self):
        reticles = []
        t = Targeter(on_reticle=lambda f, to, s: reticles.append((f, to, s)))
        motion = FakeMotion()
        t.engage(motion, (100, 200, 150, 230), seconds=0.4)
        t.engage(motion, (300, 400, 360, 440), seconds=0.4)
        # second glide starts exactly where the first locked
        self.assertEqual(reticles[1][0], (100, 200, 150, 230))
        self.assertEqual(reticles[1][1], (300, 400, 360, 440))

    def test_engage_degrades_without_motion_methods(self):
        t = Targeter()
        cx, cy = t.engage(MinimalMotion(), (100, 200, 150, 230))
        self.assertEqual((cx, cy), (125, 215))   # still returns the center
        self.assertEqual(t.last_rect, (100, 200, 150, 230))

    def test_reset_clears_the_previous_selection(self):
        t = Targeter()
        t.engage(FakeMotion(), (0, 0, 10, 10))
        self.assertIsNotNone(t.last_rect)
        t.reset()
        self.assertIsNone(t.last_rect)

    def test_drawing_callback_errors_are_swallowed(self):
        def boom(*a):
            raise RuntimeError("overlay blew up")
        t = Targeter(on_reticle=boom)
        motion = FakeMotion()
        cx, cy = t.engage(motion, (0, 0, 100, 100))
        self.assertEqual((cx, cy), (50, 50))     # no exception escaped
        self.assertTrue(motion.moves)             # mouse still homed in

    def test_on_move_streams_every_cursor_update(self):
        """A live crosshair callback receives every cursor position while
        the mouse homes in (used by the grid targeting overlay)."""
        t = Targeter()
        motion = FakeMotion()
        seen = []
        t.engage(motion, (100, 200, 150, 230), seconds=0.4,
                 on_move=lambda x, y: seen.append((x, y)))
        self.assertEqual(seen, [(125, 215)])        # fake moves in ONE hop
        self.assertEqual(motion.streamed, [(125, 215)])
        # a raising callback must never stop the mouse or the engage
        t.engage(motion, (300, 400, 360, 440), seconds=0.4,
                 on_move=lambda x, y: (_ for _ in ()).throw(RuntimeError("x")))
        self.assertEqual(t.last_rect, (300, 400, 360, 440))


class ScreenFindBoxesTests(unittest.TestCase):

    def test_single_key_delegates_to_screen_find_box(self):
        import actions.computer_control as cc
        with mock.patch.object(cc, "_screen_find_box",
                               return_value=(1, 2, 31, 42)) as single:
            out = cc._screen_find_boxes({"btn": "the button"})
        single.assert_called_once_with("the button", max_attempts=1)
        self.assertEqual(out, {"btn": (1, 2, 31, 42)})

    def test_multi_key_uses_one_screenshot_one_vision_pass(self):
        import actions.computer_control as cc
        fake_py = mock.Mock()
        fake_py.size.return_value = (1920, 1080)
        fake_py.screenshot.return_value = mock.Mock()
        with mock.patch.object(cc, "pyautogui", fake_py), \
             mock.patch.object(cc, "_require_pyautogui", lambda: None), \
             mock.patch("core.vision.vision_generate_text",
                        return_value='{"search": [10, 20, 100, 40], '
                                     '"composer": [5, 900, 900, 960]}') as vis, \
             mock.patch.object(cc, "_screen_find_box", return_value=None) as single:
            out = cc._screen_find_boxes({"search": "the search box",
                                         "composer": "the composer"})
        self.assertEqual(out["search"], (10, 20, 100, 40))
        self.assertEqual(out["composer"], (5, 900, 900, 960))
        vis.assert_called_once()                # ONE vision call for both
        fake_py.screenshot.assert_called_once()  # ONE screenshot for both
        single.assert_not_called()               # no per-key fallback needed

    def test_multi_key_tops_up_missing_keys(self):
        import actions.computer_control as cc
        fake_py = mock.Mock()
        fake_py.size.return_value = (1920, 1080)
        fake_py.screenshot.return_value = mock.Mock()
        with mock.patch.object(cc, "pyautogui", fake_py), \
             mock.patch.object(cc, "_require_pyautogui", lambda: None), \
             mock.patch("core.vision.vision_generate_text",
                        return_value='{"search": [10, 20, 100, 40]}'), \
             mock.patch.object(cc, "_screen_find_box",
                               return_value=(5, 900, 905, 960)) as single:
            out = cc._screen_find_boxes({"search": "the search box",
                                         "composer": "the composer"})
        self.assertEqual(out["search"], (10, 20, 100, 40))
        self.assertEqual(out["composer"], (5, 900, 905, 960))  # topped up
        single.assert_called_once_with("the composer", max_attempts=1)

    def test_multi_key_falls_back_per_key_when_json_parse_fails(self):
        """A model reply that yields no usable JSON must still locate every
        element — each key falls back to its own individual look (bounded to
        one attempt)."""
        import actions.computer_control as cc
        fake_py = mock.Mock()
        fake_py.size.return_value = (1920, 1080)
        fake_py.screenshot.return_value = mock.Mock()
        with mock.patch.object(cc, "pyautogui", fake_py), \
             mock.patch.object(cc, "_require_pyautogui", lambda: None), \
             mock.patch("core.vision.vision_generate_text",
                        return_value="I see a search box but not the composer."), \
             mock.patch.object(cc, "_screen_find_box",
                               side_effect=[(10, 20, 100, 40), (5, 900, 905, 960)]) as single:
            out = cc._screen_find_boxes({"search": "the search box",
                                         "composer": "the composer"})
        self.assertEqual(out["search"], (10, 20, 100, 40))
        self.assertEqual(out["composer"], (5, 900, 905, 960))
        self.assertEqual(single.call_count, 2)      # one bounded look per key
        single.assert_has_calls([
            mock.call("the search box", max_attempts=1),
            mock.call("the composer", max_attempts=1),
        ])


if __name__ == "__main__":
    unittest.main(verbosity=2)
