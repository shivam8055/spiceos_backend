# Order and payment integrity audit

This audit found and fixes financial mutation controls in the order API.

- Payment status is manager/owner-only and follows `pending -> paid -> refunded`.
- New orders cannot start as `refunded`.
- Manual order total changes are manager/owner-only.
- QR order totals are immutable and remain server-authoritative.
- Order source is immutable so QR provenance cannot be changed into a manual order.
- Regression coverage is in `tests/test_order_integrity.py`.

There is not yet a payment-provider webhook/capture endpoint. Until one is integrated, `paid` remains a controlled manual settlement state for manager/owner users. A future payment provider webhook should become authoritative for capture/refund state.
