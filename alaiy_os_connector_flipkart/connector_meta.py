"""
Single source of truth for this connector's registration metadata.
Consumed by setup/install.py → upserted into alaiy_os's OS Connector Registry.
"""

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
}
