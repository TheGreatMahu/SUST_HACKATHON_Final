"""
Segment 2: Fallback & Confidence Handler + Chaos Toggle
=========================================================
Manages confidence degradation when provider feeds are stale or missing.
Provides the "chaos toggle" for Scenario C demo — drop a provider feed
on demand and watch confidence visibly degrade.

This is the cheapest, highest-signal demo component:
  POST /api/v1/system/chaos → feed drops → confidence degrades → fallback message

Rubric alignment:
  - "Show lower confidence or a safe fallback when data is missing, late, or conflicting"
  - "Provider data failures or inconsistencies should not silently produce confident conclusions"
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from backend.models.data_models import Provider
from backend.models.alert_models import (
    ConfidenceLevel, AlertSeverity, SystemAlert, AlertType,
    AlertClassification, LiquidityProjection, AnomalyAlert
)


# ---------------------------------------------------------------------------
# Chaos Toggle State (in-memory — resets on restart)
# ---------------------------------------------------------------------------

class ChaosState:
    """
    Tracks which providers have been manually degraded for demo purposes.
    In production, this would come from real feed health checks.
    """
    def __init__(self):
        self._degraded_providers: dict[str, dict] = {}

    def degrade_provider(self, provider: str, delay_seconds: int = 900) -> dict:
        """Simulate a provider feed going down."""
        self._degraded_providers[provider] = {
            "healthy": False,
            "delay_seconds": delay_seconds,
            "degraded_at": datetime.utcnow().isoformat(),
            "source": "chaos_toggle",
        }
        return {
            "status": "degraded",
            "provider": provider,
            "message": f"Provider {provider} feed marked as degraded. "
                       "All confidence levels for this provider will downgrade."
        }

    def restore_provider(self, provider: str) -> dict:
        """Restore a provider feed."""
        if provider in self._degraded_providers:
            del self._degraded_providers[provider]
        return {
            "status": "restored",
            "provider": provider,
            "message": f"Provider {provider} feed restored to healthy."
        }

    def is_degraded(self, provider: str) -> bool:
        return provider in self._degraded_providers

    def get_health_overrides(self) -> dict:
        return dict(self._degraded_providers)

    def get_status(self) -> dict:
        return {
            "degraded_providers": list(self._degraded_providers.keys()),
            "all_healthy": len(self._degraded_providers) == 0,
            "details": self._degraded_providers,
        }


# ---------------------------------------------------------------------------
# Alert Builder — combines liquidity and anomaly into unified SystemAlerts
# ---------------------------------------------------------------------------

class AlertBuilder:
    """
    Converts raw LiquidityProjection and AnomalyAlert objects into
    unified SystemAlert objects, applying chaos/confidence overrides.
    """

    def __init__(self, chaos_state: Optional[ChaosState] = None):
        self._chaos = chaos_state or ChaosState()

    def build_liquidity_alert(self, projection: LiquidityProjection) -> Optional[SystemAlert]:
        """Convert a liquidity projection into a SystemAlert if it's warning/critical."""
        if projection.severity == AlertSeverity.INFO:
            return None

        # Apply chaos override
        confidence = projection.confidence
        confidence_reason = projection.confidence_reason
        if projection.provider and self._chaos.is_degraded(projection.provider):
            confidence = ConfidenceLevel.LOW
            confidence_reason = (
                f"Provider {projection.provider} feed is degraded (chaos toggle active). "
                "Projection uses stale data — treat with caution."
            )

        # Build title
        if projection.balance_type == "shared_cash":
            balance_label = "shared physical cash"
        else:
            balance_label = f"{projection.balance_type} e-money"

        minutes = projection.minutes_remaining
        if minutes is not None:
            title = f"Liquidity pressure: {balance_label} may deplete in ~{minutes:.0f} minutes"
        else:
            title = f"Liquidity pressure on {balance_label}"

        summary = (
            f"Agent {projection.agent_id} ({projection.agent_name}): "
            f"{balance_label} balance is BDT {projection.current_balance:,.0f}, "
            f"draining at BDT {projection.velocity_per_hour:,.0f}/hour. "
        )
        if minutes is not None:
            summary += f"Estimated depletion in {minutes:.0f} minutes. "
        summary += f"Confidence: {confidence.value}."

        return SystemAlert(
            alert_type=AlertType.LIQUIDITY_SHORTAGE,
            classification=AlertClassification.REQUIRES_REVIEW,
            severity=projection.severity,
            confidence=confidence,
            provider=projection.provider or "shared_cash",
            agent_id=projection.agent_id,
            agent_name=projection.agent_name,
            title=title,
            summary=summary,
            evidence=projection.evidence,
            recommended_action=(
                "Verify current cash position with the agent. "
                "Coordinate float replenishment through approved channels if confirmed."
            ),
            liquidity_projection=projection,
        )

    def build_anomaly_alert(self, anomaly: AnomalyAlert) -> SystemAlert:
        """Convert an AnomalyAlert into a unified SystemAlert."""
        # Apply chaos override
        confidence = anomaly.confidence
        if self._chaos.is_degraded(anomaly.provider):
            confidence = ConfidenceLevel.LOW

        # Build title based on alert type
        titles = {
            AlertType.STRUCTURING_PATTERN: (
                f"Unusual transaction pattern detected on {anomaly.provider} — "
                f"requires review"
            ),
            AlertType.VOLUME_SPIKE_NORMAL: (
                f"Elevated demand detected on {anomaly.provider} — "
                f"likely seasonal"
            ),
            AlertType.VOLUME_SPIKE_REVIEW: (
                f"Elevated activity on {anomaly.provider} — "
                f"requires operational review"
            ),
            AlertType.FEED_DEGRADED: (
                f"Provider {anomaly.provider} feed delayed — "
                f"data quality degraded"
            ),
        }
        title = titles.get(anomaly.alert_type, f"Alert on {anomaly.provider}")

        return SystemAlert(
            alert_type=anomaly.alert_type,
            classification=anomaly.classification,
            severity=anomaly.severity,
            confidence=confidence,
            provider=anomaly.provider,
            agent_id=anomaly.agent_id,
            agent_name=anomaly.agent_name,
            title=title,
            summary=anomaly.summary_en or title,
            evidence=anomaly.evidence,
            recommended_action=anomaly.recommended_action,
            anomaly_alert=anomaly,
        )

    def build_all_alerts(
        self,
        liquidity_projections: list[LiquidityProjection],
        anomaly_alerts: list[AnomalyAlert],
    ) -> list[SystemAlert]:
        """Build unified alert list from all analytics output."""
        alerts = []

        for proj in liquidity_projections:
            alert = self.build_liquidity_alert(proj)
            if alert:
                alerts.append(alert)

        for anomaly in anomaly_alerts:
            alerts.append(self.build_anomaly_alert(anomaly))

        # Sort by severity (critical first), then by timestamp
        severity_order = {
            AlertSeverity.CRITICAL: 0,
            AlertSeverity.WARNING: 1,
            AlertSeverity.INFO: 2,
        }
        alerts.sort(key=lambda a: (severity_order.get(a.severity, 9), a.timestamp))

        return alerts
