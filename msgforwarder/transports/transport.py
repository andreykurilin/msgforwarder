
import asyncio
import blinker
import jsonschema

from msgforwarder import logger


class BaseTransport(object):

    NAME = __name__
    CONFIG_SCHEMA = {}
    MSG_TEMPLATE = "[From %(from_client)s] %(author)s : %(msg)s"

    def __init__(self, client_id, client_cfg):
        self._client_id = client_id
        self._client_cfg = client_cfg
        self._msg_template = self._client_cfg.get("msg_template",
                                                  self.MSG_TEMPLATE)

    @classmethod
    def validate(cls, cfg):
        jsonschema.validate(cfg, cls.CONFIG_SCHEMA)

    def connect(self):
        logger.info("[%s] Connecting..." % self._client_id)
        self._connect()

    def _connect(self):
        raise NotImplementedError

    def say(self, author, from_client, from_target, target, msg):
        msg = self._msg_template % {
            "author": author,
            "from_client": from_client,
            "from_target": from_target,
            "target": target,
            "msg": msg
        }
        logger.debug("Forwarding message `%s` to %s@%s" % (
            msg, target, self._client_id))
        asyncio.get_event_loop().create_task(self._say(target, msg))

    def _say(self, channel, msg):
        raise NotImplementedError

    def _forward_message(self, user, target, text):
        blinker.signal("messages").send(
            self._client_id, user=user, target=target, text=text)
