import io
from asyncio import TimeoutError
from typing import Final, List, Optional
from uuid import uuid1

from PIL import Image
from discord import Embed, Message, Reaction, File
from discord.app.context import InteractionContext
from discord.ext.commands import Context
from loguru import logger

from ..github_integration import preset_repos
from ..views.github import IssueCreation

PAGE_CONTROLS: Final = {"⏮": -1, "⏭": 1}


async def get_argument(context: Context, text: str) -> str:
    argument = None
    msg = await context.reply(text)
    try:
        result = await context.bot.wait_for(
            "message", check=lambda message: message.author == context.message.author, timeout=120
        )
        argument = result.content.strip()
        await result.delete()
        await msg.delete()
    except TimeoutError:
        await msg.delete()
        logger.warning(f"get_argument timed out")
    return argument


def update_embed(embed, desc: str, author: str, footer: str = ""):
    old_embed = embed.to_dict()
    old_embed['description'] = desc
    old_embed['author']["name"] = author
    old_embed["footer"]["text"] = footer
    return Embed().from_dict(old_embed)


async def process_attachments(context, attachment_url: str):
    return await process_attachments_contextless(context.message, context.bot.session, attachment_url)


async def process_attachments_contextless(message, session, attachment_url: str, delete_original: bool = True) -> str:
    logger.info(f"[Image processing] initial image url: {attachment_url}")
    if delete_original:
        prev_text = f"From {message.author.mention}\n```{message.content}```"
    else:
        prev_text = ""

    resp = await session.get(attachment_url)

    content_length = int(resp.headers['Content-Length'])
    logger.info(f"[Image processing] received content length: {content_length}")
    result = io.BytesIO()
    if content_length >= 6e+6:
        warn_msg = await message.reply(
            f"Attached image size exceeded 10mb. Compressing image, issue will be opened afterwards."
        )
        logger.info("[Image processing] compressing image")
        data = io.BytesIO(await resp.read())
        img = Image.open(data)

        # resize for very large images
        if img.width > 1600:
            logger.info(f"Image width exceeded 1600, resizing")
            img = img.resize((img.width // 2, img.height // 2))
        img.save(result, optimize=True, quality=50, format='PNG')
        logger.info(f"new size: {result.tell()}")
        result.seek(0)
        compressed_message = await message.reply(
            f"{prev_text}With compressed image",
            file=File(result, filename=f"resized_image_{uuid1().int}.png")
        )
        attachment_url = compressed_message.attachments[0].url
        logger.info(f"new image url: {attachment_url}")
        await warn_msg.delete()
        if delete_original:
            await message.delete()

    return f"\n![image]({attachment_url})"


async def wait_for_reactions(context: Context, ref_message: Message, expected_reactions: List[str]) -> [bool, str]:
    """
        waits for specific user to react with one of the reactions on specified message
        returns flag of success and index of reaction from passed list
    """

    def reaction_check(reaction: Reaction, user):
        return user == context.message.author and str(reaction.emoji) in expected_reactions and reaction.count > 1

    try:
        reaction, user = await context.bot.wait_for(
            "reaction_add",
            check=reaction_check,
            timeout=60
        )
        representation = str(reaction.emoji)
        if representation not in expected_reactions:
            return False, ""
        return True, representation
    except TimeoutError:
        await ref_message.delete()
        return False, ""


async def wait_for_repo_selection(context: InteractionContext, message: Message) -> Optional[str]:
    view = IssueCreation(message)
    msg = await context.respond(f"Specify target repo: ", view=view, ephemeral=True)
    view.assign_message(msg)
    timed_out = await view.wait()
    if timed_out:
        return None
    return preset_repos[view.values[0]]
