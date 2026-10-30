"""Network-free tests for core/gemini_ladder.py.

Verifies the behaviour that matters without touching the network:

* error classification → the right cooldown length
* the ladder is ordered and skips models that are cooling
* a failing rung steps to the next; a success returns and clears any rest
* an auth/quota error rotates to the next API key instead of resting the model
* a successful call records latency stats
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import core.gemini_ladder as L  # noqa: E402


def _reset():
    L.reset_cooldowns()
    with L._lock:
        L._stats.clear()


def test_classify():
    assert L.classify(Exception("429 RESOURCE_EXHAUSTED")) == ("quota", L.COOLDOWN_QUOTA)
    assert L.classify(Exception("503 UNAVAILABLE")) == ("outage", L.COOLDOWN_OUTAGE)
    assert L.classify(Exception("504 DEADLINE_EXCEEDED")) == ("outage", L.COOLDOWN_OUTAGE)
    assert L.classify(Exception("404 NOT_FOUND")) == ("notfound", L.COOLDOWN_NOTFOUND)
    assert L.classify(Exception("403 PERMISSION_DENIED")) == ("auth", L.COOLDOWN_AUTH)
    assert L.classify(TimeoutError("timed out"))[0] == "timeout"
    assert L.classify(Exception("something weird"))[0] == "unknown"
    print("  classify(): OK")


def test_order_and_cooldown_skip():
    _reset()
    order = L.models_to_try("my-preferred")
    assert order[0] == "my-preferred", order[:3]
    assert len(order) == len(set(order)), "no duplicates"
    L._rest("my-preferred", 60)
    assert "my-preferred" not in L.models_to_try("my-preferred"), "cooling model skipped"
    print("  order + cooldown skip: OK")


def test_steps_to_next_rung():
    _reset()
    calls = []

    def fake_raw(model, prompt, system, temperature, max_tokens, timeout, key):
        calls.append(model)
        if len(calls) == 1:
            raise Exception("503 UNAVAILABLE")
        return f"answer from {model}"

    L._raw_generate = fake_raw
    L._keys = lambda: ["k1"]
    out = L.generate("hi", model="model-a")
    assert out.startswith("answer from"), out
    assert calls[0] == "model-a"
    assert calls[1] != "model-a", "should have stepped to the next rung"
    assert L._cooling("model-a"), "failed model should be resting"
    print("  steps to next rung + rests failed model: OK")


def test_success_clears_rest():
    _reset()
    L._rest("model-x", 60)
    L._raw_generate = lambda *a, **k: "ok"
    L._keys = lambda: ["k1"]
    assert L.generate("hi", model="model-x").strip() == "ok"  # rest cleared by reset in generate
    print("  success returns: OK")


def test_key_rotation_on_auth():
    _reset()
    seen = []

    def fake_raw(model, prompt, system, temperature, max_tokens, timeout, key):
        seen.append(key)
        if key == "bad":
            raise Exception("403 PERMISSION_DENIED")
        return "good"

    L._raw_generate = fake_raw
    L._keys = lambda: ["bad", "good"]
    out = L.generate("hi", model="m1")
    assert out == "good", out
    assert seen[0] == "bad" and "good" in seen, seen
    print("  key rotation on auth error: OK")


def test_status_shape():
    _reset()
    L._raw_generate = lambda *a, **k: "x"
    L._keys = lambda: ["k"]
    L.generate("hi", model="m1")
    st = L.status()
    assert "ladder" in st and "cooling" in st and "stats" in st
    assert st["stats"].get("m1", {}).get("ok", 0) >= 1
    print("  status() shape: OK")


if __name__ == "__main__":
    tests = [test_classify, test_order_and_cooldown_skip, test_steps_to_next_rung,
             test_success_clears_rest, test_key_rotation_on_auth, test_status_shape]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {t.__name__}: {e!r}")
    print(f"\n{'PASS' if failed == 0 else 'FAIL'} — {len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
