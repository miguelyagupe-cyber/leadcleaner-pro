import unittest

from runtime_config import production_readiness


class ProductionReadinessTest(unittest.TestCase):
    def base_config(self):
        return {
            'DATABASE_URL': 'postgresql://user:password@db/leadcleaner',
            'SECRET_KEY': 's' * 48,
            'APP_LOGIN_EMAIL': 'daryl@example.test',
            'APP_LOGIN_PASSWORD': 'fictional-password',
            'ALERT_SMS_ENABLED': False,
        }

    def test_minimum_production_configuration_is_ready(self):
        self.assertEqual(
            production_readiness(self.base_config()),
            {'status': 'ready', 'missing': [], 'invalid': []},
        )

    def test_required_settings_and_weak_secret_are_reported(self):
        config = self.base_config()
        config['DATABASE_URL'] = ''
        config['APP_LOGIN_PASSWORD'] = ''
        config['SECRET_KEY'] = 'short'

        result = production_readiness(config)

        self.assertEqual(result['status'], 'not_ready')
        self.assertEqual(result['missing'], ['APP_LOGIN_PASSWORD', 'DATABASE_URL'])
        self.assertEqual(result['invalid'], ['SECRET_KEY'])

    def test_runtime_generated_secret_is_not_production_ready(self):
        config = self.base_config()
        config['SECRET_KEY_CONFIGURED'] = False

        result = production_readiness(config)

        self.assertIn('SECRET_KEY', result['missing'])

    def test_optional_integrations_must_be_configured_as_complete_groups(self):
        config = self.base_config()
        config['GOOGLE_DRIVE_CLIENT_ID'] = 'client-id'
        config['ALERT_EMAIL_TO'] = 'daryl@example.test'
        config['ALERT_SMS_ENABLED'] = True

        result = production_readiness(config)

        self.assertIn('GOOGLE_DRIVE_API_KEY', result['missing'])
        self.assertIn('SMTP_HOST', result['missing'])
        self.assertIn('TWILIO_AUTH_TOKEN', result['missing'])
        self.assertIn('ALERT_DELIVERY_TOKEN', result['missing'])

    def test_external_links_and_delivery_token_are_hardened(self):
        config = self.base_config()
        config.update({
            'ALERT_EMAIL_TO': 'daryl@example.test',
            'ALERT_EMAIL_FROM': 'alerts@example.test',
            'PUBLIC_BASE_URL': 'http://insecure.example.test',
            'SMTP_HOST': 'smtp.example.test',
            'ALERT_DELIVERY_TOKEN': 'short',
        })

        result = production_readiness(config)

        self.assertEqual(
            result['invalid'],
            ['ALERT_DELIVERY_TOKEN', 'PUBLIC_BASE_URL'],
        )


if __name__ == '__main__':
    unittest.main()
