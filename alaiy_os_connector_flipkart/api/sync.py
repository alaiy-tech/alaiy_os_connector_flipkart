# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Whitelisted entry points the Alaiy OS connector card and the settings form
call to kick off / inspect syncs. These stay thin: create the log so it shows
up as "queued" immediately, then enqueue the real work on the long queue.
"""

import frappe

from alaiy_os_connector_flipkart.flipkart.sync import get_or_create_log


@frappe.whitelist()
def trigger_pull_sync():
    """Manually enqueue a 'pull' sync (Flipkart → Alaiy OS)."""
    log = get_or_create_log("pull", "manual")
    frappe.enqueue(
        "alaiy_os_connector_flipkart.flipkart.sync.run_pull_sync",
        queue="long",
        timeout=600,
        trigger="manual",
        log_name=log.name,
    )
    return {"queued": True, "log_name": log.name}


@frappe.whitelist()
def trigger_push_sync():
    """Manually enqueue a 'push' sync (Alaiy OS → Flipkart)."""
    log = get_or_create_log("push", "manual")
    frappe.enqueue(
        "alaiy_os_connector_flipkart.flipkart.sync.run_push_sync",
        queue="long",
        timeout=600,
        trigger="manual",
        log_name=log.name,
    )
    return {"queued": True, "log_name": log.name}


@frappe.whitelist()
def trigger_order_pull():
    """Manually enqueue an order (shipment) pull."""
    log = get_or_create_log("order_pull", "manual")
    frappe.enqueue(
        "alaiy_os_connector_flipkart.flipkart.sync.run_order_pull",
        queue="long",
        timeout=600,
        trigger="manual",
        log_name=log.name,
    )
    return {"queued": True, "log_name": log.name}


@frappe.whitelist()
def mark_shipments_ready_to_dispatch(shipment_ids):
    """shipment_ids: JSON array or comma-separated string of shipment ids."""
    from alaiy_os_connector_flipkart.flipkart.orders import mark_ready_to_dispatch
    ids = frappe.parse_json(shipment_ids) if isinstance(shipment_ids, str) and shipment_ids.strip().startswith("[") \
        else [s.strip() for s in shipment_ids.split(",") if s.strip()]
    return mark_ready_to_dispatch(ids)


@frappe.whitelist()
def cancel_shipment(order_item_ids, reason=None):
    from alaiy_os_connector_flipkart.flipkart.orders import cancel_shipment as _cancel
    ids = frappe.parse_json(order_item_ids) if isinstance(order_item_ids, str) and order_item_ids.strip().startswith("[") \
        else [s.strip() for s in order_item_ids.split(",") if s.strip()]
    return _cancel(ids, reason=reason)


@frappe.whitelist()
def get_sync_status(sync_type=None):
    """
    Return the most recent Flipkart Sync Log rows, newest first.

    The Alaiy OS connector card passes the registry slot name ("categories"
    or "items"); map those to this connector's own sync_type values.
    """
    filters = {}
    if sync_type:
        type_map = {"categories": "pull", "items": "push"}
        filters["sync_type"] = type_map.get(sync_type, sync_type)
    return frappe.get_all(
        "Flipkart Sync Log",
        filters=filters,
        fields=[
            "name", "sync_type", "trigger", "status",
            "started_at", "finished_at",
            "items_processed", "items_created", "items_updated", "items_failed",
            "pages_total", "pages_done",
            "error_message",
        ],
        order_by="started_at desc",
        limit=10,
    )


@frappe.whitelist()
def get_dashboard_stats():
    """Local (Alaiy OS) counts for the Flipkart page's Overview card."""
    return {
        "listings_total": frappe.db.count("Flipkart Listing"),
        "listings_active": frappe.db.count("Flipkart Listing", {"listing_status": "ACTIVE"}),
        "listings_linked": frappe.db.count("Flipkart Listing", {"product": ["is", "set"]}),
        "orders_synced": frappe.db.count("Sales Order", {"sales_channel": "Flipkart"}),
    }
