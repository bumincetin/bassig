"""First-run structural setup.

This creates only structure that the contract itself defines -- the project
record shell, default thresholds and the four acceptance gates. It creates no
quantities, no dates, no areas, no permits and no progress. All project data
must arrive through Project Setup / Data Import.
"""
from __future__ import annotations

from app import constants as C
from app.extensions import db
from app.models import AcceptanceGate, Project
from app.services import settings

#: Identity taken from the signed contract package. These are project
#: identifiers, not quantities or progress, and remain editable in Project Setup.
PROJECT_DEFAULTS = {
    "name": "Bassignana Solar 2",
    "subtitle": "Project & Site Control System",
    "plant_name": "Impianto Fotovoltaico Fornace di Bassignana",
    "country": "Italy",
}


def ensure_project():
    project = Project.query.first()
    created = False
    if project is None:
        project = Project(**PROJECT_DEFAULTS)
        db.session.add(project)
        created = True
    return project, created


def ensure_gates():
    """Create the four contractual acceptance gates with no items."""
    created = 0
    for index, (code, name, reference) in enumerate(C.GATES, start=1):
        gate = AcceptanceGate.query.filter_by(gate_code=code).first()
        if gate is None:
            gate = AcceptanceGate(
                gate_code=code,
                name=name,
                sequence=index,
                contract_reference=reference,
                description=(
                    f"Gate {code} prerequisites are defined by {reference}. "
                    "Import the gate checklist in Data Import, then record status and "
                    "evidence per item. Formal acceptance is always recorded by a person."
                ),
                status="NOT STARTED",
            )
            db.session.add(gate)
            created += 1
    return created


def initialise():
    """Idempotent first-run initialisation."""
    project, project_created = ensure_project()
    gates_created = ensure_gates()
    settings_created = settings.ensure_defaults()
    db.session.commit()
    return {
        "project_created": project_created,
        "gates_created": gates_created,
        "settings_created": settings_created,
        "project": project,
    }
