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
    if not missing:
        return

    with engine.begin() as connection:
        for name, sql_type in missing:
            connection.execute(text(f"ALTER TABLE orders ADD COLUMN {name} {sql_type}"))

        connection.execute(text("UPDATE orders SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
        connection.execute(text("UPDATE orders SET status = 'created' WHERE status IS NULL"))
        connection.execute(text("UPDATE orders SET payment_status = 'pending' WHERE payment_status IS NULL"))
        connection.execute(text("UPDATE orders SET order_source = 'Unknown' WHERE order_source IS NULL"))


def ensure_qr_ordering_schema(engine) -> None:
    # New QR/menu/order-item tables are created by Base.metadata.create_all.
    # This helper intentionally avoids destructive ALTER operations for existing data.
    inspector = inspect(engine)
    if "orders" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("orders")}
    required = {"customer_phone", "qr_table_id", "qr_session_id", "idempotency_key", "public_token_hash"}
    if required.issubset(existing):
        return
    ensure_order_columns(engine)
