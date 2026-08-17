from sqlalchemy import inspect, text


def ensure_order_columns(engine) -> None:
    inspector = inspect(engine)
    if "orders" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("orders")}
    additions = {
        "restaurant_id": "VARCHAR",
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
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_orders_restaurant_id ON orders(restaurant_id)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_idempotency_key ON orders(idempotency_key)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_public_token_hash ON orders(public_token_hash)"))


def ensure_tenant_schema(engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    if "users" in tables:
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "restaurant_id" not in user_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE users ADD COLUMN restaurant_id VARCHAR"))
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_users_restaurant_id ON users(restaurant_id)"))


def ensure_qr_ordering_schema(engine) -> None:
    ensure_order_columns(engine)
    ensure_tenant_schema(engine)
