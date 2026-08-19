import pytest

from app.services.external_delivery_providers import OlaProvider, ProviderNotConfigured, RapidoProvider, UberDirectProvider


def test_uber_requires_credentials(monkeypatch):
    for key in ("UBER_DIRECT_CLIENT_ID", "UBER_DIRECT_CLIENT_SECRET", "UBER_DIRECT_CUSTOMER_ID"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ProviderNotConfigured):
        UberDirectProvider()


def test_rapido_is_explicitly_gated():
    with pytest.raises(ProviderNotConfigured):
        RapidoProvider()


def test_ola_is_explicitly_gated():
    with pytest.raises(ProviderNotConfigured):
        OlaProvider()
