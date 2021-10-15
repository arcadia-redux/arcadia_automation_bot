from datetime import timedelta

from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from discord import MessageCommand, SlashCommand, Bot
from discord.app import Option
from discord.app.context import InteractionContext
from discord.ext import commands

from .embeds import *
from ..github_integration import *
from ..views.generic import MultiselectView

_BASE_INTERVAL_CHOICES = ["10 seconds", "10 minutes", "1 hour", "6 hours", "12 hours", "1 day", "3 days", "1 week"]
BASE_INTERVAL_CHOICES = [{"name": interval} for interval in _BASE_INTERVAL_CHOICES]
INTERVAL_UNITS = {
    "second": timedelta(seconds=1),
    "minute": timedelta(minutes=1),
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
    "year": timedelta(days=365),
}

GLOBAL_BOT_REF: Bot


def parse_date_interval(interval_literal: str) -> datetime:
    interval_parts = interval_literal.split(" ")
    desired_date = datetime.now()
    reading_unit = False
    multiplier = 1
    for part in interval_parts:
        part = part.strip()
        if not reading_unit:
            multiplier = float(part)
            reading_unit = True
            continue
        if reading_unit:
            time_delta = next((delta for unit, delta in INTERVAL_UNITS.items() if unit in part), None)
            if time_delta:
                desired_date += multiplier * time_delta
            reading_unit = False
    return desired_date


async def send_reminder(
        source_member_id: Optional[int] = None,
        description: Optional[str] = None,
        source_message_id: Optional[int] = None,
        ref_channel_id: Optional[int] = None
):
    global GLOBAL_BOT_REF
    ref_member = await GLOBAL_BOT_REF.fetch_user(int(source_member_id))
    reminder_text = f"{ref_member.mention}, reminder for you:\n{description if description else ''}"

    if source_message_id:
        source_channel = GLOBAL_BOT_REF.get_channel(int(ref_channel_id))
        ref = await source_channel.fetch_message(int(source_message_id))
        await ref.reply(reminder_text)
    elif ref_channel_id:
        ref = GLOBAL_BOT_REF.get_channel(int(ref_channel_id))
        await ref.send(reminder_text)


class SchedulingCog(commands.Cog):
    def __init__(self, bot):
        # smells like ass, but that way we won't need to pickle bot object as an argument to persistent jobs
        global GLOBAL_BOT_REF
        self.bot = bot
        GLOBAL_BOT_REF = bot
        self.scheduler = AsyncIOScheduler()

        redis_job_store = RedisJobStore(
            host=getenv("REDIS_HOST"), password=getenv("PWD"), jobs_key='SchedulingCog.jobs',
            run_times_key='SchedulingCog.run_times'
        )
        self.scheduler.add_jobstore(redis_job_store)

        self.scheduler.start()

        self.bot.application_command(
            name="Remind about this", cls=MessageCommand, guild_ids=[self.bot.target_guild_ids, ]
        )(self.remind_message_context)

        self.bot.application_command(
            name="reminder", cls=SlashCommand, guild_ids=[self.bot.target_guild_ids, ]
        )(self.remind_slash)

    @commands.command(name="reminder")
    async def remind_default(self, context: Context, interval: str, description: Optional[str] = None):
        """ Remind about something after certain interval """
        desired_date = parse_date_interval(interval)

        self.scheduler.add_job(
            send_reminder, "date", run_date=desired_date,
            args=[context.author.id, description, context.message.id, context.channel.id]
        )

        await context.reply(f"Got it! Will remind you at **{desired_date}**")

    async def remind_slash(
        self, context: InteractionContext,
        interval: Option(
            str,
            "Interval. Example values: 1 week ; 3 days ; 1 hour 25 minutes ; 1.5 hours",
            required=True
        ),
        description: Option(str, "Description", required=True)
    ):
        """ Remind about something after certain interval """
        desired_date = parse_date_interval(interval)
        self.scheduler.add_job(
            send_reminder, "date", run_date=desired_date,
            args=[context.author.id, description, None, context.channel_id]
        )
        await context.respond(f"Got it! Will remind you at **{desired_date}**", ephemeral=True)

    async def remind_message_context(self, context: InteractionContext, message: Message):
        """ Remind about something after certain interval """
        interval_view = MultiselectView(
            "Select delay...", BASE_INTERVAL_CHOICES, min_values=1, max_values=1, is_sorted=True
        )

        def on_complete_transform(view):
            view.complete_description = f"Got it! Will remind you at {parse_date_interval(view.values[0])}"

        interval_view.set_on_complete(on_complete_transform)
        interval_view.set_complete_behaviour("", True)
        msg = await context.respond("Select reminder delay:", view=interval_view, ephemeral=True)
        interval_view.assign_message(msg)

        timed_out = await interval_view.wait()
        if timed_out:
            return

        desired_date = parse_date_interval(interval_view.values[0])

        self.scheduler.add_job(
            send_reminder, "date", run_date=desired_date,
            args=[context.author.id, f"Check out replied message.", message.id, context.channel_id]
        )
