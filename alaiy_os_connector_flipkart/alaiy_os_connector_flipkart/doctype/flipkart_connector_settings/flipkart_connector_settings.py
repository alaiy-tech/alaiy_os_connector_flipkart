# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class FlipkartConnectorSettings(Document):
    def validate(self):
        # old_enabled is the last-committed DB value, so this comparison has
        # to run before the save overwrites it. Heavy setup runs only on the
        # 0 -> 1 transition, not on every save.
        old_enabled = frappe.db.get_single_value(
            "Flipkart Connector Settings", "is_enabled"
        ) or 0
        self.flags.flipkart_just_enabled = bool(self.is_enabled and not old_enabled)
        self.flags.flipkart_just_disabled = bool(not self.is_enabled and old_enabled)
        self._invalidate_cached_token_if_credentials_changed()
        self._sync_registry_is_enabled()

    def on_update(self):
        # Deferred to on_update (after this row is written) so any code that
        # reads back the freshly saved credentials sees the new values.
        if self.flags.flipkart_just_enabled:
            self._on_first_enable()
        elif self.flags.flipkart_just_disabled:
            self._on_disable()

    def _on_first_enable(self):
        from alaiy_os_connector_flipkart.setup.install import setup_custom_fields
        setup_custom_fields()
        # e.g. register webhooks, create default supplier / price lists here.

    def _on_disable(self):
        # e.g. unregister webhooks here.
        pass

    def _invalidate_cached_token_if_credentials_changed(self):
        """
        A cached access token was minted for the OLD App ID/Secret pair — if
        either changes, the cached token belongs to a different (or now
        wrong) identity and must not be reused. FlipkartClient re-fetches a
        token whenever these fields are blank.
        """
        if self.is_new():
            return
        old = frappe.db.get_value(
            "Flipkart Connector Settings", None,
            ["flipkart_app_id", "flipkart_app_secret"], as_dict=True,
        ) or {}
        app_id_changed = self.flipkart_app_id != old.get("flipkart_app_id")
        secret_changed = (
            self.get_password("flipkart_app_secret", raise_exception=False)
            != old.get("flipkart_app_secret")
        )
        if app_id_changed or secret_changed:
            self.flipkart_access_token = ""
            self.flipkart_token_expires_at = None

    def _sync_registry_is_enabled(self):
        if frappe.db.exists("OS Connector Registry", "flipkart"):
            frappe.db.set_value(
                "OS Connector Registry", "flipkart", "is_enabled", self.is_enabled
            )
