import asyncio
import json
from os import getenv

import aioredis
from dotenv import load_dotenv

load_dotenv()


async def save():
    redis = await aioredis.create_redis(
        getenv("REDIS_URL"), password=getenv("PWD"), encoding="utf8"
    )
    all_keys = await redis.keys("*")
    all_values = await redis.mget(*all_keys)

    final_dict = {}

    for key, value in zip(all_keys, all_values):
        if value is not None:
            final_dict[key] = value
        else:
            try:
                final_dict[key] = await redis.lrange(key, 0, 100, encoding="utf8")
            except aioredis.errors.ReplyError:
                print("couldn't save", key)
    with open("save.json", 'w') as file:
        json.dump(final_dict, file)


async def restore():
    redis = await aioredis.create_redis(
        getenv("REDIS_URl"), password=getenv("PWD"), encoding="utf8"
    )
    executor = redis.multi_exec()
    with open("save.json", "r") as src:
        backup_content = json.load(src)
        for key, values in backup_content.items():
            print("restoring", key, values)
            executor.rpush(key, values)


def main():
    asyncio.run(restore())


main()
