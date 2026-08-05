# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Product/listing IMPORT: pull Flipkart's existing listings into Alaiy OS as
`Flipkart Listing` records (mirrors the Amazon SP-API connector's
`Amazon Listing` pattern -- a marketplace listing stands on its own, with an
OPTIONAL, never-auto-set link to an Item, rather than being pushed straight
into Item like Unicommerce's plain catalogue import).

Two-step pull, per Flipkart's documented API shape:
  1. POST /sellers/listings/v3/search -- paginated (batch of 500), returns
     only listing_id/product_id/sku_id per Flipkart's docs (no price/status).
  2. POST /sellers/listings/v3/details -- batched <= 10 SKUs per call, the
     endpoint that actually returns price/tax/status/locations.

Known, documented gaps carried over from research (do not silently paper
over these -- they're real ambiguities in Flipkart's own docs, not
assumptions made here):
  * No field literally named "fsn" appears in any response schema. We store
    the response's `product_id` into our own `fsn` field as the most likely
    candidate, but Flipkart's docs never state that equivalence -- flagged
    on the doctype field itself too.
  * The search endpoint's own schema table types `listings` as a single
    object even though the endpoint description says "batch of 500" --
    handled defensively below (accept dict OR list).
  * No documented "no more pages" signal beyond `has_more: false` -- trusted
    as the sole termination condition.
"""

import json

import frappe
from frappe.utils import cint, flt, now_datetime

from alaiy_os_connector_flipkart.flipkart.client import FlipkartClient
from alaiy_os_connector_flipkart.flipkart.sync import (
    get_or_create_log,
    _mark_running,
    _mark_finished,
)

SEARCH_PATH = "/sellers/listings/v3/search"
DETAILS_PATH = "/sellers/listings/v3/details"

SEARCH_BATCH_SIZE = 500  # Flipkart's own documented batch size for /search
DETAILS_BATCH_SIZE = 10  # Flipkart's own documented max SKUs per /details call

# Safety cap so a runaway pagination loop (e.g. a broken next_page_id echo)
# can never spin forever -- same defensive pattern as Amazon's SEARCH_MAX_PAGES.
_SEARCH_MAX_PAGES = 200


def _search_page(client, page_id=None):
    body = {"page_id": page_id}
    return client.post(SEARCH_PATH, json=body)


def _iter_search_results(client):
    """
    Yields (sku_id, listing_id, product_id) tuples across every page.
    Defensive against the documented schema/description mismatch: Flipkart's
    schema table types `listings` as a single object, but the batch-of-500
    description implies a list -- accept either shape rather than assuming.
    """
    page_id = None
    for _ in range(_SEARCH_MAX_PAGES):
        resp = _search_page(client, page_id=page_id)
        listings = resp.get("listings")
        if listings is None:
            listings = []
        elif isinstance(listings, dict):
            listings = [listings]

        for entry in listings:
            sku_id = entry.get("sku_id")
            if not sku_id:
                continue
            yield sku_id, entry.get("listing_id"), entry.get("product_id")

        if not resp.get("has_more"):
            return
        page_id = resp.get("next_page_id")
        if not page_id:
            return  # has_more=true but no cursor given -- can't continue safely


def _chunk(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _upsert_from_detail(sku_id, detail, search_hint=None):
    """
    detail is one value from the /details response's "available" map --
    i.e. the MarketplaceListingDetail shape (listing_id, product_id, price,
    tax, listing_status, fulfillment_profile, locations, archived_status).
    search_hint is the (listing_id, product_id) pair from the search step,
    used only as a fallback if /details omits them for some reason.
    """
    price = detail.get("price") or {}
    tax = detail.get("tax") or {}

    values = {
        "listing_id": detail.get("listing_id") or (search_hint[0] if search_hint else None),
        "fsn": detail.get("product_id") or (search_hint[1] if search_hint else None),
        "listing_status": detail.get("listing_status"),
        "archived_status": detail.get("archived_status") or "NONE",
        "fulfillment_profile": detail.get("fulfillment_profile"),
        "mrp": flt(price.get("mrp")) if price.get("mrp") is not None else None,
        "selling_price": flt(price.get("selling_price")) if price.get("selling_price") is not None else None,
        "mop": flt(price.get("mop")) if price.get("mop") is not None else None,
        "nlc": flt(price.get("nlc")) if price.get("nlc") is not None else None,
        "dealer_price": flt(price.get("dealer_price")) if price.get("dealer_price") is not None else None,
        "currency": price.get("currency"),
        "hsn": tax.get("hsn"),
        "tax_code": tax.get("tax_code"),
        "goods_services_rate": flt(tax.get("goods_services_rate")) if tax.get("goods_services_rate") is not None else None,
        "is_gst_sellable": 1 if tax.get("is_gst_sellable") else 0,
        "luxury_cess_percentage": flt(tax.get("luxury_cess_percentage")) if tax.get("luxury_cess_percentage") is not None else None,
        "last_synced_at": now_datetime(),
        "raw_summary": json.dumps(detail, default=str)[:100000],
    }

    locations = []
    for loc in detail.get("locations") or []:
        locations.append({
            "location_id": loc.get("id"),
            "status": loc.get("status"),
            "inventory": cint(loc.get("inventory")) if loc.get("inventory") is not None else 0,
            "pending_inventory": cint(loc.get("pending_inventory")) if loc.get("pending_inventory") is not None else 0,
        })

    if frappe.db.exists("Flipkart Listing", sku_id):
        doc = frappe.get_doc("Flipkart Listing", sku_id)
        doc.update(values)
        is_new = False
    else:
        doc = frappe.get_doc({"doctype": "Flipkart Listing", "sku": sku_id, **values})
        is_new = True

    doc.set("locations", locations)
    doc.flags.ignore_permissions = True
    if is_new:
        doc.insert(ignore_permissions=True)
    else:
        doc.save(ignore_permissions=True)
    return is_new


def pull_all_listings(trigger="scheduled", log_name=None):
    """
    Full listing import: search (paginated) -> details (batched) -> upsert.
    Unlike the Amazon precedent (whole-batch failure), each SKU's upsert is
    isolated with its own try/except so one bad record doesn't roll back an
    entire batch -- counters (items_created/items_updated/items_failed) are
    updated incrementally and the log is saved after every details batch.
    """
    log = get_or_create_log("pull", trigger, log_name)
    _mark_running(log)

    processed = created = updated = failed = 0
    try:
        client = FlipkartClient()

        search_hints = {}  # sku_id -> (listing_id, product_id)
        for sku_id, listing_id, product_id in _iter_search_results(client):
            search_hints[sku_id] = (listing_id, product_id)

        log.pages_total = len(search_hints)
        log.save(ignore_permissions=True)
        frappe.db.commit()

        sku_ids = list(search_hints.keys())
        for batch in _chunk(sku_ids, DETAILS_BATCH_SIZE):
            try:
                resp = client.post(DETAILS_PATH, json={"sku_ids": batch})
            except Exception:
                failed += len(batch)
                processed += len(batch)
                frappe.log_error(
                    title="Flipkart listing details batch failed",
                    message=frappe.get_traceback(),
                )
                continue

            available = resp.get("available") or {}
            for sku_id in batch:
                processed += 1
                detail = available.get(sku_id)
                if not detail:
                    failed += 1
                    continue
                try:
                    is_new = _upsert_from_detail(sku_id, detail, search_hint=search_hints.get(sku_id))
                    if is_new:
                        created += 1
                    else:
                        updated += 1
                except Exception:
                    failed += 1
                    frappe.log_error(
                        title=f"Flipkart listing upsert failed: {sku_id}",
                        message=frappe.get_traceback(),
                    )

            log.items_processed = processed
            log.items_created = created
            log.items_updated = updated
            log.items_failed = failed
            log.pages_done = processed
            log.save(ignore_permissions=True)
            frappe.db.commit()

        _mark_finished(log, "success" if failed == 0 else "failed",
                        error_message=(f"{failed} listing(s) failed -- see Error Log." if failed else None))
    except Exception:
        _mark_finished(log, "failed", frappe.get_traceback())
        frappe.log_error(title="Flipkart listing pull failed", message=frappe.get_traceback())
        raise

    return {"processed": processed, "created": created, "updated": updated, "failed": failed}
