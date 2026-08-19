"""Provider adapters for third-party delivery networks.

Adapters are disabled unless provider credentials are configured. No
undocumented/private partner APIs are used.
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests

from app.services.delivery_providers import DeliveryProvider, DeliveryQuote, ProviderDelivery


class ProviderNotConfigured(RuntimeError):
    pass


class ProviderRequestError(RuntimeError):
    pass


class _HttpProvider(DeliveryProvider):
    timeout_seconds = 15

    def _request(self, method: str, url: str, *, headers: dict[str, str], payload: dict[str, Any] | None = None) -> dict[str, Any]:
        response = requests.request(method, url, headers=headers, json=payload, timeout=self.timeout_seconds)
        if response.status_code >= 400:
            raise ProviderRequestError(f"{self.name} returned HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderRequestError(f"{self.name} returned invalid JSON") from exc


class UberDirectProvider(_HttpProvider):
    """Uber Direct DaaS adapter using Uber's official Direct API."""

    name = "uber_direct"

    def __init__(self) -> None:
        self.client_id = os.getenv("UBER_DIRECT_CLIENT_ID")
        self.client_secret = os.getenv("UBER_DIRECT_CLIENT_SECRET")
        self.customer_id = os.getenv("UBER_DIRECT_CUSTOMER_ID")
        self.base_url = os.getenv("UBER_DIRECT_BASE_URL", "https://api.uber.com")
        if not all((self.client_id, self.client_secret, self.customer_id)):
            raise ProviderNotConfigured("Uber Direct credentials are not configured")

    def _token(self) -> str:
        response = requests.post(
            "https://auth.uber.com/oauth/v2/token",
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
                "scope": "eats.deliveries",
            },
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            raise ProviderRequestError(f"Uber Direct authentication failed: HTTP {response.status_code}")
        token = response.json().get("access_token")
        if not token:
            raise ProviderRequestError("Uber Direct authentication returned no access token")
        return token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"}

    @staticmethod
    def _address(value: str) -> str:
        try:
            json.loads(value)
            return value
        except (TypeError, json.JSONDecodeError):
            return json.dumps({"street_address": [value], "country": "IN"})

    def _create_quote(self, pickup_address: str, delivery_address: str) -> dict[str, Any]:
        return self._request(
            "POST",
            f"{self.base_url}/v1/customers/{self.customer_id}/delivery_quotes",
            headers=self._headers(),
            payload={
                "pickup_address": self._address(pickup_address),
                "dropoff_address": self._address(delivery_address),
            },
        )

    def quote(self, pickup_address: str, delivery_address: str) -> DeliveryQuote:
        data = self._create_quote(pickup_address, delivery_address)
        return DeliveryQuote(
            provider=self.name,
            amount=int(data.get("fee", 0)),
            currency=str(data.get("currency", "INR")).upper(),
            eta_minutes=int(data["duration"]) if data.get("duration") is not None else None,
        )

    def create_delivery(self, *, pickup_address: str, delivery_address: str, customer_name: str | None, customer_phone: str | None, idempotency_key: str) -> ProviderDelivery:
        quote_data = self._create_quote(pickup_address, delivery_address)
        quote_id = quote_data.get("id")
        if not quote_id:
            raise ProviderRequestError("Uber Direct quote response did not include an id")

        payload: dict[str, Any] = {
            "quote_id": quote_id,
            "pickup_address": self._address(pickup_address),
            "dropoff_address": self._address(delivery_address),
            "pickup_name": "SpiceOS",
            "dropoff_name": customer_name or "Customer",
            "idempotency_key": idempotency_key,
        }
        if customer_phone:
            payload["dropoff_phone_number"] = customer_phone

        data = self._request(
            "POST",
            f"{self.base_url}/v1/customers/{self.customer_id}/deliveries",
            headers=self._headers(),
            payload=payload,
        )
        return ProviderDelivery(
            provider=self.name,
            provider_delivery_id=str(data.get("id", "")),
            status=str(data.get("status", "pending")),
            tracking_url=data.get("tracking_url"),
        )

    def cancel_delivery(self, provider_delivery_id: str) -> None:
        self._request(
            "POST",
            f"{self.base_url}/v1/customers/{self.customer_id}/deliveries/{provider_delivery_id}/cancel",
            headers=self._headers(),
            payload={"cancelation_reason": "other", "additional_description": "Cancelled by SpiceOS"},
        )

    def get_status(self, provider_delivery_id: str) -> ProviderDelivery:
        data = self._request(
            "GET",
            f"{self.base_url}/v1/customers/{self.customer_id}/deliveries/{provider_delivery_id}",
            headers=self._headers(),
        )
        return ProviderDelivery(
            provider=self.name,
            provider_delivery_id=provider_delivery_id,
            status=str(data.get("status", "unknown")),
            tracking_url=data.get("tracking_url"),
        )

    def tracking(self, provider_delivery_id: str) -> str | None:
        return self.get_status(provider_delivery_id).tracking_url


class _PartnerProvider(DeliveryProvider):
    def __init__(self, provider_name: str) -> None:
        self.name = provider_name
        raise ProviderNotConfigured(f"{provider_name.title()} partner/API credentials are not configured")

    def quote(self, pickup_address: str, delivery_address: str) -> DeliveryQuote:
        raise ProviderNotConfigured(f"{self.name.title()} integration is awaiting official partner API access")

    def create_delivery(self, *, pickup_address: str, delivery_address: str, customer_name: str | None, customer_phone: str | None, idempotency_key: str) -> ProviderDelivery:
        raise ProviderNotConfigured(f"{self.name.title()} integration is awaiting official partner API access")

    def cancel_delivery(self, provider_delivery_id: str) -> None:
        raise ProviderNotConfigured(f"{self.name.title()} integration is awaiting official partner API access")

    def get_status(self, provider_delivery_id: str) -> ProviderDelivery:
        raise ProviderNotConfigured(f"{self.name.title()} integration is awaiting official partner API access")

    def tracking(self, provider_delivery_id: str) -> str | None:
        raise ProviderNotConfigured(f"{self.name.title()} integration is awaiting official partner API access")


class RapidoProvider(_PartnerProvider):
    name = "rapido"

    def __init__(self) -> None:
        super().__init__(self.name)


class OlaProvider(_PartnerProvider):
    name = "ola"

    def __init__(self) -> None:
        super().__init__(self.name)
