import os
import tempfile
import unittest

from sqlalchemy import inspect, text

from crm import CRMRepository
from migrate import CONTACT_POINT_COLUMNS, run_migrations


class SchemaMigrationTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(self.temp_dir.name, 'crm.db')

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_contact_points_schema_is_created_with_expected_indexes(self):
        run_migrations(self.database_path)
        repository = CRMRepository(self.database_path)
        inspector = inspect(repository.engine)

        columns = {
            item['name']
            for item in inspector.get_columns('contact_points')
        }
        indexes = {
            item['name']: item
            for item in inspector.get_indexes('contact_points')
        }

        self.assertEqual(columns, CONTACT_POINT_COLUMNS)
        self.assertIn('idx_contact_points_lead', indexes)
        self.assertIn('idx_contact_points_status', indexes)
        self.assertTrue(indexes['idx_contact_points_identity']['unique'])
        alert_columns = {
            item['name']
            for item in inspector.get_columns('operational_alerts')
        }
        self.assertIn('emailed_at', alert_columns)
        self.assertIn('sms_sent_at', alert_columns)
        repository.engine.dispose()

    def test_migration_is_idempotent_and_preserves_existing_rows(self):
        run_migrations(self.database_path)
        repository = CRMRepository(self.database_path)
        with repository.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO import_runs (
                        job_id, source_filename, output_filename, tax_year,
                        stats_json, created_at
                    ) VALUES (
                        'migration-test', 'test.xlsx', 'clean.xlsx', 2023,
                        '{}', CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO leads (
                        owner_name, tax_id,
                        total_due, property_address, mailing_address,
                        source_job_id, tax_year, source_data_json,
                        status, priority, research_status,
                        deceased_flag, mailing_signal, created_at, updated_at
                    ) VALUES (
                        'TEST OWNER', 'T-1',
                        100, 'TEST ADDRESS', 'TEST ADDRESS',
                        'migration-test', 2023,
                        '{}', 'new', 'normal', 'unreviewed',
                        0, '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            lead_id = connection.scalar(
                text("SELECT id FROM leads WHERE source_job_id = 'migration-test'")
            )
            connection.execute(
                text(
                    """
                    INSERT INTO contact_points (
                        lead_id, kind, value, normalized_value, source_name,
                        confidence, status, is_primary, created_at, updated_at
                    ) VALUES (
                        :lead_id, 'phone', '9185550100', '9185550100',
                        'Migration test', 'verified', 'active', 1,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """
                ),
                {'lead_id': lead_id},
            )
        repository.engine.dispose()

        run_migrations(self.database_path)
        repository = CRMRepository(self.database_path)
        with repository.engine.connect() as connection:
            count = connection.scalar(text('SELECT count(*) FROM contact_points'))

        self.assertEqual(count, 1)
        repository.engine.dispose()
