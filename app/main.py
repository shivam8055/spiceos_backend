from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.accounting import router as accounting_router
from app.api.v1.auth import router as auth_router
from app.api.v1.customers import router as customers_router
from app.api.v1.delivery import router as delivery_router
from app.api.v1.delivery_webhooks import router as delivery_webhooks_router
from app.api.v1.inventory import router as inventory_router
from app.api.v1.menu_admin import router as menu_admin_router
from app.api.v1.orders import router as orders_router
from app.api.v1.qr_ordering import router as qr_router
from app.api.v1 import qr_ordering as _qr_ordering
from app.api.v1.reports import router as reports_router
from app.api.v1.users import router as users_router
from app.api.v1.whatsapp_webhooks import router as whatsapp_router
from app.core.accounting_migration import migrate_accounting_schema
from app.core.config import CORS_ALLOWED_ORIGINS
from app.core.database import engine
from app.core.delivery_migration import migrate_delivery_schema
from app.core.schema_migrations import ensure_qr_ordering_schema

from app.services import menu_import as _menu_import
from app.services.menu_enrichment import enrich_extractor
from app.services.menu_import_name_repair_safe import repair_local_ocr
from app.services.menu_momo_table import augment_local_ocr

_menu_import._local_ocr_extract = repair_local_ocr(_menu_import._local_ocr_extract)
_menu_import._local_ocr_extract = augment_local_ocr(_menu_import._local_ocr_extract)
_menu_import.extract_menu_from_image = enrich_extractor(_menu_import.extract_menu_from_image)
_qr_ordering.extract_menu_from_image = enrich_extractor(_qr_ordering.extract_menu_from_image)

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
ensure_qr_ordering_schema(engine)

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(users_router)
app.include_router(orders_router, prefix="/orders")
app.include_router(inventory_router, prefix="/inventory")
app.include_router(accounting_router)
app.include_router(reports_router)
app.include_router(customers_router)
app.include_router(qr_router)
app.include_router(menu_admin_router)
app.include_router(qr_router, prefix="/qr")
app.include_router(delivery_router)
app.include_router(delivery_webhooks_router)
app.include_router(whatsapp_router)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "spiceos_backend",
        "accounting": True,
        "reports": True,
        "customers": True,
        "whatsapp_ordering": True,
    }
