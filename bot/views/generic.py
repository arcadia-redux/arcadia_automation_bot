from inspect import iscoroutinefunction
from typing import List, Optional, Callable, Union, Awaitable

from discord import Message, SelectOption, Interaction, ButtonStyle
from discord.errors import NotFound
from discord.ui import View, Select, Button
from loguru import logger

_Callback = Callable[["MultiselectView"], Union[None, Awaitable[None]]]


class ActionButton(Button):
    def __init__(self, label: str, style: ButtonStyle):
        super().__init__(label=label, style=style)
        self.__callback = None

    async def callback(self, interaction: Interaction):
        if self.__callback:
            await (self.__callback(self, interaction))

    def set_callback(self, callback: _Callback):
        self.__callback = callback


class TimeoutView(View):
    """ view, that removes itself from message on timeout, leaving source message intact """
    assigned_message = None

    complete_callback = None
    complete_description = "Interaction complete. You may close it now."
    remove_view = False

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
    def __init__(self, placeholder: str, options_base: List[dict], min_values: int = 0, max_values: int = 10,
                 is_sorted: bool = False):
        options = []
        for option_def in (sorted(options_base, key=lambda item: item["name"]) if not is_sorted else options_base):
            options.append(SelectOption(
                label=option_def["name"], description=option_def.get("description", None),
                default=option_def.get("selected", False)
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

        if self.view.complete_callback:
            if iscoroutinefunction(self.view.complete_callback):
                await self.view.complete_callback(self.view)
            else:
                self.view.complete_callback(self.view)

        if not self.view.remove_view:
            await interaction.response.edit_message(content=self.view.complete_description, view=self.view)
        else:
            await interaction.response.edit_message(content=self.view.complete_description, view=None)


class MultiselectView(TimeoutErasingView):
    def __init__(self, placeholder: str, items: List[dict], min_values: int = 0, max_values: int = 10,
                 is_sorted: bool = False):
        super().__init__()
        self.values = {}
        self.add_item(MultiselectDropdown(placeholder, items, min_values, max_values, is_sorted))

    def set_complete_behaviour(self, complete_description: str, remove_view: Optional[bool] = False):
        self.complete_description = complete_description
        self.remove_view = remove_view

    def set_on_complete(self, callback: _Callback):
        self.complete_callback = callback
