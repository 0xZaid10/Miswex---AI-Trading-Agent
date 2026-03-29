import logging
import os
from datetime import datetime

def setup_logger(level=None):

    log_file = f"logs/bot_{datetime.now().strftime('%Y%m%d')}.log"

    # Allow ENV override
    if level is None:
        level = logging.DEBUG if os.getenv("LOG_LEVEL") == "DEBUG" else logging.INFO

    logger = logging.getLogger()
    logger.setLevel(level)

    # Prevent duplicate handlers
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger
