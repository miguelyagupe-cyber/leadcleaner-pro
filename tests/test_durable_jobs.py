import os
import tempfile
import unittest

import pandas as pd

from app import app, load_job_meta, materialize_artifact, persist_artifact, save_job_meta
from crm import CRMRepository


class DurableProcessingJobsTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = os.path.join(self.temp_dir.name, 'outputs')
        self.upload_dir = os.path.join(self.temp_dir.name, 'uploads')
        os.makedirs(self.output_dir)
        os.makedirs(self.upload_dir)
        self.database_path = os.path.join(self.temp_dir.name, 'crm.db')
        app.config.update(
            TESTING=True,
            DATABASE_URL=None,
            CRM_DATABASE=self.database_path,
            OUTPUT_FOLDER=self.output_dir,
            UPLOAD_FOLDER=self.upload_dir,
        )
        self.repository = CRMRepository(self.database_path)
        self.repository.initialize()
        self.client = app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_verified_job(self):
        job_id = 'durable-test-job'
        filename = 'Assessor_Verified_test.xlsx'
        workbook_path = os.path.join(self.output_dir, filename)
        frame = pd.DataFrame([{
            'Tax ID': 'TEST-100',
            'Owner Name': 'TEST OWNER ALPHA',
            'Current Assessor Owner': 'TEST OWNER ALPHA',
            'Current Owner Verification': 'Verified candidate',
            'Total Due': 4200,
        }])
        with pd.ExcelWriter(workbook_path, engine='openpyxl') as writer:
            frame.to_excel(writer, sheet_name='Prequalified - Verify', index=False)
        meta = {
            'uid': job_id,
            'source_filename': 'fictional-input.xlsx',
            'output_filename': 'Clean_test.xlsx',
            'assessor_output_filename': filename,
            'tax_year': 2023,
            'stats': {'final': 1},
            'created_at': '2026-01-01T12:00:00',
        }
        save_job_meta(meta)
        persist_artifact(job_id, 'assessor', filename, workbook_path)
        return job_id, filename, workbook_path

    def test_repository_round_trips_job_and_artifact(self):
        self.repository.save_processing_job({
            'uid': 'roundtrip-job',
            'tax_year': 2023,
            'stats': {'final': 2},
        })
        saved = self.repository.save_processing_artifact(
            'roundtrip-job', 'qualification', 'Clean_test.xlsx',
            b'fictional workbook bytes',
        )
        restored_meta = self.repository.get_processing_job('roundtrip-job')
        restored_file = self.repository.get_processing_artifact(
            job_id='roundtrip-job', kind='qualification',
        )
        self.assertEqual(restored_meta['stats']['final'], 2)
        self.assertEqual(restored_file['content'], b'fictional workbook bytes')
        self.assertEqual(saved['size_bytes'], 24)
        self.assertEqual(len(saved['content_sha256']), 64)

    def test_meta_and_workbook_recover_after_local_cache_loss(self):
        job_id, filename, workbook_path = self._create_verified_job()
        meta_path = os.path.join(self.output_dir, f'{job_id}_meta.json')
        os.remove(meta_path)
        os.remove(workbook_path)
        meta = load_job_meta(job_id)
        restored_path = materialize_artifact(
            job_id, 'assessor', filename, self.output_dir,
        )
        self.assertEqual(meta['source_filename'], 'fictional-input.xlsx')
        self.assertTrue(os.path.exists(meta_path))
        self.assertTrue(os.path.exists(restored_path))

    def test_approval_preview_survives_local_cache_loss(self):
        job_id, _, workbook_path = self._create_verified_job()
        os.remove(os.path.join(self.output_dir, f'{job_id}_meta.json'))
        os.remove(workbook_path)
        response = self.client.get(f'/api/import/{job_id}/preview')
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['approved_candidates'], 1)
        self.assertEqual(payload['total_debt'], 4200)

    def test_download_streams_database_artifact_when_cache_is_missing(self):
        _, filename, workbook_path = self._create_verified_job()
        with open(workbook_path, 'rb') as file_handle:
            expected = file_handle.read()
        os.remove(workbook_path)
        response = self.client.get(f'/download/{filename}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, expected)
        self.assertIn('attachment', response.headers['Content-Disposition'])

    def test_dashboard_reads_jobs_from_database_after_cache_loss(self):
        job_id, _, workbook_path = self._create_verified_job()
        os.remove(os.path.join(self.output_dir, f'{job_id}_meta.json'))
        os.remove(workbook_path)
        payload = self.client.get('/api/dashboard').get_json()
        self.assertTrue(payload['has_data'])
        self.assertEqual(payload['latest_job']['id'], job_id)
        self.assertTrue(payload['latest_job']['download_available'])


if __name__ == '__main__':
    unittest.main()
