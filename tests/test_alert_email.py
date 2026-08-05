import unittest
from unittest.mock import Mock

from alert_email import build_alert_digest, send_alert_digest


class AlertEmailTest(unittest.TestCase):
    def setUp(self):
        self.alerts = [{
            'severity': 'urgent',
            'title': 'Follow-up overdue',
            'detail': 'Call the owner today.',
            'href': '/leads?lead=12',
        }]

    def test_digest_contains_actionable_absolute_link(self):
        body = build_alert_digest(self.alerts, 'https://leadcleaner.example.test')
        self.assertIn('[URGENT] Follow-up overdue', body)
        self.assertIn('https://leadcleaner.example.test/leads?lead=12', body)

    def test_smtp_delivery_uses_tls_and_configured_credentials(self):
        smtp = Mock()
        smtp.__enter__ = Mock(return_value=smtp)
        smtp.__exit__ = Mock(return_value=False)
        factory = Mock(return_value=smtp)
        delivered = send_alert_digest({
            'ALERT_EMAIL_TO': 'daryl@example.test',
            'ALERT_EMAIL_FROM': 'alerts@example.test',
            'PUBLIC_BASE_URL': 'https://leadcleaner.example.test',
            'SMTP_HOST': 'smtp.example.test',
            'SMTP_PORT': 587,
            'SMTP_USERNAME': 'smtp-user',
            'SMTP_PASSWORD': 'fictional-password',
            'SMTP_STARTTLS': True,
            'SMTP_FACTORY': factory,
        }, self.alerts)

        self.assertEqual(delivered, 1)
        smtp.starttls.assert_called_once_with()
        smtp.login.assert_called_once_with('smtp-user', 'fictional-password')
        smtp.send_message.assert_called_once()


if __name__ == '__main__':
    unittest.main()
