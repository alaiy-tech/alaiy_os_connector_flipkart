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
Partner Dashboard for the initial registration -- confirmed from
order-management-notifications.html's own "Subscribing to Notifications"
section, which lists it as a manual ticket process, not an API call. POST
/v3/notification/subscription only toggles order/returns notifications on/off
for a subscription that ALREADY exists -- it has no field for a callback URL
at all, confirmed by reading its request schema directly) -- this module only
verifies and acts on what Flipkart sends once that manual setup is done.

Event routing, confirmed against order-management-notifications-reference.html
(every event's own EventStructure + Example, read individually, not inferred
from the summary table):
  shipment_created            -> create the Sales Order (reuses orders.py's
                                  own dedup-by-shipment-id upsert, so a
                                  redelivered notification -- the docs say
                                  delivery is at-least-once, not exactly-once
                                  -- is naturally a no-op the second time)
  shipment_packed /
  shipment_ready_to_dispatch /
  shipment_shipped /
  shipment_delivered /
  shipment_unhold              -> attributes.status written onto the Sales
                                   Order's flipkart_shipment_status field
  shipment_cancelled            -> flipkart_shipment_status set to CANCELLED.
                                    Deliberately does NOT cancel the Sales
                                    Order document itself -- that's a
                                    financial document and auto-cancelling it
                                    from a webhook is a real-money decision,
                                    left for manual review instead of guessed.
  shipment_hold /
  shipment_dispatch_dates_changed /
  shipment_form_failed /
  return_*  (6 event types)      -> logged only, not acted on. Return sync
                                     and the hold/dispatch-date side-effects
                                     are separate unbuilt features (see the
                                     connector's own pending-features report)
                                     -- routing them here would be guessing
                                     what "acting on" a return even means
                                     before that feature exists.

Every branch still returns {"message": "ok"} / 200 per the docs' own
contract ("respond with 200, or throw only when the seller system is down
or the payload is malformed") -- an unhandled-but-valid eventType is not a
malformed payload, so it must not fail the webhook.
"""

import base64
import hashlib
import json
from email.utils import parsedate_to_datetime

import frappe

_STATUS_ONLY_EVENTS = {
    "shipment_packed", "shipment_ready_to_dispatch",
    "shipment_shipped", "shipment_delivered", "shipment_unhold",
}
_LOG_ONLY_EVENTS = {
    "shipment_hold", "shipment_dispatch_dates_changed", "shipment_form_failed",
    "return_created", "return_tracking_id_updated", "return_expected_date_changed",
    "return_picked_up", "return_completed", "return_cancelled",
}


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


def _log_event(event_type, trigger_status, payload):
    frappe.get_doc({
        "doctype": "Flipkart Sync Log",
        "sync_type": "order_pull",
        "trigger": "webhook",
        "status": trigger_status,
        "log_messages": f"{event_type}: {json.dumps(payload, default=str)[:9000]}",
    }).insert(ignore_permissions=True)
    frappe.db.commit()


def _find_sales_order(shipment_id):
    return frappe.db.get_value(
        "Sales Order", {"flipkart_shipment_id": shipment_id, "docstatus": ["!=", 2]}, "name")


def _handle_shipment_created(payload):
    from alaiy_os_connector_flipkart.flipkart.client import FlipkartClient
    from alaiy_os_connector_flipkart.flipkart.orders import (
        _upsert_order_from_shipment, _get_or_create_customer,
    )

    shipment_id = payload.get("shipmentId")
    attrs = payload.get("attributes") or {}
    if not shipment_id or not attrs.get("orderItems"):
        _log_event(payload.get("eventType", "shipment_created"), "failed", payload)
        return

    # Same shape orders.py's pull already understands -- the notification's
    # `attributes` is the shipment body, `shipmentId` is just a sibling key
    # here instead of nested inside it.
    shipment = dict(attrs)
    shipment["shipmentId"] = shipment_id

    client = FlipkartClient()
    settings = client._settings
    customer = _get_or_create_customer()
    company = settings.flipkart_company or frappe.defaults.get_global_default("company")
    warehouse = settings.flipkart_default_warehouse or frappe.defaults.get_global_default("warehouse")
    price_list = settings.flipkart_price_list or "Standard Selling"

    was_created, skip_reason = _upsert_order_from_shipment(
        shipment, settings, customer, warehouse, company, price_list)
    _log_event("shipment_created", "success" if was_created or not skip_reason else "skipped", payload)


def _handle_status_update(payload):
    shipment_id = payload.get("shipmentId")
    status = (payload.get("attributes") or {}).get("status")
    if not shipment_id or not status:
        _log_event(payload.get("eventType", "status_update"), "failed", payload)
        return

    so_name = _find_sales_order(shipment_id)
    if not so_name:
        # Notification arrived before/without a matching Sales Order (e.g.
        # order pull hasn't run yet, or the SKU didn't map to a local Item
        # at import time) -- not an error on Flipkart's side, just nothing
        # to update yet.
        _log_event(payload.get("eventType", "status_update"), "skipped", payload)
        return

    frappe.db.set_value("Sales Order", so_name, "flipkart_shipment_status", status[:140])
    frappe.db.commit()
    _log_event(payload.get("eventType", "status_update"), "success", payload)


_HANDLERS = {
    "shipment_created": _handle_shipment_created,
    "shipment_cancelled": _handle_status_update,  # attributes.status is "CANCELLED" too
}


@frappe.whitelist(allow_guest=True)
def receive_notification():
    """
    Entry point for Flipkart's notification service. Verifies the signature,
    then routes by eventType. Always returns 200/{"message": "ok"} for any
    signature-valid, JSON-parseable payload -- per the docs, a non-200 here
    should only happen when this system is down or the payload itself is
    malformed, not because we don't yet act on a given eventType.
    """
    request = frappe.request
    x_date = request.headers.get("X-Date") or request.headers.get("X_Date")
    x_authorization = request.headers.get("X-Authorization") or request.headers.get("X_Authorization")

    if not verify_signature(x_date, x_authorization, method=request.method):
        frappe.local.response.http_status_code = 401
        return {"error": "Signature verification failed."}

    payload = frappe.request.get_json(silent=True)
    if payload is None:
        frappe.local.response.http_status_code = 400
        return {"error": "Malformed JSON payload."}

    event_type = payload.get("eventType")

    try:
        if event_type in _HANDLERS:
            _HANDLERS[event_type](payload)
        elif event_type in _STATUS_ONLY_EVENTS:
            _handle_status_update(payload)
        elif event_type in _LOG_ONLY_EVENTS:
            _log_event(event_type, "skipped", payload)
        else:
            # Unknown eventType (a new one Flipkart added since these docs
            # were written, most likely) -- log it rather than silently
            # dropping, but still 200 since the payload itself is valid.
            _log_event(event_type or "unknown", "skipped", payload)
    except Exception:
        frappe.log_error(
            title=f"Flipkart webhook: {event_type} handling failed",
            message=frappe.get_traceback(),
        )
        # Still 200 -- our own bug in handling a valid notification isn't
        # "the seller system is down" or "payload incorrect", and Flipkart
        # will keep retrying an errored webhook, which would just repeat
        # the same failure forever.

    return {"message": "ok"}
