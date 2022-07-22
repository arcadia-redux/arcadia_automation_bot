from os import getenv
from hashlib import sha256

import aioredis
from aiohttp import web, ClientSession
from loguru import logger

from loc_issue_manager import publish_localization_changes, base_api_headers

routes = web.RouteTableDef()


@routes.post("/push")
async def github_event_handler(request: web.Request):
    data = await request.json()
    redis = request.app["redis"]
    session = request.app["session"]

    if data["ref"] != "refs/heads/master" and data["ref"] != "refs/heads/main":
        return web.Response(status=200)

    sent_data = {
        "repo": {
            "name": data["repository"]["full_name"].replace("arcadia-redux/", "").replace("SanctusAnimus/", ""),
            "base_url": data["repository"]["html_url"],
            "url": data["repository"]["html_url"].replace("github.com", "api.github.com/repos")
        },
        "compare": data["compare"],
        "pusher": data["pusher"]["name"],
        "file": {},
        "before": data["before"],
        "after": data["after"],
    }

    diff_res = await session.get(
        f"{sent_data['repo']['url']}/compare/{data['before']}...{data['after']}",
        headers=base_api_headers
    )
    if diff_res.status < 400:
        diff_data = await diff_res.json()
        addon_english_file = next(
            (file for file in diff_data["files"] if "addon_english.txt" in file["filename"]),
            None
        )
        if addon_english_file:
            # pointer to addon_english changes inside diff, for ease of use
            sent_data["anchor"] = sha256(addon_english_file["filename"].encode("utf-8")).hexdigest()
            sent_data["file"] = addon_english_file
            await publish_localization_changes(session, redis, sent_data)
        else:
            logger.warning(f"No changes in addon english file")
    else:
        logger.warning(f"Error fetching diff: {await diff_res.json()}")

    return web.Response(status=200)


async def init():
    url = getenv("REDIS_URL")
    pwd = getenv("PWD")

    app = web.Application()
    app["redis"] = await aioredis.create_redis_pool(url, password=pwd, maxsize=2)
    app["session"] = ClientSession()
    app.add_routes(routes)
    return app


web.run_app(init(), host="0.0.0.0", port=80)
