# Alaiy OS Connector: Flipkart

Connects a Flipkart seller account to [Alaiy OS](https://alaiy.com),
syncing listings, orders, and inventory/price updates through Flipkart's
Marketplace Seller API.

## Features

- **Listing import** — pulls the seller's existing Flipkart listings into
  Alaiy OS.
- **Order import** — pulls dispatch-ready orders into Alaiy OS as Sales
  Orders.
- **Price/inventory push** — pushes price and stock updates back to
  Flipkart for linked listings.
- **Secure authentication** — OAuth2 client credentials for outbound calls,
  with token caching; signed webhook verification for inbound order/return
  notifications from Flipkart.
- **Sandbox and production modes**, with a live Test Connection check.

## Setup

1. Register an application with Flipkart Seller/Partner support to get an
   App ID and App Secret.
2. In Alaiy OS: open **Flipkart Connector Settings** and fill in the App
   ID, App Secret, Seller ID, Company, Default Warehouse, and Price List.
3. Click **Test Connection** to confirm the credentials work.
4. Enable the connector and save.

## License

AGPL-3.0
