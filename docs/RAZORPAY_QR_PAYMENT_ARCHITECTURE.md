# Razorpay QR Payment Architecture

## Goal
Add verified online payments to the existing QR table ordering flow without creating a parallel order system or trusting browser payment state.

## Target flow
1. Customer creates a QR order. SpiceOS calculates the authoritative total.
2. SpiceOS creates a Razorpay Order server-side for exactly that total in INR.
3. Customer opens Razorpay Checkout using the public checkout payload. No Razorpay secret is sent to the client.
4. Browser returns Razorpay payment identifiers/signature to the backend.
5. Backend verifies the Razorpay signature and exact local order/amount mapping.
6. Razorpay webhook is independently verified using the webhook secret.
7. `payment.captured` is the authoritative settlement event. `payment.failed` records failure. Refund events move an already-paid payment to refunded.
8. Webhook handling is idempotent and safe to retry.
9. SpiceOS order payment status changes only through the verified payment service.
10. Kitchen continues using the existing order lifecycle; payment state and fulfillment state remain separate.

## Security rules
- Never trust a client-supplied amount, currency, restaurant, table, or order total.
- Never mark an order paid from a frontend callback alone.
- Verify the Razorpay order ID belongs to the intended SpiceOS order.
- Verify payment amount and currency match the local payment record.
- Verify webhook signatures using the server-side webhook secret.
- Make webhook event processing idempotent.
- Keep Razorpay key secret and webhook secret in Railway environment variables.
- Test and live credentials must be separate.
- Public QR endpoints must never expose secret credentials.
- Preserve existing QR server-authoritative pricing and tenant isolation.

## Data model preparation
A dedicated payment record should map:
- SpiceOS order ID
- Razorpay order ID
- Razorpay payment ID (when available)
- amount in paise
- currency
- provider status
- verified timestamps
- webhook event ID / idempotency key
- failure/refund metadata as appropriate

Do not overload `orders.payment_status` with provider identifiers.

## State model
Payment provider state is separate from fulfillment:

`created -> pending -> paid -> refunded`

Provider failures do not automatically cancel the kitchen order unless business rules explicitly require it.

## Rollout
1. Backend contract + tests.
2. Razorpay test-mode credentials.
3. QR customer checkout UI.
4. Signature + webhook verification.
5. End-to-end test-mode verification.
6. Reconciliation and failure testing.
7. Production live credentials only after verification.

## Acceptance
A QR customer can pay an order through Razorpay test mode; SpiceOS independently verifies the payment, records the provider payment, marks the existing order paid exactly once, and remains correct under duplicate callbacks/webhooks or forged browser requests.
