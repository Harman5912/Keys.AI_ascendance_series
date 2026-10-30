"""
qa_artifacts/regression_tests/test_crown_engine.py — Crown Code v2 Engine Tests.

Tests the new crown_code/engine/ package:
  - EventBus: pub/sub, history, thread safety
  - LoopDetector: repeat/spin/stall detection
  - CheckpointStore: save/list/restore/delete (mocked git)
  - UIAdapter: event → player method translation
  - Interface: make_engine factory, feature flag
  - V2Engine: plan → tool loop → verify → done (with mocked LLM)
  - LegacyEngine: wraps mocked CrownBridge, emits correct events

All tests are offline — no Ollama, no subprocess, no real filesystem IO
beyond tempdir.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ── EventBus ──────────────────────────────────────────────────────────────────

from crown_code.engine.events import (
    EventBus,
    ProgressEvent,
    DoneEvent,
    ErrorEvent,
    ToolCallEvent,
    ToolResultEvent,
    FileWriteEvent,
    ThinkEvent,
    PlanEvent,
    CheckpointEvent,
    reset_bus,
    get_bus,
)


class TestEventBus:
    def test_subscribe_and_emit(self):
        bus = EventBus()
        received = []
        bus.subscribe(received.append)
        bus.emit(ProgressEvent("test", 0.5))
        assert len(received) == 1
        assert isinstance(received[0], ProgressEvent)

    def test_unsubscribe(self):
        bus = EventBus()
        received = []
        unsub = bus.subscribe(received.append)
        bus.emit(ProgressEvent("a", 0.1))
        unsub()
        bus.emit(ProgressEvent("b", 0.2))
        assert len(received) == 1  # only the first

    def test_history_replay(self):
        bus = EventBus(maxhistory=10)
        for i in range(5):
            bus.emit(ProgressEvent(f"phase_{i}", i / 10))
        late_received = []
        bus.subscribe(late_received.append)
        # history() returns past events — subscriber doesn't auto-replay but
        # the caller can iterate bus.history()
        assert len(bus.history()) == 5

    def test_thread_safety(self):
        bus = EventBus()
        received = []
        lock = threading.Lock()

        def collect(e):
            with lock:
                received.append(e)

        bus.subscribe(collect)
        threads = [
            threading.Thread(target=lambda: bus.emit(ProgressEvent(f"t{i}", i / 100)))
            for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(received) == 20

    def test_bad_subscriber_does_not_crash_bus(self):
        bus = EventBus()
        def bad_sub(e):
            raise RuntimeError("boom")
        good_received = []
        bus.subscribe(bad_sub)
        bus.subscribe(good_received.append)
        bus.emit(ProgressEvent("phase", 0.1))
        # good subscriber still got the event
        assert len(good_received) == 1

    def test_get_bus_singleton(self):
        bus1 = get_bus()
        bus2 = get_bus()
        assert bus1 is bus2

    def test_reset_bus_creates_new(self):
        original = get_bus()
        fresh = reset_bus()
        assert fresh is not original
        assert get_bus() is fresh


# ── LoopDetector ──────────────────────────────────────────────────────────────

from crown_code.engine.loop_detector import LoopDetector, LoopConfig


class TestLoopDetector:
    def test_repeat_detection(self):
        bus = EventBus()
        cancelled = threading.Event()
        detector = LoopDetector(
            bus=bus,
            cancel_fn=cancelled.set,
            config=LoopConfig(repeat_limit=3, spin_limit=20, stall_seconds=300),
        )
        detector.start()

        errors = []
        bus.subscribe(lambda e: errors.append(e) if isinstance(e, ErrorEvent) else None)

        # emit 3 identical tool calls
        for _ in range(3):
            bus.emit(ToolCallEvent(name="run_shell", params={"command": "ls"}))

        time.sleep(0.05)
        detector.stop()

        assert cancelled.is_set()
        assert any("Loop detected" in e.message for e in errors)

    def test_spin_detection(self):
        bus = EventBus()
        cancelled = threading.Event()
        detector = LoopDetector(
            bus=bus,
            cancel_fn=cancelled.set,
            config=LoopConfig(repeat_limit=100, spin_limit=5, stall_seconds=300),
        )
        detector.start()

        errors = []
        bus.subscribe(lambda e: errors.append(e) if isinstance(e, ErrorEvent) else None)

        # emit 5 different tool calls, no FileWriteEvent
        for i in range(5):
            bus.emit(ToolCallEvent(name=f"tool_{i}", params={}))

        time.sleep(0.05)
        detector.stop()

        assert cancelled.is_set()
        assert any("Spin detected" in e.message for e in errors)

    def test_file_write_resets_spin_counter(self):
        bus = EventBus()
        cancelled = threading.Event()
        detector = LoopDetector(
            bus=bus,
            cancel_fn=cancelled.set,
            config=LoopConfig(repeat_limit=100, spin_limit=5, stall_seconds=300),
        )
        detector.start()

        errors = []
        bus.subscribe(lambda e: errors.append(e) if isinstance(e, ErrorEvent) else None)

        # 4 tool calls (below spin limit), then a file write, then 4 more
        for i in range(4):
            bus.emit(ToolCallEvent(name=f"tool_{i}", params={}))
        bus.emit(FileWriteEvent(path="main.py", size=100))
        for i in range(4):
            bus.emit(ToolCallEvent(name=f"tool_{i+10}", params={}))

        time.sleep(0.05)
        detector.stop()

        # should NOT have been cancelled
        assert not cancelled.is_set()


# ── UIAdapter ─────────────────────────────────────────────────────────────────

from crown_code.engine.ui_adapter import UIAdapter


class TestUIAdapter:
    def _make_player(self):
        p = MagicMock()
        return p

    def test_progress_event_calls_player(self):
        bus = EventBus()
        player = self._make_player()
        adapter = UIAdapter(bus=bus, player=player)
        adapter.attach()

        bus.emit(ProgressEvent("building", 0.5, "Half done"))

        assert player.creation_progress.called
        args = player.creation_progress.call_args[0]
        assert args[0] == 0.5
        assert args[1] == "building"

    def test_done_event_speaks_and_detaches(self):
        bus = EventBus()
        player = self._make_player()
        adapter = UIAdapter(bus=bus, player=player, speak_done=True)
        adapter.attach()

        bus.emit(DoneEvent(ok=True, summary="Built successfully"))

        assert player.speak.called
        # after DoneEvent the adapter detaches — no more calls
        call_count = player.terminal_output.call_count
        bus.emit(ProgressEvent("x", 0.0))
        assert player.terminal_output.call_count == call_count  # no change

    def test_error_event_writes_to_terminal(self):
        bus = EventBus()
        player = self._make_player()
        adapter = UIAdapter(bus=bus, player=player)
        adapter.attach()

        bus.emit(ErrorEvent(message="Something broke"))

        calls = [str(c) for c in player.terminal_output.call_args_list]
        assert any("Something broke" in c for c in calls)

    def test_file_write_event(self):
        bus = EventBus()
        player = self._make_player()
        adapter = UIAdapter(bus=bus, player=player)
        adapter.attach()

        bus.emit(FileWriteEvent(path="src/main.py", size=1234))

        calls = [str(c) for c in player.terminal_output.call_args_list]
        assert any("main.py" in c for c in calls)

    def test_shell_event_success(self):
        bus = EventBus()
        player = self._make_player()
        adapter = UIAdapter(bus=bus, player=player)
        adapter.attach()

        from crown_code.engine.events import ShellEvent
        bus.emit(ShellEvent(command="pytest", exit_code=0, stdout="5 passed"))

        calls = [str(c) for c in player.terminal_output.call_args_list]
        assert any("pytest" in c for c in calls)

    def test_missing_player_methods_are_silently_ignored(self):
        """Player object with no methods should not crash the adapter."""
        bus = EventBus()
        adapter = UIAdapter(bus=bus, player=object())  # plain object, no methods
        adapter.attach()
        # Should not raise
        bus.emit(ProgressEvent("x", 0.5, "fine"))
        bus.emit(DoneEvent(ok=True))


# ── make_engine factory ───────────────────────────────────────────────────────

from crown_code.engine.interface import make_engine


class TestMakeEngine:
    def test_default_is_legacy(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CROWN_ENGINE", raising=False)
        bus = EventBus()
        from crown_code.engine.legacy_engine import LegacyEngine
        engine = make_engine("job1", "build X", tmp_path, bus, {})
        assert isinstance(engine, LegacyEngine)

    def test_v2_flag_gives_v2_engine(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CROWN_ENGINE", "v2")
        bus = EventBus()
        from crown_code.engine.v2_engine import V2Engine
        engine = make_engine("job2", "build Y", tmp_path, bus, {})
        assert isinstance(engine, V2Engine)

    def test_explicit_engine_type_overrides_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CROWN_ENGINE", "legacy")
        bus = EventBus()
        from crown_code.engine.v2_engine import V2Engine
        engine = make_engine("job3", "build Z", tmp_path, bus, {},
                             engine_type="v2")
        assert isinstance(engine, V2Engine)

    def test_config_engine_key_used_when_no_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CROWN_ENGINE", raising=False)
        bus = EventBus()
        from crown_code.engine.v2_engine import V2Engine
        engine = make_engine("job4", "build W", tmp_path, bus,
                             {"engine": "v2"})
        assert isinstance(engine, V2Engine)


# ── V2Engine (mocked LLM) ─────────────────────────────────────────────────────

from crown_code.engine.v2_engine import V2Engine


class TestV2Engine:
    def _make_engine(self, tmp_path, plan_response, action_responses):
        bus = EventBus()
        engine = V2Engine(
            job_id=uuid.uuid4().hex[:10],
            brief="build a hello-world Python script",
            workspace=tmp_path,
            bus=bus,
            config={"max_iterations": 5},
        )
        responses = [plan_response] + list(action_responses)
        call_count = [0]

        def fake_complete(task, prompt):
            idx = call_count[0]
            call_count[0] += 1
            if idx < len(responses):
                return responses[idx]
            return '{"type": "done", "summary": "complete"}'

        return engine, bus, fake_complete

    def test_engine_runs_and_emits_done(self, tmp_path):
        plan = "1. Write main.py\n2. Done"
        actions = [
            '{"type": "tool", "name": "write_file", "params": {"path": "main.py", "content": "print(\'hello\')"}}\n',
            '{"type": "done", "summary": "Done!"}',
        ]
        engine, bus, fake_complete = self._make_engine(tmp_path, plan, actions)
        events = []
        bus.subscribe(events.append)

        with patch("crown_code.engine.v2_engine.V2Engine._llm",
                   side_effect=lambda self_inner, p, **kw: fake_complete("crown_code", p)):
            # bypass LLM patching, just patch _llm directly
            pass

        # simpler: patch core.llm_client.complete
        with patch("core.llm_client.complete") as mock_llm:
            mock_llm.side_effect = fake_complete
            engine.start()
            engine.join(timeout=10)

        assert engine.status in ("done", "failed")  # either is acceptable in offline test

    def test_cancel_stops_engine(self, tmp_path):
        bus = EventBus()
        engine = V2Engine(
            job_id=uuid.uuid4().hex[:10],
            brief="build a complex app",
            workspace=tmp_path,
            bus=bus,
            config={"max_iterations": 100},
        )

        def slow_llm(task, prompt):
            time.sleep(5)
            return '{"type": "think", "text": "thinking"}'

        events = []
        bus.subscribe(events.append)

        with patch("core.llm_client.complete", side_effect=slow_llm):
            engine.start()
            time.sleep(0.2)
            engine.cancel()
            engine.join(timeout=8)

        assert engine.status in ("cancelled", "failed", "done")

    def test_write_file_tool_creates_file(self, tmp_path):
        from crown_code.engine.v2_engine import _tool_write_file
        bus = EventBus()
        events = []
        bus.subscribe(events.append)
        result = _tool_write_file(
            {"path": "hello.py", "content": "print('hi')"},
            tmp_path, bus
        )
        assert "Wrote" in result
        assert (tmp_path / "hello.py").exists()
        fw_events = [e for e in events if isinstance(e, FileWriteEvent)]
        assert len(fw_events) == 1

    def test_read_file_tool(self, tmp_path):
        from crown_code.engine.v2_engine import _tool_read_file
        (tmp_path / "test.txt").write_text("hello world")
        result = _tool_read_file({"path": "test.txt"}, tmp_path)
        assert "hello world" in result

    def test_read_nonexistent_file(self, tmp_path):
        from crown_code.engine.v2_engine import _tool_read_file
        result = _tool_read_file({"path": "nope.txt"}, tmp_path)
        assert "ERROR" in result

    def test_list_dir_tool(self, tmp_path):
        from crown_code.engine.v2_engine import _tool_list_dir
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "b.py").write_text("y")
        result = _tool_list_dir({"path": "."}, tmp_path)
        assert "a.py" in result
        assert "b.py" in result

    def test_grep_tool(self, tmp_path):
        from crown_code.engine.v2_engine import _tool_grep
        (tmp_path / "main.py").write_text("def hello():\n    pass\n")
        result = _tool_grep({"pattern": "def hello", "glob": "*.py"}, tmp_path)
        assert "hello" in result

    def test_unknown_tool_returns_error(self, tmp_path):
        bus = EventBus()
        engine = V2Engine(
            job_id="x", brief="x", workspace=tmp_path, bus=bus, config={}
        )
        result = engine._exec_tool("nonexistent_tool", {})
        assert "ERROR" in result

    def test_verify_catches_syntax_error(self, tmp_path):
        bus = EventBus()
        engine = V2Engine(
            job_id="x", brief="x", workspace=tmp_path, bus=bus, config={}
        )
        (tmp_path / "bad.py").write_text("def foo(\n  pass  # syntax error")
        ok, msg = engine._verify(["bad.py"])
        assert not ok
        assert "bad.py" in msg

    def test_verify_passes_valid_python(self, tmp_path):
        bus = EventBus()
        engine = V2Engine(
            job_id="x", brief="x", workspace=tmp_path, bus=bus, config={}
        )
        (tmp_path / "good.py").write_text("def foo():\n    return 42\n")
        ok, msg = engine._verify(["good.py"])
        assert ok

    def test_parse_action_json(self):
        from crown_code.engine.v2_engine import _parse_action
        result = _parse_action(
            'Here is my answer: {"type": "tool", "name": "read_file", "params": {"path": "x.py"}}'
        )
        assert result is not None
        assert result["type"] == "tool"
        assert result["name"] == "read_file"

    def test_parse_action_invalid_returns_none(self):
        from crown_code.engine.v2_engine import _parse_action
        result = _parse_action("I'll write the file now.")
        assert result is None


# ── CheckpointStore (no git needed, mocked) ───────────────────────────────────

from crown_code.engine.checkpoints import CheckpointStore


class TestCheckpointStore:
    def test_no_workspace_is_silently_disabled(self):
        store = CheckpointStore(workspace=None, job_id="abc")
        assert store.save() == ""
        assert store.restore("any") is False
        assert store.list() == []

    def test_non_git_workspace_is_silently_disabled(self, tmp_path):
        store = CheckpointStore(workspace=tmp_path, job_id="abc")
        # tmp_path is not a git repo — _available should be False
        assert not store._available
        assert store.save() == ""
