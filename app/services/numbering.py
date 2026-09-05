"""Deterministic record numbering: BAS-NCR-0001, BAS-PUN-0001, ...

Numbers are allocated from the highest existing number of the same prefix, so
they stay stable and gap-free per register even if a record is edited.
"""
from __future__ import annotations

import re

from app import constants as C
from app.models import Blocker, DailySiteReport, Issue, QualityRecord, Rfi
from app.services import settings

_PATTERN = re.compile(r"(\d+)\s*$")


def _next_index(existing_numbers, prefix):
    highest = 0
    for number in existing_numbers:
        if not number or not str(number).startswith(prefix):
            continue
        match = _PATTERN.search(str(number))
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def _format(prefix, index, width=4):
    return f"{prefix}-{index:0{width}d}"


def next_quality_number(record_type):
    prefix = C.QUALITY_NUMBER_PREFIX.get((record_type or "").upper(), "BAS-QR")
    numbers = [row.record_number for row in
               QualityRecord.query.with_entities(QualityRecord.record_number).all()]
    return _format(prefix, _next_index(numbers, prefix))


def next_rfi_number():
    prefix = "BAS-RFI"
    numbers = [row.rfi_number for row in Rfi.query.with_entities(Rfi.rfi_number).all()]
    return _format(prefix, _next_index(numbers, prefix))


def next_issue_number():
    prefix = "BAS-ACT"
    numbers = [row.issue_number for row in Issue.query.with_entities(Issue.issue_number).all()]
    return _format(prefix, _next_index(numbers, prefix))


def next_blocker_number():
    prefix = "BAS-BLK"
    numbers = [row.blocker_number for row in Blocker.query.with_entities(Blocker.blocker_number).all()]
    return _format(prefix, _next_index(numbers, prefix))


def next_daily_report_number():
    prefix = str(settings.get("report_number_prefix", "BAS-DSR"))
    numbers = [row.report_number for row in
               DailySiteReport.query.with_entities(DailySiteReport.report_number).all()]
    return _format(prefix, _next_index(numbers, prefix))
