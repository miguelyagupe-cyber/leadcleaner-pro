import re
from dataclasses import dataclass

import pandas as pd


ENTITY_PATTERNS = (
    r'\bLLC\b',
    r'\bL\.?\s*L\.?\s*C\.?\b',
    r'\bINC(?:ORPORATED)?\b',
    r'\bCORP(?:ORATION)?\b',
    r'\bLTD\b',
    r'\bLIMITED\b',
    r'\bLLP\b',
    r'\bLP\b$',
    r'\bCOMPANY\b',
    r'\bCO\.?\s*(?:$|NO\b)',
    r'\bGROUP\b',
    r'\bENTERPRISES?\b',
    r'\bPARTNERSHIP\b',
    r'\bHOLDINGS?\b',
    r'\bREALTY\b',
    r'\bPROPERTIES\b',
    r'\bINVESTMENTS?\b',
    r'\bDEVELOPMENT\b',
    r'\bCONSTRUCTION\b',
    r'\bSERVICES?\b',
    r'\bSOLUTIONS?\b',
    r'\bMANUFACTURING\b',
    r'\bRESTAURANT\b',
    r'\bBAR\s+AND\s+GRILL\b',
    r'\bHOTELS?\b',
    r'\bINN\b',
    r'\bSUITES?\b',
    r'\bCLINIC\b',
    r'\bMEDICAL\b',
    r'\bPHARMACY\b',
    r'\bFITNESS\b',
    r'\bGYM\b',
    r'\bSALON\b',
    r'\bSPA\b',
    r'\bSTUDIO\b',
    r'\bCENTER\b',
    r'\bOPPORTUNITY\s+ZONE\b',
    r'\bLAND\s*&\s*WILDLIFE\b',
    r'\bROOFING\b',
    r'\bPLUMBING\b',
    r'\bAUTOMOTIVE\b',
    r'\bAUTO\s+SALES\b',
)

GOVERNMENT_NONPROFIT_PATTERNS = (
    r'^CITY\s+OF\b',
    r'^COUNTY\s+OF\b',
    r'^STATE\s+OF\b',
    r'\bSCHOOL\s+DISTRICT\b',
    r'\bUNIVERSITY\b',
    r'\bAUTHORITY\b',
    r'\bCHURCH\b',
    r'\bCHAPEL\b',
    r'\bMINISTR(?:Y|IES)\b',
    r'\bFOUNDATION\b',
    r'\bASSOCIATION\b',
    r'\bBISHOP\s+OF\b',
)

CANNABIS_PATTERNS = (
    r'\bCANNABIS\b',
    r'\bDISPENSARY\b',
    r'\bMARI[HJ]UANA\b',
    r'\bHEMP\b',
    r'\bCBD\b',
    r'\bTHC\b',
    r'\bMMJ\b',
    r'\bMMA\b',
    r'\bSKUNK\b',
    r'\bKUSH\b',
    r'\b420\b',
)

DECEASED_PATTERNS = (
    (r'\bPR\s+OF\s+THE\s+ESTATE\b', 'Probate representative named'),
    (r'\bPERSONAL\s+REP(?:RESENTATIVE)?\b', 'Personal representative named'),
    (r'\bESTATE\s+OF\b', 'Estate of owner'),
    (r'\bHEIRS?\s+OF\b', 'Heirs of owner'),
    (r'\bDECEASED\b', 'Owner marked deceased'),
    (r'\bEXECUTOR\b', 'Executor named'),
    (r'\bESTATE\b', 'Estate notation in owner name'),
)


def _text(value):
    return '' if pd.isna(value) else str(value).strip()


def _find_column(dataframe, *tokens):
    normalized_tokens = [re.sub(r'[^A-Z0-9]', '', token.upper()) for token in tokens]
    for column in dataframe.columns:
        normalized = re.sub(r'[^A-Z0-9]', '', str(column).upper())
        if all(token in normalized for token in normalized_tokens):
            return column
    return None


def _matches(value, patterns):
    text = _text(value).upper()
    return any(re.search(pattern, text) for pattern in patterns)


def _deceased_evidence(owner_name):
    text = _text(owner_name).upper()
    if 'REAL ESTATE' in text:
        return '', 'None'
    for pattern, evidence in DECEASED_PATTERNS:
        if re.search(pattern, text):
            return evidence, 'High'
    return '', 'None'


def _mailing_signal(row, columns):
    mailing_address = _text(row.get(columns.mailing_address)).upper()
    mailing_city = _text(row.get(columns.mailing_city)).upper()
    mailing_state = _text(row.get(columns.mailing_state)).upper()
    property_city = _text(row.get(columns.property_city)).upper()
    property_city = re.sub(r'^CITY OF\s+', '', property_city)
    property_city = re.sub(r'\s+COUNTY$', '', property_city)

    signals = []
    if re.search(r'\bP\.?\s*O\.?\s*BOX\b', mailing_address):
        signals.append('PO Box')
    if re.search(r'\bC/?O\b', mailing_address):
        signals.append('Care of')
    if mailing_state and mailing_state != 'OK':
        signals.append('Out of state')
    if mailing_city and property_city and mailing_city != property_city:
        signals.append('Different mailing city')
    return '; '.join(signals)


def _property_address(row, columns):
    return ' '.join(
        part
        for part in (
            _text(row.get(columns.street_number)),
            _text(row.get(columns.street_direction)),
            _text(row.get(columns.street_name)),
            _text(row.get(columns.street_type)),
        )
        if part
    )


@dataclass(frozen=True)
class Columns:
    owner_name: str
    tax_id: str
    total_due: str
    mailing_address: str | None
    mailing_city: str | None
    mailing_state: str | None
    zip_code: str | None
    street_number: str | None
    street_direction: str | None
    street_name: str | None
    street_type: str | None
    property_city: str | None
    subdivision: str | None
    legal_description: str | None
    tax_year: str | None


def resolve_columns(dataframe):
    owner_name = _find_column(dataframe, 'OWNER', 'NAME')
    tax_id = _find_column(dataframe, 'TAX', 'ID')
    total_due = _find_column(dataframe, 'TOTAL', 'DUE')
    missing = [
        label
        for label, value in (
            ('owner name', owner_name),
            ('tax ID', tax_id),
            ('total due', total_due),
        )
        if value is None
    ]
    if missing:
        raise ValueError(f"Required columns not found: {', '.join(missing)}")
    return Columns(
        owner_name=owner_name,
        tax_id=tax_id,
        total_due=total_due,
        mailing_address=_find_column(dataframe, 'ADDRESS'),
        mailing_city=_find_column(dataframe, 'OWNR_ADDR', '6'),
        mailing_state=_find_column(dataframe, 'OWNR_ADDR', 'ST'),
        zip_code=_find_column(dataframe, 'ZIP'),
        street_number=_find_column(dataframe, 'ST_NO'),
        street_direction=_find_column(dataframe, 'ST_DIR'),
        street_name=_find_column(dataframe, 'ST_NAME'),
        street_type=_find_column(dataframe, 'ST_STREET', 'TYPE'),
        property_city=_find_column(dataframe, 'ST_CITY'),
        subdivision=_find_column(dataframe, 'ADDITNAME'),
        legal_description=_find_column(dataframe, 'LEGAL', 'DESCRIPTION'),
        tax_year=_find_column(dataframe, 'TAX', 'YEAR'),
    )


def _score(total_due, deceased_confidence, absentee_signal, owner_type, issues):
    score = 40
    if total_due >= 10000:
        score += 30
    elif total_due >= 5000:
        score += 22
    elif total_due >= 3000:
        score += 14
    elif total_due >= 2000:
        score += 7
    if deceased_confidence == 'High':
        score += 25
    if 'Out of state' in absentee_signal:
        score += 8
    if 'Different mailing city' in absentee_signal:
        score += 4
    if 'PO Box' in absentee_signal:
        score += 2
    if owner_type == 'Trust':
        score += 2
    score -= 8 * len(issues)
    return max(0, min(score, 100))


def qualify_leads(dataframe, selected_tax_year):
    """Classify county rows without presenting weak heuristics as verified facts."""
    columns = resolve_columns(dataframe)
    working = dataframe.copy()
    input_rows = len(working)
    year_validation = 'Selected at import; source has no row-level tax year'
    if columns.tax_year:
        years = pd.to_numeric(working[columns.tax_year], errors='coerce')
        working = working[years == selected_tax_year].copy()
        year_validation = 'Verified from source tax-year column'

    owner_counts = working[columns.owner_name].fillna('').astype(str).value_counts()
    records = []
    for _, row in working.iterrows():
        owner_name = _text(row.get(columns.owner_name))
        owner_upper = owner_name.upper()
        tax_id_text = _text(row.get(columns.tax_id))
        try:
            tax_id_number = int(float(tax_id_text))
        except ValueError:
            tax_id_number = 0
        try:
            total_due = float(row.get(columns.total_due))
        except (TypeError, ValueError):
            total_due = 0

        business_personal_property = 6000000 <= tax_id_number <= 6999999
        cannabis = _matches(owner_upper, CANNABIS_PATTERNS)
        government_nonprofit = _matches(
            owner_upper, GOVERNMENT_NONPROFIT_PATTERNS
        ) and not re.match(r'^CHURCH\s*,', owner_upper)
        trust = bool(re.search(r'\bTRUST(?:EE)?\b', owner_upper))
        entity = _matches(owner_upper, ENTITY_PATTERNS)
        deceased_evidence, deceased_confidence = _deceased_evidence(owner_name)
        absentee_signal = _mailing_signal(row, columns)
        property_address = _property_address(row, columns)

        if cannabis:
            owner_type = 'Cannabis business'
            decision, reason = 'Excluded', 'Cannabis-related business'
        elif business_personal_property:
            owner_type = 'Business personal property'
            decision, reason = 'Excluded', 'Tax ID series 6 identifies business personal property'
        elif government_nonprofit:
            owner_type = 'Government / nonprofit'
            decision, reason = 'Excluded', 'Government or nonprofit owner'
        elif entity and not trust:
            owner_type = 'Business entity'
            decision, reason = 'Excluded', 'Business entity in owner name'
        elif trust:
            owner_type = 'Trust'
            decision, reason = 'Qualified', 'Trust retained under acquisition rules'
        else:
            owner_type = 'Individual / joint owners'
            decision, reason = 'Qualified', 'Individual owner with delinquent balance'

        issues = []
        if not owner_name:
            issues.append('Missing owner name')
        if (
            not property_address
            or not _text(row.get(columns.street_name))
            or not _text(row.get(columns.property_city))
        ):
            issues.append('Incomplete property location')
        if total_due <= 0:
            issues.append('Invalid debt amount')
        if decision == 'Qualified' and issues:
            decision = 'Review'
            reason = '; '.join(issues)

        lead_score = _score(
            total_due,
            deceased_confidence,
            absentee_signal,
            owner_type,
            issues,
        )
        if decision == 'Excluded':
            tier = 'Excluded'
            lead_score = 0
        elif decision == 'Review':
            tier = 'Review'
        elif lead_score >= 75:
            tier = 'A'
        elif lead_score >= 58:
            tier = 'B'
        else:
            tier = 'C'

        enriched = row.to_dict()
        enriched.update(
            {
                'Pipeline Decision': decision,
                'Decision Reason': reason,
                'Owner Type': owner_type,
                'Lead Score': lead_score,
                'Lead Tier': tier,
                'Deceased Confidence': deceased_confidence,
                'Deceased Evidence': deceased_evidence,
                'Absentee Signal': absentee_signal,
                'Data Quality Issues': '; '.join(issues),
                'Property Address (Normalized)': property_address,
                'Owner Portfolio Count': int(owner_counts.get(owner_name, 1)),
                'Tax Year Provenance': year_validation,
            }
        )
        records.append(enriched)

    audit = pd.DataFrame(records)
    qualified = audit[audit['Pipeline Decision'] == 'Qualified'].copy()
    review = audit[audit['Pipeline Decision'] == 'Review'].copy()
    excluded = audit[audit['Pipeline Decision'] == 'Excluded'].copy()
    deceased = audit[audit['Deceased Confidence'] == 'High'].copy()
    absentee = audit[
        (audit['Pipeline Decision'] != 'Excluded') & (audit['Absentee Signal'] != '')
    ].copy()

    order = ['Lead Score', columns.total_due]
    qualified = qualified.sort_values(order, ascending=[False, False])
    review = review.sort_values(order, ascending=[False, False])
    deceased = deceased.sort_values(order, ascending=[False, False])
    absentee = absentee.sort_values(order, ascending=[False, False])

    stats = {
        'original': input_rows,
        'after_year_filter': len(working),
        'qualified': len(qualified),
        'review': len(review),
        'excluded': len(excluded),
        'excluded_business_personal_property': int(
            pd.to_numeric(audit[columns.tax_id], errors='coerce')
            .between(6000000, 6999999)
            .sum()
        ),
        'excluded_cannabis': int((audit['Owner Type'] == 'Cannabis business').sum()),
        'deceased_high_confidence': len(deceased),
        'absentee_opportunities': len(absentee),
        'tier_a': int((qualified['Lead Tier'] == 'A').sum()),
        'tier_b': int((qualified['Lead Tier'] == 'B').sum()),
        'tier_c': int((qualified['Lead Tier'] == 'C').sum()),
        'final': len(qualified),
        'deceased_flagged': len(deceased),
        'with_phone': int(
            qualified[_find_column(qualified, 'PHONE')].notna().sum()
            if _find_column(qualified, 'PHONE')
            else 0
        ),
        'without_phone': 0,
        'tax_year_row_level_verified': bool(columns.tax_year),
    }
    stats['without_phone'] = stats['qualified'] - stats['with_phone']
    return {
        'qualified': qualified,
        'review': review,
        'excluded': excluded,
        'deceased': deceased,
        'absentee': absentee,
        'audit': audit,
        'stats': stats,
    }
