"""What both services need to talk to each other and to the browser safely.

Identical in both services (A2 decision: small shared code is copied, and CI
checks the copies match).

- require_internal_key: /internal/... endpoints are reachable from the internet
  on Azure (both services have public ingress for the browser), so each call
  must carry the shared INTERNAL_API_KEY in the X-Internal-Key header.
- add_cors: only the UI's origin may call the service from a browser. Done in
  code, not in Container Apps ingress, which rejects JSON preflights (Azure guide
  step 5).
"""

import hmac
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

INTERNAL_KEY_HEADER = "X-Internal-Key"


def require_internal_key(x_internal_key: Optional[str] = Header(default=None)) -> None:
    # compare_digest: the time taken doesn't reveal how much of the key matched.
    if not x_internal_key or not hmac.compare_digest(x_internal_key, settings.internal_api_key):
        raise HTTPException(status_code=401, detail="internal endpoint: missing or wrong key")


def add_cors(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type", "Authorization"],
        allow_credentials=False,  # the login is a header, never a cookie
    )
