import json
import re


OFFICIAL_RESEARCH_SOURCES = (
    {
        'id': 'oscn',
        'title': 'Search Tulsa probate cases',
        'source_name': 'OSCN',
        'evidence_type': 'probate_case',
        'url': 'https://www.oscn.net/dockets/Search.aspx',
        'instruction': (
            'Select Tulsa County, search the owner as a party, and limit the '
            'district case type to probate when possible.'
        ),
        'limitation': (
            'OSCN may require human verification and states that its online '
            'docket is not an official court record.'
        ),
    },
    {
        'id': 'ok2explore',
        'title': 'Search Oklahoma death index',
        'source_name': 'Oklahoma Vital Records — OK2Explore',
        'evidence_type': 'death_index',
        'url': 'https://ok2explore.health.ok.gov/App/DeathSearch',
        'instruction': (
            'Search the normalized owner name and compare county, event date, '
            'and any available identity details.'
        ),
        'limitation': (
            'The free index includes Oklahoma deaths only after they are at '
            'least five years old. No result does not support that a person is living.'
        ),
    },
    {
        'id': 'tulsa_probate',
        'title': 'Open Tulsa County probate office',
        'source_name': 'Tulsa County Court Clerk',
        'evidence_type': 'probate_case',
        'url': 'https://courtclerk.tulsacounty.org/Home/Probate',
        'instruction': (
            'Use the Court Clerk as the official follow-up when an online '
            'docket needs confirmation or an archived probate record.'
        ),
        'limitation': (
            'A manual records request or direct contact may be required.'
        ),
    },
    {
        'id': 'land_records',
        'title': 'Check recorded land documents',
        'source_name': 'Tulsa County Clerk — Acclaim',
        'evidence_type': 'other',
        'url': 'https://acclaim.tulsacounty.org/AcclaimWeb/Search/SearchTypeParcel',
        'instruction': (
            'Search the parcel or owner for deeds, personal-representative '
            'documents, and transfers that explain a current-owner change.'
        ),
        'limitation': (
            'A transfer or mailing-address change is a research signal, not '
            'proof of death by itself.'
        ),
    },
)


def _source_row(lead):
    value = lead.get('source_row_json')
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value or '{}')
    except (TypeError, ValueError):
        return {}


def normalized_subject(owner_name):
    value = re.sub(
        r'\b(?:ESTATE\s+OF|HEIRS?\s+OF|DECEASED|PR\s+OF\s+THE\s+ESTATE|'
        r'PERSONAL\s+REPRESENTATIVE|EXECUTOR|L(?:IFE|F)\s+ESTATE)\b',
        ' ',
        str(owner_name or ''),
        flags=re.I,
    )
    value = re.sub(r'\s+', ' ', value).strip(' ,-&')
    primary = re.split(r'\s+(?:&|AND)\s+', value, maxsplit=1, flags=re.I)[0]
    return primary.strip(' ,-') or str(owner_name or '').strip()


def build_research_plan(lead):
    source = _source_row(lead)
    owner_name = str(lead.get('owner_name') or '')
    subject = normalized_subject(owner_name)
    signals = []
    score = 0
    if lead.get('deceased_flag'):
        signals.append('County owner text contains an estate or deceased-owner signal')
        score += 60
    mailing_signal = str(lead.get('mailing_signal') or '')
    if mailing_signal:
        signals.append(f'{mailing_signal} mailing-address signal')
        score += 15 if mailing_signal == 'Strong' else 7
    total_due = float(lead.get('total_due') or 0)
    if total_due >= 10000:
        signals.append('High delinquent-tax balance')
        score += 15
    elif total_due >= 5000:
        signals.append('Elevated delinquent-tax balance')
        score += 8
    assessor_owner = str(source.get('Current Assessor Owner') or '')
    source_owner = str(source.get('Owner Name') or '')
    verification = str(source.get('Current Owner Verification') or '')
    if verification == 'Review' and assessor_owner and source_owner:
        signals.append('Current Assessor owner differs or requires review')
        score += 25

    if score >= 60:
        priority = 'Immediate'
    elif score >= 25:
        priority = 'High'
    else:
        priority = 'Standard'

    return {
        'subject': subject,
        'priority': priority,
        'score': min(score, 100),
        'status': 'Unconfirmed — research required',
        'signals': signals or ['No direct death signal; research is exploratory'],
        'identity_rule': (
            'Do not confirm death unless the evidence subject matches this owner '
            'and at least one additional identity detail, such as address, relative, '
            'case party, or property interest.'
        ),
        'sources': [dict(item) for item in OFFICIAL_RESEARCH_SOURCES],
    }
