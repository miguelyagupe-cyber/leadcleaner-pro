from urllib.parse import urlparse


REQUIRED_PRODUCTION_SETTINGS = (
    'DATABASE_URL',
    'SECRET_KEY',
    'APP_LOGIN_EMAIL',
    'APP_LOGIN_PASSWORD',
)


def production_readiness(config):
    missing = [name for name in REQUIRED_PRODUCTION_SETTINGS if not config.get(name)]
    if config.get('SECRET_KEY_CONFIGURED') is False:
        missing.append('SECRET_KEY')
    invalid = []

    secret_key = config.get('SECRET_KEY')
    if secret_key and len(secret_key) < 32:
        invalid.append('SECRET_KEY')
    database_url = str(config.get('DATABASE_URL') or '')
    if database_url and not database_url.startswith(('postgresql://', 'postgresql+psycopg://')):
        invalid.append('DATABASE_URL')

    drive_values = ('GOOGLE_DRIVE_CLIENT_ID', 'GOOGLE_DRIVE_API_KEY')
    if any(config.get(name) for name in drive_values):
        missing.extend(name for name in drive_values if not config.get(name))

    email_values = (
        'ALERT_EMAIL_TO', 'ALERT_EMAIL_FROM', 'PUBLIC_BASE_URL',
        'SMTP_HOST', 'ALERT_DELIVERY_TOKEN',
    )
    if any(config.get(name) for name in email_values):
        missing.extend(name for name in email_values if not config.get(name))

    if config.get('ALERT_SMS_ENABLED'):
        sms_values = (
            'ALERT_SMS_TO', 'ALERT_SMS_FROM', 'TWILIO_ACCOUNT_SID',
            'TWILIO_AUTH_TOKEN', 'ALERT_DELIVERY_TOKEN',
        )
        missing.extend(name for name in sms_values if not config.get(name))

    delivery_token = config.get('ALERT_DELIVERY_TOKEN')
    if delivery_token and len(delivery_token) < 32:
        invalid.append('ALERT_DELIVERY_TOKEN')
    public_url = config.get('PUBLIC_BASE_URL')
    if public_url:
        parsed = urlparse(public_url)
        if parsed.scheme != 'https' or not parsed.netloc:
            invalid.append('PUBLIC_BASE_URL')

    missing = sorted(set(missing))
    invalid = sorted(set(invalid))
    return {
        'status': 'ready' if not missing and not invalid else 'not_ready',
        'missing': missing,
        'invalid': invalid,
    }
