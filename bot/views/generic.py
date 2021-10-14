from typing import List

from discord import Message, SelectOption, Interaction
from discord.errors import NotFound
from discord.ui import View, Select
from loguru import logger


class TimeoutView(View):
    """ view, that removes itself from message on timeout, leaving source message intact """
    assigned_message = None

    def __init__(self):
        super().__init__(timeout=600)

    async def on_timeout(self) -> None:
        if self.assigned_message:
            try:
                await self.assigned_message.edit(
                    content=self.assigned_message.content,
                    embed=self.assigned_message.embeds[0] if self.assigned_message.embeds else None,
                    view=None
                )
            except NotFound:
                logger.warning(f"Tried editing non-existent message in TimeoutView on_timeout")

    def assign_message(self, message: Message):
        self.assigned_message = message


class TimeoutErasingView(TimeoutView):
    """ view, that removes itself together with source message on timeout """
    def __init__(self):
        super().__init__()

    async def on_timeout(self) -> None:
        if self.assigned_message:
            try:
                await self.assigned_message.delete()
            except NotFound:
                logger.warning(f"Tried editing non-existent message in TimeoutErasingView on_timeout")


class MultiselectDropdown(Select):
    def __init__(self, placeholder: str, options_base: List[dict], min_values: int = 0, max_values: int = 10):
        options = []
        for option_definition in sorted(options_base, key=lambda item: item["name"]):
            options.append(SelectOption(
                label=option_definition["name"], description=option_definition.get("description", None),
                default=option_definition.get("selected", False)
            ))
        super().__init__(
            placeholder=placeholder,
            min_values=min_values,
            max_values=min(max_values, len(options_base)),
            options=options
        )

    async def callback(self, interaction: Interaction):
        self.view.values = self.values
        self.disabled = True
        self.view.stop()
        await interaction.response.edit_message(content="Interaction complete. You may close it now.", view=self.view)


class MultiselectView(TimeoutErasingView):
    def __init__(self, placeholder: str, items: List[dict], min_values: int = 0, max_values: int = 10):
        super().__init__()
        self.values = {}
        self.add_item(MultiselectDropdown(placeholder, items, min_values, max_values))
