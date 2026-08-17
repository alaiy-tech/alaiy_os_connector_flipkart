# Architecture & Sync Engine

The plumbing shared across every domain: auth, the API client, how syncs are
scheduled and logged, and how failures are surfaced.

---

## Connector pattern

Standalone Frappe app that registers into `alaiy_os`'s OS Connector Registry
on `after_migrate` (`setup/install.py:sync_connector_registry`, idempotent).
Settings live on a Single DocType (`Flipkart Connector Settings`); every sync
run is recorded on a dedicated log DocType (`Flipkart Sync Log`). Heavy setup
(custom fields) does not run on migrate — it runs once, lazily, the first
time an admin flips `is_enabled` on from the settings form, so installing the
app itself is cheap and non-destructive.

## Auth & client

`flipkart/client.py`'s `FlipkartClient` implements Flipkart's OAuth2 Client
Credentials flow: `GET {base_url}/oauth-service/oauth/token` with
`grant_type=client_credentials&scope=Seller_Api` and a Basic Auth header of
`app_id:app_secret`. The scope string is exactly `"Seller_Api"` — the module
docstring notes that `"Seller_Api,Default"` was confirmed live to be rejected
with `invalid_scope`.

The resulting token is cached on `Flipkart Connector Settings`
(`flipkart_access_token` / `flipkart_token_expires_at`) and reused across
every request; `get_access_token()` only calls `_fetch_new_token()` when the
cached token is missing or within `_TOKEN_REFRESH_MARGIN_SECONDS` (300s) of
its recorded expiry, rather than on every call. `base_url` is
`sandbox-api.flipkart.net` or `api.flipkart.net`, chosen by
`flipkart_use_sandbox`.

All requests go through `get`/`post`/`get_absolute`, each a thin `requests`
wrapper with a fixed `timeout=30` and `resp.raise_for_status()` — there is no
retry/backoff logic in the client; any non-2xx response raises
`requests.exceptions.HTTPError` straight up to the caller. `get_absolute` is a
separate method because Flipkart returns some pagination cursors
(`nextPageUrl` on shipment search) as a full absolute URL rather than a page
token, so the caller can't reuse `get()`'s path-joining logic for those.

Inbound webhook auth is a **separate scheme** from the outbound client:
`webhooks.py:verify_signature` checks Flipkart's own request signature
(`X-Date` / `X-Authorization: FKLOGIN base64(app_id:sig)`, where
`sig = SHA1(epoch_seconds(X-Date) + registered_notification_url + method + app_secret)`)
against the App Secret and `flipkart_notification_url` stored in settings. It
never raises — an unparseable header just evaluates to "not verified" and the
endpoint returns 401.

## Change detection & identity

- **Listings**: no diffing before push or pull — `listings.py`'s pull always
  upserts every SKU it fetches (get-or-create on `item_code = sku_id`,
  update-or-insert on `Flipkart Listing` name = `sku`), and
  `listings_push.py`'s push always sends price+inventory for every linked
  listing on every run. There is no "only push if changed" logic anywhere in
  this connector.
- **Orders**: identity is `flipkart_shipment_id` on Sales Order.
  `_upsert_order_from_shipment` checks
  `frappe.db.exists("Sales Order", {"flipkart_shipment_id": shipment_id, "docstatus": ["!=", 2]})`
  before creating, so both the scheduled/manual pull and the
  `shipment_created` webhook route through the same dedup check — a
  redelivered webhook notification (Flipkart's delivery is documented as
  at-least-once, not exactly-once) is naturally a no-op.

## Don't mark a sync successful if some rows failed

This is the connector's load-bearing pattern, and other connectors copy it.
Every top-level sync function tracks per-row counters and, at the end,
chooses `"success"` vs `"failed"` based on whether **any** row failed —
never a blanket "the loop finished, so it succeeded":

- `flipkart/listings.py`, `pull_all_listings` (lines ~258-259):
  ```python
  _mark_finished(log, "success" if failed == 0 else "failed",
                  error_message=(f"{failed} listing(s) failed -- see Error Log." if failed else None))
  ```
- `flipkart/orders.py`, `pull_orders` (lines ~201-202): same
  `"success" if failed == 0 else "failed"` shape.
- `flipkart/listings_push.py`, `run_push_sync` (lines ~200-201): same shape
  again, on the push side.

Each of these three functions also isolates failure **per row** (per-SKU
`try/except` in listings, per-shipment `try/except` in orders, per-SKU
`try/except` in push) so one bad record doesn't abort the whole batch or roll
back everything already committed — but the run as a whole is still reported
as `failed` if even one row didn't make it, with the failure count folded
into `error_message` and every individual failure recorded via
`frappe.log_error`. A partially-successful run is visible as "failed" in
Flipkart Sync Log, not silently reported as a clean success with a smaller
number buried in a counter column.

The one exception, by design rather than oversight: `webhooks.py`'s
`receive_notification` always returns HTTP 200 regardless of whether a given
`eventType` was acted on — that's a deliberate reading of Flipkart's own
webhook contract (non-200 should mean "system is down or payload malformed",
not "we don't yet handle this event"), and is orthogonal to the sync-log
success/failure reporting described above, which still applies to the
Sales Order upsert that webhook triggers.

## Sync log / error visibility

`Flipkart Sync Log` (autoname `FLK-SYNC-.YYYY.-.MM.-.DD.-.######`) has
`sync_type` (pull / push / order_pull), `trigger` (scheduled / manual /
webhook), `status` (queued / running / success / failed / skipped),
`started_at` / `finished_at`, `items_processed` / `items_created` /
`items_updated` / `items_failed`, `pages_total` / `pages_done`,
`error_message` (truncated to 2000 chars), and `log_messages` (used by the
webhook handler to record raw event payloads, truncated to 9000 chars).
Registered under the Alaiy OS sidebar as "Flipkart Logs"
(`hooks.py:alaiy_os_sidebar_log_items`). Every failure is also written to
Frappe's standard Error Log via `frappe.log_error`, with a title identifying
which sync/row failed, so the full traceback is available beyond the
2000-char `error_message` field.

`sync_jobs.py`'s scheduler (`check_and_enqueue`, cron `* * * * *`) treats a
sync stuck in `"running"` for more than 30 minutes (`_STALE_RUNNING_SECONDS`)
as dead, so a crashed worker never blocks the schedule forever — it will
enqueue a fresh run instead of waiting indefinitely for the stale one.
