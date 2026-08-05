import smtplib
from email.message import EmailMessage
from urllib.parse import urljoin


def build_alert_digest(alerts, base_url):
    lines = [
        f"{len(alerts)} LeadCleaner alert{'s' if len(alerts) != 1 else ''} need attention.",
        '',
    ]
    for item in alerts:
        lines.extend([
            f"[{item['severity'].upper()}] {item['title']}",
            item['detail'],
            urljoin(base_url.rstrip('/') + '/', item['href'].lstrip('/')),
            '',
        ])
    lines.append('Open LeadCleaner to review and clear these alerts.')
    return '\n'.join(lines)


def send_alert_digest(config, alerts):
    if not alerts:
        return 0
    required = ('ALERT_EMAIL_TO', 'ALERT_EMAIL_FROM', 'SMTP_HOST')
    if any(not config.get(key) for key in required):
        raise ValueError('Email alert delivery is not configured')

    message = EmailMessage()
    message['To'] = config['ALERT_EMAIL_TO']
    message['From'] = config['ALERT_EMAIL_FROM']
    message['Subject'] = (
        f"LeadCleaner · {len(alerts)} operational "
        f"alert{'s' if len(alerts) != 1 else ''}"
    )
    message.set_content(build_alert_digest(alerts, config['PUBLIC_BASE_URL']))

    factory = config.get('SMTP_FACTORY', smtplib.SMTP)
    with factory(config['SMTP_HOST'], int(config.get('SMTP_PORT', 587)), timeout=20) as smtp:
        if config.get('SMTP_STARTTLS', True):
            smtp.starttls()
        if config.get('SMTP_USERNAME'):
            smtp.login(config['SMTP_USERNAME'], config.get('SMTP_PASSWORD', ''))
        smtp.send_message(message)
    return len(alerts)
