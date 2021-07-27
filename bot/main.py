import asyncio
import datetime
import json
import os
from typing import Final, Dict, Any

from .__load_env import LOCALS_IMPORTED  # True if imported local .env file

import aiohttp
import aioredis
import discord
from aioredis.pubsub import Receiver
from discord.ext import commands, tasks
from loguru import logger

from .cogs import github_cog, core_cog
from .enums import BotState
from .translator import translate_single, translate

PREFIX: Final = "$" if not LOCALS_IMPORTED else "%"
token = os.getenv("BOT_TOKEN", None)

__BOT_STATE = BotState.UNSET

intents = discord.Intents.default()
intents.bans = False
intents.integrations = False
intents.webhooks = False
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)
bot.session = aiohttp.ClientSession()
bot.add_cog(github_cog.Github(bot))
bot.add_cog(core_cog.Core(bot))

# ew, hardcode
SERVER_LINKS = {
    "CustomHeroClash": "https://chc-2.dota2unofficial.com/",
    "Dota12v12": "https://api.12v12.dota2unofficial.com/",
    "Overthrow": "https://api.overthrow.dota2unofficial.com/",
    "WarMasters": "https://api.warmasters.dota2unofficial.com/",
}

custom_game_names: Final[Dict[str, Any]] = {key: None for key in SERVER_LINKS.keys()}
bot.report_channels = custom_game_names.copy()
bot.chat_channels = custom_game_names.copy()
bot.queued_chat_messages = custom_game_names.copy()
bot.translation_channel = None

webapi_key = os.getenv("WEBAPI_KEY")


@bot.event
@logger.catch
async def on_ready():
    global __BOT_STATE
    if __BOT_STATE == BotState.SET:
        logger.info(f"Bot is already in state [SET], skipping")
        return
    logger.info("[Ready] Started")
    url = os.getenv("REDIS_URl")
    pwd = os.getenv("PWD")
    bot.redis = await aioredis.create_redis_pool(url, password=pwd)
    bot.running_local = LOCALS_IMPORTED

    logger.add("exec.log", rotation="1 day", retention="1 week", enqueue=True)
    logger.add("error.log", rotation="1 day", retention="1 week", enqueue=True, level="ERROR")

    for custom_game in bot.report_channels.keys():
        executor = bot.redis.multi_exec()
        executor.get(f"{custom_game}-report-channel-id")
        executor.get(f"{custom_game}-report-channel-name")
        ch_id, name = await executor.execute()

        if ch_id and name:
            logger.info(f"[{custom_game}] Assigned report channel: {ch_id}:{name}")
            bot.report_channels[custom_game] = bot.get_channel(int(ch_id))

    for custom_game in bot.chat_channels.keys():
        executor = bot.redis.multi_exec()
        executor.get(f"{custom_game}-chat-channel-id")
        executor.get(f"{custom_game}-chat-channel-name")
        ch_id, name = await executor.execute()

        if ch_id and name:
            logger.info(f"[{custom_game}] Assigned chat channel: {ch_id}:{name}")
            bot.chat_channels[custom_game] = bot.get_channel(int(ch_id))

    receiver = Receiver()

    @logger.catch
    async def reader(channel):
        async for ch, message in channel.iter():
            if ch.name == b'suggestions:*':
                await send_suggestion(message[1])
            elif ch.name == b'chat:*':
                await queue_chat_message(message[1])
        logger.info("finished reading!")

    bot.task = asyncio.ensure_future(reader(receiver))
    await bot.redis.psubscribe(receiver.pattern('suggestions:*'))
    await bot.redis.psubscribe(receiver.pattern('chat:*'))

    send_queued_chat_messages.start()
    __BOT_STATE = BotState.SET
    logger.info(f"[Ready] Finished")


@bot.command()
async def state(ctx):
    await ctx.send(__BOT_STATE)


@bot.command()
async def list_users(context: commands.Context):
    messages = await context.channel.history(limit=10).flatten()
    users = {}
    embeds = {}
    for message in messages:
        users[message.author.id] = message.author.name
        embeds[message.id] = message.embeds[0].title if message.embeds and message.embeds[0] and message.embeds[0].title else None
    titles = "\n".join([f"{_id}: {title}" for _id, title in embeds.items() if title is not None])
    await context.send(f"""
    Users: {", ".join([f"{_id}:{user}" for _id, user in users.items()])}
    Embed titles: {titles}
    """)


@logger.catch
async def send_suggestion(message: bytes):
    decoded = json.loads(message)
    custom_game = decoded["custom_game"]
    steam_id = decoded["steam_id"]
    text = decoded["text"]

    logger.info(f"Message from channel {custom_game} by {steam_id}: {text}")

    translated, language = await translate_single(text)

    report_channel = bot.report_channels.get(custom_game, None)
    if not report_channel:
        return

    resp = await bot.session.get(
        f"http://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/?key={webapi_key}&steamids={steam_id}"
    )
    steam_profile_data = None
    if resp.status == 200:
        steam_profile_data = await resp.json()

    profile_avatar_link, profile_name = None, None
    if steam_profile_data:
        steam_profile_data = steam_profile_data["response"]["players"][0]
        profile_avatar_link = steam_profile_data["avatarmedium"]
        profile_name = steam_profile_data["personaname"]

    embed = discord.Embed(
        timestamp=datetime.datetime.utcnow(),
        description=f'```{decoded["text"].strip()}```',
    )
    embed.set_author(
        name=profile_name,
        url=f"https://steamcommunity.com/profiles/{steam_id}",
        icon_url=profile_avatar_link or ""
    )
    if translated and language != "en":
        embed.add_field(name=f"Translation from **{language.upper()}**", value=f"```{translated}```")

    if custom_game == "CustomHeroClash" and steam_id:
        embed.add_field(
            name=f"🌟 Reward 🌟",
            value="\t|\t".join(
                f"[{i}<:fortune:831077783446749194>](https://chc-2.dota2unofficial.com/api/lua/mail/feedback"
                f"?steam_id={steam_id}&fortune_value={i})" for i in
                [5, 10, 25, 50, 100]),
            inline=False
        )

    await report_channel.send(embed=embed)


async def queue_chat_message(message: bytes):
    decoded = json.loads(message)
    custom_game = decoded["custom_game"]
    if custom_game not in bot.queued_chat_messages:
        bot.queued_chat_messages[custom_game] = []
    bot.queued_chat_messages[custom_game].append(decoded)


@bot.event
@commands.has_permissions(manage_messages=True)
async def on_message(message: discord.Message):
    if message.author.bot:
        if message.author.id != 682861064517451855 or not message.embeds:
            return
        embed = message.embeds[0]
        if not embed.title:
            return
        title = embed.title.lower()
        if "main success on" in title or "github actions checks success on" in title:
            await message.delete()
        return

    message_text = message.content

    channel = message.channel

    if not message_text.startswith(PREFIX):
        for custom_game, m_channel in bot.chat_channels.items():
            if not m_channel or channel.id != m_channel.id:
                continue

            tl_prefix = message_text.lower()[0:3]
            if tl_prefix == "cn:" or tl_prefix == "cn ":
                message_text, detected_language = await translate_single(message_text[3:], "zh-CN")
                await message.reply(f"Sent translated to chinese: {message_text}")
            if tl_prefix == "ru:" or tl_prefix == "ru ":
                message_text, detected_language = await translate_single(message_text[3:], "ru")
                await message.reply(f"Sent translated to russian: {message_text}")

            backend_link = SERVER_LINKS.get(custom_game, None)
            if not backend_link:
                continue
            # process chat message sending
            # backend_link = "http://127.0.0.1:5000/"
            resp = await bot.session.post(f"{backend_link}api/lua/match/send_dev_chat_message", json={
                "steamId": -1,
                "customGame": custom_game,
                "steamName": message.author.name,
                "text": message_text
            })
            if resp.status >= 400:
                await message.add_reaction("🚫")
            return

    if not message_text.startswith(PREFIX) or bot.get_cog("Core").reserved(message_text):
        await bot.process_commands(message)
        return

    command_key = message_text.split(" ")[0][1:]
    if command_value := await bot.redis.lrange(command_key, 0, 100):
        result = "\n".join([val.decode("utf-8") for val in command_value])
        await message.channel.send(result)

    await bot.process_commands(message)


@bot.event
@logger.catch
async def on_command_error(context, err):
    logger.error(f"[ON_COMMAND] {err.args!r}")


@tasks.loop(seconds=10, reconnect=True)
async def send_queued_chat_messages():
    for custom_game, queue in bot.queued_chat_messages.items():
        if queue and len(queue) > 0:
            current_msg_len = 0

            channel = bot.chat_channels.get(custom_game, None)
            if not channel:
                continue

            compound_message = []

            messages_content = [message["text"] for message in queue]
            translated = await translate(messages_content)

            for i, message in enumerate(queue):
                translation = translated[i]
                if translation.detected_language_code != "en":
                    translated_text = f"(TL [**{translation.detected_language_code}**]: {translation.translated_text})"
                else:
                    translated_text = ""
                m_name = f"**<{message['name']}>**" if not message.get("anon", False) else f"*<{message['name']}>*"
                built_string = f"{message['time']} [{int(message['steam_id']) - 76561197960265728}] {m_name} **:** " \
                               f"{message['text']} \t {translated_text}"
                current_msg_len += len(built_string)
                compound_message.append(built_string)

                if current_msg_len >= 1800:  # actual message length limit is ~2048, but just to be sure
                    await channel.send("\n".join(compound_message))
                    compound_message = []
                    current_msg_len = 0
            await channel.send("\n".join(compound_message))
        bot.queued_chat_messages[custom_game] = []


bot.run(token)
