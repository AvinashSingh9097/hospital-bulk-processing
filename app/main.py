from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import close_http_client, init_http_client
from app.api.routes import hospitals
from app.api.exception_handlers import register_exception_handlers
from app.core.config import get_settings
from app.db.session import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await init_db()
    await init_http_client(settings)
    yield
    await close_http_client()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Bulk hospital processing service. "
        "Upload a CSV to create and activate hospitals via the Hospital Directory API."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(hospitals.router, prefix="/api/v1")


@app.get("/health", tags=["Health"])
async def health() -> dict:
    return {"status": "ok", "version": settings.app_version}