from flask import Flask, request, jsonify
import json
import os
import threading
import requests
from datetime import datetime

app = Flask(__name__)

API_SECRET = 'JINX-SECRET-2026'
DB_FILE = 'bins_db.json'
PORT = 5000
DEVELOPER = '@jinx_sj'

db_lock = threading.Lock()

def _load_db():
    if not os.path.exists(DB_FILE):
        return {}
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def _save_db(data):
    with open(DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def _get_bin_info_external(bin_num):
    try:
        r = requests.get(f'https://bins.antipublic.cc/bins/{bin_num}', timeout=8)
        if r.status_code == 200:
            data = r.json()
            return {
                'brand': data.get('brand', 'UNKNOWN'),
                'type': data.get('type', 'UNKNOWN'),
                'level': data.get('level', 'UNKNOWN'),
                'bank': data.get('bank', 'UNKNOWN'),
                'country': data.get('country_name', 'UNKNOWN'),
                'flag': data.get('country_flag', '')
            }
    except Exception:
        pass
    return {
        'brand': 'UNKNOWN',
        'type': 'UNKNOWN',
        'level': 'UNKNOWN',
        'bank': 'UNKNOWN',
        'country': 'UNKNOWN',
        'flag': ''
    }

def _format_vbv(vbv_str):
    s = str(vbv_str).strip().lower()
    if 'non' in s:
        return '✅ Non-VBV'
    if 'vbv' in s:
        return '❌ VBV'
    return '❓ UNKNOWN'

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        'status': 'online',
        'service': 'Jinx BIN API',
        'version': '1.0',
        'developer': DEVELOPER,
        'endpoints': {
            'vbv': 'GET /vbv?bin=XXXXXX'
        }
    })

@app.route('/vbv', methods=['GET'])
def vbv_lookup():
    try:
        bin_num = request.args.get('bin', '').strip()
        if not bin_num or len(bin_num) < 6:
            return jsonify({'success': False, 'error': 'Invalid BIN'}), 400
        bin_key = bin_num[:6]
        with db_lock:
            db = _load_db()
        raw_vbv = db.get(bin_key, {}).get('vbv', 'UNKNOWN')
        vbv_status = _format_vbv(raw_vbv)
        external = _get_bin_info_external(bin_key)
        return jsonify({
            'success': True,
            'developer': DEVELOPER,
            'bin': bin_key,
            'vbv': vbv_status,
            'brand': external['brand'],
            'type': external['type'],
            'level': external['level'],
            'bank': external['bank'],
            'country': external['country'],
            'flag': external['flag']
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/mbins', methods=['POST'])
def mbins_lookup():
    try:
        data = request.get_json(silent=True) or {}
        bins_list = data.get('bins', [])
        if not isinstance(bins_list, list) or not bins_list:
            return jsonify({'success': False, 'error': 'No bins provided'}), 400
        with db_lock:
            db = _load_db()
        results = []
        for bin_num in bins_list[:100]:
            bin_str = str(bin_num).strip()
            if not bin_str or len(bin_str) < 6:
                continue
            bin_key = bin_str[:6]
            raw_vbv = db.get(bin_key, {}).get('vbv', 'UNKNOWN')
            vbv_status = _format_vbv(raw_vbv)
            external = _get_bin_info_external(bin_key)
            results.append({
                'bin': bin_key,
                'vbv': vbv_status,
                'brand': external['brand'],
                'type': external['type'],
                'level': external['level'],
                'bank': external['bank'],
                'country': external['country'],
                'flag': external['flag']
            })
        return jsonify({
            'success': True,
            'developer': DEVELOPER,
            'total': len(results),
            'results': results
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/addbin', methods=['POST'])
def addbin():
    try:
        data = request.get_json(silent=True) or {}
        secret = data.get('secret', '')
        if secret != API_SECRET:
            return jsonify({'success': False, 'error': 'Invalid secret'}), 401
        bins_list = data.get('bins', [])
        if not isinstance(bins_list, list):
            if data.get('bin'):
                bins_list = [{'bin': data.get('bin'), 'vbv': data.get('vbv', 'UNKNOWN')}]
            else:
                return jsonify({'success': False, 'error': 'No bins provided'}), 400
        if not bins_list:
            return jsonify({'success': False, 'error': 'Empty bins list'}), 400
        added = 0
        updated = 0
        skipped = 0
        with db_lock:
            db = _load_db()
            now = int(datetime.now().timestamp())
            for item in bins_list:
                bin_num = str(item.get('bin', '')).strip()
                vbv = str(item.get('vbv', 'UNKNOWN')).strip()
                if not bin_num or len(bin_num) < 6:
                    skipped += 1
                    continue
                bin_key = bin_num[:6]
                if bin_key in db:
                    db[bin_key]['vbv'] = vbv
                    db[bin_key]['updated_at'] = now
                    updated += 1
                else:
                    db[bin_key] = {
                        'vbv': vbv,
                        'added_at': now,
                        'updated_at': now
                    }
                    added += 1
            _save_db(db)
        return jsonify({
            'success': True,
            'developer': DEVELOPER,
            'added': added,
            'updated': updated,
            'skipped': skipped,
            'total': len(db)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/delbin', methods=['POST'])
def delbin():
    try:
        data = request.get_json(silent=True) or {}
        secret = data.get('secret', '')
        if secret != API_SECRET:
            return jsonify({'success': False, 'error': 'Invalid secret'}), 401
        bin_num = str(data.get('bin', '')).strip()
        if not bin_num or len(bin_num) < 6:
            return jsonify({'success': False, 'error': 'Invalid BIN'}), 400
        bin_key = bin_num[:6]
        with db_lock:
            db = _load_db()
            if bin_key not in db:
                return jsonify({'success': False, 'error': 'BIN not found'}), 404
            del db[bin_key]
            _save_db(db)
        return jsonify({
            'success': True,
            'developer': DEVELOPER,
            'deleted': bin_key
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/binstats', methods=['GET'])
def binstats():
    try:
        secret = request.args.get('secret', '')
        if secret != API_SECRET:
            return jsonify({'success': False, 'error': 'Invalid secret'}), 401
        with db_lock:
            db = _load_db()
        vbv_count = 0
        non_vbv_count = 0
        unknown_count = 0
        for bin_key, entry in db.items():
            vbv_status = str(entry.get('vbv', '')).lower()
            if 'non' in vbv_status:
                non_vbv_count += 1
            elif 'vbv' in vbv_status:
                vbv_count += 1
            else:
                unknown_count += 1
        return jsonify({
            'success': True,
            'developer': DEVELOPER,
            'total': len(db),
            'vbv': vbv_count,
            'non_vbv': non_vbv_count,
            'unknown': unknown_count
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    print(f'Jinx BIN API starting on port {PORT}...')
    print(f'DB file: {DB_FILE}')
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)