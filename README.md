# BASSIGNANA EPC CONTROL

**Bassignana Solar 2 — Project & Site Control System**

A project-specific EPC execution, construction monitoring, quality, procurement,
schedule-control and acceptance-readiness application for the Bassignana Solar 2
photovoltaic project (Comune di Bassignana, Provincia di Alessandria, Piemonte).

It replaces the manual spreadsheets, daily progress sheets, site reports, material
tracking, punch lists and schedule comparisons currently used on this project, and
holds them in one register with a single traceable chain:

> Contract → WBS → Schedule → Work Package → Area/Workfront → Daily Actuals →
> Quality/Issues → Materials/Procurement → Testing → Acceptance

The interface is available in **English, Türkçe and Italiano**, switched with the
EN / TR / IT buttons in the header. See section 3a.

It runs on one PC in the site office (sections 2-3), or on one small shared server
so that everyone in the company works on the same record from a browser
(section 3b and `deploy/HOSTING.md`).

---

## 1. Operating constraints

The application runs entirely on one computer you already own -- a PC in the site
office, or a single shared server for the whole company. Either way there is one
program and one database file.

* No cloud hosting, no paid API, no paid database.
* No OpenAI / Claude / Gemini / Azure / AWS / Google Cloud / Firebase / Supabase /
  Vercel / Power BI / Power Apps / Power Automate.
* **No internet connection is required in normal operation.** Bootstrap 5 and
  Chart.js are bundled in `static/vendor/`; nothing is fetched from a CDN.
* No generative AI, chatbot, RAG or machine learning. Every number is produced by
  deterministic arithmetic in `app/services/`, and every report line is a counted
  fact.
* No user accounts. On a site LAN everyone has the same access. A copy published
  on the internet is protected by one shared access password (section 3b); the
  application itself still contacts no external service.

---

## 2. Install

Requires Python 3.10 or newer.

```
pip install -r requirements.txt
```

That is the only install step. `requirements.txt` pulls Flask, Flask-SQLAlchemy,
SQLAlchemy, openpyxl (for `.xlsx` imports), Waitress (the production server) and
pytest. Every one of them is a pure-Python wheel, so the install needs no
compiler and works on a plain Windows or Linux PC.

## 3. Run

**Windows:** double-click **`START.bat`**. It checks Python, installs the
requirements on first run, takes a startup backup of the database and starts the
server. Leave the window open while the system is in use; closing it stops the
server.

**Linux / macOS:** `./start.sh`

Or start it by hand:

```
python run.py
```

The application is served by **Waitress**, a production WSGI server that ships
as a pure-Python wheel — no compiler, no configuration file, no internet
connection at runtime. If Waitress is missing the launcher falls back to the
Flask development server and says so, rather than refusing to start.

```
python run.py --port 5001     use a different port
python run.py --threads 16    more worker threads for a busy site office
python run.py --debug         Flask development server with the reloader
```

The launcher binds to `0.0.0.0` and prints both addresses:

```
  On this computer : http://127.0.0.1:5000/
                     http://localhost:5000/
  On the same Wi-Fi / LAN (phone, tablet, site laptop):
                     http://192.168.x.x:5000/
```

**Local URL:** <http://localhost:5000/>

**LAN access:** open the printed `http://<ip>:5000/` address from any phone,
tablet or laptop on the same Wi-Fi. If the LAN address does not respond, allow
Python through the Windows Firewall for private networks (the first run usually
prompts for this), or run `ipconfig` / `ip addr` to confirm the machine's IPv4
address. Use `python run.py --port 5001` if port 5000 is already taken.

Stop the server with `CTRL+C`. Data survives restarts; it lives in
`data/bassignana.db`.

`http://<host>:5000/healthz` returns a small JSON status document (version,
schema version, record counts, server time) so the site team can confirm the
server is alive without opening the interface.

---

## 3a. Interface languages

The interface is available in three languages, switched with the **EN / TR / IT**
buttons at the top right of every page. The choice is remembered for the rest of
the session and applies to every screen, including the printed reports.

| | |
|---|---|
| English | source language, and the fallback for anything untranslated |
| Türkçe | 1500 entries, dates written `04.09.2026` |
| Italiano | 1500 entries, dates written `04/09/2026` |

Two things deliberately do **not** change with the language:

* **Project data.** Activity names from Schedule 03, document titles, contractor
  names and observation text are contractual content and read exactly as their
  source document does.
* **Stored values.** `IN PROGRESS`, `ACCEPTED`, `NCR` and every other status is
  stored, compared and exported in English; only the on-screen label changes.
  Switching language can therefore never alter what the database holds or what a
  CSV export contains — `tests/test_translations.py` asserts this.

### Editing or extending a translation

Catalogues are plain JSON keyed by the English source string, so a missing entry
degrades to readable English rather than to a raw identifier such as
`nav.dashboard`. Edit the parts under `translations/_parts/` and rebuild:

```
python translations/build.py
```

The build merges the parts, reports any key translated two different ways, and
writes `translations/tr.json` and `translations/it.json`. Restart the server to
load them. No Babel, no `.mo` compilation and no Node.js is involved.

`tests/test_translations.py` fails the build if a template gains user-facing text
that never passes through `t()`, if a placeholder such as `{count}` is lost in
translation, or if any page fails to render in any language.

---

## 3b. Hosting it for the whole company

The same code runs unchanged on a shared server; only environment variables
differ. **`deploy/HOSTING.md`** is the step-by-step guide. In short:

* **GitHub Pages cannot host it.** GitHub Pages serves static files; this is a
  server program with a database that every form writes into.
* **The host needs a persistent disk.** The free tiers of Render, Railway, Koyeb,
  Hugging Face Spaces, Vercel and Netlify wipe their file system on every deploy or
  restart and would discard the project record. The guide recommends
  **PythonAnywhere** (free, no card, persistent disk, HTTPS) for a zero-cost host,
  **Docker on any server** (`Dockerfile`, `docker-compose.yml`; an always-free
  cloud VM works) for a custom domain, or a **Cloudflare Tunnel** from the office
  PC if it stays on anyway.
* **Set `BASSIGNANA_ACCESS_PASSWORD`.** With it set, every page -- photographs
  included -- asks for the shared password once per device (remembered 30 days),
  wrong answers are slowed down and an address is locked out after 8 failures.
  The login screen is in EN / TR / IT like everything else. Set
  `BASSIGNANA_HTTPS=1` and `BASSIGNANA_BEHIND_PROXY=1` behind the platform's
  HTTPS.
* **One live database.** Copy `data/bassignana.db`, `static/uploads/` and
  `project_data/source_documents/` to the host once (guide, section 6), then use
  only the host. Every entry made on the web lands in that file and carries
  forward day by day exactly as on the PC; download a backup from the Backup page
  weekly.
* `BASSIGNANA_DATA_DIR` moves the database, logs, secret key, uploads, backups and
  source documents onto one mounted volume (the Docker image uses `/data`).
  `BASSIGNANA_SQLITE_JOURNAL_MODE=DELETE` is for hosts whose disk is a network
  file system, where SQLite's WAL mode cannot be used. `PORT`, injected by most
  platforms, is honoured when `BASSIGNANA_PORT` is not set. `wsgi.py` exposes
  `application` for gunicorn / uWSGI / PythonAnywhere.

The repository never contains live data, secrets or the contract documents:
`data/`, `backups/`, `static/uploads/`, `project_data/source_documents/` and the
`BASSIGNANA_EPC_SOFTWARE_SOURCE_PACK_v1.0/` folder are ignored by git, so an
update on the host (`git pull`) can never touch the record.

---

## 4. Repository structure

```
Bassignana/
├── START.bat                    Windows: double-click to start (backs up first)
├── wsgi.py                      WSGI entry point for hosting platforms
├── Dockerfile, docker-compose.yml   container image with all live data under /data
├── deploy/                      HOSTING.md, PythonAnywhere WSGI/setup, Caddyfile
├── .github/workflows/tests.yml  pytest on 3.10 and 3.12, Docker build, on every push
├── start.sh                     Linux / macOS launcher
├── run.py                       launcher: binds 0.0.0.0, prints localhost + LAN URLs
├── seed_demo.py                 OPTIONAL demonstration data (separate database)
├── requirements.txt             one pip install
├── pytest.ini
├── README.md
│
├── app/
│   ├── __init__.py              application factory, blueprints, template filters
│   ├── config.py                paths and configuration
│   ├── constants.py             every status list and classification, defined once
│   ├── security.py              persisted secret key, CSRF protection, headers
│   ├── auth.py                  optional shared access password (hosted copies)
│   ├── logging_setup.py         rotating file log in data/logs/
│   ├── extensions.py
│   ├── models/
│   │   ├── core.py              Project, ProjectSetting, SourceDocument, ImportBatch,
│   │   │                        ScheduleVersion, WbsActivity, Area, ActivityQuantity,
│   │   │                        Contractor
│   │   ├── site.py              DailySiteReport, DailyProgress, WorkforceEntry,
│   │   │                        EquipmentEntry, SiteObservation, Blocker, Photo
│   │   ├── commercial.py        ProcurementPackage, Material, Delivery,
│   │   │                        MaterialTransaction, PaymentMilestone
│   │   ├── quality.py           InspectionRequirement, QualityRecord, Rfi, Issue
│   │   └── completion.py        PermitItem, DocumentRegisterItem, AcceptanceGate,
│   │                            AcceptanceGateItem
│   ├── services/                ALL business logic — no arithmetic in routes
│   │   ├── calculations.py      pure, zero-division-safe arithmetic
│   │   ├── status_rules.py      every status classification, in one place
│   │   ├── settings.py          configurable thresholds
│   │   ├── progress.py          progress measurement and weighted rollup
│   │   ├── schedule_service.py  baseline vs current comparison, lookaheads
│   │   ├── forecasting.py       simple production-rate forecast
│   │   ├── commercial_service.py   payment milestones, delay-damages exposure
│   │   ├── schema.py            additive SQLite schema reconciliation
│   │   ├── procurement_service.py  stock, delivery and package status
│   │   ├── registers.py         quality, RFI, blocker, permit, gate queries
│   │   ├── dashboard.py         dashboard assembly and chart payloads
│   │   ├── reports.py           daily and weekly report data
│   │   ├── importers.py         CSV/XLSX preview, validation, commit
│   │   ├── exporters.py         CSV exporters
│   │   ├── data_health.py       DATA REQUIRED reporting
│   │   ├── backup.py            backup, integrity check, restore guidance
│   │   ├── bootstrap.py         first-run structural setup
│   │   └── numbering.py         BAS-NCR-0001, BAS-PUN-0001, ...
│   └── routes/                  thin blueprints, one per navigation section
│
├── templates/                   Jinja2, server-rendered
├── static/
│   ├── vendor/                  Bootstrap 5.3.3 + Chart.js 4.4.4, bundled locally
│   ├── css/app.css              site-control UI: high contrast, large controls, print CSS
│   ├── js/app.js                vanilla JS only
│   └── uploads/                 site photographs and evidence
│
├── project_data/
│   ├── source_documents/        files attached to source-document register entries
│   ├── import_templates/        blank CSV templates
│   └── import_ready/            structured extracts prepared from the Bassignana pack
│
├── translations/
│   ├── tr.json, it.json         built catalogues, keyed by the English source
│   ├── _parts/                  editable source parts, merged by build.py
│   └── build.py                 rebuilds the catalogues and reports conflicts
│
├── data/bassignana.db           live SQLite database
├── data/logs/bassignana.log     rotating application log
├── data/secret_key              generated on first run, never committed
├── backups/                     timestamped database backups
└── tests/                       pytest suite
```

---

## 5. First run — initialisation wizard

On first start the application creates only structure the contract itself defines:
the project record shell, the default thresholds and the four acceptance gates
(A–D) with **no items**. It creates no quantities, dates, areas, permits or
progress.

Open **Project Setup**. The wizard has ten steps and the validation report tells
you exactly what is still missing:

| Step | What to do | Where |
|---|---|---|
| 1 | Project identity from the signed contract | Project Setup → Project identity |
| 2 | Register the authoritative source documents | Project Setup → Source documents |
| 3 | Import the contractual baseline schedule | Schedule & WBS → Versions, then Data Import |
| 4 | Import the current working schedule | as above, into a **separate** version |
| 5 | Import WBS quantities / BOQ | Data Import → Quantities |
| 6 | Create or import areas / workfronts | Project Setup → Areas |
| 7 | Import procurement packages | Data Import → Materials |
| 8 | Import quality / ITP requirements, gate checklists, permits | Data Import |
| 9 | Configure thresholds | Project Setup → Thresholds |
| 10 | Validation report | Project Setup → Validation |

Setup **cannot** be marked complete while a mandatory input is missing. Until
then every page carries a `DATA REQUIRED` banner naming the missing document.

---

## 6. Required Bassignana initialisation files

Register these under **Project Setup → Source documents**, then import the
structured extract where one exists.

| # | Document | Used for | Status in the supplied pack |
|---|---|---|---|
| 1 | Signed EPC Contract | parties, contract reference, obligations | supplied |
| 2 | Schedule 01 — General Report and Site Description | plant master data, quantities | supplied |
| 3 | Schedule 02 — Technical Specification | technical and inspection criteria | supplied |
| 4 | Schedule 03 — Project Timeline | **contractual baseline** WBS and dates | supplied, extracted |
| 5 | Updated programme 27.07.2026 | current working plan | supplied, extracted |
| 6 | Schedule 04 / 04A / 04B / 04C / 04D | testing protocols and the four acceptance gates | supplied, extracted |
| 7 | Autorizzazione Unica DDVA4-733-2024 (08.08.2024) | permit / readiness register | supplied, extracted |
| 8 | Schedule 12 / Schedule 18 — vendor lists | procurement packages and approved vendors | supplied, extracted |
| 9 | IFC layout 26C009-2C020 | earthworks quantities, drawing reference | supplied (earthworks layout only) |
| 10 | **Latest programme as XLSX / CSV / MS Project / Primavera export** | supersedes item 5 | **DATA REQUIRED** |
| 11 | **Approved BOQ / quantity register with WBS, unit and total required quantity** | quantity-based progress and forecasting | **DATA REQUIRED** |
| 12 | Schedule 13B — Scope of Work Q&A rev.2 (25.02.2026) | scope inclusions/exclusions, plant configuration, workfronts | supplied, extracted |
| 13 | Schedule 06 — List of Documents (executive design section) | engineering deliverable register | supplied, extracted (project prefix to reconcile) |
| 14 | Schedule 10 — Payment | payment milestones | supplied, extracted |
| 15 | Site report no. 0 (27.08.2026) | opening observation backlog | supplied, extracted |
| 16 | **Full approved IFC drawing register with revisions** | drawing control | **DATA REQUIRED** |
| 17 | **Approved executive design layout for the final workfront coding** | confirms CT1/CT2/CT3 and adds any sub-field split | **DATA REQUIRED** |
| 18 | **Verified live permit register** | Schedule 05 is a Regione Puglia / Foggia list for a different project | **DO NOT IMPORT — use the Autorizzazione Unica instead** |
| 19 | **Verified executive design document numbering** | Schedule 06 executive design list carries the prefix `01APN`, not a Bassignana code | **RECONCILIATION REQUIRED** |
| 20 | **Approved Bassignana QA/QC Plan and ITPs** | Schedule 17 is a generic template ("PROJECT: XX") | **RECONCILIATION REQUIRED** |
| 21 | **Pull-out test report** | governs the pile embedment depth; recorded as awaited on 27.08.2026 | **DATA REQUIRED** |
| 22 | **Foundation pile count from the executive design** | quantity-based progress on the largest mechanical activity | **DATA REQUIRED** |
| 23 | **Current HSE / PSC / POS set** | Schedule 08 is a placeholder, due 10 working days after the Effective Date | **DATA REQUIRED** |
| 24 | **Approved progress-weight register** | contractual weighted progress | **DATA REQUIRED** |
| 25 | **Current procurement register, PO status, FAT register, delivery forecast** | live procurement control | **DATA REQUIRED** |
| 26 | **Current RFI, NCR and punch list registers** | opening balances | **DATA REQUIRED** |

For schedule data always prefer a structured export. PDFs may be registered as
evidence; the application does not interpret them.

### Files already prepared in `project_data/import_ready/`

These are structured extracts of the supplied source documents. They still pass
through validation and confirmation like any other import — nothing is loaded
automatically.

| File | Rows | Import type | Source |
|---|---|---|---|
| `schedule_contractual_baseline_Schedule03.csv` | 143 | Schedule / WBS | Schedule 03 (contractual baseline) |
| `schedule_current_working_27-07-2026.csv` | 148 | Schedule / WBS | Programme update 27.07.2026, with its reported completion % |
| `quantities_boq_Schedule01_13B_IFC.csv` | 17 | Quantities / BOQ | Schedule 01, corrected by Schedule 13B rev.2, plus drawing 26C009-2C020 |
| `materials_packages_Schedule12-18.csv` | 15 | Materials / Packages | Schedules 12 and 18 |
| `quality_itp_Schedule04_UPI.csv` | 26 | Quality / ITP | Schedule 04 (UPI 820-I1-04) |
| `acceptance_gates_Schedule04A-04D.csv` | 68 | Acceptance gate items | Schedules 04A, 04B, 04C, 04D |
| `permits_Bassignana_AU_2024-08-08.csv` | 23 | Permits / readiness | Autorizzazione Unica DDVA4-733-2024 |
| `documents_Schedule04C_project_documentation.csv` | 285 | Document register | Schedule 04C documentation structure |
| `documents_commissioning_checklist_Schedule04A-04B.csv` | 24 | Document register | Schedule 04A/04B commissioning check list |
| `areas_Schedule13B_layout.csv` | 12 | Areas / Workfronts | Schedule 13B rev.2 and layout 001-25-0096-4001_1 |
| `documents_Schedule06_executive_design.csv` | 64 | Document register | Schedule 06 executive design deliverables |
| `quality_itp_Schedule02_technical.csv` | 15 | Quality / ITP | Schedule 02 technical acceptance criteria |
| `payments_Schedule10.csv` | 9 | Payment Milestones | Schedule 10, priced from the Contract |
| `observations_2026-08-27_site_report.csv` | 10 | Site Observations | Site report no. 0 of 27.08.2026 |

**Import order for the two programmes.** Create the contractual baseline version
first (Schedule & WBS → Versions, type `CONTRACTUAL BASELINE`), import
`schedule_contractual_baseline_Schedule03.csv` into it, then create a second
version of type `CURRENT WORKING` and import
`schedule_current_working_27-07-2026.csv` into that.

**How the baseline is protected.** A new baseline version is created *unlocked*
so its activities can be loaded once. It **locks itself automatically** the moment
that import commits. From then on:

* importing any programme into it is refused;
* it cannot be deleted;
* it cannot also be set as the current working programme;
* unlocking it requires typing `UNLOCK BASELINE` in a confirmation box, and the
  unlock is written into the version's notes with the date.

The working programme therefore never overwrites contractual dates. Contractual
start and finish live only on the baseline version's rows; a working-programme
import writes only current planned dates.

---

## 7. Import templates

Download a blank template from **Data Import**, or write them all to
`project_data/import_templates/` with the button on that page.

| Template | Required columns | All columns |
|---|---|---|
| **Schedule / WBS** | `wbs_code`, `activity_name` | `wbs_code, parent_wbs_code, activity_name, work_package, discipline, contractual_start, contractual_finish, current_planned_start, current_planned_finish, duration_days, milestone, unit, total_required_quantity, progress_weight, current_reported_completion_pct, responsible_party, schedule_version, schedule_status, source_document` |
| **Areas / Workfronts** | `area_code`, `area_name` | `area_code, area_name, description, parent_area, drawing_reference, ifc_revision, active` |
| **Quantities / BOQ** | `item`, `total_quantity` | `wbs_code, area_code, activity_name, item, total_quantity, unit, source, revision, notes` |
| **Materials / Packages** | `package_code`, `package_name` | `package_code, package_name, item, manufacturer, vendor, approved_vendor, unit, contract_quantity, required_quantity, ordered_quantity, planned_delivery, actual_delivery, po_reference, fat_required, source` |
| **Quality / ITP** | `itp_reference` | `wbs_code, work_package, itp_reference, inspection_type, point_type, required_evidence, acceptance_criterion, applicable_specification, discipline, source` |
| **Acceptance gate items** | `gate_code`, `item_name` | `gate_code, item_code, item_name, description, category, responsible_party, target_date, contract_reference, source` |
| **Permits / readiness** | `item_name` | `item_name, authority, responsibility, required_for, required_by_date, issued_date, expiry_date, status, document_reference, blocker_impact, comments, source` |
| **Document register** | `title` | `document_number, title, category, discipline, wbs_code, revision, status, required_date, gate_code, mandatory, folder_path, remarks` |
| **Payment milestones** | `description`, `percentage` | `sequence, milestone_code, description, percentage, wbs_code, gate_code, package_code, planned_date, forecast_date, status, comments, source` |
| **Site observations** | `observation_date`, `observation` | `observation_date, area_code, wbs_code, observation, category, severity, action_required, responsible_party, target_date, status, source` |

Notes that apply to every import:

* Dates accept `YYYY-MM-DD`, `DD/MM/YYYY`, `DD.MM.YYYY` and the Italian
  `lun 11/05/26` form used by the programme exports.
* Numbers accept `1.234,56` and `1,234.56`; percentages may carry a `%`.
* Booleans accept `YES/NO`, `Y/N`, `TRUE/FALSE`, `1/0`, `SI`, `X`.
* Comma and semicolon delimiters, and a UTF-8 BOM, are all handled.
* Every import shows a row-by-row preview with errors, warnings, duplicate
  detection and a create/update/skip classification **before** anything is
  written. Rows with errors are never committed.

---

## 8. What the application does

**Dashboard** — contractual planned %, current-plan %, actual %, variance against
both, today's planned and actual quantity and achievement, workforce, active
equipment, lost hours, open blockers, issues, NCRs, punch items, overdue actions,
procurement warnings, late deliveries, quality holds, critical activities,
upcoming milestones and acceptance readiness. Twelve charts covering the baseline
vs current vs actual curve, progress by work package and workfront, productivity,
workforce, equipment utilisation, lost hours by cause, issues, procurement stages,
quality findings, milestones and gate readiness.

**Schedule & WBS** — multiple schedule versions with type, revision, issue and
effective dates, source document and status. Baseline vs current vs actual in one
table with variance, delay days and classification. 2-week and 4-week lookaheads,
overdue and late-start lists, critical workfronts, recovery comparison.

Because the Bassignana programme renumbered its WBS codes between the contractual
issue and the 27.07.2026 update, activities are matched to the baseline by
**normalised activity name first**, then by WBS code, with a manual override per
activity. Activities with no contractual counterpart are flagged `NO BASELINE`
rather than silently compared against the wrong row.

**Daily Site** — the one screen you use every day. The amber
**Today's site entry** button in the header opens (and, on first use, creates)
the diary for today from anywhere in the application. One page then covers the
whole day in six numbered steps:

1. **Report header** — weather AM/PM, temperature, wind and rainfall, shift,
   working hours, prepared by, contractor, subcontractors.
2. **Work done today** — WBS activity, workfront, planned and actual quantity,
   workers, hours and a free-text explanation. Cumulative quantities are carried
   forward automatically, so the next day starts from where this one finished
   and you never re-enter a running total.
3. **Workforce** by contractor and discipline.
4. **Plant and equipment** with working, idle and breakdown hours.
5. **Deliveries and materials today** — record a delivery (with its DDT, the
   quantity accepted after inspection and any rejection), material issued from
   store to a workfront, material installed in the works, returns and stock
   adjustments. Installed quantities accumulate day by day and each day stays
   separately recoverable.
6. **Site observations** with photographs, plus automatic blocker creation when
   a progress line is marked as affected.

Previous day / next day links move along the diary without going back to the
list.

**Entering a past day.** The diary is not limited to today. The date picker on
the Daily Site register opens any date up to today, the register lists the days
in the period that still have no diary as one-click chips, and opening a date
that has no diary yet creates it. Quantities still carry forward correctly: when
a day is written up out of order, every later day's running total for the
affected activity is recomputed and the confirmation message says how many totals
moved. Future dates are refused, because work cannot be recorded before it
happens. `tests/test_backdating.py` covers this.

**Progress** — quantity-based and weighted/manual measurement, rollup by activity
→ work package → discipline → project, and production by workfront.

**Payment Milestones** — the Schedule 10 milestone schedule priced from the
registered Contract Price, showing value earned, certified, invoiced and paid
against measured physical progress, plus the delay liquidated damages exposure at
the contractual rate.

**Workforce & Plant**, **Procurement & Materials**, **Quality**,
**Issues / Punch / NCR**, **Blockers**, **RFI**, **Permits & Readiness**,
**Testing & Acceptance**, **Reports**, **Data Import / Export**,
**Project Setup**, **Backup** — each with its own register, filters and CSV export.

---

## 9. Control rules

### Schedule classification (thresholds configurable in Project Setup)

| Variance (actual − planned, percentage points) | Classification |
|---|---|
| ≥ −5 | ON TRACK |
| < −5 and ≥ −10 | AT RISK |
| < −10 | CRITICAL |

An incomplete milestone whose planned finish has passed is **CRITICAL**
regardless of its variance.

### Progress weighting

Project progress is **never** a simple mean of activity percentages. It is a
weighted rollup over **leaf activities only**, so a summary line never
double-counts its children. Three bases are selectable:

* `APPROVED WEIGHT` — uses only weights imported from an approved
  progress-weight register.
* `DURATION DERIVED` (default) — weights each leaf by its programme duration.
  Deterministic and transparent, but **not contractual**: the application says so
  in a banner on every affected page and in both reports until an approved
  weight register is imported.
* `QUANTITY` — weights by total required quantity.

### Procurement, stock and acceptance

* `available = accepted receipts + returns + adjustments − issued to workfront`
* Installing material does **not** deduct from store a second time: it left the
  store when it was issued. Installation is recorded as its own movement so the
  installed quantity builds up day by day and remains auditable.
* Stock: `OK` / `LOW STOCK` / `SHORTAGE` (threshold configurable).
* Procurement: `ON TIME` / `AT RISK` / `LATE` / `DELIVERED` / `ACCEPTED` /
  `INSTALLED`. **Delivered ≠ Accepted ≠ Installed** — they are three separate
  quantities and none is inferred from another. Delivered and accepted are
  recalculated from delivery records; installed is a site fact entered explicitly.
* Gate readiness counts only items recorded `ACCEPTED`; `NOT APPLICABLE` items
  leave the denominator. **100% readiness never accepts a gate** — a gate can only
  be recorded `ACCEPTED` by a person, and only when the name of who accepted it is
  supplied.

### Commercial control

* Milestone amounts are `Contract Price x milestone percentage`. Both come from
  registered documents; neither is typed in as a figure. Without a Contract Price
  the module shows `DATA REQUIRED` rather than a zero.
* Value earned is compared against measured physical progress so the position is
  visible. It is a comparison of two recorded figures, not an assessment of
  entitlement.
* Delay liquidated damages exposure is
  `Contract Price x rate per day x slip days`, capped at the contractual cap,
  where the slip is the difference between the Provisional Acceptance milestone
  in the contractual baseline and in the current working programme. It reports
  contractual arithmetic only; it takes no view on entitlement to an extension of
  time and is not a legal assessment.
* Achievement, certification, invoicing and payment are recorded by a person. No
  milestone is ever marked achieved because physical progress suggests it.

### Adverse weather

The EPC Contract grants an extension of time for adverse weather only where wind
exceeds 30 m/s or rainfall exceeds 10 mm/h, measured by calibrated site
instrumentation, and deems the entitlement waived if that instrumentation is not
installed. The daily diary therefore records the measured maximum wind and
rainfall on every day, and a day with no measurement can never satisfy the test —
the application says the measurement is missing rather than assuming the weather
was acceptable. Both thresholds are configurable in Project Setup.

### Forecasting

`remaining = total required − completed`; `rate` = mean actual production over the
**active working days** in the last 7 or 14 calendar days (days with no production
are excluded so an idle day cannot deflate the rate);
`working days remaining = remaining ÷ rate`. It is labelled
**Simple production-rate forecast** everywhere, and reports
*"Not enough production history to calculate forecast."* below the configured
minimum. It is never presented as a contractual date.

---

## 10. Data-integrity guarantees

The application will not:

* overwrite a contractual baseline with an updated working schedule — the
  baseline is a separate, locked schedule version and an updated programme always
  creates a new one;
* silently replace an approved revision — registering a superseding document
  marks the prior one `SUPERSEDED` and keeps it;
* accept a `DRAFT`, `REFERENCE ONLY`, `SUPERSEDED` or `REQUIRES RECONCILIATION`
  document as an import source;
* invent a missing quantity, area, date or milestone — it shows `DATA REQUIRED`
  and names the source document that would supply it;
* mark a contractual acceptance gate complete by itself;
* treat delivered equipment as accepted or installed;
* treat a punch item as an NCR — reclassification is explicit, is written into the
  record's comments and issues a new record number;
* calculate overall progress as a simple mean;
* mix demonstration data with live records — `seed_demo.py` writes to a
  **separate database** (`data/bassignana_demo.db`) and never touches
  `data/bassignana.db`.

Known source conflicts, each flagged in the prepared import files rather than
resolved silently:

* **Transformer substations.** Schedule 01 (March 2022) describes six 1250 kVA
  transformers and eight sub-fields each served by a pair of MV/LV cabins.
  Schedule 13B rev.2 (25.02.2026) — the later document — confirms **three**
  transformer substations `CT1`, `CT2`, `CT3` plus one technical room. The BOQ
  entry follows Schedule 13B and records that it supersedes Schedule 01.
* **Inverter rating.** Schedule 01 states 37 string inverters of 185 kW in §6.1
  but a 105 kW inverter in the §5 data table → `SOURCE RECONCILIATION REQUIRED`.
* **Scope boundary.** The Cabina di Consegna is expressly excluded from the
  Contractor's scope (Schedule 13B rev.2 items 9 and 10); the Opere di Rete are
  executed by E-Distribuzione. It is registered as a workfront with a zero
  quantity so the exclusion is visible rather than absent.
* **Client registered office.** The Autorizzazione Unica (2024) gives Parma; the
  signed Contract (2026) gives Palermo. Both are correct at their date; use the
  Contract for contractual correspondence.
* **Schedule 05 (permits)** is a Regione Puglia / Provincia di Foggia list for a
  different project → **do not import**. The permit register is built from the
  actual Autorizzazione Unica instead.
* **Schedule 06 (documents).** The `DOCUMENTI PROGETTO AUTORIZZATO` section
  belongs to another project (`G29SDU8`, Regione Puglia) and is excluded. The
  `DOCUMENTI PROGETTO ESECUTIVO` section is a clean executive-design deliverable
  register and is provided for import, flagged because its numbers carry the
  prefix `01APN` rather than a Bassignana project code.
* **Schedule 17 (QA plan)** is a generic template (`PROJECT: XX`) → reference
  only, never the approved project plan.
* **Schedule 02 §4.4.1** states a performance commitment of 86.4% in year one,
  86.0% in year two and 80.4% in year three. The year-three figure looks like a
  transcription error in the source but is recorded exactly as written.

---

## 10a. Production operation

**Server.** Waitress, a production WSGI server. The Flask development server is
used only with `--debug`.

**Concurrency and durability.** SQLite runs in WAL mode with a 10-second busy
timeout and foreign keys enforced, so the site team can read while somebody else
is writing.

**Schema changes.** On every start the application reconciles the live database
against the models: it creates missing tables, adds missing columns and indexes,
and records a schema version. Every operation is additive — no column is ever
dropped or retyped — so starting a newer build against an older database cannot
lose data. Alembic is deliberately not used: it would add a dependency, a
migrations directory and a command-line step to a system that has to install with
one `pip install` and start with one `python run.py`.

**Sessions and CSRF.** The secret key is generated on first run and persisted in
`data/secret_key`, so a site tablet does not lose its session and a half-finished
import preview is not discarded on restart. Every posting form is protected by a
CSRF token that is injected into the response, so a form added to a template later
cannot be left unprotected by omission. There are no user accounts; a hosted
copy requires the shared access password described in section 3b.

**Logging.** Everything of consequence is written to `data/logs/bassignana.log`,
rotating at 2 MB with five generations kept. Unhandled errors are logged with a
traceback and the transaction is rolled back.

**Health check.** `GET /healthz` returns version, schema version, record counts
and server time as JSON.

**Housekeeping.** Import files that are previewed but never confirmed are deleted
after 24 hours, so the workspace cannot grow without bound.

---

## 11. Reports

**Daily Site Report** (`Reports → Daily`) — headed *BASSIGNANA SOLAR 2 / DAILY SITE
REPORT*, with report details, summary, contractors and workforce by discipline,
plant, planned vs actual by WBS and workfront, cumulative progress, deliveries and
shortages, inspections and NCR/punch status, blockers and lost hours by cause, RFI
status, site observations, critical actions, upcoming work, photographs and a
signature block.

**Weekly Project Control Report** (`Reports → Weekly`) — overall progress, weekly
plan vs actual, daily productivity, workforce trend, late and critical activities,
2-week lookahead, milestones, procurement, quality, RFIs, blockers, permits,
upcoming tests, acceptance readiness and a ranked list of top actions for next
week.

Every summary line is a counted fact — number of active workfronts, daily
achievement, activities below target, open critical blockers, late procurement
items, overdue NCR/punch items, the largest cause of lost hours, the next
milestones. There is no generated prose.

Use the **Print / Save as PDF** button. The print stylesheet removes navigation,
charts and buttons and formats the sheet for A4.

---

## 12. CSV exports

Available from **Data Import / Export** and from each register page (where the
page's current filters are preserved):

WBS/Schedule · Daily Progress · Workforce · Equipment · Blockers ·
Issues/Actions · Quality (all types, or NCR / Punch separately) · RFIs ·
Procurement packages · Materials · Deliveries · Permits/Readiness ·
Testing/Acceptance register · Document register · Areas · Quantities/BOQ ·
ITP requirements · Site observations · Source document register.

---

## 13. Backup and restore

**Settings → Backup → Back up the database now** writes
`backups/bassignana_YYYY-MM-DD_HHMMSS.db` using SQLite's own backup API, so the
copy is consistent even while the application is running, then runs
`PRAGMA integrity_check` on it. Backups can be downloaded, re-verified at any
time, and deleted only after typing the exact file name.

### Restore

1. Stop the application (close the terminal running `python run.py`).
2. Open `backups/` and pick the backup to restore.
3. Rename the current `data/bassignana.db` to
   `data/bassignana_before_restore.db` so you can go back.
4. Copy the chosen backup into `data/` and rename it `bassignana.db`.
5. Copy back the matching `static/uploads/` folder if you are restoring onto a
   different machine — photographs and evidence are stored there, **not** in the
   database.
6. Copy back `project_data/source_documents/` so registered documents remain
   reachable from their register entries.
7. Start again with `python run.py` and check the Dashboard and Data Import
   history.

### Moving to another machine

Copy the whole project folder, or at minimum `data/bassignana.db`,
`static/uploads/`, `project_data/` and `backups/`. Install Python 3.10+, run
`pip install -r requirements.txt`, then `python run.py`.

**A database backup alone is not the whole record.** Always take
`static/uploads/` and `project_data/source_documents/` with it.

---

## 14. Optional demonstration data

```
python seed_demo.py            build the demo database
python seed_demo.py --reset    delete and rebuild it
python seed_demo.py --run      build it and serve it on port 5001
```

Everything it creates is prefixed `DEMO` and lives in
`data/bassignana_demo.db`. The live database is never touched. Real project data
must always arrive through Project Setup / Data Import.

---

## 15. Tests

```
python -m pytest
```

512 tests covering:

| Area | Tests |
|---|---|
| Achievement, productivity, zero-division safety | `tests/test_calculations.py` |
| Weighted project progress (proved not to be a mean) | `test_calculations.py`, `test_progress_and_forecast.py` |
| Schedule variance and ON TRACK / AT RISK / CRITICAL thresholds | `tests/test_schedule_control.py` |
| Contractual baseline vs current schedule separation | `tests/test_schedule_control.py` |
| Baseline matching across renumbered WBS codes | `tests/test_schedule_control.py` |
| Overdue milestone classification | `tests/test_schedule_control.py` |
| Lookaheads, overdue, late start, recovery comparison | `tests/test_schedule_control.py` |
| Blocker lost-hour and lost-man-hour calculation | `tests/test_registers.py` |
| Stock calculation and LOW STOCK / SHORTAGE | `tests/test_registers.py` |
| Procurement late status; delivered ≠ accepted ≠ installed | `tests/test_registers.py` |
| NCR / punch overdue detection and independent numbering | `tests/test_registers.py` |
| Acceptance-gate readiness and the human-decision rule | `tests/test_registers.py` |
| Forecast calculation and insufficient-history handling | `tests/test_progress_and_forecast.py` |
| Schedule import validation, duplicates, lock protection | `tests/test_imports.py` |
| Document precedence and supersession | `tests/test_imports.py` |
| Prepared Bassignana files validate without errors | `tests/test_imports.py` |
| Daily report and weekly report assembly | `tests/test_reports_exports_backup.py` |
| CSV exports | `tests/test_reports_exports_backup.py` |
| Backup creation, integrity check and restore guidance | `tests/test_reports_exports_backup.py` |
| Web surface, including gate-acceptance and reclassification guards | `tests/test_reports_exports_backup.py` |
| Today's entry button, day navigation and carry-forward | `tests/test_daily_entry.py` |
| Deliveries and material movements recorded from the diary | `tests/test_daily_entry.py` |
| Installed quantity accumulating day by day without double-deducting stock | `tests/test_daily_entry.py` |
| CSRF enforcement, token injection and security headers | `tests/test_production.py` |
| Additive schema reconciliation and data survival | `tests/test_production.py` |
| Payment milestones, earned/paid value and the physical comparison | `tests/test_production.py` |
| Delay liquidated damages exposure, cap and termination threshold | `tests/test_production.py` |
| Adverse-weather thresholds and the missing-measurement rule | `tests/test_production.py` |
| Site observation backlog import | `tests/test_production.py` |
| Import workspace housekeeping | `tests/test_production.py` |
| Recovered source data, including the superseded transformer count | `tests/test_production.py` |
| Opening a past day, and refusing a future one | `tests/test_backdating.py` |
| Cumulative totals rebased when a day is entered out of order | `tests/test_backdating.py` |
| Catalogue coverage, placeholder survival and duplicate detection | `tests/test_translations.py` |
| Every page rendering in English, Turkish and Italian | `tests/test_translations.py` |
| Language never altering stored values or CSV exports | `tests/test_translations.py` |
| No template text or confirmation dialog escaping translation | `tests/test_translations.py` |
| Shared access password: gate, lockout, safe redirects, translated login | `tests/test_access.py` |
| Relocatable data folders, uploads route, journal mode, platform port | `tests/test_hosting.py` |

Tests run against an in-memory database and never touch `data/bassignana.db`.

---

## 16. Deferred

* No per-user accounts or permissions. A hosted copy uses one shared password
  (section 3b); everyone who has it has the same access.
* No PDF or OCR interpretation. PDFs are registered as evidence; schedule data
  must arrive as CSV/XLSX. The two Bassignana programmes have already been
  extracted into `project_data/import_ready/`.
* No HSE compliance workflow beyond the observation category and the permit
  register — the contractual Schedule 08 is a placeholder (the HSE Plan is due
  within 10 working days of the Effective Date) and the approved Bassignana
  HSE/PSC/POS set has not been supplied.
* The two daily site reports in the source pack are image-only PDFs. The
  27.08.2026 report has been transcribed into an importable observation backlog;
  the 01.09.2026 report contains no extractable text and must be re-entered or
  supplied in a text format.
* No cost control or earned-value cost module. Payment milestones and delay
  damages exposure are tracked; actual cost, committed cost and CPI are not,
  because no cost ledger has been supplied (Schedule 13C is an image-only PDF).
* Photographs are stored as uploaded (no resizing or EXIF processing).
