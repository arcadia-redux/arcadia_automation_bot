from base64 import b64encode
from os import getenv
from typing import Tuple, Union, Final, Dict, Any

from dotenv import load_dotenv

LOCALS_IMPORTED = False

if not getenv("BOT_TOKEN", False):
    load_dotenv()
    LOCALS_IMPORTED = True

TARGET_GUILD_IDS = [int(getenv("INTERACTION_GUILD_TARGET")), ]
DEDICATED_SERVER_KEY = getenv("DEDICATED_SERVER_KEY", "discord_bot_no_key_defined")

GITHUB_AUTH_STRING = b64encode(f"{getenv('GITHUB_LOGIN')}:{getenv('GITHUB_KEY')}".encode("ascii")).decode("ascii")

GITHUB_API_URL = "https://api.github.com"
GITHUB_API_HEADERS = {
    "Authorization": f"Basic {GITHUB_AUTH_STRING}",
    "Accept": "application/vnd.github.v3+json",
}

PRIVATE_REPOSITORIES = [
    "custom_hero_clash", "chclash_webserver",
    "arcadia_automation_bot", "overthrow_3",
    "ar_custom_game_template", "ar_webserver_template"
]

PRESET_REPOSITORIES = {
    "chc": "custom_hero_clash_issues",
    "12v12": "12v12",
    "old_ot": "overthrow2",
    "ot3": "overthrow_3",
    "bot": "arcadia_automation_bot",
    "template": "ar_custom_game_template",
    "template_server": "ar_webserver_template",
}

SERVER_LINKS = {
    "CustomHeroClash": "https://api.chc.dota2unofficial.com/",
    "Dota12v12": "https://api.12v12.dota2unofficial.com/",
    "Overthrow": "https://api.overthrow.dota2unofficial.com/",
    "Overthrow3": "https://api.ot3.dota2unofficial.com/",
}

CUSTOM_GAMES: Final[Dict[str, Any]] = {key: None for key in SERVER_LINKS.keys()}

Numeric = Union[str, int]
ApiResponse = Tuple[bool, Union[dict, list]]
