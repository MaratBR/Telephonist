import gettext
import re
from typing import Optional, Type

from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.requests import Request
from starlette.responses import Response

__all__ = ("Localization",)

from server.l10n.lazy_l10n import translation_var


def parse_accept_language(v: str):
    languages = v.split(",")
    locale_q_pairs = []

    for language in languages:
        if language.split(";")[0] == language:
            # no q => q = 1
            locale_q_pairs.append((language.strip(), "1"))
        else:
            locale = language.split(";")[0].strip()
            q = language.split(";")[1].split("=")[1]
            locale_q_pairs.append((locale, q))

    return locale_q_pairs


def detect_language(
    accept_language: str, supported_languages: list[str], default: str
):
    pairs = parse_accept_language(accept_language)
    for pair in pairs:
        for locale in supported_languages:
            if pair[0].replace("-", "_").lower().startswith(locale.lower()):
                return locale

    return default


class LocalizationMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        l10n: "Localization",
        supported_languages: list[str],
        default_locale: str,
        set_header: bool = False,
        language_cookie: str = "lang",
    ):
        super(LocalizationMiddleware, self).__init__(app)
        self.supported_languages = supported_languages
        self.default_locale = default_locale
        self.set_header = set_header
        self._l10n = l10n
        self.cookie = language_cookie

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        language_cookie = request.cookies.get(self.cookie)
        if language_cookie and language_cookie in self.supported_languages:
            detected = language_cookie
        else:
            accept_language = request.headers.get("accept-language")
            if accept_language:
                detected = detect_language(
                    accept_language,
                    supported_languages=self.supported_languages,
                    default=self.default_locale,
                )
            else:
                detected = self.default_locale
        request.scope["locale"] = detected
        t = self._l10n.get_translation(detected)
        translation_var.set(t)
        response = await call_next(request)
        if self.set_header:
            response.headers["X-Detected-Language"] = detected
        return response


locale_regexp = re.compile(
    r"^[A-Za-z]{2,4}([_-][A-Za-z]{4})?([_-]([A-Za-z]{2}|\d{3}))?$"
)


def _chk_locale(locale: str):
    if not locale_regexp.match(locale):
        raise ValueError(f'"{locale}" is not a valid locale string')


class Localization:
    def __init__(
        self,
        localedir: str,
        supported_locales: list[str],
        default_locale: Optional[str] = None,
    ):
        if len(supported_locales) == 0:
            raise ValueError("Empty list of locales")
        default_locale = default_locale or supported_locales[0]
        _chk_locale(default_locale)
        for locale in supported_locales:
            _chk_locale(locale)
        self.supported_locales = supported_locales
        if default_locale not in supported_locales:
            self.supported_locales.append(default_locale)
        self.default_locale = default_locale
        self._initialized = False
        self._translations: dict[str, gettext.NullTranslations] = {}
        self.localedir = localedir
        self._middleware_class: Optional[Type[LocalizationMiddleware]] = None

    def init(self):
        if self._initialized:
            return
        for locale in self.normalized_locales:
            self._translations[locale] = gettext.translation(
                localedir=self.localedir, domain="messages", languages=[locale]
            )

    def get_translation(self, locale: str):
        self.init()
        t = self._translations.get(locale)
        if t is None:
            t = self._translations[self.default_locale]
        return t

    @property
    def normalized_locales(self) -> set[str]:
        return set(
            {
                v.casefold(): v
                for v in map(
                    lambda v: v.replace("-", "_"), self.supported_locales
                )
            }.values()
        )

    @property
    def middleware(self) -> Type[BaseHTTPMiddleware]:
        self.init()
        if self._middleware_class is None:
            this = self

            class ConcreteLocalizationMiddleware(LocalizationMiddleware):
                def __init__(self, app):
                    super(ConcreteLocalizationMiddleware, self).__init__(
                        app,
                        this,
                        supported_languages=this.supported_locales,
                        default_locale=this.default_locale,
                    )

            self._middleware_class = ConcreteLocalizationMiddleware
        return self._middleware_class
