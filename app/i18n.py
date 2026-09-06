"""English / Turkish / Italian interface, without a build step.

Catalogues are plain JSON keyed by the English source string, so the English
interface is the catalogue's own key set and a missing translation falls back to
readable English rather than to a raw identifier. That matters on a site tool:
an untranslated label is a small annoyance, a label reading `nav.dashboard`
is a defect.

Two things are deliberately NOT translated:

* Project data — activity names from Schedule 03, document titles, contractor
  names, observation text. That is contractual content and must read exactly as
  its source document does.
* Stored status values. `IN PROGRESS` is stored, compared and exported in
  English; only its on-screen label changes. Switching language can therefore
  never change what the database holds or what a CSV export contains.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path

from flask import g, request, session

logger = logging.getLogger(__name__)

DEFAULT_LANGUAGE = "en"

#: code -> (endonym, short label for the switcher)
LANGUAGES = {
    "en": ("English", "EN"),
    "tr": ("Türkçe", "TR"),
    "it": ("Italiano", "IT"),
}

SESSION_KEY = "language"
CATALOGUE_DIR = Path(__file__).resolve().parent.parent / "translations"

#: code -> {english source: translated}
_CATALOGUES: dict[str, dict[str, str]] = {}
#: Source strings seen at runtime with no translation, for the coverage report.
_MISSING: dict[str, set[str]] = {code: set() for code in LANGUAGES}

#: Date format per language. Turkish writes 04.09.2026, the others 04/09/2026.
DATE_FORMATS = {"en": "%d/%m/%Y", "it": "%d/%m/%Y", "tr": "%d.%m.%Y"}


def load_catalogues(directory=None):
    """Read every catalogue from disk. Called once at start-up."""
    directory = Path(directory or CATALOGUE_DIR)
    _CATALOGUES.clear()
    for code in LANGUAGES:
        if code == DEFAULT_LANGUAGE:
            _CATALOGUES[code] = {}
            continue
        path = directory / f"{code}.json"
        if not path.exists():
            logger.warning("No translation catalogue for %s at %s", code, path)
            _CATALOGUES[code] = {}
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.error("Could not read the %s catalogue: %s", code, exc)
            data = {}
        _CATALOGUES[code] = {k: v for k, v in data.items() if isinstance(v, str) and v}
    return {code: len(entries) for code, entries in _CATALOGUES.items()}


def supported(code):
    return code in LANGUAGES


def resolve_language():
    """Language for this request: explicit choice, then session, then browser."""
    requested = (request.args.get("lang") or "").lower()
    if supported(requested):
        session[SESSION_KEY] = requested
        session.permanent = True
        return requested

    stored = (session.get(SESSION_KEY) or "").lower()
    if supported(stored):
        return stored

    best = request.accept_languages.best_match(list(LANGUAGES)) if request else None
    return best if supported(best) else DEFAULT_LANGUAGE


def current_language():
    try:
        return getattr(g, "language", DEFAULT_LANGUAGE)
    except RuntimeError:  # outside an application context, e.g. a launcher script
        return DEFAULT_LANGUAGE


def translate(text, language=None, **kwargs):
    """Translate one English source string.

    Placeholders are substituted after lookup, so a translator can reorder them:
    `t("{count} of {total} satisfied", count=3, total=9)`.
    """
    if text is None:
        return ""
    source = str(text)
    if not source.strip():
        # A blank option label has nothing to translate and must not be
        # reported as a missing entry.
        return source
    language = language or current_language()

    if language == DEFAULT_LANGUAGE:
        result = source
    else:
        catalogue = _CATALOGUES.get(language) or {}
        result = catalogue.get(source)
        if result is None:
            # Try the trimmed form: templates often carry incidental whitespace.
            stripped = source.strip()
            result = catalogue.get(stripped)
            if result is None:
                _MISSING.setdefault(language, set()).add(stripped or source)
                result = source

    if kwargs:
        try:
            return result.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            # A malformed placeholder must never break a page.
            logger.warning("Bad placeholder in translation of %r", source)
            return result
    return result


def lookup(text, language):
    """A translation if the catalogue has one, else None. Records no miss.

    Used by the content layer, which consults this before falling back to the
    source wording: a project field that happens to hold a word the interface
    already knows should read the same way in both places.
    """
    if text is None or language == DEFAULT_LANGUAGE:
        return None
    catalogue = _CATALOGUES.get(language) or {}
    source = str(text)
    return catalogue.get(source) or catalogue.get(source.strip())


def missing_report():
    """Source strings seen at runtime with no translation, per language."""
    return {code: sorted(values) for code, values in _MISSING.items()
            if code != DEFAULT_LANGUAGE}


def coverage():
    """How much of the catalogue each language carries."""
    english_keys = set()
    for code, entries in _CATALOGUES.items():
        if code != DEFAULT_LANGUAGE:
            english_keys |= set(entries)
    total = len(english_keys) or 1
    return {
        code: {
            "name": LANGUAGES[code][0],
            "entries": len(_CATALOGUES.get(code) or {}),
            "percent": (len(_CATALOGUES.get(code) or {}) / total) * 100.0,
        }
        for code in LANGUAGES if code != DEFAULT_LANGUAGE
    }


def date_format(language=None):
    return DATE_FORMATS.get(language or current_language(), DATE_FORMATS[DEFAULT_LANGUAGE])


def format_date(value, language=None):
    """A date written the way the selected language writes it.

    Flash messages use this rather than a hard-coded strftime so that a date
    inside a sentence matches the dates in the tables around it.
    """
    if value is None:
        return "-"
    fmt = date_format(language)
    if isinstance(value, datetime):
        return value.strftime(fmt + " %H:%M")
    if isinstance(value, date):
        return value.strftime(fmt)
    return str(value)


def init_app(app):
    counts = load_catalogues()
    app.logger.info("Translation catalogues loaded: %s", counts)

    @app.before_request
    def _set_language():
        g.language = resolve_language()

    # `t` is a Jinja global rather than a context variable so that macros
    # imported without `with context` can still translate their labels.
    app.jinja_env.globals["t"] = translate

    @app.context_processor
    def _inject():
        language = current_language()
        return {
            "LANG": language,
            "LANG_LABEL": LANGUAGES[language][1],
            "LANG_NAME": LANGUAGES[language][0],
            "LANGUAGES": LANGUAGES,
        }

    @app.template_filter("t")
    def _filter(value):
        return translate(value)
