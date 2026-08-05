import json
import os
import tempfile
import unittest

import pandas as pd

from app import app
from crm import CRMRepository


class ApprovedImportTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = os.path.join(self.temp_dir.name, 'outputs')
        os.makedirs(self.output_dir)
        self.database_path = os.path.join(self.temp_dir.name, 'crm.db')
        app.config.update(
            TESTING=True,
            DATABASE_URL=None,
            CRM_DATABASE=self.database_path,
            OUTPUT_FOLDER=self.output_dir,
        )
        self.client = app.test_client()
        self.repository = CRMRepository(self.database_path)
        self.repository.initialize()
        rows = []
        for index, decision in enumerate(
            (
                'Verified candidate',
                'Verified candidate',
                'Verified candidate',
                'Review',
                'Not checked',
            ),
            start=1,
        ):
            property_number = 1 if index in (1, 2) else index
            rows.append(
                {
                    'Tax ID': f'TEST-{index}',
                    'PID': f'00000-00-00-0000{property_number}',
                    'Owner Name': f'SOURCE OWNER {property_number}',
                    'Current Assessor Owner': f'CURRENT OWNER {property_number}',
                    'Current Owner Verification': decision,
                    'TotalDue': index * 1000,
                    'Phone': '9185550101' if index in (1, 2) else '',
                    'Address': f'TEST MAILING ADDRESS {index}',
                    'OWNR_ADDR 6': 'TULSA',
                    'OWNR_ADDR ST': 'OK',
                    'ZIP': '00000',
                    'ST_NO': str(property_number * 100),
                    'ST_NAME': 'SAMPLE',
                    'ST_STREET_TYPE': 'ST',
                    'ST_CITY': 'TULSA',
                    'Lead Score': 50,
                    'Lead Tier': 'C',
                    'Score Status': 'Preliminary',
                    'Deceased Research Status': 'No text signal',
                    'Owner Type': 'Individual / joint owners',
                    'Data Quality Issues': '',
                    'Assessor Vacant': 'No',
                    'Deceased Evidence': (
                        'Estate notation in owner name' if index == 1 else ''
                    ),
                    'Absentee Signal': 'Out of state' if index == 2 else '',
                }
            )
        dataframe = pd.DataFrame(rows)
        workbook_name = 'Assessor_Verified_clean.xlsx'
        with pd.ExcelWriter(
            os.path.join(self.output_dir, workbook_name),
            engine='openpyxl',
        ) as writer:
            dataframe.to_excel(
                writer,
                sheet_name='Prequalified - Verify',
                index=False,
            )
        with open(
            os.path.join(self.output_dir, 'approval-job_meta.json'),
            'w',
        ) as file_handle:
            json.dump(
                {
                    'uid': 'approval-job',
                    'source_filename': 'test-source.xlsx',
                    'output_filename': 'clean.xlsx',
                    'assessor_output_filename': workbook_name,
                    'tax_year': 2023,
                    'stats': {'prequalified': 5},
                    'status': 'ready_for_approval',
                    'assessor_progress': {
                        'checked': 5,
                        'total': 5,
                        'remaining': 0,
                    },
                },
                file_handle,
            )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_preview_includes_only_verified_candidates(self):
        response = self.client.get('/api/import/approval-job/preview')
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['approved_candidates'], 2)
        self.assertEqual(payload['approved_accounts'], 3)
        self.assertEqual(payload['consolidated_accounts'], 1)
        self.assertEqual(payload['total_debt'], 6000)
        self.assertEqual(payload['decision_counts']['Review'], 1)
        self.assertEqual(payload['decision_counts']['Not checked'], 1)
        self.assertEqual(len(payload['approval_token']), 64)

    def test_commit_requires_current_preview_and_is_idempotent(self):
        stale = self.client.post(
            '/api/import/approval-job/commit',
            json={
                'approval_token': 'stale',
                'confirmation': 'IMPORT VERIFIED CANDIDATES',
            },
        )
        preview = self.client.get(
            '/api/import/approval-job/preview'
        ).get_json()
        first = self.client.post(
            '/api/import/approval-job/commit',
            json={
                'approval_token': preview['approval_token'],
                'confirmation': 'IMPORT VERIFIED CANDIDATES',
            },
        ).get_json()
        second = self.client.post(
            '/api/import/approval-job/commit',
            json={
                'approval_token': preview['approval_token'],
                'confirmation': 'IMPORT VERIFIED CANDIDATES',
            },
        ).get_json()
        leads = self.repository.list_leads()

        self.assertEqual(stale.status_code, 409)
        self.assertEqual(first['imported'], 2)
        self.assertEqual(first['approved_accounts'], 3)
        self.assertEqual(first['consolidated_accounts'], 1)
        self.assertEqual(first['duplicates_skipped'], 0)
        self.assertEqual(second['imported'], 0)
        self.assertEqual(second['duplicates_skipped'], 2)
        self.assertEqual(leads['total'], 2)
        self.assertEqual(
            {lead['owner_name'] for lead in leads['items']},
            {'CURRENT OWNER 1', 'CURRENT OWNER 3'},
        )
        consolidated = next(
            lead for lead in leads['items']
            if lead['owner_name'] == 'CURRENT OWNER 1'
        )
        self.assertEqual(consolidated['total_due'], 3000)
        self.assertEqual(consolidated['tax_id'], 'TEST-2 | TEST-1')

    def test_approved_contact_flows_into_ledger_and_call_pipeline(self):
        preview = self.client.get(
            '/api/import/approval-job/preview'
        ).get_json()
        self.client.post(
            '/api/import/approval-job/commit',
            json={
                'approval_token': preview['approval_token'],
                'confirmation': 'IMPORT VERIFIED CANDIDATES',
            },
        )
        lead = next(
            item for item in self.repository.list_leads()['items']
            if item['owner_name'] == 'CURRENT OWNER 1'
        )
        detail = self.repository.get_lead(lead['id'])
        follow_up = pd.Timestamp.today().date() + pd.Timedelta(days=2)
        call = self.client.post(
            f"/api/leads/{lead['id']}/calls",
            json={
                'direction': 'outbound',
                'outcome': 'call_later',
                'phone_number': detail['phone'],
                'next_follow_up': follow_up.isoformat(),
            },
        )

        self.assertEqual(len(detail['contact_points']), 1)
        self.assertEqual(
            detail['contact_points'][0]['source_name'],
            'test-source.xlsx',
        )
        self.assertTrue(detail['contact_points'][0]['is_primary'])
        self.assertEqual(call.status_code, 201)
        self.assertEqual(call.get_json()['lead']['status'], 'attempted_contact')

    def test_review_and_unchecked_records_never_enter_crm(self):
        preview = self.client.get(
            '/api/import/approval-job/preview'
        ).get_json()
        self.client.post(
            '/api/import/approval-job/commit',
            json={
                'approval_token': preview['approval_token'],
                'confirmation': 'IMPORT VERIFIED CANDIDATES',
            },
        )
        owners = {
            lead['owner_name'] for lead in self.repository.list_leads()['items']
        }

        self.assertNotIn('CURRENT OWNER 4', owners)
        self.assertNotIn('CURRENT OWNER 5', owners)

    def test_preview_is_locked_until_assessor_verification_is_complete(self):
        meta_path = os.path.join(
            self.output_dir,
            'approval-job_meta.json',
        )
        with open(meta_path) as file_handle:
            meta = json.load(file_handle)
        meta['status'] = 'assessor_in_progress'
        meta['assessor_progress']['remaining'] = 1
        with open(meta_path, 'w') as file_handle:
            json.dump(meta, file_handle)

        response = self.client.get('/api/import/approval-job/preview')

        self.assertEqual(response.status_code, 409)
        self.assertIn('locked', response.get_json()['error'])


if __name__ == '__main__':
    unittest.main()
