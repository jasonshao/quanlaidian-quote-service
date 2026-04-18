from fastapi import FastAPI, Request
from app.api import quote, health, files
from app.errors import register_exception_handlers

app = FastAPI(title="Quanlaidian Quote Service", version="1.0.0")

register_exception_handlers(app)

# Middleware to set request_id for error responses
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    if not hasattr(request.state, "request_id"):
        request.state.request_id = "unknown"
    response = await call_next(request)
    return response

app.include_router(quote.router)
app.include_router(health.router)
app.include_router(files.router)
