# Razorpay Test-Mode Setup

## Railway variables
Set these in the SpiceOS backend Railway service. Never commit their values.

- `RAZORPAY_KEY_ID` = Razorpay Test Mode Key ID (`rzp_test_...`)
- `RAZORPAY_KEY_SECRET` = Razorpay Test Mode Key Secret
- `RAZORPAY_WEBHOOK_SECRET` = strong random webhook secret
- `QR_PUBLIC_TOKEN_SECRET` = strong stable random QR token secret

## Razorpay Dashboard
Use Test Mode first. Create a webhook pointing to:

`https://spiceosbackend-production.up.railway.app/qr/public/payments/razorpay/webhook`

Subscribe at minimum to:

- `payment.captured`
- `payment.failed`
- `order.paid`
- refund event(s) used by the account

The webhook secret configured in Razorpay must exactly match `RAZORPAY_WEBHOOK_SECRET` in Railway.

## Acceptance test
1. Open a fresh table QR.
2. Add an item and place a QR order.
3. Click **Pay securely**.
4. Complete a Razorpay Test Mode payment.
5. Confirm the browser callback is accepted only after server-side signature verification.
6. Confirm the webhook changes the SpiceOS payment status to `paid`.
7. Refresh the customer screen and confirm it remains paid.
8. Confirm the kitchen order is unchanged and continues through the existing fulfillment lifecycle.
9. Repeat a failed payment and retry to ensure the order remains payable until captured.
10. Send a duplicate webhook event and confirm it is idempotent.

## Go-live gate
Do not replace test keys with live keys until the complete test-mode flow passes and the Razorpay webhook is receiving events. Razorpay's live integration requires HTTPS and server-side signature/webhook verification.
