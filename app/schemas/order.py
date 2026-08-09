from pydantic import BaseModel


class Order(BaseModel):
    id: int
    order_number: str
    customer_name: str
    total: float