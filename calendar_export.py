from datetime import date, timedelta
from urllib.parse import urlencode


def _escape(value):
    return (
        str(value or '')
        .replace('\\', '\\\\')
        .replace('\r\n', '\\n')
        .replace('\n', '\\n')
        .replace(',', '\\,')
        .replace(';', '\\;')
    )


def follow_up_event(lead, app_url=''):
    follow_up = date.fromisoformat(lead['next_follow_up'][:10])
    end = follow_up + timedelta(days=1)
    owner = lead.get('owner_name') or 'Unknown owner'
    address = lead.get('property_address') or 'Property address unavailable'
    lead_url = f"{app_url.rstrip('/')}/leads?lead={lead['id']}" if app_url else ''
    description = f"LeadCleaner Pro follow-up\nProperty: {address}"
    if lead.get('phone'):
        description += f"\nPhone: {lead['phone']}"
    if lead_url:
        description += f"\nLead: {lead_url}"
    return {
        'uid': f"lead-{lead['id']}-{follow_up.isoformat()}@leadcleaner.pro",
        'title': f'Follow up — {owner}',
        'description': description,
        'location': address,
        'start': follow_up.strftime('%Y%m%d'),
        'end': end.strftime('%Y%m%d'),
    }


def event_ics(event):
    lines = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'PRODID:-//LeadCleaner Pro//Follow-ups//EN',
        'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH',
        'BEGIN:VEVENT',
        f"UID:{_escape(event['uid'])}",
        f"DTSTART;VALUE=DATE:{event['start']}",
        f"DTEND;VALUE=DATE:{event['end']}",
        f"SUMMARY:{_escape(event['title'])}",
        f"DESCRIPTION:{_escape(event['description'])}",
        f"LOCATION:{_escape(event['location'])}",
        'TRANSP:TRANSPARENT',
        'END:VEVENT',
        'END:VCALENDAR',
        '',
    ]
    return '\r\n'.join(lines).encode('utf-8')


def google_calendar_url(event):
    return 'https://calendar.google.com/calendar/render?' + urlencode({
        'action': 'TEMPLATE',
        'text': event['title'],
        'dates': f"{event['start']}/{event['end']}",
        'details': event['description'],
        'location': event['location'],
    })
