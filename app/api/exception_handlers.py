from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import BatchNotFoundError, CSVTooLargeError, CSVValidationError


def register_exception_handlers(app: FastAPI) -> None:

    @app.exception_handler(CSVValidationError)
    async def csv_validation_handler(request: Request, exc: CSVValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(CSVTooLargeError)
    async def csv_too_large_handler(request: Request, exc: CSVTooLargeError) -> JSONResponse:
        return JSONResponse(status_code=413, content={"detail": str(exc)})

    @app.exception_handler(BatchNotFoundError)
    async def batch_not_found_handler(request: Request, exc: BatchNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})