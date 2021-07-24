from discord.ext import commands, tasks
from discord import Game, Embed, Member
from loguru import logger
from datetime import datetime
from croniter import croniter
from typing import Optional


class Core(commands.Cog, name="Core"):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("[COG] Core is ready!")
        self.set_status.start()

    @commands.Cog.listener()
    async def on_member_join(self, member):
        embed = Embed(
            description="You have joined Arcadia Redux server!",
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Need help with Patreon membership?", value="Contact **Australia Is My City#9760**")
        embed.set_thumbnail(url="https://cdn.discordapp.com/attachments/684952282076282882/838854388201553930/123.png")
        embed.set_author(
            name="Welcome!"
        )
        await member.send(embed=embed)

    @staticmethod
    def reserved(key: str) -> bool:
        return "-report-channel-id" in key or "-report-channel-name" in key

    @commands.command()
    async def season_reset(self, context: commands.Context):
        date = datetime.utcnow()
        cron = croniter("0 0 1 */3 *", date)
        schedule = "\n".join(str(cron.get_next(datetime)) for _ in range(4))
        await context.send(f"Season Reset schedule:\n{schedule}")

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def link(self, context: commands.Context, key: str, *args):
        if self.reserved(key):
            return
        await context.bot.redis.delete(key)
        await context.bot.redis.rpush(key, *args)
        await context.send(f"Successfully set link keypair")

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def unlink(self, context: commands.Context, key: str):
        if self.reserved(key):
            return
        await context.bot.redis.delete(key)
        await context.send(f"Successfully deleted key <{key}>")

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def list_commands(self, context: commands.Context):
        keys = await context.bot.redis.keys("*")
        commands_list = f"\n".join([key.decode("utf-8") for key in keys])
        await context.send(f"Linked commands:\n```{commands_list}```")

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    @logger.catch
    async def assign(self, context: commands.Context, custom_game_name: str, ch_type: Optional[str] = "report"):
        if not context.message.author.guild_permissions.administrator:
            return
        executor = context.bot.redis.multi_exec()
        executor.set(f"{custom_game_name}-{ch_type}-channel-id", context.channel.id)
        executor.set(f"{custom_game_name}-{ch_type}-channel-name", context.channel.name)
        state_1, state_2 = await executor.execute()

        if ch_type == "report":
            context.bot.report_channels[custom_game_name] = context.channel
        elif ch_type == "chat":
            context.bot.chat_channels[custom_game_name] = context.channel

        if state_1 and state_2:
            await context.channel.send(f"Successfully set {ch_type} channel of {custom_game_name} "
                                       f"to <{context.channel.id}>{context.channel.name}")
            return
        await context.channel.send(f"Something went wrong! Status codes: {state_1}:{state_2}")

    @tasks.loop(minutes=1, reconnect=True)
    async def set_status(self):
        await self.bot.change_presence(activity=Game(
            name=f"UTC: {datetime.utcnow()}"
        ))
