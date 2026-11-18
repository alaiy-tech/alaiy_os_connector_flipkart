"""
Single source of truth for this connector's registration metadata.
Consumed by setup/install.py → upserted into alaiy_os's OS Connector Registry.
"""

_LOG_FIELDS = {
    "processed": "items_processed",
    "changed": ["items_created", "items_updated"],
    "failed": "items_failed",
    "error": "error_message",
}


def _health(key, label, sync_type, scheduled, interval_setting=None, expects_rows=True):
    entry = {
        "key": key,
        "label": label,
        "direction": "push" if sync_type == "push" else "pull",
        "log_doctype": "Flipkart Sync Log",
        "log_filter": {"sync_type": sync_type},
        "fields": _LOG_FIELDS,
        "scheduled": scheduled,
        "expects_rows": expects_rows,
    }
    if interval_setting:
        entry["interval_setting"] = interval_setting
    return entry


connector_meta = {
    "connector_id": "flipkart",
    "connector_name": "Flipkart",
    "connector_app": "alaiy_os_connector_flipkart",
    # "channel" (sell TO — e.g. Shopify) or "supplier" (buy FROM — e.g. Cloudstore)
    "connector_type": "channel",
    "description": "Flipkart Marketplace connector — listings and order sync via the Flipkart Seller API.",
    "icon": "box",
    "icon_url": "",
    "settings_doctype": "Flipkart Connector Settings",
    "test_method": "alaiy_os_connector_flipkart.api.test_connection.test_connection",
    # The registry exposes two sync "slots". Map them to whatever your
    # connector actually does; the labels are what the UI shows.
    "sync_categories_method": "alaiy_os_connector_flipkart.api.sync.trigger_pull_sync",
    "sync_items_method": "alaiy_os_connector_flipkart.api.sync.trigger_push_sync",
    "sync_status_method": "alaiy_os_connector_flipkart.api.sync.get_sync_status",
    "sync_categories_label": "Pull",
    "sync_items_label": "Push",
    "is_enabled": 0,
    "connection_status": "untested",

    "health": [
        _health("pull", "Listings pull", "pull", True, "flipkart_pull_sync_interval"),
        # Only runs when the push master switch is on.
        _health("push", "Listings push", "push", True, "flipkart_push_sync_interval", expects_rows=False),
        # Started manually; the schedule does not run it.
        _health("order_pull", "Order pull", "order_pull", False, expects_rows=False),
    ],
}
