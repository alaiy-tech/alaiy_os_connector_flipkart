# Orders

Flipkart shipments become Sales Orders in Alaiy OS. Pull + shipment actions:
`flipkart/orders.py`. Inbound push notifications: `flipkart/webhooks.py`.
This connector implements **Standard Fulfilment** only — Self-Ship's fuller
state machine (dispatch/delivery/service attempts, returns) is a materially
different flow per Flipkart's own docs and is not built here.

---

## Flipkart field → Alaiy OS field

Shipment search (`POST /sellers/v3/shipments/filter`, `filter.type=preDispatch`)
→ Sales Order:

| Flipkart field | Sales Order field | Notes |
|---|---|---|
| `shipmentId` | `flipkart_shipment_id` (custom field) | Dedup key — a Sales Order with this value and `docstatus != 2` already existing skips re-import. |
| `orderItems[].sku` | `items[].item_code` | Looked up against an existing Item by that exact code; unmapped SKUs are logged and dropped from the order rather than blocking the whole import. |
| `orderItems[].quantity` | `items[].qty` | Falls back to `1` if missing/zero. |
| `orderItems[].priceComponents.sellingPrice` | `items[].rate` | |
| `orderItems[0].orderDate` | `transaction_date` | Falls back to today if absent. |
| `dispatchByDate` | `delivery_date` | Falls back to `transaction_date` if absent. |
| (fixed) | `customer` | Always `"Flipkart Marketplace"` — Flipkart's Standard Fulfilment shipment payload has no buyer name/address/contact fields at all; the logistics partner handles delivery, not the seller. |
| (fixed) | `sales_channel` | Always `"Flipkart"`. |
| — | `warehouse` (per line) | From `flipkart_default_warehouse` setting, or the global default warehouse. |
| — | `selling_price_list` | From `flipkart_price_list` setting, or `"Standard Selling"`. |
| — | `company` | From `flipkart_company` setting, or the global default company. |

Webhook notification (`attributes.status`) → Sales Order:

| eventType | Sales Order effect |
|---|---|
| `shipment_created` | New Sales Order via the same upsert function the pull uses. |
| `shipment_packed`, `shipment_ready_to_dispatch`, `shipment_shipped`, `shipment_delivered`, `shipment_unhold` | `flipkart_shipment_status` set to `attributes.status`, truncated to 140 chars. |
| `shipment_cancelled` | `flipkart_shipment_status` set to `CANCELLED`. **Does not cancel the Sales Order document.** |
| `shipment_hold`, `shipment_dispatch_dates_changed`, `shipment_form_failed`, and all 6 `return_*` events | Logged to Flipkart Sync Log only (`status="skipped"`), no document changes. |
| anything else | Logged as `"skipped"` under its raw eventType name — treated as an event added since these docs were written, not an error. |

---

## Dedup and the pull/webhook overlap

Both the scheduled/manual pull (`pull_orders`) and the webhook's
`shipment_created` handler route through the exact same
`_upsert_order_from_shipment` function and the same existence check on
`flipkart_shipment_id`. Whichever one sees a given shipment first wins; the
other is a no-op. This is also why `flipkart_shipment_status` is described in
its own custom-field definition as having "two writers" — both the polling
pull and the webhook receiver can write it, since either may observe a given
state change first depending on timing.

## Shipment actions (manual only)

`mark_ready_to_dispatch` (`POST /sellers/v3/shipments/dispatch`) requires the
shipment to already be `PACKED` per Flipkart's documented state machine — the
label/invoice generation step (`POST /v3/shipments/labels`) that produces
that state is not wired up anywhere in this connector. `cancel_shipment`
(`POST /sellers/v3/shipments/cancel`) takes order-item IDs and an optional
reason. Both are exposed as whitelisted API methods
(`api/sync.py:mark_shipments_ready_to_dispatch` / `cancel_shipment`) but
nothing in this codebase calls them — no scheduled job, no page button.

## Known gaps

- **No status polling for already-imported orders.** Once a Sales Order
  exists, `flipkart_shipment_status` only updates via the webhook — if
  notifications aren't registered/working, status silently stays stale;
  there is no fallback poll of `postDispatch`/`cancelled` shipments.
- **Cancellation is status-only.** `shipment_cancelled` never cancels the
  Sales Order itself — by design, not a bug, since that's a financial
  document decision left to a human.
- **Returns are not implemented.** All 6 return event types are logged only.
