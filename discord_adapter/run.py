"""Discord adapter: one Bot (and one brain/ folder) per channel.

Each human message goes to Bot.on_message; a timer calls Bot.on_tick every TICK_MINUTES (default 60).
Run with: python -m discord_adapter.run   (needs DISCORD_BOT_TOKEN in .env)
Optional: DISCORD_CHANNEL_IDS=123,456 limits the bot to those channels; BRAINS_DIR (default brains/).
"""
import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

import certifi

# python.org builds on macOS ship without root certs, so aiohttp can't verify discord.com.
# Must be set before aiohttp is imported, since it builds its SSL context at import time.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import discord  # noqa: E402
from discord.ext import tasks  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from social_glue.bot import Bot  # noqa: E402 - after load_dotenv so llm.py sees the keys

log = logging.getLogger("glue.discord")
BRAINS = Path(os.getenv("BRAINS_DIR") or "brains")
ALLOWED = {int(c) for c in (os.getenv("DISCORD_CHANNEL_IDS") or "").split(",") if c.strip()}
TICK_MINUTES = float(os.getenv("TICK_MINUTES") or 60)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
bots: dict[int, Bot] = {}
locks: dict[int, asyncio.Lock] = {}


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()  # naive local time, like the sim


def bot_for(channel_id: int) -> Bot:
    if channel_id not in bots:
        bots[channel_id] = Bot(str(BRAINS / str(channel_id)))
        locks[channel_id] = asyncio.Lock()
    return bots[channel_id]


async def say(channel, text: str | None) -> None:
    if text:
        await channel.send(text[:2000])


@client.event
async def on_ready():
    log.info("logged in as %s; channels: %s", client.user, sorted(ALLOWED) or "all")
    if not tick.is_running():
        tick.start()


@client.event
async def on_message(message: discord.Message):
    if message.author.bot or (ALLOWED and message.channel.id not in ALLOWED):
        return
    text = message.content
    if client.user in message.mentions:  # "@Glue" arrives as <@id>; the governor looks for the word "glue"
        text = text.replace(f"<@{client.user.id}>", "@glue").replace(f"<@!{client.user.id}>", "@glue")
    msg = {"name": message.author.display_name, "text": text, "ts": now_iso()}
    bot = bot_for(message.channel.id)
    async with locks[message.channel.id]:
        try:
            reply = await asyncio.to_thread(bot.on_message, msg)
        except Exception:
            log.exception("on_message failed")
            return
        for note in bot.last_notes:
            log.info("[brain %s] %s", message.channel.id, note)
    await say(message.channel, reply)


@tasks.loop(minutes=TICK_MINUTES)
async def tick():
    for channel_id, bot in list(bots.items()):
        channel = client.get_channel(channel_id)
        if channel is None:
            continue
        async with locks[channel_id]:
            try:
                reply = await asyncio.to_thread(bot.on_tick, now_iso())
            except Exception:
                log.exception("on_tick failed")
                continue
        await say(channel, reply)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    for cid in ALLOWED:  # so the timer runs for configured channels even before anyone speaks
        bot_for(cid)
    client.run(os.getenv("DISCORD_BOT_TOKEN") or os.environ["DISCORD_TOKEN"], log_handler=None)


if __name__ == "__main__":
    main()
