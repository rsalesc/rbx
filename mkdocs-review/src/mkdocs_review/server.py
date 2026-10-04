"""Local HTTP server for the review UI and the two annotated sites."""

import http.server
import json
import mimetypes
import pathlib
import threading
import traceback
import urllib.parse
from typing import Optional, Tuple

from mkdocs_review.session import SIDES, NotReady, Session

STATIC = pathlib.Path(__file__).parent / 'static'

MISSING_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="/_mr/inject.css">
<script src="/_mr/inject.js" data-side="{side}" defer></script></head>
<body class="mr-missing-page"><p>{message}</p></body></html>"""


def _inside(root: pathlib.Path, rel: str) -> Optional[pathlib.Path]:
    root = root.resolve()
    path = (root / rel).resolve()
    if path != root and root not in path.parents:
        return None
    return path


def make_handler(session: Session):
    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = 'mkdocs-review'

        def log_message(self, format, *args):  # noqa: A002 - stdlib signature
            pass

        def _send(
            self, status: int, body: bytes, content_type: str, cache: bool = False
        ):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            if not cache:
                self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)

        def _json(self, data, status: int = 200):
            self._send(status, json.dumps(data).encode(), 'application/json')

        def _html(self, html: str, status: int = 200):
            self._send(status, html.encode(), 'text/html; charset=utf-8')

        def _file(self, path: Optional[pathlib.Path], cache: bool = False):
            if path is None or not path.is_file():
                self._send(404, b'not found', 'text/plain')
                return
            content_type = (
                mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
            )
            self._send(200, path.read_bytes(), content_type, cache=cache)

        def _body(self):
            length = int(self.headers.get('Content-Length') or 0)
            return json.loads(self.rfile.read(length) or b'null')

        def _route(self) -> Tuple[str, str, dict]:
            parts = urllib.parse.urlsplit(self.path)
            query = dict(urllib.parse.parse_qsl(parts.query))
            return self.command, urllib.parse.unquote(parts.path), query

        def _placeholder(self, side: str, message: str, status: int):
            self._html(MISSING_PAGE.format(side=side, message=message), status)

        def _site(self, base: str, side: str, rel: str):
            if rel == '' or rel.endswith('/'):
                rel += 'index.html'
            try:
                comparison = session.comparison(base)
            except KeyError:
                return self._placeholder(side, 'Unknown snapshot.', 404)
            except NotReady:
                return self._placeholder(
                    side, 'This snapshot is still being built.', 503
                )
            page = comparison.page(rel)
            if page is not None:
                html = getattr(comparison.page_diff(rel), f'{side}_html')
                if html is None:
                    return self._placeholder(
                        side,
                        f'This page does not exist on the <b>{side}</b> side.',
                        404,
                    )
                return self._html(html)
            # Built assets never change for a commit; the UI's own files may.
            self._file(_inside(comparison.sites[side].root, rel), cache=True)

        def _dispatch(self):
            method, path, query = self._route()
            if method in ('GET', 'HEAD'):
                if path == '/':
                    return self._file(STATIC / 'index.html')
                if path.startswith('/_mr/'):
                    return self._file(_inside(STATIC, path[len('/_mr/') :]))
                if path.startswith('/r/'):
                    base, _, rest = path[len('/r/') :].partition('/')
                    side, _, rel = rest.partition('/')
                    if side in SIDES:
                        return self._site(base, side, rel)
                if path == '/api/state':
                    try:
                        return self._json(session.state(query.get('base')))
                    except KeyError as exc:
                        return self._json({'error': str(exc)}, 404)
                if path == '/api/snapshots':
                    return self._json(session.snapshot_states())
                if path == '/api/drafts':
                    return self._json(session.drafts.load())
            if method == 'PUT' and path == '/api/drafts':
                session.drafts.save(self._body())
                return self._json({'ok': True})
            if method == 'POST' and path == '/api/build':
                base = session.resolve_base((self._body() or {}).get('base'))
                session.builder.prioritize(base)
                return self._json({'ok': True})
            if method == 'POST' and path == '/api/anchors':
                return self._json(session.anchors(self._body()))
            if method == 'POST' and path == '/api/preview':
                body = self._body() or {}
                return self._json(
                    session.review_payload(
                        body.get('drafts', []), body.get('summary', '')
                    )
                )
            if method == 'POST' and path == '/api/submit':
                body = self._body() or {}
                try:
                    review = session.submit(body.get('summary', ''))
                except (RuntimeError, ValueError) as exc:
                    return self._json({'error': str(exc)}, 400)
                return self._json({'ok': True, 'url': review.get('html_url')})
            if method in ('GET', 'HEAD') and self._from_pane(path):
                return
            self._send(404, b'not found', 'text/plain')

        def _from_pane(self, path: str) -> bool:
            """Serve a root-absolute URL (`/assets/x.js`) requested by a page
            in one of the panes from that pane's site."""
            referer = urllib.parse.urlsplit(self.headers.get('Referer') or '').path
            if not referer.startswith('/r/'):
                return False
            base, _, rest = referer[len('/r/') :].partition('/')
            side = rest.partition('/')[0]
            if side not in SIDES:
                return False
            self._site(base, side, path.lstrip('/'))
            return True

        def _safe_dispatch(self):
            try:
                self._dispatch()
            except Exception as exc:  # noqa: BLE001 - report every failure to the UI
                traceback.print_exc()
                self._json({'error': f'{type(exc).__name__}: {exc}'}, 500)

        do_GET = do_HEAD = do_PUT = do_POST = _safe_dispatch

    return Handler


def serve(session: Session, host: str = '127.0.0.1', port: int = 0):
    """Start serving in a background thread; returns the server."""
    server = http.server.ThreadingHTTPServer((host, port), make_handler(session))
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
