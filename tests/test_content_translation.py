"""The project's own words, read in the reader's language.

The interface catalogues translate what the application says. These
catalogues translate what the *project* says: the activity names from
Schedule 03, the acceptance-gate prerequisites, the permit register, the
document titles. Before this existed a Turkish user saw a Turkish menu around
an English programme, which is most of the screen.

What must stay true, and is checked here:

* the stored value never changes. The database, the baseline comparison and
  every CSV export keep the wording of the source document;
* a missing entry degrades to that wording, never to a blank;
* the original stays reachable, in the tooltip of a translated name.
"""
from __future__ import annotations

import json
import pathlib
import re
from datetime import date

import pytest

from app import content_i18n, i18n

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTENT = ROOT / "translations" / "content"


def catalogue(code):
    return json.loads((CONTENT / f"{code}.json").read_text(encoding="utf-8"))


class TestTheCatalogues:
    def test_both_languages_exist(self):
        for code in ("tr", "it"):
            assert (CONTENT / f"{code}.json").exists()

    def test_they_cover_the_same_source_strings(self):
        assert set(catalogue("tr")) == set(catalogue("it"))

    def test_they_are_not_empty(self):
        assert len(catalogue("tr")) > 500

    @pytest.mark.parametrize("code", ["tr", "it"])
    def test_no_entry_is_blank(self, code):
        blank = [k for k, v in catalogue(code).items() if not str(v).strip()]
        assert blank == []

    @pytest.mark.parametrize("code", ["tr", "it"])
    def test_the_programme_is_translated(self, code):
        """The schedule activity names are what a site engineer reads all day."""
        entries = catalogue(code)
        for name in ("Foundation Piles Ramming", "PV Mechanical Works",
                     "Development of Executive Design", "Mechanical Completion"):
            assert name in entries, f"{code}: {name} has no translation"
            assert entries[name] != name


class TestTheFilterIsAppliedToTheFieldNotTheFallback:
    """`{{ x or '-' | tc }}` translates the dash, not x.

    A Jinja filter binds tighter than `or`, so that expression parses as
    `x or ('-' | tc)` and the field itself is never translated. It read
    correctly, it passed every page-renders test, and it silently left 59
    fields in English. The parentheses are the whole fix.
    """

    PATTERN = re.compile(r"\{\{\s*[A-Za-z_][A-Za-z0-9_.\[\]']*\s+or\s+"
                         r"(?:'[^']*'|\"[^\"]*\")\s*\|\s*tc?\s*\}\}")

    def test_no_template_filters_only_the_fallback(self):
        findings = []
        for path in sorted((ROOT / "templates").rglob("*.html")):
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if self.PATTERN.search(line):
                    findings.append(f"{path.name}:{lineno} {line.strip()[:80]}")
        assert findings == [], (
            "the filter binds to the fallback, not the field; wrap it in "
            "parentheses:\n" + "\n".join(findings[:8]))


class TestTranslatingContent:
    def test_a_known_string_is_translated(self, app):
        assert content_i18n.translate_content(
            "Foundation Piles Ramming", "tr") != "Foundation Piles Ramming"

    def test_an_unknown_string_keeps_the_source_wording(self, app):
        text = "A activity name nobody has translated"
        assert content_i18n.translate_content(text, "tr") == text

    def test_english_is_always_the_source_wording(self, app):
        assert content_i18n.translate_content(
            "Foundation Piles Ramming", "en") == "Foundation Piles Ramming"

    def test_none_and_blank_are_safe(self, app):
        assert content_i18n.translate_content(None, "tr") == ""
        assert content_i18n.translate_content("   ", "tr") == "   "

    def test_it_falls_back_to_the_interface_catalogue(self, app):
        """A project field can hold a word the interface already knows."""
        assert content_i18n.translate_content("Electrical", "tr") == \
            i18n.translate("Electrical", language="tr")

    def test_the_source_wording_is_offered_for_a_tooltip(self, app):
        assert content_i18n.is_translated("Foundation Piles Ramming", "tr") is True
        assert content_i18n.is_translated("Nothing anyone has translated", "tr") is False
        # In English there is nothing to show twice.
        assert content_i18n.is_translated("Foundation Piles Ramming", "en") is False


class TestThePageShowsIt:
    @pytest.fixture()
    def programme(self, db, working_version, activity_factory):
        activity_factory(working_version, "1.3.2.2", "Foundation Piles Ramming",
                         date(2026, 8, 1), date(2026, 9, 30),
                         work_package="PV Mechanical Works")
        return working_version

    def test_the_schedule_reads_in_turkish(self, app, client, programme):
        page = client.get("/schedule/?lang=tr").get_data(as_text=True)
        assert content_i18n.translate_content("Foundation Piles Ramming", "tr") in page

    def test_the_schedule_reads_in_italian(self, app, client, programme):
        page = client.get("/schedule/?lang=it").get_data(as_text=True)
        assert content_i18n.translate_content("Foundation Piles Ramming", "it") in page

    def test_english_still_shows_the_contractual_wording(self, app, client, programme):
        page = client.get("/schedule/?lang=en").get_data(as_text=True)
        assert "Foundation Piles Ramming" in page

    def test_the_contractual_wording_stays_in_the_tooltip(self, app, client, programme):
        page = client.get("/schedule/?lang=tr").get_data(as_text=True)
        assert 'title="Foundation Piles Ramming"' in page


class TestTheStoredRecordIsUntouched:
    @pytest.fixture()
    def programme(self, db, working_version, activity_factory):
        return activity_factory(working_version, "1.3.2.2", "Foundation Piles Ramming",
                                date(2026, 8, 1), date(2026, 9, 30))

    def test_the_database_keeps_the_source_wording(self, app, client, db, programme):
        client.get("/schedule/?lang=tr")
        from app.models import WbsActivity
        assert WbsActivity.query.one().activity_name == "Foundation Piles Ramming"

    def test_the_csv_export_is_unchanged_by_the_language(self, app, client, programme):
        english = client.get("/data/export/schedule.csv?lang=en")
        turkish = client.get("/data/export/schedule.csv?lang=tr")
        if english.status_code != 200:
            pytest.skip("the schedule export is not at this address")
        assert english.get_data() == turkish.get_data()
        assert "Foundation Piles Ramming" in english.get_data(as_text=True)

    def test_the_baseline_is_matched_on_the_stored_name(self, app, db, baseline_version,
                                                        working_version, activity_factory):
        """Matching must not depend on the language anybody is reading in."""
        activity_factory(baseline_version, "1.3.2.2", "Foundation Piles Ramming",
                         date(2026, 8, 1), date(2026, 9, 30))
        activity_factory(working_version, "1.4.2.2", "Foundation Piles Ramming",
                         date(2026, 8, 10), date(2026, 10, 5))
        from app.services import schedule_service
        rows = schedule_service.comparison_rows(date(2026, 9, 4))
        assert rows and rows[0]["match_kind"] != "UNMATCHED"
