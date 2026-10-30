"""actions/make_call.py — REMOVED.

Calling features have been removed from Keys.ai. This module now provides
only stub functions so any legacy imports do not break.
"""


def make_call(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    return (
        "I'm sorry, I cannot make calls. Calling features have been removed "
        "from Keys.ai. I can only send messages via WhatsApp, Telegram, or "
        "other messaging platforms. Please use the send_message or "
        "whatsapp_control tools instead."
    )


def last_call_status() -> str:
    return "Calling features are disabled. Keys.ai can only send messages."
