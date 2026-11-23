"""Player-facing text in two languages. English is the default (MCP tools, tests, API without a header);
the web app sends X-SOE-Lang: pl|en and its middleware sets the language for the request.

    from soe.i18n import t
    t("Missing: {x}", "Brakuje: {x}", x=...)   # or with f-strings: t(f"...", f"...")
"""
from __future__ import annotations

from contextvars import ContextVar

LANGS = ("en", "pl")
_lang: ContextVar[str] = ContextVar("soe_lang", default="en")


def set_lang(lang: str | None):
    return _lang.set(lang if lang in LANGS else "en")


def reset_lang(token):
    _lang.reset(token)


def lang() -> str:
    return _lang.get()


def t(en: str, pl: str, **kw) -> str:
    s = pl if _lang.get() == "pl" else en
    return s.format(**kw) if kw else s
