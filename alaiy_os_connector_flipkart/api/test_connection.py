# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Reachability check for the saved credentials. Wired into the registry via
connector_meta["test_method"] and called by the "Test Connection" button.
Always returns {"success": bool, "message": str} — never raises to the caller.

Flipkart has no generic /ping endpoint, so the real test IS the OAuth2
client_credentials exchange itself: if it returns an access token, the App ID
/ App Secret pair is valid and the sandbox/production toggle points at a
reachable host.
"""

import frappe
import requests

from alaiy_os_connector_flipkart.flipkart.client import FlipkartClient


@frappe.whitelist()
def test_connection():
    try:
        client = FlipkartClient()
    except RuntimeError as e:
        return {"success": False, "message": str(e)}

    try:
        client.get_access_token()
        env = "sandbox" if client.base_url.startswith("https://sandbox") else "production"
        return {"success": True, "message": f"Connected successfully ({env})."}
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status == 401:
            return {"success": False, "message": "Authentication failed — check App ID / App Secret."}
        body = e.response.text[:200] if e.response is not None else str(e)
        return {"success": False, "message": f"HTTP {status}: {body}"}
    except requests.exceptions.ConnectionError:
        return {"success": False, "message": f"Could not connect to {client.base_url}."}
    except requests.exceptions.Timeout:
        return {"success": False, "message": "Request timed out (30s)."}
    except Exception as e:
        return {"success": False, "message": str(e)[:200]}
