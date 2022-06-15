from typing import Optional, List, Dict, Any

from aiohttp import ClientSession
from discord import Message, Member
from discord.commands import ApplicationContext
from discord.ext.commands import Context

from .constants import Numeric, ApiResponse, GITHUB_API_URL, GITHUB_API_HEADERS
from .enums import ApiRequestKind


def body_wrap(body: str, context: Context) -> str:
    return f"{body if body else ''}\n\nOpened from Discord by " \
           f"**{context.author.name}#{context.author.discriminator}**\n" \
           f"Follow the conversation [here]({context.message.jump_url})"


def body_wrap_contextless(body: str, message: Message) -> str:
    return f"{body if body else ''}\n\nOpened from Discord by " \
           f"**{message.author.name}#{message.author.discriminator}**\n" \
           f"Follow the conversation [here]({message.jump_url})"


def body_wrap_plain(body: str, author: Member):
    return f"{body if body else ''}\n\nOpened from Discord by " \
           f"**{author.name}#{author.discriminator}**"


def comment_wrap(body: str, context: Context) -> str:
    return f"{body if body else ''}\n\nComment from Discord by " \
           f"**{context.author.name}#{context.author.discriminator}**\n" \
           f"Follow the conversation [here]({context.message.jump_url})"


def comment_wrap_contextless(body: str, message: Message, comment_prefix: str = "Comment") -> str:
    return f"{body if body else ''}\n\n{comment_prefix} from Discord by " \
           f"**{message.author.name}#{message.author.discriminator}**\n" \
           f"Follow the conversation [here]({message.jump_url})"


def comment_wrap_interaction(body: str, context: ApplicationContext, ref_message: Message,
                             comment_prefix: str = "Comment") -> str:
    return f"{body if body else ''}\n\n{comment_prefix} from Discord by " \
           f"**{context.author.name}#{context.author.discriminator}**\n" \
           f"Follow the conversation [here]({ref_message.jump_url})"


async def github_api_request(session: ClientSession, request_kind: ApiRequestKind, request_path: str,
                             body: Optional[dict] = None) -> ApiResponse:
    completed_request_path = GITHUB_API_URL + request_path
    response = await getattr(session, str(request_kind))(completed_request_path, json=body, headers=GITHUB_API_HEADERS)
    return response.status < 400, await response.json()


async def open_issue(context: Context, repo: str, title: str, body: Optional[str] = "") -> ApiResponse:
    return await github_api_request(
        context.bot.session, ApiRequestKind.POST, f"/repos/arcadia-redux/{repo}/issues", {
            "title": title,
            "body": body_wrap(body, context),
        }
    )


async def open_issue_contextless(session: ClientSession, author: Member, repo: str, title: str,
                                 body: Optional[str] = "") -> ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.POST, f"/repos/arcadia-redux/{repo}/issues", {
            "title": title,
            "body": body_wrap_plain(body, author),
        }
    )


async def set_issue_state(session: ClientSession, repo: str, issue_id: Numeric, state: str = "closed") -> ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.PATCH, f"/repos/arcadia-redux/{repo}/issues/{issue_id}", {
            "state": state
        }
    )


async def update_issue_title_and_body(context: Context, repo: str, title: str, body: str,
                                      issue_id: Numeric) -> ApiResponse:
    return await github_api_request(
        context.bot.session, ApiRequestKind.PATCH, f"/repos/arcadia-redux/{repo}/issues/{issue_id}", {
            "title": title,
            "body": body_wrap(body, context),
        }
    )


async def update_issue(session: ClientSession, repo: str, issue_id: Numeric, fields: Dict[str, Any]) -> ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.PATCH, f"/repos/arcadia-redux/{repo}/issues/{issue_id}", fields
    )


async def add_labels(session: ClientSession, repo: str, issue_id: Numeric, labels: List[str]):
    return await github_api_request(
        session, ApiRequestKind.PATCH, f"/repos/arcadia-redux/{repo}/issues/{issue_id}", {
            "labels": labels
        }
    )


async def assign_issue(session: ClientSession, repo: str, issue_id: Numeric, assignees: List[str]) -> ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.POST, f"/repos/arcadia-redux/{repo}/issues/{issue_id}/assignees", {
            "assignees": assignees,
        }
    )


async def deassign_issue(session: ClientSession, repo: str, issue_id: Numeric, assignees: List[str]) -> ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.DELETE, f"/repos/arcadia-redux/{repo}/issues/{issue_id}/assignees", {
            "assignees": assignees,
        }
    )


async def get_issues(session: ClientSession, repo: str, count: Numeric, state: str, page: Numeric) -> ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.GET,
        f"/repos/arcadia-redux/{repo}/issues?per_page={count}&state={state}&page={page}",
        {}
    )


async def get_issues_list_formatted(session: ClientSession, repo: str, state: str, count: Numeric,
                                    page: Numeric) -> str:
    status, data = await get_issues(session, repo, count, state, page)
    if not status:
        return ""
    description_list = []
    for issue in data:
        issue_state = "🟢" if issue['state'] == "open" else "🔴"
        description_list.append(
            f"{issue_state} [`#{issue['number']}`]({issue['html_url']}) {issue['title']}"
        )
    return "\n".join(description_list)


async def get_issue_by_number(session: ClientSession, repo: str, issue_id: Numeric) -> ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.GET, f"/repos/arcadia-redux/{repo}/issues/{issue_id}"
    )


async def get_pull_request_by_number(session: ClientSession, repo: str, pull_id: Numeric) -> ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.GET, f"/repos/arcadia-redux/{repo}/pulls/{pull_id}"
    )


async def get_commit_by_sha(session: ClientSession, repo: str, sha: str) -> ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.GET, f"/repos/arcadia-redux/{repo}/commits/{sha}"
    )


async def get_commits_diff(session: ClientSession, repo: str, base: str, head: str) -> ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.GET, f"/repos/arcadia-redux/{repo}/compare/{base}...{head}"
    )


async def get_repo_labels(session: ClientSession, repo: str) -> ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.GET, f"/repos/arcadia-redux/{repo}/labels"
    )


async def get_arcadia_team_members(session: ClientSession) -> ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.GET, f"/organizations/46830822/team/4574724/members"
    )


async def get_repo_single_label(session: ClientSession, repo: str, label_name: str) -> ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.GET, f"/repos/arcadia-redux/{repo}/labels/{label_name}"
    )


async def create_repo_label(session: ClientSession, repo: str, label_name: str, color: Optional[str] = None,
                            description: Optional[str] = None) -> ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.POST, f"/repos/arcadia-redux/{repo}/labels", {
            "name": label_name,
            "color": color,
            "description": description,
        }
    )


async def set_issue_milestone(session: ClientSession, repo: str, issue_id: Numeric, milestone: str) -> ApiResponse:
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
    return await set_issue_milestone_raw(session, repo, issue_id, milestone_number)


async def set_issue_milestone_raw(
        session: ClientSession, repo: str, issue_id: Numeric, milestone_number: int
) -> ApiResponse:
    issue_body = {
        "milestone": milestone_number
    }
    resp = await session.patch(
        f"{GITHUB_API_URL}/repos/arcadia-redux/{repo}/issues/{issue_id}", json=issue_body, headers=GITHUB_API_HEADERS,
    )
    return resp.status < 400, await resp.json()


async def get_repo_milestones(session: ClientSession, repo: str) -> ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.GET, f"/repos/arcadia-redux/{repo}/milestones"
    )


async def comment_issue(session: ClientSession, repo: str, issue_id: Numeric, body: str) -> ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.POST, f"/repos/arcadia-redux/{repo}/issues/{issue_id}/comments", {
            "body": body
        }
    )


async def get_issue_comment(session: ClientSession, repo: str, comment_id: Numeric) -> ApiResponse:
    return await github_api_request(
        session, ApiRequestKind.GET, f"/repos/arcadia-redux/{repo}/issues/comments/{comment_id}"
    )


async def get_issue_comments(
        session: ClientSession, repo: str, issue_number: Numeric, since: Optional[str] = None
) -> ApiResponse:
    if since:
        url = f"/repos/arcadia-redux/{repo}/issues/{issue_number}/comments?since={since}"
    else:
        url = f"/repos/arcadia-redux/{repo}/issues/{issue_number}/comments"
    return await github_api_request(
        session, ApiRequestKind.GET, url
    )


async def search_issues(session: ClientSession, repo: str, query: str,
                        page_num: Optional[Numeric] = 1, per_page: Optional[Numeric] = 10) -> ApiResponse:
    request_body = {
        "q": f"repo:arcadia-redux/{repo} {query}",
        "per_page": per_page,
        "page": page_num
    }

    resp = await session.get(
        f"{GITHUB_API_URL}/search/issues", headers=GITHUB_API_HEADERS, params=request_body
    )
    return resp.status < 400, await resp.json()
