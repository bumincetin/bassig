"""Reading the project's own content in Turkish or Italian.

`app/i18n.py` translates the interface: the buttons, headings and messages
the application itself writes. This module translates the *content* -- the
activity names from Schedule 03, the acceptance-gate prerequisites, the
permit register, the document titles. That text arrives from the contract
documents, so it used to be shown exactly as written, in English. On a site
where the team works in Turkish that meant most of what is on the screen
stayed English, which is what this module fixes.

The contractual guarantee is unchanged, and that is the point of doing it
here rather than in the database:

* the stored value is never touched. What was imported from Schedule 03 is
  what stays in `wbs_activity.activity_name`, what is compared against the
  baseline, and what a CSV export contains;
* only the label on the screen changes, exactly as it already does for a
  status like `IN PROGRESS`;
* an untranslated string degrades to the original wording rather than to a
  blank or an identifier, so a missing entry is a small annoyance and never
  a lost fact;
* the original is kept within reach: pages that show a translated name carry
  the source wording in the element's tooltip.

Catalogues live in `translations/content/<code>.json`, keyed by the exact
source string. They are separate files from the interface catalogues because
they change for a different reason: the interface changes when the software
changes, this changes when the project's documents do.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.i18n import DEFAULT_LANGUAGE, LANGUAGES, current_language

logger = logging.getLogger(__name__)

CONTENT_DIR = Path(__file__).resolve().parent.parent / "translations" / "content"

#: code -> {source string: translated string}
_CATALOGUES: dict[str, dict[str, str]] = {}
#: Source strings seen at runtime with no translation, for the coverage report.
_MISSING: dict[str, set[str]] = {code: set() for code in LANGUAGES}


def load_catalogues(directory=None):
    """Read every content catalogue from disk. Called once at start-up."""
    directory = Path(directory or CONTENT_DIR)
    _CATALOGUES.clear()
    for code in LANGUAGES:
        if code == DEFAULT_LANGUAGE:
            _CATALOGUES[code] = {}
            continue
        path = directory / f"{code}.json"
        if not path.exists():
            _CATALOGUES[code] = {}
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.error("Could not read the %s content catalogue: %s", code, exc)
            data = {}
        _CATALOGUES[code] = {k: v for k, v in data.items() if isinstance(v, str) and v.strip()}
    return {code: len(entries) for code, entries in _CATALOGUES.items()}


def translate_content(text, language=None):
    """The project's own wording, in the reader's language where known."""
    if text is None:
        return ""
    source = str(text)
    if not source.strip():
        return source
    language = language or current_language()
    if language == DEFAULT_LANGUAGE:
        return source

    catalogue = _CATALOGUES.get(language) or {}
    found = catalogue.get(source) or catalogue.get(source.strip())
    if found is not None:
        return found
    # A project field can hold a word the interface already knows -- a
    # discipline, a category, a status. Read it the same way in both places.
    from app import i18n
    found = i18n.lookup(source, language)
    if found is not None:
        return found
    _MISSING.setdefault(language, set()).add(source.strip())
    return source


def is_translated(text, language=None):
    """True when this exact content string has an entry."""
    language = language or current_language()
    if language == DEFAULT_LANGUAGE or text is None:
        return False
    from app import i18n
    catalogue = _CATALOGUES.get(language) or {}
    source = str(text).strip()
    return source in catalogue or i18n.lookup(source, language) is not None


def missing_report():
    """Content strings seen on screen with no translation, per language."""
    return {code: sorted(values) for code, values in _MISSING.items()
            if code != DEFAULT_LANGUAGE}


def coverage(values, language):
    """How much of a set of content strings this language covers."""
    values = [str(v).strip() for v in values if v and str(v).strip()]
    if not values:
        return {"total": 0, "translated": 0, "percent": 100.0}
    catalogue = _CATALOGUES.get(language) or {}
    done = sum(1 for v in values if v in catalogue)
    return {"total": len(values), "translated": done,
            "percent": done / len(values) * 100.0}


def init_app(app):
    counts = load_catalogues()
    app.logger.info("Content catalogues loaded: %s", counts)

    # `tc` mirrors `t`: a Jinja global so macros imported without context can
    # still use it, and a filter so `{{ row.activity_name | tc }}` reads well.
    app.jinja_env.globals["tc"] = translate_content

    @app.template_filter("tc")
    def _filter(value):
        return translate_content(value)

    @app.template_filter("tc_title")
    def _source_wording(value):
        """The original wording, for a tooltip, when a translation is shown.

        Empty when nothing was translated, so the template can leave the
        attribute off rather than repeat the same text twice.
        """
        if value is None:
            return ""
        return str(value) if is_translated(value) else ""
