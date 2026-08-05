import os

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    inspect,
    text,
)

from crm import CRMRepository


MIGRATION_LOCK_NAME = 'leadcleaner-schema-v1'
CONTACT_POINT_COLUMNS = {
    'id',
    'lead_id',
    'kind',
    'value',
    'normalized_value',
    'label',
    'source_name',
    'confidence',
    'status',
    'is_primary',
    'notes',
    'created_at',
    'updated_at',
}
def contact_points_table():
    metadata = MetaData()
    Table(
        'leads',
        metadata,
        Column('id', Integer, primary_key=True),
    )
    table = Table(
        'contact_points',
        metadata,
        Column('id', Integer, primary_key=True),
        Column(
            'lead_id',
            Integer,
            ForeignKey('leads.id', ondelete='CASCADE'),
            nullable=False,
        ),
        Column('kind', String(20), nullable=False),
        Column('value', Text, nullable=False),
        Column('normalized_value', Text, nullable=False),
        Column('label', String(60)),
        Column('source_name', Text, nullable=False),
        Column('confidence', String(20), nullable=False),
        Column('status', String(30), nullable=False),
        Column('is_primary', Boolean, nullable=False, default=False),
        Column('notes', Text),
        Column('created_at', DateTime(timezone=True), nullable=False),
        Column('updated_at', DateTime(timezone=True), nullable=False),
    )
    Index('idx_contact_points_lead', table.c.lead_id)
    Index('idx_contact_points_status', table.c.status)
    Index(
        'idx_contact_points_identity',
        table.c.lead_id,
        table.c.kind,
        table.c.normalized_value,
        unique=True,
    )
    return table


def _configure_postgres_migration(connection):
    connection.execute(text("SET LOCAL lock_timeout = '5s'"))
    connection.execute(text("SET LOCAL statement_timeout = '30s'"))
    acquired = connection.scalar(
        text('SELECT pg_try_advisory_xact_lock(hashtext(:lock_name))'),
        {'lock_name': MIGRATION_LOCK_NAME},
    )
    if not acquired:
        raise RuntimeError('Another LeadCleaner schema migration is running')


def _verify_contact_points_schema(connection):
    inspector = inspect(connection)
    columns = {
        item['name']
        for item in inspector.get_columns('contact_points')
    }
    missing = CONTACT_POINT_COLUMNS - columns
    if missing:
        raise RuntimeError(
            'contact_points schema is incomplete; missing: '
            + ', '.join(sorted(missing))
        )


def _migrate_operational_alerts(connection):
    inspector = inspect(connection)
    columns = {item['name'] for item in inspector.get_columns('operational_alerts')}
    if 'emailed_at' not in columns:
        connection.execute(text(
            'ALTER TABLE operational_alerts ADD COLUMN emailed_at TIMESTAMP'
        ))
    if 'sms_sent_at' not in columns:
        connection.execute(text(
            'ALTER TABLE operational_alerts ADD COLUMN sms_sent_at TIMESTAMP'
        ))


def run_migrations(database_target):
    repository = CRMRepository(database_target)
    repository.initialize()
    table = contact_points_table()

    with repository.engine.begin() as connection:
        if connection.dialect.name == 'postgresql':
            _configure_postgres_migration(connection)
        table.create(connection, checkfirst=True)
        for index in table.indexes:
            index.create(connection, checkfirst=True)
        _verify_contact_points_schema(connection)
        _migrate_operational_alerts(connection)

    repository.engine.dispose()


def main():
    database_target = os.environ.get('DATABASE_URL') or os.environ.get(
        'CRM_DATABASE',
        os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'data',
            'leadcleaner.db',
        ),
    )
    run_migrations(database_target)
    print('LeadCleaner schema is ready.')


if __name__ == '__main__':
    main()
