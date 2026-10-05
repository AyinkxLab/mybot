import asyncio
import sys
import threading

import discord

from agent import Agent
from config import DISCORD_ALLOWED_IDS, DISCORD_TOKEN, MAX_SESSIONS
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


def _respond(channel_id: int, text: str) -> str:
    _ctx.chat_id = channel_id
    return _agent_for(channel_id).respond(text)


def _agent_for(channel_id: int) -> Agent:
    if channel_id not in _sessions:
        if len(_sessions) >= MAX_SESSIONS:
            _sessions.pop(next(iter(_sessions)))
        _sessions[channel_id] = Agent()
    return _sessions[channel_id]


def _authorized(user_id: int) -> bool:
    return not DISCORD_ALLOWED_IDS or user_id in DISCORD_ALLOWED_IDS


# Requires the privileged "Message Content Intent" enabled in the Discord dev portal.
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


@client.event
async def on_ready() -> None:
    print(f"Discord bot logged in as {client.user}")


@client.event
async def on_message(message: discord.Message) -> None:
    if message.author == client.user or not message.content:
        return
    if client.user not in message.mentions and not isinstance(message.channel, discord.DMChannel):
        return
    if not _authorized(message.author.id):
        await message.channel.send("not authorized")
        return

    content = message.content
    for mention in message.mentions:
        content = content.replace(mention.mention, "")
    content = content.strip()
    if not content:
        return
    if content == "/reset":
        _agent_for(message.channel.id).reset()
        await message.channel.send("history cleared")
        return
    if content == "/approve":
        action = _last_request.get(message.channel.id)
        if not action:
            await message.channel.send("nothing is waiting for approval")
            return
        _approvals[(message.channel.id, action)] = True
        await message.channel.send("approved. proceeding.")
        content = "Approved. Proceed with the action you requested approval for."

    async with message.channel.typing():
        try:
            answer = await asyncio.to_thread(_respond, message.channel.id, content)
        except Exception as exc:
            answer = f"error: {exc}"
    await message.channel.send(answer[:1900] or "(no reply)")


def main() -> None:
    if not DISCORD_TOKEN:
        print("DISCORD_TOKEN is not set in .env", file=sys.stderr)
        sys.exit(1)
    if not DISCORD_ALLOWED_IDS:
        print("WARNING: DISCORD_ALLOWED_IDS is empty - anyone who messages this bot gets shell access.",
              file=sys.stderr)
    client.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
