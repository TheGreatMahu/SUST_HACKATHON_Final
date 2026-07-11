"""
Segment 2: Alert & Analytics Models
=====================================
Pydantic models for analytics output — liquidity projections, anomaly alerts,
and the unified SystemAlert envelope.

These models are the contract between:
  - Segment 2 (analytics engine) — produces them
  - Segment 3 (LLM narration) — reads them to generate bilingual text
  - Segment 4 (case workflow) — wraps them in a trackable case
  - Segment 5 (dashboard) — renders them in the UI

Design principle: every alert carries confidence + evidence + classification.
No bare "risk: high" badges.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
import uuid


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ConfidenceLevel(str, Enum):
    """How much we trust the output — degrades when data is stale or missing."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AlertType(str, Enum):
    """
    Three-way classification — the key differentiator.
    Most teams will only do binary (normal/anomaly). We explicitly separate:
      - Operational demand spikes (likely normal)
      - Data quality issues (feed delay, conflict)
      - Patterns requiring human review (unusual activity)
    """
    LIQUIDITY_SHORTAGE = "liquidity_shortage"
    STRUCTURING_PATTERN = "structuring_pattern"
    VOLUME_SPIKE_NORMAL = "volume_spike_normal"       # Elevated demand — likely normal
    VOLUME_SPIKE_REVIEW = "volume_spike_review"       # Unusual activity — requires review
    FEED_DEGRADED = "feed_degraded"                   # Data quality issue


class AlertSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class AlertClassification(str, Enum):
    """
    The three-way distinction the problem statement explicitly requires:
    "help users distinguish operational demand spikes, data-quality problems,
     and patterns requiring review."
    """
    LIKELY_NORMAL = "likely_normal"          # Elevated seasonal demand
    DATA_QUALITY_ISSUE = "data_quality_issue"  # Feed delay, stale, conflicting
    REQUIRES_REVIEW = "requires_review"      # Unusual activity, needs human review


# ---------------------------------------------------------------------------
# Liquidity Projection
# ---------------------------------------------------------------------------

class LiquidityProjection(BaseModel):
    """
    Per-agent, per-provider (or shared-cash) liquidity projection.

    Shows:
      - How fast cash/e-money is draining
      - When it will run out
      - How confident we are (degrades with stale data)
      - The evidence behind the projection
    """
    agent_id: str
    agent_name: str = ""
    provider: Optional[str] = None   # None = shared physical cash
    balance_type: str = Field(..., description="'shared_cash' or provider name")
    current_balance: float
    velocity_per_hour: float = Field(..., description="Net outflow in BDT/hour (positive = draining)")
    minutes_remaining: Optional[float] = Field(None, description="Estimated minutes until depletion. None if not draining.")
    confidence: ConfidenceLevel
    confidence_reason: str = ""
    severity: AlertSeverity = AlertSeverity.INFO
    evidence: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Anomaly Alert
# ---------------------------------------------------------------------------

class AnomalyAlert(BaseModel):
    """
    A detected anomaly pattern with full evidence and classification.

    CRITICAL: uses "unusual activity" language, NEVER "fraud".
    Every alert includes the literal numbers that triggered it.
    """
    alert_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    alert_type: AlertType
    classification: AlertClassification
    provider: str
    agent_id: str
    agent_name: str = ""
    severity: AlertSeverity
    confidence: ConfidenceLevel
    confidence_reason: str = ""

    # The literal evidence that triggered the flag
    evidence: dict = Field(
        default_factory=dict,
        description="Literal numbers: txn_count, unique_accounts, amount_spread, "
                    "time_window_minutes, z_score, etc."
    )

    # Human-readable summary (filled by Segment 3 LLM narration)
    summary_en: str = ""
    summary_bn: str = ""
    summary_banglish: str = ""

    # Recommended action — always a human action
    recommended_action: str = ""

    # Disclaimer — baked into every alert
    disclaimer: str = "This is not a final determination. Human review is required before any action."

    time_window_start: Optional[datetime] = None
    time_window_end: Optional[datetime] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Unified System Alert (envelope for both liquidity and anomaly)
# ---------------------------------------------------------------------------

class SystemAlert(BaseModel):
    """
    Unified alert envelope — wraps either a liquidity projection or anomaly alert.
    This is what the case workflow (Segment 4) and dashboard (Segment 5) consume.
    """
    alert_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    alert_type: AlertType
    classification: AlertClassification
    severity: AlertSeverity
    confidence: ConfidenceLevel
    provider: str
    agent_id: str
    agent_name: str = ""

    # Core content
    title: str
    summary: str
    evidence: dict = Field(default_factory=dict)
    recommended_action: str = ""
    disclaimer: str = "This is not a final determination. Human review is required before any action."

    # Source data
    liquidity_projection: Optional[LiquidityProjection] = None
    anomaly_alert: Optional[AnomalyAlert] = None

    timestamp: datetime = Field(default_factory=datetime.utcnow)
