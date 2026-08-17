# Flipkart Connector — what it actually does

Flipkart is a marketplace channel: sellers list products and fulfil orders
through Flipkart's Seller API. Alaiy OS is the ERPNext-based back office. This
connector moves listing data and orders between the two, using Flipkart's
OAuth2 Seller API (`client.py`) plus one inbound webhook for order/return
notifications (`webhooks.py`).

---

## The short version

| | Direction | Automatic? |
|---|---|---|
| Listings (product/price/tax/stock) | Flipkart → Alaiy OS | yes, on the configured Pull interval, or manual "Pull" button |
| Listings (price + inventory) | Alaiy OS → Flipkart | **only if** "Enable Two-Way Sync (Push)" is on, then on the configured Push interval, or manual "Push" button |
| New listing creation on Flipkart | Alaiy OS → Flipkart | **not built.** `listings_push.py` only has `update_price` / `update_inventory`; there is no code path that calls the create-listing endpoint. |
| Orders (preDispatch shipments) | Flipkart → Alaiy OS | yes, on the configured Pull interval (shares `flipkart_pull_sync_interval`), manual "Pull" button, or immediately via the `shipment_created` webhook |
| Order status changes (packed/shipped/delivered/cancelled) | Flipkart → Alaiy OS | yes, automatically, but **only via the webhook** — there is no polling for shipment status changes on already-imported orders |
| Shipment dispatch / cancel actions | Alaiy OS → Flipkart | manual only — `mark_shipments_ready_to_dispatch` / `cancel_shipment` are whitelisted methods with no caller wired up in this codebase (called from a client script or REST call, not from a UI button visible here) |
| Sales Order cancellation on `shipment_cancelled` | — | **never happens automatically.** The webhook only updates the `flipkart_shipment_status` field to `CANCELLED`; it deliberately never cancels the Sales Order document itself, left for manual review since that's a financial document. |

**Nothing writes to Flipkart unless "Enable Two-Way Sync (Push)" is turned on
explicitly** — the pull side (listings and orders) is read-only against
Flipkart and always safe to run; every write (price update, inventory update,
listing update/create) is gated behind that one switch, checked both by the
scheduler and by the module functions themselves so a direct call can't
bypass it. Turning the connector on (`is_enabled`) only lets pull syncs run
and provisions two Item/Sales Order custom fields — it does **not** turn on
push.

---

## Coming IN from Flipkart

### Listings
`flipkart/listings.py` runs a two-step pull: `POST /sellers/listings/v3/search`
(paginated, 500/page) to enumerate every SKU, then
`POST /sellers/listings/v3/details` (batched, 10 SKUs/call) to fetch
price/tax/status/location detail. Each SKU becomes an Item (`item_code` =
Flipkart's `sku_id`, created if missing) plus a linked `Flipkart Listing` row
holding price, tax, and per-location inventory. Runs on the configured Pull
interval, on the manual "Pull" button, or from `bench execute`.

### Orders
`flipkart/orders.py` searches `POST /sellers/v3/shipments/filter` for
`preDispatch` shipments and creates one Sales Order per shipment, billed to a
single fixed placeholder Customer ("Flipkart Marketplace") — Flipkart's
Standard Fulfilment API never exposes buyer name/address to the seller.
Dedup key is `flipkart_shipment_id` on the Sales Order.

### Order/return notifications (webhook)
`flipkart/webhooks.py` exposes `receive_notification` (guest-accessible,
signature-verified). `shipment_created` creates the Sales Order immediately
(same dedup path as the pull, so a re-delivered notification is a no-op).
`shipment_packed` / `_ready_to_dispatch` / `_shipped` / `_delivered` /
`_unhold` / `_cancelled` update `flipkart_shipment_status` on the matching
Sales Order. Everything else (hold, dispatch-date-changed, form-failed, all 6
return events) is logged to Flipkart Sync Log only — not acted on.

---

## Going OUT to Flipkart

### Price & inventory push
`flipkart/listings_push.py` pushes `mrp/selling_price/mop/nlc/dealer_price`
via `POST /sellers/listings/v3/update/price` and per-location inventory via
`POST /sellers/listings/v3/update/inventory`, for every `Flipkart Listing`
that has a linked Item. Source of truth is whatever is currently stored on
the `Flipkart Listing` doc — there is no Item/Price-List → Flipkart mapping;
an operator (or future logic) edits the Flipkart Listing doc directly to
change what gets pushed. Gated behind `flipkart_enable_push_sync`.

### Shipment actions
`mark_ready_to_dispatch` (`POST /sellers/v3/shipments/dispatch`) and
`cancel_shipment` (`POST /sellers/v3/shipments/cancel`) exist as whitelisted
API methods but have no scheduled or UI trigger in this codebase — they run
only if something outside this repo calls them.
