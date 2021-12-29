import logging
import os
import sys

from loguru import logger


class InterceptHandler(logging.Handler):
    def emit(self, record):
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage(), logger_name=record.name
        )


LOG_LEVEL = logging.getLevelName(os.environ.get("LOG_LEVEL", "DEBUG"))
JSON_LOGS = True if os.environ.get("JSON_LOGS", "0") == "1" else False


def create_logger():
    logger.remove()
    logger.bind(logger_name="default")
    format = "<green>{time:YYMMDD hh:mm:ss}</green> | <level>{message}</level>"
    logger.add(sys.stderr, format=format)
    seen = set()
    logging.getLogger("uvicorn.access").handlers = [InterceptHandler()]
    for logger_name in ["uvicorn", "uvicorn.access"]:
        logger_name = logger_name.split(".")[0]
        if logger_name not in seen:
            seen.add(logger_name)
            logging.getLogger(logger_name).handlers = [InterceptHandler()]
    return logging.getLogger("fastapi")
