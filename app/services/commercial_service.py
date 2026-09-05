"""Contractual payment milestones.

Payment percentages come from Schedule 10; the Contract Price comes from the
signed Contract. Amounts are derived from those two registered figures and from
nothing else. A milestone is never marked achieved because physical progress
suggests it: achievement, certification, invoicing and payment are recorded
facts entered by a person.
"""
from __future__ import annotations

from datetime import date

from app import constants as C
from app.models import AcceptanceGate, PaymentMilestone, Project
from app.services import progress, registers, schedule_service
from app.services.calculations import pct, safe_div

PAYMENT_STATUS = [
    "NOT STARTED", "IN PROGRESS", "ACHIEVED", "CERTIFIED", "INVOICED", "PAID", "DISPUTED",
]
PAYMENT_EARNED_STATES = {"ACHIEVED", "CERTIFIED", "INVOICED", "PAID"}
PAYMENT_PAID_STATES = {"PAID"}


def contract_price():
    project = Project.query.first()
    return project.contract_price if project else None


def currency():
    project = Project.query.first()
    return (project.currency if project and project.currency else "EUR")


def milestone_view(milestone, price=None, as_of=None):
    as_of = as_of or date.today()
    price = price if price is not None else contract_price()
    status = (milestone.status or "NOT STARTED").upper()
    target = milestone.forecast_date or milestone.planned_date
    overdue = bool(target and target < as_of and status not in PAYMENT_EARNED_STATES)
    return {
        "milestone": milestone,
        "amount": milestone.amount(price),
        "status": status,
        "derived_status": "OVERDUE" if overdue else status,
        "overdue": overdue,
        "earned": status in PAYMENT_EARNED_STATES,
        "paid": status in PAYMENT_PAID_STATES,
        "target_date": target,
    }


def summary(as_of=None):
    as_of = as_of or date.today()
    price = contract_price()
    rows = PaymentMilestone.query.order_by(
        PaymentMilestone.sequence, PaymentMilestone.milestone_code).all()
    views = [milestone_view(m, price, as_of) for m in rows]

    total_pct = sum(float(m.percentage or 0.0) for m in rows)
    earned_pct = sum(float(v["milestone"].percentage or 0.0) for v in views if v["earned"])
    paid_pct = sum(float(v["milestone"].percentage or 0.0) for v in views if v["paid"])

    roll = progress.rollup(as_of=as_of)
    physical = roll["overall_actual"]

    return {
        "views": views,
        "count": len(rows),
        "contract_price": price,
        "currency": currency(),
        "total_pct": total_pct,
        "schedule_complete": abs(total_pct - 100.0) < 0.01 if rows else False,
        "earned_pct": earned_pct,
        "paid_pct": paid_pct,
        "earned_amount": (price * earned_pct / 100.0) if price is not None else None,
        "paid_amount": (price * paid_pct / 100.0) if price is not None else None,
        "outstanding_amount": (price * (earned_pct - paid_pct) / 100.0)
                              if price is not None else None,
        "overdue": [v for v in views if v["overdue"]],
        "physical_pct": physical,
        # Commercial exposure: money earned running ahead of the works is a
        # contractual risk the project controller must see.
        "commercial_vs_physical": (None if (physical is None) else earned_pct - physical),
        "as_of": as_of,
    }


def delay_damages_exposure(as_of=None):
    """Delay liquidated damages exposure at the contractual rate.

    This reports the contractual arithmetic only. It is not a legal assessment,
    it takes no view on entitlement to an extension of time, and it is shown
    only when the contract parameters and a scheduled PAC date are registered.
    """
    as_of = as_of or date.today()
    project = Project.query.first()
    if project is None or not project.contract_price or not project.delay_lds_pct_per_day:
        return None

    baseline = progress.baseline_version()
    working = progress.current_version()
    if baseline is None:
        return None

    scheduled = _pac_date(baseline)
    forecast = _pac_date(working) if working is not None else None
    if scheduled is None:
        return None

    slip_days = (forecast - scheduled).days if forecast else None
    daily = project.contract_price * project.delay_lds_pct_per_day / 100.0
    cap = (project.contract_price * project.delay_lds_cap_pct / 100.0
           if project.delay_lds_cap_pct else None)
    exposure = None
    capped = False
    if slip_days and slip_days > 0:
        exposure = daily * slip_days
        if cap is not None and exposure > cap:
            exposure, capped = cap, True

    return {
        "scheduled_pac": scheduled,
        "forecast_pac": forecast,
        "slip_days": slip_days,
        "daily_rate": daily,
        "cap": cap,
        "exposure": exposure,
        "capped": capped,
        "cap_days": (cap / daily) if (cap and daily) else None,
        "termination_days": project.delay_termination_days,
        "termination_risk": bool(slip_days and project.delay_termination_days
                                 and slip_days > project.delay_termination_days),
        "currency": currency(),
    }


def _pac_date(version):
    """Latest planned finish of the Provisional Acceptance Certificate milestone."""
    if version is None:
        return None
    candidates = []
    for activity in progress.activities_for(version):
        name = (activity.activity_name or "").upper()
        if "PROVISIONAL ACCEPTANCE CERTIFICATE" in name and activity.is_milestone:
            target = activity.plan_finish or activity.baseline_finish
            if target:
                candidates.append(target)
    if candidates:
        return max(candidates)
    # Fall back to the end of the programme if the milestone is not named.
    _, finish = schedule_service.project_dates(version)
    return finish


def gate_link_options():
    return [(g.gate_code, g.name)
            for g in AcceptanceGate.query.order_by(AcceptanceGate.sequence).all()]
