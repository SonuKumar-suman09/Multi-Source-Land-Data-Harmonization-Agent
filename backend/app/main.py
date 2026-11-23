"""FastAPI application entry point."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.harmonization import router as harmonization_router
from app.api.ingestion import router as ingestion_router
from app.api.quality import router as quality_router
from app.core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Secure API foundation for the Multi-Source Land-Data Harmonization Agent.",
)
origins = [origin.strip() for origin in settings.frontend_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(ingestion_router, prefix=settings.api_v1_prefix)
app.include_router(harmonization_router, prefix=settings.api_v1_prefix)
app.include_router(quality_router, prefix=settings.api_v1_prefix)
app.include_router(health_router)
