# SpiceOS QR Table Ordering API

## Public endpoints

### `GET /qr/public/qr/{qr_token}/menu`
Resolves an opaque QR token and returns only the restaurant/branch/table context plus server-authoritative menu data, prices, modifiers and availability.

### `POST /qr/public/qr/{qr_token}/orders`
Requires `Idempotency-Key` header. Body contains menu item IDs, quantities, modifier IDs and optional customer details. The server resolves prices and availability from the QR table's restaurant/branch menu. Client totals/prices are never accepted.

Response includes a customer-safe `public_order_token` for status polling.

### `GET /qr/public/orders/{public_order_token}`
Returns only customer-safe order number, status, total, currency, table name and creation time. No staff credentials or internal order data are exposed.

## Staff setup endpoints

`POST /qr/admin/qr-tables` creates an opaque QR token and URL. `POST /qr/admin/menu-items` creates a branch menu item. Both require the existing staff authorization dependency.

## Security rules

- QR tokens are stored as SHA-256 hashes; raw tokens are only returned when a staff QR is created.
- QR tokens can be inactive or expired.
- Menu is scoped to the QR restaurant + branch.
- Order prices are recalculated server-side.
- Unavailable items/modifiers are rejected.
- Idempotency keys are unique and replay the original order response without creating a second order.
- QR orders use `order_source=qr_table` and the existing `Order` model/status pipeline.
- Public status uses a separate customer-safe token and never exposes staff-only APIs.

## Production configuration

Set `PUBLIC_QR_BASE_URL` to the customer-facing URL prefix and set a strong random `QR_PUBLIC_TOKEN_SECRET` in the production environment. Do not use the development fallback secret in production.
