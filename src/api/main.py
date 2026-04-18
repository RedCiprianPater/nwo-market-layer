"""
NWO Market Layer 6 — FastAPI application.

Can be run standalone on port 8006, or mounted into the Layer 5 gateway.

── Mounting into Layer 5 ────────────────────────────────────────────────────
In your Layer 5 src/api/main.py, add:

    from nwo_market_layer6.src.api.main import market_app
    app.mount("/", market_app)

Or, if running as a separate service, point the Layer 5 gateway to it:
    LAYER6_URL=http://localhost:8006

Then proxy /v1/market/* from Layer 5 → Layer 6.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..assembly_ai.cache import init_cache
from .routes import router

market_app = FastAPI(
    title="NWO Market — Layer 6",
    description=(
        "Market features for NWO Robotics: "
        "on-chain identity (Cardiac SDK + Base Mainnet), "
        "physics simulation (nwo-simulation-api), "
        "Assembly AI (Claude BOM + steps), "
        "token economy (NWOPaymentProcessor settlement)."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

market_app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

market_app.include_router(router)


@market_app.on_event("startup")
async def startup() -> None:
    """Initialise the assembly instruction cache on startup."""
    try:
        await init_cache()
    except Exception as e:
        print(f"[WARN] Cache init: {e}")


@market_app.get("/health", tags=["System"])
async def root_health():
    return {"status": "ok", "service": "nwo-market-layer6", "version": "0.1.0"}


@market_app.get("/", tags=["System"])
async def root():
    return {
        "service":    "NWO Market Layer 6",
        "version":    "0.1.0",
        "docs":       "/docs",
        "endpoints": {
            "identity":   "/v1/market/identity/*",
            "simulation": "/v1/market/simulate",
            "assembly":   "/v1/market/assembly/*",
            "tokens":     "/v1/market/tokens/*",
        },
        "contracts": {
            "NWOIdentityRegistry": os.getenv("NWO_IDENTITY_REGISTRY"),
            "NWOPaymentProcessor": os.getenv("NWO_PAYMENT_PROCESSOR"),
            "chain_id": 8453,
            "network":  "Base Mainnet",
        },
    }
