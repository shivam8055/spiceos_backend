from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import Base, engine
from app.models.order import Order
from app.models.user import User

from app.api.v1.orders import router as orders_router
from app.api.v1.auth import router as auth_router

from app.models.inventory_item import InventoryItem
from app.api.v1.inventory import router as inventory_router

Base.metadata.create_all(bind=engine)


app = FastAPI(
    title="SpiceOS API",
    version="1.0.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127.0.0.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(
    orders_router,
    prefix="/orders",
    tags=["Orders"],
)

app.include_router(
    inventory_router,
    prefix="/inventory",
    tags=["Inventory"],
)

app.include_router(
    auth_router,
    prefix="/auth",
    tags=["Authentication"],
)


@app.get("/")
def root():
    return {
        "name": "SpiceOS API",
        "status": "running",
        "version": "1.0.0",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "SpiceOS Backend",
        "version": "1.0.0",
    }