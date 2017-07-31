
import asyncio
import aiohttp

import json

from msgforwarder import logger
from msgforwarder.transports import transport


loop = asyncio.get_event_loop()


class GitterClient(transport.BaseTransport):

    NAME = "Gitter"
    MSG_TEMPLATE = "*[From %(from_client)s]* **%(author)s** : %(msg)s"
    CLIENT_SCHEMA = {
        "type": "object",
        "properties": {
            "transport": {"enum": ["gitter"]},
            "token": {
                "type": "string",
                "description": "The token to use for connection."
            },
            "channels": {"type": "array",
                         "items": {"type": "string",
                                   "minItem": 1},
                         "description": "The list of channels to connect"},
            "msg_template": {
                "type": "string",
                "description": "Format message before forwarding. The "
                               "following keys can be used: client_id, "
                               "author, msg."
            }
        },
        "additionalProperties": False,
        "required": ["token"]
    }

    BASE_URL = "https://api.gitter.im/v1"
    STREAM_URL = "https://stream.gitter.im/v1/rooms/%(room_id)s/chatMessages"

    def __init__(self, client_id, client_cfg):
        super(GitterClient, self).__init__(client_id, client_cfg)
        self._user = None
        self._rooms = {}
        self._headers = {"Authorization":
                             "Bearer %s" % self._client_cfg["token"]}

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

    async def _join_room(self, room_name, session):
        """Discover room ID and join to it.
        
        :param room_name: Room name to joint to
        :param session: a Session object
        """
        rooms_url = "user/%s/rooms" % self._user["id"]
        # fetch room_id
        room_id = await self._make_request(
            "rooms", session, method="POST", data={"uri": room_name})
        # join
        await self._make_request(
            rooms_url, session, method="POST", data={"id": room_id})
        self._rooms[room_name] = room_id

    async def _listen_messages(self, room_name):
        """Start listening a messages of the specific room.
        
        :param room_name: name of the room to listen messages from.
        """
        room_id = self._rooms[room_name]
        while True:
            async with aiohttp.ClientSession(loop=loop,
                                             headers=self._headers) as session:
                async with session.get(self.STREAM_URL % {"room_id": room_id},
                                       timeout=None) as resp:
                    async for raw_data in resp.content:
                        if not raw_data:
                            continue
                        try:
                            message = json.loads(raw_data.decode("utf-8"))
                        except json.JSONDecodeError:
                            continue
                        author = message.get("fromUser", {})
                        author = author.get("username", "")
                        if author == self._user["username"]:
                            # do not forward self-messages
                            continue
                        text = message.get("text")
                        self._forward_message(user=author, target=room_name,
                                              text=text)

                await asyncio.sleep(0.5)

    def connect(self):
        logger.info("[%s] Connecting..." % self._client_id)
        asyncio.get_event_loop().create_task(self._connect())

    async def _connect(self):
        async with aiohttp.ClientSession(headers=self._headers,
                                         loop=loop) as session:
            user = await self._make_request("user", session=session)
            self._user = user[0]
            logger.debug("[%s] Connected as %s" %
                         (self._client_id, self._user["username"]))
            rooms = await self._make_request("rooms", session=session)
            self._rooms = dict((room["name"], room["id"]) for room in rooms
                               if not room["oneToOne"])
            if self._rooms:
                logger.debug("[%s] The list of connected rooms: %s" %
                             (self._client_id, ", ".join(self._rooms)))

            requested_rooms = self._client_cfg.get("channels", [])
            rooms_to_join = set(self._rooms.keys()) - set(requested_rooms)
            if rooms_to_join:
                rooms_to_join = [self._join_room(room, session=session)
                                 for room in rooms_to_join]
                await asyncio.wait(rooms_to_join)

        # start listening messages
        for room in requested_rooms:
            loop.create_task(self._listen_messages(room))

    async def _say(self, channel, msg):
        async with aiohttp.ClientSession(headers=self._headers,
                                         loop=loop) as session:
            url = "rooms/%s/chatMessages" % self._rooms[channel]
            await self._make_request(url, session=session, method="POST",
                                     data={"text": msg})
