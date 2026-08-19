from sqlalchemy import create_engine, inspect

from app.core.delivery_migration import migrate_delivery_schema


def test_delivery_migration_sqlite():
    engine = create_engine("sqlite:///:memory:")
    migrate_delivery_schema(engine)
    tables = set(inspect(engine).get_table_names())
    assert {"delivery_agents", "delivery_jobs", "delivery_events"}.issubset(tables)

    columns = {c["name"] for c in inspect(engine).get_columns("delivery_jobs")}
    assert {"id", "delivery_token", "tracking_url", "provider"}.issubset(columns)


def test_delivery_migration_is_idempotent():
    engine = create_engine("sqlite:///:memory:")
    migrate_delivery_schema(engine)
    migrate_delivery_schema(engine)
    assert "delivery_jobs" in inspect(engine).get_table_names()
