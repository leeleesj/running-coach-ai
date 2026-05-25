"""중앙 로깅 설정"""

import logging
import sys


def _setup_root_logger() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )


_setup_root_logger()


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
