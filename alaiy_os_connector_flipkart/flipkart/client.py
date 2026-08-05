# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Flipkart Seller API client — OAuth2 Client Credentials flow (self-access
application; see https://sandbox-api.flipkart.net/oauth-service/oauth/token).

Flipkart's Client Credentials flow (the one that applies here — a registered
seller integrating for their own orders/listings, not a third-party
aggregator using the Authorization Code flow):

  GET {base_url}/oauth-service/oauth/token?grant_type=client_credentials&scope=Seller_Api
  Authorization: Basic base64(app_id:app_secret)

  -> {"access_token": "...", "token_type": "bearer", "expires_in": <seconds>, "scope": "..."}

The token is long-lived (commonly ~38 days) but not permanent, so it's cached
on Flipkart Connector Settings (flipkart_access_token / flipkart_token_expires_at)
and only refreshed once it's actually close to expiry — every other API call
reuses the cached token instead of minting a new one per request.
"""

import base64

import frappe
import requests
from frappe.utils import add_to_date, now_datetime, get_datetime

PRODUCTION_BASE_URL = "https://api.flipkart.net"
SANDBOX_BASE_URL = "https://sandbox-api.flipkart.net"

TOKEN_PATH = "/oauth-service/oauth/token"
# Confirmed live against production: "Seller_Api,Default" is rejected with
# invalid_scope ("Invalid scope: Default") -- only the bare scope from the
# docs' own curl example works.
TOKEN_SCOPE = "Seller_Api"

# Refresh this many seconds before the token's real expiry, so a call in
# flight never gets caught using a token that expires mid-request.
_TOKEN_REFRESH_MARGIN_SECONDS = 300


class FlipkartClient:
    def __init__(self):
        settings = frappe.get_single("Flipkart Connector Settings")
        self.app_id = (settings.flipkart_app_id or "").strip()
        self.app_secret = (
            settings.get_password("flipkart_app_secret")
            if settings.flipkart_app_secret else None
        )
        if not self.app_id or not self.app_secret:
            raise RuntimeError("Flipkart connector is not configured (App ID / App Secret missing).")

        self.base_url = SANDBOX_BASE_URL if settings.flipkart_use_sandbox else PRODUCTION_BASE_URL
        self._settings = settings

    # -- Authentication --------------------------------------------------

    def _basic_auth_header(self):
        raw = f"{self.app_id}:{self.app_secret}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    def get_access_token(self):
        """Cached token if it's not close to expiry, otherwise fetch a fresh
        one and persist it (so every other worker/request reuses it too)."""
        cached_token = self._settings.get_password("flipkart_access_token", raise_exception=False)
        expires_at = self._settings.flipkart_token_expires_at
        if cached_token and expires_at and get_datetime(expires_at) > now_datetime():
            return cached_token
        return self._fetch_new_token()

    def _fetch_new_token(self):
        resp = requests.get(
            f"{self.base_url}{TOKEN_PATH}",
            params={"grant_type": "client_credentials", "scope": TOKEN_SCOPE},
            headers={"Authorization": self._basic_auth_header()},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data["access_token"]
        expires_in = int(data.get("expires_in") or 0)

        expires_at = add_to_date(
            now_datetime(), seconds=max(expires_in - _TOKEN_REFRESH_MARGIN_SECONDS, 0)
        )
        frappe.db.set_single_value("Flipkart Connector Settings", "flipkart_access_token", token)
        frappe.db.set_single_value("Flipkart Connector Settings", "flipkart_token_expires_at", expires_at)
        frappe.db.commit()
        self._settings.reload()
        return token

    def _headers(self):
        return {"Authorization": f"Bearer {self.get_access_token()}"}

    # -- Requests ----------------------------------------------------------

    def get(self, path, params=None, timeout=30):
        resp = requests.get(
            f"{self.base_url}/{path.lstrip('/')}",
            headers=self._headers(),
            params=params,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def post(self, path, json=None, timeout=30):
        resp = requests.post(
            f"{self.base_url}/{path.lstrip('/')}",
            headers=self._headers(),
            json=json,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()
