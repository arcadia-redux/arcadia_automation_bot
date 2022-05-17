from base64 import b64encode
from os import getenv

from aiohttp import ClientSession
from loguru import logger

login = getenv("GITHUB_LOGIN")
password = getenv("GITHUB_KEY")
auth_string = b64encode(f"{login}:{password}".encode("ascii")).decode("ascii")

base_api_headers = {
    "Authorization": f"Basic {auth_string}",
    "Accept": "application/vnd.github.v3+json",
}

assignees = [
    "AnnHuangofNJUST", "PonyashaWright"
]


async def publish_localization_changes(session: ClientSession, redis, data: dict) -> None:
    issue_number = await redis.get(f"{data['repo']['name']}_loc_issue")
    if issue_number:
        issue_number = int(issue_number)

    if not issue_number or issue_number == -1:
        issue_number = await create_localization_issue(session, data["repo"]["url"])
        await redis.set(f"{data['repo']['name']}_loc_issue", issue_number)

    if issue_number == -1:
        return

    base_url = data["repo"]["base_url"]
    before = data["before"]
    after = data["after"]
    mentions = " ".join(f"@{name}" for name in assignees)
    comment_description = f"{mentions} localization changes in diff from " \
                          f"[`{before[:6]}`]({base_url}/commits/{before}) " \
                          f"to [`{after[:6]}`]({base_url}/commits/{after}) " \
                          f"[`+{data['file']['additions']}` / `-{data['file']['deletions']}`]\n" \
                          f"Compare changes using [github diff]({data['compare']}#diff-{data['anchor']})"

    create_comment_link = f"{data['repo']['url']}/issues/{issue_number}/comments"
    body = {
        "body": comment_description,
    }

    result = await session.post(create_comment_link, json=body, headers=base_api_headers)
    details = await result.json()
    if result.status >= 400:
        logger.warning(f"Failed to add comment: {details}")


async def create_localization_issue(session: ClientSession, repo_link: str) -> int:
    issue_body = {
        "title": f"[AUTO] Localization updates",
        "body": f"Issue for automatic english localization updates tracking.",
    }
    result = await session.post(f"{repo_link}/issues", json=issue_body, headers=base_api_headers)
    details = await result.json()

    if result.status >= 400:
        logger.warning(f"Failed to create issue: {details}")
        return -1

    issue_id = details["number"]

    # Lock conversation for issue
    lock_body = {
        "lock_reason": "too heated"
    }
    lock_result = await session.put(f"{repo_link}/issues/{issue_id}/lock", json=lock_body, headers=base_api_headers)
    if lock_result.status >= 400:
        logger.warning(f"Lock failed: {await lock_result.json()}")

    # Assign translators
    assign_body = {
        "assignees": assignees
    }
    assign_result = await session.post(
        f"{repo_link}/issues/{issue_id}/assignees",
        json=assign_body,
        headers=base_api_headers
    )
    if assign_result.status >= 400:
        logger.warning(f"Assign failed: {await assign_result.json()}")

    return issue_id
