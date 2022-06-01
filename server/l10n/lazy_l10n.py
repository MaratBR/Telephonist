import contextvars
from gettext import NullTranslations
from typing import Optional

translation_var: contextvars.ContextVar[
    Optional[NullTranslations]
] = contextvars.ContextVar(
    "Current translations instance", default=NullTranslations()
)


def gettext(v):
    return translation_var.get().gettext(v)
