import logging
import os
import sys
import time

from starlette.requests import Request

from server.app import create_app


def _debug_init():
    root_logger = logging.getLogger("telephonist")

    class InfoFilter(logging.Filter):
        def filter(self, rec):
            return rec.levelno in (logging.DEBUG, logging.INFO)

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
    app = create_app()
    _debug_init()

    logger = logging.getLogger("telephonist.debug")

    @app.middleware("http")
    async def add_process_time_header(request: Request, call_next):
        start_time = time.time()
        cpu_start = time.process_time()
        response = await call_next(request)
        process_time = time.time() - start_time
        cpu_time = time.process_time() - cpu_start
        response.headers["Server-Timing"] = (
            f"app;dur={(process_time - cpu_time) * 1000},"
            f" cpu;dur={cpu_time * 1000}"
        )
        logger.debug(
            f"{request.method} {request.url} -"
            f" total={seconds_to_string(process_time)} cpu={seconds_to_string(cpu_time)}"
        )
        return response

    return app
