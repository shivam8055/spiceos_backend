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
        "preparing_at": "TIMESTAMP",
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
        # Existing orders already in or beyond preparation have no historical
        # kitchen-start timestamp. Use created_at as a safe one-time fallback;
        # all newly started orders receive the real server timestamp.
        connection.execute(text(
            "UPDATE orders "
            "SET preparing_at = created_at "
            "WHERE preparing_at IS NULL "
            "AND status IN ('preparing', 'ready', 'outForDelivery', 'delivered')"
        ))
        if "qr_tables" in inspector.get_table_names():
            connection.execute(text(
                "UPDATE orders "
                "SET restaurant_id = (SELECT restaurant_id FROM qr_tables WHERE qr_tables.id = orders.qr_table_id) "
                "WHERE restaurant_id IS NULL AND qr_table_id IS NOT NULL"
            ))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_orders_restaurant_id ON orders(restaurant_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_orders_preparing_at ON orders(preparing_at)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_idempotency_key ON orders(idempotency_key)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_public_token_hash ON orders(public_token_hash)"))


def ensure_inventory_tenant_schema(engine) -> None:
    inspector = inspect(engine)
    if "inventory_items" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("inventory_items")}
    with engine.begin() as connection:
        if "restaurant_id" not in existing:
            connection.execute(text("ALTER TABLE inventory_items ADD COLUMN restaurant_id VARCHAR"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_inventory_items_restaurant_id ON inventory_items(restaurant_id)"))


def ensure_payment_schema(engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    dialect = engine.dialect.name
    with engine.begin() as connection:
        if "payments" not in tables:
            id_definition = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
            connection.execute(text(
                "CREATE TABLE payments ("
                f"id {id_definition}, "
                "order_id INTEGER NOT NULL, "
                "provider VARCHAR NOT NULL, "
                "provider_order_id VARCHAR NOT NULL, "
                "provider_payment_id VARCHAR, "
                "amount_paise INTEGER NOT NULL, "
                "currency VARCHAR NOT NULL, "
                "status VARCHAR NOT NULL, "
                "provider_status VARCHAR, "
                "webhook_event_id VARCHAR, "
                "last_error TEXT, "
                "created_at TIMESTAMP NOT NULL, "
                "updated_at TIMESTAMP NOT NULL, "
                "captured_at TIMESTAMP, "
                "refunded_at TIMESTAMP"
                ")"
            ))
        else:
            # Older releases used a unique constraint/index on order_id.
            # On PostgreSQL a constraint owns its backing index, so dropping
            # the index directly crashes startup. Drop the constraint when it
            # exists, otherwise drop the legacy standalone index.
            if dialect == "postgresql":
                connection.execute(text(
                    "ALTER TABLE payments DROP CONSTRAINT IF EXISTS uq_payments_order_id"
                ))
            else:
                connection.execute(text("DROP INDEX IF EXISTS uq_payments_order_id"))

        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_payments_order_id ON payments(order_id)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_provider_order_id ON payments(provider_order_id)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_provider_payment_id ON payments(provider_payment_id)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_webhook_event_id ON payments(webhook_event_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_payments_provider_order_id ON payments(provider_order_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_payments_provider_payment_id ON payments(provider_payment_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_payments_status ON payments(status)"))


def ensure_tenant_schema(engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    if "users" in tables:
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "restaurant_id" not in user_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE users ADD COLUMN restaurant_id VARCHAR"))
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_users_restaurant_id ON users(restaurant_id)"))

    ensure_inventory_tenant_schema(engine)


def ensure_qr_ordering_schema(engine) -> None:
    ensure_order_columns(engine)
    ensure_tenant_schema(engine)
    ensure_payment_schema(engine)
