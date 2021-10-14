from discord import Interaction, ButtonStyle
from discord.ui import button, Button

from .generic import TimeoutView, MultiselectView, TimeoutErasingView, MultiselectDropdown
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
            } for shortcut, full_name in preset_repos.items()
        ]
        self.add_item(MultiselectDropdown("Select repo...", repos_selection, 1, 1))


class IssueControls(TimeoutView):
    def __init__(self, session, repo: str, github_id: int, issue_data: Optional[dict] = None):
        self.session = session
        self.repo = repo
        self.github_id = github_id
        self.details = issue_data if issue_data else {}
        super().__init__()

    async def _update_details(self):
        """ since any button changes issue data, we should update it after every successful interaction"""
        status, data = await get_issue_by_number(self.session, self.repo, self.github_id)
        if status:
            self.details = data

    @button(label="Edit Labels", style=ButtonStyle.green)
    async def edit_labels_action(self, _button: Button, interaction: Interaction):
        """ Edit labels of an issue, allowing to select from 0 (removing all labels) up to 10. """
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
            complete_selection = set(view.values)
            # assignees that were removed from final selection
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

# TODO: finish and alter for PRs (or disable for PRs)
"""
    @button(label="Close issue", style=ButtonStyle.red)
    async def set_issue_state(self, _button: Button, interaction: Interaction):
        status, data = await set_issue_state(
            self.session, self.repo, self.github_id, "closed" if _button.label == "Close issue" else "open"
        )
        _button.style = ButtonStyle.success if data["state"] == "closed" else ButtonStyle.red
        _button.label = "Reopen issue" if data["state"] == "closed" else "Close issue"
        await interaction.response.edit_message(content=interaction.message.content, view=self)
"""