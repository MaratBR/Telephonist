import contextvars
from gettext import NullTranslations
from typing import Optional

translation_var: contextvars.ContextVar[
    Optional[NullTranslations]
] = contextvars.ContextVar("Current translations instance", default=None)


def gettext(v):
    t = translation_var.get()
    if t is None:
        return v
    return t.gettext(v)
