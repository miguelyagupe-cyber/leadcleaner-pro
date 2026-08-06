"""Provider-neutral selective skip tracing with a Tracerfy adapter."""

from dataclasses import dataclass

import requests


class SkipTraceError(RuntimeError):
    pass


@dataclass(frozen=True)
class SkipTraceResult:
    hit: bool
    credits: int
    phones: tuple[dict, ...]
    emails: tuple[dict, ...]
    deceased: bool | None = None


class TracerfyProvider:
    name = 'Tracerfy'
    cost_per_hit = 0.10

    def __init__(self, token, http=None, base_url='https://tracerfy.com/v1/api'):
        self.token = str(token or '').strip()
        self.http = http or requests
        self.base_url = base_url.rstrip('/')
        if not self.token:
            raise ValueError('Tracerfy API token is not configured')

    def lookup(self, lead):
        payload = {
            'address': str(lead.get('property_address') or '').strip(),
            'city': str(lead.get('property_city') or '').strip(),
            'state': str(lead.get('property_state') or 'OK').strip().upper(),
            'zip': str(lead.get('zip_code') or '').strip(),
            'find_owner': True,
        }
        if not payload['address'] or not payload['city']:
            raise SkipTraceError('Property address and city are required')
        try:
            response = self.http.post(
                f'{self.base_url}/trace/lookup/', json=payload,
                headers={'Authorization': f'Bearer {self.token}'}, timeout=20,
            )
        except requests.RequestException as error:
            raise SkipTraceError('Tracerfy is temporarily unavailable') from error
        if response.status_code == 402:
            raise SkipTraceError('Tracerfy account has insufficient credits')
        if response.status_code in (401, 403):
            raise SkipTraceError('Tracerfy authorization failed')
        if response.status_code >= 400:
            raise SkipTraceError('Tracerfy rejected the lookup')
        data = response.json()
        phones, emails, deceased = [], [], None
        for person in data.get('persons') or []:
            if person.get('deceased') is not None:
                deceased = bool(person['deceased']) if deceased is None else deceased
            phones.extend(person.get('phones') or [])
            emails.extend(person.get('emails') or [])
        contacts = data.get('contacts') or {}
        phones.extend(contacts.get('phones') or [])
        emails.extend(contacts.get('emails') or [])
        return SkipTraceResult(
            hit=bool(data.get('hit')), credits=int(data.get('credits_deducted') or 0),
            phones=tuple(phones), emails=tuple(emails), deceased=deceased,
        )
