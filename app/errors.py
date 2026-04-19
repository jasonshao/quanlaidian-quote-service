from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class OutOfRangeError(Exception):
    def __init__(self, field: str, message: str, hint: str | None = None):
        self.field = field
        self.message = message
        self.hint = hint


class PricingError(Exception):
    def __init__(self, message: str):
        self.message = message


class RenderError(Exception):
    def __init__(self, message: str):
        self.message = message


class ApprovalPendingError(Exception):
    def __init__(self, quote_id: str, reasons: list[str]):
        self.quote_id = quote_id
        self.reasons = reasons
        self.message = f"quote {quote_id} 需要审批后才能渲染/下发"


class NotFoundError(Exception):
    def __init__(self, resource: str, resource_id: str):
        self.resource = resource
        self.resource_id = resource_id
        self.message = f"{resource} {resource_id} 不存在或无权访问"


def _error_response(
    request: Request,
    status: int,
    code: str,
    message: str,
    field: str | None = None,
    hint: str | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    body: dict = {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
        }
    }
    if field:
        body["error"]["field"] = field
    if hint:
        body["error"]["hint"] = hint
    return JSONResponse(status_code=status, content=body)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        field = str(errors[0]["loc"][-1]) if errors else None
        msg = errors[0]["msg"] if errors else "Validation failed"
        return _error_response(request, 422, "INVALID_FORM", msg, field=field)

    @app.exception_handler(OutOfRangeError)
    async def oor_handler(request: Request, exc: OutOfRangeError) -> JSONResponse:
        return _error_response(request, 400, "OUT_OF_RANGE", exc.message, field=exc.field, hint=exc.hint)

    @app.exception_handler(PricingError)
    async def pricing_handler(request: Request, exc: PricingError) -> JSONResponse:
        return _error_response(request, 500, "PRICING_FAILED", exc.message)

    @app.exception_handler(RenderError)
    async def render_handler(request: Request, exc: RenderError) -> JSONResponse:
        return _error_response(request, 500, "RENDER_FAILED", exc.message)

    @app.exception_handler(ApprovalPendingError)
    async def approval_pending_handler(request: Request, exc: ApprovalPendingError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        body = {
            "error": {
                "code": "APPROVAL_PENDING",
                "message": exc.message,
                "request_id": request_id,
                "quote_id": exc.quote_id,
                "approval_reasons": exc.reasons,
            }
        }
        return JSONResponse(status_code=409, content=body)

    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
        return _error_response(request, 404, "NOT_FOUND", exc.message, field=exc.resource)

    @app.exception_handler(Exception)
    async def catch_all_handler(request: Request, exc: Exception) -> JSONResponse:
        return _error_response(request, 500, "INTERNAL_ERROR", "Internal server error")
