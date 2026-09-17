from flask import Flask, request, jsonify
import json
import os
import threading
import requests
from datetime import datetime

app = Flask(__name__)

API_SECRET = 'JINX-SECRET-2026'
UNKNOWN_SECRET = 'JINX-UNKNOWN-2026'
DB_FILE = 'bins_db.json'
UNKNOWN_FILE = 'bins_unknown.json'
PORT = 5000
DEVELOPER = '@jinx_sj'

MAX_UNKNOWN_SIZE = 10000

db_lock = threading.Lock()
unknown_lock = threading.Lock()

# ==================== DB HELPERS ====================

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

# ==================== UNKNOWN BINS HELPERS ====================

def _load_unknown():
    if not os.path.exists(UNKNOWN_FILE):
        return {}
    try:
        with open(UNKNOWN_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def _save_unknown(data):
    with open(UNKNOWN_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def _record_unknown(bin_key, external_info):
    try:
        with unknown_lock:
            unknown = _load_unknown()
            now = int(datetime.now().timestamp())
            if bin_key in unknown:
                unknown[bin_key]['last_seen'] = now
                unknown[bin_key]['count'] = unknown[bin_key].get('count', 1) + 1
                if unknown[bin_key].get('bank') in (None, 'UNKNOWN', ''):
                    unknown[bin_key]['bank'] = external_info.get('bank', 'UNKNOWN')
                if unknown[bin_key].get('country') in (None, 'UNKNOWN', ''):
                    unknown[bin_key]['country'] = external_info.get('country', 'UNKNOWN')
                if not unknown[bin_key].get('flag'):
                    unknown[bin_key]['flag'] = external_info.get('flag', '')
            else:
                if len(unknown) >= MAX_UNKNOWN_SIZE:
                    try:
                        oldest = min(unknown.items(), key=lambda x: x[1].get('last_seen', 0))
                        del unknown[oldest[0]]
                    except Exception:
                        pass
                unknown[bin_key] = {
                    'first_seen': now,
                    'last_seen': now,
                    'count': 1,
                    'brand': external_info.get('brand', 'UNKNOWN'),
                    'type': external_info.get('type', 'UNKNOWN'),
                    'level': external_info.get('level', 'UNKNOWN'),
                    'bank': external_info.get('bank', 'UNKNOWN'),
                    'country': external_info.get('country', 'UNKNOWN'),
                    'flag': external_info.get('flag', '')
                }
            _save_unknown(unknown)
    except Exception:
        pass

def _remove_from_unknown(bin_keys):
    try:
        with unknown_lock:
            unknown = _load_unknown()
            removed = 0
            for bin_key in bin_keys:
                if bin_key in unknown:
                    del unknown[bin_key]
                    removed += 1
            if removed:
                _save_unknown(unknown)
            return removed
    except Exception:
        return 0

# ==================== EXTERNAL INFO ====================

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

# ==================== PUBLIC ROUTES ====================

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        'status': 'online',
        'service': 'Jinx BIN API',
        'version': '1.1',
        'developer': DEVELOPER,
        'endpoints': {
            'vbv': 'GET /vbv?bin=XXXXXX',
            'mbins': 'POST /mbins'
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

        if bin_key in db:
            raw_vbv = db[bin_key].get('vbv', 'UNKNOWN')
            vbv_status = _format_vbv(raw_vbv)
            entry = db[bin_key]
            bank = entry.get('bank')
            country = entry.get('country')
            flag = entry.get('flag')
            info = entry.get('info')
            if bank and country:
                return jsonify({
                    'success': True,
                    'developer': DEVELOPER,
                    'bin': bin_key,
                    'vbv': vbv_status,
                    'bank': bank,
                    'country': country,
                    'flag': flag or '',
                    'info': info or ''
                })

        external = _get_bin_info_external(bin_key)
        _record_unknown(bin_key, external)

        return jsonify({
            'success': True,
            'developer': DEVELOPER,
            'bin': bin_key,
            'vbv': _format_vbv('UNKNOWN'),
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

            if bin_key in db:
                raw_vbv = db[bin_key].get('vbv', 'UNKNOWN')
                entry = db[bin_key]
                results.append({
                    'bin': bin_key,
                    'vbv': _format_vbv(raw_vbv),
                    'bank': entry.get('bank', 'UNKNOWN'),
                    'country': entry.get('country', 'UNKNOWN'),
                    'flag': entry.get('flag', ''),
                    'info': entry.get('info', 'UNKNOWN')
                })
            else:
                external = _get_bin_info_external(bin_key)
                _record_unknown(bin_key, external)
                results.append({
                    'bin': bin_key,
                    'vbv': _format_vbv('UNKNOWN'),
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

# ==================== SECRET ROUTES (PROTECTED) ====================

def _check_api_auth():
    secret = request.args.get('secret', '') or (
        request.get_json(silent=True) or {}
    ).get('secret', '')
    return secret == API_SECRET

def _check_unknown_auth():
    secret = request.args.get('secret', '') or (
        request.get_json(silent=True) or {}
    ).get('secret', '')
    return secret == UNKNOWN_SECRET

@app.route('/addbin', methods=['POST'])
def addbin():
    try:
        if not _check_api_auth():
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401

        data = request.get_json(silent=True) or {}
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
        added_keys = []

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
                added_keys.append(bin_key)
            _save_db(db)

        removed_from_unknown = _remove_from_unknown(added_keys)

        return jsonify({
            'success': True,
            'developer': DEVELOPER,
            'added': added,
            'updated': updated,
            'skipped': skipped,
            'removed_from_unknown': removed_from_unknown,
            'total': len(db)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/delbin', methods=['POST'])
def delbin():
    try:
        if not _check_api_auth():
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401

        data = request.get_json(silent=True) or {}
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
        if not _check_api_auth():
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401

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

@app.route('/unknown', methods=['GET'])
def unknown_list():
    try:
        if not _check_unknown_auth():
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401

        limit = int(request.args.get('limit', 100))
        sort_by = request.args.get('sort', 'count')

        with unknown_lock:
            unknown = _load_unknown()

        items = []
        for bin_key, data in unknown.items():
            items.append({
                'bin': bin_key,
                'count': data.get('count', 0),
                'first_seen': data.get('first_seen', 0),
                'last_seen': data.get('last_seen', 0),
                'brand': data.get('brand', 'UNKNOWN'),
                'type': data.get('type', 'UNKNOWN'),
                'level': data.get('level', 'UNKNOWN'),
                'bank': data.get('bank', 'UNKNOWN'),
                'country': data.get('country', 'UNKNOWN'),
                'flag': data.get('flag', '')
            })

        if sort_by == 'count':
            items.sort(key=lambda x: x['count'], reverse=True)
        elif sort_by == 'first_seen':
            items.sort(key=lambda x: x['first_seen'], reverse=True)
        elif sort_by == 'last_seen':
            items.sort(key=lambda x: x['last_seen'], reverse=True)

        items = items[:limit]

        return jsonify({
            'success': True,
            'developer': DEVELOPER,
            'total': len(unknown),
            'returned': len(items),
            'sort': sort_by,
            'results': items
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/unknown_stats', methods=['GET'])
def unknown_stats():
    try:
        if not _check_unknown_auth():
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401

        with unknown_lock:
            unknown = _load_unknown()

        total = len(unknown)
        total_lookups = sum(d.get('count', 0) for d in unknown.values())

        now = int(datetime.now().timestamp())
        day_ago = now - 86400
        last_24h = sum(1 for d in unknown.values() if d.get('last_seen', 0) >= day_ago)

        top = sorted(unknown.items(), key=lambda x: x[1].get('count', 0), reverse=True)[:10]
        top_list = [
            {'bin': k, 'count': v.get('count', 0), 'bank': v.get('bank', 'UNKNOWN')}
            for k, v in top
        ]

        return jsonify({
            'success': True,
            'developer': DEVELOPER,
            'total_unknown_bins': total,
            'total_lookups': total_lookups,
            'last_24h': last_24h,
            'top_10': top_list
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/unknown_clear', methods=['POST'])
def unknown_clear():
    try:
        if not _check_unknown_auth():
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401

        with unknown_lock:
            unknown = _load_unknown()
            count = len(unknown)
            _save_unknown({})

        return jsonify({
            'success': True,
            'developer': DEVELOPER,
            'cleared': count
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/unknown_promote', methods=['POST'])
def unknown_promote():
    try:
        if not _check_unknown_auth():
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401

        data = request.get_json(silent=True) or {}
        now = int(datetime.now().timestamp())

        with db_lock:
            db = _load_db()
            added = 0
            updated = 0
            removed_keys = []

            if data.get('promote_all'):
                default_vbv = str(data.get('vbv', 'UNKNOWN'))
                with unknown_lock:
                    unknown = _load_unknown()
                    for bin_key, info in unknown.items():
                        if bin_key in db:
                            db[bin_key]['vbv'] = default_vbv
                            db[bin_key]['updated_at'] = now
                            updated += 1
                        else:
                            db[bin_key] = {
                                'vbv': default_vbv,
                                'bank': info.get('bank', 'UNKNOWN'),
                                'country': info.get('country', 'UNKNOWN'),
                                'flag': info.get('flag', ''),
                                'info': f"{info.get('brand', 'UNKNOWN')} {info.get('type', 'UNKNOWN')} {info.get('level', 'UNKNOWN')}".strip(),
                                'added_at': now,
                                'updated_at': now
                            }
                            added += 1
                        removed_keys.append(bin_key)
                _save_unknown({})
            else:
                bins_list = data.get('bins', [])
                if not isinstance(bins_list, list) or not bins_list:
                    return jsonify({'success': False, 'error': 'No bins provided'}), 400

                with unknown_lock:
                    unknown = _load_unknown()
                    for item in bins_list:
                        bin_num = str(item.get('bin', '')).strip()
                        vbv = str(item.get('vbv', 'UNKNOWN')).strip()
                        if not bin_num or len(bin_num) < 6:
                            continue
                        bin_key = bin_num[:6]
                        if bin_key in db:
                            db[bin_key]['vbv'] = vbv
                            db[bin_key]['updated_at'] = now
                            updated += 1
                        else:
                            info = unknown.get(bin_key, {})
                            db[bin_key] = {
                                'vbv': vbv,
                                'bank': info.get('bank', 'UNKNOWN'),
                                'country': info.get('country', 'UNKNOWN'),
                                'flag': info.get('flag', ''),
                                'info': f"{info.get('brand', 'UNKNOWN')} {info.get('type', 'UNKNOWN')} {info.get('level', 'UNKNOWN')}".strip(),
                                'added_at': now,
                                'updated_at': now
                            }
                            added += 1
                        if bin_key in unknown:
                            del unknown[bin_key]
                            removed_keys.append(bin_key)
                    _save_unknown(unknown)

            _save_db(db)

        return jsonify({
            'success': True,
            'developer': DEVELOPER,
            'added': added,
            'updated': updated,
            'removed_from_unknown': len(removed_keys),
            'total': len(db)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/unknown_cleanup', methods=['POST'])
def unknown_cleanup():
    try:
        if not _check_unknown_auth():
            return jsonify({'success': False, 'error': 'Unauthorized'}), 401

        data = request.get_json(silent=True) or {}
        days = int(data.get('days', 30))
        cutoff = int(datetime.now().timestamp()) - (days * 86400)

        with unknown_lock:
            unknown = _load_unknown()
            to_delete = [k for k, v in unknown.items() if v.get('last_seen', 0) < cutoff]
            for k in to_delete:
                del unknown[k]
            _save_unknown(unknown)

        return jsonify({
            'success': True,
            'developer': DEVELOPER,
            'removed': len(to_delete),
            'days': days,
            'remaining': len(unknown)
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    print(f'Jinx BIN API starting on port {PORT}...')
    print(f'DB file: {DB_FILE}')
    print(f'Unknown file: {UNKNOWN_FILE}')
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)
