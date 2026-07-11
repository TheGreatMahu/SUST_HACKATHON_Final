"""
FastAPI Application — Multi-Provider Liquidity & Anomaly System
Segment 1 bootstrap: data generation + provider isolation endpoints
"""

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

from backend.data.generator import SyntheticDataGenerator
from backend.models.data_models import Provider, ProviderFeed, AgentProfile
from backend.providers.registry import ProviderRegistry, ProviderPipeline

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = FastAPI(
    title="SuperAgent LiquidityIQ API",
    description="Multi-provider MFS agent liquidity and anomaly decision-support system",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Global state (loaded once at startup)
# ---------------------------------------------------------------------------
_registry: Optional[ProviderRegistry] = None
_raw_data: Optional[dict] = None
_ground_truth: Optional[list] = None

DATA_CACHE = Path("backend/data/generated_data.json")
GT_CACHE   = Path("backend/data/ground_truth.json")


@app.on_event("startup")
async def startup():
    global _registry, _raw_data, _ground_truth

    print("[Startup] Generating synthetic data...")
    gen = SyntheticDataGenerator()
    result = gen.generate()
    _raw_data = result

    # Cache to disk for frontend/metrics use
    DATA_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_CACHE, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)

    # Save ground truth separately (private — not exposed to UI)
    with open(GT_CACHE, "w", encoding="utf-8") as f:
        json.dump(result["ground_truth"], f, indent=2, default=str)

    _ground_truth = result["ground_truth"]

    # Build registry from generated feeds
    feeds = {
        Provider(k): ProviderFeed(**v)
        for k, v in result["provider_feeds"].items()
    }
    agents = [AgentProfile(**a) for a in result["agents"]]
    pipelines = {prov: ProviderPipeline(prov, feed) for prov, feed in feeds.items()}
    _registry = ProviderRegistry(pipelines, agents)

    print("[Startup] Registry ready.")
    print(f"[Startup] Summary: {result['summary']}")


# ---------------------------------------------------------------------------
# Routes — Segment 1
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/v1/system/health")
def system_health():
    """Provider feed health — shows if any provider data is delayed or missing."""
    if not _registry:
        return JSONResponse({"error": "system not ready"}, status_code=503)
    return _registry.health_summary()


@app.get("/api/v1/data/summary")
def data_summary():
    """Simulation summary — transaction counts, ground truth event count."""
    if not _raw_data:
        return JSONResponse({"error": "data not ready"}, status_code=503)
    return _raw_data["summary"]


@app.get("/api/v1/agents")
def list_agents(area: Optional[str] = Query(None, description="Filter by area name")):
    """List all agents with combined provider view (balances always kept separate)."""
    if not _registry:
        return JSONResponse({"error": "system not ready"}, status_code=503)
    return _registry.get_area_overview(area)


@app.get("/api/v1/agents/{agent_id}")
def get_agent(agent_id: str):
    """Combined view for a single agent — shared cash + separate provider balances."""
    if not _registry:
        return JSONResponse({"error": "system not ready"}, status_code=503)
    view = _registry.get_combined_agent_view(agent_id)
    if not view:
        return JSONResponse({"error": "agent not found"}, status_code=404)
    return view


@app.get("/api/v1/transactions")
def get_transactions(
    provider: Optional[str] = Query(None),
    agent_id: Optional[str] = Query(None),
    since: Optional[str] = Query(None, description="ISO datetime"),
    until: Optional[str] = Query(None, description="ISO datetime"),
    limit: int = Query(200, le=1000),
):
    """Query transactions with optional provider/agent/time filters."""
    if not _registry:
        return JSONResponse({"error": "system not ready"}, status_code=503)

    prov = Provider(provider) if provider else None
    since_dt = datetime.fromisoformat(since) if since else None
    until_dt = datetime.fromisoformat(until) if until else None

    txns = _registry.get_all_transactions(prov, agent_id, since_dt, until_dt)
    txns = txns[:limit]

    return {
        "count": len(txns),
        "transactions": [t.model_dump(mode="json") for t in txns],
    }


@app.get("/api/v1/providers/{provider_id}/balances")
def get_provider_balances(provider_id: str):
    """Provider-specific balances — only that provider's data returned."""
    if not _registry:
        return JSONResponse({"error": "system not ready"}, status_code=503)
    try:
        prov = Provider(provider_id)
    except ValueError:
        return JSONResponse({"error": f"unknown provider: {provider_id}"}, status_code=400)

    pipeline = _registry.get_pipeline(prov)
    agents = pipeline.all_agents_in_feed
    balances = [pipeline.get_agent_balance(a) for a in agents if pipeline.get_agent_balance(a)]

    return {
        "provider": provider_id,
        "feed_healthy": pipeline.is_healthy,
        "delay_seconds": pipeline.delay_seconds,
        "balances": [b.model_dump(mode="json") for b in balances],
    }


# NOTE: Ground truth is intentionally NOT exposed via API.
# It is only read by the validation/metrics module in Segment 6.
