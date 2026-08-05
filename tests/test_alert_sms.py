import unittest
from unittest.mock import Mock

from alert_sms import build_alert_sms, send_alert_sms


class AlertSmsTest(unittest.TestCase):
    def setUp(self):
        self.alerts = [{
            'title': 'Follow-up overdue',
            'detail': 'Call the owner today.',
            'href': '/leads?lead=12',
        }]

    def test_message_is_actionable_and_bounded(self):
        body = build_alert_sms(self.alerts, 'https://leadcleaner.example.test')
        self.assertIn('Follow-up overdue', body)
        self.assertIn('https://leadcleaner.example.test/leads?lead=12', body)
        self.assertLessEqual(len(body), 1500)

    def test_delivery_requires_explicit_opt_in(self):
        with self.assertRaisesRegex(ValueError, 'explicit opt-in'):
            send_alert_sms({'ALERT_SMS_ENABLED': False}, self.alerts)

    def test_delivery_uses_provider_credentials(self):
        response = Mock()
        http = Mock()
        http.post.return_value = response
        delivered = send_alert_sms({
            'ALERT_SMS_ENABLED': True,
            'ALERT_SMS_TO': '+19185550100',
            'ALERT_SMS_FROM': '+19185550199',
            'PUBLIC_BASE_URL': 'https://leadcleaner.example.test',
            'TWILIO_ACCOUNT_SID': 'AC-fictional',
            'TWILIO_AUTH_TOKEN': 'fictional-token',
            'ALERT_SMS_HTTP': http,
        }, self.alerts)

        self.assertEqual(delivered, 1)
        http.post.assert_called_once()
        response.raise_for_status.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
