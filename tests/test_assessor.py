import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

import pandas as pd

from app import app
from assessor import (
    AssessorResult,
    normalize_account_no,
    owner_match,
    parse_assessor_page,
    verification_decision,
)


SAMPLE_PAGE = """
<html><body>
  <div>Owner Name:</div><div>DOE, JANE</div>
  <div>Account Type:</div><div>Residential</div>
  <span class="badge">Vacant</span>
</body></html>
"""


class FakeAssessorClient:
    calls = 0

    def fetch(self, pid):
        self.__class__.calls += 1
        account_no = normalize_account_no(pid)
        return AssessorResult(
            account_no=account_no,
            status='verified',
            source_url=f'https://example.test/{account_no}',
            current_owner='DOE, JANE',
            account_type='Residential',
            vacant=False,
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )


class AssessorTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = os.path.join(self.temp_dir.name, 'outputs')
        os.makedirs(self.output_dir)
        app.config.update(
            TESTING=True,
            DATABASE_URL=None,
            CRM_DATABASE=os.path.join(self.temp_dir.name, 'crm.db'),
            OUTPUT_FOLDER=self.output_dir,
            ASSESSOR_BATCH_LIMIT=2,
            ASSESSOR_CLIENT_FACTORY=FakeAssessorClient,
        )
        FakeAssessorClient.calls = 0
        self.client = app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parses_official_fields_without_claiming_more_than_page_shows(self):
        result = parse_assessor_page(
            SAMPLE_PAGE,
            'R123',
            'https://example.test/R123',
        )

        self.assertEqual(result.status, 'verified')
        self.assertEqual(result.current_owner, 'DOE, JANE')
        self.assertEqual(result.account_type, 'Residential')
        self.assertTrue(result.vacant)
        self.assertEqual(owner_match('JANE DOE', result.current_owner), 'match')
        self.assertEqual(owner_match('JOHN SMITH', result.current_owner), 'changed')

    def test_decision_requires_owner_match_and_allowed_account_type(self):
        result = parse_assessor_page(
            SAMPLE_PAGE,
            'R123',
            'https://example.test/R123',
        )
        decision, _ = verification_decision('DOE, JANE', result)
        self.assertEqual(decision, 'Verified candidate')

        commercial = AssessorResult(
            **{**result.as_dict(), 'account_type': 'Commercial'}
        )
        decision, _ = verification_decision('DOE, JANE', commercial)
        self.assertEqual(decision, 'Review')

    def test_batch_verification_persists_progress_and_reuses_cache(self):
        dataframe = pd.DataFrame(
            [
                {
                    'PID': '12345-67-89-00001',
                    'Owner Name': 'DOE, JANE',
                    'Current Owner Verification': 'Not checked',
                },
                {
                    'PID': '12345-67-89-00002',
                    'Owner Name': 'DOE, JANE',
                    'Current Owner Verification': 'Not checked',
                },
                {
                    'PID': '12345-67-89-00003',
                    'Owner Name': 'DOE, JANE',
                    'Current Owner Verification': 'Not checked',
                },
            ]
        )
        workbook = os.path.join(self.output_dir, 'clean.xlsx')
        with pd.ExcelWriter(workbook, engine='openpyxl') as writer:
            dataframe.to_excel(
                writer,
                sheet_name='Prequalified - Verify',
                index=False,
            )
        with open(os.path.join(self.output_dir, 'job-1_meta.json'), 'w') as file_handle:
            json.dump(
                {
                    'uid': 'job-1',
                    'source_filename': 'source.xlsx',
                    'output_filename': 'clean.xlsx',
                    'tax_year': 2023,
                    'stats': {'prequalified': 3},
                },
                file_handle,
            )

        first = self.client.post(
            '/api/assessor/verify/job-1',
            json={'limit': 2},
        ).get_json()
        second = self.client.post(
            '/api/assessor/verify/job-1',
            json={'limit': 2},
        ).get_json()

        self.assertEqual(first['processed'], 2)
        self.assertEqual(first['remaining_estimate'], 1)
        self.assertEqual(second['processed'], 1)
        self.assertEqual(second['remaining_estimate'], 0)
        self.assertEqual(FakeAssessorClient.calls, 3)
        self.assertTrue(
            os.path.exists(
                os.path.join(self.output_dir, second['download_file'])
            )
        )


if __name__ == '__main__':
    unittest.main()
