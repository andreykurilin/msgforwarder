#!/usr/bin/env python3

"""
Forwarder - is a simple irc bot for synchronizing messages between 
different channels and IRC networks. Since other popular messengers like Gitter
or Slack support IRC-tunnel, the Forwarder can help to not limit your community
by one tool and allow to involve people in your regular workflow without 
forcing to use old-fashion IRC.

Requirements of the tool:

* python 3 (tested with python 3.5)
* asyncirc library (pip install asyncio-irc)
* yaml (pip install yaml)

This script accepts only one cli argument, which is a path to a configuration 
file. The data in the file should be in YAML or JSON format, which are quite 
popular nowadays.

There are 3 expected keys in the config:

1. "clients" <- this section should include a dictionary where keys are 
   identifiers (e.g. Freenode/IRC/Gitter) which will be used as just 
   identification for a single client and for logging purpose.
   The values should be dictionaries with configuration for a single client.
   (execute `forwarder --help clients` to see JSONSchema)
2. "rules" <- a list with forwarding rules. Rule is a configuration of what to 
   where should be forwarded.
   (execute `forwarder --help rules` to see JSONSchema)
3. "logging" <- optional section with logging details: 

  * "title" - just name of logger. Defaults to "forwarder"
  * "level" - a numeric logging level
  * "handlers" - a dict, where keys can be "stdout" (to print logging into 
    stdout, the default behaviour) and "file" (to save logs in the specific 
    file).
    
An example of configuration of rallydev-bot for https://github.com/xRally team:

    {"clients": {
        "IRC": {
            "server": "chat.freenode.net",
            "port": 6667,
            "nickname": "rallydev-bot",
            "ident": "Mr.Gitter~",
            "realname": "https://gitter.im/xRally/Lobby",
            "channels": ["#openstack-rally"]},
        "Gitter": {
            "server": "irc.gitter.im",
            "port": 6697,
            "use_ssl": True
            "nickname": "rallydev-bot",
            "password": "hahaha. I'll not share our real password :)",
            "ident": "Mr.Gitter~",
            "realname": "https://gitter.im/xRally/Lobby",
            "channels": ["#xRally/Lobby", "#xRally/statuses"]},
     "rules": [
        {
            "from": "#openstack-rally@IRC", 
            "send_to": "#xRally/Lobby"@Gitter",
            "ignore_nicknames": ["openstackgerrit"],
            "msg_template": "*[From %(client_id)s]* **%(author)s** : %(msg)s"
        },
        {
            "from": "#openstack-rally@IRC", 
            "send_to": "#xRally/statuses@Gitter",
            "nickname": "openstackgerrit",
            "msg_template": "*[From %(client_id)s]* **%(author)s** : %(msg)s"
        },
        {
            "from": "#xRally/Lobby"@Gitter", 
            "send_to": "#openstack-rally@IRC"
        }]}
    }
    
    NOTES:
        
        1) You can connect to multiple number of clients(networks), but I 
           tested this script only with two
        2) Gitter support IRC tunnel. You should go to irc.gitter.im for 
           obtaining a token for authentication.
        3) Gitter/Slack supports formatting of messages. It is nice feature 
           which allows to make important data more visible. For example, In 
           the example, the author of original message will be bold.
        4) It is better to register regular user at IRC networks for forwarder,
           It should help in case of reconnections.
     
"""

import asyncio
import json
import jsonschema
import logging
import os
import re
import sys
import textwrap

from asyncirc import irc
import blinker
import yaml

LOG = None


CLIENT_SCHEMA = {
    "type": "object",
    "properties": {
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
            "description": "Use SSL for connection or not. Defaults to False"
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

RULE_SCHEMA = {
    "type": "object",
    "properties": {
        "from": {
            "type": "string",
            "description": "The client and a channel to forward messages from."
        },
        "send_to": {
            "type": "string",
            "description": "The client and a channel to forward messages to."
        },
        "nicknames": {
            "type": "array", "items": {"type": "string"},
            "description": "Forward messages only from specified nicknames."
        },
        "ignore_nicknames": {
            "type": "array", "items": {"type": "string"},
            "description": "Ignore forwarding messages from specific "
                           "nicknames."
        },
        "regexp": {
            "type": "string",
            "description": "Forward only specific messages."
        },
        "msg_template": {
            "type": "string",
            "description": "Format message before forwarding. The following "
                           "keys can be used: client_id, author, msg."
        }
    },
    "additionalProperties": False,
    "required": ["from", "send_to"]
}


class IRCClient(object):
    def __init__(self, client_id, client_cfg):
        self._client_id = client_id
        self._client_cfg = client_cfg
        self._irc = None

    def connect(self):
        LOG.info("Connecting %s to channel(s): %s..." %
                 (self._client_id, ", ".join(self._client_cfg["channels"])))
        self._irc = irc.connect(self._client_cfg["server"],
                                port=self._client_cfg["port"],
                                use_ssl=self._client_cfg.get("use_ssl", False))
        self._irc.register(self._client_cfg["nickname"],
                           user=self._client_cfg.get("ident", ""),
                           realname=self._client_cfg.get("realname", ""),
                           password=self._client_cfg.get("password", None))
        self._irc.join(self._client_cfg["channels"])

    def say(self, channel, msg):
        LOG.debug("Forwarding message `%s` to %s@%s" % (
            msg, channel, self._client_cfg["server"]))
        self._irc.say(channel, msg)


class Forwarder(object):

    DEFAULT_MSG_TEMPLATE = "[From %(client_id)s] %(author)s : %(msg)s"

    def __init__(self, clients, rules):
        self._rules = rules
        self._clients = clients
        for client in self._clients:
            self._clients[client]["client"] = IRCClient(client,
                                                        clients[client])
        blinker.signal("message").connect(self.on_message)

    def on_message(self, message, user, target, text):
        server_info = message.client.server_info
        author_id = "%s@%s:%s" % (message.client.nick,
                                  server_info["host"],
                                  server_info["port"])
        if user.nick == message.client.nick:
            # ignore messages from connected clients
            return
        LOG.info("Received message at %s from %s:\n%s" % (
            author_id, user.nick, textwrap.indent(text, "\t")))
        for rule in self._rules:
            from_channel, from_client_id = rule["from"].split("@", 1)
            # check that rule fit the message
            if (self._clients[from_client_id]["server"] != server_info["host"]
                    or from_channel != target):
                continue
            if "nicknames" in rule and user.nick not in rule["nicknames"]:
                continue
            if user.nick in rule.get("ignore_nicknames", []):
                continue
            if "regexp" in rule and not re.match(text, rule["regexp"]):
                continue

            # ok, the message ok, let's forward it
            to_channel, to_client_id = rule["send_to"].split("@", 1)
            msg_template = rule.get("msg_template", self.DEFAULT_MSG_TEMPLATE)
            self._clients[to_client_id]["client"].say(
                to_channel,
                msg_template % {
                    "client_id": from_client_id,
                    "author": user.nick,
                    "msg": text
                }
            )

    @classmethod
    def validate(cls, clients, rules):
        for client_id in clients:
            try:
                jsonschema.validate(clients[client_id], CLIENT_SCHEMA)
            except jsonschema.ValidationError:
                LOG.exception(
                    "The credentials of %s user is invalid." % client_id)
                return

        validated_rules = []
        for rule in rules:
            try:
                jsonschema.validate(rule, RULE_SCHEMA)
            except jsonschema.ValidationError:
                LOG.exception("The following rule is invalid.")
                return

            from_channel, from_client_id = rule["from"].split("@", 1)
            to_channel, to_client_id = rule["send_to"].split("@", 1)
            missed_user = (
                from_client_id if from_client_id not in clients else (
                    to_client_id if to_client_id not in clients else None))
            if missed_user:
                LOG.warning(
                    "The user '%s' is specified in the rule, but was not "
                    "initialized. This rule will be ignored." %
                    missed_user)
                continue
            validated_rules.append(rule)
        return clients, validated_rules

    def start(self):
        for client in self._clients.values():
            client["client"].connect()
        asyncio.get_event_loop().run_forever()


def run():
    args = sys.argv[1:]
    if "--help" in args or "-h" in args or "help" in args:
        if "clients" in args or "client" in args:
            print("The jsonschema for values of clients section: \n")
            print(json.dumps(CLIENT_SCHEMA, indent=4))
        elif "rules" in args or "rule" in args:
            print("The jsonschema for items of rules section: \n")
            print(json.dumps(RULE_SCHEMA, indent=4))
        else:
            print(__doc__)

        sys.exit(0)
    elif len(args) > 1:
        print("ERROR: there are too many provided arguments. "
              "Call `%s --help` to print help message." % __file__)
        sys.exit(1)
    elif not args:
        print("ERROR: You should provide a path to config. "
              "Call `%s --help` to print help message." % __file__)
        sys.exit(1)
    elif not os.path.isfile(os.path.expanduser(args[0])):
        print("IOError: Failed to open configuration file at %s." % args[0])
        sys.exit(1)

    filename = os.path.expanduser(args[0])
    with open(filename) as f:
        config = f.read()

    try:
        config = yaml.safe_load(config)
    except Exception:
        print("ERROR: failed to load config file. It doesn't look like valid "
              "YAML or JSON.")
        raise

    if "clients" not in config:
        print("ERROR: You should specify clients section. "
              "Call `%s --help` to print help message." % __file__)
        sys.exit(1)
    elif "rules" not in config:
        print("ERROR: You should specify rules section. "
              "Call `%s --help` to print help message." % __file__)
        sys.exit(1)

    resp = Forwarder.validate(config["clients"], config["rules"])
    if resp is None:
        sys.exit(1)
    clients, rules = resp

    # ok, everything looks valid
    global LOG
    logging_cfg = config.get("logging", {})
    LOG = logging.getLogger(logging_cfg.get("title", "forwarder"))
    LOG.setLevel(logging_cfg.get("level", logging.INFO))

    formatter = logging.Formatter("%(asctime)s %(levelname)s | %(message)s",
                                  "%Y-%m-%d %H:%M:%S")
    for handler, cfg in logging_cfg.get("handlers", {"stdout": None}).items():
        handler_cls = None
        if handler == "stdout":
            handler_cls = logging.StreamHandler(sys.stdout)
        elif handler == "file":
            handler_cls = logging.FileHandler(cfg)

        if handler_cls:
            handler_cls.setFormatter(formatter)
            LOG.addHandler(handler_cls)

    # start forwarder
    Forwarder(clients, rules).start()

if __name__ == "__main__":
    run()
