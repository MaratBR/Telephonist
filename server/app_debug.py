import logging
import os
import sys

from server.app import create_debug_app as _create_debug_app


def debug_init():
    root_logger = logging.getLogger("telephonist")

    class InfoFilter(logging.Filter):
        def filter(self, rec):
            return rec.levelno <= logging.INFO

    log_factory = logging.getLogRecordFactory()
    cwd = os.getcwd()

    def _debug_log_factory(*args, **kwargs):
        record = log_factory(*args, **kwargs)
        record.compact_path = record.pathname[len(cwd) + 1 :]
        return record

    logging.setLogRecordFactory(_debug_log_factory)

    formatter = logging.Formatter("%(compact_path)s:%(lineno)d:\t%(message)s")

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    stderr_handler.setLevel(logging.WARNING)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    stdout_handler.setLevel(logging.DEBUG)
    stdout_handler.addFilter(InfoFilter())

    root_logger.handlers = [stdout_handler, stderr_handler]
    root_logger.setLevel(logging.DEBUG)


def seconds_to_string(seconds: float):
    if seconds < 1.5:
        return f"{seconds * 1000}ms"
    return f"{seconds}s"


def create_debug_app():
    debug_init()
    app = _create_debug_app()
    return app
