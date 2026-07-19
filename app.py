from flask import Flask, render_template, request, send_file, jsonify
import pandas as pd
import re
import os
import uuid
import json
import requests
import oscn.find as oscn_find
from datetime import datetime

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['OUTPUT_FOLDER'] = 'outputs'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)

# ─── SKIP TRACING CONFIG ──────────────────────────────────────────────────────
SKIP_TRACE_PROVIDER = 'none'
SKIP_TRACE_API_KEY = os.environ.get('SKIP_TRACE_API_KEY', '')

# ─── BUSINESS PATTERNS ───────────────────────────────────────────────────────

BUSINESS_PATTERNS = [
    r'\bLLC\b', r'\bL\.L\.C\.?\b',
    r'\bINC\.?\b', r'\bINCORPORATED\b',
    r'\bCORP\.?\b', r'\bCORPORATION\b',
    r'\bLTD\.?\b', r'\bLIMITED\b',
    r'\bCOMPANY\b', r'\bCO\.\b',
    r'\bGROUP\b', r'\bENTERPRISES?\b',
    r'\bASSOCIATES?\b', r'\bPARTNERS?\b',
    r'\bHOLDINGS?\b', r'\bREALTY\b',
    r'\bREAL ESTATE\b', r'\bPROPERTIES\b',
    r'\bINVESTMENTS?\b', r'\bVENTURES?\b',
    r'\bCHURCH\b', r'\bCHAPEL\b', r'\bMINISTRIES?\b',
    r'\bFOUNDATION\b', r'\bCATTLE\b', r'\bRANCH\b',
    r'\bFARMS?\b', r'\bCULTIVATION\b',
]

CANNABIS_PATTERNS = [
    r'\bCANNABIS\b',
    r'\bDISPENSARY\b',
    r'\bDISPENSARIES\b',
    r'\bMARIJUANA\b',
    r'\bMARIHUANA\b',
    r'\bHEMP\b',
    r'\bCBD\b',
    r'\bTHC\b',
    r'\bMMJ\b',
    r'\bMEDICINAL\b',
    r'\b420\b',
    r'\bGANJA\b',
    r'\bWEED\s+(CO|LLC|INC|CORP|GROUP)\b',
]

DECEASED_PATTERNS = [
    r'\bDECEASED\b',
    r'\bESTATE\s+OF\b',
    r'(?<!REAL\s)\bESTATE\b(?!\s+LLC)(?!\s+TRUST)(?!\s+SERIES)',
    r'\bHEIRS?\s+OF\b',
    r'\bPR\s+OF\s+THE\s+ESTATE\b',
    r'\bPERSONAL\s+REP(RESENTATIVE)?\b',
    r'\bEXECUTOR\b',
    r'\bSURVIVING\s+(SPOUSE|HEIR)\b',
    r'\bIN\s+CARE\s+OF\s+ESTATE\b',
    r'\bC/?O\s+ESTATE\b',
]


def find_column(df, keywords):
    """Find the first column whose name contains ALL given keywords (case-insensitive,
    ignoring spaces). Handles variants like 'Owner Name', 'PROPERTY OWNER NAME',
    'OwnerName', 'TotalDue', 'Total Due', etc."""
    for col in df.columns:
        normalized = re.sub(r'[^A-Z]', '', str(col).upper())
        if all(re.sub(r'[^A-Z]', '', kw.upper()) in normalized for kw in keywords):
            return col
    return None


def is_business(name):
    if pd.isna(name):
        return False
    name_upper = str(name).upper()
    if re.search(r'\bTRUST(EE)?\b', name_upper):
        return False
    for pattern in BUSINESS_PATTERNS:
        if re.search(pattern, name_upper):
            return True
    return False


def is_cannabis(name):
    if pd.isna(name):
        return False
    name_upper = str(name).upper()
    for pattern in CANNABIS_PATTERNS:
        if re.search(pattern, name_upper):
            return True
    return False


def is_likely_deceased(name, comments=None):
    fields_to_check = []
    if not pd.isna(name):
        fields_to_check.append(str(name).upper().strip())
    if comments is not None and not pd.isna(comments):
        fields_to_check.append(str(comments).upper())

    for field in fields_to_check:
        if re.search(r'\bREAL\s+ESTATE\b', field):
            continue
        for pattern in DECEASED_PATTERNS:
            if re.search(pattern, field):
                return True
    return False


def clean_leads(df, tax_year):
    stats = {'original': len(df)}

    # ── Resolve real column names dynamically (fixes 'Owner Name' vs
    #    'PROPERTY OWNER NAME', 'TotalDue' vs 'Total Due', etc.) ──
    owner_col = find_column(df, ['OWNER', 'NAME'])
    if owner_col is None:
        raise ValueError(
            f"Coluna do nome do proprietario nao encontrada. "
            f"Colunas disponiveis: {list(df.columns)}"
        )

    total_due_col = find_column(df, ['TOTAL', 'DUE'])
    comments_col = find_column(df, ['COMMENT'])
    tax_col = find_column(df, ['TAX', 'YEAR'])

    # Detect tax year column (only filters if the column actually exists)
    if tax_col:
        df[tax_col] = pd.to_numeric(df[tax_col], errors='coerce')
        df = df[df[tax_col] == tax_year].copy()
    stats['after_year_filter'] = len(df)

    # Flag deceased BEFORE removing businesses (estate records are valuable leads)
    df['_deceased'] = df.apply(
        lambda row: is_likely_deceased(
            row.get(owner_col, ''),
            row.get(comments_col, None) if comments_col else None
        ),
        axis=1
    )

    # Remove cannabis businesses
    df['_is_cannabis'] = df[owner_col].apply(is_cannabis)
    stats['removed_cannabis'] = int(df['_is_cannabis'].sum())
    df = df[~df['_is_cannabis']].copy()

    # Remove other businesses (keep trusts)
    df['_is_business'] = df[owner_col].apply(is_business)
    df = df[~df['_is_business']].copy()
    df = df.drop(columns=['_is_cannabis', '_is_business'])

    stats['after_business_filter'] = len(df)

    # Add Deceased Owner column (kept in main sheet too — valuable leads)
    df['Deceased Owner (Flagged)'] = df['_deceased'].map(
        {True: 'YES - Verify', False: ''}
    )
    stats['deceased_flagged'] = int(df['_deceased'].sum())

    # Build the separate "deceased owners" tab Daryl asked for
    deceased_df = df[df['_deceased']].drop(columns=['_deceased']).copy()
    df = df.drop(columns=['_deceased'])

    # Remove completely empty rows
    df = df.dropna(how='all')
    stats['final'] = len(df)

    # Sort by Total Due descending (works regardless of 'Total Due' vs 'TotalDue')
    if total_due_col:
        df = df.sort_values(total_due_col, ascending=False)
        deceased_df = deceased_df.sort_values(total_due_col, ascending=False) if len(deceased_df) else deceased_df

    stats['removed_year']     = stats['original'] - stats['after_year_filter']
    stats['removed_business'] = stats['after_year_filter'] - stats['after_business_filter']
    phone_col = find_column(df, ['PHONE'])
    stats['with_phone']       = int(df[phone_col].notna().sum()) if phone_col else 0
    stats['without_phone']    = stats['final'] - stats['with_phone']

    stats = {k: int(v) for k, v in stats.items()}
    return df, deceased_df, stats


# ─── SKIP TRACING ─────────────────────────────────────────────────────────────

def run_skip_tracing(df):
    if SKIP_TRACE_PROVIDER == 'none' or not SKIP_TRACE_API_KEY:
        return df, {'error': 'No skip tracing provider configured.'}
    elif SKIP_TRACE_PROVIDER == 'batchdata':
        return _skip_trace_batchdata(df)
    elif SKIP_TRACE_PROVIDER == 'tracerfy':
        return _skip_trace_tracerfy(df)
    else:
        return df, {'error': f'Unknown provider: {SKIP_TRACE_PROVIDER}'}


def _skip_trace_batchdata(df):
    try:
        records = []
        for _, row in df.iterrows():
            record = {
                'address':   str(row.get('ST_NO', '')) + ' ' + str(row.get('ST_NAME', '')),
                'city':      str(row.get('OWNR_ADDR 6', '')),
                'state':     str(row.get('OWNR_ADDR ST', '')),
                'zip':       str(row.get('ZIP', '')),
                'firstName': '',
                'lastName':  str(row.get('Owner Name', '')),
            }
            records.append(record)

        response = requests.post(
            'https://api.batchdata.com/api/v1/property/skip-trace',
            headers={
                'Authorization': f'Bearer {SKIP_TRACE_API_KEY}',
                'Content-Type': 'application/json'
            },
            json={'requests': records},
            timeout=120
        )
        response.raise_for_status()
        results = response.json()

        phones = []
        for result in results.get('results', []):
            contacts = result.get('results', {}).get('phoneNumbers', [])
            phone_list = [p.get('number', '') for p in contacts[:8]]
            while len(phone_list) < 8:
                phone_list.append('')
            phones.append(phone_list)

        for i in range(1, 9):
            df[f'Phone {i}'] = [p[i-1] if i-1 < len(p) else '' for p in phones]

        stats = {
            'provider': 'BatchData',
            'records_sent': len(records),
            'records_matched': sum(1 for p in phones if any(p))
        }
        return df, stats

    except Exception as e:
        return df, {'error': str(e)}


def _skip_trace_tracerfy(df):
    try:
        import csv, io, time

        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(['address', 'city', 'state', 'zip', 'first_name', 'last_name'])
        for _, row in df.iterrows():
            address = f"{row.get('ST_NO', '')} {row.get('ST_NAME', '')}".strip()
            writer.writerow([
                address,
                row.get('OWNR_ADDR 6', ''),
                row.get('OWNR_ADDR ST', ''),
                row.get('ZIP', ''),
                '',
                row.get('Owner Name', '')
            ])
        csv_content = csv_buffer.getvalue()

        response = requests.post(
            'https://api.tracerfy.com/trace/',
            headers={'Authorization': f'Bearer {SKIP_TRACE_API_KEY}'},
            files={'file': ('leads.csv', csv_content, 'text/csv')},
            data={'trace_type': 'normal'},
            timeout=60
        )
        response.raise_for_status()
        queue_id = response.json().get('queue_id')

        download_url = None
        for _ in range(30):
            time.sleep(10)
            status_resp = requests.get(
                f'https://api.tracerfy.com/queue/{queue_id}/',
                headers={'Authorization': f'Bearer {SKIP_TRACE_API_KEY}'}
            )
            status_data = status_resp.json()
            if not status_data.get('pending'):
                download_url = status_data.get('download_url')
                break

        result_resp = requests.get(download_url)
        result_df = pd.read_csv(io.StringIO(result_resp.text))

        phone_cols = [c for c in result_df.columns if 'phone' in c.lower()]
        for col in phone_cols[:8]:
            df[col] = result_df[col].values if len(result_df) == len(df) else ''

        stats = {
            'provider': 'Tracerfy',
            'records_sent': len(df),
            'records_matched': result_df[phone_cols[0]].notna().sum() if phone_cols else 0
        }
        return df, stats

    except Exception as e:
        return df, {'error': str(e)}


# ─── ROUTES ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/process', methods=['POST'])
def process():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    tax_year = request.form.get('tax_year', '2023')
    try:
        tax_year = int(tax_year)
    except ValueError:
        return jsonify({'error': 'Invalid tax year'}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ['.xlsx', '.xls', '.csv']:
        return jsonify({'error': 'File must be .xlsx, .xls or .csv'}), 400

    uid = str(uuid.uuid4())[:8]
    upload_path = os.path.join(app.config['UPLOAD_FOLDER'], f'{uid}_input{ext}')
    file.save(upload_path)

    try:
        df = pd.read_csv(upload_path) if ext == '.csv' else pd.read_excel(upload_path, engine='openpyxl')
    except Exception as e:
        return jsonify({'error': f'Could not read file: {str(e)}'}), 400

    try:
        cleaned_df, deceased_df, stats = clean_leads(df, tax_year)
    except Exception as e:
        return jsonify({'error': f'Error during cleaning: {str(e)}', 'columns_found': list(df.columns)}), 500

    date_str = datetime.now().strftime('%Y%m%d')
    output_filename = f'Clean_Leads_{tax_year}_{date_str}_{uid}.xlsx'
    output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)

    # Write two tabs: "All Leads" and "Deceased Owners" (as Daryl requested)
    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        cleaned_df.to_excel(writer, sheet_name='All Leads', index=False)
        deceased_df.to_excel(writer, sheet_name='Deceased Owners', index=False)

    job_meta = {
        'uid': uid,
        'output_filename': output_filename,
        'tax_year': tax_year,
        'stats': stats
    }
    meta_path = os.path.join(app.config['OUTPUT_FOLDER'], f'{uid}_meta.json')
    with open(meta_path, 'w') as f:
        json.dump(job_meta, f)

    return jsonify({
        'success': True,
        'stats': stats,
        'download_file': output_filename,
        'job_id': uid,
        'skip_trace_available': SKIP_TRACE_PROVIDER != 'none'
    })


@app.route('/skiptrace/<job_id>', methods=['POST'])
def skiptrace(job_id):
    meta_path = os.path.join(app.config['OUTPUT_FOLDER'], f'{job_id}_meta.json')
    if not os.path.exists(meta_path):
        return jsonify({'error': 'Job not found. Please process a list first.'}), 404

    with open(meta_path) as f:
        meta = json.load(f)

    clean_path = os.path.join(app.config['OUTPUT_FOLDER'], meta['output_filename'])
    if not os.path.exists(clean_path):
        return jsonify({'error': 'Cleaned file not found.'}), 404

    df = pd.read_excel(clean_path, engine='openpyxl', sheet_name='All Leads')

    enriched_df, trace_stats = run_skip_tracing(df)

    if 'error' in trace_stats:
        return jsonify({'error': trace_stats['error']}), 500

    date_str = datetime.now().strftime('%Y%m%d')
    enriched_filename = f'Enriched_Leads_{meta["tax_year"]}_{date_str}_{job_id}.xlsx'
    enriched_path = os.path.join(app.config['OUTPUT_FOLDER'], enriched_filename)
    enriched_df.to_excel(enriched_path, index=False)

    return jsonify({
        'success': True,
        'trace_stats': trace_stats,
        'download_file': enriched_filename
    })


@app.route('/download/<filename>')
def download(filename):
    safe_name = os.path.basename(filename)
    filepath = os.path.join(app.config['OUTPUT_FOLDER'], safe_name)
    if not os.path.exists(filepath):
        return 'File not found', 404
    return send_file(filepath, as_attachment=True, download_name=safe_name)

@app.route('/test-oscn', methods=['GET'])
def test_oscn():
    """
    Rota de diagnóstico: testa se o servidor (Render) consegue mesmo
    ligar-se ao OSCN, sem depender de VPN nem de estar em Portugal.
    Uso: GET /test-oscn?last=SMITH&first=JOHN
    """
    last_name = request.args.get('last', 'SMITH')
    first_name = request.args.get('first', '')

    try:
        results = oscn_find.CaseIndexes(
            county='tulsa',
            last_name=last_name,
            first_name=first_name,
            dcct='PB',
            filed_after='',
        )
        results_list = list(results)

        return jsonify({
            'success': True,
            'searched': {'last_name': last_name, 'first_name': first_name},
            'num_results': len(results_list),
            'results': results_list,
            'warning': (
                'Zero resultados para um apelido comum pode ser bloqueio '
                'silencioso do OSCN, não ausência real de processos.'
                if len(results_list) == 0 else None
            )
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__,
            'searched': {'last_name': last_name, 'first_name': first_name},
        }), 500
 
    
@app.route('/test-network', methods=['GET'])
def test_network():
    """
    Testa a ligação de rede em bruto ao OSCN, sem passar pela lib oscn
    (que engole erros de ligação). Equivalente ao 'curl -v' que fizemos
    localmente, mas correndo a partir do Render.
    """
    try:
        resp = requests.get(
            'https://www.oscn.net/dockets/Search.aspx',
            timeout=15,
            headers={'User-Agent': 'Mozilla/5.0 (LeadCleanerPro diagnostic)'}
        )
        return jsonify({
            'success': True,
            'status_code': resp.status_code,
            'content_length': len(resp.text),
            'content_preview': resp.text[:200],
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__,
        }), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
