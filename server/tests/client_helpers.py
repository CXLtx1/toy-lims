"""Browser fixtures opt in to CSRF; security rejection tests use raw clients."""

import secrets
from unittest.mock import patch
from urllib.parse import urlsplit

from flask.testing import FlaskClient
from werkzeug.datastructures import Headers

from security import RateLimiter, SAFE_METHODS


class BrowserClient(FlaskClient):
    def open(self, *args, **kwargs):
        # Werkzeug replays Request objects itself when following redirects.
        if args and isinstance(args[0], str):
            path = urlsplit(args[0]).path
            headers = Headers(kwargs.pop("headers", None))
            if path.startswith("/api/instrument/"):
                token = ("STANDARD_CLIENT_TOKEN" if path.startswith("/api/instrument/standard/")
                         else "XRF_CLIENT_TOKEN")
                headers.setdefault("X-Instrument-Token", self.application.config[token])
            elif kwargs.get("method", "GET").upper() not in SAFE_METHODS:
                base_url = kwargs.get("base_url", "http://localhost")
                with self.session_transaction(base_url=base_url) as session:
                    token = session.setdefault("csrf_token", secrets.token_urlsafe(32))
                headers.setdefault("Origin", base_url.rstrip("/"))
                headers.setdefault("X-CSRF-Token", token)
            kwargs["headers"] = headers
        return super().open(*args, **kwargs)


def browser_client(case, app):
    config = patch.dict(app.config, {
        "XRF_CLIENT_TOKEN": "test-xrf-device-token",
        "STANDARD_CLIENT_TOKEN": "test-standard-device-token",
    })
    config.start()
    case.addCleanup(config.stop)
    # A fresh limiter per test, not per request; limits stay active.
    limiter = patch.dict(app.extensions, {"security_rate_limiter": RateLimiter()})
    limiter.start()
    case.addCleanup(limiter.stop)
    return BrowserClient(app, app.response_class)
