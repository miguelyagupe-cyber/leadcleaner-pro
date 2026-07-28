import unittest

from research_plan import build_research_plan, normalized_subject


class ResearchPlanTest(unittest.TestCase):
    def test_normalizes_primary_subject_without_claiming_identity(self):
        self.assertEqual(
            normalized_subject('LEVIN, STEPHEN A & BARBARA L LF ESTATE'),
            'LEVIN, STEPHEN A',
        )
        self.assertEqual(
            normalized_subject('ARRIAGA, HERLINDA M PR OF THE ESTATE'),
            'ARRIAGA, HERLINDA M',
        )

    def test_estate_signal_creates_immediate_official_research_plan(self):
        plan = build_research_plan(
            {
                'owner_name': 'DOE, JANE ESTATE',
                'deceased_flag': True,
                'mailing_signal': 'Strong',
                'total_due': 12000,
            }
        )

        self.assertEqual(plan['priority'], 'Immediate')
        self.assertEqual(plan['score'], 90)
        self.assertIn('additional identity detail', plan['identity_rule'])
        self.assertEqual(
            [source['id'] for source in plan['sources']],
            ['oscn', 'ok2explore', 'tulsa_probate', 'land_records'],
        )

    def test_absentee_signal_remains_research_not_death_confirmation(self):
        plan = build_research_plan(
            {
                'owner_name': 'DOE, JANE',
                'deceased_flag': False,
                'mailing_signal': 'Weak',
                'total_due': 2500,
            }
        )

        self.assertEqual(plan['priority'], 'Standard')
        self.assertIn('Weak mailing', plan['signals'][0])
        self.assertEqual(plan['status'], 'Unconfirmed — research required')


if __name__ == '__main__':
    unittest.main()
