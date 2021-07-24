from base64 import b64encode
from os import getenv
from typing import Optional, List, Tuple, Union
from aiohttp import ClientSession

from discord.ext.commands import Context
from loguru import logger
from .enums import ApiRequestKind

login = getenv("GITHUB_LOGIN")
password = getenv("GITHUB_KEY")
auth_string = b64encode(f"{login}:{password}".encode("ascii")).decode("ascii")

base_api_link = "https://api.github.com"
base_api_headers = {
    "Authorization": f"Basic {auth_string}",
    "Accept": "application/vnd.github.v3+json",
}
repositories = []

preset_repos = {
    "chc": "custom_hero_clash_issues",
    "12v12": "12v12",
    "ot": "overthrow2",
    "revolt": "reVolt",
    "war": "war_masters",
    "bot": "arcadia_automation_bot",
    "conquest": "conquest",
}

preset_repos_reverse = {value: key for key, value in preset_repos.items()}

excluded_global_repos = {
    "who_will_win_server", "custom_game_encrypter", "server", "Aghanims_Editor", "resources", "who_will_win",
    "aghslab2", "contest.dota2unofficial.com"
}

_Numeric = Union[str, int]
_ApiResponse = Tuple[bool, Union[dict, list]]


async def github_init(bot) -> str:
    return await get_repos(bot)


def body_wrap(body: str, context: Context) -> str:
    return f"{body if body else ''}\n\nOpened from Discord by " \
           f"**{context.author.name}#{context.author.discriminator}**\n" \
           f"Follow the conversation [here]({context.message.jump_url})"


def comment_wrap(body: str, context: Context) -> str:
    return f"{body if body else ''}\n\nComment from Discord by " \
           f"**{context.author.name}#{context.author.discriminator}**\n" \
           f"Follow the conversation [here]({context.message.jump_url})"


def comment_wrap_contextless(body: str, message) -> str:
    return f"{body if body else ''}\n\nComment from Discord by " \
           f"**{message.author.name}#{message.author.discriminator}**\n" \
           f"Follow the conversation [here]({message.jump_url})"


async def github_api_request(session: ClientSession, request_kind: ApiRequestKind, request_path: str,
                             body: Optional[dict] = None) -> _ApiResponse:
    completed_request_path = base_api_link + request_path
    response = await getattr(session, str(request_kind))(completed_request_path, json=body, headers=base_api_headers)
    return response.status < 400, await response.json()


async def open_issue(context: Context, repo: str, title: str, body: Optional[str] = "") -> _ApiResponse:
    return await github_api_request(
        context.bot.session, ApiRequestKind.POST, f"/repos/arcadia-redux/{repo}/issues", {
            "title": title,
            "body": body_wrap(body, context),
        }
    )


async def close_issue(session: ClientSession, repo: str, issue_id: _Numeric) -> _ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.PATCH, f"/repos/arcadia-redux/{repo}/issues/{issue_id}", {
            "state": "closed"
        }
    )


async def update_issue(context: Context, repo: str, title: str, body: str, issue_id: _Numeric) -> _ApiResponse:
    return await github_api_request(
        context.bot.session, ApiRequestKind.PATCH, f"/repos/arcadia-redux/{repo}/issues/{issue_id}", {
            "title": title,
            "body": body_wrap(body, context),
        }
    )


async def add_labels(session: ClientSession, repo: str, issue_id: _Numeric, labels: List[str]):
    return await github_api_request(
        session, ApiRequestKind.PATCH, f"/repos/arcadia-redux/{repo}/issues/{issue_id}", {
            "labels": labels
        }
    )


async def assign_issue(session: ClientSession, repo: str, issue_id: _Numeric, assignees: List[str]) -> _ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.POST, f"/repos/arcadia-redux/{repo}/issues/{issue_id}/assignees", {
            "assignees": assignees,
        }
    )


async def get_repos(bot) -> str:
    global repositories
    resp = await bot.session.get(f"{base_api_link}/orgs/arcadia-redux/repos", headers=base_api_headers)
    if resp.status >= 400:
        logger.warning(f"Error when fetching org repos: {await resp.body()}")
        return ""
    response = await resp.json()
    repositories.clear()
    for repo in response:
        if repo["name"] not in excluded_global_repos:
            preset_name = f' [{preset_repos_reverse[repo["name"]]}]' if repo["name"] in preset_repos_reverse else ""
            repositories.append(f'`{repo["name"]}{preset_name}`')
    repositories.sort()
    return '\n'.join(repositories)


async def get_issues_list(session: ClientSession, repo: str, state: str, count: _Numeric, page: _Numeric) -> str:
    resp = await session.get(
        f"{base_api_link}/repos/arcadia-redux/{repo}/issues?per_page={count}&state={state}&page={page}",
        headers=base_api_headers
    )
    if resp.status >= 400:
        return ""
    response = await resp.json()
    description_list = []
    for issue in response:
        issue_state = "🟢" if issue['state'] == "open" else "🔴"
        description_list.append(
            f"{issue_state} [`#{issue['number']}`]({issue['html_url']}) {issue['title']}"
        )
    return "\n".join(description_list)


async def get_issue_by_number(session: ClientSession, repo: str, issue_id: _Numeric) -> _ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.GET, f"/repos/arcadia-redux/{repo}/issues/{issue_id}"
    )


async def get_pull_request_by_number(session: ClientSession, repo: str, pull_id: _Numeric) -> _ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.GET, f"/repos/arcadia-redux/{repo}/pulls/{pull_id}"
    )


async def get_commit_by_sha(session: ClientSession, repo: str, sha: str) -> _ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.GET, f"/repos/arcadia-redux/{repo}/commits/{sha}"
    )


async def get_commits_diff(session: ClientSession, repo: str, base: str, head: str) -> _ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.GET, f"/repos/arcadia-redux/{repo}/compare/{base}...{head}"
    )


async def get_repo_labels(session: ClientSession, repo: str) -> _ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.GET, f"/repos/arcadia-redux/{repo}/labels"
    )


async def get_arcadia_team_members(session: ClientSession) -> _ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.GET, f"/organizations/46830822/team/4574724/members"
    )


async def get_repo_single_label(session: ClientSession, repo: str, label_name: str) -> _ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.GET, f"/repos/arcadia-redux/{repo}/labels/{label_name}"
    )


async def create_repo_label(session: ClientSession, repo: str, label_name: str, color: Optional[str] = None,
                            description: Optional[str] = None) -> _ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.POST, f"/repos/arcadia-redux/{repo}/labels", {
            "name": label_name,
            "color": color,
            "description": description,
        }
    )


async def set_issue_milestone(session: ClientSession, repo: str, issue_id: _Numeric, milestone: str) -> _ApiResponse:
    status, repo_milestones = await get_repo_milestones(session, repo)
    if not status:
        return status, repo_milestones
    milestone_dict = next(
        (item for item in repo_milestones if item["title"].lower().strip() == milestone.lower().strip()), None
    )
    if not milestone_dict:
        return False, {"error": f"No milestone with name `{milestone}`"}
    milestone_number = milestone_dict.get("number", None)
    if not milestone_number:
        return False, {"error": f"No milestone with name `{milestone}`"}
    issue_body = {
        "milestone": milestone_number
    }
    resp = await session.patch(
        f"{base_api_link}/repos/arcadia-redux/{repo}/issues/{issue_id}", json=issue_body, headers=base_api_headers,
    )
    return resp.status < 400, await resp.json()


async def get_repo_milestones(session: ClientSession, repo: str) -> _ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.GET, f"/repos/arcadia-redux/{repo}/milestones"
    )


async def comment_issue(session: ClientSession, repo: str, issue_id: _Numeric, body: str) -> _ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.POST, f"/repos/arcadia-redux/{repo}/issues/{issue_id}/comments", {
            "body": body
        }
    )


async def search_issues(session: ClientSession, repo: str, query: str,
                        page_num: Optional[_Numeric] = 1, per_page: Optional[_Numeric] = 10) -> _ApiResponse:
    request_body = {
        "q": f"repo:arcadia-redux/{repo} {query}",
        "per_page": per_page,
        "page": page_num
    }

    resp = await session.get(
        f"{base_api_link}/search/issues", headers=base_api_headers, params=request_body
    )
    return resp.status < 400, await resp.json()
