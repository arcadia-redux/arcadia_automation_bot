from aiohttp import ClientSession
from discord import Embed
from datetime import datetime
from discord.colour import Colour
import re

from ..github_integration import get_issue_by_number, get_pull_request_by_number

url_regex = re.compile(
    "(https?:\/\/(.+?\.)?github\.com\/arcadia-redux(\/[A-Za-z0-9\-\._~:\/\?#\[\]@!$&'\(\)\*\+,;\=]*)?)"
)


def get_image_link(body: str) -> (str, str):
    result = re.search(
        r"(!\[(.*?)\]\((.*?)\))",
        body
    )
    if result:
        link_structure = result.group(0)
        extracted_link = link_structure.replace("![image](", "")[:-1]
        cleaned_body = body.replace(link_structure + "\n", "").replace(link_structure + "\r\n", "")
        return extracted_link, cleaned_body
    return "", body


async def parse_markdown(session: ClientSession, text: str, repo_name: str) -> str:
    issue_number_refs = re.findall(
        r"( #[0-9]*)",  # searching for #111 issue numbers, for task lists
        text
    )
    github_obj_links = re.findall(url_regex, text)
    for issue_number in issue_number_refs:
        status, issue_data = await get_issue_by_number(session, repo_name, issue_number.replace(" #", ""))
        if status:
            issue_state = "🟢" if issue_data['state'] == "open" else "🔴"
            text = text.replace(
                issue_number, f" {issue_state} [{issue_data['title']}{issue_number}]({issue_data['html_url']})"
            )
    for github_obj in github_obj_links:
        github_obj_link = github_obj[0]
        link_split = github_obj_link.split("/")
        m_repo_name, obj_type, obj_id = link_split[-3:]
        if obj_type == "issues":
            status, obj_data = await get_issue_by_number(session, m_repo_name, obj_id)
        else:
            status, obj_data = await get_pull_request_by_number(session, m_repo_name, obj_id)
        if status:
            issue_state = "🟢" if obj_data['state'] == "open" else "🔴"
            text = text.replace(
                github_obj_link, f"{issue_state} [{obj_data['title']} #{obj_data['number']}]({github_obj_link})"
            )

    return text.replace("- [x]", "✅").replace("* [x]", "✅").replace("- [ ]", "☐")


async def get_issue_embed(session: ClientSession, data: dict, object_id: str, repo_name: str, link: str) -> Embed:
    labels = ", ".join([f"`{label['name']}`" for label in data['labels']])
    assignees = ", ".join([f"`{assignee['login']}`" for assignee in data['assignees']])
    milestone = data["milestone"].get("title", None)
    image_link, data["body"] = get_image_link(data["body"])
    data["body"] = await parse_markdown(session, data["body"] or "", repo_name)
    description = [
        f"**Labels**: {labels}" if labels else "",
        f"**Assignees**: {assignees}" if assignees else "",
        f"**Milestone**: `{milestone}`" if milestone else "",
        f'\n{data["body"]}' if len(data["body"]) < 1200 else "",
    ]
    embed = Embed(
        title=data['title'],
        description="\n".join(description),
        colour=Colour.green() if data['state'] == "open" else Colour.red(),
    )
    embed.set_author(
        name=f"Linked issue #{object_id} in {repo_name} by {data['user']['login']}",
        url=link,
        icon_url=data["user"]["avatar_url"]
    )
    opened_at_date = datetime.strptime(data['created_at'], "%Y-%m-%dT%H:%M:%SZ")
    embed.set_footer(text=f"{data['comments']} comment{'s' if data['comments'] != 1 else ''} "
                          f"| Opened at {opened_at_date.strftime('%c')}")
    if image_link:
        embed.set_image(url=image_link)
    return embed


async def get_pull_request_embed(session: ClientSession, data: dict, object_id: str, repo_name: str, link: str) -> Embed:
    labels = ", ".join([f"`{label['name']}`" for label in data['labels']])
    assignees = ", ".join([f"`{assignee['login']}`" for assignee in data['assignees']])
    reviewers = ", ".join([f"`{reviewer['login']}`" for reviewer in data["requested_reviewers"]])
    milestone = data["milestone"]["title"] if data["milestone"] else None
    merge_state = ""
    color = Colour.green()
    if data['draft']:
        merge_state = "draft"
        color = Colour.dark_grey()
    elif data['merged']:
        merge_state = "merged"
        color = Colour.dark_purple()
    elif data["mergeable"]:
        merge_state = data['mergeable_state']
        if merge_state in ["blocked", "behind"]:
            color = Colour.red()
    elif data['mergeable_state'] == "dirty":
        merge_state = "has conflicts"
        color = Colour.dark_orange()
    data["body"] = await parse_markdown(session, data["body"] or "", repo_name)
    description = [
        f"**Labels**: {labels}" if labels else "",
        f"**Assignees**: {assignees}" if assignees else "",
        f"**Reviewers**: {reviewers}" if reviewers else "",
        f"**Milestone**: `{milestone}`" if milestone else "",
        f"**Changes**: {data['commits']} commit{'s' if data['commits'] != 1 else ''}, "
        f"`+{data['additions']}` : `-{data['deletions']}` in {data['changed_files']} files",
        f"**Merge state**: `{merge_state}`",
        f'\n{data["body"]}' if len(data["body"]) < 1200 else "",
    ]
    embed = Embed(
        title=data['title'],
        description="\n".join(description),
        colour=color,
    )
    embed.set_author(
        name=f"Linked PR #{object_id} in {repo_name} by {data['user']['login']}",
        url=link,
        icon_url=data['user']['avatar_url']
    )
    opened_at_date = datetime.strptime(data['created_at'], "%Y-%m-%dT%H:%M:%SZ")
    embed.set_footer(text=f"{data['comments']} comment{'s' if data['comments'] != 1 else ''} "
                          f"| Opened at {opened_at_date.strftime('%c')}")
    return embed
