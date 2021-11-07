import re
from datetime import datetime
from typing import List
from urllib.parse import quote

from aiohttp import ClientSession
from discord import Embed
from discord.colour import Colour

from ..github_integration import get_issue_by_number, get_pull_request_by_number

url_regex = re.compile(
    "(https?:\/\/(.+?\.)?github\.com\/arcadia-redux\/.*\/(issues|pull)\/\d*)"
)


def get_image_link(body: str) -> (str, str):
    result = re.search(
        r"(!\[(.*?)\]\((.*?)\))",
        body
    )
    if result:
        link_structure = result.group(0)
        primary_link_start = link_structure.find("(")
        extracted_link = link_structure[primary_link_start + 1: -1]
        cleaned_body = body \
            .replace(link_structure, "[On Thumbnail]") \
            .replace(link_structure, "[On Thumbnail]")
        return extracted_link, cleaned_body
    return "", body


def get_users_parsed(assignees: List[dict]) -> str:
    parsed_assignees = [
        f"[`{assignee['login']}`](https://github.com/{assignee['login']})"
        for assignee in assignees
    ]
    return ", ".join(parsed_assignees)


def get_labels_parsed(repo_name: str, labels: List[dict]) -> str:
    parsed_labels = [
        f"[`{label['name']}`](https://github.com/arcadia-redux/{repo_name}/labels/{quote(label['name'])})"
        for label in labels
    ]
    return ", ".join(parsed_labels)


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
                issue_number, f" {issue_state} [{issue_number} {issue_data['title']}]({issue_data['html_url']})"
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
                github_obj_link, f"{issue_state} [#{obj_data['number']} {obj_data['title']}]({github_obj_link})"
            )

    return text.replace("- [x]", "✅").replace("* [x]", "✅").replace("- [ ]", "☐")


async def get_issue_embed(session: ClientSession, data: dict, object_id: str, repo_name: str,
                          link: str = None) -> Embed:
    if not link:
        link = data["html_url"]
    labels = get_labels_parsed(repo_name, data['labels'])
    assignees = get_users_parsed(data["assignees"])
    milestone = data.get("milestone", {})
    if milestone:
        milestone = milestone.get("title", None)
    image_link, data["body"] = get_image_link(data["body"] or "")
    data["body"] = (await parse_markdown(session, data["body"] or "", repo_name)).strip()
    description = [
        f"**Labels**: {labels}\n" if labels else "",
        f"**Assignees**: {assignees}\n" if assignees else "",
        f"**Milestone**: `{milestone}`\n" if milestone else "",
        f'\n{data["body"]}' if len(data["body"]) < 1800 else "",
    ]
    complete_description = "".join(description)

    embed = Embed(
        title=data['title'],
        description=complete_description,
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


async def get_pull_request_embed(session: ClientSession, data: dict, object_id: str, repo_name: str,
                                 link: str) -> Embed:
    labels = get_labels_parsed(repo_name, data['labels'])
    assignees = get_users_parsed(data["assignees"])
    reviewers = get_users_parsed(data["requested_reviewers"])
    # ", ".join([f"`{reviewer['login']}`" for reviewer in data["requested_reviewers"]])
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


async def get_issue_comment_embed(session: ClientSession, data: dict, object_id: str, repo_name: str,
                                  link: str) -> Embed:
    image_link, new_body = get_image_link(data["body"] or "")
    new_body = await parse_markdown(session, new_body, repo_name)
    embed = Embed(
        title=f"{data['user']['login']}:",
        description=new_body,
        colour=Colour.dark_gold()
    )
    embed.set_author(
        name=f"Comment at issue #{object_id} in {repo_name}",
        url=link,
        icon_url=data['user']['avatar_url']
    )
    opened_at_date = datetime.strptime(data['created_at'], "%Y-%m-%dT%H:%M:%SZ")
    embed.set_footer(text=f"Commented at {opened_at_date.strftime('%c')}")
    if image_link:
        embed.set_image(url=image_link)
    return embed


def get_code_block_embed(extension: str, code: str, repo_name: str, line_pointers: List[int],
                         file_path_details: List[str], full_link: str) -> Embed:
    commit_sha = file_path_details[0]
    if len(line_pointers) == 1:
        title = f"Line **{line_pointers[0]}** at [`{commit_sha[:6]}`]" \
                f"(https://github.com/arcadia-redux/{repo_name}/commit/{commit_sha})"
    else:
        title = f"Lines **{line_pointers[0]}** to **{line_pointers[1]}** at [`{commit_sha[:6]}`]" \
                f"(https://github.com/arcadia-redux/{repo_name}/commit/{commit_sha})"
    embed = Embed(
        description=f"{title}\n```{extension}\n{code}```",
        colour=Colour.dark_teal()
    )
    embed.set_author(
        name=f"Code snippet at /{'/'.join(file_path_details[1:])}",
        url=full_link
    )
    return embed
