import logging
import os
import sys

LOG_LEVEL = os.getenv("LC_LOG_LEVEL", "INFO").upper()

_formatter = logging.Formatter(
    "[%(asctime)s] %(levelname)-7s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

_handler = logging.StreamHandler(sys.stderr)
_handler.setFormatter(_formatter)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.addHandler(_handler)
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.DEBUG))
    return logger