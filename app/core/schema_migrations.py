from sqlalchemy import inspect, text


def ensure_order_columns(engine) -> None:
    inspector = inspect(engine)
    if "orders" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("orders")}
    additions = {"restaurant_id":"VARCHAR","customer_id":"VARCHAR","primary_item":"VARCHAR","created_at":"TIMESTAMP","preparing_at":"TIMESTAMP","ready_at":"TIMESTAMP","out_for_delivery_at":"TIMESTAMP","delivered_at":"TIMESTAMP","status":"VARCHAR","payment_status":"VARCHAR","order_source":"VARCHAR","customer_phone":"VARCHAR","qr_table_id":"INTEGER","qr_session_id":"VARCHAR","idempotency_key":"VARCHAR","public_token_hash":"VARCHAR"}
    missing = [(name, sql_type) for name, sql_type in additions.items() if name not in existing]
    with engine.begin() as connection:
        for name, sql_type in missing:
            connection.execute(text(f"ALTER TABLE orders ADD COLUMN {name} {sql_type}"))
        connection.execute(text("UPDATE orders SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
        connection.execute(text("UPDATE orders SET status = 'created' WHERE status IS NULL"))
        connection.execute(text("UPDATE orders SET payment_status = 'pending' WHERE payment_status IS NULL"))
        connection.execute(text("UPDATE orders SET order_source = 'Unknown' WHERE order_source IS NULL"))
        connection.execute(text("UPDATE orders SET preparing_at = created_at WHERE preparing_at IS NULL AND status IN ('preparing', 'ready', 'outForDelivery', 'delivered')"))
        if "qr_tables" in inspector.get_table_names():
            connection.execute(text("UPDATE orders SET restaurant_id = (SELECT restaurant_id FROM qr_tables WHERE qr_tables.id = orders.qr_table_id) WHERE restaurant_id IS NULL AND qr_table_id IS NOT NULL"))
        for index_sql in [
            "CREATE INDEX IF NOT EXISTS ix_orders_restaurant_id ON orders(restaurant_id)",
            "CREATE INDEX IF NOT EXISTS ix_orders_preparing_at ON orders(preparing_at)",
            "CREATE INDEX IF NOT EXISTS ix_orders_ready_at ON orders(ready_at)",
            "CREATE INDEX IF NOT EXISTS ix_orders_out_for_delivery_at ON orders(out_for_delivery_at)",
            "CREATE INDEX IF NOT EXISTS ix_orders_delivered_at ON orders(delivered_at)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_idempotency_key ON orders(idempotency_key)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_public_token_hash ON orders(public_token_hash)",
        ]:
            connection.execute(text(index_sql))


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
            connection.execute(text("CREATE TABLE payments (id " + id_definition + ", order_id INTEGER NOT NULL, provider VARCHAR NOT NULL, provider_order_id VARCHAR NOT NULL, provider_payment_id VARCHAR, amount_paise INTEGER NOT NULL, currency VARCHAR NOT NULL, status VARCHAR NOT NULL, provider_status VARCHAR, webhook_event_id VARCHAR, last_error TEXT, created_at TIMESTAMP NOT NULL, updated_at TIMESTAMP NOT NULL, captured_at TIMESTAMP, refunded_at TIMESTAMP)"))
        else:
            if dialect == "postgresql":
                connection.execute(text("ALTER TABLE payments DROP CONSTRAINT IF EXISTS uq_payments_order_id"))
            else:
                connection.execute(text("DROP INDEX IF EXISTS uq_payments_order_id"))
        for index_sql in [
            "CREATE INDEX IF NOT EXISTS ix_payments_order_id ON payments(order_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_provider_order_id ON payments(provider_order_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_provider_payment_id ON payments(provider_payment_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_webhook_event_id ON payments(webhook_event_id)",
            "CREATE INDEX IF NOT EXISTS ix_payments_provider_order_id ON payments(provider_order_id)",
            "CREATE INDEX IF NOT EXISTS ix_payments_provider_payment_id ON payments(provider_payment_id)",
            "CREATE INDEX IF NOT EXISTS ix_payments_status ON payments(status)",
        ]:
            connection.execute(text(index_sql))


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


def ensure_whatsapp_ordering_schema(engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    dialect = engine.dialect.name
    with engine.begin() as connection:
        if "whatsapp_sessions" not in tables:
            id_definition = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
            connection.execute(text("CREATE TABLE whatsapp_sessions (id " + id_definition + ", wa_id VARCHAR NOT NULL, restaurant_id VARCHAR, branch_id VARCHAR, qr_token VARCHAR, state VARCHAR NOT NULL, draft_json TEXT NOT NULL, customer_name VARCHAR, customer_phone VARCHAR, last_message_id VARCHAR, created_at TIMESTAMP NOT NULL, updated_at TIMESTAMP NOT NULL)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_whatsapp_sessions_wa_id ON whatsapp_sessions(wa_id)"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_whatsapp_sessions_last_message_id ON whatsapp_sessions(last_message_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_whatsapp_sessions_restaurant_id ON whatsapp_sessions(restaurant_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_whatsapp_sessions_branch_id ON whatsapp_sessions(branch_id)"))


def ensure_qr_ordering_schema(engine) -> None:
    ensure_order_columns(engine)
    ensure_tenant_schema(engine)
    ensure_payment_schema(engine)
    ensure_whatsapp_ordering_schema(engine)
