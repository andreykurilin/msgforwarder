
import asyncio
from asyncirc import irc
import blinker

from msgforwarder import logger
from msgforwarder.transports import transport


loop = asyncio.get_event_loop()


class IRCClient(transport.BaseTransport):

    NAME = "irc"

    CLIENT_SCHEMA = {
        "type": "object",
        "properties": {
            "transport": {"enum": ["irc"]},
            "server": {
                "type": "string",
                "description": "The server to connect."
            },
            "port": {
                "type": "integer",
                "minimum": 0,
                "maximum": 65535,
                "description": "The server port to connect."
            },
            "use_ssl": {
                "type": "boolean",
                "description": "Use SSL for connection or not. "
                               "Defaults to False"
            },
            "nickname": {
                "type": "string",
                "description": "Nickname of a user."
            },
            "password": {
                "type": "string",
                "description": "Password of user to connect."
            },
            "ident": {
                "type": "string"
            },
            "realname": {
                "type": "string"
            },
            "channels": {"type": "array",
                         "items": {"type": "string",
                                   "minItem": 1},
                         "description": "The list of channels to connect"}
        },
        "additionalProperties": False,
        "required": ["server", "port", "nickname"]
    }

    def __init__(self, client_id, client_cfg):
        super(IRCClient, self).__init__(client_id, client_cfg)
        self._irc = None

    def _connect(self):
        self._irc = irc.connect(self._client_cfg["server"],
                                port=self._client_cfg["port"],
                                use_ssl=self._client_cfg.get("use_ssl", False))
        self._irc.register(self._client_cfg["nickname"],
                           user=self._client_cfg.get("ident", ""),
                           realname=self._client_cfg.get("realname", ""),
                           password=self._client_cfg.get("password", None))

        logger.info("[%s] Joining to channel(s): %s..." %
                    (self._client_id, ", ".join(self._client_cfg["channels"])))
        self._irc.join(self._client_cfg["channels"])

        # we are using external library for IRC, so we should unify the message
        # before forwarding it
        blinker.signal("message").connect(self.on_message)

    async def _say(self, channel, msg):
        self._irc.say(channel, msg)

    def on_message(self, message, user, target, text):
        if user.nick == message.client.nick:
            # do not forward messages from yourself (from the bot)
            return

        self._forward_message(user=user.nick, target=target, text=text)
