from sqlalchemy import inspect, text


def migrate_delivery_schema(engine):
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        if "delivery_agents" not in tables:
            conn.execute(text("CREATE TABLE delivery_agents (id INTEGER PRIMARY KEY, restaurant_id VARCHAR NOT NULL, name VARCHAR(120) NOT NULL, phone VARCHAR(40), status VARCHAR(20) NOT NULL DEFAULT 'offline', is_active BOOLEAN NOT NULL DEFAULT 1, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"))
        if "delivery_jobs" not in tables:
            conn.execute(text("CREATE TABLE delivery_jobs (id INTEGER PRIMARY KEY, delivery_token VARCHAR(64) NOT NULL UNIQUE, restaurant_id VARCHAR NOT NULL, order_id INTEGER NOT NULL UNIQUE, agent_id INTEGER, provider VARCHAR(40) NOT NULL DEFAULT 'own_agent', provider_delivery_id VARCHAR(120), status VARCHAR(30) NOT NULL DEFAULT 'created', pickup_address TEXT, delivery_address TEXT NOT NULL, customer_name VARCHAR(120), customer_phone VARCHAR(40), eta_minutes INTEGER, latitude VARCHAR(32), longitude VARCHAR(32), created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"))
        if "delivery_events" not in tables:
            conn.execute(text("CREATE TABLE delivery_events (id INTEGER PRIMARY KEY, delivery_job_id INTEGER NOT NULL, restaurant_id VARCHAR NOT NULL, status VARCHAR(30) NOT NULL, actor_type VARCHAR(30) NOT NULL, actor_id VARCHAR(120), latitude VARCHAR(32), longitude VARCHAR(32), note TEXT, created_at DATETIME NOT NULL)"))
