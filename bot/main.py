import asyncio
import datetime
import json
import os
from typing import Final

import aiohttp
import aioredis
import discord
from aioredis.pubsub import Receiver
from discord import AllowedMentions
from discord.ext import commands, tasks
from loguru import logger

from .cogs import github_cog, core_cog, scheduling_cog
from .constants import CUSTOM_GAMES
from .constants import LOCALS_IMPORTED, SERVER_LINKS  # True if imported local .env file
from .enums import BotState
from .translator import translate_single, translate
from .views.generic import URLView

PREFIX: Final = "$" if not LOCALS_IMPORTED else "%"
token = os.getenv("BOT_TOKEN", None)

__BOT_STATE = BotState.UNSET

intents = discord.Intents.default()
intents.bans = False
intents.integrations = False
intents.webhooks = False
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)
bot.session = aiohttp.ClientSession()
bot.running_local = LOCALS_IMPORTED
bot.add_cog(github_cog.Github(bot), override=True)
bot.add_cog(scheduling_cog.SchedulingCog(bot), override=True)
bot.add_cog(core_cog.Core(bot), override=True)

bot.report_channels = CUSTOM_GAMES.copy()
bot.chat_channels = CUSTOM_GAMES.copy()
bot.queued_chat_messages = CUSTOM_GAMES.copy()
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
    bot.redis = await aioredis.create_redis_pool(os.getenv("REDIS_URL"), password=os.getenv("PWD"))

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


@logger.catch
async def send_suggestion(message: bytes):
    decoded = json.loads(message)
    custom_game = decoded["custom_game"]
    steam_id = decoded["steam_id"]
    text = decoded["text"].strip()
    if len(text) < 3:
        return
    supporter_level = decoded.get("supporter_level", -1)

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
        description=f'```{text.strip()}```',
    )
    embed.set_author(
        name=f"{{{supporter_level}}}  " + profile_name if supporter_level > -1 else profile_name,
        url=f"https://steamcommunity.com/profiles/{steam_id}",
        icon_url=profile_avatar_link or ""
    )
    if translated and language != "en" and translated.strip() != text:
        embed.add_field(name=f"Translation from **{language.upper()}**", value=f"```{translated}```")

    view = URLView()
    backend_url = SERVER_LINKS.get(custom_game)
    view.add_url("Player Profile", f"{backend_url}/players/{steam_id}")
    if match_id := decoded.get("match_id", None):
        view.add_url("Match", f"{backend_url}/matches/details/{match_id}")

    await report_channel.send(embed=embed, allowed_mentions=AllowedMentions.none(), view=view)


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
        return

    message_text = message.content

    channel = message.channel

    if not message_text.startswith(PREFIX):
        for custom_game, m_channel in bot.chat_channels.items():
            if not m_channel or channel.id != m_channel.id:
                continue

            tl_prefix = message_text.lower()[0:3]
            applied_translation = False
            if tl_prefix == "cn:" or tl_prefix == "cn ":
                message_text, detected_language = await translate_single(message_text[3:], "zh-CN")
                await message.reply(f"Sent translated to chinese: {message_text}")
                applied_translation = True
            if tl_prefix == "ru:" or tl_prefix == "ru ":
                message_text, detected_language = await translate_single(message_text[3:], "ru")
                await message.reply(f"Sent translated to russian: {message_text}")
                applied_translation = True

            if not applied_translation:
                translated_text, detected_language = await translate_single(message_text)
                logger.info(f"chat translate, {detected_language=}")
                if detected_language != "en" and translated_text != message_text:
                    await message.reply(f"[TL: {detected_language} => en] {translated_text}", mention_author=False)

            backend_link = SERVER_LINKS.get(custom_game, None)
            if not backend_link:
                continue
            # process chat message sending
            # backend_link = "http://127.0.0.1:5000/"
            resp = await bot.session.post(f"{backend_link}/api/lua/match/send_dev_chat_message", json={
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
                supporter_level = message.get("supporter_level", -1)
                if not message.get("anon", False):
                    m_name = f"**<{message['name']} {{{supporter_level}}}>**"
                else:
                    m_name = f"*<{message['name']} {{{supporter_level}}}>*"

                message_time = message['time'] if type(message['time']) == str else f"<t:{int(message['time'])}:R>"
                built_string = f"{message_time} [{int(message['steam_id']) - 76561197960265728}] {m_name} **:** " \
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