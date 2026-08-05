frappe.pages["flipkart"].on_page_load = function (wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Flipkart",
		single_column: true,
	});

	page.set_secondary_action("Settings", function() {
		frappe.set_route("Form", "Flipkart Connector Settings");
	}, "settings");

	$(page.body).html(`
		<div class="flipkart-page">
			<div class="container flipkart-container">
				<!-- Connection Status -->
				<div class="flipkart-card">
					<div class="flipkart-card-body">
						<div id="flipkart-connector-status" class="flipkart-connector-status"></div>
					</div>
				</div>

				<!-- Stats -->
				<div class="flipkart-card">
					<div class="flipkart-card-header">
						<span class="flipkart-icon-badge"><i class="fa fa-bar-chart"></i></span>
						<div class="flipkart-card-header-text">
							<h5>Overview</h5>
							<p>Current listing and order sync state.</p>
						</div>
					</div>
					<div class="flipkart-card-body">
						<div id="flipkart-stats-grid"></div>
					</div>
				</div>

				<!-- Orders -->
				<div class="flipkart-card">
					<div class="flipkart-card-header">
						<span class="flipkart-icon-badge"><i class="fa fa-cart-plus"></i></span>
						<div class="flipkart-card-header-text">
							<h5>Orders</h5>
							<p>Import Flipkart shipments as Sales Orders, and act on individual shipments.</p>
						</div>
					</div>
					<div class="flipkart-card-body">
						<p class="flipkart-text-muted">Pulls shipments awaiting dispatch. One Sales Order is created per shipment.</p>
						<div class="flipkart-info-strip">
							<span class="flipkart-info-pill"><i class="fa fa-check-circle"></i> Sales Orders</span>
							<span class="flipkart-info-pill"><i class="fa fa-truck"></i> Standard Fulfilment</span>
						</div>
						<button id="import-orders-btn" class="flipkart-btn flipkart-btn-primary">
							<i class="fa fa-cloud-download"></i> Import Orders from Flipkart
						</button>
						<div id="orders-log" class="flipkart-sync-log"></div>
					</div>
				</div>

				<!-- Products & Listings -->
				<div class="flipkart-card">
					<div class="flipkart-card-header">
						<span class="flipkart-icon-badge"><i class="fa fa-cubes"></i></span>
						<div class="flipkart-card-header-text">
							<h5>Products &amp; Listings</h5>
							<p>Pull Flipkart's listings in as Items, with each channel listing (price, tax, stock per location) linked to its Item.</p>
						</div>
					</div>
					<div class="flipkart-card-body">
						<button id="import-products-btn" class="flipkart-btn flipkart-btn-primary">
							<i class="fa fa-cloud-download"></i> Import Products from Flipkart
						</button>
						<button id="manage-listings-btn" class="flipkart-btn flipkart-btn-outline-primary">
							Manage Listings
						</button>
						<div id="listings-log" class="flipkart-sync-log"></div>
					</div>
				</div>

				<!-- Two-Way Sync -->
				<div class="flipkart-card">
					<div class="flipkart-card-header">
						<span class="flipkart-icon-badge"><i class="fa fa-exchange"></i></span>
						<div class="flipkart-card-header-text">
							<h5>Two-Way Sync</h5>
							<p>Push local changes back out to Flipkart. Off by default -- these are real writes to a live listing.</p>
						</div>
					</div>
					<div class="flipkart-card-body">
						<label style="display:flex; align-items:center; gap:10px; cursor:pointer; margin-bottom:14px;">
							<input type="checkbox" id="push-sync-toggle" style="width:16px; height:16px;">
							<span>Enable Two-Way Sync (Push)</span>
						</label>
						<p class="flipkart-text-muted">What this covers, and what it doesn't:</p>
						<div class="flipkart-info-strip">
							<span class="flipkart-info-pill"><i class="fa fa-check-circle"></i> Price updates</span>
							<span class="flipkart-info-pill"><i class="fa fa-check-circle"></i> Inventory updates</span>
							<span class="flipkart-info-pill"><i class="fa fa-times-circle"></i> Full listing update</span>
							<span class="flipkart-info-pill"><i class="fa fa-times-circle"></i> Create new listing</span>
						</div>
						<p class="flipkart-text-muted">Pushes price + inventory for every Flipkart Listing linked to an Item, using whatever's currently stored on that listing's own record. Only "Update Price" and "Update Inventory" are implemented -- "Update Listing" (title/tax/shipping/fulfilment) and "Create Listing" are not.</p>
						<button id="push-sync-btn" class="flipkart-btn flipkart-btn-primary" disabled>
							<i class="fa fa-cloud-upload"></i> Push Price &amp; Inventory to Flipkart
						</button>
						<div id="push-log" class="flipkart-sync-log"></div>
					</div>
				</div>

				<!-- Sync Logs -->
				<div class="flipkart-card">
					<div class="flipkart-card-header">
						<span class="flipkart-icon-badge"><i class="fa fa-history"></i></span>
						<div class="flipkart-card-header-text">
							<h5>Sync Logs</h5>
							<p>Recent synchronization activity across all types</p>
						</div>
					</div>
					<div class="flipkart-card-body">
						<div id="sync-logs-container" class="flipkart-logs-container">
							<p class="flipkart-text-muted">Loading logs...</p>
						</div>
					</div>
				</div>
			</div>
		</div>
	`);

	function render_connector_status() {
		frappe.call({
			method: "alaiy_os.api.connectors.get_all_connectors",
			callback: function(r) {
				var connector = (r.message || []).find(function(c) {
					return c.connector_id === "flipkart";
				});
				if (!connector) return;
				document.getElementById('flipkart-connector-status').innerHTML =
					alaiy_os.connector_card._html(connector);
			}
		});
	}

	function check_connection() {
		frappe.call({
			method: 'alaiy_os_connector_flipkart.api.test_connection.test_connection',
			callback: function() { render_connector_status(); },
			error: function() { render_connector_status(); }
		});
	}

	function run_job(method, args, log_container, btn, on_done) {
		btn.disabled = true;
		log_container.classList.add('flipkart-active');
		log_container.innerHTML = '<div class="flipkart-log-status-running">Starting...<span class="flipkart-spinner"></span></div>';

		frappe.call({
			method: method,
			args: args || {},
			callback: function(r) {
				if (r.message && r.message.log_name) {
					poll_job_progress(r.message.log_name, log_container, btn);
					setTimeout(refresh_logs, 1000);
				} else {
					btn.disabled = false;
					log_container.innerHTML = '<div class="flipkart-log-entry">Nothing to run</div>';
				}
				if (on_done) on_done(r);
			},
			error: function() {
				btn.disabled = false;
				log_container.innerHTML = '<div class="flipkart-log-entry flipkart-alert-warning">Failed to start</div>';
			}
		});
	}

	function poll_job_progress(log_name, log_container, btn) {
		frappe.call({
			method: 'frappe.client.get',
			args: {doctype: 'Flipkart Sync Log', name: log_name},
			callback: function(r) {
				if (!r.message) return;
				var log = r.message;
				var is_active = (log.status === 'running' || log.status === 'queued');
				var html = '<div class="flipkart-log-status flipkart-log-status-' + log.status + '">' + log.status.toUpperCase() + '</div>';
				if (log.items_processed) html += '<div class="flipkart-log-entry">Processed: ' + log.items_processed + '</div>';
				if (log.items_created) html += '<div class="flipkart-log-entry">Created: ' + log.items_created + '</div>';
				if (log.items_failed) html += '<div class="flipkart-log-entry">Failed: ' + log.items_failed + '</div>';
				if (log.error_message) html += '<div class="flipkart-log-entry flipkart-alert-warning"><strong>Error:</strong> ' + log.error_message + '</div>';
				log_container.innerHTML = html;

				if (is_active) {
					setTimeout(function() { poll_job_progress(log_name, log_container, btn); }, 2000);
				} else {
					btn.disabled = false;
					refresh_logs();
					load_stats();
				}
			}
		});
	}

	function import_orders() {
		run_job(
			'alaiy_os_connector_flipkart.api.sync.trigger_order_pull',
			{},
			document.getElementById('orders-log'),
			document.getElementById('import-orders-btn')
		);
	}

	function import_products() {
		run_job(
			'alaiy_os_connector_flipkart.api.sync.trigger_pull_sync',
			{},
			document.getElementById('listings-log'),
			document.getElementById('import-products-btn')
		);
	}

	function push_sync() {
		run_job(
			'alaiy_os_connector_flipkart.api.sync.trigger_push_sync',
			{},
			document.getElementById('push-log'),
			document.getElementById('push-sync-btn'),
			function(r) {
				if (r.message && r.message.queued === false) {
					document.getElementById('push-log').innerHTML =
						'<div class="flipkart-log-entry flipkart-alert-warning">' + (r.message.message || 'Push sync is disabled.') + '</div>';
					document.getElementById('push-log').classList.add('flipkart-active');
				}
			}
		);
	}

	function load_push_sync_toggle() {
		frappe.call({
			method: 'alaiy_os_connector_flipkart.api.sync.get_push_sync_status',
			callback: function(r) {
				var enabled = !!(r.message && r.message.enabled);
				document.getElementById('push-sync-toggle').checked = enabled;
				document.getElementById('push-sync-btn').disabled = !enabled;
			}
		});
	}

	function on_push_sync_toggle_change() {
		var checkbox = document.getElementById('push-sync-toggle');
		var enabled = checkbox.checked;
		var confirm_and_set = function() {
			frappe.call({
				method: 'alaiy_os_connector_flipkart.api.sync.set_push_sync_enabled',
				args: { enabled: enabled ? 1 : 0 },
				callback: function(r) {
					var actually_enabled = !!(r.message && r.message.enabled);
					checkbox.checked = actually_enabled;
					document.getElementById('push-sync-btn').disabled = !actually_enabled;
				},
				error: function() {
					checkbox.checked = !enabled;
				}
			});
		};

		if (enabled) {
			frappe.confirm(
				'This allows the connector to push price and inventory changes to your live Flipkart listings. Continue?',
				confirm_and_set,
				function() { checkbox.checked = false; }
			);
		} else {
			confirm_and_set();
		}
	}

	function escape_html(value) {
		return String(value || '')
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;')
			.replace(/"/g, '&quot;');
	}

	function badge_html(value, color) {
		return '<span class="indicator-pill ' + color + '" title="' + escape_html(value || '') + '"><span>' + escape_html(value || '') + '</span></span>';
	}

	function refresh_logs() {
		frappe.call({
			method: 'alaiy_os_connector_flipkart.api.sync.get_sync_status',
			callback: function(r) {
				if (r.message) render_logs_table(r.message);
			}
		});
	}

	function render_logs_table(logs) {
		var container = document.getElementById('sync-logs-container');
		if (!logs || logs.length === 0) {
			container.innerHTML = '<p class="flipkart-text-muted">No sync logs yet.</p>';
			return;
		}

		var html = '<table class="flipkart-logs-table"><thead><tr><th>Name</th><th>Type</th><th>Trigger</th><th>Status</th><th>Started</th><th>Progress</th></tr></thead><tbody>';
		logs.forEach(function(log) {
			var sync_type = log.sync_type || '-';
			var trigger = log.trigger || '-';
			var status = log.status || '-';
			var started = log.started_at ? new Date(log.started_at).toLocaleString() : '-';
			var progress = (log.items_created || 0) + ' created / ' + (log.items_failed || 0) + ' failed';
			var sync_color = sync_type === 'order_pull' ? 'pink' : sync_type === 'pull' ? 'green' : sync_type === 'push' ? 'blue' : 'darkgrey';
			var trigger_color = trigger === 'manual' ? 'orange' : trigger === 'scheduled' ? 'purple' : trigger === 'webhook' ? 'cyan' : 'darkgrey';
			var status_color = status === 'success' ? 'green' : status === 'failed' ? 'red' : status === 'running' ? 'blue' : status === 'queued' ? 'grey' : status === 'skipped' ? 'yellow' : 'darkgrey';
			var name_html = '<a href="#" class="flipkart-log-link" data-name="' + escape_html(log.name || '') + '">' + escape_html(log.name || '') + '</a>';
			html += '<tr><td>' + name_html + '</td><td>' + badge_html(sync_type, sync_color) + '</td><td>' + badge_html(trigger, trigger_color) + '</td><td>' + badge_html(status, status_color) + '</td><td>' + escape_html(started) + '</td><td>' + escape_html(progress) + '</td></tr>';
		});
		html += '</tbody></table>';
		container.innerHTML = html;

		$(container).find('.flipkart-log-link').on('click', function(e) {
			e.preventDefault();
			frappe.set_route('Form', 'Flipkart Sync Log', $(this).data('name'));
		});

		var running = logs.some(function(l) { return l.status === 'running' || l.status === 'queued'; });
		if (running) setTimeout(refresh_logs, 3000);
	}

	function render_stat_group(title, cards, accent) {
		var html = '<div class="flipkart-stat-group-title">' + title + '</div><div class="flipkart-stats-grid">';
		cards.forEach(function(c) {
			html += '<div class="flipkart-stat-tile flipkart-stat-accent-' + accent + '">' +
				'<div class="flipkart-stat-value">' + c.value + '</div>' +
				'<div class="flipkart-stat-label">' + c.label + '</div>' +
				'</div>';
		});
		html += '</div>';
		return html;
	}

	function load_stats() {
		var grid = document.getElementById('flipkart-stats-grid');
		frappe.call({
			method: 'alaiy_os_connector_flipkart.api.sync.get_dashboard_stats',
			callback: function(r) {
				var s = r.message;
				if (!s) return;
				grid.innerHTML = render_stat_group('Alaiy OS (local)', [
					{label: 'Listings (total)', value: s.listings_total},
					{label: 'Listings (active)', value: s.listings_active},
					{label: 'Listings linked to Item', value: s.listings_linked},
					{label: 'Orders synced', value: s.orders_synced},
				], 'local');
			}
		});
	}

	check_connection();
	load_stats();
	refresh_logs();
	load_push_sync_toggle();

	document.getElementById('import-orders-btn').addEventListener('click', import_orders);
	document.getElementById('import-products-btn').addEventListener('click', import_products);
	document.getElementById('push-sync-btn').addEventListener('click', push_sync);
	document.getElementById('push-sync-toggle').addEventListener('change', on_push_sync_toggle_change);
	document.getElementById('manage-listings-btn').addEventListener('click', function() {
		frappe.set_route('List', 'Flipkart Listing');
	});
};
