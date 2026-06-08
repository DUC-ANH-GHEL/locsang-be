# LocSang API

This is a well-structured FastAPI backend project for Lộc Sang.

## Contact email notifications

When a customer submits `POST /api/contacts`, backend will:

- Save contact into database (always).
- Send notification email to admin in background.
- Optionally send auto-reply email back to customer (if customer email is provided).

Set these environment variables to enable SMTP sending:

- `SMTP_HOST=<smtp_host>`
- `SMTP_PORT=587` (or your provider port)
- `SMTP_USERNAME=<smtp_username>`
- `SMTP_PASSWORD=<smtp_password>`
- `SMTP_USE_TLS=true` (common for port 587)
- `SMTP_USE_SSL=false` (set `true` for providers using SSL, often port 465)
- `SMTP_FROM_EMAIL=<from_email>` (optional, fallback to `SMTP_USERNAME`)
- `SMTP_FROM_NAME=Lộc Sang` (optional)
- `CONTACT_NOTIFICATION_TO_EMAIL=<admin1@example.com,admin2@example.com>` (optional, comma-separated)
- `CONTACT_SEND_AUTO_REPLY=true` (optional)

Notes:

- If `CONTACT_NOTIFICATION_TO_EMAIL` is empty, backend falls back to `SMTP_FROM_EMAIL` or `SMTP_USERNAME`.
- SMTP errors do not fail contact API response.

## Account password emails

Backend now also sends emails for account password flows:

- `POST /api/account/forgot-password`: sends reset link email to user.
- `POST /api/account/reset-password`: sends security notice email after password was changed.

Notes:

- These emails use the same SMTP variables listed above.
- API responses remain generic/safe even if email send fails.

## Order emails

When creating order via `POST /api/orders`, backend will:

- Send order notification email to admin.
- Optionally send confirmation email to customer if `receiverEmail` is provided.
- Fallback to logged-in account email when `receiverEmail` is empty.

Additional env:

- `ORDER_NOTIFICATION_TO_EMAIL=<admin1@example.com,admin2@example.com>` (optional)
- `ORDER_SEND_AUTO_REPLY=true` (optional)

Notes:

- If `ORDER_NOTIFICATION_TO_EMAIL` is empty, backend falls back to `CONTACT_NOTIFICATION_TO_EMAIL`, then SMTP sender email.
- SMTP errors do not fail checkout API response.

## Pancake POS order sync

When creating orders via `POST /api/orders`, the backend can also create the same order on Pancake POS.

Set these environment variables:

- `PANCAKE_ENABLED=true`
- `PANCAKE_API_KEY=<your_api_key>`
- `PANCAKE_SHOP_ID=<your_shop_id>`
- `PANCAKE_BASE_URL=https://pos.pages.fm/api/v1` (optional)
- `PANCAKE_SYNC_STRICT=false` (optional, when `true` local order creation fails if Pancake sync fails)
- `PANCAKE_ORDER_MUST_SYNC=true` (recommended; when `true`, storefront checkout fails if Pancake order is not created)
- `PANCAKE_ORDER_STATUS=0` (optional)
- `PANCAKE_ORDER_STATUS_SYNC_STRICT=false` (optional; when `true`, admin status updates fail if Pancake status sync fails)
- `PANCAKE_WEBHOOK_SECRET=<optional_secret>` (recommended when enabling webhook)
- `PANCAKE_WEBHOOK_TOKEN=<optional_token>` (optional; if set, webhook must include `X-Webhook-Token`)

Order sync behavior:

- If a local order item uses a synced variant (`pancake_variation_id` available), backend sends direct `variation_id` to Pancake.
- If not mapped, backend falls back to `one_time_product` item payload.
- Admin order status updates attempt to sync status to Pancake when `orders.pancake_order_id` exists.
- Pancake can sync status back to web through webhook endpoint: `POST /api/orders/pancake-webhook`.

## Pancake product sync (Pancake -> Lộc Sang)

Use admin endpoint to pull products from Pancake:

- `POST /api/v1/admin/products/sync/pancake`
- Query params: `max_pages` (default 10), `page_size` (default from env)

Additional env:

- `PANCAKE_PRODUCT_SYNC_PAGE_SIZE=100` (optional)
- `PANCAKE_CATALOG_READ_ONLY=true` (recommended, default true): disable manual catalog CRUD and manage products only via Pancake sync.

Notes:

- Sync stores direct linkage fields for reliable interoperability:
	- `products.pancake_product_id`
	- `product_variants.pancake_variation_id`
	- `orders.pancake_order_id`
	- `order_items.pancake_variation_id`
- Raw source payload from Pancake is stored in:
	- `products.pancake_payload`
	- `product_variants.pancake_payload`
	- `orders.pancake_payload`
