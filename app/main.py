from fastapi import FastAPI

from app.core.database import Base, engine
from app.models.order import Order
from app.api.v1.orders import router as orders_router
from fastapi.middleware.cors import CORSMiddleware

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="SpiceOS API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(
    orders_router,
    prefix="/orders",
    tags=["Orders"],
)


@app.get("/")
def root():
    return {
        "name": "SpiceOS API",
        "status": "running",
        "version": "1.0.0",
    }