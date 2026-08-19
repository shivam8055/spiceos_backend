from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.delivery import router as delivery_router
from app.api.v1.inventory import router as inventory_router
from app.api.v1.orders import router as orders_router
from app.api.v1.qr_ordering import router as qr_router
from app.api.v1.users import router as users_router
from app.core.database import engine
from app.core.delivery_migration import migrate_delivery_schema

app = FastAPI(title="SpiceOS Backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

migrate_delivery_schema(engine)

app.include_router(users_router)
app.include_router(orders_router)
app.include_router(inventory_router)
app.include_router(qr_router)
app.include_router(delivery_router)

@app.get("/health")
def health():
    return {"status": "ok"}
