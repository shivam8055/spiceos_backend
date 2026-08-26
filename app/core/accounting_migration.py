from sqlalchemy import inspect, text


def _id_column(engine) -> str:
    return "BIGSERIAL PRIMARY KEY" if engine.dialect.name == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"


def migrate_accounting_schema(engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    rid = _id_column(engine)
    with engine.begin() as conn:
        if "sales_invoices" not in tables:
            conn.execute(text(
                f"CREATE TABLE sales_invoices (id {rid}, restaurant_id VARCHAR NOT NULL, invoice_number VARCHAR NOT NULL, "
                "order_id INTEGER, customer_name VARCHAR(255) NOT NULL DEFAULT 'Walk-in Customer', customer_phone VARCHAR, "
                "customer_gstin VARCHAR(15), invoice_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, subtotal DOUBLE PRECISION NOT NULL DEFAULT 0, "
                "cgst DOUBLE PRECISION NOT NULL DEFAULT 0, sgst DOUBLE PRECISION NOT NULL DEFAULT 0, igst DOUBLE PRECISION NOT NULL DEFAULT 0, "
                "discount DOUBLE PRECISION NOT NULL DEFAULT 0, total DOUBLE PRECISION NOT NULL DEFAULT 0, payment_status VARCHAR NOT NULL DEFAULT 'pending', "
                "status VARCHAR NOT NULL DEFAULT 'issued', notes TEXT, created_by_user_id INTEGER NOT NULL)"
            ))
        if "purchase_invoices" not in tables:
            conn.execute(text(
                f"CREATE TABLE purchase_invoices (id {rid}, restaurant_id VARCHAR NOT NULL, bill_number VARCHAR NOT NULL, vendor_name VARCHAR(255) NOT NULL, "
                "vendor_gstin VARCHAR(15), invoice_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, due_date TIMESTAMP, subtotal DOUBLE PRECISION NOT NULL DEFAULT 0, "
                "cgst DOUBLE PRECISION NOT NULL DEFAULT 0, sgst DOUBLE PRECISION NOT NULL DEFAULT 0, igst DOUBLE PRECISION NOT NULL DEFAULT 0, total DOUBLE PRECISION NOT NULL DEFAULT 0, "
                "payment_status VARCHAR NOT NULL DEFAULT 'unpaid', attachment_url VARCHAR, notes TEXT, created_by_user_id INTEGER NOT NULL)"
            ))
        if "expenses" not in tables:
            conn.execute(text(
                f"CREATE TABLE expenses (id {rid}, restaurant_id VARCHAR NOT NULL, expense_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "category VARCHAR(100) NOT NULL, description VARCHAR(255) NOT NULL, amount DOUBLE PRECISION NOT NULL, gst_amount DOUBLE PRECISION NOT NULL DEFAULT 0, "
                "payment_mode VARCHAR(30) NOT NULL DEFAULT 'cash', reference VARCHAR(100), created_by_user_id INTEGER NOT NULL)"
            ))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sales_invoices_restaurant_date ON sales_invoices(restaurant_id, invoice_date)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_purchase_invoices_restaurant_date ON purchase_invoices(restaurant_id, invoice_date)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_expenses_restaurant_date ON expenses(restaurant_id, expense_date)"))
        # Invoice numbers and vendor bills are tenant-scoped; the API also validates duplicates before insert.
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_invoice_number_restaurant ON sales_invoices(restaurant_id, invoice_number)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_purchase_bill_restaurant_vendor ON purchase_invoices(restaurant_id, bill_number, vendor_name)"))
