"""agent_control — Keys.ai Agent Control Mode.

    AppControlEngine   — universal app control facade (spec §2)
    ControlOverlay     — animated gold border + watermark + controls (spec §5-9)
    ControlStateMachine— task execution state machine (spec §22)
    ControlHistory     — KEYS.AI CONTROL HISTORY (spec §12)
    HumourEngine       — optional humour personality layer (spec §15-17)
    ConfirmationGate   — high-impact action confirmation (spec §11)
    EmergencyStop      — global ESC stop + user takeover (spec §9-10)
    tools              — agent_control / agent_settings AI tools (spec §21)

Everything reuses the existing Keys.ai automation stack (automation/), UI
(ui.py), tool registry (core/) and settings; nothing here replaces them.
"""

from agent_control.settings import AgentControlSettings, get_settings
from agent_control.action_log import ControlHistory, get_history
from agent_control.humour import HumourEngine, get_humour
from agent_control.confirmation import ConfirmationGate, get_gate, classify
from agent_control.states import ControlStateMachine, get_machine, ui_status
from agent_control.app_control import AppControlEngine, get_control_engine, \
    init_control_system, ControlStopped

__version__ = "1.0.0"

__all__ = [
    "AgentControlSettings", "get_settings",
    "ControlHistory", "get_history",
    "HumourEngine", "get_humour",
    "ConfirmationGate", "get_gate", "classify",
    "ControlStateMachine", "get_machine", "ui_status",
    "AppControlEngine", "get_control_engine", "init_control_system",
    "ControlStopped",
]
