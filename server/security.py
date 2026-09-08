"""Browser security hooks. Install before authentication before-request hooks."""

import math
import os
import secrets
import threading
import time
from urllib.parse import urlsplit

from flask import current_app, g, jsonify, request, session
from flask.sessions import SecureCookieSessionInterface


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Exact endpoint names only. Each must retain its independent instrument auth.
INSTRUMENT_ENDPOINTS = frozenset({
    "standard_client_authorize", "standard_client_session_touch", "standard_client_logout",
    "standard_client_instruments", "standard_client_status", "standard_client_tasks",
    "standard_client_start_sample", "standard_client_submit", "xrf_client_tasks",
    "xrf_client_status", "xrf_client_import", "xrf_client_import_batch",
    "xrf_uq_import", "xrf_uq_import_batch", "xrf_sync_state",
})
RATE_ACTIONS = {"auth.login": "login", "auth.setup": "setup",
                "auth.authorize": "authorize", "standard_client_authorize": "authorize"}


class RateLimiter:
    """Bounded process-local fixed windows, with no rejected-attempt extension.

    A full table rejects new keys until a window expires instead of evicting
    existing limits. Multi-worker deployments also need an ingress/shared limit.
    """

    def __init__(self, max_keys=4096, clock=time.monotonic):
        if max_keys < 1:
            raise ValueError("max_keys must be positive")
        self.max_keys = max_keys
        self.clock = clock
        self._entries = {}
        self._lock = threading.Lock()

    def check(self, ip, action, limit, window):
        if limit < 1 or window <= 0:
            raise ValueError("rate limits must be positive")
        with self._lock:
            now = self.clock()
            expired = [key for key, (_, until) in self._entries.items() if until <= now]
            for key in expired:
                del self._entries[key]
            key = (ip, action)
            count, until = self._entries.get(key, (0, now + window))
            if key not in self._entries and len(self._entries) >= self.max_keys:
                retry = max(1, math.ceil(min(end for _, end in self._entries.values()) - now))
                return {"allowed": False, "limit": limit, "remaining": 0, "retry_after": retry}
            allowed = count < limit
            if allowed:
                count += 1
                self._entries[key] = (count, until)
            return {"allowed": allowed, "limit": limit, "remaining": max(0, limit - count),
                    "retry_after": max(1, math.ceil(until - now))}


def _env_bool(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip().lower()
    if value not in {"1", "true", "yes", "0", "false", "no"}:
        raise ValueError(f"{name} must be a boolean")
    return value in {"1", "true", "yes"}


def _local_http():
    return (request.remote_addr in {"127.0.0.1", "::1"} and
            urlsplit(request.host_url).hostname in {"localhost", "127.0.0.1", "::1"})


class SecuritySessionInterface(SecureCookieSessionInterface):
    def get_cookie_secure(self, app):
        override = app.config["SECURITY_COOKIE_SECURE"]
        if override is not None:
            return override
        return bool(app.config.get("SESSION_COOKIE_SECURE") or request.is_secure or not _local_http())


def csrf_token():
    if not session.get("csrf_token"):
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def csp_nonce():
    if not getattr(g, "csp_nonce", None):
        g.csp_nonce = secrets.token_urlsafe(24)
    return g.csp_nonce


def _origin(value, *, referer=False):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or
                parsed.username is not None or parsed.password is not None or
                (not referer and (parsed.path or parsed.query or parsed.fragment))):
            return None
        return (parsed.scheme, parsed.hostname.lower(),
                parsed.port or (443 if parsed.scheme == "https" else 80))
    except ValueError:
        return None


def protect_request():
    if (current_app.config["SECURITY_REQUIRE_HTTPS"] and not request.is_secure
            and not _local_http()):
        return jsonify(ok=False, code="https_required", error="HTTPS is required"), 403
    if request.method in SAFE_METHODS:
        return None
    if request.endpoint not in INSTRUMENT_ENDPOINTS:
        expected = _origin(request.host_url, referer=True)
        origin = request.headers.get("Origin")
        referer = request.headers.get("Referer")
        if (request.headers.get("Sec-Fetch-Site") not in {None, "same-origin", "none"}
                or (origin is None and not referer)
                or (origin is not None and _origin(origin) != expected)
                or (referer is not None and _origin(referer, referer=True) != expected)):
            return jsonify(ok=False, code="csrf_origin", error="Same-origin request required"), 403
        supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
        token = session.get("csrf_token")
        if (not isinstance(token, str) or not isinstance(supplied, str) or not token
                or not secrets.compare_digest(token.encode(), supplied.encode())):
            return jsonify(ok=False, code="csrf_invalid", error="Invalid or missing CSRF token"), 403
    action = RATE_ACTIONS.get(request.endpoint)
    if action:
        limit, window = current_app.config["SECURITY_RATE_LIMITS"][action]
        info = current_app.extensions["security_rate_limiter"].check(
            request.remote_addr or "unknown", action, limit, window)
        g.security_rate = info
        if not info["allowed"]:
            return jsonify(ok=False, code="rate_limited", error="Too many attempts; try again later",
                           retry_after=info["retry_after"]), 429
    return None


def security_headers(response):
    nonce = getattr(g, "csp_nonce", None)
    scripts = "'self'" + (f" 'nonce-{nonce}'" if nonce else "")
    response.headers["Content-Security-Policy"] = (
        f"default-src 'self'; script-src {scripts}; script-src-attr 'none'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
        "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'")
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    if (response.mimetype == "text/html" or request.path.startswith("/api/")
            or (request.endpoint or "").startswith("auth.")):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    info = getattr(g, "security_rate", None)
    if info:
        response.headers["RateLimit-Limit"] = str(info["limit"])
        response.headers["RateLimit-Remaining"] = str(info["remaining"])
        response.headers["RateLimit-Reset"] = str(info["retry_after"])
        if not info["allowed"]:
            response.headers["Retry-After"] = str(info["retry_after"])
    return response


def init_security(app):
    """Call once after app config, BEFORE registering auth before-request hooks.

    No AUTH_DISABLED/TESTING bypass: tests must use real CSRF tokens and origins.
    Trust forwarded headers only through a correctly configured trusted proxy.
    """
    if "security_rate_limiter" in app.extensions:
        raise RuntimeError("security already initialized")
    app.config.setdefault("SECURITY_REQUIRE_HTTPS", _env_bool("LIMS_REQUIRE_HTTPS", True))
    app.config.setdefault("SECURITY_COOKIE_SECURE", _env_bool("LIMS_SESSION_COOKIE_SECURE", None))
    app.config.setdefault("SECURITY_RATE_LIMITS", {
        "login": (10, 60), "setup": (5, 60), "authorize": (20, 60)})
    app.config.setdefault("SECURITY_RATE_MAX_KEYS", 4096)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict")
    app.session_interface = SecuritySessionInterface()
    app.extensions["security_rate_limiter"] = RateLimiter(app.config["SECURITY_RATE_MAX_KEYS"])
    app.before_request(protect_request)
    app.after_request(security_headers)
    app.context_processor(lambda: {"csrf_token": csrf_token, "csp_nonce": csp_nonce})

    @app.errorhandler(500)
    def internal_error(_error):
        # Flask logs the original exception; never send database details to clients.
        return jsonify(ok=False, code="internal_error", error="Internal server error"), 500
