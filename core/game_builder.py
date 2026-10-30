"""Deterministic builder for real, playable games.

"Build me a game" used to route to the web path and produce an HTML page with a
canvas and the word GAME in it. Nothing about that is a game: there is no loop,
no state, no way to lose.

This writes a small but genuinely complete arcade game instead, with the two
properties that make it checkable:

* the game **state** is plain Python with no pygame import, so its rules can be
  tested headlessly and deterministically (seeded RNG, fixed timestep);
* the pygame **scene** is a thin renderer/input layer over that state.

``python main.py --selftest`` therefore proves the rules work *and* that pygame
imports and builds a scene under the dummy video driver, without a human
clicking anything and without a display.

Colours come from ``core.design_system`` so a game inherits the same
contrast-checked palette as everything else, rather than a random RGB triple.

Pattern reference (adapted, not copied): the pygame project's own tutorial
introduces the loop/render split this follows —
https://www.pygame.org/docs/tut/newbieguide.html
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from core.design_system import build_tokens

# ── state (no pygame) ────────────────────────────────────────────────────────

_STATE_PY = '''"""Game rules. No pygame here on purpose: the rules must be testable headless."""

from __future__ import annotations

import random

WIDTH = 960
HEIGHT = 600
PLAYER_W = 40
PLAYER_H = 22
PLAYER_SPEED = 430.0          # px per second
BULLET_SPEED = 620.0
BULLET_W = 3
BULLET_H = 14
ENEMY_W = 34
ENEMY_H = 24
ENEMY_SPEED = 90.0
FIRE_COOLDOWN = 0.16
SPAWN_EVERY = 0.85
START_LIVES = 3


class Game:
    """A single run: player, bullets, enemies, score, lives, level."""

    WIDTH = WIDTH
    HEIGHT = HEIGHT

    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed)
        self.reset()

    # -- lifecycle ---------------------------------------------------------
    def reset(self) -> None:
        self.player_x = WIDTH / 2.0
        self.bullets: list[dict] = []
        self.enemies: list[dict] = []
        self.score = 0
        self.lives = START_LIVES
        self.level = 1
        self.over = False
        self.paused = False
        self.elapsed = 0.0
        self._fire_cd = 0.0
        self._spawn_cd = 0.0

    def restart(self) -> None:
        self.rng = random.Random(self.rng.randrange(1 << 30))
        self.reset()

    def toggle_pause(self) -> None:
        if not self.over:
            self.paused = not self.paused

    # -- one tick ----------------------------------------------------------
    def step(self, dt: float, left: bool, right: bool, shoot: bool) -> None:
        """Advance the game by `dt` seconds. Safe to call with dt=0."""
        if self.over or self.paused:
            return
        dt = max(0.0, min(dt, 0.1))          # never let a stall teleport things
        self.elapsed += dt
        self.level = 1 + int(self.score // 12)

        if left and not right:
            self.player_x -= PLAYER_SPEED * dt
        elif right and not left:
            self.player_x += PLAYER_SPEED * dt
        half = PLAYER_W / 2.0
        self.player_x = max(half, min(WIDTH - half, self.player_x))

        # firing
        self._fire_cd = max(0.0, self._fire_cd - dt)
        if shoot and self._fire_cd <= 0.0:
            self.bullets.append({"x": self.player_x, "y": HEIGHT - 70.0})
            self._fire_cd = FIRE_COOLDOWN

        # bullets travel up and leave
        for b in self.bullets:
            b["y"] -= BULLET_SPEED * dt
        self.bullets = [b for b in self.bullets if b["y"] + BULLET_H > 0]

        # spawning gets faster with level
        self._spawn_cd -= dt
        if self._spawn_cd <= 0.0:
            self._spawn_cd = max(0.28, SPAWN_EVERY - 0.06 * (self.level - 1))
            self.enemies.append({
                "x": self.rng.uniform(ENEMY_W, WIDTH - ENEMY_W),
                "y": -ENEMY_H,
                "v": ENEMY_SPEED * (1.0 + 0.12 * (self.level - 1)),
            })

        # enemies fall
        for e in self.enemies:
            e["y"] += e["v"] * dt

        # bullet hits enemy
        survivors: list[dict] = []
        for e in self.enemies:
            hit = False
            for b in self.bullets:
                if (abs(b["x"] - e["x"]) < (ENEMY_W + BULLET_W) / 2 and
                        abs(b["y"] - e["y"]) < (ENEMY_H + BULLET_H) / 2):
                    hit = True
                    try:
                        self.bullets.remove(b)
                    except ValueError:
                        pass
                    break
            if hit:
                self.score += 1
            else:
                survivors.append(e)
        self.enemies = survivors

        # enemy reaches the bottom: cost a life, remove it
        remaining: list[dict] = []
        for e in self.enemies:
            if e["y"] - ENEMY_H / 2 > HEIGHT - 48:
                self.lives -= 1
            else:
                remaining.append(e)
        self.enemies = remaining

        if self.lives <= 0:
            self.lives = 0
            self.over = True


def selftest() -> str:
    """Exercise the rules with no display. Raises AssertionError on a defect."""
    # movement is clamped to the play field
    g = Game(seed=1)
    g.step(0.5, left=True, right=False, shoot=False)
    assert g.player_x >= PLAYER_W / 2, g.player_x
    for _ in range(40):
        g.step(0.1, left=True, right=False, shoot=False)
    assert g.player_x == PLAYER_W / 2, f"left clamp failed: {g.player_x}"

    # shooting spawns one bullet per cooldown, not one per frame
    g = Game(seed=2)
    g.step(1 / 60, False, False, True)
    assert len(g.bullets) == 1, g.bullets
    g.step(1 / 60, False, False, True)
    assert len(g.bullets) == 1, "cooldown did not limit fire rate"

    # a bullet that reaches an enemy scores and removes both. Spawning is
    # pinned off so this asserts the hit, not the spawn timer.
    g = Game(seed=3)
    g._spawn_cd = 1e9
    g.enemies = [{"x": g.player_x, "y": 500.0, "v": 0.0}]
    g.bullets = [{"x": g.player_x, "y": 500.0}]
    g.step(0.0, False, False, False)
    assert g.score == 1, g.score
    assert not g.enemies, g.enemies

    # an enemy that reaches the bottom costs exactly one life
    g = Game(seed=4)
    g._spawn_cd = 1e9
    g.enemies = [{"x": 100.0, "y": HEIGHT - 40.0, "v": 500.0}]
    g.step(0.2, False, False, False)
    assert g.lives == START_LIVES - 1, g.lives
    assert not g.enemies

    # running out of lives ends the run, and pause freezes it
    g = Game(seed=5)
    g._spawn_cd = 1e9
    g.lives = 1
    g.enemies = [{"x": 100.0, "y": HEIGHT - 40.0, "v": 500.0}]
    g.step(0.2, False, False, False)
    assert g.over, "run should be over at zero lives"

    g = Game(seed=6)
    g.toggle_pause()
    before = g.elapsed
    g.step(1.0, True, False, True)
    assert g.elapsed == before, "paused game advanced"

    # restart clears the board
    g.over = True
    g.restart()
    assert not g.over and g.score == 0 and g.lives == START_LIVES

    # the same seed replays identically
    a, b = Game(seed=99), Game(seed=99)
    for _ in range(120):
        a.step(1 / 60, False, False, True)
        b.step(1 / 60, False, False, True)
    assert [e["x"] for e in a.enemies] == [e["x"] for e in b.enemies], \\
        "same seed produced different runs"
    return "state rules OK"
'''

_INIT_PY = '''"""__TITLE__ — a small arcade game."""

__version__ = "1.0.0"
'''

_THEME_PY = '''"""Colours for __TITLE__, generated from the Keys.AI design tokens.

Every pair below was contrast-checked when these tokens were produced
(WCAG 2.2 SC 1.4.3: 4.5:1 body text, 3:1 large text and UI boundaries).
"""

from __future__ import annotations

TITLE = "__TITLE__"

BG = __BG__
PANEL = __PANEL__
INK = __INK__
MUTED = __MUTED__
ACCENT = __ACCENT__
DANGER = __DANGER__
GOOD = __GOOD__
'''

_SCENE_PY = '''"""Rendering and input. All rules live in game.state."""

from __future__ import annotations

import pygame

from game import state
from game import theme


class Scene:
    def __init__(self, game: state.Game) -> None:
        self.game = game
        # Initialise the modules this scene needs itself: a caller that forgets
        # pygame.init() should not get "font not initialized" from here.
        pygame.font.init()
        self.screen = pygame.display.set_mode((game.WIDTH, game.HEIGHT))
        pygame.display.set_caption(theme.TITLE)
        self.font = pygame.font.SysFont("consolas", 20)
        self.small = pygame.font.SysFont("consolas", 16)
        self.big = pygame.font.SysFont("consolas", 44, bold=True)

    # -- helpers -----------------------------------------------------------
    def _text(self, text: str, font, colour, centre=None, topleft=None):
        surface = font.render(text, True, colour)
        rect = surface.get_rect()
        if centre:
            rect.center = centre
        if topleft:
            rect.topleft = topleft
        self.screen.blit(surface, rect)
        return rect

    # -- main loop ---------------------------------------------------------
    def run(self) -> None:
        clock = pygame.time.Clock()
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_ESCAPE, pygame.K_q):
                        running = False
                    elif event.key == pygame.K_p:
                        self.game.toggle_pause()
                    elif event.key == pygame.K_r and self.game.over:
                        self.game.restart()

            keys = pygame.key.get_pressed()
            dt = clock.tick(60) / 1000.0
            self.game.step(
                dt,
                left=bool(keys[pygame.K_LEFT] or keys[pygame.K_a]),
                right=bool(keys[pygame.K_RIGHT] or keys[pygame.K_d]),
                shoot=bool(keys[pygame.K_SPACE] or keys[pygame.K_UP]),
            )
            self.draw()
            pygame.display.flip()

    # -- draw --------------------------------------------------------------
    def draw(self) -> None:
        g = self.game
        self.screen.fill(theme.BG)

        # star field: deterministic, cheap, and it gives the scene depth
        for i in range(60):
            x = (i * 137) % g.WIDTH
            y = (i * 89 + int(g.elapsed * 24)) % g.HEIGHT
            pygame.draw.circle(self.screen, theme.MUTED, (x, y), 1)

        for b in g.bullets:
            pygame.draw.rect(self.screen, theme.ACCENT,
                             (b["x"] - 1, b["y"], 3, 14))
        for e in g.enemies:
            pygame.draw.rect(self.screen, theme.DANGER,
                             (e["x"] - 17, e["y"] - 12, 34, 24), border_radius=4)

        # player: a triangle, so it reads as a ship at a glance
        x = g.player_x
        y = g.HEIGHT - 58
        pygame.draw.polygon(self.screen, theme.GOOD,
                            [(x, y), (x - 20, y + 24), (x + 20, y + 24)])

        self._text(f"SCORE {g.score}", self.font, theme.INK, topleft=(16, 12))
        self._text(f"LIVES {g.lives}", self.font, theme.INK,
                   topleft=(g.WIDTH - 130, 12))
        self._text(f"LEVEL {g.level}", self.font, theme.MUTED,
                   topleft=(g.WIDTH // 2 - 44, 12))
        self._text("A/D or arrows to move   SPACE to fire   P pause   ESC quit",
                   self.small, theme.MUTED, centre=(g.WIDTH // 2, g.HEIGHT - 18))

        if g.paused and not g.over:
            self._text("PAUSED", self.big, theme.ACCENT,
                       centre=(g.WIDTH // 2, g.HEIGHT // 2))
        if g.over:
            self._text("GAME OVER", self.big, theme.DANGER,
                       centre=(g.WIDTH // 2, g.HEIGHT // 2 - 20))
            self._text(f"FINAL SCORE {g.score}   —   R to play again",
                       self.font, theme.INK,
                       centre=(g.WIDTH // 2, g.HEIGHT // 2 + 30))


def selftest() -> str:
    """Prove pygame imports and a scene builds and draws under the dummy driver."""
    import os

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    game = state.Game(seed=11)
    scene = Scene(game)
    for _ in range(120):                 # two seconds at 60 FPS
        game.step(1 / 60, False, False, True)
        scene.draw()
    assert game.elapsed > 1.5, game.elapsed
    return f"pygame {pygame.version.ver} scene OK ({game.elapsed:.2f}s simulated)"
'''

_MAIN_PY = '''"""__TITLE__ — entry point.

    python main.py             play
    python main.py --selftest  check the rules and the scene without a display
"""

from __future__ import annotations

import sys


def selftest() -> int:
    from game import state as game_state
    from game import scene as game_scene

    print(f"rules: {game_state.selftest()}")
    print(f"scene: {game_scene.selftest()}")
    print("OK")
    return 0


def main() -> int:
    import pygame

    from game import scene as game_scene
    from game import state as game_state

    pygame.init()
    try:
        game_scene.Scene(game_state.Game(seed=7)).run()
    finally:
        pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else main())
'''

_REQUIREMENTS = "pygame>=2.6,<3\n"

_README = """# __TITLE__

A small arcade game built by Keys.AI. Real loop, real state, real way to lose.

## Run

```
pip install -r requirements.txt
python main.py
```

## Controls

| Key | Action |
|-----|--------|
| A / D or ← / → | move |
| SPACE or ↑ | fire |
| P | pause |
| R | play again (after game over) |
| ESC or Q | quit |

## Verify without a display

```
python main.py --selftest
```

That runs the rules headlessly (movement clamp, fire cooldown, hit scoring,
life loss, game over, pause, restart, seed replay) and then builds the pygame
scene under the dummy video driver. It prints `OK` only if both pass.

## Layout

| File | Role |
|------|------|
| `game/state.py` | the rules — plain Python, no pygame, fully testable |
| `game/scene.py` | pygame input and drawing over that state |
| `game/theme.py` | colours, taken from the Keys.AI design tokens |
| `main.py` | entry point and `--selftest` |
"""


def _render(template: str, **tokens: str) -> str:
    out = template
    for key, value in tokens.items():
        out = out.replace(f"__{key.upper()}__", str(value))
    return out


def _rgb(hex_colour: str) -> str:
    h = hex_colour.strip().lstrip("#")
    return f"({int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)})"


def _title_from(brief: str) -> str:
    words = [w for w in (brief or "").split() if w.isalnum() or "-" in w][:6]
    if not words:
        return "Arcade"
    stop = {"build", "make", "create", "me", "a", "an", "the", "game", "in",
            "python", "with", "please", "for"}
    kept = [w for w in words if w.lower() not in stop] or words
    return " ".join(w.capitalize() for w in kept[:4])


def build_game(brief: str, out_dir: Path | str, *, on_phase=None,
               on_log=None, verify: bool = True) -> dict:
    """Write the game scaffold, then verify it the way the user would."""
    workspace = Path(out_dir)
    workspace.mkdir(parents=True, exist_ok=True)
    started = time.time()
    checks: list[str] = []

    def phase(name: str, pct: float, detail: str = "") -> None:
        if on_phase:
            try:
                on_phase(name, pct, detail)
            except Exception:
                pass

    def log(line: str) -> None:
        if on_log:
            try:
                on_log(line)
            except Exception:
                pass

    title = _title_from(brief)
    tokens = build_tokens(brief or title, kind="game", mood="dark")
    p = tokens.palette

    phase("designing", 0.1, "palette and rules")
    files: dict[str, str] = {
        "game/__init__.py": _render(_INIT_PY, title=title),
        "game/state.py": _STATE_PY,
        "game/scene.py": _SCENE_PY,
        "game/theme.py": _render(
            _THEME_PY, title=title,
            bg=_rgb(p["bg"]), panel=_rgb(p["panel"]), ink=_rgb(p["ink"]),
            muted=_rgb(p["muted"]), accent=_rgb(p["accent"]),
            danger=_rgb(p["danger"]), good=_rgb(p["success"])),
        "main.py": _render(_MAIN_PY, title=title),
        "requirements.txt": _REQUIREMENTS,
        "README.md": _render(_README, title=title),
    }

    phase("writing", 0.35, f"{len(files)} files")
    for name, content in files.items():
        path = workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        log(f"wrote {name}")

    written = sorted(files)
    if not verify:
        return {"ok": True, "kind": "game", "path": str(workspace),
                "files": written, "entry": "main.py", "checks": [],
                "seconds": round(time.time() - started, 2),
                "message": f"wrote {len(written)} files (not verified)"}

    # ── checks that actually run ──────────────────────────────────────────
    phase("verifying", 0.6, "compiling")
    compile_cmd = [sys.executable, "-m", "py_compile", "main.py",
                   "game/state.py", "game/scene.py", "game/theme.py",
                   "game/__init__.py"]
    proc = subprocess.run(compile_cmd, cwd=str(workspace), capture_output=True,
                          text=True, timeout=120)
    compiled = proc.returncode == 0
    checks.append("compiled" if compiled else
                  f"compile failed: {(proc.stderr or '')[:200]}")
    log(checks[-1])

    ran = False
    output = ""
    if compiled:
        phase("verifying", 0.8, "running --selftest headless")
        env = dict(os.environ)
        env["SDL_VIDEODRIVER"] = "dummy"
        env["SDL_AUDIODRIVER"] = "dummy"
        try:
            proc = subprocess.run([sys.executable, "main.py", "--selftest"],
                                  cwd=str(workspace), capture_output=True,
                                  text=True, timeout=180, env=env)
            output = (proc.stdout or "") + (proc.stderr or "")
            ran = proc.returncode == 0 and "OK" in (proc.stdout or "")
        except Exception as exc:                     # pragma: no cover
            output = f"selftest could not run: {exc}"
        checks.append("selftest OK" if ran else
                      f"selftest FAILED: {output.strip()[:300]}")
        log(checks[-1])

    ok = compiled and ran
    phase("done", 1.0, "verified" if ok else "failed")
    return {
        "ok": ok, "kind": "game", "path": str(workspace),
        "files": written, "entry": "main.py", "checks": checks,
        "seconds": round(time.time() - started, 2),
        "message": (f"{title}: playable arcade game, {len(written)} files, "
                    f"rules and scene self-tested"
                    if ok else
                    "the game was written but its self-test failed — see checks"),
    }
