import json
import os
from datetime import date, datetime, timezone

import pandas as pd
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    case,
    create_engine,
    func,
    or_,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


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
EVIDENCE_TYPES = (
    'probate_case',
    'death_index',
    'death_certificate',
    'obituary',
    'assessor_owner_change',
    'estate_text',
    'skip_trace_mismatch',
    'other',
)
EVIDENCE_OUTCOMES = ('supports_deceased', 'supports_living', 'inconclusive')
EVIDENCE_CONFIDENCE = ('confirmed', 'strong', 'weak', 'rejected')
IDENTITY_MATCHES = ('exact', 'probable', 'uncertain', 'mismatch')


def utc_now():
    return datetime.now(timezone.utc)


def normalize_database_url(database_target):
    """Accept a local file path or a Render-style PostgreSQL URL."""
    target = str(database_target)
    if '://' not in target:
        path = os.path.abspath(target)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return f"sqlite:///{path}"
    if target.startswith('postgres://'):
        return target.replace('postgres://', 'postgresql+psycopg://', 1)
    if target.startswith('postgresql://'):
        return target.replace('postgresql://', 'postgresql+psycopg://', 1)
    return target


class Base(DeclarativeBase):
    pass


class ImportRun(Base):
    __tablename__ = 'import_runs'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    source_filename: Mapped[str] = mapped_column(Text, nullable=False)
    output_filename: Mapped[str] = mapped_column(Text, nullable=False)
    tax_year: Mapped[int] = mapped_column(Integer, nullable=False)
    stats_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProcessingJob(Base):
    __tablename__ = 'processing_jobs'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    meta_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProcessingArtifact(Base):
    __tablename__ = 'processing_artifacts'
    __table_args__ = (
        UniqueConstraint('job_id', 'kind', name='uq_job_artifact_kind'),
        Index('idx_artifact_filename', 'filename'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey('processing_jobs.job_id', ondelete='CASCADE'),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Lead(Base):
    __tablename__ = 'leads'
    __table_args__ = (
        UniqueConstraint(
            'source_job_id',
            'tax_id',
            'owner_name',
            'property_address',
            name='uq_lead_source_identity',
        ),
        Index('idx_leads_status', 'status'),
        Index('idx_leads_priority', 'priority'),
        Index('idx_leads_research', 'research_status'),
        Index('idx_leads_owner', 'owner_name'),
        Index('idx_leads_tax_id', 'tax_id'),
        Index('idx_leads_source_job', 'source_job_id'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tax_id: Mapped[str | None] = mapped_column(Text)
    owner_name: Mapped[str] = mapped_column(Text, nullable=False)
    property_address: Mapped[str | None] = mapped_column(Text)
    property_city: Mapped[str | None] = mapped_column(Text)
    mailing_address: Mapped[str | None] = mapped_column(Text)
    mailing_city: Mapped[str | None] = mapped_column(Text)
    mailing_state: Mapped[str | None] = mapped_column(Text)
    zip_code: Mapped[str | None] = mapped_column(Text)
    total_due: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    tax_year: Mapped[int] = mapped_column(Integer, nullable=False)
    deceased_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mailing_signal: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default='new')
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default='normal')
    research_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default='unreviewed'
    )
    phone: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    next_follow_up: Mapped[str | None] = mapped_column(String(30))
    last_contacted_at: Mapped[str | None] = mapped_column(String(40))
    source_job_id: Mapped[str] = mapped_column(
        String(100), ForeignKey('import_runs.job_id'), nullable=False
    )
    source_data_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LeadNote(Base):
    __tablename__ = 'lead_notes'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        ForeignKey('leads.id', ondelete='CASCADE'), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LeadActivity(Base):
    __tablename__ = 'lead_activity'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        ForeignKey('leads.id', ondelete='CASCADE'), nullable=False
    )
    activity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResearchEvidence(Base):
    __tablename__ = 'research_evidence'
    __table_args__ = (
        Index('idx_evidence_lead', 'lead_id'),
        Index('idx_evidence_outcome', 'outcome'),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        ForeignKey('leads.id', ondelete='CASCADE'), nullable=False
    )
    evidence_type: Mapped[str] = mapped_column(String(50), nullable=False)
    outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[str] = mapped_column(String(30), nullable=False)
    identity_match: Mapped[str] = mapped_column(String(30), nullable=False)
    source_name: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    case_number: Mapped[str | None] = mapped_column(String(100))
    subject_name: Mapped[str | None] = mapped_column(Text)
    event_date: Mapped[str | None] = mapped_column(String(30))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retraction_reason: Mapped[str | None] = mapped_column(Text)


class AssessorVerification(Base):
    __tablename__ = 'assessor_verifications'
    __table_args__ = (Index('idx_assessor_status', 'status'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_no: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    current_owner: Mapped[str | None] = mapped_column(Text)
    account_type: Mapped[str | None] = mapped_column(String(80))
    vacant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _as_dict(instance):
    return {
        column.name: getattr(instance, column.name)
        for column in instance.__table__.columns
    }


def summarize_evidence(items):
    items = [item for item in items if not item.retracted_at]
    if not items:
        return {
            'status': 'no_evidence',
            'label': 'No evidence',
            'confirmed': False,
            'reason': 'No research evidence has been recorded',
        }
    living = [
        item for item in items
        if item.outcome == 'supports_living'
        and item.confidence == 'confirmed'
        and item.identity_match in ('exact', 'probable')
    ]
    official_death_types = {'probate_case', 'death_index', 'death_certificate'}
    confirmed = [
        item for item in items
        if item.outcome == 'supports_deceased'
        and item.confidence == 'confirmed'
        and item.identity_match == 'exact'
        and item.evidence_type in official_death_types
    ]
    if living and confirmed:
        return {
            'status': 'conflicting_evidence',
            'label': 'Conflicting evidence',
            'confirmed': False,
            'reason': 'Confirmed living and death evidence require manual resolution',
        }
    if living:
        return {
            'status': 'false_positive',
            'label': 'False positive',
            'confirmed': False,
            'reason': 'Confirmed evidence supports that the matched person is living',
        }
    if confirmed:
        return {
            'status': 'confirmed_deceased',
            'label': 'Confirmed deceased',
            'confirmed': True,
            'reason': 'Exact identity match supported by confirmed official evidence',
        }
    strong = [
        item for item in items
        if item.outcome == 'supports_deceased'
        and item.confidence in ('confirmed', 'strong')
        and item.identity_match in ('exact', 'probable')
    ]
    if strong:
        return {
            'status': 'probable_deceased',
            'label': 'Probable deceased',
            'confirmed': False,
            'reason': 'Strong evidence exists but confirmation requirements are incomplete',
        }
    return {
        'status': 'inconclusive',
        'label': 'Inconclusive',
        'confirmed': False,
        'reason': 'Recorded evidence does not establish identity and death',
    }


class CRMRepository:
    def __init__(self, database_target):
        self.database_url = normalize_database_url(database_target)
        connect_args = (
            {'check_same_thread': False}
            if self.database_url.startswith('sqlite:')
            else {}
        )
        self.engine = create_engine(
            self.database_url,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        self.Session = sessionmaker(self.engine, expire_on_commit=False)

    def initialize(self):
        Base.metadata.create_all(self.engine)

    def health(self):
        with self.engine.connect() as connection:
            connection.execute(select(1))
        return {'status': 'ok', 'database': self.engine.dialect.name}

    def save_processing_job(self, meta):
        now = utc_now()
        payload = json.dumps(meta, default=str)
        with self.Session.begin() as session:
            item = session.scalar(
                select(ProcessingJob).where(
                    ProcessingJob.job_id == meta['uid']
                )
            )
            if item:
                item.meta_json = payload
                item.updated_at = now
            else:
                session.add(
                    ProcessingJob(
                        job_id=meta['uid'],
                        meta_json=payload,
                        created_at=now,
                        updated_at=now,
                    )
                )

    def get_processing_job(self, job_id):
        with self.Session() as session:
            item = session.scalar(
                select(ProcessingJob).where(ProcessingJob.job_id == job_id)
            )
            if not item:
                return None
            meta = json.loads(item.meta_json)
            meta['_created_at'] = item.created_at.isoformat()
            meta['_updated_at'] = item.updated_at.isoformat()
            return meta

    def list_processing_jobs(self, limit=20):
        with self.Session() as session:
            items = session.scalars(
                select(ProcessingJob)
                .order_by(ProcessingJob.updated_at.desc())
                .limit(min(max(int(limit), 1), 100))
            ).all()
            result = []
            for item in items:
                meta = json.loads(item.meta_json)
                meta['_created_at'] = item.created_at.isoformat()
                meta['_updated_at'] = item.updated_at.isoformat()
                result.append(meta)
            return result

    def save_processing_artifact(self, job_id, kind, filename, content):
        import hashlib

        now = utc_now()
        content = bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        with self.Session.begin() as session:
            item = session.scalar(
                select(ProcessingArtifact).where(
                    ProcessingArtifact.job_id == job_id,
                    ProcessingArtifact.kind == kind,
                )
            )
            values = {
                'filename': filename,
                'content': content,
                'content_sha256': digest,
                'size_bytes': len(content),
                'updated_at': now,
            }
            if item:
                for field, value in values.items():
                    setattr(item, field, value)
            else:
                item = ProcessingArtifact(
                    job_id=job_id,
                    kind=kind,
                    created_at=now,
                    **values,
                )
                session.add(item)
        return {
            'job_id': job_id,
            'kind': kind,
            'filename': filename,
            'content_sha256': digest,
            'size_bytes': len(content),
        }

    def get_processing_artifact(self, job_id=None, kind=None, filename=None):
        conditions = []
        if job_id:
            conditions.append(ProcessingArtifact.job_id == job_id)
        if kind:
            conditions.append(ProcessingArtifact.kind == kind)
        if filename:
            conditions.append(ProcessingArtifact.filename == filename)
        if not conditions:
            return None
        with self.Session() as session:
            item = session.scalar(
                select(ProcessingArtifact)
                .where(*conditions)
                .order_by(ProcessingArtifact.updated_at.desc())
            )
            return _as_dict(item) if item else None

    def get_assessor_verification(self, account_no):
        with self.Session() as session:
            item = session.scalar(
                select(AssessorVerification).where(
                    AssessorVerification.account_no == account_no
                )
            )
            return _as_dict(item) if item else None

    def save_assessor_verification(self, result):
        fetched_at = datetime.fromisoformat(result.fetched_at)
        with self.Session.begin() as session:
            item = session.scalar(
                select(AssessorVerification).where(
                    AssessorVerification.account_no == result.account_no
                )
            )
            values = {
                'status': result.status,
                'current_owner': result.current_owner,
                'account_type': result.account_type,
                'vacant': result.vacant,
                'source_url': result.source_url,
                'error': result.error,
                'fetched_at': fetched_at,
            }
            if item:
                for field, value in values.items():
                    setattr(item, field, value)
            else:
                item = AssessorVerification(
                    account_no=result.account_no,
                    **values,
                )
                session.add(item)
            session.flush()
            record = _as_dict(item)
        return record

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
        if deceased_flag or mailing_signal == 'Strong' or total_due >= 10000:
            return 'high'
        if mailing_signal or total_due >= 5000:
            return 'medium'
        return 'normal'

    def import_leads(self, dataframe, job, columns):
        now = utc_now()
        imported = 0
        with self.Session.begin() as session:
            import_run = session.scalar(
                select(ImportRun).where(ImportRun.job_id == job['uid'])
            )
            if import_run:
                import_run.output_filename = job['output_filename']
                import_run.stats_json = json.dumps(job['stats'])
            else:
                session.add(
                    ImportRun(
                        job_id=job['uid'],
                        source_filename=job['source_filename'],
                        output_filename=job['output_filename'],
                        tax_year=job['tax_year'],
                        stats_json=json.dumps(job['stats']),
                        created_at=now,
                    )
                )
                session.flush()

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
                tax_id = str(self._value(row, columns.get('tax_id'))).strip()
                duplicate = session.scalar(
                    select(Lead.id).where(
                        Lead.source_job_id == job['uid'],
                        Lead.tax_id == tax_id,
                        Lead.owner_name == owner_name,
                        Lead.property_address == property_address,
                    )
                )
                if duplicate:
                    continue

                try:
                    total_due = float(
                        self._value(row, columns.get('total_due'), 0)
                    )
                except (TypeError, ValueError):
                    total_due = 0
                deceased_value = str(
                    self._value(row, columns.get('deceased_flag'))
                ).strip()
                deceased_flag = (
                    bool(deceased_value)
                    and deceased_value.upper()
                    not in ('NO', 'FALSE', 'NONE', 'NAN')
                )
                mailing_signal = str(
                    self._value(row, columns.get('mailing_signal'))
                ).strip()
                lead = Lead(
                    tax_id=tax_id,
                    owner_name=owner_name,
                    property_address=property_address,
                    property_city=str(
                        self._value(row, columns.get('property_city'))
                    ).strip(),
                    mailing_address=str(
                        self._value(row, columns.get('mailing_address'))
                    ).strip(),
                    mailing_city=str(
                        self._value(row, columns.get('mailing_city'))
                    ).strip(),
                    mailing_state=str(
                        self._value(row, columns.get('mailing_state'))
                    ).strip(),
                    zip_code=str(
                        self._value(row, columns.get('zip_code'))
                    ).strip(),
                    total_due=total_due,
                    tax_year=job['tax_year'],
                    deceased_flag=deceased_flag,
                    mailing_signal=mailing_signal,
                    status='research_needed'
                    if deceased_flag or mailing_signal
                    else 'new',
                    priority=self._priority(
                        deceased_flag, mailing_signal, total_due
                    ),
                    research_status='unreviewed',
                    phone=str(self._value(row, columns.get('phone'))).strip(),
                    source_job_id=job['uid'],
                    source_data_json=self._record_json(row),
                    created_at=now,
                    updated_at=now,
                )
                session.add(lead)
                session.flush()
                session.add(
                    LeadActivity(
                        lead_id=lead.id,
                        activity_type='imported',
                        detail=f"Imported from {job['source_filename']}",
                        created_at=now,
                    )
                )
                imported += 1
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
        if search:
            term = f'%{search}%'
            conditions.append(
                or_(
                    Lead.owner_name.ilike(term),
                    Lead.property_address.ilike(term),
                    Lead.tax_id.ilike(term),
                )
            )
        if status in CRM_STATUSES:
            conditions.append(Lead.status == status)
        if priority in CRM_PRIORITIES:
            conditions.append(Lead.priority == priority)
        if research_only:
            conditions.append(
                or_(
                    Lead.deceased_flag.is_(True),
                    Lead.mailing_signal.in_(('Strong', 'Weak')),
                )
            )

        page = max(int(page), 1)
        per_page = min(max(int(per_page), 1), 100)
        offset = (page - 1) * per_page
        latest_note = (
            select(LeadNote.body)
            .where(LeadNote.lead_id == Lead.id)
            .order_by(LeadNote.created_at.desc())
            .limit(1)
            .correlate(Lead)
            .scalar_subquery()
        )
        priority_order = case(
            (Lead.priority == 'urgent', 0),
            (Lead.priority == 'high', 1),
            (Lead.priority == 'medium', 2),
            else_=3,
        )

        with self.Session() as session:
            total = session.scalar(
                select(func.count()).select_from(Lead).where(*conditions)
            ) or 0
            rows = session.execute(
                select(Lead, latest_note.label('latest_note'))
                .where(*conditions)
                .order_by(
                    priority_order,
                    Lead.deceased_flag.desc(),
                    Lead.total_due.desc(),
                    Lead.id.desc(),
                )
                .limit(per_page)
                .offset(offset)
            ).all()

        return {
            'items': [
                {**_as_dict(lead), 'latest_note': note} for lead, note in rows
            ],
            'total': total,
            'page': page,
            'per_page': per_page,
            'pages': max((total + per_page - 1) // per_page, 1),
        }

    def get_lead(self, lead_id):
        with self.Session() as session:
            lead = session.get(Lead, lead_id)
            if not lead:
                return None
            notes = session.scalars(
                select(LeadNote)
                .where(LeadNote.lead_id == lead_id)
                .order_by(LeadNote.created_at.desc())
            ).all()
            activity = session.scalars(
                select(LeadActivity)
                .where(LeadActivity.lead_id == lead_id)
                .order_by(LeadActivity.created_at.desc())
            ).all()
            evidence = session.scalars(
                select(ResearchEvidence)
                .where(ResearchEvidence.lead_id == lead_id)
                .order_by(ResearchEvidence.created_at.desc())
            ).all()
            return {
                **_as_dict(lead),
                'notes': [_as_dict(note) for note in notes],
                'activity': [_as_dict(item) for item in activity],
                'evidence': [_as_dict(item) for item in evidence],
                'evidence_summary': summarize_evidence(evidence),
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
        with self.Session.begin() as session:
            lead = session.get(Lead, lead_id)
            if not lead:
                return None
            for field, value in updates.items():
                if getattr(lead, field) != value:
                    setattr(lead, field, value)
                    session.add(
                        LeadActivity(
                            lead_id=lead_id,
                            activity_type='updated',
                            detail=(
                                f"{field.replace('_', ' ').title()} changed to "
                                f"{value or 'empty'}"
                            ),
                            created_at=now,
                        )
                    )
            lead.updated_at = now
        return self.get_lead(lead_id)

    def add_note(self, lead_id, body):
        body = (body or '').strip()
        if not body:
            raise ValueError('Note cannot be empty')
        now = utc_now()
        with self.Session.begin() as session:
            if not session.get(Lead, lead_id):
                return None
            note = LeadNote(lead_id=lead_id, body=body, created_at=now)
            session.add(note)
            session.flush()
            note_id = note.id
            session.add(
                LeadActivity(
                    lead_id=lead_id,
                    activity_type='note_added',
                    detail='Note added',
                    created_at=now,
                )
            )
        return {'id': note_id, 'lead_id': lead_id, 'body': body, 'created_at': now}

    def add_evidence(self, lead_id, payload):
        evidence_type = str(payload.get('evidence_type', '')).strip()
        outcome = str(payload.get('outcome', '')).strip()
        confidence = str(payload.get('confidence', '')).strip()
        identity_match = str(payload.get('identity_match', '')).strip()
        source_name = str(payload.get('source_name', '')).strip()
        if evidence_type not in EVIDENCE_TYPES:
            raise ValueError('Invalid evidence type')
        if outcome not in EVIDENCE_OUTCOMES:
            raise ValueError('Invalid evidence outcome')
        if confidence not in EVIDENCE_CONFIDENCE:
            raise ValueError('Invalid evidence confidence')
        if identity_match not in IDENTITY_MATCHES:
            raise ValueError('Invalid identity match')
        if not source_name:
            raise ValueError('Evidence source is required')

        source_url = str(payload.get('source_url', '')).strip() or None
        if source_url and not source_url.startswith(('https://', 'http://')):
            raise ValueError('Evidence URL must start with http:// or https://')
        now = utc_now()
        with self.Session.begin() as session:
            lead = session.get(Lead, lead_id)
            if not lead:
                return None
            evidence = ResearchEvidence(
                lead_id=lead_id,
                evidence_type=evidence_type,
                outcome=outcome,
                confidence=confidence,
                identity_match=identity_match,
                source_name=source_name,
                source_url=source_url,
                case_number=str(payload.get('case_number', '')).strip() or None,
                subject_name=str(payload.get('subject_name', '')).strip() or None,
                event_date=str(payload.get('event_date', '')).strip() or None,
                notes=str(payload.get('notes', '')).strip() or None,
                created_at=now,
            )
            session.add(evidence)
            session.flush()
            evidence_id = evidence.id
            session.add(
                LeadActivity(
                    lead_id=lead_id,
                    activity_type='evidence_added',
                    detail=(
                        f"Evidence added: {evidence_type.replace('_', ' ')} "
                        f"({outcome.replace('_', ' ')})"
                    ),
                    created_at=now,
                )
            )
            all_evidence = session.scalars(
                select(ResearchEvidence).where(
                    ResearchEvidence.lead_id == lead_id
                )
            ).all()
            summary = summarize_evidence(all_evidence)
            if summary['confirmed']:
                lead.research_status = 'verified'
            elif summary['status'] == 'false_positive':
                lead.research_status = 'rejected'
            else:
                lead.research_status = 'in_progress'
            lead.updated_at = now
        detail = self.get_lead(lead_id)
        return {
            'evidence_id': evidence_id,
            'lead': detail,
        }

    def retract_evidence(self, lead_id, evidence_id, reason):
        reason = str(reason or '').strip()
        if not reason:
            raise ValueError('Retraction reason is required')
        now = utc_now()
        with self.Session.begin() as session:
            lead = session.get(Lead, lead_id)
            if not lead:
                return None
            evidence = session.get(ResearchEvidence, evidence_id)
            if not evidence or evidence.lead_id != lead_id:
                return None
            if not evidence.retracted_at:
                evidence.retracted_at = now
                evidence.retraction_reason = reason
                session.add(
                    LeadActivity(
                        lead_id=lead_id,
                        activity_type='evidence_retracted',
                        detail=(
                            f"Evidence retracted: "
                            f"{evidence.evidence_type.replace('_', ' ')}"
                        ),
                        created_at=now,
                    )
                )
            active = session.scalars(
                select(ResearchEvidence).where(
                    ResearchEvidence.lead_id == lead_id
                )
            ).all()
            summary = summarize_evidence(active)
            if summary['confirmed']:
                lead.research_status = 'verified'
            elif summary['status'] == 'false_positive':
                lead.research_status = 'rejected'
            elif summary['status'] == 'no_evidence':
                lead.research_status = 'unreviewed'
            else:
                lead.research_status = 'in_progress'
            lead.updated_at = now
        return self.get_lead(lead_id)

    def dashboard_metrics(self):
        active_research = (
            Lead.research_status.in_(('unreviewed', 'in_progress')),
            or_(
                Lead.deceased_flag.is_(True),
                Lead.mailing_signal.in_(('Strong', 'Weak')),
            ),
        )
        today = date.today().isoformat()
        with self.Session() as session:
            total = session.scalar(select(func.count()).select_from(Lead)) or 0
            deceased = session.scalar(
                select(func.count())
                .select_from(Lead)
                .where(Lead.deceased_flag.is_(True))
            ) or 0
            research = session.scalar(
                select(func.count()).select_from(Lead).where(*active_research)
            ) or 0
            contacts = session.scalar(
                select(func.count())
                .select_from(Lead)
                .where(
                    or_(
                        func.coalesce(func.trim(Lead.phone), '') != '',
                        func.coalesce(func.trim(Lead.email), '') != '',
                    )
                )
            ) or 0
            overdue = session.scalar(
                select(func.count())
                .select_from(Lead)
                .where(
                    Lead.next_follow_up.is_not(None),
                    Lead.next_follow_up < today,
                    Lead.status.not_in(('closed', 'disqualified')),
                )
            ) or 0
        return {
            'actionable_leads': total,
            'deceased_signals': deceased,
            'research_queue': research,
            'contacts_found': contacts,
            'overdue_follow_ups': overdue,
        }
