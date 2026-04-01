"""
VerifiAgent — Adversarial Verification as a Product.

SecurityMonitor + VerificationSpecialist + DreamConsolidation
as a hosted API and GitHub App.

Run: uvicorn app:app --host 127.0.0.1 --port 8003
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routes import verify, webhooks


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Graceful startup and shutdown."""
    # Startup
    print(f"VerifiAgent v{settings.version} starting...")
    print(f"  Scratch dir: {settings.scratch_dir}")
    print(f"  Memory dir: {settings.memory_dir}")
    print(f"  GitHub App ID: {settings.github_app_id or 'not configured'}")

    yield

    # Shutdown
    print("VerifiAgent shutting down...")


app = FastAPI(
    title="VerifiAgent",
    description="Adversarial Verification as a Product",
    version=settings.version,
    lifespan=lifespan,
)

# CORS for API access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(verify.router)
app.include_router(webhooks.router)


@app.get("/")
async def root():
    return {
        "service": "VerifiAgent",
        "version": settings.version,
        "docs": "/docs",
        "health": "/verify/health",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
