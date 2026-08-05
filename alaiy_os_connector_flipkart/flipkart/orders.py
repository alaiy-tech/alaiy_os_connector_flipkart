# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Order pull: Flipkart shipments -> Sales Order. NOT implemented yet -- the
order/shipment API shape (Standard vs Self-Ship fulfilment, the pack ->
ready-to-dispatch -> shipped -> delivered state machine, get-shipment-details
response schema) still needs the same careful docs-verification pass that
flipkart/listings.py went through before real sync logic gets written here.
See the Phase 2 research notes: Flipkart's order model is closer to
Unicommerce's fulfillment submodule (discrete stateful steps) than Shopify's
simpler order push, and Self-Ship orders need a materially different state
machine than Standard Fulfilment ones.

sales_channel is the one piece that's safe to wire up now: alaiy_os core
already ships a generic `sales_channel` field on Sales Order (added earlier
this session), written by every connector that pulls orders --
Shopify writes "Shopify" (shopify/order/upsert.py), Unicommerce writes the
order's own Channel display_name (unicommerce/order/pull.py, since one
Unicommerce account can aggregate several real storefronts). Flipkart is a
single fixed channel like Shopify, so it's always the literal string
"Flipkart", not a per-order lookup.

flipkart_shipment_id (Sales Order custom field, see setup/install.py) is the
intended dedup key once real import exists -- Flipkart's shipment is the
actual fulfilment unit (one order can split into multiple shipments), not
the order id itself.
"""

SALES_CHANNEL = "Flipkart"


def _create_order(shipment_data):
    """
    TODO: implement once the shipment/order API shape is confirmed.
    Sketch of the one settled piece (sales_channel) for when this gets built:

        sales_order = frappe.get_doc({
            "doctype": "Sales Order",
            ...
            "sales_channel": SALES_CHANNEL,
            "flipkart_shipment_id": shipment_data["shipment_id"],
            ...
        })
    """
    raise NotImplementedError("Flipkart order pull is not implemented yet.")
