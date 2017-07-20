=========
FORWARDER
=========

Forwarder - is a simple irc bot for synchronizing messages between
different channels and IRC, Gitter networks.

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

  .. code-block:: json

    {"clients": {
        "IRC": {
            "server": "chat.freenode.net",
            "port": 6667,
            "nickname": "rallydev-bot",
            "ident": "Mr.Gitter~",
            "realname": "https://gitter.im/xRally/Lobby",
            "channels": ["#openstack-rally"]},
        "Gitter": {
            "token": "hahaha. I'll not share a real token :).",
            "channels": ["xRally/Lobby", "xRally/statuses"]}},
        "rules": [
        {
            "from": "#openstack-rally@IRC",
            "send_to": "xRally/Lobby@Gitter",
            "ignore_nicknames": ["openstackgerrit"]
        },
        {
            "from": "#openstack-rally@IRC",
            "send_to": "xRally/statuses@Gitter",
            "nicknames": ["openstackgerrit"]
        },
        {
            "from": "xRally/Lobby@Gitter",
            "send_to": "#openstack-rally@IRC"
        }]
    }


NOTES:

    1) You can connect to multiple number of clients(networks), but I
       tested this script only with two
    2) To take a token for Gitter you need to login at
       https://developer.gitter.im/apps.
    3) It is better to register regular user at IRC networks for forwarder,
       It should help in case of reconnections.
