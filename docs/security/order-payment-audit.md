# Order and payment integrity audit

## Findings

### P1 — unrestricted payment-status mutation
The order PATCH endpoint previously accepted `payment_status` changes from any staff role and did not enforce transitions. This allowed a staff user to mark an order paid/refunded or move between payment states without a payment workflow.

**Fix:** payment changes are manager/owner-only and follow `pending -> paid -> refunded` transitions.

### P1 — financial total mutation
The order PATCH endpoint previously allowed any staff role to change `total`. This could alter the financial amount after order creation.

**Fix:** manual-order total changes are manager/owner-only. QR order totals are immutable because their prices are server-authoritative.

### P1 — order provenance mutation
The order PATCH endpoint previously allowed `order_source` to be changed. That could convert a QR order into a manual order and weaken downstream controls/auditing.

**Fix:** order source is immutable.

### P1 — invalid initial payment states
Manual order creation previously accepted `refunded` as an initial payment state.

**Fix:** new orders may start only as `pending` or `paid`; staff may create pending orders, while paid creation is manager/owner-only.

## Regression coverage
`tests/test_order_integrity.py` covers staff restrictions, payment transitions, QR total immutability, and order-source immutability.

## Remaining payment architecture
There is currently no payment-provider webhook or server-side payment-capture endpoint in this backend. Therefore `paid` remains a controlled manual settlement state for manager/owner users. When a payment provider is integrated, the provider webhook should become the authoritative source for `paid`/`refunded` and the manual mutation path should be removed or restricted further.
