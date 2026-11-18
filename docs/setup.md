# Setup & Configuration

Standalone Frappe app (`alaiy_os_connector_flipkart`). It installs disabled:
`connector_meta.py` sets `is_enabled: 0` and the settings DocType's `is_enabled`
field defaults to `0`. Turning it on runs `setup_custom_fields()` once — it
adds two custom fields to Item and two to Sales Order (see §4). No webhook
registration happens automatically anywhere in this codebase; that is a
manual step with Flipkart (see §1).

---

## 1. Prerequisites

- A Frappe bench with `alaiy_os` and `erpnext` installed (`required_apps` in
  `hooks.py`).
- A Flipkart Seller account with a **self-access application** registered for
  the OAuth2 Client Credentials grant (App ID + App Secret) — this connector
  does not implement the Authorization Code flow used by third-party
  aggregators.
- For order/return notifications: registering the notification receiver URL
  with Flipkart is a **manual support-ticket process** through the
  Seller/Partner Dashboard, per Flipkart's own docs
  (`order-management-notifications.html`, "Subscribing to Notifications").
  `POST /v3/notification/subscription` only toggles an *existing*
  subscription on/off — it has no field to set the callback URL, so nothing
  in this connector can provision that URL for you.

## 2. Flipkart credentials

| Flipkart-side value | Settings field | Notes |
|---|---|---|
| Application ID (client ID) | `flipkart_app_id` | Pasted directly. |
| Application Secret (client secret) | `flipkart_app_secret` | Pasted directly (Password field). Used only for Basic Auth on the token endpoint — never sent to any other endpoint. |
| — | `flipkart_access_token` | **Not pasted.** The connector mints this itself via `client.py`'s OAuth2 client_credentials exchange and caches it here (read-only field). |
| — | `flipkart_token_expires_at` | Set automatically alongside the token; refreshed 5 minutes before real expiry. |
| Seller ID (from Flipkart dashboard) | `flipkart_seller_id` | Pasted directly. Required for the notification enable/disable API and included in some payloads. |
| The exact HTTPS receiver URL registered with Flipkart | `flipkart_notification_url` | Pasted directly, and must match byte-for-byte what's registered — Flipkart signs each webhook with `SHA1(timestamp + this URL + method + App Secret)`, and `webhooks.py` recomputes that same hash for verification. |

Changing App ID or App Secret on an already-configured connector clears the
cached access token automatically (`_invalidate_cached_token_if_credentials_changed`
in `flipkart_connector_settings.py`), since a token minted under the old pair
is not valid under the new one.

## 3. Flipkart Connector Settings — every field

Single DocType `Flipkart Connector Settings`. Fields grouped by section
exactly as in the DocType JSON:

**(top-level)**

| Field | Type | Purpose |
|---|---|---|
| `is_enabled` | Check | Master on/off. Gates the scheduler and provisions custom fields on first `0→1` transition. |

**API Connection**

| Field | Type | Purpose |
|---|---|---|
| `flipkart_use_sandbox` | Check (default 1) | Points the client at `sandbox-api.flipkart.net` instead of `api.flipkart.net`. |
| `flipkart_app_id` | Data, required | OAuth client ID. |
| `flipkart_app_secret` | Password, required | OAuth client secret. |
| `flipkart_access_token` | Password, read-only | Cached bearer token, minted automatically. |
| `flipkart_token_expires_at` | Datetime, read-only | Cache expiry, minted automatically. |

**Webhooks (Order/Return Notifications)**

| Field | Type | Purpose |
|---|---|---|
| `flipkart_notification_url` | Data | Must match the URL registered with Flipkart byte-for-byte (used in signature verification). |
| `flipkart_seller_id` | Data | Seller identifier for the notification enable/disable API and some payloads. |

**Alaiy OS Defaults**

| Field | Type | Purpose |
|---|---|---|
| `flipkart_company` | Link (Company) | **Not read by any sync logic yet** — placeholder. `orders.py` falls back to `frappe.defaults.get_global_default("company")` regardless of this field's value. |
| `flipkart_default_warehouse` | Link (Warehouse) | Used by order pull (`orders.py`) as the warehouse on imported Sales Order line items, falling back to the global default warehouse if blank. Not used by listings pull/push. |
| `flipkart_price_list` | Link (Price List) | Used by order pull as `selling_price_list` on imported Sales Orders (falls back to `"Standard Selling"` if blank). Not read by listings logic. |

**Sync Schedule**

| Field | Type | Purpose |
|---|---|---|
| `flipkart_pull_sync_interval` | Select: Disabled/5/15/30/60 min | Drives both listing pull and order pull — there is only one pull interval, not separate ones. |
| `flipkart_push_sync_interval` | Select: Disabled/5/15/30/60 min | Drives the scheduled price/inventory push, but only takes effect if `flipkart_enable_push_sync` is also on. |

**Two-Way Sync (Push to Flipkart)**

| Field | Type | Purpose |
|---|---|---|
| `flipkart_enable_push_sync` | Check (default 0) | Master switch for every outbound write (price, inventory, listing update/create). Checked independently by the scheduler and by `listings_push.py`'s own functions — `is_enabled` alone never allows a push. |

## 4. First enable

The moment `is_enabled` flips `0 → 1` (`flipkart_connector_settings.py`,
`_on_first_enable`), `setup/install.py`'s `setup_custom_fields()` runs and
adds:

- **Item**: `flipkart_fsn` (read-only Data, Flipkart's product-level
  identifier) and `sync_to_flipkart` (Check, include this Item in Flipkart
  syncs — shown in list view).
- **Sales Order**: `flipkart_shipment_id` (read-only Data, the dedup key used
  by both the pull and the webhook) and `flipkart_shipment_status` (read-only
  Data, in list view, written by both the order pull and the webhook
  receiver).

Both are idempotent — safe to run again on every enable/migrate. Nothing else
happens on first enable: no webhooks are registered (that's a manual ticket
with Flipkart, see §1), no default supplier/price list is created. Disabling
(`_on_disable`) currently does nothing — the method exists as a stub with no
body beyond `pass`.

Separately, on every `bench migrate` (not gated on enable), `after_migrate`
runs `sync_connector_registry()`, which upserts this connector's row in
`alaiy_os`'s OS Connector Registry and force-patches the settings DocType to
`issingle=1` if it drifted — unrelated to whether Flipkart itself is enabled.
