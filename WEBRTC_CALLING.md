# Calling Features — REMOVED

Calling features have been removed from Keys.ai. The AI assistant can only
**send messages** — it cannot make or receive calls.

## What was removed

- `make_call` tool — placed voice/video WhatsApp/Telegram/Signal/Instagram desktop calls
- `whatsapp_control` call action — made WhatsApp Web calls
- Incoming-call receptionist — automatically answered incoming WhatsApp calls
- `call_rules` — pre-set instructions for the receptionist
- `call_audio` — loopback capture and virtual cable for call audio
- WhatsApp call watcher — detected incoming calls on Web and desktop

## What still works

- **WhatsApp messaging** — send messages via WhatsApp desktop app
- **Telegram messaging** — send messages via Telegram
- **Other messaging platforms** — send messages via other platforms
- **WhatsApp Web read actions** — list chats, read messages, open chat, chat meta
- **Google-verified contacts** — contact lookup and verification
- **All other tools** — web search, email, browser control, computer control, etc.

## If you need calling

Calling features can be re-enabled in the future by restoring the removed code
from git history. The calling infrastructure was well-designed and could be
brought back if needed.
