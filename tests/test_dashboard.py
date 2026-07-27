import json
import os
import tempfile
import unittest
from datetime import datetime

from app import app


class DashboardApiTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        app.config.update(
            TESTING=True,
            OUTPUT_FOLDER=self.temp_dir.name,
        )
        self.client = app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_empty_dashboard_uses_zero_metrics(self):
        response = self.client.get('/api/dashboard')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertFalse(payload['has_data'])
        self.assertEqual(payload['metrics']['actionable_leads'], 0)
        self.assertEqual(payload['attention'], [])

    def test_dashboard_is_derived_from_latest_job_metadata(self):
        output_filename = 'Clean_Leads_2023_test.xlsx'
        output_path = os.path.join(self.temp_dir.name, output_filename)
        open(output_path, 'wb').close()

        metadata = {
            'uid': 'test-job',
            'output_filename': output_filename,
            'tax_year': 2023,
            'stats': {
                'final': 1619,
                'deceased_flagged': 5,
                'absentee_signal_strong': 68,
                'absentee_signal_weak': 389,
                'with_phone': 0,
                'without_phone': 1619,
            },
        }
        meta_path = os.path.join(self.temp_dir.name, 'test-job_meta.json')
        with open(meta_path, 'w', encoding='utf-8') as meta_file:
            json.dump(metadata, meta_file)
        timestamp = datetime(2026, 7, 27, 12, 0).timestamp()
        os.utime(meta_path, (timestamp, timestamp))

        payload = self.client.get('/api/dashboard').get_json()

        self.assertTrue(payload['has_data'])
        self.assertEqual(payload['metrics']['actionable_leads'], 1619)
        self.assertEqual(payload['metrics']['deceased_signals'], 5)
        self.assertEqual(payload['metrics']['research_queue'], 457)
        self.assertEqual(payload['latest_job']['id'], 'test-job')
        self.assertTrue(payload['latest_job']['download_available'])


if __name__ == '__main__':
    unittest.main()
