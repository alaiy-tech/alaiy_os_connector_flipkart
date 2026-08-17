# Listings

Products/listings sync bidirectionally between Flipkart and Alaiy OS.
Pull code: `flipkart/listings.py`. Push code: `flipkart/listings_push.py`.
Storage: `Flipkart Listing` (per-SKU, linked to an Item) and its child table
`Flipkart Listing Location`.

---

## Flipkart field → Alaiy OS field

Pull direction (`/sellers/listings/v3/search` + `/sellers/listings/v3/details`
→ `Flipkart Listing`):

| Flipkart field | Flipkart Listing field | Notes |
|---|---|---|
| `sku_id` (search) | `sku` (doc name, autoname `field:sku`) | Also used as the linked Item's `item_code`. |
| `listing_id` | `listing_id` | Falls back to the search step's value if `/details` omits it. |
| `product_id` | `fsn` | No endpoint literally names a field `fsn` — `product_id` is confirmed (via Flipkart's glossary + a live seller-dashboard export) to be the same catalog-level identifier concept. |
| `product_title` | `title`, and seeds `item_name` on first Item creation | |
| `listing_status` | `listing_status` (ACTIVE/INACTIVE) | |
| `archived_status` | `archived_status` (NONE/ARCHIVED) | Defaults `"NONE"` if absent. |
| `fulfillment_profile` | `fulfillment_profile` (NON_FBF/FBF_LITE/FBF) | |
| `price.mrp` / `price.selling_price` / `price.mop` / `price.nlc` / `price.dealer_price` | `mrp` / `selling_price` / `mop` / `nlc` / `dealer_price` | |
| `price.currency` | `currency` | |
| `tax.hsn` / `tax.tax_code` / `tax.goods_services_rate` / `tax.is_gst_sellable` / `tax.luxury_cess_percentage` | `hsn` / `tax_code` / `goods_services_rate` / `is_gst_sellable` / `luxury_cess_percentage` | |
| `locations[].id` / `.status` / `.inventory` / `.pending_inventory` | `Flipkart Listing Location` rows: `location_id` / `status` / `inventory` / `pending_inventory` | Child table, fully replaced (`doc.set("locations", ...)`) on every pull. |
| (whole `/details` response for that SKU) | `raw_summary` | Verbatim JSON, truncated to 100,000 chars, for fields not yet modeled. |
| (pull timestamp) | `last_synced_at` | |

Push direction (`Flipkart Listing` → `/sellers/listings/v3/update/price` and
`/update/inventory`):

| Flipkart Listing field | Request field | Notes |
|---|---|---|
| `mrp` / `selling_price` / `mop` / `nlc` / `dealer_price` | `price.mrp` / `.selling_price` / `.mop` / `.nlc` / `.dealer_price` | Cast to `int` via `cint()` — Flipkart's price API is documented as integer paise/rupee values, not decimal. |
| `currency` | `price.currency` | Falls back to `"INR"` if blank. |
| `locations[].location_id` / `.status` / `.inventory` / `.pending_inventory` | `locations[].id` / `.status` / `.inventory` / `.pending_inventory` | Rows without a `location_id` are dropped; `status` falls back to `"ENABLED"`. |
| `fsn` | `product_id` in the request body | |

---

## Items and the product link

`_get_or_create_item` creates an Item with `item_code = sku_id` only if one
doesn't already exist (`frappe.db.exists`) — it never updates an existing
Item's name/group/UOM from Flipkart data on subsequent pulls. New Items get
`sync_to_flipkart = 1` and fall back to Stock Settings' default item
group/UOM if none is configured. `Flipkart Listing.product` is a plain `Item`
Link, set once at creation time.

## Push is gated, and checked in more than one place

Every function in `listings_push.py` — `update_price`, `update_inventory`,
`push_price_and_inventory`, and `run_push_sync` — calls
`_require_push_enabled()` itself rather than trusting the caller to have
checked. `run_push_sync` catches `PushSyncDisabled` and marks the log
`"skipped"` (not `"failed"`) with the reason recorded, rather than raising.

## Unverified request/response shape (documented gap, not silently assumed)

`listings_push.py`'s own docstring flags that Flipkart's docs render the
request/response body for all four update/create endpoints as a
Redoc/OpenAPI `additionalProperties` map (keyed by an arbitrary string) with
no concrete JSON example shown anywhere in the vendored docs — unlike the
pull side's `/details` endpoint, which does show a real "available" map
example. The code assumes the push request/response is **also** keyed by
`sku_id`, by analogy with that confirmed pull-side convention, but this has
not been confirmed against a live sandbox call. `_check_response` falls back
to treating the whole response as the single result if the `sku_id` key
isn't present, specifically so a sandbox test immediately reveals which
shape Flipkart actually returns.

## Known gaps

- **No new-listing creation.** `CREATE_LISTING_PATH` (`POST
  /sellers/listings/v3`) is defined as a constant but no function calls it —
  push only updates price/inventory on listings that already exist on
  Flipkart.
- **No full listing update either.** `UPDATE_LISTING_PATH` is likewise
  defined but unused.
- **No category/brand/attribute data.** Confirmed by the pull module's own
  docstring via full-text search across the vendored API docs — no endpoint
  exposes or sets these, even though Flipkart's glossary describes them as
  belonging to the "Product" entity.
- **Path prefix unverified against a live sandbox call.** The vendored docs
  mirror consistently uses `/sellers/listings/v3/*`; Flipkart's separate live
  seller-dashboard reference appears to use `/listings/v3/*` without that
  prefix. The two sources disagree and this has not been confirmed against a
  real API call.
