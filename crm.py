import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

import pandas as pd


CRM_STATUSES = (
    'new',
    'research_needed',
    'contact_ready',
    'attempted_contact',
    'interested',
    'appointment_scheduled',
    'negotiation',
    'contract_pending',
    'closed',
    'disqualified',
)

CRM_PRIORITIES = ('urgent', 'high', 'medium', 'normal')
RESEARCH_STATUSES = ('unreviewed', 'in_progress', 'verified', 'rejected')


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class CRMRepository:
    def __init__(self, database_path):
        self.database_path = database_path

    @contextmanager
    def connect(self):
        directory = os.path.dirname(os.path.abspath(self.database_path))
        os.makedirs(directory, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self):
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS import_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL UNIQUE,
                    source_filename TEXT NOT NULL,
                    output_filename TEXT NOT NULL,
                    tax_year INTEGER NOT NULL,
                    stats_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS leads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tax_id TEXT,
                    owner_name TEXT NOT NULL,
                    property_address TEXT,
                    property_city TEXT,
                    mailing_address TEXT,
                    mailing_city TEXT,
                    mailing_state TEXT,
                    zip_code TEXT,
                    total_due REAL NOT NULL DEFAULT 0,
                    tax_year INTEGER NOT NULL,
                    deceased_flag INTEGER NOT NULL DEFAULT 0,
                    mailing_signal TEXT,
                    status TEXT NOT NULL DEFAULT 'new',
                    priority TEXT NOT NULL DEFAULT 'normal',
                    research_status TEXT NOT NULL DEFAULT 'unreviewed',
                    phone TEXT,
                    email TEXT,
                    next_follow_up TEXT,
                    last_contacted_at TEXT,
                    source_job_id TEXT NOT NULL,
                    source_data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source_job_id, tax_id, owner_name, property_address),
                    FOREIGN KEY(source_job_id) REFERENCES import_runs(job_id)
                );

                CREATE TABLE IF NOT EXISTS lead_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lead_id INTEGER NOT NULL,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS lead_activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    lead_id INTEGER NOT NULL,
                    activity_type TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
                CREATE INDEX IF NOT EXISTS idx_leads_priority ON leads(priority);
                CREATE INDEX IF NOT EXISTS idx_leads_research ON leads(research_status);
                CREATE INDEX IF NOT EXISTS idx_leads_owner ON leads(owner_name);
                CREATE INDEX IF NOT EXISTS idx_leads_tax_id ON leads(tax_id);
                CREATE INDEX IF NOT EXISTS idx_leads_source_job ON leads(source_job_id);
                """
            )

    @staticmethod
    def _value(row, column, default=''):
        if not column:
            return default
        value = row.get(column, default)
        if pd.isna(value):
            return default
        return value

    @staticmethod
    def _record_json(row):
        record = {}
        for key, value in row.items():
            if pd.isna(value):
                record[str(key)] = None
            elif hasattr(value, 'item'):
                record[str(key)] = value.item()
            else:
                record[str(key)] = value
        return json.dumps(record, default=str)

    @staticmethod
    def _priority(deceased_flag, mailing_signal, total_due):
        if deceased_flag:
            return 'high'
        if mailing_signal == 'Strong':
            return 'high'
        if total_due >= 10000:
            return 'high'
        if mailing_signal == 'Weak' or total_due >= 5000:
            return 'medium'
        return 'normal'

    def import_leads(self, dataframe, job, columns):
        now = utc_now()
        imported = 0
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO import_runs (
                    job_id, source_filename, output_filename, tax_year,
                    stats_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    output_filename = excluded.output_filename,
                    stats_json = excluded.stats_json
                """,
                (
                    job['uid'],
                    job['source_filename'],
                    job['output_filename'],
                    job['tax_year'],
                    json.dumps(job['stats']),
                    now,
                ),
            )

            for _, row in dataframe.iterrows():
                owner_name = str(self._value(row, columns.get('owner_name'))).strip()
                if not owner_name:
                    continue

                property_address = ' '.join(
                    str(part).strip()
                    for part in (
                        self._value(row, columns.get('street_number')),
                        self._value(row, columns.get('street_name')),
                        self._value(row, columns.get('street_type')),
                    )
                    if str(part).strip()
                )
                total_due_raw = self._value(row, columns.get('total_due'), 0)
                try:
                    total_due = float(total_due_raw)
                except (TypeError, ValueError):
                    total_due = 0

                deceased_flag = str(
                    self._value(row, columns.get('deceased_flag'))
                ).upper().startswith('YES')
                mailing_signal = str(
                    self._value(row, columns.get('mailing_signal'))
                ).strip()
                priority = self._priority(deceased_flag, mailing_signal, total_due)
                status = 'research_needed' if deceased_flag or mailing_signal else 'new'

                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO leads (
                        tax_id, owner_name, property_address, property_city,
                        mailing_address, mailing_city, mailing_state, zip_code,
                        total_due, tax_year, deceased_flag, mailing_signal,
                        status, priority, research_status, phone, source_job_id,
                        source_data_json, created_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        str(self._value(row, columns.get('tax_id'))).strip(),
                        owner_name,
                        property_address,
                        str(self._value(row, columns.get('property_city'))).strip(),
                        str(self._value(row, columns.get('mailing_address'))).strip(),
                        str(self._value(row, columns.get('mailing_city'))).strip(),
                        str(self._value(row, columns.get('mailing_state'))).strip(),
                        str(self._value(row, columns.get('zip_code'))).strip(),
                        total_due,
                        job['tax_year'],
                        int(deceased_flag),
                        mailing_signal,
                        status,
                        priority,
                        'unreviewed',
                        str(self._value(row, columns.get('phone'))).strip(),
                        job['uid'],
                        self._record_json(row),
                        now,
                        now,
                    ),
                )
                if cursor.rowcount:
                    imported += 1
                    lead_id = cursor.lastrowid
                    connection.execute(
                        """
                        INSERT INTO lead_activity (
                            lead_id, activity_type, detail, created_at
                        ) VALUES (?, 'imported', ?, ?)
                        """,
                        (lead_id, f"Imported from {job['source_filename']}", now),
                    )
        return imported

    def list_leads(
        self,
        search='',
        status='',
        priority='',
        research_only=False,
        page=1,
        per_page=50,
    ):
        conditions = []
        params = []
        if search:
            conditions.append(
                '(owner_name LIKE ? OR property_address LIKE ? OR tax_id LIKE ?)'
            )
            term = f'%{search}%'
            params.extend((term, term, term))
        if status in CRM_STATUSES:
            conditions.append('status = ?')
            params.append(status)
        if priority in CRM_PRIORITIES:
            conditions.append('priority = ?')
            params.append(priority)
        if research_only:
            conditions.append(
                "(deceased_flag = 1 OR mailing_signal IN ('Strong', 'Weak'))"
            )

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ''
        page = max(int(page), 1)
        per_page = min(max(int(per_page), 1), 100)
        offset = (page - 1) * per_page

        with self.connect() as connection:
            total = connection.execute(
                f'SELECT COUNT(*) FROM leads {where}', params
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT
                    leads.*,
                    (
                        SELECT body FROM lead_notes
                        WHERE lead_notes.lead_id = leads.id
                        ORDER BY created_at DESC LIMIT 1
                    ) AS latest_note
                FROM leads
                {where}
                ORDER BY
                    CASE priority
                        WHEN 'urgent' THEN 0
                        WHEN 'high' THEN 1
                        WHEN 'medium' THEN 2
                        ELSE 3
                    END,
                    deceased_flag DESC,
                    total_due DESC,
                    id DESC
                LIMIT ? OFFSET ?
                """,
                (*params, per_page, offset),
            ).fetchall()

        return {
            'items': [dict(row) for row in rows],
            'total': total,
            'page': page,
            'per_page': per_page,
            'pages': max((total + per_page - 1) // per_page, 1),
        }

    def get_lead(self, lead_id):
        with self.connect() as connection:
            lead = connection.execute(
                'SELECT * FROM leads WHERE id = ?', (lead_id,)
            ).fetchone()
            if not lead:
                return None
            notes = connection.execute(
                """
                SELECT * FROM lead_notes
                WHERE lead_id = ? ORDER BY created_at DESC
                """,
                (lead_id,),
            ).fetchall()
            activity = connection.execute(
                """
                SELECT * FROM lead_activity
                WHERE lead_id = ? ORDER BY created_at DESC
                """,
                (lead_id,),
            ).fetchall()
        return {
            **dict(lead),
            'notes': [dict(row) for row in notes],
            'activity': [dict(row) for row in activity],
        }

    def update_lead(self, lead_id, changes):
        allowed = {
            'status': CRM_STATUSES,
            'priority': CRM_PRIORITIES,
            'research_status': RESEARCH_STATUSES,
            'next_follow_up': None,
            'phone': None,
            'email': None,
        }
        updates = {}
        for field, value in changes.items():
            if field not in allowed:
                continue
            choices = allowed[field]
            if choices and value not in choices:
                raise ValueError(f'Invalid {field}')
            updates[field] = value
        if not updates:
            raise ValueError('No valid changes supplied')

        now = utc_now()
        assignments = ', '.join(f'{field} = ?' for field in updates)
        values = list(updates.values())
        with self.connect() as connection:
            current = connection.execute(
                'SELECT * FROM leads WHERE id = ?', (lead_id,)
            ).fetchone()
            if not current:
                return None
            connection.execute(
                f'UPDATE leads SET {assignments}, updated_at = ? WHERE id = ?',
                (*values, now, lead_id),
            )
            for field, value in updates.items():
                if current[field] != value:
                    connection.execute(
                        """
                        INSERT INTO lead_activity (
                            lead_id, activity_type, detail, created_at
                        ) VALUES (?, 'updated', ?, ?)
                        """,
                        (lead_id, f"{field.replace('_', ' ').title()} changed to {value or 'empty'}", now),
                    )
        return self.get_lead(lead_id)

    def add_note(self, lead_id, body):
        body = (body or '').strip()
        if not body:
            raise ValueError('Note cannot be empty')
        now = utc_now()
        with self.connect() as connection:
            exists = connection.execute(
                'SELECT id FROM leads WHERE id = ?', (lead_id,)
            ).fetchone()
            if not exists:
                return None
            cursor = connection.execute(
                """
                INSERT INTO lead_notes (lead_id, body, created_at)
                VALUES (?, ?, ?)
                """,
                (lead_id, body, now),
            )
            connection.execute(
                """
                INSERT INTO lead_activity (
                    lead_id, activity_type, detail, created_at
                ) VALUES (?, 'note_added', 'Note added', ?)
                """,
                (lead_id, now),
            )
        return {'id': cursor.lastrowid, 'lead_id': lead_id, 'body': body, 'created_at': now}

    def dashboard_metrics(self):
        with self.connect() as connection:
            total = connection.execute('SELECT COUNT(*) FROM leads').fetchone()[0]
            deceased = connection.execute(
                'SELECT COUNT(*) FROM leads WHERE deceased_flag = 1'
            ).fetchone()[0]
            research = connection.execute(
                """
                SELECT COUNT(*) FROM leads
                WHERE research_status IN ('unreviewed', 'in_progress')
                  AND (deceased_flag = 1 OR mailing_signal IN ('Strong', 'Weak'))
                """
            ).fetchone()[0]
            contacts = connection.execute(
                """
                SELECT COUNT(*) FROM leads
                WHERE COALESCE(TRIM(phone), '') != ''
                   OR COALESCE(TRIM(email), '') != ''
                """
            ).fetchone()[0]
            overdue = connection.execute(
                """
                SELECT COUNT(*) FROM leads
                WHERE next_follow_up IS NOT NULL
                  AND next_follow_up < date('now')
                  AND status NOT IN ('closed', 'disqualified')
                """
            ).fetchone()[0]
        return {
            'actionable_leads': total,
            'deceased_signals': deceased,
            'research_queue': research,
            'contacts_found': contacts,
            'overdue_follow_ups': overdue,
        }
