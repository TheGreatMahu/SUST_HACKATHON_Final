"""
FastAPI Application — Multi-Provider Liquidity & Anomaly System
Segment 1: data generation + provider isolation endpoints
Segment 2: analytics engine — liquidity projection, anomaly detection, chaos toggle
Segment 3: LLM narration layer — bilingual alerts, stakeholder-specific framing
Segment 4: case & coordination workflow — lifecycle, audit trail, escalation
Segment 6: validation, metrics, and demo endpoints
"""

from contextlib import asynccontextmanager
import time

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

from backend.data.generator import SyntheticDataGenerator, SIM_END
from backend.models.data_models import Provider, ProviderFeed, AgentProfile
from backend.providers.registry import ProviderRegistry, ProviderPipeline

# Segment 2 imports
from backend.analytics.liquidity import LiquidityProjector
from backend.analytics.anomaly import AnomalyDetector
from backend.analytics.fallback import ChaosState, AlertBuilder

# Segment 3 imports
from backend.narration import NarrationEngine

# Segment 4 imports
from backend.workflow import CaseManager, CaseStatus, StakeholderRole

# Segment 6 imports
from backend.validation import ValidationEngine, LatencyMetrics



# ---------------------------------------------------------------------------
# Global state (loaded once at startup)
# ---------------------------------------------------------------------------
_registry: Optional[ProviderRegistry] = None
_raw_data: Optional[dict] = None
_ground_truth: Optional[list] = None

# Segment 2 — analytics state
_liquidity_projector: Optional[LiquidityProjector] = None
_anomaly_detector: Optional[AnomalyDetector] = None
_chaos_state: ChaosState = ChaosState()
_alert_builder: Optional[AlertBuilder] = None
_sim_end_time: Optional[datetime] = None

# Segment 3 — narration state
_narration_engine: Optional[NarrationEngine] = None

# Segment 4 — case workflow state
_case_manager: CaseManager = CaseManager()

# Segment 6 — validation/metrics state
_latency_metrics: LatencyMetrics = LatencyMetrics()
_validation_report: Optional[dict] = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_CACHE = PROJECT_ROOT / "backend" / "data" / "generated_data.json"
GT_CACHE = PROJECT_ROOT / "backend" / "data" / "ground_truth.json"



@asynccontextmanager
async def lifespan(application: FastAPI):
    """Application lifespan — initializes all segments on startup."""
    global _registry, _raw_data, _ground_truth
    global _liquidity_projector, _anomaly_detector, _alert_builder, _sim_end_time
    global _narration_engine

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

    # Segment 2 — initialize analytics engine
    _liquidity_projector = LiquidityProjector(_registry)
    _anomaly_detector = AnomalyDetector(_registry)
    _alert_builder = AlertBuilder(_chaos_state)
    _sim_end_time = SIM_END

    # Segment 3 — initialize narration engine
    _narration_engine = NarrationEngine()

    print("[Startup] Registry ready.")
    print("[Startup] Analytics engine initialized.")
    print(f"[Startup] Narration mode: {_narration_engine.mode}")
    print(f"[Startup] Summary: {result['summary']}")

    yield  # Application runs here

    # Shutdown logic (if needed)
    print("[Shutdown] Application shutting down.")


# ---------------------------------------------------------------------------
# App setup (MUST come after lifespan definition)
# ---------------------------------------------------------------------------
app = FastAPI(
    title="SuperAgent LiquidityIQ API",
    description="Multi-provider MFS agent liquidity and anomaly decision-support system",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routes — Segment 1: Data & Provider Isolation
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    frontend_path = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
    return FileResponse(frontend_path)


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/v1/system/health")
def system_health():
    """Provider feed health — shows if any provider data is delayed or missing."""
    if not _registry:
        return JSONResponse({"error": "system not ready"}, status_code=503)
    health_data = _registry.health_summary()
    # Include chaos state
    health_data["chaos_state"] = _chaos_state.get_status()
    return health_data


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


# ---------------------------------------------------------------------------
# Routes — Segment 2: Analytics Engine
# ---------------------------------------------------------------------------

@app.get("/api/v1/analytics/liquidity")
def get_all_liquidity():
    """Liquidity projections for all agents — time-to-depletion with confidence."""
    if not _liquidity_projector:
        return JSONResponse({"error": "analytics not ready"}, status_code=503)

    projections = _liquidity_projector.project_all_agents(
        reference_time=_sim_end_time,
        feed_health=_chaos_state.get_health_overrides(),
    )
    return {
        "count": len(projections),
        "projections": [p.model_dump(mode="json") for p in projections],
    }


@app.get("/api/v1/analytics/liquidity/{agent_id}")
def get_agent_liquidity(agent_id: str):
    """Liquidity projection for a single agent — shared cash + per-provider."""
    if not _liquidity_projector or not _registry:
        return JSONResponse({"error": "analytics not ready"}, status_code=503)

    agent = _registry.get_agent(agent_id)
    if not agent:
        return JSONResponse({"error": "agent not found"}, status_code=404)

    projections = _liquidity_projector.project_agent(
        agent,
        reference_time=_sim_end_time,
        feed_health=_chaos_state.get_health_overrides(),
    )
    return {
        "agent_id": agent_id,
        "projections": [p.model_dump(mode="json") for p in projections],
    }


@app.get("/api/v1/analytics/anomalies")
def get_all_anomalies():
    """All detected anomalies across all agents and providers."""
    if not _anomaly_detector:
        return JSONResponse({"error": "analytics not ready"}, status_code=503)

    anomalies = _anomaly_detector.detect_all(
        reference_time=_sim_end_time,
        feed_health=_chaos_state.get_health_overrides(),
    )
    return {
        "count": len(anomalies),
        "anomalies": [a.model_dump(mode="json") for a in anomalies],
    }


@app.get("/api/v1/analytics/anomalies/{agent_id}")
def get_agent_anomalies(agent_id: str):
    """Anomalies detected for a single agent."""
    if not _anomaly_detector:
        return JSONResponse({"error": "analytics not ready"}, status_code=503)

    anomalies = _anomaly_detector.detect_for_agent(
        agent_id,
        reference_time=_sim_end_time,
    )
    return {
        "agent_id": agent_id,
        "count": len(anomalies),
        "anomalies": [a.model_dump(mode="json") for a in anomalies],
    }


@app.get("/api/v1/analytics/alerts")
def get_all_alerts():
    """
    Combined alerts — liquidity shortages + anomaly detections.
    Sorted by severity (critical first). Every alert carries:
      - Confidence level
      - Classification (likely_normal / data_quality_issue / requires_review)
      - Evidence (the literal numbers that triggered it)
      - Recommended action
      - Human-review disclaimer
    """
    if not _liquidity_projector or not _anomaly_detector or not _alert_builder:
        return JSONResponse({"error": "analytics not ready"}, status_code=503)

    feed_health = _chaos_state.get_health_overrides()

    # Get shortage-level liquidity alerts only
    liquidity = _liquidity_projector.get_shortage_alerts(
        reference_time=_sim_end_time,
        feed_health=feed_health,
    )

    anomalies = _anomaly_detector.detect_all(
        reference_time=_sim_end_time,
        feed_health=feed_health,
    )

    alerts = _alert_builder.build_all_alerts(liquidity, anomalies)

    return {
        "count": len(alerts),
        "alerts": [a.model_dump(mode="json") for a in alerts],
        "chaos_active": not _chaos_state.get_status()["all_healthy"],
    }


# ---------------------------------------------------------------------------
# Routes — Segment 2: Chaos Toggle (Scenario C demo)
# ---------------------------------------------------------------------------

@app.post("/api/v1/system/chaos/degrade/{provider_id}")
def chaos_degrade(provider_id: str, delay_seconds: int = Query(900)):
    """
    Chaos toggle: simulate a provider feed going down.
    Immediately degrades confidence on all alerts for this provider.
    Use this for Scenario C demo — flip the switch and watch confidence drop.
    """
    try:
        prov = Provider(provider_id)
    except ValueError:
        return JSONResponse({"error": f"unknown provider: {provider_id}"}, status_code=400)

    result = _chaos_state.degrade_provider(prov.value, delay_seconds)
    return result


@app.post("/api/v1/system/chaos/restore/{provider_id}")
def chaos_restore(provider_id: str):
    """Restore a previously degraded provider feed."""
    try:
        prov = Provider(provider_id)
    except ValueError:
        return JSONResponse({"error": f"unknown provider: {provider_id}"}, status_code=400)

    result = _chaos_state.restore_provider(prov.value)
    return result


@app.get("/api/v1/system/chaos/status")
def chaos_status():
    """Current chaos toggle state — which providers are degraded."""
    return _chaos_state.get_status()


# ---------------------------------------------------------------------------
# Routes — Segment 3: LLM Narration Layer
# ---------------------------------------------------------------------------

@app.get("/api/v1/narration/alert/{alert_index}")
def narrate_alert(alert_index: int = 0):
    """
    Generate bilingual narration (Bangla/Banglish/English) for an alert.
    Uses LLM when API key is available, template fallback otherwise.
    """
    if not _narration_engine or not _alert_builder:
        return JSONResponse({"error": "narration not ready"}, status_code=503)

    feed_health = _chaos_state.get_health_overrides()
    liquidity = _liquidity_projector.get_shortage_alerts(
        reference_time=_sim_end_time, feed_health=feed_health,
    )
    anomalies = _anomaly_detector.detect_all(
        reference_time=_sim_end_time, feed_health=feed_health,
    )
    alerts = _alert_builder.build_all_alerts(liquidity, anomalies)

    if alert_index >= len(alerts):
        return JSONResponse({"error": f"alert index {alert_index} out of range (total: {len(alerts)})"}, status_code=404)

    alert = alerts[alert_index]
    narration = _narration_engine.narrate(alert)

    return {
        "alert_id": alert.alert_id,
        "alert_type": alert.alert_type.value,
        "provider": alert.provider,
        "agent_id": alert.agent_id,
        "narration": narration,
    }


@app.get("/api/v1/narration/alert/{alert_index}/stakeholder/{role}")
def narrate_for_stakeholder(alert_index: int = 0, role: str = "agent"):
    """
    Generate stakeholder-specific narration:
      - agent: Bangla/Banglish, supportive tone, focus on cash availability
      - field_officer: mixed language, coordination focus
      - compliance_analyst: English, statistical evidence, escalation checklist
    """
    if not _narration_engine or not _alert_builder:
        return JSONResponse({"error": "narration not ready"}, status_code=503)

    feed_health = _chaos_state.get_health_overrides()
    liquidity = _liquidity_projector.get_shortage_alerts(
        reference_time=_sim_end_time, feed_health=feed_health,
    )
    anomalies = _anomaly_detector.detect_all(
        reference_time=_sim_end_time, feed_health=feed_health,
    )
    alerts = _alert_builder.build_all_alerts(liquidity, anomalies)

    if alert_index >= len(alerts):
        return JSONResponse({"error": f"alert index {alert_index} out of range"}, status_code=404)

    valid_roles = ["agent", "field_officer", "compliance_analyst"]
    if role not in valid_roles:
        return JSONResponse({"error": f"role must be one of {valid_roles}"}, status_code=400)

    alert = alerts[alert_index]
    framing = _narration_engine.narrate_for_stakeholder(alert, role)

    return {
        "alert_id": alert.alert_id,
        "role": role,
        "framing": framing,
    }


@app.get("/api/v1/narration/mode")
def narration_mode():
    """Check current narration mode — 'llm' or 'template'."""
    return {
        "mode": _narration_engine.mode if _narration_engine else "not_initialized",
    }


# ---------------------------------------------------------------------------
# Routes — Segment 4: Case & Coordination Workflow
# ---------------------------------------------------------------------------

@app.get("/api/v1/cases")
def list_cases(
    status: Optional[str] = Query(None, description="Filter by status"),
    provider: Optional[str] = Query(None, description="Filter by provider"),
    agent_id: Optional[str] = Query(None, description="Filter by agent"),
):
    """List all cases with optional filters."""
    cases = _case_manager.all_cases
    if status:
        cases = [c for c in cases if c.status.value == status]
    if provider:
        cases = [c for c in cases if c.provider == provider]
    if agent_id:
        cases = [c for c in cases if c.agent_id == agent_id]

    return {
        "count": len(cases),
        "cases": [c.model_dump(mode="json") for c in cases],
    }


@app.get("/api/v1/cases/summary")
def cases_summary():
    """Case board overview — counts by status, open critical cases."""
    return _case_manager.get_summary()


@app.get("/api/v1/cases/{case_id}")
def get_case(case_id: str):
    """Get a single case with full audit trail."""
    case = _case_manager.get_case(case_id)
    if not case:
        return JSONResponse({"error": f"case {case_id} not found"}, status_code=404)
    return case.model_dump(mode="json")


@app.post("/api/v1/cases/create-from-alerts")
def create_cases_from_alerts():
    """
    Create cases from all current alerts.
    Each alert gets narrated (Segment 3) and wrapped in a trackable case (Segment 4).
    """
    if not _alert_builder or not _narration_engine:
        return JSONResponse({"error": "system not ready"}, status_code=503)

    feed_health = _chaos_state.get_health_overrides()
    liquidity = _liquidity_projector.get_shortage_alerts(
        reference_time=_sim_end_time, feed_health=feed_health,
    )
    anomalies = _anomaly_detector.detect_all(
        reference_time=_sim_end_time, feed_health=feed_health,
    )
    alerts = _alert_builder.build_all_alerts(liquidity, anomalies)

    # Narrate each alert
    narrations = _narration_engine.narrate_batch(alerts)

    # Create cases
    alert_dicts = [a.model_dump(mode="json") for a in alerts]
    cases = _case_manager.create_cases_from_alerts(alert_dicts, narrations)

    return {
        "created": len(cases),
        "cases": [c.model_dump(mode="json") for c in cases],
    }


@app.post("/api/v1/cases/{case_id}/assign")
def assign_case(
    case_id: str,
    role: str = Query("field_officer", description="Stakeholder role to assign"),
):
    """Assign a case to a stakeholder role."""
    try:
        owner_role = StakeholderRole(role)
    except ValueError:
        valid = [r.value for r in StakeholderRole]
        return JSONResponse({"error": f"role must be one of {valid}"}, status_code=400)

    case = _case_manager.assign_case(case_id, owner_role)
    if not case:
        return JSONResponse({"error": f"case {case_id} not found"}, status_code=404)
    return case.model_dump(mode="json")


@app.post("/api/v1/cases/{case_id}/acknowledge")
def acknowledge_case(case_id: str):
    """Mark a case as acknowledged by its current owner."""
    case = _case_manager.get_case(case_id)
    if not case:
        return JSONResponse({"error": f"case {case_id} not found"}, status_code=404)

    owner_id = case.current_owner_id or "SYSTEM"
    owner_role = case.current_owner_role or StakeholderRole.FIELD_OFFICER

    updated = _case_manager.acknowledge_case(case_id, owner_id, owner_role)
    return updated.model_dump(mode="json")


@app.post("/api/v1/cases/{case_id}/escalate")
def escalate_case(
    case_id: str,
    reason: str = Query("", description="Reason for escalation"),
):
    """Escalate a case to the next level in the hierarchy."""
    case = _case_manager.get_case(case_id)
    if not case:
        return JSONResponse({"error": f"case {case_id} not found"}, status_code=404)

    actor_id = case.current_owner_id or "SYSTEM"
    actor_role = case.current_owner_role or StakeholderRole.FIELD_OFFICER

    updated = _case_manager.escalate_case(case_id, actor_id, actor_role, reason)
    return updated.model_dump(mode="json")


@app.post("/api/v1/cases/{case_id}/resolve")
def resolve_case(
    case_id: str,
    note: str = Query("", description="Resolution note"),
):
    """Resolve a case with a closure note."""
    case = _case_manager.get_case(case_id)
    if not case:
        return JSONResponse({"error": f"case {case_id} not found"}, status_code=404)

    actor_id = case.current_owner_id or "SYSTEM"
    actor_role = case.current_owner_role or StakeholderRole.FIELD_OFFICER

    updated = _case_manager.resolve_case(case_id, actor_id, actor_role, note)
    return updated.model_dump(mode="json")


@app.post("/api/v1/cases/{case_id}/note")
def add_case_note(
    case_id: str,
    note: str = Query(..., description="Note text"),
    role: str = Query("field_officer", description="Actor role"),
):
    """Add a note to a case without changing its status."""
    case = _case_manager.get_case(case_id)
    if not case:
        return JSONResponse({"error": f"case {case_id} not found"}, status_code=404)

    try:
        actor_role = StakeholderRole(role)
    except ValueError:
        actor_role = StakeholderRole.FIELD_OFFICER

    actor_id = case.current_owner_id or "SYSTEM"
    updated = _case_manager.add_note(case_id, actor_id, actor_role, note)
    return updated.model_dump(mode="json")


@app.get("/api/v1/cases/{case_id}/audit")
def get_case_audit(case_id: str):
    """Get the full audit trail for a case."""
    case = _case_manager.get_case(case_id)
    if not case:
        return JSONResponse({"error": f"case {case_id} not found"}, status_code=404)

    return {
        "case_id": case_id,
        "status": case.status.value,
        "audit_trail": [e.model_dump(mode="json") for e in case.audit_trail],
        "notification_log": case.notification_log,
    }


# ---------------------------------------------------------------------------
# Middleware — Segment 6: Latency Tracking
# ---------------------------------------------------------------------------

@app.middleware("http")
async def latency_tracking_middleware(request: Request, call_next):
    """Record response time for every API call."""
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    _latency_metrics.record(request.url.path, elapsed_ms)
    response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.2f}"
    return response


# ---------------------------------------------------------------------------
# Routes — Segment 6: Validation & Metrics
# ---------------------------------------------------------------------------

@app.get("/api/v1/metrics/validation")
def run_validation():
    """
    Run the full validation report — compares analytics output against ground truth.
    Returns precision/recall/F1, false-positive rates, narration safety, and workflow audit.
    """
    global _validation_report

    if not _alert_builder or not _narration_engine or not _ground_truth:
        return JSONResponse({"error": "system not ready"}, status_code=503)

    feed_health = _chaos_state.get_health_overrides()

    # Get all analytics output
    liquidity = _liquidity_projector.get_shortage_alerts(
        reference_time=_sim_end_time, feed_health=feed_health,
    )
    all_projections = _liquidity_projector.project_all_agents(
        reference_time=_sim_end_time, feed_health=feed_health,
    )
    anomalies = _anomaly_detector.detect_all(
        reference_time=_sim_end_time, feed_health=feed_health,
    )
    alerts = _alert_builder.build_all_alerts(liquidity, anomalies)

    # Narrate all alerts
    narrations = _narration_engine.narrate_batch(alerts)

    # Create cases if none exist
    if not _case_manager.all_cases:
        alert_dicts = [a.model_dump(mode="json") for a in alerts]
        _case_manager.create_cases_from_alerts(alert_dicts, narrations)

    # Run validation
    engine = ValidationEngine(
        ground_truth=_ground_truth,
        alerts=alerts,
        projections=all_projections,
        narrations=narrations,
        cases=_case_manager.all_cases,
        reference_time=_sim_end_time,
        latency_metrics=_latency_metrics,
    )

    _validation_report = engine.generate_report()
    return _validation_report


@app.get("/api/v1/metrics/anomaly")
def anomaly_metrics():
    """Anomaly detection precision/recall/F1 against ground truth."""
    if not _alert_builder or not _ground_truth:
        return JSONResponse({"error": "system not ready"}, status_code=503)

    feed_health = _chaos_state.get_health_overrides()
    liquidity = _liquidity_projector.get_shortage_alerts(
        reference_time=_sim_end_time, feed_health=feed_health,
    )
    anomalies = _anomaly_detector.detect_all(
        reference_time=_sim_end_time, feed_health=feed_health,
    )
    alerts = _alert_builder.build_all_alerts(liquidity, anomalies)

    from backend.validation import AnomalyMetrics
    metrics = AnomalyMetrics(_ground_truth, alerts)
    return metrics.compute()


@app.get("/api/v1/metrics/latency")
def latency_report():
    """API latency P50/P95 across all recorded endpoints."""
    return _latency_metrics.compute()


@app.get("/api/v1/metrics/narration-safety")
def narration_safety():
    """Scan all narrations for banned words and disclaimer compliance."""
    if not _alert_builder or not _narration_engine:
        return JSONResponse({"error": "system not ready"}, status_code=503)

    feed_health = _chaos_state.get_health_overrides()
    liquidity = _liquidity_projector.get_shortage_alerts(
        reference_time=_sim_end_time, feed_health=feed_health,
    )
    anomalies = _anomaly_detector.detect_all(
        reference_time=_sim_end_time, feed_health=feed_health,
    )
    alerts = _alert_builder.build_all_alerts(liquidity, anomalies)
    narrations = _narration_engine.narrate_batch(alerts)

    from backend.validation import NarrationSafetyMetrics
    metrics = NarrationSafetyMetrics(narrations)
    return metrics.compute()


@app.get("/api/v1/metrics/ground-truth")
def ground_truth_summary():
    """Ground truth events summary (for internal validation only)."""
    if not _ground_truth:
        return JSONResponse({"error": "ground truth not loaded"}, status_code=503)

    return {
        "count": len(_ground_truth),
        "events": [
            {
                "event_type": e.get("event_type"),
                "provider": e.get("provider"),
                "agent_id": e.get("agent_id"),
                "start_time": e.get("start_time"),
                "end_time": e.get("end_time"),
                "injected_txn_count": len(e.get("injected_txn_ids", [])),
            }
            for e in _ground_truth
        ],
    }

