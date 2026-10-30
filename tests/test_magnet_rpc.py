"""Exercise real transmission-rpc serialization against a local HTTP fixture."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from clients import TransmissionClient


def test_magnet_add_and_tracker_merge_rpc():
    calls = []
    info_hash = 'a' * 40
    torrent = {'id': 1, 'hashString': info_hash, 'name': 'Test', 'trackers': []}
    present = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if self.headers.get('X-Transmission-Session-Id') != 'test-session':
                self.send_response(409)
                self.send_header('X-Transmission-Session-Id', 'test-session')
                self.end_headers()
                return
            calls.append(request)
            method = request['method']
            if method == 'session-get':
                arguments = {'version': '4.1.3 (838877323f)', 'rpc-version': 17, 'rpc-version-minimum': 14, 'download-dir': '/remote/downloads'}
            elif method == 'torrent-get':
                arguments = {'torrents': present}
            elif method == 'torrent-add':
                present.append(torrent)
                arguments = {'torrent-added': torrent}
            else:
                assert method == 'torrent-set'
                arguments = {}
            data = json.dumps({'result': 'success', 'arguments': arguments, 'tag': request.get('tag')}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = TransmissionClient(f'http://127.0.0.1:{server.server_port}', '', '')
        magnet = f'magnet:?xt=urn:btih:{info_hash}&tr=https%3A%2F%2Ftracker.example%2Fannounce'
        assert client.add_magnet(magnet, '/remote/chosen', False) is None
        assert client.find_magnet_duplicate(magnet)[:2] == (info_hash, 'Test')
        assert client.add_magnet(magnet, '/wrong/path', True)
        client.add_trackers(info_hash, ['https://new.example/announce'])
        adds = [c for c in calls if c['method'] == 'torrent-add']
        assert len(adds) == 1
        assert adds[0]['arguments'] == {'filename': magnet, 'download-dir': '/remote/chosen', 'paused': True}
        changes = [c for c in calls if c['method'] == 'torrent-set']
        assert changes[0]['arguments'] == {'ids': [info_hash], 'trackerAdd': ['https://new.example/announce']}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_connect_with_web_ui_address_uses_rpc_endpoint():
    # Issue #416: connecting with the web UI address a user copies from a
    # browser must reach the RPC endpoint instead of POSTing to the HTML page.
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            length = int(self.headers['Content-Length'])
            self.rfile.read(length)
            if self.path != '/transmission/rpc':
                data = b'<html><title>Transmission Web</title></html>'
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if self.headers.get('X-Transmission-Session-Id') != 'test-session':
                self.send_response(409)
                self.send_header('X-Transmission-Session-Id', 'test-session')
                self.end_headers()
                return
            data = json.dumps({'result': 'success', 'arguments': {
                'version': '4.1.4 (test)', 'rpc-version': 18,
                'rpc-version-minimum': 14, 'download-dir': '/downloads'}}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f'http://127.0.0.1:{server.server_port}'
        for suffix in ('/transmission/web/', '/', '/transmission/rpc/'):
            client = TransmissionClient(base + suffix, '', '')
            assert client.test_connection() == '4.1.4 (test)', suffix
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
