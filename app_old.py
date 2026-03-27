from flask import Flask, render_template, request, send_file, jsonify
import pandas as pd
import re
import os
import uuid
from datetime import datetime

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = '/tmp/uploads'
os.makedirs('/tmp/uploads', exist_ok=True)
app.config['OUTPUT_FOLDER'] = '/tmp/outputs'
os.makedirs('/tmp/outputs', exist_ok=True)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

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

def clean_leads(df, tax_year):
    stats = {'original': len(df)}

    tax_col = next((c for c in df.columns if 'TAX' in c.upper() and 'YEAR' in c.upper()), None)

    if tax_col:
        df[tax_col] = pd.to_numeric(df[tax_col], errors='coerce')
        df = df[df[tax_col] == tax_year].copy()
    stats['after_year_filter'] = len(df)

    df['_is_business'] = df['PROPERTY OWNER NAME'].apply(is_business)
    df = df[~df['_is_business']].copy()
    df = df.drop(columns=['_is_business'])
    stats['after_business_filter'] = len(df)

    df = df.dropna(how='all')
    stats['final'] = len(df)

    if 'Total Due' in df.columns:
        df = df.sort_values('Total Due', ascending=False)

    stats['removed_year'] = stats['original'] - stats['after_year_filter']
    stats['removed_business'] = stats['after_year_filter'] - stats['after_business_filter']
    stats['with_phone'] = df['Phone'].notna().sum() if 'Phone' in df.columns else 0
    stats['without_phone'] = stats['final'] - stats['with_phone']

    stats = {k: int(v) for k, v in stats.items()}

    return df, stats

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

    tax_year = request.form.get('tax_year', '2022')
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
        if ext == '.csv':
            df = pd.read_csv(upload_path)
        else:
            df = pd.read_excel(upload_path, engine='openpyxl')
    except Exception as e:
        return jsonify({'error': f'Could not read file: {str(e)}'}), 400

    try:
        cleaned_df, stats = clean_leads(df, tax_year)
    except Exception as e:
        return jsonify({'error': f'Error during cleaning: {str(e)}'}), 500

    date_str = datetime.now().strftime('%Y%m%d')
    output_filename = f'Clean_Leads_{tax_year}_{date_str}_{uid}.xlsx'
    output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
    cleaned_df.to_excel(output_path, index=False)

    return jsonify({
        'success': True,
        'stats': stats,
        'download_file': output_filename
    })

@app.route('/download/<filename>')
def download(filename):
    safe_name = os.path.basename(filename)
    filepath = os.path.join(app.config['OUTPUT_FOLDER'], safe_name)
    if not os.path.exists(filepath):
        return 'File not found', 404
    return send_file(filepath, as_attachment=True, download_name=safe_name)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
