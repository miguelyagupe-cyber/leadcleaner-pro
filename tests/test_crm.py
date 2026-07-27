import os
import tempfile
import unittest

import pandas as pd

from app import app
from crm import CRMRepository


class CRMTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = os.path.join(self.temp_dir.name, 'crm.db')
        app.config.update(TESTING=True, CRM_DATABASE=self.database_path)
        self.repository = CRMRepository(self.database_path)
        self.repository.initialize()
        self.client = app.test_client()

        dataframe = pd.DataFrame(
            [
                {
                    'Tax ID': 'A-100',
                    'Owner Name': 'JANE DOE ESTATE OF',
                    'TotalDue': 12500,
                    'Phone': '',
                    'Address': 'PO BOX 100',
                    'OWNR_ADDR 6': 'TULSA',
                    'OWNR_ADDR ST': 'OK',
                    'ZIP': '74101',
                    'ST_NO': '120',
                    'ST_NAME': 'MAIN',
                    'ST_STREET_TYPE': 'ST',
                    'ST_CITY': 'TULSA',
                    'Deceased Owner (Flagged)': 'YES - Verify',
                    'Absentee/Suspicious Mailing (Verify)': 'Strong',
                },
                {
                    'Tax ID': 'B-200',
                    'Owner Name': 'JOHN SMITH',
                    'TotalDue': 2300,
                    'Phone': '9185550100',
                    'Address': '200 E PINE ST',
                    'OWNR_ADDR 6': 'TULSA',
                    'OWNR_ADDR ST': 'OK',
                    'ZIP': '74103',
                    'ST_NO': '200',
                    'ST_NAME': 'PINE',
                    'ST_STREET_TYPE': 'ST',
                    'ST_CITY': 'TULSA',
                    'Deceased Owner (Flagged)': '',
                    'Absentee/Suspicious Mailing (Verify)': '',
                },
            ]
        )
        columns = {
            'tax_id': 'Tax ID',
            'owner_name': 'Owner Name',
            'total_due': 'TotalDue',
            'phone': 'Phone',
            'mailing_address': 'Address',
            'mailing_city': 'OWNR_ADDR 6',
            'mailing_state': 'OWNR_ADDR ST',
            'zip_code': 'ZIP',
            'street_number': 'ST_NO',
            'street_name': 'ST_NAME',
            'street_type': 'ST_STREET_TYPE',
            'property_city': 'ST_CITY',
            'deceased_flag': 'Deceased Owner (Flagged)',
            'mailing_signal': 'Absentee/Suspicious Mailing (Verify)',
        }
        job = {
            'uid': 'job-1',
            'source_filename': 'tulsa.xlsx',
            'output_filename': 'clean.xlsx',
            'tax_year': 2023,
            'stats': {'final': 2},
        }
        self.repository.import_leads(dataframe, job, columns)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_import_creates_prioritized_leads_and_research_queue(self):
        all_leads = self.repository.list_leads()
        research = self.repository.list_leads(research_only=True)

        self.assertEqual(all_leads['total'], 2)
        self.assertEqual(research['total'], 1)
        self.assertEqual(all_leads['items'][0]['owner_name'], 'JANE DOE ESTATE OF')
        self.assertEqual(all_leads['items'][0]['priority'], 'high')
        self.assertEqual(all_leads['items'][0]['status'], 'research_needed')

    def test_api_updates_workflow_and_adds_note(self):
        lead_id = self.repository.list_leads()['items'][0]['id']

        update = self.client.patch(
            f'/api/leads/{lead_id}',
            json={'status': 'contact_ready', 'research_status': 'verified'},
        )
        note = self.client.post(
            f'/api/leads/{lead_id}/notes',
            json={'body': 'Probate record verified in county research.'},
        )
        detail = self.client.get(f'/api/leads/{lead_id}').get_json()

        self.assertEqual(update.status_code, 200)
        self.assertEqual(note.status_code, 201)
        self.assertEqual(detail['status'], 'contact_ready')
        self.assertEqual(detail['research_status'], 'verified')
        self.assertEqual(detail['notes'][0]['body'], 'Probate record verified in county research.')
        self.assertGreaterEqual(len(detail['activity']), 4)

    def test_dashboard_metrics_are_derived_from_crm(self):
        metrics = self.repository.dashboard_metrics()

        self.assertEqual(metrics['actionable_leads'], 2)
        self.assertEqual(metrics['deceased_signals'], 1)
        self.assertEqual(metrics['research_queue'], 1)
        self.assertEqual(metrics['contacts_found'], 1)


if __name__ == '__main__':
    unittest.main()
