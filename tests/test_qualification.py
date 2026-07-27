import unittest

import pandas as pd

from qualification import qualify_leads


class QualificationEngineTest(unittest.TestCase):
    def setUp(self):
        self.dataframe = pd.DataFrame(
            [
                {
                    'Tax ID': 6100000,
                    'Owner Name': 'TULSA FITNESS CENTER',
                    'TotalDue': 9000,
                    'Address': '1 BUSINESS RD',
                    'OWNR_ADDR 6': 'TULSA',
                    'OWNR_ADDR ST': 'OK',
                    'ST_NO': '1',
                    'ST_NAME': 'BUSINESS',
                    'ST_STREET_TYPE': 'RD',
                    'ST_CITY': 'CITY OF TULSA',
                },
                {
                    'Tax ID': 100,
                    'Owner Name': 'DOE, JANE ESTATE',
                    'TotalDue': 6000,
                    'Address': 'PO BOX 12',
                    'OWNR_ADDR 6': 'DALLAS',
                    'OWNR_ADDR ST': 'TX',
                    'ST_NO': '10',
                    'ST_NAME': 'MAIN',
                    'ST_STREET_TYPE': 'ST',
                    'ST_CITY': 'CITY OF TULSA',
                },
                {
                    'Tax ID': 200,
                    'Owner Name': 'SMITH FAMILY TRUST',
                    'TotalDue': 2500,
                    'Address': '20 MAIN ST',
                    'OWNR_ADDR 6': 'TULSA',
                    'OWNR_ADDR ST': 'OK',
                    'ST_NO': '20',
                    'ST_NAME': 'MAIN',
                    'ST_STREET_TYPE': 'ST',
                    'ST_CITY': 'CITY OF TULSA',
                },
                {
                    'Tax ID': 300,
                    'Owner Name': 'BROWN, JOHN',
                    'TotalDue': 2200,
                    'Address': '',
                    'OWNR_ADDR 6': 'TULSA',
                    'OWNR_ADDR ST': 'OK',
                    'ST_NO': '30',
                    'ST_NAME': '',
                    'ST_STREET_TYPE': 'ST',
                    'ST_CITY': 'CITY OF TULSA',
                },
            ]
        )

    def test_separates_qualified_review_and_excluded_records(self):
        result = qualify_leads(self.dataframe, 2023)

        self.assertEqual(result['stats']['qualified'], 2)
        self.assertEqual(result['stats']['review'], 1)
        self.assertEqual(result['stats']['excluded'], 1)
        self.assertEqual(
            result['excluded'].iloc[0]['Owner Type'],
            'Business personal property',
        )

    def test_deceased_and_absentee_are_independent_evidence(self):
        result = qualify_leads(self.dataframe, 2023)
        estate = result['deceased'].iloc[0]

        self.assertEqual(estate['Deceased Confidence'], 'High')
        self.assertIn('Estate', estate['Deceased Evidence'])
        self.assertIn('Out of state', estate['Absentee Signal'])
        self.assertEqual(result['stats']['deceased_high_confidence'], 1)

    def test_trusts_remain_qualified(self):
        result = qualify_leads(self.dataframe, 2023)
        trust = result['qualified'][
            result['qualified']['Owner Type'] == 'Trust'
        ].iloc[0]

        self.assertEqual(trust['Decision Reason'], 'Trust retained under acquisition rules')

    def test_does_not_claim_row_level_year_validation_without_source_column(self):
        result = qualify_leads(self.dataframe, 2023)

        self.assertFalse(result['stats']['tax_year_row_level_verified'])
        self.assertIn(
            'source has no row-level tax year',
            result['audit'].iloc[0]['Tax Year Provenance'],
        )


if __name__ == '__main__':
    unittest.main()
