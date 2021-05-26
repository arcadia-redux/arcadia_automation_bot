# Arcadia Redux Automation  

Docker-compose image that contains:
 - Discord bot to relay feedback, sent through Redis pub/sub, manage issues on Github
 - Aiohttp webserver for listening to Github webhooks calls, to notify translators about english localization changes

Feedback is automatically translated using Google Cloud translation API


### Configuring and deploying
As described before, this repo is a docker-compose image, and is meant to be deployed using `docker-compose`.
Before deploying, one must create `common.env` file in the root folder, that contain following keys:
```dotenv
REDIS_URl = # remote Redis url (as redis://11.11.11.11)
PWD = # remote Redis password
WEBAPI_KEY = # Steam WebAPI key
GITHUB_LOGIN = # Github bot user login
GITHUB_KEY = # Github user password (advise - use access key instead)
BOT_TOKEN = # Discord bot token 

GOOGLE_PROJECT_API = # google cloud project name (with translation api enabled, like model-quad-111)
GOOGLE_PROJECT_CREDS_FILENAME = # credentials for that project (something like model-quad-111-222.json)
```

### Running on localhost
You can run Discord bot locally, for that create `.env` file in `bot` folder. It should contain same set of keys, but values may be different of course (to utilize different bot token for testing purposes, or use local Redis instance)