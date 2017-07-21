import asyncio
import aiohttp

from msgforwarder import logger
from msgforwarder.transports import transport

loop = asyncio.get_event_loop()


class TelegramClient(transport.BaseTransport):
    NAME = "telegram"
    MSG_TEMPLATE = "_[From %(from_client)s]_ *%(author)s* : %(msg)s"
    CLIENT_SCHEMA = {
        "type": "object",
        "properties": {
            "transport": {"enum": ["telegram"]},
            "token": {
                "type": "string",
                "description": "The token to use for connection."
            },
            "channels": {"type": "object",
                         "description": "Mapping Channel ID with name. Keys "
                                        "are names, values are IDs.",
                         "patternProperties": {
                             "^.*$": {"type": "string"}
                         }
            }
        },
        "additionalProperties": False,
        "required": ["token"]
    }

    BASE_URL = "https://api.telegram.org/bot%(token)s"

    def __init__(self, client_id, client_cfg):
        super(TelegramClient, self).__init__(client_id, client_cfg)
        self._user = None
        self._channels = self._client_cfg.get("channels", {})

    def _make_url(self, action, params=None):
        url = self.BASE_URL % {"token": self._client_cfg["token"]}
        url = "%s/%s" % (url, action)
        if params:
            url += "?%s" % "&".join("%s=%s" % (k, v)
                                    for k, v in params.items())
        return url

    def connect(self):
        logger.info("[%s] Connecting..." % self._client_id)
        asyncio.get_event_loop().create_task(self._connect())

    async def _make_request(self, url, session, method="GET", data=None):
        """Make simple API request to the Gitter host.

        :param url: a part of url which will be added to Gitter API url
        :param session: a Session object
        :param method: a method of request (GET by default)
        :param data: a dict to attach to request as data
        """
        url = "%s/%s" % (self.BASE_URL, url)
        with aiohttp.Timeout(10, loop=session.loop):
            async with session.request(method, url, data=data) as response:
                return await response.json()

    async def _listen_for_update(self):
        offset = None
        while True:
            async with aiohttp.ClientSession(loop=loop) as session:
                params = None
                if offset:
                    params = {"offset": offset}
                url = self._make_url("getUpdates", params=params)
                async with session.get(url) as response:
                    result = await response.json()
                    if not result["ok"]:
                        logger.error("[%s] Failed to connect: %s" %
                                     (self._client_id, result["description"]))
                        continue
                    updates = result["result"]
                    for update in updates:
                        key = {"message", "channel_post", "edited_message",
                               "edited_channel_post"} & set(update.keys())
                        if not key:
                            continue
                        message = update[key.pop()]
                        if "text" not in message:
                            # we do not support sharing photos yet.
                            continue
                        channel_name = message["chat"]["title"]
                        channel_id = message["chat"]["id"]
                        if channel_name not in self._channels:
                            self._channels[channel_name] = channel_id
                        logger.info("THE NEW CHANNEL DETECTED: "
                                    "ID=%s; Name=%s" % (channel_id,
                                                        channel_name))
                        author = message.get("from", {})
                        if "username" in author:
                            author = author["username"]
                        elif "first_name" in author:
                            author = author["first_name"]
                        else:
                            continue
                        text = message["text"]
                        # update offset
                        offset = update["update_id"] + 1
                        self._forward_message(user=author, target=channel_name,
                                              text=text)

    async def _connect(self):
        # ensure that token is valid
        async with aiohttp.ClientSession(loop=loop) as session:
            with aiohttp.Timeout(10, loop=session.loop):
                async with session.get(self._make_url("getMe")) as response:
                    result = await response.json()
                    if not result["ok"]:
                        logger.error("[%s] Failed to connect: %s" %
                                     (self._client_id, result["description"]))
                        return
                    self._user = result["result"]
        asyncio.get_event_loop().create_task(self._listen_for_update())

    async def _say(self, channel, msg):
        if channel not in self._channels:
            logger.error("[%s] Failed to send message to the unknown %s "
                         "channel: %s" % (self._client_id, channel, msg))
        async with aiohttp.ClientSession(loop=loop) as session:
            with aiohttp.Timeout(10, loop=session.loop):
                url = self._make_url("sendMessage")
                data = {
                    "parse_mode": "Markdown",
                    "text": msg,
                    "chat_id": self._channels[channel]
                }
                async with session.get(url, data=data) as response:
                    result = await response.json()
                    if not result["ok"]:
                        logger.error("[%s] Failed to send message: %s" %
                                     (self._client_id, result["description"]))
                        return
