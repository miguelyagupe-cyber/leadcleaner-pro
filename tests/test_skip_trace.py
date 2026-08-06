import os
import tempfile
import unittest
from unittest.mock import Mock

import pandas as pd

from app import app
from crm import CRMRepository
from skip_trace import SkipTraceError, TracerfyProvider


class SkipTraceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repository = CRMRepository(os.path.join(self.temp_dir.name, 'crm.db'))
        self.repository.initialize()
        frame = pd.DataFrame([{
            'Tax ID': 'A', 'Owner': 'OWNER', 'Due': 12000, 'ST': '100',
            'NAME': 'MAIN', 'TYPE': 'ST', 'CITY': 'TULSA', 'ZIP': '74103',
            'Deceased': '', 'Signal': '',
        }])
        columns = {
            'tax_id': 'Tax ID', 'owner_name': 'Owner', 'total_due': 'Due',
            'street_number': 'ST', 'street_name': 'NAME', 'street_type': 'TYPE',
            'property_city': 'CITY', 'zip_code': 'ZIP',
            'deceased_flag': 'Deceased', 'mailing_signal': 'Signal',
        }
        self.repository.import_leads(frame, {
            'uid': 'campaign-job', 'source_filename': 'tulsa.xlsx',
            'output_filename': 'clean.xlsx', 'tax_year': 2026, 'stats': {'final': 1},
        }, columns)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_selective_api_results_enter_contact_ledger_and_block_dnc(self):
        campaign = self.repository.list_campaigns()[0]
        batch = self.repository.create_enrichment_batch(
            'Tracerfy', .10, 10, 65, campaign['id'], 'high_priority'
        )
        response = Mock(status_code=200)
        response.json.return_value = {
            'hit': True, 'credits_deducted': 5,
            'persons': [{
                'deceased': True,
                'phones': [
                    {'number': '9185550101', 'type': 'Mobile', 'dnc': False},
                    {'number': '9185550102', 'type': 'Mobile', 'dnc': True},
                ],
                'emails': [{'email': 'owner@example.com'}],
            }],
        }
        http = Mock()
        http.post.return_value = response
        result = self.repository.execute_skip_trace_batch(
            batch['batch_id'], TracerfyProvider('secret', http=http)
        )
        lead = self.repository.get_lead(self.repository.list_leads()['items'][0]['id'])

        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['actual_cost'], .10)
        self.assertEqual(len(lead['contact_points']), 3)
        self.assertEqual(lead['phone'], '9185550101')
        self.assertTrue(lead['deceased_flag'])
        self.assertEqual(
            next(item for item in lead['contact_points'] if item['value'] == '9185550102')['status'],
            'do_not_contact',
        )

    def test_provider_maps_credit_and_auth_failures(self):
        http = Mock()
        http.post.return_value = Mock(status_code=402)
        provider = TracerfyProvider('secret', http=http)
        with self.assertRaisesRegex(SkipTraceError, 'insufficient credits'):
            provider.lookup({'property_address': '1 Main St', 'property_city': 'Tulsa'})
