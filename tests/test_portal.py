"""One web address for Docautomate and Synchro: the chooser, the remembered choice and the pass-through to Synchro."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

TUNNEL = {"Cf-Connecting-Ip": "203.0.113.7", "Cf-Ray": "abc"}


class FakeSynchro(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, status, body, extra=()):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/api/auth/state"):
            return self._send(200, {"ok": True})
        if self.path.startswith("/api/missing"):
            return self._send(404, {"error": "Няма такъв адрес"})
        if self.path.startswith("/api/cut"):  # promises 100 bytes, sends 2, hangs up
            self.send_response(200)
            self.send_header("Content-Length", "100")
            self.end_headers()
            self.wfile.write(b"{}")
            self.wfile.flush()
            self.connection.shutdown(2)
            return
        if self.path.startswith("/api/hop"):
            return self._send(200, {"x_hop": self.headers.get("X-Hop"), "enc": self.headers.get("Content-Encoding")},
                              [("Connection", "X-Up"), ("X-Up", "1"), ("Content-Encoding", "identity")])
        self._send(200, {"path": self.path, "cookie": self.headers.get("Cookie"), "cf": self.headers.get("Cf-Connecting-Ip")})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        self._send(200, {"got": body}, [("Set-Cookie", "erp_sid=abc; Path=/; HttpOnly"), ("Set-Cookie", "other=1; Path=/")])


@pytest.fixture
def synchro(monkeypatch):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeSynchro)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("SYNCHRO_URL", f"http://127.0.0.1:{srv.server_address[1]}")
    yield srv
    srv.shutdown()


def test_internet_start_page_asks_where_to_go(app, synchro):
    c = app.test_client()
    r = c.get("/", headers=TUNNEL)
    assert r.status_code == 302 and r.headers["Location"].endswith("/portal")
    page = c.get("/portal", headers=TUNNEL).get_data(as_text=True)
    assert "Къде отивате?" in page and "/portal/go/synchro" in page and "/portal/go/docautomate" in page
    assert "не работи" not in page


def test_local_opening_goes_straight_to_docautomate(app, synchro):
    r = app.test_client().get("/")
    assert r.status_code == 302 and "/portal" not in r.headers["Location"]


def test_choosing_synchro_passes_everything_on(app, synchro):
    c = app.test_client()
    r = c.get("/portal/go/synchro", headers=TUNNEL)
    assert r.status_code == 302 and "portal=synchro" in r.headers["Set-Cookie"]
    got = c.get("/api/orders?status=active", headers=TUNNEL).get_json()
    assert got["path"] == "/api/orders?status=active"
    assert got["cf"] == "203.0.113.7", "Synchro still knows the request came from the internet"
    r = c.post("/api/auth/login", json={"username": "x"}, headers=TUNNEL)
    assert r.get_json() == {"got": {"username": "x"}}
    cookies = r.headers.getlist("Set-Cookie")
    assert any(v.startswith("erp_sid=abc") for v in cookies) and any(v.startswith("other=1") for v in cookies)
    assert c.get("/api/missing").status_code == 404
    css = c.get("/static/style.css")
    assert css.status_code == 200 and "text/css" in css.headers["Content-Type"], "the chooser keeps its own styles"
    # the chooser stays reachable from Synchro, and going back to Docautomate works
    assert "Къде отивате?" in c.get("/portal").get_data(as_text=True)
    c.get("/portal/go/docautomate")
    r = c.get("/candidates")
    assert r.status_code == 302 and "/login" in r.headers["Location"] or "/setup" in r.headers["Location"]


def test_synchro_down_shows_a_way_back(app, monkeypatch):
    monkeypatch.setenv("SYNCHRO_URL", "http://127.0.0.1:9")
    c = app.test_client()
    assert "не работи" in c.get("/portal").get_data(as_text=True)
    c.get("/portal/go/synchro")
    r = c.get("/")
    assert r.status_code == 502 and "/portal/go/docautomate" in r.get_data(as_text=True)


def test_unknown_choice_and_spoofed_tunnel_header(app, synchro):
    c = app.test_client()
    assert c.get("/portal/go/evil").headers["Location"].endswith("/portal")
    # a Cloudflare header from a non-local address is not the tunnel
    r = c.get("/", headers=TUNNEL, environ_base={"REMOTE_ADDR": "198.51.100.1"})
    assert "/portal" not in r.headers["Location"]


def test_proxy_keeps_the_address_and_follows_http_rules(app, synchro):
    c = app.test_client()
    c.get("/portal/go/synchro")
    assert c.get("/api/orders/%D0%90%23x?q=%D0%B0").get_json()["path"] == "/api/orders/%D0%90%23x?q=%D0%B0"
    assert c.get("/api/orders/1?status=active").get_json()["path"] == "/api/orders/1?status=active"
    r = c.get("/api/hop", headers={"Connection": "X-Hop", "X-Hop": "secret", "Content-Encoding": "gzip"})
    assert r.get_json() == {"x_hop": None, "enc": "gzip"}, "a header named by Connection stays on this hop"
    assert "X-Up" not in r.headers and r.headers["Content-Encoding"] == "identity"
    r = c.get("/api/cut")
    assert r.status_code == 502 and "/portal/go/docautomate" in r.get_data(as_text=True)
