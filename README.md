# Alaiy OS Connector — Flipkart

A [Frappe](https://frappeframework.com) app integrating Alaiy OS with the [Flipkart Marketplace Seller API](https://seller.flipkart.com/api-docs/). Plugs into the Alaiy OS workspace, sidebar, and `OS Connector Registry` the same way every other connector (Shopify, Unicommerce, Amazon SP-API) does — core never contains connector-specific code.

## Status

**Authentication only, so far.** Registry registration, the Settings form, the Sync Log, and both the outbound OAuth2 client and inbound webhook signature verification are real and working. Listing/order sync (`flipkart/sync.py`'s `run_pull_sync` / `run_push_sync`) is still a stub — that's the next piece of work.

## Prerequisites

- A Frappe v16 / ERPNext v16 bench with `alaiy_os` already installed (`required_apps = ["alaiy_os", "erpnext"]` — bench refuses to install without it).
- A Flipkart Seller account with a registered application (App ID + App Secret) — see [Flipkart's Client Credentials flow docs](https://sandbox-api.flipkart.net/oauth-service/oauth/token) for how to register one.

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app alaiy_os_connector_flipkart /path/to/this/repo
bench install-app alaiy_os_connector_flipkart
bench --site <site> migrate
bench build --app alaiy_os_connector_flipkart
```

## Authentication

Flipkart uses two entirely separate auth schemes for the two directions of traffic:

**Outbound (us → Flipkart) — OAuth2 Client Credentials.**
`FlipkartClient` (`flipkart/client.py`) exchanges the App ID/Secret for a bearer access token:

```
GET {base_url}/oauth-service/oauth/token?grant_type=client_credentials&scope=Seller_Api,Default
Authorization: Basic base64(app_id:app_secret)
-> {"access_token": "...", "token_type": "bearer", "expires_in": <seconds>, "scope": "..."}
```

The token is long-lived (Flipkart typically issues one valid for weeks) but not permanent, so it's cached on `Flipkart Connector Settings` (`flipkart_access_token` / `flipkart_token_expires_at`) and only refreshed once within 5 minutes of expiry — every other call reuses the cached token rather than minting a new one per request. Changing the App ID or App Secret on the settings form invalidates the cached token immediately (`flipkart_connector_settings.py:_invalidate_cached_token_if_credentials_changed`).

`base_url` switches between `https://sandbox-api.flipkart.net` and `https://api.flipkart.net` based on the `Use Sandbox` checkbox — sandbox by default.

**Inbound (Flipkart → us) — signature verification, not OAuth.**
Flipkart's order/return notification service (`flipkart/webhooks.py`) signs each request instead of presenting a bearer token:

```
X-Date: <HTTP-Date>
X-Authorization: FKLOGIN Base64(app_id:fk_signature)

fk_signature = SHA1(epoch_seconds(X-Date) + notification_url + HTTP_METHOD + app_secret)
```

`verify_signature()` recomputes that hash using the *exact* URL stored in `flipkart_notification_url` (must match byte-for-byte what's registered with Flipkart — that URL is part of the signed payload) and the connector's own App Secret. `receive_notification()` is the whitelisted, guest-allowed entry point Flipkart calls; it verifies the signature and records the raw event as a `Flipkart Sync Log` row (`trigger="webhook"`) — it does not yet act on the event (that's part of the still-unimplemented sync logic).

Note: registering a receiver URL with Flipkart in the first place (and toggling notifications on/off once registered) happens outside this codebase — a support ticket via the Seller/Partner Dashboard for initial registration, and `POST /v3/notification/subscription` only enables/disables an *existing* subscription.

## Settings fields (`Flipkart Connector Settings`)

| Field | Purpose |
|---|---|
| `is_enabled` | Master on/off switch. |
| `flipkart_use_sandbox` | Sandbox vs production host. Defaults on. |
| `flipkart_app_id` / `flipkart_app_secret` | OAuth2 client credentials. |
| `flipkart_access_token` / `flipkart_token_expires_at` | Cached token, read-only, managed by `FlipkartClient`. |
| `flipkart_notification_url` | The exact URL registered with Flipkart for webhooks — required for signature verification to succeed. |
| `flipkart_seller_id` | Seller identifier, needed for the notification subscription toggle API and some payloads. |
| `flipkart_company` / `flipkart_default_warehouse` / `flipkart_price_list` | Alaiy OS defaults for whatever gets synced in. |
| `flipkart_pull_sync_interval` / `flipkart_push_sync_interval` | Scheduled sync cadence, read by `sync_jobs.check_and_enqueue()`. |

## What's next (not built yet)

- `flipkart/sync.py` — real `run_pull_sync` (listings + orders from Flipkart) and `run_push_sync` (inventory/price push).
- A `Flipkart Product Listing` doctype (FSN, category attributes) — Flipkart's listing model doesn't map onto a plain Item the way Unicommerce's does.
- Acting on verified webhook payloads in `receive_notification()` (currently just logged).
- Custom fields beyond the placeholder `flipkart_fsn` / `sync_to_flipkart` on Item — real field set depends on what the listing/order sync ends up needing.

## File reference

| Path | Role |
|---|---|
| `hooks.py` | App manifest — name/dependencies, install/migrate hooks, sidebar log registration, scheduler cron. |
| `connector_meta.py` | Single source of truth for this connector's `OS Connector Registry` row. |
| `setup/install.py` | `after_install`, `sync_connector_registry`, `setup_custom_fields` (first-enable only). |
| `api/test_connection.py` | Whitelisted reachability check — performs the real OAuth2 exchange. |
| `api/sync.py` | Whitelisted trigger/status endpoints — delegate to `flipkart/sync.py`. |
| `flipkart/client.py` | OAuth2 client_credentials HTTP client, with token caching. |
| `flipkart/webhooks.py` | Inbound notification signature verification + receiver. |
| `flipkart/sync.py` | Sync Log lifecycle helpers; `run_pull_sync`/`run_push_sync` still stubs. |
| `flipkart/sync_jobs.py` | Scheduler entry point — decides what's due and enqueues it. |
| `alaiy_os_connector_flipkart/doctype/flipkart_connector_settings/` | Single DocType: credentials, webhook config, ERPNext defaults, sync intervals. |
| `alaiy_os_connector_flipkart/doctype/flipkart_sync_log/` | One row per sync run / webhook event. |

## License

AGPL-3.0 (`license.txt`) — matches `app_license` in `hooks.py`.
