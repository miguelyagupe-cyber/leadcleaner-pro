import os
import tempfile
import unittest
import io
from datetime import date, timedelta

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
        self.dataframe = dataframe
        self.job = job
        self.columns = columns
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
        self.assertEqual(
            all_leads['items'][0]['research_reason'],
            'Deceased-owner signal · Mailing signal: Strong',
        )

    def test_detailed_mailing_signal_uses_the_same_research_queue_rule(self):
        dataframe = self.dataframe.iloc[[1]].copy()
        dataframe.loc[:, 'Tax ID'] = 'C-300'
        dataframe.loc[:, 'Owner Name'] = 'TEST OWNER GAMMA'
        dataframe.loc[:, 'Absentee/Suspicious Mailing (Verify)'] = (
            'Out of state; Different mailing city'
        )
        job = {
            **self.job,
            'uid': 'job-detailed-mailing-signal',
            'source_filename': 'tulsa-detailed-signal.xlsx',
        }
        self.repository.import_leads(dataframe, job, self.columns)

        research = self.repository.list_leads(research_only=True)
        gamma = next(
            item for item in research['items']
            if item['tax_id'] == 'C-300'
        )
        metrics = self.repository.dashboard_metrics()

        self.assertEqual(gamma['status'], 'research_needed')
        self.assertEqual(
            gamma['research_reason'],
            'Mailing signal: Out of state; Different mailing city',
        )
        self.assertEqual(research['total'], 2)
        self.assertEqual(metrics['research_queue'], research['total'])

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
        self.assertEqual(
            detail['research_plan']['status'],
            'Unconfirmed — research required',
        )
        self.assertEqual(
            detail['research_plan']['sources'][0]['source_name'],
            'OSCN',
        )

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

    def test_call_outcome_updates_pipeline_and_creates_follow_up(self):
        lead_id = self.repository.list_leads()['items'][0]['id']
        follow_up = (date.today() + timedelta(days=2)).isoformat()

        result = self.repository.log_call(
            lead_id,
            {
                'direction': 'outbound',
                'outcome': 'spoke_follow_up',
                'phone_number': '0000000000',
                'duration_minutes': 7,
                'notes': 'Fictional owner requested a later conversation.',
                'next_follow_up': follow_up,
            },
        )
        lead = result['lead']

        self.assertEqual(lead['status'], 'interested')
        self.assertEqual(lead['next_follow_up'], follow_up)
        self.assertIsNotNone(lead['last_contacted_at'])
        self.assertEqual(lead['calls'][0]['outcome'], 'spoke_follow_up')
        self.assertEqual(lead['calls'][0]['duration_minutes'], 7)
        self.assertEqual(lead['activity'][0]['activity_type'], 'call_logged')

    def test_follow_up_outcomes_require_a_date(self):
        lead_id = self.repository.list_leads()['items'][0]['id']

        with self.assertRaisesRegex(ValueError, 'requires a next follow-up'):
            self.repository.log_call(
                lead_id,
                {'direction': 'outbound', 'outcome': 'no_answer'},
            )

    def test_call_api_returns_updated_lead(self):
        lead_id = self.repository.list_leads()['items'][0]['id']
        response = self.client.post(
            f'/api/leads/{lead_id}/calls',
            json={
                'direction': 'inbound',
                'outcome': 'appointment_set',
                'duration_minutes': 12,
                'next_follow_up': (date.today() + timedelta(days=1)).isoformat(),
            },
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(payload['lead']['status'], 'appointment_scheduled')
        self.assertEqual(payload['lead']['calls'][0]['direction'], 'inbound')

    def test_not_interested_closes_follow_up_without_deleting_history(self):
        lead_id = self.repository.list_leads()['items'][0]['id']
        self.repository.update_lead(
            lead_id,
            {'next_follow_up': date.today().isoformat()},
        )

        result = self.repository.log_call(
            lead_id,
            {
                'direction': 'outbound',
                'outcome': 'not_interested',
                'notes': 'Fictional owner declined further contact.',
            },
        )

        self.assertEqual(result['lead']['status'], 'disqualified')
        self.assertIsNone(result['lead']['next_follow_up'])
        self.assertEqual(len(result['lead']['calls']), 1)

    def test_today_queue_contains_due_active_follow_ups(self):
        lead_id = self.repository.list_leads()['items'][0]['id']
        self.repository.update_lead(
            lead_id,
            {'next_follow_up': date.today().isoformat()},
        )

        due = self.repository.list_leads(follow_up='due')
        metrics = self.repository.dashboard_metrics()

        self.assertEqual(due['total'], 1)
        self.assertEqual(due['items'][0]['id'], lead_id)
        self.assertEqual(metrics['follow_ups_due'], 1)

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
        self.assertIn(b'Prepare evidence', response.data)

    def test_today_page_exposes_call_and_follow_up_workspace(self):
        response = self.client.get('/today')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Daily calling queue', response.data)
        self.assertIn(b'Log a call', response.data)
        self.assertIn(b'Save call outcome', response.data)

    def test_daily_check_in_tracks_recorded_work_and_closes_day(self):
        lead_id = self.repository.list_leads()['items'][0]['id']
        started = self.repository.start_daily_check_in({
            'focus': 'Clear the probate research queue',
            'call_target': 5,
            'research_target': 2,
        })
        self.repository.log_call(
            lead_id,
            {
                'direction': 'outbound',
                'outcome': 'not_interested',
                'phone_number': '9185550100',
            },
        )
        self.repository.add_evidence(
            lead_id,
            {
                'evidence_type': 'other',
                'outcome': 'inconclusive',
                'confidence': 'weak',
                'identity_match': 'uncertain',
                'source_name': 'Manual research',
            },
        )
        progress = self.client.get('/api/today/execution').get_json()
        closed = self.client.post(
            '/api/today/check-out',
            json={'closing_notes': 'Completed the priority review.'},
        ).get_json()
        page = self.client.get('/today')

        self.assertEqual(started['check_in']['status'], 'open')
        self.assertEqual(progress['timezone'], 'America/Chicago')
        self.assertEqual(progress['check_in']['call_progress']['completed'], 1)
        self.assertEqual(progress['check_in']['research_progress']['completed'], 1)
        self.assertEqual(closed['check_in']['status'], 'completed')
        self.assertEqual(
            closed['check_in']['closing_notes'],
            'Completed the priority review.',
        )
        self.assertIn(b'Daily execution', page.data)
        self.assertIn(b'Today\xe2\x80\x99s primary focus', page.data)

    def test_operational_alerts_are_deduplicated_and_persistent(self):
        lead_id = self.repository.list_leads()['items'][0]['id']
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self.repository.update_lead(
            lead_id,
            {'next_follow_up': yesterday},
        )
        for outcome, evidence_type in (
            ('supports_deceased', 'probate_case'),
            ('supports_living', 'other'),
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
        self.repository.save_processing_job({
            'uid': 'alert-job',
            'status': 'ready_for_approval',
            'source_filename': 'tulsa-alert.xlsx',
            'stats': {'final': 1},
        })

        first = self.repository.list_operational_alerts()
        second = self.repository.list_operational_alerts()
        marked = self.client.post(
            f"/api/alerts/{first['items'][0]['id']}/read"
        )
        after = self.client.get('/api/alerts').get_json()
        page = self.client.get('/alerts')

        self.assertEqual(first['unread'], 3)
        self.assertEqual(len(first['items']), 3)
        self.assertEqual(len(second['items']), 3)
        self.assertEqual(marked.status_code, 200)
        self.assertEqual(after['unread'], 2)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Nothing important slips through.', page.data)

    def test_pipeline_board_aggregates_stages_and_debt(self):
        board = self.repository.pipeline_board()
        stages = {stage['status']: stage for stage in board['stages']}

        self.assertEqual(sum(stage['count'] for stage in board['stages']), 2)
        self.assertEqual(stages['research_needed']['count'], 1)
        self.assertEqual(stages['new']['count'], 1)
        self.assertEqual(
            sum(stage['total_debt'] for stage in board['stages']),
            14800,
        )

    def test_pipeline_page_and_api_move_lead_between_stages(self):
        lead_id = self.repository.list_leads()['items'][0]['id']
        page = self.client.get('/pipeline')
        moved = self.client.patch(
            f'/api/leads/{lead_id}',
            json={'status': 'negotiation'},
        )
        board = self.client.get('/api/pipeline').get_json()
        stages = {stage['status']: stage for stage in board['stages']}

        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Move every opportunity forward', page.data)
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(stages['negotiation']['count'], 1)
        self.assertEqual(stages['negotiation']['items'][0]['id'], lead_id)

    def test_property_workspace_consolidates_repeated_imports(self):
        repeated_job = {
            **self.job,
            'uid': 'job-2',
            'source_filename': 'tulsa-refresh.xlsx',
        }
        self.repository.import_leads(
            self.dataframe,
            repeated_job,
            self.columns,
        )

        properties = self.repository.list_properties()
        report = self.repository.acquisition_report()
        alpha = next(
            item for item in properties['items']
            if item['tax_id'] == 'A-100'
        )
        page = self.client.get('/properties')
        api = self.client.get('/api/properties?q=A-100').get_json()

        self.assertEqual(properties['total'], 2)
        self.assertEqual(alpha['record_count'], 2)
        self.assertEqual(alpha['total_due'], 12500)
        self.assertEqual(report['summary']['active_debt'], 14800)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'One property. One source of truth.', page.data)
        self.assertEqual(api['total'], 1)
        self.assertIn('Tulsa County parcel/PID', api['methodology'])

    def test_property_workspace_uses_pid_and_assessor_source_context(self):
        first = self.dataframe.iloc[[1]].copy()
        first.loc[:, 'Tax ID'] = 'TAX-ONE'
        first.loc[:, 'Owner Name'] = 'FORMER LIST OWNER'
        first.loc[:, 'PID'] = '12345-67-89-00001'
        first.loc[:, 'Property Lead Key'] = 'pid:R12345678900001'
        first.loc[:, 'Tax IDs'] = 'TAX-ONE | TAX-TWO'
        first.loc[:, 'Current Owner Verification'] = 'Verified candidate'
        first.loc[:, 'Current Assessor Owner'] = 'CURRENT ASSESSOR OWNER'
        first.loc[:, 'Assessor URL'] = 'https://example.test/assessor/R12345678900001'

        second = first.copy()
        second.loc[:, 'Tax ID'] = 'TAX-TWO'
        second.loc[:, 'TotalDue'] = 9900

        first_job = {
            **self.job,
            'uid': 'job-pid-one',
            'source_filename': 'pid-one.xlsx',
        }
        second_job = {
            **self.job,
            'uid': 'job-pid-two',
            'source_filename': 'pid-two.xlsx',
        }
        self.repository.import_leads(first, first_job, self.columns)
        self.repository.import_leads(second, second_job, self.columns)

        properties = self.repository.list_properties(search='12345-67-89-00001')
        property_item = properties['items'][0]

        self.assertEqual(properties['total'], 1)
        self.assertEqual(property_item['record_count'], 2)
        self.assertEqual(property_item['property_key'], 'pid:R12345678900001')
        self.assertEqual(property_item['parcel_id'], '12345-67-89-00001')
        self.assertEqual(property_item['tax_ids'], 'TAX-ONE | TAX-TWO')
        self.assertEqual(
            property_item['current_owner_verification'],
            'Verified candidate',
        )
        self.assertEqual(
            property_item['current_assessor_owner'],
            'CURRENT ASSESSOR OWNER',
        )

    def test_acquisition_report_uses_recorded_crm_facts(self):
        lead_id = self.repository.list_leads()['items'][0]['id']
        self.repository.add_evidence(
            lead_id,
            {
                'evidence_type': 'probate_case',
                'outcome': 'supports_deceased',
                'confidence': 'confirmed',
                'identity_match': 'exact',
                'source_name': 'Official probate docket',
            },
        )

        report = self.repository.acquisition_report()
        page = self.client.get('/reports')
        api = self.client.get('/api/reports/acquisition').get_json()

        self.assertEqual(report['summary']['active_leads'], 2)
        self.assertEqual(report['summary']['active_debt'], 14800)
        self.assertEqual(report['summary']['contactable_leads'], 1)
        self.assertEqual(report['summary']['contact_rate'], 50)
        self.assertEqual(report['summary']['confirmed_deceased'], 1)
        self.assertNotIn(
            'source_data_json',
            report['top_opportunities'][0],
        )
        self.assertIn('does not estimate revenue', report['methodology'])
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Know exactly where to act next.', page.data)
        self.assertEqual(api['summary']['active_debt'], 14800)

    def test_enrichment_exchange_caps_cost_and_preserves_conflicts(self):
        batch = self.repository.create_enrichment_batch(
            provider='Test pay-per-use source',
            cost_per_record=.15,
            budget_cap=10,
            max_records=100,
        )
        lead_id = self.repository.list_leads()['items'][0]['id']

        self.assertEqual(batch['lead_count'], 1)
        self.assertEqual(batch['estimated_cost'], .15)
        exported = self.client.get(
            f"/api/enrichment/batches/{batch['batch_id']}/export"
        )
        imported = self.client.post(
            f"/api/enrichment/batches/{batch['batch_id']}/results",
            data={
                'file': (
                    io.BytesIO(
                        f'Lead ID,Phone,Email\n{lead_id},9185550100,\n'.encode()
                    ),
                    'results.csv',
                ),
            },
            content_type='multipart/form-data',
        )
        conflict = self.repository.apply_enrichment_results(
            batch['batch_id'],
            [{'Lead ID': lead_id, 'Phone': '9185559999'}],
        )
        detail = self.repository.get_lead(lead_id)
        page = self.client.get('/enrichment')

        self.assertEqual(exported.status_code, 200)
        self.assertIn(b'Lead ID,Tax ID,Owner Name', exported.data)
        self.assertEqual(imported.status_code, 200)
        self.assertEqual(detail['phone'], '9185550100')
        self.assertEqual(conflict['result_summary']['conflicts'], 1)
        self.assertEqual(detail['activity'][0]['activity_type'], 'enrichment_conflict')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Control the cost before you enrich.', page.data)

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
