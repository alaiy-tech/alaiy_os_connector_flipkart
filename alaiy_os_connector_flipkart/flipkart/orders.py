# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Order pull: Flipkart shipments -> Sales Order.

Confirmed against fk-api-platform-docs/docs/mp-api_versioned (raw HTML read
directly, not paraphrased):
  POST /sellers/v3/shipments/filter -- search shipments by filter.type
    (preDispatch / postDispatch / cancelled) + states[]. Response already
    embeds the full shipment payload (orderItems, subShipments, forms) --
    unlike listings, there is NO separate "details" call needed here.
  POST /sellers/v3/shipments/dispatch -- mark READY_TO_DISPATCH.
  POST /sellers/v3/shipments/cancel -- cancel order items in a shipment.
  This also resolves the earlier "/sellers/ vs /listings/" path-prefix
  ambiguity noted in listings.py, at least for shipments: the breadcrumb on
  every one of these pages literally reads "POST /sellers/v3/shipments/...",
  confirming our given docs' "/sellers/" prefix is the real one.

Genuinely documented gap, not guessed: the shipment schema (both the search
response and get-shipment-details) has NO buyer name/address/contact fields
at all -- order-management-intro.html states buyer phone/email are only
present on the get-shipment-details response for SELF-SHIP shipments, and
even then no shipping address. Standard Fulfilment orders never expose the
buyer to the seller through this API surface (Flipkart's logistics partner
handles delivery). So every imported order is billed to one fixed
placeholder Customer ("Flipkart Marketplace") -- there is no per-order
address to sync, unlike Shopify/Amazon.

Self-Ship's fuller state machine (dispatch/delivery/service attempts,
returns) is a materially different flow (order-management-intro.html) and
is NOT implemented here -- only Standard Fulfilment's shipment states
(APPROVED -> ... -> DELIVERED) via the plain GET/dispatch/cancel calls above.
"""

import json

import frappe
from frappe.utils import cint, flt, getdate, today

from alaiy_os_connector_flipkart.flipkart.client import FlipkartClient
from alaiy_os_connector_flipkart.flipkart.sync import (
    get_or_create_log,
    _mark_running,
    _mark_finished,
)

SHIPMENTS_FILTER_PATH = "/sellers/v3/shipments/filter"
SHIPMENTS_DISPATCH_PATH = "/sellers/v3/shipments/dispatch"
SHIPMENTS_CANCEL_PATH = "/sellers/v3/shipments/cancel"

# New orders sit in preDispatch; that's the only bucket worth importing --
# postDispatch/cancelled shipments are already-imported orders whose state
# changes we don't yet sync back onto the Sales Order.
_IMPORT_FILTER_TYPE = "preDispatch"
_PAGE_SIZE = 100

# Safety cap, same pattern as listings.py's _SEARCH_MAX_PAGES.
_SHIPMENTS_MAX_PAGES = 500

FLIPKART_CUSTOMER = "Flipkart Marketplace"


def _iter_shipments(client):
    body = {
        "filter": {"type": _IMPORT_FILTER_TYPE},
        "pagination": {"pageSize": _PAGE_SIZE},
    }
    resp = client.post(SHIPMENTS_FILTER_PATH, json=body)
    for _ in range(_SHIPMENTS_MAX_PAGES):
        for shipment in resp.get("shipments") or []:
            yield shipment
        if not resp.get("hasMore"):
            return
        next_url = resp.get("nextPageUrl")
        if not next_url:
            return  # hasMore=true but no cursor -- can't continue safely
        resp = client.get_absolute(next_url)


def _get_or_create_customer():
    if not frappe.db.exists("Customer", FLIPKART_CUSTOMER):
        frappe.get_doc({
            "doctype": "Customer",
            "customer_name": FLIPKART_CUSTOMER,
            "customer_type": "Company",
            "customer_group": frappe.db.get_single_value("Selling Settings", "customer_group")
            or "All Customer Groups",
            "territory": frappe.db.get_single_value("Selling Settings", "territory") or "All Territories",
        }).insert(ignore_permissions=True)
    return FLIPKART_CUSTOMER


def _resolve_item_code(sku):
    if sku and frappe.db.exists("Item", sku):
        return sku
    return None


def _upsert_order_from_shipment(shipment, settings, customer, warehouse, company, price_list):
    shipment_id = shipment.get("shipmentId")
    if not shipment_id:
        return False, "no shipmentId in shipment payload"
    if frappe.db.exists("Sales Order", {"flipkart_shipment_id": shipment_id, "docstatus": ["!=", 2]}):
        return False, None  # already imported

    order_items = shipment.get("orderItems") or []
    if not order_items:
        return False, f"shipment {shipment_id} has no orderItems"

    line_items = []
    for oi in order_items:
        item_code = _resolve_item_code(oi.get("sku"))
        if not item_code:
            frappe.log_error(
                title=f"Flipkart order import: unmapped SKU in shipment {shipment_id}",
                message=json.dumps(oi, default=str),
            )
            continue
        price = oi.get("priceComponents") or {}
        line_items.append({
            "item_code": item_code,
            "qty": cint(oi.get("quantity")) or 1,
            "rate": flt(price.get("sellingPrice")),
            "warehouse": warehouse,
        })

    if not line_items:
        return False, f"shipment {shipment_id}: no line item's SKU matched a local Item"

    order_date = getdate(order_items[0].get("orderDate")) if order_items[0].get("orderDate") else getdate(today())
    delivery_date = getdate(shipment.get("dispatchByDate")) if shipment.get("dispatchByDate") else order_date

    so = frappe.new_doc("Sales Order")
    so.customer = customer
    so.company = company
    so.transaction_date = order_date
    so.delivery_date = delivery_date
    so.selling_price_list = price_list
    so.set_warehouse = warehouse
    so.sales_channel = "Flipkart"
    so.flipkart_shipment_id = shipment_id
    for li in line_items:
        so.append("items", li)
    so.flags.ignore_permissions = True
    so.insert()
    frappe.db.commit()
    return True, None


def pull_orders(trigger="scheduled", log_name=None):
    """
    Full order pull: search preDispatch shipments (paginated) -> one Sales
    Order per shipment. Per-shipment upsert wrapped in its own try/except,
    same isolation pattern as listings.py's per-SKU upsert.
    """
    log = get_or_create_log("order_pull", trigger, log_name)
    _mark_running(log)

    processed = created = skipped = failed = 0
    try:
        client = FlipkartClient()
        settings = client._settings
        customer = _get_or_create_customer()
        company = settings.flipkart_company or frappe.defaults.get_global_default("company")
        warehouse = settings.flipkart_default_warehouse or frappe.defaults.get_global_default("warehouse")
        price_list = settings.flipkart_price_list or "Standard Selling"

        for shipment in _iter_shipments(client):
            processed += 1
            try:
                was_created, skip_reason = _upsert_order_from_shipment(
                    shipment, settings, customer, warehouse, company, price_list)
                if was_created:
                    created += 1
                elif skip_reason:
                    skipped += 1
                    frappe.log_error(
                        title="Flipkart order import: shipment skipped",
                        message=skip_reason,
                    )
            except Exception:
                failed += 1
                frappe.log_error(
                    title=f"Flipkart order import failed: {shipment.get('shipmentId')}",
                    message=frappe.get_traceback(),
                )

            if processed % 20 == 0:
                log.items_processed = processed
                log.items_created = created
                log.items_failed = failed
                log.save(ignore_permissions=True)
                frappe.db.commit()

        log.items_processed = processed
        log.items_created = created
        log.items_failed = failed
        log.save(ignore_permissions=True)
        frappe.db.commit()

        _mark_finished(log, "success" if failed == 0 else "failed",
                        error_message=(f"{failed} shipment(s) failed -- see Error Log." if failed else None))
    except Exception:
        _mark_finished(log, "failed", frappe.get_traceback())
        frappe.log_error(title="Flipkart order pull failed", message=frappe.get_traceback())
        raise

    return {"processed": processed, "created": created, "skipped": skipped, "failed": failed}


# ---------------------------------------------------------------------------
# Shipment actions -- Standard Fulfilment only (see module docstring)
# ---------------------------------------------------------------------------
def mark_ready_to_dispatch(shipment_ids):
    """POST /sellers/v3/shipments/dispatch -- shipment must already be PACKED
    (labels/invoice generated) per Flipkart's own documented state machine;
    that generation step (POST /v3/shipments/labels) isn't wired up yet."""
    client = FlipkartClient()
    return client.post(SHIPMENTS_DISPATCH_PATH, json={"shipmentIds": shipment_ids})


def cancel_shipment(order_item_ids, reason=None):
    client = FlipkartClient()
    body = {"orderItemIds": order_item_ids}
    if reason:
        body["cancelReason"] = reason
    return client.post(SHIPMENTS_CANCEL_PATH, json=body)
