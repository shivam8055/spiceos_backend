from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class DeliveryQuote:
    provider: str
    amount: int
    currency: str = "INR"
    eta_minutes: Optional[int] = None


@dataclass
class ProviderDelivery:
    provider: str
    provider_delivery_id: str
    status: str
    tracking_url: Optional[str] = None
    eta_minutes: Optional[int] = None


class DeliveryProvider(ABC):
    name: str

    @abstractmethod
    def quote(self, pickup_address: str, delivery_address: str) -> DeliveryQuote:
        raise NotImplementedError

    @abstractmethod
    def create_delivery(self, *, pickup_address: str, delivery_address: str, customer_name: str | None, customer_phone: str | None, idempotency_key: str) -> ProviderDelivery:
        raise NotImplementedError

    @abstractmethod
    def cancel_delivery(self, provider_delivery_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_status(self, provider_delivery_id: str) -> ProviderDelivery:
        raise NotImplementedError

    @abstractmethod
    def tracking(self, provider_delivery_id: str) -> Optional[str]:
        raise NotImplementedError


class OwnAgentProvider(DeliveryProvider):
    name = "own_agent"

    def quote(self, pickup_address: str, delivery_address: str) -> DeliveryQuote:
        return DeliveryQuote(provider=self.name, amount=0)

    def create_delivery(self, *, pickup_address: str, delivery_address: str, customer_name: str | None, customer_phone: str | None, idempotency_key: str) -> ProviderDelivery:
        return ProviderDelivery(provider=self.name, provider_delivery_id=idempotency_key, status="created")

    def cancel_delivery(self, provider_delivery_id: str) -> None:
        return None

    def get_status(self, provider_delivery_id: str) -> ProviderDelivery:
        return ProviderDelivery(provider=self.name, provider_delivery_id=provider_delivery_id, status="created")

    def tracking(self, provider_delivery_id: str) -> Optional[str]:
        return None
