import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests


ASSESSOR_BASE_URL = 'https://assessor.tulsacounty.org/Property/Info'
ALLOWED_ACCOUNT_TYPES = {'Residential', 'Agricultural'}


def normalize_account_no(pid):
    value = re.sub(r'[^A-Z0-9]', '', str(pid or '').upper())
    if not value:
        return ''
    return value if value.startswith('R') else f'R{value}'


def normalize_owner(value):
    return re.sub(r'[^A-Z0-9]', '', str(value or '').upper())


def _owner_tokens(value):
    ignored = {
        'AND', 'OF', 'THE', 'TRUST', 'TRUSTEE', 'ESTATE', 'HEIRS',
        'PR', 'REPRESENTATIVE', 'JR', 'SR',
    }
    return {
        token
        for token in re.findall(r'[A-Z0-9]+', str(value or '').upper())
        if token not in ignored and len(token) > 1
    }


def owner_match(source_owner, current_owner):
    source = normalize_owner(source_owner)
    current = normalize_owner(current_owner)
    if not source or not current:
        return 'unknown'
    if source == current or source in current or current in source:
        return 'match'
    source_tokens = _owner_tokens(source_owner)
    current_tokens = _owner_tokens(current_owner)
    if len(source_tokens & current_tokens) >= 2:
        return 'match'
    return 'changed'


def _clean_html_text(html):
    text = re.sub(r'<script\b[^>]*>.*?</script>', ' ', html, flags=re.I | re.S)
    text = re.sub(r'<style\b[^>]*>.*?</style>', ' ', text, flags=re.I | re.S)
    text = re.sub(r'<[^>]+>', '\n', text)
    text = (
        text.replace('&amp;', '&')
        .replace('&#39;', "'")
        .replace('&nbsp;', ' ')
    )
    return '\n'.join(
        line.strip() for line in text.splitlines() if line.strip()
    )


def _value_after_label(text, label):
    lines = text.splitlines()
    target = label.upper()
    for index, line in enumerate(lines):
        normalized = re.sub(r'\s+', ' ', line).strip().upper().rstrip(':')
        if normalized == target:
            for candidate in lines[index + 1 : index + 5]:
                value = candidate.strip()
                if value and value.upper().rstrip(':') != target:
                    return value
    return ''


@dataclass(frozen=True)
class AssessorResult:
    account_no: str
    status: str
    source_url: str
    current_owner: str = ''
    account_type: str = ''
    vacant: bool = False
    error: str = ''
    fetched_at: str = ''

    def as_dict(self):
        return self.__dict__.copy()


def parse_assessor_page(html, account_no, source_url):
    text = _clean_html_text(html)
    current_owner = (
        _value_after_label(text, 'Current Owner')
        or _value_after_label(text, 'Owner Name')
    )
    account_type = _value_after_label(text, 'Account Type')
    vacant = bool(re.search(r'\bVACANT\b', text, flags=re.I))
    if not current_owner and not account_type:
        return AssessorResult(
            account_no=account_no,
            status='parse_error',
            source_url=source_url,
            error='Expected owner and account-type fields were not found',
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )
    return AssessorResult(
        account_no=account_no,
        status='verified',
        source_url=source_url,
        current_owner=current_owner,
        account_type=account_type,
        vacant=vacant,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )


class TulsaAssessorClient:
    def __init__(self, session=None, timeout=15, delay_seconds=0.5):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.delay_seconds = max(float(delay_seconds), 0)
        self.session.headers.update(
            {
                'User-Agent': (
                    'LeadCleanerPro/1.0 '
                    '(property research; low-rate cached requests)'
                )
            }
        )

    def fetch(self, pid):
        account_no = normalize_account_no(pid)
        source_url = f'{ASSESSOR_BASE_URL}?accountNo={account_no}'
        if not account_no:
            return AssessorResult(
                account_no='',
                status='invalid_account',
                source_url=source_url,
                error='Missing PID/account number',
                fetched_at=datetime.now(timezone.utc).isoformat(),
            )
        try:
            response = self.session.get(source_url, timeout=self.timeout)
            if response.status_code == 404:
                return AssessorResult(
                    account_no=account_no,
                    status='not_found',
                    source_url=source_url,
                    error='Property account was not found',
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                )
            response.raise_for_status()
            return parse_assessor_page(response.text, account_no, source_url)
        except requests.RequestException as error:
            return AssessorResult(
                account_no=account_no,
                status='request_error',
                source_url=source_url,
                error=str(error)[:500],
                fetched_at=datetime.now(timezone.utc).isoformat(),
            )
        finally:
            if self.delay_seconds:
                time.sleep(self.delay_seconds)


def verification_decision(source_owner, result):
    if result.status != 'verified':
        return 'Not verified', 'Assessor lookup did not produce reliable data'
    match = owner_match(source_owner, result.current_owner)
    if match == 'changed':
        return 'Review', 'Current Assessor owner differs from source list'
    if not result.account_type:
        return 'Review', 'Assessor account type is missing'
    if result.account_type not in ALLOWED_ACCOUNT_TYPES:
        return 'Review', f'{result.account_type} account requires acquisition-rule review'
    if match == 'unknown':
        return 'Review', 'Current owner could not be compared'
    return 'Verified candidate', 'Current owner and account type passed verification'
