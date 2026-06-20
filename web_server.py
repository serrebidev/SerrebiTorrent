import os
import threading
import sys
import hmac
import time
import tempfile
from flask import Flask, request, jsonify, send_from_directory, session, redirect
from werkzeug.utils import secure_filename

def get_bundle_dir():
    return getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))

static_dir = os.path.join(get_bundle_dir(), 'web_static')
app = Flask(__name__, static_folder=static_dir)


def _load_or_create_secret_key():
    """Persist the Flask secret key so sessions survive restarts.

    Regenerating os.urandom() every launch silently invalidates all sessions on
    restart. Store the key under the app data dir (best-effort)."""
    try:
        from app_paths import get_data_dir
        key_path = os.path.join(get_data_dir(), 'web_secret.key')
        if os.path.exists(key_path):
            with open(key_path, 'rb') as f:
                data = f.read()
            if len(data) >= 16:
                return data
        key = os.urandom(32)
        try:
            with open(key_path, 'wb') as f:
                f.write(key)
        except OSError:
            pass
        return key
    except Exception:
        return os.urandom(32)


app.secret_key = _load_or_create_secret_key()
# Harden the session cookie and cap request bodies.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',  # blocks cross-site POST -> mitigates CSRF
    PERMANENT_SESSION_LIFETIME=43200,  # 12h idle session lifetime
    MAX_CONTENT_LENGTH=64 * 1024 * 1024,  # 64 MB cap on request bodies
)

# --- Login brute-force throttling (per client IP) ---
_AUTH_FAIL_LIMIT = 8
_AUTH_LOCK_SECONDS = 300
_auth_lock = threading.Lock()
_auth_failures = {}  # ip -> (fail_count, window_start_ts)


def _client_ip():
    return request.remote_addr or 'unknown'


def _is_locked_out(ip):
    with _auth_lock:
        rec = _auth_failures.get(ip)
        if not rec:
            return False
        count, first = rec
        if count < _AUTH_FAIL_LIMIT:
            return False
        if time.time() - first < _AUTH_LOCK_SECONDS:
            return True
        _auth_failures.pop(ip, None)  # lock window expired
        return False


def _record_auth_failure(ip):
    with _auth_lock:
        count, first = _auth_failures.get(ip, (0, time.time()))
        if time.time() - first >= _AUTH_LOCK_SECONDS:
            count, first = 0, time.time()
        _auth_failures[ip] = (count + 1, first)


def _clear_auth_failures(ip):
    with _auth_lock:
        _auth_failures.pop(ip, None)


def _weak_web_credentials():
    """True when the Web UI password is still the default/empty (unsafe to expose)."""
    pw = WEB_CONFIG.get('password') or ''
    return pw == '' or pw == 'password'


def _allowed_add_url(u):
    """Allow only network/magnet torrent sources; block file://, UNC, SSRF schemes."""
    return u.lower().startswith(('http://', 'https://', 'magnet:'))


def _csrf_token():
    token = session.get('csrf_token')
    if not token:
        token = os.urandom(16).hex()
        session['csrf_token'] = token
    return token


@app.before_request
def protect_mutating_requests():
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return None
    if not request.path.startswith('/api/'):
        return None
    if request.endpoint == 'api_login':
        return None
    if not session.get('logged_in'):
        return None
    expected = session.get('csrf_token')
    supplied = request.headers.get('X-CSRF-Token') or request.form.get('_csrf')
    if not expected or not supplied or not hmac.compare_digest(str(supplied), str(expected)):
        return "CSRF token missing or invalid.", 403
    return None

# Global context to hold reference to the active torrent client and credentials
# These are updated by the MainFrame when the Web UI is enabled or settings change.
WEB_CONFIG = {
    'app': None, # Reference to MainFrame
    'client': None,
    'username': 'admin',
    'password': 'password',
    'host': '127.0.0.1',
    'port': 8080,
    'enabled': False
}

def login_required(f):
    def wrapper(*args, **kwargs):
        if not session.get('logged_in'):
            if request.path.startswith('/api/'):
                return "Unauthorized", 403
            return redirect('/login.html')
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

@app.route('/')
@login_required
def index():
    return send_from_directory(static_dir, 'index.html')

@app.route('/login.html')
def login_page():
    return send_from_directory(static_dir, 'login.html')

@app.route('/<path:filename>')
def serve_static(filename):
    # login.html is the only public page; everything else (app.js, index.html,
    # style.css) is part of the authenticated app shell.
    if filename != 'login.html' and not session.get('logged_in'):
        return redirect('/login.html')
    return send_from_directory(static_dir, filename)

@app.route('/api/v2/auth/login', methods=['POST'])
def api_login():
    ip = _client_ip()
    if _is_locked_out(ip):
        return "Too many failed attempts. Try again later.", 429
    user = (request.form.get('username') or '').encode('utf-8')
    pw = (request.form.get('password') or '').encode('utf-8')
    exp_user = (WEB_CONFIG.get('username') or '').encode('utf-8')
    exp_pw = (WEB_CONFIG.get('password') or '').encode('utf-8')
    # Constant-time comparison avoids a timing side-channel on the password.
    if hmac.compare_digest(user, exp_user) and hmac.compare_digest(pw, exp_pw):
        session['logged_in'] = True
        session['csrf_token'] = os.urandom(16).hex()
        session.permanent = True
        _clear_auth_failures(ip)
        return "Ok."
    _record_auth_failure(ip)
    return "Fails.", 403

@app.route('/api/v2/auth/csrf')
@login_required
def api_csrf():
    return jsonify({'csrf_token': _csrf_token()})

@app.route('/api/v2/auth/logout', methods=['POST'])
def api_logout():
    session.pop('logged_in', None)
    session.pop('csrf_token', None)
    return "Ok."

@app.route('/api/v2/profiles')
@login_required
def get_profiles():
    app_ref = WEB_CONFIG['app']
    if not app_ref:
        return jsonify({'profiles': {}, 'current_id': None})
    profiles = app_ref.config_manager.get_profiles()
    current_id = app_ref.current_profile_id
    return jsonify({
        'profiles': profiles,
        'current_id': current_id
    })

@app.route('/api/v2/profiles/switch', methods=['POST'])
@login_required
def switch_profile():
    pid = request.form.get('id')
    app_ref = WEB_CONFIG['app']
    if app_ref and pid:
        import wx
        wx.CallAfter(app_ref.connect_profile, pid)
        return "Ok."
    return "Failed.", 400

@app.route('/api/v2/profiles/add', methods=['POST'])
@login_required
def add_profile():
    app_ref = WEB_CONFIG['app']
    if not app_ref:
        return "Error", 500
    
    name = request.form.get('name')
    type = request.form.get('type')
    url = request.form.get('url')
    user = request.form.get('user', '')
    pw = request.form.get('password', '')
    
    if name and type and url:
        import wx
        wx.CallAfter(app_ref.config_manager.add_profile, name, type, url, user, pw)
        return "Ok."
    return "Missing data", 400

@app.route('/api/v2/torrents/info')
@login_required
def torrents_info():
    app_ref = WEB_CONFIG['app']
    if not app_ref:
        return jsonify({'torrents': [], 'stats': {}, 'trackers': {}})
    
    # Use all_torrents for stats but allow the info call to return what's actually there
    # Use thread-safe copy if available
    if hasattr(app_ref, 'get_all_torrents_safe'):
        torrents = app_ref.get_all_torrents_safe()
    else:
        torrents = list(app_ref.all_torrents)

    stats = {"All": 0, "Downloading": 0, "Finished": 0, "Seeding": 0, "Stopped": 0, "Failed": 0}
    tracker_counts = {}
    
    for t in torrents:
        size = t.get('size', 0)
        done = t.get('done', 0)
        pct = (done / size * 100) if size > 0 else 0
        state = t.get('state', 0)
        msg = t.get('message', '')
        tracker_domain = t.get('tracker_domain', 'Unknown') or 'Unknown'
        
        is_seeding = (state == 1 and pct >= 100)
        is_stopped = (state == 0)
        is_error = bool(msg and "success" not in msg.lower() and "ok" not in msg.lower())
        
        stats["All"] += 1
        if state == 1 and pct < 100:
            stats["Downloading"] += 1
        if pct >= 100:
            stats["Finished"] += 1
        if is_seeding:
            stats["Seeding"] += 1
        if is_stopped:
            stats["Stopped"] += 1
        if is_error:
            stats["Failed"] += 1
        
        tracker_counts[tracker_domain] = tracker_counts.get(tracker_domain, 0) + 1

    return jsonify({
        'torrents': torrents,
        'stats': stats,
        'trackers': tracker_counts
    })

@app.route('/api/v2/torrents/all')
@login_required
def torrents_all():
    client = WEB_CONFIG['client']
    if client:
        try:
            return jsonify(client.get_torrents_full())
        except Exception as e:
            print(f"torrents/all error: {e}")
            return "Failed to fetch torrents.", 500
    return jsonify([])

@app.route('/api/v2/torrents/files')
@login_required
def torrents_files():
    hash = request.args.get('hash')
    client = WEB_CONFIG['client']
    if client and hash:
        return jsonify(client.get_files(hash))
    return jsonify([])

@app.route('/api/v2/torrents/resume', methods=['POST'])
@login_required
def torrents_resume():
    hashes = request.form.get('hashes')
    client = WEB_CONFIG['client']
    if client and hashes:
        for h in hashes.split('|'):
            client.start_torrent(h)
    return "Ok."

@app.route('/api/v2/torrents/pause', methods=['POST'])
@login_required
def torrents_pause():
    hashes = request.form.get('hashes')
    client = WEB_CONFIG['client']
    if client and hashes:
        for h in hashes.split('|'):
            client.stop_torrent(h)
    return "Ok."

@app.route('/api/v2/torrents/recheck', methods=['POST'])
@login_required
def torrents_recheck():
    hashes = request.form.get('hashes')
    client = WEB_CONFIG['client']
    if client and hashes:
        for h in hashes.split('|'):
            try:
                client.recheck_torrent(h)
            except Exception:
                continue
    return "Ok."

@app.route('/api/v2/torrents/reannounce', methods=['POST'])
@login_required
def torrents_reannounce():
    hashes = request.form.get('hashes')
    client = WEB_CONFIG['client']
    if client and hashes:
        for h in hashes.split('|'):
            try:
                client.reannounce_torrent(h)
            except Exception:
                continue
    return "Ok."

@app.route('/api/v2/torrents/openfolder', methods=['POST'])
@login_required
def torrents_openfolder():
    hashes = request.form.get('hashes')
    client = WEB_CONFIG['client']
    app_ref = WEB_CONFIG['app']
    if client and hashes:
        h = hashes.split('|')[0]
        try:
            path = client.get_torrent_save_path(h)
            if path and app_ref:
                import wx
                wx.CallAfter(app_ref._open_path, path)
        except Exception:
            pass
    return "Ok."

@app.route('/api/v2/torrents/delete', methods=['POST'])
@login_required
def torrents_delete():
    hashes = request.form.get('hashes')
    delete_files = request.form.get('deleteFiles') == 'true'
    client = WEB_CONFIG['client']
    if client and hashes:
        for h in hashes.split('|'):
            if delete_files:
                client.remove_torrent_with_data(h)
            else:
                client.remove_torrent(h)
    return "Ok."

@app.route('/api/v2/torrents/add', methods=['POST'])
@login_required
def torrents_add():
    client = WEB_CONFIG['client']
    if not client:
        return "No client", 500
    
    urls = request.form.get('urls')
    save_path = request.form.get('savepath')
    errors = []
    attempted = 0
    
    if urls:
        for url in urls.split('\n'):
            u = url.strip()
            if u:
                if not _allowed_add_url(u):
                    errors.append("rejected-scheme")
                    print(f"Web add: rejected non-http/magnet URL: {u[:80]!r}")
                    continue
                try:
                    attempted += 1
                    client.add_torrent_url(u, sp=save_path)
                except Exception as e:
                    errors.append("url-failed")
                    print(f"Web add URL error for {u[:80]!r}: {e}")

    if 'torrents' in request.files:
        files = request.files.getlist('torrents')
        for f in files:
            content = f.read()
            if content:
                try:
                    attempted += 1
                    client.add_torrent_file(content, sp=save_path)
                except Exception as e:
                    errors.append("file-failed")
                    print(f"Web add file error for {f.filename!r}: {e}")

    if attempted == 0 and not errors:
        return "No torrents provided", 400
    if errors:
        # Detail is logged server-side; don't leak exception text to clients.
        return "Failed to add torrents.", 500
    return "Ok."

@app.route('/api/v2/rss/feeds')
@login_required
def rss_feeds():
    app_ref = WEB_CONFIG['app']
    if not app_ref or not hasattr(app_ref, 'rss_panel'):
        return jsonify({})
    return jsonify(app_ref.rss_panel.manager.feeds)

@app.route('/api/v2/rss/add_feed', methods=['POST'])
@login_required
def rss_add_feed():
    app_ref = WEB_CONFIG['app']
    url = request.form.get('url')
    alias = request.form.get('alias', '')
    if app_ref and url:
        import wx
        wx.CallAfter(app_ref.rss_panel.manager.add_feed, url, alias)
        return "Ok."
    return "Failed", 400

@app.route('/api/v2/rss/remove_feed', methods=['POST'])
@login_required
def rss_remove_feed():
    app_ref = WEB_CONFIG['app']
    url = request.form.get('url')
    if app_ref and url:
        import wx
        wx.CallAfter(app_ref.rss_panel.manager.remove_feed, url)
        return "Ok."
    return "Failed", 400

@app.route('/api/v2/rss/rules')
@login_required
def rss_rules():
    app_ref = WEB_CONFIG['app']
    if not app_ref or not hasattr(app_ref, 'rss_panel'):
        return jsonify([])
    return jsonify(app_ref.rss_panel.manager.rules)

@app.route('/api/v2/rss/set_rule', methods=['POST'])
@login_required
def rss_set_rule():
    app_ref = WEB_CONFIG['app']
    index = request.form.get('index', type=int)
    pattern = request.form.get('pattern')
    rule_type = request.form.get('type', 'accept')
    enabled = request.form.get('enabled') == 'true'
    
    if app_ref and pattern:
        data = {'pattern': pattern, 'type': rule_type, 'enabled': enabled}
        import wx
        def do_update():
            if index is not None and index >= 0:
                app_ref.rss_panel.manager.update_rule(index, data)
            else:
                app_ref.rss_panel.manager.add_rule(pattern, rule_type)
        wx.CallAfter(do_update)
        return "Ok."
    return "Failed", 400

@app.route('/api/v2/rss/remove_rule', methods=['POST'])
@login_required
def rss_remove_rule():
    app_ref = WEB_CONFIG['app']
    index = request.form.get('index', type=int)
    if app_ref and index is not None:
        import wx
        wx.CallAfter(app_ref.rss_panel.manager.remove_rule, index)
        return "Ok."
    return "Failed", 400

@app.route('/api/v2/rss/import_flexget', methods=['POST'])
@login_required
def rss_import_flexget():
    app_ref = WEB_CONFIG['app']
    if not app_ref:
        return "Error", 500
    if 'config' not in request.files:
        return "No file", 400
    
    f = request.files['config']
    # Save to temp and import
    filename = secure_filename(f.filename or '') or 'flexget.yml'
    temp_path = os.path.join(tempfile.gettempdir(), f"serrebitorrent_{os.getpid()}_{filename}")
    f.save(temp_path)
    
    import wx
    def do_import():
        try:
            app_ref.rss_panel.manager.import_flexget_config(temp_path)
        except Exception as e:
            print(f"Import error: {e}")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    wx.CallAfter(do_import)
    return jsonify({'status': 'Import started in background'})

@app.route('/api/v2/app/prefs')
@login_required
def get_app_prefs():
    app_ref = WEB_CONFIG['app']
    if not app_ref:
        return jsonify({})
    return jsonify(app_ref.config_manager.get_preferences())

@app.route('/api/v2/app/prefs', methods=['POST'])
@login_required
def set_app_prefs():
    app_ref = WEB_CONFIG['app']
    if not app_ref:
        return "Error", 500
    new_prefs = request.json
    if new_prefs:
        import wx
        def apply():
            app_ref.config_manager.set_preferences(new_prefs)
            app_ref._update_client_default_save_path()
            app_ref._update_web_ui()
        wx.CallAfter(apply)
        return "Ok."
    return "No data", 400

@app.route('/api/v2/app/remote_prefs')
@login_required
def get_remote_prefs():
    client = WEB_CONFIG['client']
    if not client:
        return jsonify({})
    # We also return the client name to determine schema on frontend
    name = "Other"
    from clients import QBittorrentClient, RTorrentClient, TransmissionClient
    if isinstance(client, QBittorrentClient):
        name = "qbittorrent"
    elif isinstance(client, RTorrentClient):
        name = "rtorrent"
    elif isinstance(client, TransmissionClient):
        name = "transmission"
    
    return jsonify({
        'name': name,
        'prefs': client.get_app_preferences()
    })

@app.route('/api/v2/app/remote_prefs', methods=['POST'])
@login_required
def set_remote_prefs():
    client = WEB_CONFIG['client']
    if not client:
        return "No client", 500
    new_prefs = request.json
    if new_prefs:
        try:
            client.set_app_preferences(new_prefs)
            return "Ok."
        except Exception as e:
            print(f"remote_prefs error: {e}")
            return "Failed to update remote preferences.", 500
    return "No data", 400

@app.route('/api/v2/sync/maindata')
@login_required
def sync_maindata():
    client = WEB_CONFIG['client']
    if not client:
        return jsonify({'torrents': {}})
    
    torrents = client.get_torrents_full()
    # qBit sync format is a dict indexed by hash
    t_dict = {t['hash']: t for t in torrents}
    return jsonify({
        'torrents': t_dict,
        'full_update': True
    })

# Server Threading
server_thread = None

def run_server():
    host = WEB_CONFIG.get('host') or '127.0.0.1'
    app.run(host=host, port=WEB_CONFIG['port'], threaded=True)

def start_web_ui():
    global server_thread
    if server_thread and server_thread.is_alive():
        return
    if _weak_web_credentials():
        print("Web UI not started: change the default Web UI password first.")
        return
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    print(f"Web UI started on port {WEB_CONFIG['port']}")
