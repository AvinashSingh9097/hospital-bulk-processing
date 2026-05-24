from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.deps import close_http_client, init_http_client
from app.api.routes import hospitals
from app.core.config import get_settings
from app.core.exceptions import BatchNotFoundError, CSVTooLargeError, CSVValidationError
from app.db.session import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup
    await init_db()
    await init_http_client(settings)
    yield
    # Shutdown
    await close_http_client()


def create_app() -> FastAPI:
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

    # ── Global exception handlers ────────────────────────────────────────────
    @app.exception_handler(CSVValidationError)
    async def csv_validation_handler(request: Request, exc: CSVValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(CSVTooLargeError)
    async def csv_too_large_handler(request: Request, exc: CSVTooLargeError) -> JSONResponse:
        return JSONResponse(status_code=413, content={"detail": str(exc)})

    @app.exception_handler(BatchNotFoundError)
    async def batch_not_found_handler(request: Request, exc: BatchNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    # ── Routers ──────────────────────────────────────────────────────────────
    app.include_router(hospitals.router, prefix="/api/v1")

    @app.get("/health", tags=["Health"])
    async def health() -> dict:
        return {"status": "ok", "version": settings.app_version}

    return app


app = create_app()
