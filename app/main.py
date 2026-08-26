from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.accounting import router as accounting_router
from app.api.v1.auth import router as auth_router
from app.api.v1.delivery import router as delivery_router
from app.api.v1.delivery_webhooks import router as delivery_webhooks_router
from app.api.v1.inventory import router as inventory_router
from app.api.v1.orders import router as orders_router
from app.api.v1.qr_ordering import router as qr_router
from app.api.v1.users import router as users_router
from app.core.accounting_migration import migrate_accounting_schema
from app.core.config import CORS_ALLOWED_ORIGINS
from app.core.database import engine
from app.core.delivery_migration import migrate_delivery_schema

app = FastAPI(title="SpiceOS Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

migrate_delivery_schema(engine)
migrate_accounting_schema(engine)

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(users_router)

# The order and inventory routers define collection/item routes relative to
# their feature namespace. Mount them under the same /orders and /inventory
# paths used by the production Flutter web client. Previously these routers
# were mounted at the API root, which caused /orders/* and /inventory/* to
# return 404/307 responses even though the handlers existed.
app.include_router(orders_router, prefix="/orders")
app.include_router(inventory_router, prefix="/inventory")

app.include_router(accounting_router)
app.include_router(qr_router)
# Keep the legacy /qr/* namespace working while the canonical API remains
# /public/* and /admin/*.
app.include_router(qr_router, prefix="/qr")
app.include_router(delivery_router)
app.include_router(delivery_webhooks_router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "spiceos_backend", "accounting": True}
