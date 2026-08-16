from sqlalchemy import inspect, text


def ensure_order_columns(engine) -> None:
    inspector = inspect(engine)
    if "orders" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("orders")}
    additions = {
        "customer_id": "VARCHAR",
        "primary_item": "VARCHAR",
        "created_at": "TIMESTAMP",
        "status": "VARCHAR",
        "payment_status": "VARCHAR",
        "order_source": "VARCHAR",
        "customer_phone": "VARCHAR",
        "qr_table_id": "INTEGER",
        "qr_session_id": "VARCHAR",
        "idempotency_key": "VARCHAR",
        "public_token_hash": "VARCHAR",
    }
    missing = [(name, sql_type) for name, sql_type in additions.items() if name not in existing]
    with engine.begin() as connection:
        for name, sql_type in missing:
            connection.execute(text(f"ALTER TABLE orders ADD COLUMN {name} {sql_type}"))
        connection.execute(text("UPDATE orders SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
        connection.execute(text("UPDATE orders SET status = 'created' WHERE status IS NULL"))
        connection.execute(text("UPDATE orders SET payment_status = 'pending' WHERE payment_status IS NULL"))
        connection.execute(text("UPDATE orders SET order_source = 'Unknown' WHERE order_source IS NULL"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_idempotency_key ON orders(idempotency_key)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_public_token_hash ON orders(public_token_hash)"))


def ensure_qr_ordering_schema(engine) -> None:
    ensure_order_columns(engine)
