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

## Admin new-order push notifications

When creating order via `POST /api/orders`, backend can also send Web Push notifications to admin browsers and installed PWA apps that have enabled notifications in the admin header.

Set these environment variables to enable Web Push:

- `WEB_PUSH_VAPID_PUBLIC_KEY=<vapid_public_key>`
- `WEB_PUSH_VAPID_PRIVATE_KEY=<vapid_private_key>`
- `WEB_PUSH_VAPID_SUBJECT=mailto:admin@locsang.vn`

Notes:

- Without VAPID keys, the admin notification button will show that push is not configured.
- Push delivery runs in a background task and does not fail checkout if a notification provider rejects an expired subscription.

## Local catalog and orders

Lộc Sang manages products, categories, inventory, images, prices, and orders directly in this backend.

Notes:

- Admin creates and edits catalog data from the Lộc Sang admin panel.
- Storefront checkout creates local orders immediately and does not require any third-party POS configuration.
- Admin order status updates are local-only: `pending`, `processing`, `shipped`, `delivered`, `cancelled`.
- Customer delivery information is stored as receiver name, phone, address text, and optional note.
