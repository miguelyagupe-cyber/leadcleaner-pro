from urllib.parse import quote


def build_alert_sms(alerts, base_url, max_length=1500):
    heading = f"LeadCleaner: {len(alerts)} urgent alert{'s' if len(alerts) != 1 else ''}"
    lines = [heading]
    for item in alerts:
        link = f"{base_url.rstrip('/')}/{item['href'].lstrip('/')}"
        lines.append(f"- {item['title']}: {item['detail']} {link}")
    message = '\n'.join(lines)
    return message if len(message) <= max_length else message[:max_length - 1].rstrip() + '…'


def send_alert_sms(config, alerts):
    if not alerts:
        return 0
    required = (
        'ALERT_SMS_TO', 'ALERT_SMS_FROM', 'PUBLIC_BASE_URL',
        'TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN',
    )
    if not config.get('ALERT_SMS_ENABLED'):
        raise ValueError('SMS alert delivery requires explicit opt-in')
    if any(not config.get(key) for key in required):
        raise ValueError('SMS alert delivery is not configured')

    endpoint = (
        'https://api.twilio.com/2010-04-01/Accounts/'
        f"{quote(config['TWILIO_ACCOUNT_SID'], safe='')}/Messages.json"
    )
    response = config['ALERT_SMS_HTTP'].post(
        endpoint,
        data={
            'To': config['ALERT_SMS_TO'],
            'From': config['ALERT_SMS_FROM'],
            'Body': build_alert_sms(alerts, config['PUBLIC_BASE_URL']),
        },
        auth=(config['TWILIO_ACCOUNT_SID'], config['TWILIO_AUTH_TOKEN']),
        timeout=20,
    )
    response.raise_for_status()
    return len(alerts)
