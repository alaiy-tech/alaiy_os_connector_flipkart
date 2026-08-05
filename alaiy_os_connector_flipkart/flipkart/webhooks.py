# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Inbound order/return notifications FROM Flipkart. Separate auth scheme from
the outbound OAuth2 client used by FlipkartClient — Flipkart signs each
notification request rather than us presenting a bearer token:

  X_Date: <HTTP-Date>
  X_Authorization: FKLOGIN Base64(app_id:fk_signature)

  fk_signature = SHA1(epoch_seconds(X_Date) + notification_url + HTTP_METHOD + app_secret)

`notification_url` in that hash is the exact URL registered with Flipkart's
notification service for this seller (Flipkart Connector Settings ->
flipkart_notification_url) — not whatever frappe.request.url happens to
report behind a proxy, since that can differ from what Flipkart itself signed
against.

Subscribing/unsubscribing notifications and registering the receiver URL
itself both happen outside this codebase (a support ticket via the Seller/
Partner Dashboard for the initial registration; POST /v3/notification/
subscription only toggles an existing subscription on/off, see Flipkart's
Order Management Notification docs) — this module only verifies and accepts
what Flipkart sends once that's set up.
"""

import base64
import hashlib
from email.utils import parsedate_to_datetime

import frappe


def _expected_signature(app_secret, notification_url, method, timestamp_epoch):
    raw = f"{timestamp_epoch}{notification_url}{method}{app_secret}"
    return hashlib.sha1(raw.encode()).hexdigest()


def verify_signature(x_date, x_authorization, method="POST"):
    """
    True only if the request's X_Authorization signature matches what we
    compute from our own stored App Secret + registered notification URL.
    Never raises — an unparseable header is just "not verified".
    """
    settings = frappe.get_single("Flipkart Connector Settings")
    app_secret = settings.get_password("flipkart_app_secret", raise_exception=False)
    notification_url = (settings.flipkart_notification_url or "").strip()
    if not app_secret or not notification_url or not x_date or not x_authorization:
        return False

    try:
        timestamp_epoch = int(parsedate_to_datetime(x_date).timestamp())
        prefix = "FKLOGIN "
        if not x_authorization.startswith(prefix):
            return False
        decoded = base64.b64decode(x_authorization[len(prefix):]).decode()
        app_id, _, signature = decoded.partition(":")
        if app_id != (settings.flipkart_app_id or "").strip():
            return False
        expected = _expected_signature(app_secret, notification_url, method, timestamp_epoch)
        return signature == expected
    except Exception:
        return False


@frappe.whitelist(allow_guest=True)
def receive_notification():
    """
    Entry point for Flipkart's notification service. Verifies the signature
    and records the raw event -- does not yet act on it (order/return sync
    from a webhook is separate work; see flipkart/sync.py's own TODOs).
    """
    request = frappe.request
    x_date = request.headers.get("X-Date") or request.headers.get("X_Date")
    x_authorization = request.headers.get("X-Authorization") or request.headers.get("X_Authorization")

    if not verify_signature(x_date, x_authorization, method=request.method):
        frappe.local.response.http_status_code = 401
        return {"error": "Signature verification failed."}

    payload = frappe.request.get_json(silent=True) or {}
    frappe.get_doc({
        "doctype": "Flipkart Sync Log",
        "sync_type": "pull",
        "trigger": "webhook",
        "status": "success",
        "log_messages": frappe.as_json(payload)[:9000],
    }).insert(ignore_permissions=True)
    frappe.db.commit()

    return {"message": "ok"}
