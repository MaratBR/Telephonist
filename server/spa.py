import os
from typing import Callable, Optional

from starlette.staticfiles import StaticFiles


class SPA(StaticFiles):
    def __init__(
        self,
        directory: str,
        index: str = "index.html",
        api_path_check: Optional[Callable[[str], bool]] = None,
    ):
        super(SPA, self).__init__(directory=directory)
        self.index = index
        self.api_path_check = api_path_check

    def lookup_path(self, path: str) -> tuple[str, Optional[os.stat_result]]:
        if path.startswith("/"):
            path = path[1:]
        if self.api_path_check and self.api_path_check(path):
            return "", None
        if path in (".", "/"):
            return super(SPA, self).lookup_path(self.index)
        else:
            full_path, stat = super(SPA, self).lookup_path(path)
            if stat is None:
                full_path, stat = super(SPA, self).lookup_path(self.index)
            return full_path, stat
