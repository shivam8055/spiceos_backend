from sqlalchemy import inspect, text


def _is_postgres(engine) -> bool:
    return engine.dialect.name == "postgresql"


def _id_column(engine) -> str:
    return "BIGSERIAL PRIMARY KEY" if _is_postgres(engine) else "INTEGER PRIMARY KEY"


def migrate_delivery_schema(engine):
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    id_column = _id_column(engine)

    with engine.begin() as conn:
        if "delivery_agents" not in tables:
            conn.execute(text(
                f"CREATE TABLE delivery_agents ("
                f"id {id_column}, restaurant_id VARCHAR NOT NULL, name VARCHAR(120) NOT NULL, "
                "phone VARCHAR(40), status VARCHAR(20) NOT NULL DEFAULT 'offline', "
                "is_active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMP NOT NULL, "
                "updated_at TIMESTAMP NOT NULL)"
            ))

        if "delivery_jobs" not in tables:
            conn.execute(text(
                f"CREATE TABLE delivery_jobs ("
                f"id {id_column}, delivery_token VARCHAR(64) NOT NULL UNIQUE, "
                "restaurant_id VARCHAR NOT NULL, order_id INTEGER NOT NULL UNIQUE, agent_id BIGINT, "
                "provider VARCHAR(40) NOT NULL DEFAULT 'own_agent', provider_delivery_id VARCHAR(120), "
                "tracking_url TEXT, status VARCHAR(30) NOT NULL DEFAULT 'created', pickup_address TEXT, "
                "delivery_address TEXT NOT NULL, customer_name VARCHAR(120), customer_phone VARCHAR(40), "
                "eta_minutes INTEGER, latitude VARCHAR(32), longitude VARCHAR(32), "
                "created_at TIMESTAMP NOT NULL, updated_at TIMESTAMP NOT NULL)"
            ))
        else:
            columns = {column["name"] for column in inspect(conn).get_columns("delivery_jobs")}
            if "tracking_url" not in columns:
                conn.execute(text("ALTER TABLE delivery_jobs ADD COLUMN tracking_url TEXT"))

        if "delivery_events" not in tables:
            conn.execute(text(
                f"CREATE TABLE delivery_events ("
                f"id {id_column}, delivery_job_id BIGINT NOT NULL, restaurant_id VARCHAR NOT NULL, "
                "status VARCHAR(30) NOT NULL, actor_type VARCHAR(30) NOT NULL, actor_id VARCHAR(120), "
                "latitude VARCHAR(32), longitude VARCHAR(32), note TEXT, created_at TIMESTAMP NOT NULL)"
            ))
