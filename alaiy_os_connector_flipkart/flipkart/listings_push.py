# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Listings PUSH: send price/inventory/listing updates from Alaiy OS out to
Flipkart. The reverse direction of listings.py's pull.

Confirmed against fk-api-platform-docs/docs/mp-api_versioned (raw HTML read
directly for each endpoint individually, not inferred from the summary
table):
  POST /sellers/listings/v3/update/price      -- price only
  POST /sellers/listings/v3/update/inventory  -- inventory/location only
  POST /sellers/listings/v3/update            -- full listing update
  POST /sellers/listings/v3                   -- create a brand-new listing

UNVERIFIED, flagged rather than guessed: every one of these endpoints'
request/response schema renders in the docs as "request -> property name*
object (...)" -- the standard OpenAPI/Redoc rendering for a body whose type
is `additionalProperties: <Schema>`, i.e. a MAP keyed by an arbitrary string,
not a single flat object. No concrete JSON example is shown anywhere in this
doc mirror for these four endpoints (unlike /listings/v3/details, whose
"available" map IS shown with a real example) and no raw OpenAPI yaml/json
backs this HTML mirror to check byte-for-byte. The response schema uses the
identical "property name*" pattern, and Flipkart's confirmed pull-side
convention (/details' "available" map) keys results by SKU -- so this code
assumes the request map is ALSO keyed by SKU (sku_id -> UpdatePriceRequest,
etc), matching that established pattern. This is the most defensible
inference available, not a wild guess, but it has NOT been confirmed against
a live sandbox call. VERIFY THIS FIRST against sandbox before any production
traffic -- same posture as the listings pull's path-prefix flag.

Gated behind flipkart_enable_push_sync (Flipkart Connector Settings) --
these are real writes to a live marketplace listing, not a safe-to-retry
read, so nothing here runs unless that switch is explicitly on. Checked at
every entry point in this module, not just by the caller, so a stray direct
call can't bypass it.
"""

import json

import frappe
from frappe.utils import cint, flt

from alaiy_os_connector_flipkart.flipkart.client import FlipkartClient

UPDATE_PRICE_PATH = "/sellers/listings/v3/update/price"
UPDATE_INVENTORY_PATH = "/sellers/listings/v3/update/inventory"
UPDATE_LISTING_PATH = "/sellers/listings/v3/update"
CREATE_LISTING_PATH = "/sellers/listings/v3"

# Flipkart's response for all four endpoints, per ListingChangeResponse.
_SUCCESS_STATUSES = {"SUCCESS", "WARNING"}


class PushSyncDisabled(Exception):
    pass


def _require_push_enabled(settings=None):
    settings = settings or frappe.get_single("Flipkart Connector Settings")
    if not settings.flipkart_enable_push_sync:
        raise PushSyncDisabled(
            "Two-way sync (push) is disabled in Flipkart Connector Settings. "
            "Enable 'Enable Two-Way Sync (Push)' before pushing price/inventory/listing changes."
        )
    return settings


def _price_block(listing):
    return {
        "mrp": cint(listing.mrp),
        "selling_price": cint(listing.selling_price),
        "mop": cint(listing.mop) if listing.mop else None,
        "nlc": cint(listing.nlc) if listing.nlc else None,
        "dealer_price": cint(listing.dealer_price) if listing.dealer_price else None,
        "currency": listing.currency or "INR",
    }


def _locations_block(listing):
    return [
        {
            "id": row.location_id,
            "status": row.status or "ENABLED",
            "inventory": cint(row.inventory),
            "pending_inventory": cint(row.pending_inventory),
        }
        for row in (listing.locations or [])
        if row.location_id
    ]


def update_price(sku_id, listing=None):
    """Push one listing's current price fields to Flipkart.
    listing: optional pre-loaded Flipkart Listing doc, to avoid a re-fetch
    when called from a loop that already has it."""
    _require_push_enabled()
    listing = listing or frappe.get_doc("Flipkart Listing", sku_id)

    client = FlipkartClient()
    body = {sku_id: {"product_id": listing.fsn, "price": _price_block(listing)}}
    resp = client.post(UPDATE_PRICE_PATH, json=body)
    return _check_response(resp, sku_id)


def update_inventory(sku_id, listing=None):
    """Push one listing's current locations/inventory to Flipkart."""
    _require_push_enabled()
    listing = listing or frappe.get_doc("Flipkart Listing", sku_id)

    client = FlipkartClient()
    body = {sku_id: {"product_id": listing.fsn, "locations": _locations_block(listing)}}
    resp = client.post(UPDATE_INVENTORY_PATH, json=body)
    return _check_response(resp, sku_id)


def _check_response(resp, sku_id):
    """resp is the top-level map keyed by sku_id (per this module's
    documented-but-unverified assumption) -- fall back to treating the
    whole response as the single result if that key isn't present, so a
    sandbox test immediately shows which shape was actually returned."""
    result = resp.get(sku_id, resp) if isinstance(resp, dict) else resp
    status = (result or {}).get("status") if isinstance(result, dict) else None
    ok = status in _SUCCESS_STATUSES
    if not ok:
        frappe.log_error(
            title=f"Flipkart push failed: {sku_id}",
            message=json.dumps(resp, default=str),
        )
    return ok, result


def push_price_and_inventory(sku_id):
    """Push both price and inventory for one listing -- the common case
    when something changed locally and needs to reflect on Flipkart."""
    _require_push_enabled()
    listing = frappe.get_doc("Flipkart Listing", sku_id)
    price_ok, price_result = update_price(sku_id, listing=listing)
    inventory_ok, inventory_result = update_inventory(sku_id, listing=listing)
    if price_ok and inventory_ok:
        listing.db_set("last_synced_at", frappe.utils.now_datetime())
    return {
        "price": {"ok": price_ok, "result": price_result},
        "inventory": {"ok": inventory_ok, "result": inventory_result},
    }


def run_push_sync(trigger="scheduled", log_name=None):
    """
    Push price + inventory for every Flipkart Listing linked to an Item
    (product set) -- the source of truth for outbound values is whatever's
    currently stored on the Flipkart Listing doc itself (mrp/selling_price/
    locations), same as the pull writes into. There is no live Item ->
    Flipkart price-list mapping yet; an operator (or future logic) edits
    the Flipkart Listing doc directly to change what gets pushed.
    """
    from alaiy_os_connector_flipkart.flipkart.sync import get_or_create_log, _mark_running, _mark_finished

    log = get_or_create_log("push", trigger, log_name)
    _mark_running(log)

    try:
        _require_push_enabled()
    except PushSyncDisabled as e:
        _mark_finished(log, "skipped", str(e))
        return {"processed": 0, "skipped_reason": str(e)}

    processed = updated = failed = 0
    try:
        sku_ids = frappe.get_all(
            "Flipkart Listing", filters={"product": ["is", "set"]}, pluck="name")

        for sku_id in sku_ids:
            processed += 1
            try:
                result = push_price_and_inventory(sku_id)
                if result["price"]["ok"] and result["inventory"]["ok"]:
                    updated += 1
                else:
                    failed += 1
            except Exception:
                failed += 1
                frappe.log_error(
                    title=f"Flipkart push sync failed: {sku_id}",
                    message=frappe.get_traceback(),
                )

            if processed % 20 == 0:
                log.items_processed = processed
                log.items_updated = updated
                log.items_failed = failed
                log.save(ignore_permissions=True)
                frappe.db.commit()

        log.items_processed = processed
        log.items_updated = updated
        log.items_failed = failed
        log.save(ignore_permissions=True)
        frappe.db.commit()

        _mark_finished(log, "success" if failed == 0 else "failed",
                        error_message=(f"{failed} listing(s) failed to push -- see Error Log." if failed else None))
    except Exception:
        _mark_finished(log, "failed", frappe.get_traceback())
        frappe.log_error(title="Flipkart push sync failed", message=frappe.get_traceback())
        raise

    return {"processed": processed, "updated": updated, "failed": failed}
