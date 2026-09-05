"""Nothing the interface says may stay English when another language is chosen.

`tests/test_translations.py` guards the templates: it fails when literal text
is typed into a page without passing through `t()`. That guard cannot see two
much larger classes of English, and both of them reached the site:

* text assembled inside a Jinja expression -- the KPI captions were built as
  `count ~ ' leaf activities'`, and the guard masks `{{ ... }}` before it
  looks;
* text produced in Python -- status values from `app/constants.py`, the daily
  report's summary lines, the DATA REQUIRED messages, the threshold
  descriptions and the restore instructions.

So this module works from the other end: it renders every page twice and
compares what a person would actually read. Anything identical in English and
Turkish is English that never reached a catalogue.
"""
from __future__ import annotations

import json
import pathlib
import re
from html.parser import HTMLParser

import pytest

from app import constants as C
from app import i18n
from app.services import importers

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Pages worth sweeping. Detail pages are added by the fixtures below.
PAGES = [
    "/", "/schedule/", "/schedule/versions", "/schedule/lookahead", "/schedule/recovery",
    "/progress/", "/progress/forecast", "/progress/quantities", "/daily/", "/daily/new",
    "/daily/observations", "/quality/", "/quality/requirements", "/issues/", "/procurement/",
    "/procurement/materials", "/procurement/deliveries", "/acceptance/", "/acceptance/documents",
    "/permits/", "/rfi/", "/blockers/", "/blockers/analysis", "/setup/documents", "/workforce/",
    "/workforce/contractors", "/commercial/", "/reports/", "/reports/daily", "/reports/weekly",
    "/setup/", "/setup/project", "/setup/areas", "/setup/thresholds", "/setup/validation",
    "/data/", "/backup/", "/daily/today",
]

#: Text that is deliberately identical in every language.
#:
#: The import templates' column names are the literal headers of the CSV files
#: the user uploads: translating them would break every import. Everything
#: else here is a code, a unit or a symbol.
ALLOWED = {
    "-", "/", "|", "&", "+", "%", "n/a", "OK", "EUR", "CSV", "XLSX", "PDF",
    "WBS", "ITP", "NCR", "RFI", "FAT", "IFC", "HSE", "QA/QC", "PAC", "FAC",
    "BAS", "DC", "AC", "kWp", "MWp", "kW", "kV", "m/s", "mm/h", "h", "m2", "m3",
    "Bassignana Solar 2", "BASSIGNANA EPC CONTROL", "Bassignana",
}


def column_lists():
    """The exact header rows of the import templates, which stay English."""
    lists = set()
    for spec in importers.SPECS.values():
        lists.add(", ".join(spec.columns))
        lists.add(", ".join(spec.required))
    return lists


ALLOWED_LISTS = column_lists()


class VisibleText(HTMLParser):
    """Everything a person reads on the page, and nothing else."""

    SKIP = {"script", "style"}
    ATTRIBUTES = {"placeholder", "title", "aria-label", "alt", "data-confirm",
                  "data-label-none", "data-label-value"}

    def __init__(self):
        super().__init__()
        self.stack, self.chunks, self.attributes = [], [], []

    def handle_starttag(self, tag, attrs):
        self.stack.append(tag)
        for name, value in attrs:
            if name in self.ATTRIBUTES and value and value.strip():
                self.attributes.append(value.strip())

    def handle_endtag(self, tag):
        if tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass

    def handle_data(self, data):
        if any(t in self.SKIP for t in self.stack):
            return
        text = re.sub(r"\s+", " ", data).strip()
        if text:
            self.chunks.append(text)


def read(html):
    parser = VisibleText()
    parser.feed(html)
    return set(parser.chunks), set(parser.attributes)


#: A word that only an English-speaking reader would recognise.
ENGLISH = re.compile(
    r"\b(the|and|with|from|for|of|is|are|was|were|not|this|that|by|on|at|to|in|be|"
    r"no|yes|all|any|each|has|have|had|will|would|can|could|may|must|should|"
    r"add|new|edit|save|delete|remove|open|close|closed|show|hide|total|date|name|"
    r"status|type|record|records|report|reports|day|days|week|weeks|item|items|"
    r"required|planned|actual|progress|quantity|quantities|activity|activities|"
    r"none|nothing|yet|per|than|then|when|where|which|what|who|why|how|"
    r"accepted|overdue|late|lost|hours|price|weighting|baseline|milestone)\b",
    re.I)


def suspicious(chunk):
    """True when this chunk is English that a reader should not be seeing."""
    if chunk in ALLOWED or chunk in ALLOWED_LISTS:
        return False
    if len(chunk) < 3 or not ENGLISH.search(chunk):
        return False
    # Codes, numbers, dates and units.
    if re.fullmatch(r"[-+*/=<>%&|.,;:()\[\]#0-9\s]+", chunk):
        return False
    return True


def sweep(client, paths):
    """Interface text that did not change between English and Turkish."""
    findings = {}
    for path in paths:
        separator = "&" if "?" in path else "?"
        english = client.get(f"{path}{separator}lang=en", follow_redirects=True)
        turkish = client.get(f"{path}{separator}lang=tr", follow_redirects=True)
        if english.status_code != 200 or turkish.status_code != 200:
            continue
        en_text, en_attrs = read(english.get_data(as_text=True))
        tr_text, tr_attrs = read(turkish.get_data(as_text=True))
        for chunk in (en_text & tr_text) | (en_attrs & tr_attrs):
            if suspicious(chunk):
                findings.setdefault(chunk, path)
    return findings


class TestNoEnglishSurvivesTheSwitch:
    def test_every_page_is_fully_translated(self, app, client):
        findings = sweep(client, PAGES)
        assert findings == {}, \
            "English text reached a Turkish page:\n" + "\n".join(
                f"  {path}: {chunk[:90]}" for chunk, path in sorted(findings.items()))

    def test_the_detail_pages_are_fully_translated(self, app, client, db, daily_report,
                                                   area, working_version, activity_factory,
                                                   gate_a):
        from datetime import date
        activity = activity_factory(working_version, "1.1", "Foundation piles",
                                    date(2026, 8, 1), date(2026, 9, 30))
        client.post("/issues/ncr/new", data={"title": "Torque below specification",
                                             "severity": "MAJOR"}, follow_redirects=True)
        from app.models import QualityRecord
        ncr = QualityRecord.query.first()
        paths = [f"/daily/{daily_report.id}", f"/schedule/activity/{activity.id}",
                 f"/acceptance/gate/{gate_a.gate_code}", f"/issues/ncr/{ncr.id}"]
        findings = sweep(client, [p for p in paths if client.get(p).status_code == 200])
        assert findings == {}, \
            "English text reached a Turkish detail page:\n" + "\n".join(
                f"  {path}: {chunk[:90]}" for chunk, path in sorted(findings.items()))


class TestTheStoredVocabularyIsTranslated:
    """Every status, category and type in constants.py is shown to the user."""

    @staticmethod
    def vocabulary():
        terms = set()
        for name in dir(C):
            if name.startswith("_"):
                continue
            value = getattr(C, name)
            if isinstance(value, (list, tuple, set)):
                for entry in value:
                    if isinstance(entry, str) and entry.strip():
                        terms.add(entry)
            elif isinstance(value, dict):
                terms.update(k for k in value if isinstance(k, str) and k.strip())
            elif isinstance(value, str) and value.strip() and name.isupper():
                terms.add(value)
        # Gate letters, record-number prefixes, CSS classes and contract
        # references are codes, not words.
        return {t for t in terms
                if not t.startswith(("bg-", "text-", "BAS-", "Schedule 0"))
                and len(t) > 1}

    @pytest.mark.parametrize("code", ["tr", "it"])
    def test_every_stored_value_has_a_label(self, code):
        catalogue = json.loads(
            (ROOT / "translations" / f"{code}.json").read_text(encoding="utf-8"))
        missing = sorted(t for t in self.vocabulary() if t not in catalogue)
        assert missing == [], f"{code}: no label for {missing[:8]}"

    #: Terms the trade uses in English in that language too. Forcing a
    #: translation here would make the page harder to read, not easier: an
    #: Italian site engineer writes "punch list" and "as-built".
    LOANWORDS = {
        "it": {"PUNCH LIST", "Punch List", "As-Built", "LOOKAHEAD", "Lookahead",
               "Milestone", "Baseline"},
        "tr": set(),
    }

    @pytest.mark.parametrize("code", ["tr", "it"])
    def test_no_label_is_a_copy_of_the_stored_value(self, code):
        catalogue = json.loads(
            (ROOT / "translations" / f"{code}.json").read_text(encoding="utf-8"))
        copied = sorted(t for t in self.vocabulary()
                        if catalogue.get(t) == t and len(t) > 4
                        and t not in {"QA/QC", "PDF", "CSV", "XLSX"}
                        and t not in self.LOANWORDS[code])
        assert copied == [], f"{code}: untranslated {copied[:8]}"


class TestTheStoredValueNeverChanges:
    """Translating a label must not touch what is stored, posted or exported."""

    def test_a_dropdown_posts_the_english_value(self, app, client):
        page = client.get("/issues/?lang=tr").get_data(as_text=True)
        # The option's value stays English; only the text a person reads moves.
        assert 'value="IN PROGRESS"' in page
        assert i18n.translate("IN PROGRESS", language="tr") in page
        assert ">IN PROGRESS<" not in page

    def test_a_status_badge_keeps_the_english_value_out_of_sight(self, app, client, db):
        client.post("/issues/ncr/new", data={"title": "Torque below specification",
                                             "severity": "MAJOR"}, follow_redirects=True)
        from app.models import QualityRecord
        assert QualityRecord.query.one().status == "OPEN"
        turkish = client.get("/issues/?lang=tr").get_data(as_text=True)
        assert i18n.translate("OPEN", language="tr") in turkish

    def test_the_csv_export_is_unchanged_by_the_language(self, app, client, db, daily_report):
        english = client.get("/daily/export.csv?lang=en").get_data(as_text=True)
        turkish = client.get("/daily/export.csv?lang=tr").get_data(as_text=True)
        assert english == turkish
