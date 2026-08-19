# SpiceOS Delivery Provider Setup

## Provider strategy

SpiceOS supports a provider-neutral delivery layer. `own_agent` is always available. External providers are selected per delivery job and must never bypass tenant authorization or delivery state validation.

## Uber Direct

The adapter uses Uber's official Direct API OAuth flow and delivery quote/create/status/cancel endpoints. Uber documents the OAuth `client_credentials` flow with the `eats.deliveries` scope and requires a Direct customer ID. Test credentials operate in sandbox; production credentials require the Uber account to be approved for production and billing to be configured.

Required environment variables:

- `UBER_DIRECT_CLIENT_ID`
- `UBER_DIRECT_CLIENT_SECRET`
- `UBER_DIRECT_CUSTOMER_ID`
- Optional: `UBER_DIRECT_BASE_URL` (defaults to `https://api.uber.com`)

Never commit these values. Configure them as Railway secrets/environment variables.

## Rapido

SpiceOS has a provider boundary for Rapido, but no undocumented/private API is used. Activation requires official partner/API documentation and credentials from Rapido. Until then, requesting `rapido` returns a controlled `503` rather than silently falling back or pretending a delivery was created.

## Ola

SpiceOS has a provider boundary for Ola, but no undocumented/private API is used. Activation requires official partner/API documentation and credentials from Ola. Until then, requesting `ola` returns a controlled `503`.

## Production activation

1. Configure provider secrets.
2. Run adapter contract tests.
3. Validate quote/create/status/cancel in provider sandbox.
4. Verify webhook/event handling and idempotency.
5. Enable the provider for the restaurant only after the provider account is approved.
6. Keep `own_agent` available as the operational fallback.
