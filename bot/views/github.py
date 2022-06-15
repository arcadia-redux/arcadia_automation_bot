from datetime import datetime

from discord import Interaction, ButtonStyle, Embed, Colour
from discord.ui import button, Button
from loguru import logger

from .generic import TimeoutView, MultiselectView, TimeoutErasingView, MultiselectDropdown, ActionButton
from .views_subdata import close_reason_selection, reopen_reason_selection
from ..cogs.embeds import get_issue_embed, parse_markdown
from ..constants import PRESET_REPOSITORIES, Union
from ..github_integration import *


class IssueCreation(TimeoutErasingView):
    def __init__(self, ref_message: Message):
        self.ref_message = ref_message
        self.values = {}
        super().__init__()

        repos_selection = [
            {
                "name": shortcut,
                "description": full_name
            } for shortcut, full_name in PRESET_REPOSITORIES.items()
        ]

        self.add_item(MultiselectDropdown("Select repo...", repos_selection, 1, 1))


class IssueControls(TimeoutView):
    def __init__(self, session, repo: str, github_id: int, issue_data: Optional[dict] = None):
        self.session = session
        self.repo = repo
        self.github_id = github_id
        self.details = issue_data if issue_data else {}
        super().__init__()

        base_label = "Reopen" if self.details["state"] == "closed" else "Close"
        base_style = ButtonStyle.success if self.details["state"] == "closed" else ButtonStyle.red

        close_button = ActionButton(base_label, base_style)
        close_button.set_callback(lambda _button, interaction: self.set_issue_state(_button, interaction))

        self.add_item(close_button)

    async def _update_details(self):
        """
        Since any button changes issue data, we should update it after every successful interaction,
        and update issue embed
        """
        status, data = await get_issue_by_number(self.session, self.repo, self.github_id)
        if status:
            self.details = data
            new_embed = await get_issue_embed(self.session, self.details, self.github_id, self.repo)

            if self.assigned_message:
                self.assigned_message = await self.assigned_message.edit(
                    content=self.assigned_message.content, embed=new_embed, view=self
                )
            else:
                logger.warning(f"_update_details missing assigned message!")

    @button(label="Edit Labels", style=ButtonStyle.green)
    async def edit_labels_action(self, _button: Button, interaction: Interaction):
        """
        Edit labels of an issue, allowing to select from 0 (removing all labels) up to 10.
        """
        status, data = await get_repo_labels(self.session, self.repo)
        if not status:
            await interaction.response.send_message(f"Error!\n{data}", ephemeral=True)
            return

        present_labels = [label["name"] for label in self.details.get("labels", [])]
        for label_data in data:
            label_data["selected"] = label_data["name"] in present_labels

        view = MultiselectView("Select labels...", data)
        msg = await interaction.response.send_message("Select labels:", view=view, ephemeral=True)
        view.assign_message(msg)

        timed_out = await view.wait()
        if not timed_out:
            await add_labels(self.session, self.repo, self.github_id, view.values)
            await self._update_details()

    @button(label="Edit Assignees", style=ButtonStyle.green)
    async def edit_assignees(self, _button: Button, interaction: Interaction):
        """ Edit assignees of an issue, allowing to select from 0 (removing all assignees) up to 10 """
        status, data = await get_arcadia_team_members(self.session)
        if not status:
            await interaction.response.send_message(f"Error!\n{data}", ephemeral=True)
            return

        assigned_members = [member["login"] for member in self.details.get("assignees", [])]
        view_data = [
            {
                "name": assignee["login"],
                "selected": assignee["login"] in assigned_members
            }
            for assignee in data
        ]

        view = MultiselectView("Select assignees...", view_data)
        msg = await interaction.response.send_message("Select assignees:", view=view, ephemeral=True)
        view.assign_message(msg)

        timed_out = await view.wait()
        if not timed_out:
            # assignees that were removed from final selection
            complete_selection = set(view.values)
            removed_assignees = set(assigned_members) - complete_selection

            await assign_issue(self.session, self.repo, self.github_id, view.values)

            if len(removed_assignees) > 0:
                await deassign_issue(self.session, self.repo, self.github_id, list(removed_assignees))

            await self._update_details()

    @button(label="Edit milestone", style=ButtonStyle.green)
    async def edit_milestone(self, _button: Button, interaction: Interaction):
        """ Edit active milestone for this issue. Can only select one. """
        status, repo_milestones = await get_repo_milestones(self.session, self.repo)

        base_milestone = self.details.get("milestone", {}) or {}
        view_data = [
            {
                "name": milestone["title"],
                "description": milestone["description"],
                "selected": milestone["number"] == base_milestone.get("number", -1)
            }
            for milestone in repo_milestones
        ]

        view = MultiselectView("Select milestone...", view_data, 1, 1)
        msg = await interaction.response.send_message("Select milestone:", view=view, ephemeral=True)
        view.assign_message(msg)
        timed_out = await view.wait()

        if not timed_out:
            selected_milestone = view.values[0].lower().strip()
            selected_milestone_number = next(
                (item for item in repo_milestones if item["title"].lower().strip() == selected_milestone), {}
            ).get("number", -1)

            if selected_milestone_number == -1:
                return

            await set_issue_milestone_raw(self.session, self.repo, self.github_id, selected_milestone_number)
            await self._update_details()

    @button(label="View comments", style=ButtonStyle.green)
    async def view_comments(self, _button: Button, interaction: Interaction):
        view = GithubPaginationControls(self.session, self.repo, self.github_id)
        status, embed = await view.get_embed(interaction)
        if not status:
            return
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def set_issue_state(self, _button: Button, interaction: Interaction):
        """ Executed by ActionButton callback created and assigned in __init__ """
        desired_state = "closed" if self.details["state"] == "open" else "open"
        comment_state = "Closed" if self.details["state"] == "open" else "Reopen"
        selection = close_reason_selection if self.details["state"] == "open" else reopen_reason_selection
        reason_view = MultiselectView("Select reason...", selection, max_values=1)
        msg = await interaction.response.send_message(
            f"Please select basic reason.\n"
            f"Issue **won't be {comment_state.lower()}** until you pick one or this message times out (10 minutes)",
            view=reason_view, ephemeral=True
        )
        reason_view.assign_message(msg)
        timed_out = await reason_view.wait()
        close_reason = ""
        if not timed_out:
            close_reason = reason_view.values[0] + ".\n"

        status, _ = await comment_issue(
            self.session,
            self.repo,
            self.github_id,
            f"{close_reason}{comment_state} from Discord using Issue Controls button by "
            f"**{interaction.user.name}#{interaction.user.discriminator}**"
        )

        status, data = await set_issue_state(
            self.session, self.repo, self.github_id, desired_state
        )

        _button.style = ButtonStyle.success if data["state"] == "closed" else ButtonStyle.red
        _button.label = "Reopen" if data["state"] == "closed" else "Close"

        await self._update_details()

    @button(emoji="✖️", style=ButtonStyle.danger, row=3)
    async def cancel_view(self, _button: Button, interaction: Interaction):
        self.stop()
        await self.remove_view_from_message()


class GithubPaginationControls(TimeoutView):
    def __init__(self, session: ClientSession, repo: str, github_id: Union[str, int]):
        self.session = session
        self.repo_name = repo
        self.github_id = github_id
        self.details = None

        self.current_page = 0
        self.pages_dates = [None for _ in range(100)]

        super().__init__()

    @button(emoji="⏮️", style=ButtonStyle.green)
    async def prev_page(self, _button: Button, interaction: Interaction):
        if self.current_page == 0:
            await interaction.response.send_message(f"Reached beginning of the conversation!", ephemeral=True)
            return
        self.current_page -= 1
        status, embed = await self.get_embed(interaction)
        if not status:
            return
        await interaction.response.edit_message(embed=embed)

    @button(emoji="⏭️", style=ButtonStyle.green)
    async def next_page(self, _button: Button, interaction: Interaction):
        self.current_page += 1
        status, embed = await self.get_embed(interaction)
        if not status:
            return
        await interaction.response.edit_message(embed=embed)

    @staticmethod
    def preprocess_comment_body(comment_body) -> [str, str]:
        appropriate_lines = []
        override_author = None
        for line in comment_body.split("\n"):
            if "Follow the conversation" in line:
                continue
            original_author_quote_start = line.find("from Discord by")
            if original_author_quote_start != -1:
                override_author = line[original_author_quote_start + 15:].strip()
                continue
            appropriate_lines.append(line)
        return "\n".join(appropriate_lines), override_author

    async def get_embed(self, interaction: Interaction):
        since_date = self.pages_dates[self.current_page]
        status, self.details = await get_issue_comments(
            self.session, self.repo_name, self.github_id, since_date
        )
        if not status:
            await interaction.response.send_message(f"Github error occurred:\n{self.details}", ephemeral=True)
            return False, None
        if len(self.details) <= 0:
            await interaction.response.send_message(f"No comments for that issue/PR exist yet.", ephemeral=True)
            return False, None
        return True, await self.__generate_embed()

    async def __generate_embed(self) -> Embed:
        embed_body = []
        current_length = 0

        for comment in self.details:
            override_author = None

            new_body = comment["body"] or ""
            if comment['user']['login'] == "ArcadiaReduxAutomation":
                new_body, override_author = self.preprocess_comment_body(new_body)

            if len(new_body) > 500:
                new_body = new_body[:1000] + " ..."

            new_body = await parse_markdown(self.session, new_body, self.repo_name)

            created_at_date = datetime.strptime(comment['created_at'], "%Y-%m-%dT%H:%M:%SZ")
            comment_timestamp = created_at_date.timestamp()

            if override_author:
                user_link = f"{override_author} via [**{comment['user']['login']}**]({comment['user']['html_url']})"
            else:
                user_link = f"[**{comment['user']['login']}**]({comment['user']['html_url']})"

            comment_entry = f"**<t:{int(comment_timestamp)}:R>** " \
                            f"{user_link}:\n{new_body}\n"
            comment_entry_len = len(comment_entry)
            if comment_entry_len + current_length < 2000:
                current_length += comment_entry_len
                embed_body.append(
                    comment_entry
                )
            else:
                self.pages_dates[self.current_page + 1] = comment["created_at"]
                break
        embed = Embed(
            title=f"Page: {self.current_page + 1}",
            description="\n".join(embed_body),
            colour=Colour.dark_gold()
        )
        embed.set_author(
            name=f"Comments at #{self.github_id} in {self.repo_name}",
            url=f"https://github.com/arcadia-redux/{self.repo_name}/issues/{self.github_id}"
        )
        return embed
