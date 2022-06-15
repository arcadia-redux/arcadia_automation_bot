from discord import colour, InputTextStyle, Interaction, default_permissions
from discord.commands import Option
from discord.ext import commands
from discord.ui import InputText

from .cog_util import *
from .embeds import *
from ..constants import TARGET_GUILD_IDS, DEDICATED_SERVER_KEY, PRESET_REPOSITORIES, PRIVATE_REPOSITORIES, SERVER_LINKS
from ..github_integration import *
from ..views.generic import ModalTextInput
from ..views.github import IssueControls


class Github(commands.Cog, name="Github"):
    def __init__(self, bot):
        self.bot = bot

        self.reply_processors = {
            "assign": self._reply_assign,
            "close": self._reply_close,
            "label": self._reply_label,
            "milestone": self._reply_milestone,
            "title": self._reply_title,
            "description": self._reply_description,
        }

        self.url_regex = re.compile(
            r"(https?:\/\/(.+?\.)?github\.com\/arcadia-redux(\/[A-Za-z0-9\-\._~:\/\?#\[\]@!$&'\(\)\*\+,;\=]*)?)"
        )
        self.numeric_regex = re.compile(r'[-+]?\d+')
        self.line_pointer_regex = re.compile(r'L\d+')

    @commands.slash_command(name="issue", guild_ids=TARGET_GUILD_IDS)
    @default_permissions(
        manage_messages=True
    )
    async def issue_slash_command(
            self,
            context: ApplicationContext,
            repo_name: Option(str, "Repository name", choices=list(PRESET_REPOSITORIES.keys()), required=True),
    ):
        """
        Open new GitHub issue in target repo
        """
        full_repo_name = PRESET_REPOSITORIES.get(repo_name, None)
        if not full_repo_name:
            await context.respond(f"Unknown repo name. Please use one from slash command choices.", ephemeral=True)
            return

        issue_creation_modal = ModalTextInput("Fill issue details", [
            InputText(label="Title", placeholder="Issue title", required=True, style=InputTextStyle.singleline),
            InputText(label="Description", placeholder="Issue description", required=False, style=InputTextStyle.long),
        ])

        @logger.catch
        async def _complete_issue_creation(modal_context, fields):
            status, details = await open_issue_contextless(
                self.bot.session, modal_context.user, full_repo_name, fields["Title"], fields["Description"] or ""
            )
            if not status:
                await modal_context.response.send_message(f"Error creating issue:\n{details}", ephemeral=True)
                return
            embed = await get_issue_embed(self.bot.session, details, details["number"], full_repo_name)
            issue_view = IssueControls(self.bot.session, full_repo_name, details['number'], details)
            msg = await modal_context.response.send_message(
                f"{modal_context.user.mention} opened issue using slash command", embed=embed, view=issue_view
            )
            issue_view.assign_message(await msg.original_message())

        issue_creation_modal.set_callback(_complete_issue_creation)
        await context.send_modal(issue_creation_modal)

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("[COG] Github is ready!")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        reference = message.reference
        if not reference:
            return

        if reference.cached_message:
            replied_message = reference.cached_message
        else:
            replied_message = await message.channel.fetch_message(reference.message_id)

        if replied_message.author != self.bot.user:
            return

        if not replied_message.embeds:
            return

        issue_link_split = replied_message.embeds[0].author.url.split("/")
        issue_number = issue_link_split[-1]
        repo = issue_link_split[-3]

        body = message.content
        message_split = body.split(":")
        reply_command = message_split[0]
        args: List[str] = message_split[1].strip().split(" ") if len(message_split) > 1 else []

        if "https://steamcommunity.com/profiles/" in replied_message.embeds[0].author.url:
            if reply_command.lower() == "send":
                await self._send_feedback_reply(message, replied_message, issue_number, message_split[1:])
            return

        callback = self.reply_processors.get(reply_command.lower(), None)

        if callback:
            status = await callback(message, repo, issue_number, args)
        else:
            if message.attachments:
                body += await process_attachments_contextless(
                    message, self.bot.session, message.attachments[0].url, False
                )

            status, _ = await comment_issue(
                self.bot.session,
                repo,
                issue_number,
                comment_wrap_contextless(body, message)
            )
        if status:
            issue_req_status, details = await get_issue_by_number(self.bot.session, repo, issue_number)
            if issue_req_status:
                await update_issue_embed(self.bot.session, replied_message, details, repo, issue_number)
        await message.add_reaction("✅" if status else "🚫")

    async def _reply_assign(self, message: Message, repo: str, issue_id: str, assignees: List[str]) -> bool:
        for i, assignee in enumerate(assignees):
            if assignee.startswith("<"):
                assignees[i] = await self.bot.redis.hget(
                    "github_mention", assignee.replace("!", ""), encoding='utf8'
                )
                if not assignees[i]:
                    await message.reply(
                        f"**Warning**: Github name for {assignee} is unknown.\n"
                        f"Consider adding it via `$add_github_name @mention github_username`"
                    )
        assignees = list(filter(None, assignees))
        if not assignees:
            return False
        status, _ = await assign_issue(self.bot.session, repo, issue_id, assignees)
        return status

    async def _reply_close(self, message: Message, repo: str, issue_id: str, reason: List[str]) -> bool:
        if len(reason) > 0:
            status, _ = await comment_issue(
                self.bot.session, repo, issue_id, comment_wrap_contextless(" ".join(reason), message, "Closed")
            )
        status, _ = await set_issue_state(self.bot.session, repo, issue_id)
        return status

    async def _reply_label(self, message: Message, repo: str, issue_id: str, labels_base: List[str]) -> bool:
        labels_final = []
        _reading_complex_label = False
        _complex_label = ""
        for m_label in labels_base:
            if m_label.startswith('"'):
                _complex_label = m_label[1:]
                _reading_complex_label = True
                continue
            if m_label.endswith('"'):
                _complex_label += f" {m_label[:-1]}"
                _reading_complex_label = False
                labels_final.append(_complex_label)
                _complex_label = ""
                continue
            if _reading_complex_label:
                _complex_label += m_label
            else:
                labels_final.append(m_label)
        status, repo_labels = await get_repo_labels(self.bot.session, repo)
        if status:
            labels_final_set = set(labels_final)
            repo_label_names = set({label["name"] for label in repo_labels})
            labels_final = list(labels_final_set.intersection(repo_label_names))
            labels_missing = labels_final_set - repo_label_names
            if labels_missing:
                await message.reply(
                    f"**Warning**: Following labels aren't present in target repo and won't be applied:"
                    f"\n`{', '.join(labels_missing)}`"
                )
            if not labels_final:
                return False
        status, _ = await add_labels(self.bot.session, repo, issue_id, labels_final)
        return status

    async def _reply_milestone(self, message: Message, repo: str, issue_id: str, milestones: List[str]) -> bool:
        status, _ = await set_issue_milestone(self.bot.session, repo, issue_id, " ".join(milestones).replace('"', ''))
        return status

    async def _reply_title(self, message: Message, repo: str, issue_id: str, new_title: List[str]) -> bool:
        status, _ = await update_issue(self.bot.session, repo, issue_id, {
            "title": " ".join(new_title),
        })
        return status

    async def _reply_description(self, message: Message, repo: str, issue_id: str, new_body: List[str]) -> bool:
        status, _ = await update_issue(self.bot.session, repo, issue_id, {
            "body": body_wrap_contextless(" ".join(new_body), message),
        })
        return status

    async def __defer_server_link(self, message: Message) -> Optional[str]:
        for custom_game, m_channel in self.bot.report_channels.items():
            if not m_channel or message.channel.id != m_channel.id:
                continue
            return SERVER_LINKS.get(custom_game, None)

    async def __send_feedback_mail(self, steam_id: str, complete_text_content: str, attachments: dict, server_url: str):
        mail_data = {
            "steam_id": steam_id,
            "text_content": complete_text_content,
            "attachments": attachments
        }
        return await self.bot.session.post(
            f"{server_url}api/lua/mail/feedback_reply",
            json=mail_data,
            headers={
                "Dedicated-Server-Key": DEDICATED_SERVER_KEY
            }
        )

    @staticmethod
    async def __add_reply_field(embed: Embed, text_content: str, message: Message, mention: str,
                                jump_url: Optional[str] = None):
        replies_index, replies_field = next(
            ((i, item) for i, item in enumerate(embed.fields) if item.name == "Replies"), (None, None)
        )

        timestamp = int(datetime.utcnow().timestamp())

        if jump_url:
            reply_message_partial = (text_content[:20] + '...') if len(text_content) > 20 else text_content
            reply_message_link = f"<t:{timestamp}:R> [{mention}: {reply_message_partial}]({jump_url})"
        else:
            reply_message_link = f"<t:{timestamp}:R> [Interaction] {mention}: {text_content}"

        if not replies_field:
            embed.add_field(name="Replies", value=reply_message_link, inline=False)
        else:
            new_value = replies_field.value + f"\n{reply_message_link}"
            embed.set_field_at(replies_index, name="Replies", value=new_value, inline=False)

        await message.add_reaction("✉️")
        await message.edit(embed=embed)

    async def _send_feedback_reply(self, message: Message, replied_message: Message, steam_id: str, text_content: list):
        if message.author.guild_permissions.manage_messages is False:
            return await message.reply(f"You don't have enough permission to perform this action.")
        feedback_embed = replied_message.embeds[0]
        feedback_text = feedback_embed.description.replace("```", "")
        processed_text_content = ":".join(text_content).strip()
        attachments = {}
        # parse text content to find and process rewards line
        if '\n' in processed_text_content:
            # process attachments
            content_lines = processed_text_content.split('\n')
            resulting_text_lines = []

            for line in content_lines:
                lower_line = line.lower()

                if not lower_line.startswith("reward:"):
                    resulting_text_lines.append(line)
                    continue

                rewards_line = lower_line.replace("reward:", "")
                rewards = rewards_line.split(",")
                for reward in rewards:
                    value = re.findall(self.numeric_regex, reward)
                    if "currency" in reward and value:
                        attachments["currency"] = abs(int(value[0]))
                    if "fortune" in reward and value:
                        attachments["fortune"] = abs(int(value[0]))
                    if "item" in reward:
                        if "items" not in attachments:
                            attachments["items"] = []
                        attachments["items"].append({
                            "name": reward.strip(),
                            "count": 1
                        })

            processed_text_content = "\n".join(resulting_text_lines)

        final_text_content = f"In response to your feedback message:<br> => {feedback_text}" \
                             f"<br><br>{processed_text_content}"
        server_url = await self.__defer_server_link(replied_message)
        if not server_url:
            await message.add_reaction("🚫")
            return await message.reply(f"Couldn't defer backend URL for this channel.")
        result = await self.__send_feedback_mail(steam_id, final_text_content, attachments, server_url)

        if result.status < 400:
            await self.__add_reply_field(
                feedback_embed, processed_text_content, replied_message,
                message.author.mention, message.jump_url
            )
            await message.add_reaction("✅")
        else:
            await message.add_reaction("🚫")

    @commands.message_command(name="Mail Reply", guild_ids=TARGET_GUILD_IDS)
    @default_permissions(
        manage_messages=True
    )
    async def mail_reply_message_command(self, context: ApplicationContext, message: Message):
        if not message.embeds or not message.embeds[0]:
            return await context.respond("Can't send mail reply to that message.", ephemeral=True, delete_after=10)
        embed = message.embeds[0]
        if "https://steamcommunity.com/profiles/" not in embed.author.url:
            return await context.respond("Can't send mail reply to that message.", ephemeral=True, delete_after=10)
        steam_id = embed.author.url.split("/")[-1]
        feedback_text = embed.description.replace("```", "")

        server_url = await self.__defer_server_link(message)
        if not server_url:
            return await context.respond(
                "Couldn't defer backend server URL for this channel.", ephemeral=True, delete_after=10
            )

        mail_modal = ModalTextInput(title="Fill mail details", fields=[
            InputText(label="Text", placeholder="Your reply goes here...", style=InputTextStyle.long, required=True),
            InputText(label="Fortune", required=False, placeholder="0"),
            InputText(label="Currency", required=False, placeholder="0"),
            InputText(label="Item", required=False, placeholder="item_name_1"),
        ])

        async def on_modal_submit(modal_context: Interaction, fields):
            attachments = {}
            reply_text = fields["Text"]
            reward = []
            if fortune := fields.get("Fortune", None):
                attachments["fortune"] = abs(int(fortune))
                reward.append(f"{attachments['fortune']} <:fortune:831077783446749194>")
            if glory := fields.get("Currency", None):
                attachments["currency"] = abs(int(glory))
                reward.append(f"{attachments['glory']:,} <:glory:964153896341753907>")
            if item := fields.get("Item", None):
                attachments["items"] = [
                    {
                        "name": item.strip(),
                        "count": 1
                    }
                ]
                reward.append(f"`{item}`")

            complete_text_content = f"In response to your feedback message:<br> => {feedback_text}" \
                                    f"<br><br>{fields['Text']}"

            result = await self.__send_feedback_mail(steam_id, complete_text_content, attachments, server_url)
            if result.status >= 400:
                return await modal_context.response.send_message(
                    f"Failed to send mail.\nRequest status code: {result.status}", ephemeral=True, delete_after=10
                )
            if reward:
                reward_string = " ".join(reward)
                reply_text = f"{reply_text}\n**Reward:** {reward_string}"
            await self.__add_reply_field(
                embed, reply_text, message, context.author.mention
            )
            await modal_context.response.send_message(
                f"Successfully sent mail reply!\nReturn to feedback message: {message.jump_url}",
                ephemeral=True, delete_after=20
            )

        mail_modal.set_callback(on_modal_submit)
        await context.send_modal(mail_modal)

    @commands.command()
    async def test_feedback_sending(self, context: Context, steam_id: str, text: str):
        split = text.split(":")
        await self._send_feedback_reply(context.message, context.message, steam_id, split)

    @commands.command()
    async def feedback(self, context: Context):
        await context.send(f"""
You can reply to feedback messages of bot in #chc_feedback channel to send ingame mails to players.
Reply must start with `Send:`. It is possible to attach rewards to the message, adding reward line:
`Reward: 65 glory, 5 fortune, item_mail_test_2`. Reward line must be on new line, rewards should be 
separated by `,`; order of wording in each reward is irrelevant (i.e. both `65 glory` and `glory 65` are valid).
Casing of starting keywords is also irrelevant.
Full example:
```
send: glory to Arstotzka
reward: -10000 glory, -1000 fortune, item_conscription_notification
```
        """.strip())

    @staticmethod
    def process_object_id(object_id: str) -> [str, str, str]:
        new_object_id, *rest = object_id.split("#")
        return new_object_id, *rest[0].split("-")

    async def process_blob_link(self, message: Message, link: str):
        raw_link = link.replace("github", "raw.githubusercontent").replace("blob/", "")
        stripped_link = link.replace("https://github.com/arcadia-redux/", "")
        repo_name, *rest = stripped_link.split("/")
        file_name = rest[-1]
        if "#" not in file_name:
            return
        file_name, line_pointers_string = file_name.split("#")
        rest[-1] = file_name
        if "." in file_name:
            _, extension = file_name.split(".")
        else:
            extension = ""
        line_pointers = [int(line[1:]) for line in re.findall(self.line_pointer_regex, line_pointers_string)]

        raw_content_response = await self.bot.session.get(raw_link, headers=GITHUB_API_HEADERS)
        if raw_content_response.status > 200:
            logger.info(f"{await raw_content_response.text()}")
            return
        raw_content = (await raw_content_response.text()).split("\n")
        if len(line_pointers) == 1:
            resulting_code = raw_content[line_pointers[0] - 1]
        elif len(line_pointers) == 2:
            resulting_code = "\n".join(
                raw_content[line_pointers[0] - 1: line_pointers[1]]
            )
        else:
            logger.info(f"not enough line pointers: {line_pointers}")
            return
        embed = get_code_block_embed(extension, resulting_code, repo_name, line_pointers, rest[1:], link)
        await message.reply(embed=embed)

    @commands.message_command(name="GitHub render", guild_ids=TARGET_GUILD_IDS)
    async def process_github_links(self, context: ApplicationContext, message: Message):
        content = message.content
        links = re.findall(self.url_regex, content)
        links = [link[0] for link in links]
        for link in links:
            if link.endswith("/"):
                link = link[:-1]
            if "/blob/" in link:
                await self.process_blob_link(message, link)
                continue
            repo_name, link_type, object_id = link.split("/")[-3:]
            if repo_name not in PRIVATE_REPOSITORIES:
                continue
            if "#" in object_id:
                object_id, link_type, sub_object_id = self.process_object_id(object_id)
            view = None
            if link_type == "issues" or link_type == "issue":
                status, data = await get_issue_by_number(self.bot.session, repo_name, object_id)
                if not status:
                    continue
                embed = await get_issue_embed(self.bot.session, data, object_id, repo_name, link)
                view = IssueControls(self.bot.session, repo_name, object_id, data)
            elif link_type == "pull":
                status, data = await get_pull_request_by_number(self.bot.session, repo_name, object_id)
                if not status:
                    continue
                embed = await get_pull_request_embed(self.bot.session, data, object_id, repo_name, link)
                view = IssueControls(self.bot.session, repo_name, object_id, data)
            elif link_type == "issuecomment":
                status, data = await get_issue_comment(self.bot.session, repo_name, sub_object_id)
                if not status:
                    continue
                embed = await get_issue_comment_embed(self.bot.session, data, object_id, repo_name, link)
            else:
                return
            if view:
                msg = await message.channel.send(embed=embed, view=view)
                view.assign_message(msg)
            else:
                await message.channel.send(embed=embed)
        await context.respond(f"Found and rendered {len(links)} GitHub links.", ephemeral=True, delete_after=10)

    @commands.command()
    @commands.has_permissions(manage_messages=True)
    async def add_github_name(self, context: commands.Context, user: Member, github_name: str):
        await context.trigger_typing()
        await context.bot.redis.hset("github_mention", user.mention, github_name)
        await context.send(f"Successfully assigned {user.mention} to github name **{github_name}**")

    @commands.command()
    async def github_name(self, context: commands.Context, user: Member):
        await context.trigger_typing()
        github_name = await context.bot.redis.hget("github_mention", user.mention, encoding="utf8")
        if github_name:
            msg = f"Github username of {user.mention} is **{github_name}**"
        else:
            msg = f"No associated Github username for {user.mention} stored!"
        await context.send(msg)

    @commands.command(name="issue", aliases=["i", "issues", "Issues", "I"])
    async def issue(self, context: commands.Context):
        embed = Embed(
            description="Shortcuts are case-insensitive",
            timestamp=datetime.utcnow(),
            colour=colour.Color.dark_teal()
        )
        shortcuts = "\n".join([f"{key.ljust(10)} => {value}" for key, value in PRESET_REPOSITORIES.items()])
        embed.add_field(name="Shortcuts: ", value=f"```{shortcuts}```", inline=False)
        usage = """
`$add_github_name @mention github_username` - assign github name to mentioned user
`$github_name @mention` - get assigned github name of mentioned user
        """
        embed.add_field(name="Usage", value=usage, inline=False)
        reply_description = """
            You can reply to "Opened new issue..." messages from bot to interact with newly opened issue directly.
            Text is interpreted as comments, image attachments are supported.
            Also can be used with starting keyword for different actions:
```
label: bug "help wanted" enhancement "under review"
assign: darklordabc SanctusAnimus ZLOY5
close: duplicate of #12
milestone: new round progress ui  // case insensitive
title: New title, set from bot
description: New description, set from bot
```
        """
        embed.add_field(name="Replying", value=reply_description, inline=False)
        await context.send(embed=embed)
