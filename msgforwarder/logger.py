
import logging
import sys

LOG = None


def setup(config):
    global LOG
    LOG = logging.getLogger(config.get("title", "forwarder"))
    LOG.setLevel(config.get("level", logging.INFO))

    formatter = logging.Formatter("%(asctime)s %(levelname)s | %(message)s",
                                  "%Y-%m-%d %H:%M:%S")
    for handler, cfg in config.get("handlers", {"stdout": None}).items():
        handler_cls = None
        if handler == "stdout":
            handler_cls = logging.StreamHandler(sys.stdout)
        elif handler == "file":
            handler_cls = logging.FileHandler(cfg)

        if handler_cls:
            handler_cls.setFormatter(formatter)
            LOG.addHandler(handler_cls)


def info(msg):
    LOG.info(msg)


def warning(msg):
    LOG.warning(msg)


def debug(msg):
    LOG.debug(msg)


def exception(msg):
    LOG.exception(msg)


def error(msg):
    LOG.error(msg)
