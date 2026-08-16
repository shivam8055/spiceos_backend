from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text

from app.core.database import Base


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    menu_item_id = Column(Integer, nullable=False, index=True)
    item_name = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)
    modifiers_json = Column(Text, nullable=False, default="[]")
    line_total = Column(Float, nullable=False)
    note = Column(Text, nullable=True)
