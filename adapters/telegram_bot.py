import asyncio
import sys

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from agent import Agent
from config import TELEGRAM_TOKEN

_sessions: dict[int, Agent] = {}


def _agent_for(chat_id: int) -> Agent:
    if chat_id not in _sessions:
        _sessions[chat_id] = Agent()
    return _sessions[chat_id]


async def _on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()
    if not text:
        return
    if text == "/reset":
        _agent_for(chat_id).reset()
        await update.message.reply_text("history cleared")
        return
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    try:
        answer = await asyncio.to_thread(_agent_for(chat_id).respond, text)
    except Exception as exc:
        answer = f"error: {exc}"
    await update.message.reply_text(answer[:4000] or "(no reply)")


def main() -> None:
    if not TELEGRAM_TOKEN:
        print("TELEGRAM_TOKEN is not set in .env", file=sys.stderr)
        sys.exit(1)
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_message))
    print("Telegram bot running. Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
