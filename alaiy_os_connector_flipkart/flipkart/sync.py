# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
The actual sync work + the Flipkart Sync Log lifecycle helpers every sync
shares. Listing pull is real (delegates to flipkart/listings.py, which
manages its own log lifecycle since it needs to save progress incrementally
across paginated batches); run_push_sync and order pull are still stubs.
"""

import frappe
from frappe.utils import now_datetime


def get_or_create_log(sync_type, trigger, log_name=None):
    """
    Return the Sync Log to use for this run. If log_name is given (the API
    layer pre-created it so it shows as 'queued' immediately) reuse it;
    otherwise create a fresh one. Newly created logs start as 'queued'.
    """
    if log_name and frappe.db.exists("Flipkart Sync Log", log_name):
        return frappe.get_doc("Flipkart Sync Log", log_name)

    log = frappe.new_doc("Flipkart Sync Log")
    log.sync_type = sync_type
    log.trigger = trigger
    log.status = "queued"
    log.insert(ignore_permissions=True)
    frappe.db.commit()
    return log


def _mark_running(log):
    log.status = "running"
    log.started_at = now_datetime()
    log.save(ignore_permissions=True)
    frappe.db.commit()


def _mark_finished(log, status, error_message=None):
    log.status = status
    log.finished_at = now_datetime()
    if error_message:
        log.error_message = error_message[:2000]
    log.save(ignore_permissions=True)
    frappe.db.commit()


def _run(sync_type, trigger, log_name, worker):
    log = get_or_create_log(sync_type, trigger, log_name)
    _mark_running(log)
    try:
        worker(log)
        _mark_finished(log, "success")
    except Exception:
        _mark_finished(log, "failed", frappe.get_traceback())
        frappe.log_error(
            title=f"Flipkart connector: {sync_type} sync failed",
            message=frappe.get_traceback(),
        )
        raise


def run_pull_sync(trigger="scheduled", log_name=None):
    """
    Pull listings from Flipkart into Alaiy OS (Flipkart Listing records).
    Order pull is separate, not implemented yet.
    """
    from alaiy_os_connector_flipkart.flipkart.listings import pull_all_listings
    pull_all_listings(trigger=trigger, log_name=log_name)


def run_push_sync(trigger="scheduled", log_name=None):
    """Push Alaiy OS listings/inventory out to Flipkart. TODO: implement."""
    def worker(log):
        pass

    _run("push", trigger, log_name, worker)
