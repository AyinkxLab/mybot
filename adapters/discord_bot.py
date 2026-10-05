import asyncio
import sys

import discord

from agent import Agent
from config import DISCORD_TOKEN
from tools import set_approval_handler

_sessions: dict[int, Agent] = {}
_pending = {"approved": False}
APPROVALS = {"approve", "approved", "yes", "y", "go ahead", "push it", "do it", "lgtm"}


def _approve(action: str) -> bool:
    if _pending["approved"]:
        _pending["approved"] = False
        return True
    return False


set_approval_handler(_approve)


def _agent_for(channel_id: int) -> Agent:
    if channel_id not in _sessions:
        _sessions[channel_id] = Agent()
    return _sessions[channel_id]


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
    if content.lower() in APPROVALS:
        _pending["approved"] = True

    async with message.channel.typing():
        try:
            answer = await asyncio.to_thread(_agent_for(message.channel.id).respond, content)
        except Exception as exc:
            answer = f"error: {exc}"
    await message.channel.send(answer[:1900] or "(no reply)")


def main() -> None:
    if not DISCORD_TOKEN:
        print("DISCORD_TOKEN is not set in .env", file=sys.stderr)
        sys.exit(1)
    client.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
