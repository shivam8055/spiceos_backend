from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import CORS_ALLOWED_ORIGINS
from app.core.database import Base, engine
from app.core.schema_migrations import ensure_qr_ordering_schema
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.payment import Payment
from app.models.user import User
from app.models.restaurant import Restaurant
from app.models.inventory_item import InventoryItem
from app.models.inventory_movement import InventoryMovement
from app.models.qr_table import QRTable
from app.models.menu_item import MenuItem

from app.api.v1.orders import router as orders_router
from app.api.v1.auth import router as auth_router
from app.api.v1.inventory import router as inventory_router
from app.api.v1.users import router as users_router
from app.api.v1.qr_ordering import router as qr_ordering_router

Base.metadata.create_all(bind=engine)
ensure_qr_ordering_schema(engine)


app = FastAPI(
    title="SpiceOS API",
    version="1.0.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_origin_regex=r"http://(localhost|127\\.0\\.1):\\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(orders_router, prefix="/orders", tags=["Orders"])
app.include_router(inventory_router, prefix="/inventory", tags=["Inventory"])
app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
app.include_router(users_router, prefix="/users", tags=["User Administration"])
app.include_router(qr_ordering_router, prefix="/qr", tags=["QR Ordering"])


@app.get("/")
def root():
    return {"name": "SpiceOS API", "status": "running", "version": "1.0.0"}


@app.get("/health")
def health():
    return {"status": "healthy", "service": "SpiceOS Backend", "version": "1.0.0"}
