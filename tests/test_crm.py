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
        app.config.update(
            TESTING=True,
            DATABASE_URL=None,
            CRM_DATABASE=self.database_path,
        )
        self.repository = CRMRepository(self.database_path)
        self.repository.initialize()
        self.client = app.test_client()

        dataframe = pd.DataFrame(
            [
                {
                    'Tax ID': 'A-100',
                    'Owner Name': 'TEST OWNER ALPHA ESTATE OF',
                    'TotalDue': 12500,
                    'Phone': '',
                    'Address': 'TEST MAILING ADDRESS A',
                    'OWNR_ADDR 6': 'TULSA',
                    'OWNR_ADDR ST': 'OK',
                    'ZIP': '00000',
                    'ST_NO': '100',
                    'ST_NAME': 'SAMPLE',
                    'ST_STREET_TYPE': 'ST',
                    'ST_CITY': 'TULSA',
                    'Deceased Owner (Flagged)': 'YES - Verify',
                    'Absentee/Suspicious Mailing (Verify)': 'Strong',
                },
                {
                    'Tax ID': 'B-200',
                    'Owner Name': 'TEST OWNER BETA',
                    'TotalDue': 2300,
                    'Phone': '0000000000',
                    'Address': 'TEST MAILING ADDRESS B',
                    'OWNR_ADDR 6': 'TULSA',
                    'OWNR_ADDR ST': 'OK',
                    'ZIP': '00000',
                    'ST_NO': '200',
                    'ST_NAME': 'EXAMPLE',
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
        self.assertEqual(
            all_leads['items'][0]['owner_name'],
            'TEST OWNER ALPHA ESTATE OF',
        )
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

    def test_import_is_idempotent(self):
        leads = self.repository.list_leads()
        self.assertEqual(leads['total'], 2)

    def test_health_reports_database_dialect(self):
        health = self.client.get('/api/health').get_json()
        self.assertEqual(health, {'status': 'ok', 'database': 'sqlite'})

    def test_exact_confirmed_official_evidence_confirms_deceased(self):
        lead_id = self.repository.list_leads()['items'][0]['id']
        response = self.client.post(
            f'/api/leads/{lead_id}/evidence',
            json={
                'evidence_type': 'probate_case',
                'outcome': 'supports_deceased',
                'confidence': 'confirmed',
                'identity_match': 'exact',
                'source_name': 'OSCN',
                'source_url': (
                    'https://www.oscn.net/dockets/'
                    'GetCaseInformation.aspx?db=Tulsa&number=PB-2024-525'
                ),
                'case_number': 'PB-2024-525',
                'subject_name': 'TEST OWNER ALPHA',
                'notes': 'Property and representative matched manually.',
            },
        )
        lead = response.get_json()['lead']

        self.assertEqual(response.status_code, 201)
        self.assertTrue(lead['evidence_summary']['confirmed'])
        self.assertEqual(
            lead['evidence_summary']['status'],
            'confirmed_deceased',
        )
        self.assertEqual(lead['research_status'], 'verified')

    def test_probable_identity_does_not_claim_confirmed_death(self):
        lead_id = self.repository.list_leads()['items'][0]['id']
        result = self.repository.add_evidence(
            lead_id,
            {
                'evidence_type': 'probate_case',
                'outcome': 'supports_deceased',
                'confidence': 'confirmed',
                'identity_match': 'probable',
                'source_name': 'OSCN',
                'case_number': 'PB-2024-999',
            },
        )

        self.assertFalse(result['lead']['evidence_summary']['confirmed'])
        self.assertEqual(
            result['lead']['evidence_summary']['status'],
            'probable_deceased',
        )
        self.assertEqual(result['lead']['research_status'], 'in_progress')

    def test_confirmed_living_evidence_rejects_false_positive(self):
        lead_id = self.repository.list_leads()['items'][0]['id']
        result = self.repository.add_evidence(
            lead_id,
            {
                'evidence_type': 'assessor_owner_change',
                'outcome': 'supports_living',
                'confidence': 'confirmed',
                'identity_match': 'exact',
                'source_name': 'Tulsa County Assessor',
                'source_url': 'https://assessor.tulsacounty.org/',
            },
        )

        self.assertEqual(
            result['lead']['evidence_summary']['status'],
            'false_positive',
        )
        self.assertEqual(result['lead']['research_status'], 'rejected')

    def test_conflicting_confirmed_evidence_requires_manual_resolution(self):
        lead_id = self.repository.list_leads()['items'][0]['id']
        for outcome, evidence_type in (
            ('supports_deceased', 'death_certificate'),
            ('supports_living', 'assessor_owner_change'),
        ):
            self.repository.add_evidence(
                lead_id,
                {
                    'evidence_type': evidence_type,
                    'outcome': outcome,
                    'confidence': 'confirmed',
                    'identity_match': 'exact',
                    'source_name': 'Official record',
                },
            )
        lead = self.repository.get_lead(lead_id)

        self.assertFalse(lead['evidence_summary']['confirmed'])
        self.assertEqual(
            lead['evidence_summary']['status'],
            'conflicting_evidence',
        )
        self.assertEqual(lead['research_status'], 'in_progress')

    def test_research_page_exposes_evidence_ledger(self):
        response = self.client.get('/research')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Death & probate evidence', response.data)
        self.assertIn(b'Identity match', response.data)
        self.assertIn(b'Add evidence', response.data)

    def test_retraction_preserves_record_and_removes_its_effect(self):
        lead_id = self.repository.list_leads()['items'][0]['id']
        added = self.repository.add_evidence(
            lead_id,
            {
                'evidence_type': 'death_certificate',
                'outcome': 'supports_deceased',
                'confidence': 'confirmed',
                'identity_match': 'exact',
                'source_name': 'Official certificate',
            },
        )
        response = self.client.delete(
            (
                f'/api/leads/{lead_id}/evidence/'
                f"{added['evidence_id']}"
            ),
            json={'reason': 'Attached to a different person with the same name.'},
        )
        lead = response.get_json()['lead']

        self.assertEqual(response.status_code, 200)
        self.assertEqual(lead['evidence_summary']['status'], 'no_evidence')
        self.assertEqual(lead['research_status'], 'unreviewed')
        self.assertIsNotNone(lead['evidence'][0]['retracted_at'])
        self.assertIn('different person', lead['evidence'][0]['retraction_reason'])


if __name__ == '__main__':
    unittest.main()
