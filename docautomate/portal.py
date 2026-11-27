"""One web address for two programs: Docautomate and Synchro (the office ERP: orders, contracts, accounting).

Opened through the internet link (Cloudflare tunnel), the start page asks where to go. The choice is kept in a
cookie. In Synchro mode every request is passed to the local Synchro server (SYNCHRO_URL, default
http://127.0.0.1:4810), so one tunnel serves both. /portal is always the chooser, from either program.
"""
from __future__ import annotations

import os
import urllib.error
import urllib.request

from flask import Response, make_response, redirect, render_template, request

COOKIE = "portal"
# headers that belong to one connection and are never passed on
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding",
       "upgrade", "host", "content-length", "accept-encoding", "content-encoding"}


def synchro_url() -> str:
    return os.environ.get("SYNCHRO_URL", "http://127.0.0.1:4810").rstrip("/")


def via_tunnel() -> bool:
    """Cloudflare marks every request it forwards; the tunnel connects from this machine."""
    return bool(request.headers.get("Cf-Connecting-Ip") or request.headers.get("Cf-Ray")) and \
        (request.remote_addr or "").startswith(("127.", "::1", "::ffff:127."))


def synchro_alive(timeout: float = 0.8) -> bool:
    try:
        with urllib.request.urlopen(synchro_url() + "/api/auth/state", timeout=timeout) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001  (any failure means: not reachable now)
        return False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # the browser follows redirects itself
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def proxy() -> Response:
    url = synchro_url() + request.full_path.rstrip("?") if request.query_string else synchro_url() + request.path
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
    headers["X-Forwarded-Proto"] = request.headers.get("X-Forwarded-Proto", request.scheme)
    body = request.get_data() if request.method not in ("GET", "HEAD") else None
    req = urllib.request.Request(url, data=body, headers=headers, method=request.method)
    try:
        upstream = _opener.open(req, timeout=60)
    except urllib.error.HTTPError as e:  # 4xx/5xx and redirects are answers too
        upstream = e
    except (urllib.error.URLError, OSError):
        return make_response(render_template("portal_down.html", url=synchro_url()), 502)
    data = upstream.read()
    resp = Response(data, status=upstream.status if hasattr(upstream, "status") else upstream.code)
    for k, v in upstream.headers.items():
        if k.lower() not in HOP and k.lower() != "set-cookie":
            resp.headers[k] = v
    for c in upstream.headers.get_all("Set-Cookie") or []:
        resp.headers.add("Set-Cookie", c)
    return resp


def register(app) -> None:
    """Must run before auth.register: Synchro requests never reach Docautomate's login."""

    @app.before_request
    def _portal():
        path = request.path
        if path == "/portal":
            return render_template("portal.html", synchro_ok=synchro_alive(), current=request.cookies.get(COOKIE))
        if path.startswith("/portal/go/"):
            target = path.rsplit("/", 1)[-1]
            if target not in ("docautomate", "synchro"):
                return redirect("/portal")
            resp = redirect("/")
            # readable by Synchro's page, so it can show the way back; not a secret
            resp.set_cookie(COOKIE, target, max_age=180 * 86400, samesite="Lax", secure=request.is_secure or via_tunnel())
            return resp
        mode = request.cookies.get(COOKIE)
        # /static/ is Docautomate's own (the chooser's styles); Synchro serves its files from /assets/
        if mode == "synchro" and not path.startswith("/static/"):
            return proxy()
        if mode is None and path == "/" and request.method == "GET" and via_tunnel():
            return redirect("/portal")
        return None
