import unittest

import pandas as pd

from qualification import qualify_leads


class QualificationEngineTest(unittest.TestCase):
    def setUp(self):
        self.dataframe = pd.DataFrame(
            [
                {
                    'Tax ID': 6100000,
                    'PID': '00000-00-00-00001',
                    'Owner Name': 'TULSA FITNESS CENTER',
                    'TotalDue': 9000,
                    'Address': '1 BUSINESS RD',
                    'OWNR_ADDR 6': 'TULSA',
                    'OWNR_ADDR ST': 'OK',
                    'ST_NO': '1',
                    'ST_NAME': 'BUSINESS',
                    'ST_STREET_TYPE': 'RD',
                    'ST_CITY': 'CITY OF TULSA',
                    'Legal Description': 'BUSINESS PERSONAL-- |',
                },
                {
                    'Tax ID': 100,
                    'PID': '12345-67-89-00010',
                    'Owner Name': 'DOE, JANE ESTATE',
                    'TotalDue': 6000,
                    'Address': 'PO BOX 12',
                    'OWNR_ADDR 6': 'DALLAS',
                    'OWNR_ADDR ST': 'TX',
                    'ST_NO': '10',
                    'ST_NAME': 'MAIN',
                    'ST_STREET_TYPE': 'ST',
                    'ST_CITY': 'CITY OF TULSA',
                    'Legal Description': 'LT 1 BLK 1 | SAMPLE',
                },
                {
                    'Tax ID': 200,
                    'PID': '12345-67-89-00020',
                    'Owner Name': 'SMITH FAMILY TRUST',
                    'TotalDue': 2500,
                    'Address': '20 MAIN ST',
                    'OWNR_ADDR 6': 'TULSA',
                    'OWNR_ADDR ST': 'OK',
                    'ST_NO': '20',
                    'ST_NAME': 'MAIN',
                    'ST_STREET_TYPE': 'ST',
                    'ST_CITY': 'CITY OF TULSA',
                    'Legal Description': 'LT 2 BLK 1 | SAMPLE',
                },
                {
                    'Tax ID': 300,
                    'PID': '12345-67-89-00030',
                    'Owner Name': 'BROWN, JOHN',
                    'TotalDue': 2200,
                    'Address': '',
                    'OWNR_ADDR 6': 'TULSA',
                    'OWNR_ADDR ST': 'OK',
                    'ST_NO': '30',
                    'ST_NAME': '',
                    'ST_STREET_TYPE': 'ST',
                    'ST_CITY': 'CITY OF TULSA',
                    'Legal Description': 'LT 3 BLK 1 | SAMPLE',
                },
            ]
        )

    def test_separates_prequalified_review_and_excluded_records(self):
        result = qualify_leads(self.dataframe, 2023)

        self.assertEqual(result['stats']['prequalified'], 2)
        self.assertEqual(result['stats']['qualified'], 0)
        self.assertEqual(result['stats']['review'], 1)
        self.assertEqual(result['stats']['excluded'], 1)
        self.assertEqual(
            result['excluded'].iloc[0]['Owner Type'],
            'Business personal property',
        )

    def test_deceased_and_absentee_are_independent_evidence(self):
        result = qualify_leads(self.dataframe, 2023)
        estate = result['deceased'].iloc[0]

        self.assertIn('record required', estate['Deceased Research Status'])
        self.assertIn('Estate', estate['Deceased Evidence'])
        self.assertIn('Out of state', estate['Absentee Signal'])
        self.assertEqual(result['stats']['deceased_text_signals'], 1)
        self.assertEqual(result['stats']['deceased_confirmed'], 0)
        self.assertFalse(estate['Probate Confirmed'])

    def test_trusts_remain_prequalified(self):
        result = qualify_leads(self.dataframe, 2023)
        trust = result['qualified'][
            result['qualified']['Owner Type'] == 'Trust'
        ].iloc[0]

        self.assertEqual(
            trust['Decision Reason'],
            'Trust retained pending current-owner verification',
        )
        self.assertEqual(trust['Current Owner Verification'], 'Not checked')
        self.assertIn('accountNo=R12345678900020', trust['Assessor URL'])

    def test_representative_and_life_estate_are_not_death_proof(self):
        variants = self.dataframe.iloc[[1]].copy()
        representative = variants.copy()
        representative['Owner Name'] = 'ARRIAGA, HERLINDA PR OF THE ESTATE'
        life_estate = variants.copy()
        life_estate['Owner Name'] = 'LEVIN, STEPHEN LF ESTATE'
        result = qualify_leads(
            pd.concat([representative, life_estate], ignore_index=True),
            2023,
        )

        statuses = result['deceased']['Deceased Research Status'].tolist()
        self.assertIn('Representative named - owner may be living', statuses)
        self.assertIn('Life estate - not death evidence by itself', statuses)
        self.assertEqual(result['stats']['deceased_confirmed'], 0)

    def test_mobile_home_and_farm_personal_property_require_review(self):
        variants = self.dataframe.iloc[[0, 0]].copy()
        variants['Owner Name'] = ['PERSON, MOBILE', 'PERSON, FARM']
        variants['Legal Description'] = [
            'MOBILE HOME PERSONAL-- |',
            'FARM PERSONAL-- |',
        ]
        result = qualify_leads(variants, 2023)

        self.assertEqual(result['stats']['review'], 2)
        self.assertEqual(result['stats']['review_mobile_home_personal'], 1)
        self.assertEqual(result['stats']['review_farm_personal'], 1)

    def test_does_not_claim_row_level_year_validation_without_source_column(self):
        result = qualify_leads(self.dataframe, 2023)

        self.assertFalse(result['stats']['tax_year_row_level_verified'])
        self.assertIn(
            'source has no row-level tax year',
            result['audit'].iloc[0]['Tax Year Provenance'],
        )

    def test_exclusion_counts_are_mutually_exclusive_and_reconcile(self):
        result = qualify_leads(self.dataframe, 2023)
        stats = result['stats']

        self.assertEqual(stats['excluded_business_personal_property'], 1)
        self.assertEqual(stats['excluded_cannabis'], 0)
        self.assertEqual(stats['excluded_business_entity'], 0)
        self.assertEqual(stats['excluded_government_nonprofit'], 0)
        self.assertTrue(stats['classification_reconciled'])
        self.assertEqual(
            stats['prequalified'] + stats['review'] + stats['excluded'],
            stats['after_year_filter'],
        )


if __name__ == '__main__':
    unittest.main()
