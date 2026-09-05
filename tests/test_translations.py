"""The English / Turkish / Italian interface.

Two properties matter more than the wording itself:

* every page must render in every language, and
* changing language must never change what the database holds. Statuses,
  WBS codes and exported CSVs stay in the contractual English.
"""
from __future__ import annotations

import ast
import json
import pathlib
import re

import pytest

from app import i18n
from app.models import DailySiteReport, QualityRecord

ROOT = pathlib.Path(__file__).resolve().parent.parent
CATALOGUE_DIR = ROOT / "translations"

def html_pages(app):
    """Every parameterless HTML page, taken from the routing table itself.

    Discovering the pages rather than listing them means a new screen is
    covered by the language sweep the day it is added.
    """
    skip = (".csv", ".json", "/healthz", "/static")
    return sorted({rule.rule for rule in app.url_map.iter_rules()
                   if "GET" in rule.methods
                   and "<" not in rule.rule
                   and not rule.rule.endswith(skip[:2])
                   and not rule.rule.startswith("/static")
                   and rule.rule != "/healthz"})


#: A representative page from each blueprint, for the parameterised sweep.
PAGES = [
    "/", "/schedule/", "/schedule/versions", "/schedule/lookahead",
    "/schedule/recovery", "/progress/", "/progress/forecast",
    "/progress/quantities", "/daily/", "/daily/new", "/daily/observations",
    "/quality/", "/quality/requirements", "/issues/", "/procurement/",
    "/procurement/materials", "/procurement/deliveries", "/acceptance/",
    "/acceptance/documents", "/permits/", "/rfi/", "/blockers/",
    "/blockers/analysis", "/setup/documents", "/workforce/",
    "/workforce/contractors", "/commercial/", "/reports/", "/reports/daily",
    "/reports/weekly", "/setup/", "/setup/project", "/setup/areas",
    "/setup/thresholds", "/setup/validation", "/data/", "/backup/",
]


class TestCatalogues:
    def test_every_language_has_a_catalogue(self):
        for code in i18n.LANGUAGES:
            if code == i18n.DEFAULT_LANGUAGE:
                continue
            assert (CATALOGUE_DIR / f"{code}.json").exists()

    def test_the_catalogues_cover_the_same_source_strings(self):
        tr = json.loads((CATALOGUE_DIR / "tr.json").read_text(encoding="utf-8"))
        it = json.loads((CATALOGUE_DIR / "it.json").read_text(encoding="utf-8"))
        assert set(tr) == set(it)
        assert len(tr) > 1000

    def test_no_entry_is_left_as_its_english_source(self):
        """An untranslated entry is a copy of the key and would be invisible."""
        for code in ("tr", "it"):
            catalogue = json.loads((CATALOGUE_DIR / f"{code}.json").read_text(encoding="utf-8"))
            copied = [k for k, v in catalogue.items()
                      # Codes and acronyms are legitimately identical.
                      if k == v and len(k) > 24]
            assert copied == [], f"{code}: {copied[:5]}"

    def test_placeholders_survive_translation(self):
        """`{count}` must reach .format() with the same names in every language."""
        for code in ("tr", "it"):
            catalogue = json.loads((CATALOGUE_DIR / f"{code}.json").read_text(encoding="utf-8"))
            for source, translated in catalogue.items():
                assert (set(re.findall(r"{(\w+)", source))
                        == set(re.findall(r"{(\w+)", translated))), f"{code}: {source}"

    def test_every_python_message_is_in_the_catalogues(self):
        """Flash messages are raised in Python, so they need catalogue entries."""
        keys = set()
        for path in (ROOT / "app").rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (isinstance(node, ast.Call)
                        and getattr(node.func, "id", None) == "t" and node.args):
                    first = node.args[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        if first.value.strip():
                            keys.add(first.value)
        assert keys, "no translatable Python strings were found"
        for code in ("tr", "it"):
            catalogue = json.loads((CATALOGUE_DIR / f"{code}.json").read_text(encoding="utf-8"))
            missing = sorted(k for k in keys if k not in catalogue)
            assert missing == [], f"{code}: {missing[:5]}"


class TestTheSwitcher:
    @pytest.mark.parametrize("code", ["en", "tr", "it"])
    def test_the_switcher_offers_every_language(self, app, client, code):
        page = client.get(f"/?lang={code}").get_data(as_text=True)
        for other in i18n.LANGUAGES:
            assert f"lang={other}" in page

    def test_the_choice_sticks_for_the_next_request(self, app, client):
        client.get("/?lang=it")
        page = client.get("/schedule/").get_data(as_text=True)
        assert 'lang="it"' in page

    def test_an_unknown_language_falls_back_to_english(self, app, client):
        page = client.get("/?lang=zz").get_data(as_text=True)
        assert 'lang="en"' in page

    def test_the_switcher_keeps_the_current_page_and_its_filters(self, app, client):
        page = client.get("/daily/?from=2026-08-01&to=2026-09-04").get_data(as_text=True)
        assert "from=2026-08-01" in page and "lang=tr" in page

    def test_the_html_lang_attribute_follows_the_choice(self, app, client):
        for code in i18n.LANGUAGES:
            page = client.get(f"/?lang={code}").get_data(as_text=True)
            assert f'<html lang="{code}"' in page


class TestEveryPageRendersInEveryLanguage:
    @pytest.mark.parametrize("path", PAGES)
    @pytest.mark.parametrize("code", ["en", "tr", "it"])
    def test_the_page_renders(self, app, client, path, code):
        response = client.get(f"{path}?lang={code}", follow_redirects=True)
        assert response.status_code == 200, f"{path} [{code}]"

    @pytest.mark.parametrize("code", ["tr", "it"])
    def test_every_route_in_the_routing_table_renders(self, app, client, code):
        failures = []
        for path in html_pages(app):
            response = client.get(f"{path}?lang={code}", follow_redirects=True)
            if response.status_code != 200:
                failures.append((path, response.status_code))
        assert failures == []

    @pytest.mark.parametrize("code", ["tr", "it"])
    def test_no_untranslated_string_reaches_a_rendered_page(self, app, client, code):
        i18n._MISSING[code].clear()
        for path in html_pages(app):
            client.get(f"{path}?lang={code}", follow_redirects=True)
        assert sorted(i18n._MISSING[code]) == []

    @pytest.mark.parametrize("code", ["tr", "it"])
    def test_the_daily_entry_screen_renders(self, app, client, code):
        response = client.get(f"/daily/today?lang={code}", follow_redirects=True)
        assert response.status_code == 200


class TestTranslationDoesNotTouchTheData:
    def test_a_record_created_in_turkish_stores_english_statuses(self, app, client, db):
        client.post("/issues/ncr/new?lang=tr", data={
            "title": "Torque below specification",
            "description": "Row 12 fasteners under-torqued.",
            "severity": "MAJOR"}, follow_redirects=True)
        row = QualityRecord.query.one()
        assert row.record_type == "NCR"
        assert row.status == "OPEN"
        assert row.severity == "MAJOR"

    def test_a_status_badge_shows_a_translated_label_over_a_stored_value(
            self, app, client, db):
        client.post("/issues/ncr/new", data={"title": "Torque below specification",
                                             "severity": "MAJOR"},
                    follow_redirects=True)
        row = QualityRecord.query.one()
        italian = client.get("/issues/?lang=it").get_data(as_text=True)
        english = client.get("/issues/?lang=en").get_data(as_text=True)
        assert i18n.translate("OPEN", language="it") in italian
        assert ">OPEN<" in english
        # The register shows a translated label; the row itself is untouched.
        assert row.status == "OPEN"

    def test_the_report_number_is_language_independent(self, app, client):
        client.get("/daily/today?lang=it", follow_redirects=True)
        report = DailySiteReport.query.one()
        assert report.report_number.startswith("BAS-DSR-")

    def test_a_csv_export_stays_english(self, app, client, db, daily_report):
        english = client.get("/daily/export.csv?lang=en").get_data(as_text=True)
        turkish = client.get("/daily/export.csv?lang=tr").get_data(as_text=True)
        assert english == turkish
        assert "text/csv" in client.get("/daily/export.csv").headers["Content-Type"]


class TestTheTranslateFunction:
    def test_a_known_string_is_translated(self, app):
        with app.test_request_context("/?lang=tr"):
            i18n.resolve_language()
            assert i18n.translate("Dashboard", language="tr") != "Dashboard"

    def test_an_unknown_string_degrades_to_english(self, app):
        assert i18n.translate("A phrase nobody has translated", language="tr") == \
            "A phrase nobody has translated"

    def test_placeholders_are_substituted_after_lookup(self, app):
        result = i18n.translate("{count} later cumulative total(s) were rebased.",
                                language="it", count=3)
        assert "3" in result and "{count}" not in result

    def test_a_bad_placeholder_never_raises(self, app):
        assert i18n.translate("{count} later cumulative total(s) were rebased.",
                              language="it", wrong=3)

    def test_none_becomes_an_empty_string(self, app):
        assert i18n.translate(None) == ""

    def test_dates_follow_the_language(self, app):
        from datetime import date
        assert i18n.format_date(date(2026, 9, 4), "tr") == "04.09.2026"
        assert i18n.format_date(date(2026, 9, 4), "it") == "04/09/2026"
        assert i18n.format_date(None, "en") == "-"


class TestNoUntranslatedTextInTemplates:
    """A guard against new hard-coded English.

    The masks blank out Jinja, scripts, styles and comments, so what is left is
    text a user would actually read. Anything with three or more words that
    never passed through t() is a regression.
    """

    ATTRIBUTES = ("placeholder", "title", "data-confirm", "aria-label", "alt")

    @staticmethod
    def _blank(match):
        # Spaces rather than deletion, so reported line numbers stay usable.
        return re.sub(r"[^\n]", " ", match.group(0))

    def _mask(self, source):
        masked = source
        for pattern in (r"{#.*?#}", r"{%.*?%}", r"{{.*?}}",
                        r"<script\b.*?</script>", r"<style\b.*?</style>",
                        r"<!--.*?-->"):
            masked = re.sub(pattern, self._blank, masked, flags=re.S | re.I)
        return masked

    #: Settings keys and unit symbols are deliberately identical in every language.
    LITERAL = re.compile(
        r"^(?:[-+*/=<>%&|.,;:()\[\]#0-9\s]+"
        r"|[A-Z0-9_./-]{1,12}"
        r"|variance_[a-z_]+"
        r"|m/s|mm/h|kWp|MWp|kW|kV|h|no|m2|m3|EUR|CSV|XLSX|PDF|ITP|NCR|RFI|FAT|DC|AC"
        r")$")

    def _text_nodes(self, path):
        tagless = re.sub(r"<[^>]*>", self._blank,
                         self._mask(path.read_text(encoding="utf-8")), flags=re.S)
        for lineno, line in enumerate(tagless.splitlines(), 1):
            chunk = re.sub(r"&[a-z]+;", " ", line)
            # Settings keys are shown verbatim, and a line may carry several.
            chunk = re.sub(r"variance_[a-z_]+", " ", chunk).strip()
            if not chunk or self.LITERAL.match(chunk) or not re.search(r"[a-z]{2}", chunk):
                continue
            yield lineno, chunk

    def test_no_prose_escapes_translation(self):
        """Paragraphs and sentences."""
        findings = [f"{path.name}:{lineno} {chunk[:70]}"
                    for path in sorted((ROOT / "templates").rglob("*.html"))
                    for lineno, chunk in self._text_nodes(path)
                    if len(chunk.split()) >= 3]
        assert findings == [], findings[:8]

    def test_no_short_label_escapes_translation(self):
        """Table totals, option labels and headings are one or two words."""
        findings = [f"{path.name}:{lineno} {chunk[:70]}"
                    for path in sorted((ROOT / "templates").rglob("*.html"))
                    for lineno, chunk in self._text_nodes(path)
                    if len(chunk.split()) < 3]
        assert findings == [], findings[:8]

    def test_every_page_title_is_translatable(self):
        pattern = re.compile(r"{% block title %}(.*?){% endblock %}", re.S)
        findings = []
        for path in sorted((ROOT / "templates").rglob("*.html")):
            if path.name == "base.html":
                continue
            for match in pattern.finditer(path.read_text(encoding="utf-8")):
                body = match.group(1)
                # Strip the expressions, then check what literal text is left.
                literal = re.sub(r"{{.*?}}", " ", body, flags=re.S).strip()
                if literal and re.search(r"[A-Za-z]{2}", literal):
                    findings.append(f"{path.name}: {literal[:60]}")
        assert findings == [], findings[:8]

    def test_no_user_facing_attribute_escapes_translation(self):
        findings = []
        pattern = re.compile(r'\b(' + '|'.join(self.ATTRIBUTES) + r')\s*=\s*"([^"{}]{4,})"')
        for path in sorted((ROOT / "templates").rglob("*.html")):
            for match in pattern.finditer(self._mask(path.read_text(encoding="utf-8"))):
                value = match.group(2).strip()
                if len(value.split()) >= 2 and re.search(r"[a-z]{3}", value):
                    findings.append(f"{path.name}: {match.group(1)}={value[:60]}")
        assert findings == [], findings[:8]
