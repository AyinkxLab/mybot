import asyncio
import sys
import threading

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from agent import Agent
from config import MAX_SESSIONS, TELEGRAM_ALLOWED_IDS, TELEGRAM_TOKEN
from tools import set_approval_handler

_sessions: dict[int, Agent] = {}
_approvals: dict = {}
_last_request: dict = {}
_ctx = threading.local()


def _approve(action: str) -> bool:
    chat_id = getattr(_ctx, "chat_id", None)
    key = (chat_id, action)
    if _approvals.pop(key, False):
        return True
    _last_request[chat_id] = action
    return False


set_approval_handler(_approve)


def _respond(chat_id: int, text: str) -> str:
    _ctx.chat_id = chat_id
    return _agent_for(chat_id).respond(text)


def _agent_for(chat_id: int) -> Agent:
    if chat_id not in _sessions:
        if len(_sessions) >= MAX_SESSIONS:
            _sessions.pop(next(iter(_sessions)))
        _sessions[chat_id] = Agent()
    return _sessions[chat_id]


def _authorized(user_id: int) -> bool:
    return not TELEGRAM_ALLOWED_IDS or user_id in TELEGRAM_ALLOWED_IDS


async def _on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None or not _authorized(update.effective_user.id):
        await update.message.reply_text("not authorized")
        return
    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()
    if not text:
        return
    if text == "/reset":
        _agent_for(chat_id).reset()
        await update.message.reply_text("history cleared")
        return
    if text == "/approve":
        action = _last_request.get(chat_id)
        if not action:
            await update.message.reply_text("nothing is waiting for approval")
            return
        _approvals[(chat_id, action)] = True
        await update.message.reply_text("approved. proceeding.")
        text = "Approved. Proceed with the action you requested approval for."
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    try:
        answer = await asyncio.to_thread(_respond, chat_id, text)
    except Exception as exc:
        answer = f"error: {exc}"
    await update.message.reply_text(answer[:4000] or "(no reply)")


def main() -> None:
    if not TELEGRAM_TOKEN:
        print("TELEGRAM_TOKEN is not set in .env", file=sys.stderr)
        sys.exit(1)
    if not TELEGRAM_ALLOWED_IDS:
        print("WARNING: TELEGRAM_ALLOWED_IDS is empty - anyone who finds this bot gets shell access.",
              file=sys.stderr)
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT, _on_message))
    print("Telegram bot running. Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
