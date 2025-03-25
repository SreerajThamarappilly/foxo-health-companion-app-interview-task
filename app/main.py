# app/main.py
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.auth import routes as auth_routes
from app.admin import routes as admin_routes
from app.pdf import routes as pdf_routes

# Configure logging (this uses uvicorn's logger)
logger = logging.getLogger("uvicorn.error")

app = FastAPI(
    title="Health Companion API",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Enable CORS for all origins (adjust for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_routes.router, prefix="/auth", tags=["Authentication"])
app.include_router(admin_routes.router, prefix="/admin", tags=["Admin"])
app.include_router(pdf_routes.router, prefix="/reports", tags=["Reports"])

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )
