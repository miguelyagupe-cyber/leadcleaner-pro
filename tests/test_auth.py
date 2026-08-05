import unittest

from app import LOGIN_ATTEMPTS, app


class AuthenticationTest(unittest.TestCase):
    def setUp(self):
        app.config.update(
            TESTING=True,
            TEST_AUTH_ENABLED=True,
            SECRET_KEY='test-secret-key',
            APP_LOGIN_EMAIL='daryl@example.test',
            APP_LOGIN_PASSWORD='fictional-password',
            SESSION_COOKIE_SECURE=False,
        )
        LOGIN_ATTEMPTS.clear()
        self.client = app.test_client()

    def tearDown(self):
        app.config['TEST_AUTH_ENABLED'] = False
        LOGIN_ATTEMPTS.clear()

    def _csrf(self):
        self.client.get('/login')
        with self.client.session_transaction() as session:
            return session['csrf_token']

    def _login(self):
        token = self._csrf()
        return self.client.post(
            '/login',
            data={
                'email': 'daryl@example.test',
                'password': 'fictional-password',
                'csrf_token': token,
            },
        )

    def test_private_pages_redirect_and_apis_reject_anonymous_access(self):
        page = self.client.get('/')
        api = self.client.get('/api/dashboard')

        self.assertEqual(page.status_code, 302)
        self.assertIn('/login', page.headers['Location'])
        self.assertEqual(api.status_code, 401)

    def test_health_remains_public_and_security_headers_are_present(self):
        response = self.client.get('/api/health')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])

    def test_readiness_is_public_but_rejects_incomplete_production_config(self):
        response = self.client.get('/api/readiness')

        self.assertEqual(response.status_code, 503)
        payload = response.get_json()
        self.assertEqual(payload['status'], 'not_ready')
        self.assertIn('DATABASE_URL', payload['missing'])
        self.assertNotIn('fictional-password', response.get_data(as_text=True))

    def test_valid_login_creates_private_session(self):
        response = self._login()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], '/')
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_invalid_credentials_do_not_authenticate(self):
        token = self._csrf()
        response = self.client.post(
            '/login',
            data={
                'email': 'daryl@example.test',
                'password': 'wrong-password',
                'csrf_token': token,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'email or password is incorrect', response.data)
        self.assertEqual(self.client.get('/api/dashboard').status_code, 401)

    def test_mutations_require_csrf_after_login(self):
        self._login()
        rejected = self.client.post('/process')
        with self.client.session_transaction() as session:
            token = session['csrf_token']
        accepted_by_security = self.client.post(
            '/process',
            headers={'X-CSRF-Token': token},
        )

        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(accepted_by_security.status_code, 400)

    def test_logout_destroys_session(self):
        self._login()
        with self.client.session_transaction() as session:
            token = session['csrf_token']
        response = self.client.post(
            '/logout',
            data={'csrf_token': token},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get('/api/dashboard').status_code, 401)

    def test_repeated_failures_are_rate_limited(self):
        token = self._csrf()
        for _ in range(5):
            self.client.post(
                '/login',
                data={
                    'email': 'daryl@example.test',
                    'password': 'wrong-password',
                    'csrf_token': token,
                },
            )
        blocked = self.client.post(
            '/login',
            data={
                'email': 'daryl@example.test',
                'password': 'fictional-password',
                'csrf_token': token,
            },
        )

        self.assertIn(b'Too many sign-in attempts', blocked.data)
        self.assertEqual(self.client.get('/api/dashboard').status_code, 401)


if __name__ == '__main__':
    unittest.main()
