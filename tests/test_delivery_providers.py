import os

import pytest

from app.services.delivery_providers import DeliveryQuote
from app.services.external_delivery_providers import (
    OlaProvider,
    ProviderNotConfigured,
    RapidoProvider,
    UberDirectProvider,
)


def test_uber_requires_credentials(monkeypatch):
    for key in ("UBER_DIRECT_CLIENT_ID", "UBER_DIRECT_CLIENT_SECRET", "UBER_DIRECT_CUSTOMER_ID"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ProviderNotConfigured):
        UberDirectProvider()


def test_rapido_is_gated_until_official_partner_access():
    with pytest.raises(ProviderNotConfigured):
        RapidoProvider()


def test_ola_is_gated_until_official_partner_access():
    with pytest.raises(ProviderNotConfigured):
        OlaProvider()


def test_uber_quote_maps_official_response(monkeypatch):
    monkeypatch.setenv("UBER_DIRECT_CLIENT_ID", "test-client")
    monkeypatch.setenv("UBER_DIRECT_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("UBER_DIRECT_CUSTOMER_ID", "customer-1")
    provider = UberDirectProvider()
    monkeypatch.setattr(provider, "_headers", lambda: {"Authorization": "Bearer test", "Content-Type": "application/json"})
    monkeypatch.setattr(provider, "_request", lambda *args, **kwargs: {
        "id": "dqt_test",
        "fee": 599,
        "currency": "inr",
        "duration": 32,
    })
    quote = provider.quote("pickup", "dropoff")
    assert quote == DeliveryQuote(provider="uber_direct", amount=599, currency="INR", eta_minutes=32)


def test_uber_create_uses_quote_id_and_idempotency(monkeypatch):
    monkeypatch.setenv("UBER_DIRECT_CLIENT_ID", "test-client")
    monkeypatch.setenv("UBER_DIRECT_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("UBER_DIRECT_CUSTOMER_ID", "customer-1")
    provider = UberDirectProvider()
    monkeypatch.setattr(provider, "_headers", lambda: {"Authorization": "Bearer test", "Content-Type": "application/json"})
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if "delivery_quotes" in url:
            return {"id": "dqt_test", "fee": 599, "currency": "inr", "duration": 32}
        return {"id": "del_test", "status": "pending", "tracking_url": "https://tracking.example/test"}

    monkeypatch.setattr(provider, "_request", fake_request)
    delivery = provider.create_delivery(
        pickup_address="pickup",
        delivery_address="dropoff",
        customer_name="Customer",
        customer_phone="+919999999999",
        idempotency_key="delivery-order-1",
    )

    assert delivery.provider_delivery_id == "del_test"
    assert len(calls) == 2
    assert calls[1][2]["payload"]["quote_id"] == "dqt_test"
    assert calls[1][2]["payload"]["idempotency_key"] == "delivery-order-1"
