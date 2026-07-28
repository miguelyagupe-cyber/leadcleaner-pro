# LeadCleaner Pro — Setup Instructions

## First Time Setup (do this once)

Open your terminal and run these commands one by one:

```bash
# 1. Go into the project folder
cd leadcleaner

# 2. Install required packages
pip3 install flask pandas openpyxl

# 3. Start the app
python3 app.py
```

Then open your browser and go to:
**http://localhost:5000**

---

## Every Time You Want to Use It

```bash
cd leadcleaner
python3 app.py
```

Open browser → **http://localhost:5000**

---

## How to Use

1. Upload your Excel list (.xlsx or .csv)
2. Set the Tax Year you want to target (default: 2022)
3. Click **Process My List**
4. Download your clean list

---

## What the tool does automatically

- ✅ Keeps only leads from the selected tax year
- ✅ Separates prequalified, review, and excluded records with a reason on every row
- ✅ Identifies Tulsa business personal property from the county legal description
- ✅ Removes LLCs, corporations, cannabis businesses, government, and nonprofits
- ✅ Keeps TRUST / TRUSTEE names (family trusts are valid leads)
- ✅ Sorts by Total Due (highest debt first = most motivated sellers)
- ✅ Produces preliminary scores without treating absentee or estate text as proof of death
- ✅ Separates deceased evidence, absentee opportunities, and data-quality review
- ✅ Shows exactly how many records were excluded and why
- ✅ Holds qualification runs for review before any CRM import
- ✅ Builds Leads and Research Queue workspaces
- ✅ Saves pipeline status, priority, research decisions, contacts and notes

## Qualification workbook

Every processing run creates five auditable sheets:

- `Prequalified - Verify`
- `Needs Review`
- `Deceased Research`
- `Absentee Opportunities`
- `Excluded Records`

The current Tulsa source does not include a row-level tax-year column. The
selected year is therefore recorded as import provenance instead of being
misrepresented as a row-level validation.

## Tulsa County Assessor verification

After qualification, the dashboard can verify current ownership in controlled
batches of 25. Each official response is cached in PostgreSQL/SQLite so a
repeated run does not create another county request. The verified export adds:

- current Assessor owner
- official account type
- vacant indicator
- owner-match decision and reason
- source URL and checked timestamp

Request failures, missing pages, and parser failures remain `Not verified`.
They are never converted into exclusions. Commercial or changed-owner records
go to review; only matching Residential/Agricultural records become verified
candidates.

## Death and probate evidence ledger

Research evidence is stored separately from county-data signals. Every item
records its type, outcome, confidence, identity match, source, URL, case number,
subject, event date, notes, and timestamp.

`Confirmed deceased` requires an exact identity match plus confirmed official
probate, death-index, or death-certificate evidence. Obituaries, estate text,
skip-trace mismatches, and probable identity matches can prioritize research,
but cannot confirm death. Confirmed living evidence marks a false positive;
conflicting confirmed evidence remains unresolved.

OSCN pages are saved as evidence links because OSCN itself warns that online
docket information is not an official record. OK2Explore is useful but only
indexes Oklahoma deaths at least five years old, so a missing result is never
treated as evidence that a person is living.

## Approved CRM import

Assessor verification does not write to the CRM automatically. The dashboard
first produces an approval preview with the exact eligible count and total
delinquent debt. Only rows marked `Verified candidate` can be committed.

The commit requires the preview's SHA-256 approval token plus the explicit
confirmation phrase. This prevents a stale preview from approving a changed
workbook. Review, unresolved, and unchecked rows remain outside the CRM.
Repeated commits are idempotent: existing source identities are skipped and
reported instead of duplicated. The current Assessor owner becomes the CRM
owner while the complete source row remains in the audit JSON.

## Calls and daily follow-ups

Every lead supports structured inbound and outbound call logs. Each call stores
the outcome, phone used, duration, notes, timestamp, and next follow-up. The
outcome advances the pipeline automatically:

- `No answer` and `Voicemail left` → Attempted contact
- `Spoke — follow up` → Interested
- `Appointment set` → Appointment scheduled
- `Offer requested` → Negotiation
- `Deal pending` → Contract pending
- `Not interested` → Disqualified

Outcomes that require another action cannot be saved without a follow-up date.
The `Today` workspace lists active follow-ups due today or overdue, oldest
first. Call history remains attached to the lead even when the lead later
changes status.

## Visual acquisition pipeline

The Pipeline workspace groups active opportunities into nine operational
stages from `New` through `Closed`. Each column shows its lead count and total
delinquent debt; cards show owner, property, priority, phone readiness, debt,
and follow-up date.

Daryl can move a card by drag-and-drop or with its accessible stage selector.
Every move uses the normal CRM status update path and is written to the lead's
activity history. Large stages show the highest-priority 50 cards while keeping
the complete stage count and debt total visible.

## Property intelligence workspace

The Properties workspace consolidates repeated county-list appearances into
one property card, using Tax ID as the primary identity and property address
only when Tax ID is unavailable. It keeps the number of source records and tax
years visible, but shows debt and workflow data from the latest operational
record so repeated imports do not inflate opportunity totals.

Each card connects the current owner and Assessor check with active evidence,
call count, pipeline stage, and the full lead workspace. Search and stage
filters operate on the consolidated property list.

## Acquisition intelligence

The Reports workspace turns current CRM facts into an operational acquisition
brief: active delinquent debt, contact readiness, due and overdue follow-ups,
evidence-confirmed deceased owners, pipeline distribution, call outcomes, and
the highest-priority active opportunities.

Recommendations are deterministic responses to recorded gaps such as overdue
follow-ups, missing contact data, and unresolved research. The report uses the
latest CRM record per property so repeated imports do not inflate totals, and
it explicitly avoids estimating revenue, property value, or close probability.

## CRM database

Local development uses SQLite by default and creates its database at:

```text
data/leadcleaner.db
```

To use a different local location, set:

```bash
export CRM_DATABASE=/persistent/path/leadcleaner.db
```

Production uses PostgreSQL automatically when `DATABASE_URL` is present:

```bash
export DATABASE_URL=postgresql://user:password@host/database
```

The application accepts Render's internal PostgreSQL URL directly, creates the
schema idempotently on startup, and verifies connections before reusing them.
Keep the database in the same Render region as the web service and store the
internal URL as a secret environment variable named `DATABASE_URL`.

### Durable processing storage

Processing jobs no longer depend on Render's ephemeral filesystem. PostgreSQL
stores job metadata plus the source, qualification, Assessor-verified, and
skip-trace workbooks. The local `uploads/` and `outputs/` directories are only
a fast, rebuildable cache.

After a restart or deploy, the dashboard, downloads, Assessor batches, approval
preview, and explicit CRM import restore the required artifacts from the
database automatically. This deliberately favors workflow durability for the
current low-frequency list cadence; retention policies or external object
storage can be added when file volume makes that worthwhile.

Each processing run also exposes a persisted workflow state:

```text
Upload received → Qualifying records → Ready for Assessor
→ Assessor in progress → Ready for approval → Imported to CRM
```

The dashboard shows that state and can reopen any recent run. Assessor counts
are cumulative, so verification can continue safely across sessions, devices,
restarts, or deploys. Failed uploads are retained with an error state instead
of disappearing from the operational history.

### Private Render access

The production workspace is locked by default. Configure these Render
environment variables before deploying this version:

```text
APP_LOGIN_EMAIL=daryl@example.com
APP_LOGIN_PASSWORD=<a unique password shared privately with Daryl>
SECRET_KEY=<a long random value>
```

Generate `SECRET_KEY` locally with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Never place those values in GitHub, screenshots, PRs, or application logs.
Authentication uses a 12-hour secure session cookie, CSRF validation on every
mutation, and rate limiting after repeated failed sign-in attempts. The health
endpoint remains public so Render can verify the service without credentials.

The health endpoint confirms which database engine is active without exposing
credentials:

```text
GET /api/health
{"database":"postgresql","status":"ok"}
```

Do not commit or paste the database URL into source code, issues, or chat.

---

## To stop the app

Press `Ctrl + C` in the terminal.
