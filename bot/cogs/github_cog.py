import asyncio

from discord import colour, MessageCommand, UserCommand, SlashCommand
from discord.app import Option
from discord.app.context import InteractionContext
from discord.ext import commands, tasks

from .cog_util import *
from .embeds import *
from ..github_integration import *
from ..views.github import IssueControls, IssueCreation

_WarningLabelName: Final[str] = "[Auto] Cleanup warned"


class Github(commands.Cog, name="Github"):
    def __init__(self, bot):
        self.bot = bot
        self.command_list = [
            [["list", "l"], self._list_issues],
            [["close", "c"], self._close_issue],
            [["open", "o"], self._open_issue],
            [["edit", "e"], self._edit_issue],
            [["attach", "at"], self._attach_image],
            [["comment", "c"], self._comment_issue],
            [["search", "s"], self._search_issues],
            [["assign", "as"], self._assign_to_issue],
        ]
        self.private_repos = [
            "reVolt", "custom_hero_clash", "chclash_webserver", "war_masters", "revolt-webserver",
            "pathfinders", "pathfinders-webserver", "dab", "arcadia_automation_bot"
        ]

        self.reply_processors = {
            "assign": self._reply_assign,
            "close": self._reply_close,
            "label": self._reply_label,
            "milestone": self._reply_milestone,
            "title": self._reply_title,
            "description": self._reply_description,
        }

        self.repos_stringified_list = ""
        self.url_regex = re.compile(
            r"(https?:\/\/(.+?\.)?github\.com\/arcadia-redux(\/[A-Za-z0-9\-\._~:\/\?#\[\]@!$&'\(\)\*\+,;\=]*)?)"
        )
        self.numeric_regex = re.compile(r'[-+]?\d+')
        self.line_pointer_regex = re.compile(r'L\d+')

        self.bot.application_command(
            name="[Github] Make Issue", cls=MessageCommand, guild_ids=[self.bot.target_guild_ids, ]
        )(self.issue_message_command)

        self.bot.application_command(
            name="Github Username", cls=UserCommand, guild_ids=[self.bot.target_guild_ids, ]
        )(self.github_username_user_command)

        self.bot.application_command(
            name="issue", cls=SlashCommand, guild_ids=[self.bot.target_guild_ids, ]
        )(self.issue_slash_command)

    async def issue_message_command(self, context: InteractionContext, message: Message):
        content = message.content
        view = IssueCreation(message)
        msg = await context.respond(f"Specify target repo: ", view=view, ephemeral=True)
        view.assign_message(msg)
        timed_out = await view.wait()
        if timed_out:
            return
        selected_repo = preset_repos[view.values[0]]

        status, details = await open_issue_contextless(
            self.bot.session, context.author, selected_repo, content, ""
        )

        if not status:
            logger.warning(f"github issue: {details}")
            return
        embed = await get_issue_embed(self.bot.session, details, details["number"], selected_repo)
        issue_view = IssueControls(self.bot.session, selected_repo, details["number"], details)
        msg = await message.reply(
            f"{context.author.name} opened issue from this message.", embed=embed, view=issue_view
        )
        issue_view.assign_message(msg)

    async def issue_slash_command(
            self,
            context: InteractionContext,
            repo_name: Option(str, "Repository name", choices=list(preset_repos.keys()), required=True),
            title: Option(str, "Issue title", required=True),
            description: Option(str, "Issue description", required=False)
    ):
        """ Open new GitHub issue in target repo """
        full_repo_name = preset_repos.get(repo_name, None)
        if not full_repo_name:
            await context.respond(f"Unknown repo name. Please use one from slash command choices.", ephemeral=True)
            return

        status, details = await open_issue_contextless(
            self.bot.session, context.author, full_repo_name, title, description
        )
        if not status:
            await context.respond(f"Error creating issue:\n{details}", ephemeral=True)
            return
        embed = await get_issue_embed(self.bot.session, details, details["number"], full_repo_name)
        issue_view = IssueControls(self.bot.session, full_repo_name, details['number'], details)
        await context.respond("Success!", ephemeral=True)
        msg = await context.followup.send(
            f"{context.author.name} opened issue using slash command", embed=embed, view=issue_view
        )
        issue_view.assign_message(msg)

    async def github_username_user_command(self, context: InteractionContext, member: Member):
        github_name = await self.bot.redis.hget("github_mention", member.mention, encoding="utf8")
        if github_name:
            msg = f"Github username of {member.mention} is **{github_name}**"
        else:
            msg = f"No associated Github username for {member.mention} stored!"
        await context.respond(msg, ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("[COG] Github is ready!")
        self.repos_stringified_list = await github_init(self.bot)

        if not self.bot.running_local:
            self.scan_old_issues.start()
        else:
            logger.info(f"[Scan] disabled as running on local machine")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        await self.process_github_links(message)

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
        issue_id = issue_link_split[-1]
        repo = issue_link_split[-3]

        body = message.content
        message_split = body.split(":")
        reply_command = message_split[0]
        args: List[str] = message_split[1].strip().split(" ") if len(message_split) > 1 else []

        if "https://steamcommunity.com/profiles/" in replied_message.embeds[0].author.url:
            if reply_command.lower() == "send":
                await self._send_feedback_reply(message, replied_message, issue_id, message_split[1:])
            return

        callback = self.reply_processors.get(reply_command.lower(), None)

        if callback:
            status = await callback(message, repo, issue_id, args)
        else:
            if message.attachments:
                body += await process_attachments_contextless(
                    message, self.bot.session, message.attachments[0].url, False
                )

            status, _ = await comment_issue(
                self.bot.session,
                repo,
                issue_id,
                comment_wrap_contextless(body, message)
            )
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

    async def _send_feedback_reply(self, message: Message, replied_message: Message, steam_id: str, text_content: list):
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
                    if "glory" in reward and value:
                        attachments["glory"] = int(value[0])
                    if "fortune" in reward and value:
                        attachments["fortune"] = int(value[0])
                    if "item" in reward:
                        if "items" not in attachments:
                            attachments["items"] = []
                        attachments["items"].append(reward.strip())

            processed_text_content = "\n".join(resulting_text_lines)

        final_text_content = f"In response to your feedback message:<br> => {feedback_text}" \
                             f"<br><br>{processed_text_content}"

        mail_data = {
            "targetSteamId": steam_id,
            "textContent": final_text_content,
            "attachments": attachments
        }
        result = await self.bot.session.post(
            "https://traefik-chc.dota2unofficial.com/api/lua/mail/feedback_reply",
            json=mail_data
        )

        if result.status < 400:
            replies_index, replies_field = next(
                ((i, item) for i, item in enumerate(feedback_embed.fields) if item.name == "Replies"), (None, None)
            )

            reply_message_partial = (processed_text_content[:20] + '...') if len(
                processed_text_content) > 20 else processed_text_content
            timestamp = int(datetime.utcnow().timestamp())
            reply_message_link = f"<t:{timestamp}:R> [{message.author.name} : {reply_message_partial}]({message.jump_url})"
            if not replies_field:
                feedback_embed.add_field(name="Replies", value=reply_message_link, inline=False)
            else:
                new_value = replies_field.value + f"\n{reply_message_link}"
                feedback_embed.set_field_at(replies_index, name="Replies", value=new_value, inline=False)

            await message.add_reaction("✅")
            await replied_message.add_reaction("✉️")
            await replied_message.edit(embed=feedback_embed)
        else:
            await message.add_reaction("🚫")

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

        raw_content_response = await self.bot.session.get(raw_link, headers=base_api_headers)
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

    async def process_github_links(self, message: Message):
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
            if repo_name not in self.private_repos:
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

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user == self.bot.user or not reaction.message.embeds:
            return
        message = reaction.message
        embed = message.embeds[0]
        author = embed.author

        if not embed or message.author != self.bot.user:
            return

        if reaction.emoji not in PAGE_CONTROLS:
            return

        await message.remove_reaction(reaction.emoji, user)

        params = [param.lower() for param in author.name.split(" ")]
        if params[0] == "issues:":
            page_number = int(embed.footer.text.split(" ")[1]) + PAGE_CONTROLS[reaction.emoji]
            count = params[1]
            state = params[2]
            repo = params[4]
            new_description = await get_issues_list(self.bot.session, repo, state, count, page_number)

            title = f"Issues: {count} {state.capitalize()} in {repo}"
            footer = f"Page: {page_number}"
            await message.edit(embed=update_embed(embed, new_description, title, footer))

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
    async def issue(self, context: commands.Context, *args):
        if len(args) == 0:
            embed = Embed(
                description="Shortcuts are case-insensitive",
                timestamp=datetime.utcnow(),
                colour=colour.Color.dark_teal()
            )
            shortcuts = "\n".join([f"{key.ljust(10)} => {value}" for key, value in preset_repos.items()])
            embed.add_field(name="Shortcuts: ", value=f"```{shortcuts}```", inline=False)
            usage = """
    `$add_github_name @mention github_username` - assign github name to mentioned user
    `$github_name @mention` - get assigned github name of mentioned user
    `$issue [repo name] "[title]" "[description]"` - open shortcut
    `$issue [command]` - bot guidance
    `$issue open war "Test" "Test"` - example of full command for issue opening
            """
            embed.add_field(name="Usage", value=usage, inline=False)
            command_types = """
```
[o] open    - open an issue
[c] close   - close an issue
[e] edit    - edit issue' body and title
[at] attach - attach image to issue (as a comment)
[c] comment - send comment to issue (any text)
[l] list    - list of issues in repo (filtered with -all, -open, -closed)
[as] assign - assign users to specific issue
[s] search  - search issues using github query syntax
```
            """
            embed.add_field(name="Command types", value=command_types, inline=False)
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
            return
        action = args[0]
        args = args[1:]
        await self.handle_bot_command(context, action.lower(), *args)

    @commands.command()
    async def update_repos(self, context: commands.Context):
        await github_init(context.bot)

    async def handle_bot_command(self, context, action, *args):
        args_len = len(args)
        await context.trigger_typing()
        repo = None
        if action in preset_repos:
            repo = preset_repos[action]
            action = "open"
            args = ["", ] + list(args)
            args_len += 1

        if not repo:
            if args_len > 0:
                repo = args[0]
            else:
                repo = await get_argument(
                    context,
                    f"In which repo? Here's possible ones:\n{self.repos_stringified_list}"
                )
            if repo.lower() in preset_repos:
                repo = preset_repos[repo.lower()]
        if not repo:
            return
        await context.trigger_typing()
        for aliases, coro in self.command_list:
            if action in aliases:
                return await coro(context, repo, args, args_len)

    @staticmethod
    async def _list_issues(context: Context, repo: str, args: List[str], args_len: int) -> None:
        state = "open"
        if '-closed' in args: state = "closed"
        if '-all' in args: state = "all"

        count = 10
        page = 1

        embed = Embed(
            description=await get_issues_list(context.bot.session, repo, state, count, page),
            timestamp=datetime.utcnow(),
            colour=colour.Color.dark_teal()
        )

        embed.set_author(
            name=f"Issues: {count} {state.capitalize()} in {repo}",
            url=f"https://github.com/arcadia-redux/{repo}/issues",
            icon_url="https://cdn.discordapp.com/attachments/684952282076282882/838854388201553930/123.png"
        )

        embed.set_footer(text=f"Page: {page}")

        message = await context.send(embed=embed)
        await asyncio.gather(*[message.add_reaction("⏮"), message.add_reaction("⏭")])

    @staticmethod
    async def _close_issue(context: Context, repo: str, args: List[str], args_len: int) -> None:
        issue_id = args[1] if args_len > 1 else await get_argument(context, "Waiting for issue id:")
        status, detail = await set_issue_state(context.bot.session, repo, issue_id)
        if status:
            await context.send(f"Successfully closed issue **#{issue_id}** of **{repo}**")
        else:
            await context.send(f"GitHub error occurred:\n{detail}")

    @staticmethod
    async def _open_issue(context: Context, repo: str, args: List[str], args_len: int) -> None:
        title = args[1] if args_len > 1 else None
        body = args[2] if args_len > 2 else ''
        if args_len > 3:
            message = await context.reply(
                f"Way too much arguments passed! "
                f"**{args_len - 1} / 2** maximum expected arguments for this command.\n"
                f"React with ✅ to **proceed**, with 🚫 to **cancel**. Issue creation will be cancelled automatically after 60 seconds.\n"
                f"_Hint: use \" \" to wrap sentences._"
            )
            await asyncio.gather(*[message.add_reaction("✅"), message.add_reaction("🚫")])

            expected_reactions = ["✅", "🚫"]
            _wait_result, reaction_repr = await wait_for_reactions(context, message, expected_reactions)
            if not _wait_result or not reaction_repr:
                await context.message.delete()
                return
            if reaction_repr == "🚫":
                await context.message.delete()
                await message.delete()
                return
            await message.delete()

        if not title:
            argument = await get_argument(
                context,
                f"Waiting for title. You may add description on the new line of the same message."
            )
            if '\n' not in argument:
                argument += '\n '
            title, body = argument.split("\n")
        if context.message.attachments:
            body += await process_attachments(context, context.message.attachments[0].url)
        status, details = await open_issue(context, repo, title, body)

        if status:
            embed = await get_issue_embed(context.bot.session, details, details["number"], repo)
            issue_view = IssueControls(context.bot.session, repo, details["number"], details)
            msg = await context.send(embed=embed, view=issue_view)
            issue_view.assign_message(msg)
        else:
            await context.reply(f"GitHub error occurred:\n{details}.")

    @staticmethod
    async def _edit_issue(context: Context, repo: str, args: List[str], args_len: int) -> None:
        issue_id = args[1] if args_len > 1 else await get_argument(context, "Waiting for issue id:")
        title = args[2] if args_len > 2 else None
        body = args[3] if args_len > 3 else ''
        if not title:
            argument = await get_argument(
                context,
                f"Waiting for title. You may add description on the new line of the same message."
            )
            if '\n' not in argument:
                argument += '\n'
            title, body = argument.split("\n")
        status, details = await update_issue_title_and_body(context, repo, title, body, issue_id)
        if status:
            await context.reply(f"Successfully updated issue #{issue_id}")
        else:
            await context.reply(f"GitHub error occurred:\n{details}")

    @staticmethod
    async def _attach_image(context: Context, repo: str, args: List[str], args_len: int) -> None:
        issue_id = args[1] if args_len > 1 else await get_argument(context, "Waiting for issue id:")
        if context.message.attachments:
            attachment = context.message.attachments[0]
        else:
            message = await context.send("Awaiting for attachment.")
            try:
                result = await context.bot.wait_for(
                    "message",
                    check=lambda message: message.author == context.message.author and message.attachments,
                    timeout=120
                )
            except TimeoutError:
                await message.delete()
                return
            if not result.attachments:
                await message.delete()
                return
            attachment = result.attachments[0]
        status, comment_data = await comment_issue(
            context.bot.session,
            repo,
            issue_id,
            comment_wrap(await process_attachments(context, attachment.url), context)
        )
        if status:
            await context.send(f"Successfully added comment {comment_data['html_url']}")
        else:
            await context.send(f"Github error occurred: {comment_data}")

    @staticmethod
    async def _comment_issue(context: Context, repo: str, args: List[str], args_len: int) -> None:
        issue_id = args[1] if args_len > 1 else await get_argument(context, "Waiting for issue id:")
        content = args[2] if args_len > 2 else await get_argument(context, "Waiting for comment text:")
        status, comment_data = await comment_issue(context.bot.session, repo, issue_id, comment_wrap(content, context))
        if status:
            await context.send(f"Successfully added comment {comment_data['html_url']}")
        else:
            await context.send(f"Github error occurred: {comment_data}")

    @staticmethod
    async def _assign_to_issue(context: Context, repo: str, args: List[str], args_len: int) -> None:
        logger.info("assign called")
        issue_id = args[1] if args_len > 1 else await get_argument(context, "Waiting for issue id:")
        assignees = args[2:] if args_len > 2 else (await get_argument(context, "Waiting for assignees: ")).split(" ")
        status, details = await assign_issue(context.bot.session, repo, issue_id, assignees)
        if status:
            await context.send(f"Successfully assigned **{', '.join(assignees)}** to issue **{issue_id}**")
        else:
            await context.send(f"Github error occurred:\n```{details}```")

    @staticmethod
    async def _search_issues(context: Context, repo: str, args: List[str], args_len: int) -> None:
        if args_len > 1:
            query = " ".join(args[1:])
        else:
            query = await get_argument(context, "Waiting for search query:")
        status, details = await search_issues(context.bot.session, repo, query)

        if not status:
            await context.send(f"Github error occurred:\n```{details}```")
            return

        results = details["total_count"]
        description = []
        for item in details["items"]:
            link = f"[`#{item['number']}`]({item['html_url']})"
            issue_state = "🟢" if item['state'] == "open" else "🔴"
            description.append(
                f"{issue_state} {link} {item['title']}"
            )

        description.append(
            f"\n[`How to compose queries`](https://docs.github.com/en/github/searching-for-information-on-github/"
            f"searching-on-github/searching-issues-and-pull-requests#search-only-issues-or-pull-requests)"
        )

        embed = Embed(
            title=f"Total search results: {results} {'listing 10' if results > 10 else ''}",
            description="\n".join(description),
            timestamp=datetime.utcnow(),
            colour=colour.Colour.blurple(),
        )
        embed.set_author(name=f"Search in {repo}", url=f"https://github.com/arcadia-redux/{repo}")
        await context.send(embed=embed)

    async def _search_old_issues_in_repo_with_label(self, repo_name: str, label_name: str):
        logger.info(f"[Scan] Scanning old issues in {repo_name} / {label_name}")
        status, data = await search_issues(self.bot.session, repo_name, f"is:open label:{label_name}", per_page=50)
        if not status:
            logger.warning(f"[Scan] Issue search failed: {data}")
            return
        run_time = datetime.utcnow()

        for issue in data["items"]:
            await asyncio.sleep(1)
            issue_number = issue["number"]

            present_labels = [label["name"] for label in issue["labels"]]
            has_warning_label = _WarningLabelName in present_labels

            last_action_date = issue.get("updated_at", issue["created_at"])
            updated_at = datetime.strptime(last_action_date, "%Y-%m-%dT%H:%M:%SZ")
            date_difference = run_time - updated_at
            if date_difference.days < 7:
                continue

            if not has_warning_label:
                logger.info(f"[Scan] Outdated issue {issue_number}, adding label")

                status, _data = await add_labels(
                    self.bot.session, repo_name, issue_number, [_WarningLabelName, *present_labels]
                )
                if not status:
                    logger.warning(f"[Scan] Error when adding labels to issue {issue_number}, {_data}")

                status, _data = await comment_issue(
                    self.bot.session, repo_name, issue_number,
                    f"## Warning  \nThis issue was inactive for **{date_difference.days}** days "
                    f"with label {label_name}.  "
                    f"\nIt will be **closed** automatically after **7** days if this issue stays inactive."
                )
                if not status:
                    logger.warning(f"[Scan] Error when adding labels to issue {issue_number}, {_data}")
            else:
                status, _data = await set_issue_state(self.bot.session, repo_name, issue_number)
                if not status:
                    logger.warning(f"[Scan] Failed to close issue {issue_number} in scan: {_data}")

    @tasks.loop(hours=4, reconnect=True)
    async def scan_old_issues(self):
        logger.info("[Scan] Started")
        for _, repo_name in preset_repos.items():
            label_exists, _ = await get_repo_single_label(self.bot.session, repo_name, _WarningLabelName)

            if not label_exists:
                await create_repo_label(
                    self.bot.session, repo_name, "[Auto] Cleanup warned", "FF4000",
                    "This issue will be closed soon for inactivity and missing replication"
                )
            # github search query doesn't support logical OR for labels, therefore have to iterate over all of them
            for label_name in ['"unknown cause"', '"needs confirmation"', f'"{_WarningLabelName}"']:
                await self._search_old_issues_in_repo_with_label(repo_name, label_name)
                await asyncio.sleep(10)  # solid sleep to ensure we aren't exceeding rate limits
        logger.info("[Scan] Finished")
