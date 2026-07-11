"""
Segment 2: Liquidity Projector
================================
Computes per-agent, per-provider time-to-depletion for:
  - Shared physical cash (aggregate cash-out minus cash-in across all providers)
  - Per-provider e-money balance

Design:
  - Uses rolling window of transactions to compute cash velocity
  - Projects forward: minutes_remaining = current_balance / net_outflow_rate
  - Confidence degrades when provider data is stale or history is thin
  - No LLM — pure deterministic math, fully explainable

Rubric alignment:
  - "Identify provider-level and aggregate liquidity pressure before service is disrupted"
  - "Show lower confidence or a safe fallback when data is missing, late, or conflicting"
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict

from backend.models.data_models import (
    Provider, TransactionType, Transaction, AgentProfile
)
from backend.models.alert_models import (
    LiquidityProjection, ConfidenceLevel, AlertSeverity
)
from backend.providers.registry import ProviderRegistry


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Rolling window for velocity calculation (minutes)
VELOCITY_WINDOW_MINUTES = 60

# Alert thresholds (minutes remaining)
CRITICAL_THRESHOLD_MINUTES = 30
WARNING_THRESHOLD_MINUTES = 60

# Minimum transactions needed for a reliable projection
MIN_TXN_COUNT_FOR_HIGH_CONFIDENCE = 10
MIN_TXN_COUNT_FOR_MEDIUM_CONFIDENCE = 5


# ---------------------------------------------------------------------------
# Liquidity Projector
# ---------------------------------------------------------------------------

class LiquidityProjector:
    """
    Computes time-to-depletion for each agent's shared cash and per-provider
    e-money balance, based on recent transaction velocity.
    """

    def __init__(self, registry: ProviderRegistry):
        self._registry = registry

    def project_agent(
        self,
        agent: AgentProfile,
        reference_time: Optional[datetime] = None,
        feed_health: Optional[dict] = None,
    ) -> list[LiquidityProjection]:
        """
        Compute liquidity projections for a single agent.
        Returns one projection per balance type (shared cash + each provider).
        """
        if reference_time is None:
            reference_time = datetime.utcnow()

        projections = []

        # Get all transactions for this agent across all providers
        all_txns = self._registry.get_all_transactions(agent_id=agent.agent_id)
        window_start = reference_time - timedelta(minutes=VELOCITY_WINDOW_MINUTES)

        # ----- 1. Shared physical cash projection -----
        cash_projection = self._project_shared_cash(
            agent, all_txns, window_start, reference_time, feed_health
        )
        projections.append(cash_projection)

        # ----- 2. Per-provider e-money projection -----
        for prov in agent.active_providers:
            pipeline = self._registry.get_pipeline(prov)
            prov_txns = pipeline.get_transactions(agent_id=agent.agent_id)

            emoney_projection = self._project_provider_emoney(
                agent, prov, prov_txns, window_start, reference_time,
                is_healthy=pipeline.is_healthy,
                delay_seconds=pipeline.delay_seconds,
            )
            projections.append(emoney_projection)

        return projections

    def project_all_agents(
        self,
        reference_time: Optional[datetime] = None,
        feed_health: Optional[dict] = None,
    ) -> list[LiquidityProjection]:
        """Compute liquidity projections for all agents."""
        projections = []
        for agent in self._registry.list_agents():
            projections.extend(
                self.project_agent(agent, reference_time, feed_health)
            )
        return projections

    def get_shortage_alerts(
        self,
        reference_time: Optional[datetime] = None,
        feed_health: Optional[dict] = None,
    ) -> list[LiquidityProjection]:
        """Return only projections that indicate a shortage (WARNING or CRITICAL)."""
        all_proj = self.project_all_agents(reference_time, feed_health)
        return [
            p for p in all_proj
            if p.severity in (AlertSeverity.CRITICAL, AlertSeverity.WARNING)
        ]

    # ------------------------------------------------------------------
    # Internal: shared cash projection
    # ------------------------------------------------------------------

    def _project_shared_cash(
        self,
        agent: AgentProfile,
        all_txns: list[Transaction],
        window_start: datetime,
        reference_time: datetime,
        feed_health: Optional[dict] = None,
    ) -> LiquidityProjection:
        """
        Shared cash = physical cash drawer.
        Net flow = cash_in adds cash, cash_out drains cash.
        """
        # Filter to transactions in the rolling window
        window_txns = [
            t for t in all_txns
            if window_start <= t.timestamp <= reference_time
            and t.status.value == "success"
        ]

        # Compute net cash flow
        cash_in = sum(t.amount for t in window_txns if t.txn_type == TransactionType.CASH_IN)
        cash_out = sum(
            t.amount for t in window_txns
            if t.txn_type in (TransactionType.CASH_OUT, TransactionType.SEND_MONEY)
        )
        net_outflow = cash_out - cash_in  # positive = draining

        # Scale to per-hour rate
        window_hours = VELOCITY_WINDOW_MINUTES / 60
        velocity_per_hour = net_outflow / window_hours if window_hours > 0 else 0

        # Current balance
        current_balance = agent.shared_cash.cash_amount

        # Time-to-depletion
        minutes_remaining = None
        if velocity_per_hour > 0:
            hours_remaining = current_balance / velocity_per_hour
            minutes_remaining = round(hours_remaining * 60, 1)

        # Confidence
        confidence, confidence_reason = self._compute_confidence(
            len(window_txns), agent.shared_cash.data_fresh, feed_health
        )

        # Severity
        severity = self._compute_severity(minutes_remaining)

        return LiquidityProjection(
            agent_id=agent.agent_id,
            agent_name=agent.name,
            provider=None,
            balance_type="shared_cash",
            current_balance=round(current_balance, 2),
            velocity_per_hour=round(velocity_per_hour, 2),
            minutes_remaining=minutes_remaining,
            confidence=confidence,
            confidence_reason=confidence_reason,
            severity=severity,
            evidence={
                "window_minutes": VELOCITY_WINDOW_MINUTES,
                "txn_count_in_window": len(window_txns),
                "cash_in_total": round(cash_in, 2),
                "cash_out_total": round(cash_out, 2),
                "net_outflow": round(net_outflow, 2),
                "current_balance": round(current_balance, 2),
            },
            timestamp=reference_time,
        )

    # ------------------------------------------------------------------
    # Internal: per-provider e-money projection
    # ------------------------------------------------------------------

    def _project_provider_emoney(
        self,
        agent: AgentProfile,
        provider: Provider,
        prov_txns: list[Transaction],
        window_start: datetime,
        reference_time: datetime,
        is_healthy: bool = True,
        delay_seconds: int = 0,
    ) -> LiquidityProjection:
        """
        Per-provider e-money projection.
        Cash-out depletes e-money; cash-in replenishes.
        """
        # Filter to window
        window_txns = [
            t for t in prov_txns
            if window_start <= t.timestamp <= reference_time
            and t.status.value == "success"
        ]

        # E-money flow (opposite of cash)
        # Cash-out: customer gets cash, agent's e-money increases (they receive e-money)
        # Cash-in: customer deposits cash, agent's e-money decreases (they send e-money)
        # For e-money depletion tracking: large cash-in volume drains e-money
        emoney_in = sum(
            t.amount for t in window_txns
            if t.txn_type == TransactionType.CASH_OUT  # agent receives e-money
        )
        emoney_out = sum(
            t.amount for t in window_txns
            if t.txn_type in (TransactionType.CASH_IN, TransactionType.SEND_MONEY)
        )
        net_outflow = emoney_out - emoney_in  # positive = e-money draining

        window_hours = VELOCITY_WINDOW_MINUTES / 60
        velocity_per_hour = net_outflow / window_hours if window_hours > 0 else 0

        # Current balance
        bal = agent.provider_balances.get(provider)
        current_balance = bal.emoney_balance if bal else 0

        # Time-to-depletion
        minutes_remaining = None
        if velocity_per_hour > 0:
            hours_remaining = current_balance / velocity_per_hour
            minutes_remaining = round(hours_remaining * 60, 1)

        # Confidence — degrades if feed is unhealthy
        data_fresh = is_healthy and (bal.data_fresh if bal else False)
        confidence, confidence_reason = self._compute_confidence(
            len(window_txns), data_fresh,
            feed_health={"delay_seconds": delay_seconds, "healthy": is_healthy}
        )

        severity = self._compute_severity(minutes_remaining)

        return LiquidityProjection(
            agent_id=agent.agent_id,
            agent_name=agent.name,
            provider=provider.value,
            balance_type=provider.value,
            current_balance=round(current_balance, 2),
            velocity_per_hour=round(velocity_per_hour, 2),
            minutes_remaining=minutes_remaining,
            confidence=confidence,
            confidence_reason=confidence_reason,
            severity=severity,
            evidence={
                "window_minutes": VELOCITY_WINDOW_MINUTES,
                "txn_count_in_window": len(window_txns),
                "emoney_in_total": round(emoney_in, 2),
                "emoney_out_total": round(emoney_out, 2),
                "net_outflow": round(net_outflow, 2),
                "current_balance": round(current_balance, 2),
                "feed_healthy": is_healthy,
                "feed_delay_seconds": delay_seconds,
            },
            timestamp=reference_time,
        )

    # ------------------------------------------------------------------
    # Confidence computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_confidence(
        txn_count: int,
        data_fresh: bool,
        feed_health: Optional[dict] = None,
    ) -> tuple[ConfidenceLevel, str]:
        """
        Confidence degrades when:
          - Provider feed is stale or delayed
          - Too few transactions in the window for reliable extrapolation
        """
        if feed_health and not feed_health.get("healthy", True):
            delay = feed_health.get("delay_seconds", 0)
            return (
                ConfidenceLevel.LOW,
                f"Provider feed degraded (delay: {delay}s). "
                "Projection uses stale data — treat with caution."
            )

        if not data_fresh:
            return (
                ConfidenceLevel.LOW,
                "Data is not fresh. Projection may not reflect current conditions."
            )

        if txn_count < MIN_TXN_COUNT_FOR_MEDIUM_CONFIDENCE:
            return (
                ConfidenceLevel.LOW,
                f"Only {txn_count} transactions in window — insufficient for reliable projection."
            )

        if txn_count < MIN_TXN_COUNT_FOR_HIGH_CONFIDENCE:
            return (
                ConfidenceLevel.MEDIUM,
                f"Moderate transaction count ({txn_count}) — projection is directional."
            )

        return (
            ConfidenceLevel.HIGH,
            f"Sufficient data ({txn_count} transactions in window)."
        )

    # ------------------------------------------------------------------
    # Severity computation
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_severity(minutes_remaining: Optional[float]) -> AlertSeverity:
        if minutes_remaining is None:
            return AlertSeverity.INFO  # Not draining
        if minutes_remaining <= CRITICAL_THRESHOLD_MINUTES:
            return AlertSeverity.CRITICAL
        if minutes_remaining <= WARNING_THRESHOLD_MINUTES:
            return AlertSeverity.WARNING
        return AlertSeverity.INFO
