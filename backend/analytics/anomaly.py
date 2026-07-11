"""
Segment 2: Anomaly Detector
==============================
Two detection methods, no LLM — pure deterministic scoring.

1. Structuring Scorer (primary):
   - Groups transactions by (agent, provider, rolling 15-min window)
   - Scores on: transaction count, amount similarity (CV), account concentration
   - Detects: structuring/smurfing patterns (near-identical amounts, few accounts)

2. Volume Z-Score (secondary):
   - Rolling z-score on hourly volume per agent per provider
   - Distinguishes "Elevated Demand — Likely Normal" from "Unusual Activity"

THREE-WAY CLASSIFICATION (key differentiator):
  - LIKELY_NORMAL: high volume + many accounts + varied amounts = Eid demand
  - DATA_QUALITY_ISSUE: feed delay, stale data
  - REQUIRES_REVIEW: concentrated accounts + similar amounts = needs human review

Language rules:
  - NEVER use "fraud", "suspicious", "scam", "illegal"
  - USE "unusual activity", "requires review", "elevated demand"
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict
import math
import statistics

from backend.models.data_models import (
    Provider, TransactionType, TransactionStatus, Transaction, AgentProfile
)
from backend.models.alert_models import (
    AnomalyAlert, AlertType, AlertSeverity, AlertClassification,
    ConfidenceLevel
)
from backend.providers.registry import ProviderRegistry


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Structuring detection
STRUCTURING_WINDOW_MINUTES = 15
STRUCTURING_MIN_TXN_COUNT = 8          # Minimum txns in window to flag
STRUCTURING_MAX_UNIQUE_ACCOUNTS = 5    # Few accounts = concentrated
STRUCTURING_MAX_CV = 0.10              # Coefficient of variation — low = similar amounts
STRUCTURING_SCORE_THRESHOLD = 0.65     # Composite score threshold to flag

# Volume z-score
ZSCORE_WINDOW_HOURS = 1
ZSCORE_BASELINE_HOURS = 6              # Use first 6 hours as baseline
ZSCORE_THRESHOLD_REVIEW = 2.5         # Z > 2.5 needs review
ZSCORE_THRESHOLD_SPIKE = 1.8           # Z > 1.8 is elevated

# Account diversity threshold for distinguishing organic vs. concentrated
ORGANIC_ACCOUNT_RATIO = 0.5           # >50% unique accounts = organic


# ---------------------------------------------------------------------------
# Anomaly Detector
# ---------------------------------------------------------------------------

class AnomalyDetector:
    """
    Detects unusual transaction patterns using deterministic scoring.
    Every alert includes the literal numbers that triggered it.
    """

    def __init__(self, registry: ProviderRegistry):
        self._registry = registry

    def detect_all(
        self,
        reference_time: Optional[datetime] = None,
        feed_health: Optional[dict] = None,
    ) -> list[AnomalyAlert]:
        """Run all detection methods across all agents and providers."""
        alerts = []
        agents = self._registry.list_agents()

        for agent in agents:
            for prov in agent.active_providers:
                pipeline = self._registry.get_pipeline(prov)
                prov_txns = pipeline.get_transactions(agent_id=agent.agent_id)

                if not prov_txns:
                    continue

                # Use the last transaction timestamp as reference if not provided
                ref_time = reference_time or max(t.timestamp for t in prov_txns)

                # 1. Structuring detection
                struct_alerts = self._detect_structuring(
                    agent, prov, prov_txns, ref_time,
                    is_healthy=pipeline.is_healthy,
                )
                alerts.extend(struct_alerts)

                # 2. Volume z-score
                zscore_alerts = self._detect_volume_zscore(
                    agent, prov, prov_txns, ref_time,
                    is_healthy=pipeline.is_healthy,
                )
                alerts.extend(zscore_alerts)

        # Check for feed degradation alerts
        feed_alerts = self._detect_feed_degradation(feed_health)
        alerts.extend(feed_alerts)

        return alerts

    def detect_for_agent(
        self,
        agent_id: str,
        reference_time: Optional[datetime] = None,
    ) -> list[AnomalyAlert]:
        """Run detection for a single agent."""
        agent = self._registry.get_agent(agent_id)
        if not agent:
            return []

        alerts = []
        for prov in agent.active_providers:
            pipeline = self._registry.get_pipeline(prov)
            prov_txns = pipeline.get_transactions(agent_id=agent_id)

            if not prov_txns:
                continue

            ref_time = reference_time or max(t.timestamp for t in prov_txns)

            alerts.extend(self._detect_structuring(
                agent, prov, prov_txns, ref_time, pipeline.is_healthy
            ))
            alerts.extend(self._detect_volume_zscore(
                agent, prov, prov_txns, ref_time, pipeline.is_healthy
            ))

        return alerts

    # ------------------------------------------------------------------
    # 1. Structuring / Smurfing Detection
    # ------------------------------------------------------------------

    def _detect_structuring(
        self,
        agent: AgentProfile,
        provider: Provider,
        txns: list[Transaction],
        reference_time: datetime,
        is_healthy: bool = True,
    ) -> list[AnomalyAlert]:
        """
        Detect structuring patterns:
        - Many transactions in a short window
        - Near-identical amounts (low coefficient of variation)
        - Few distinct accounts (high concentration)
        """
        alerts = []

        # Focus on cash-out transactions (structuring target)
        cash_outs = [
            t for t in txns
            if t.txn_type == TransactionType.CASH_OUT
            and t.status == TransactionStatus.SUCCESS
        ]

        if len(cash_outs) < STRUCTURING_MIN_TXN_COUNT:
            return alerts

        # Scan through sliding windows
        cash_outs.sort(key=lambda t: t.timestamp)
        window_delta = timedelta(minutes=STRUCTURING_WINDOW_MINUTES)

        i = 0
        flagged_windows = set()  # Avoid duplicate alerts for overlapping windows

        while i < len(cash_outs):
            window_start = cash_outs[i].timestamp
            window_end = window_start + window_delta

            # Collect transactions in this window
            window_txns = [
                t for t in cash_outs
                if window_start <= t.timestamp <= window_end
            ]

            if len(window_txns) >= STRUCTURING_MIN_TXN_COUNT:
                # Check if we already flagged a window overlapping this one
                window_key = (
                    window_start.replace(second=0, microsecond=0),
                    agent.agent_id,
                    provider.value,
                )
                if window_key not in flagged_windows:
                    alert = self._score_structuring_window(
                        agent, provider, window_txns,
                        window_start, window_end, is_healthy,
                    )
                    if alert:
                        alerts.append(alert)
                        flagged_windows.add(window_key)

            i += 1

        return alerts

    def _score_structuring_window(
        self,
        agent: AgentProfile,
        provider: Provider,
        window_txns: list[Transaction],
        window_start: datetime,
        window_end: datetime,
        is_healthy: bool,
    ) -> Optional[AnomalyAlert]:
        """
        Score a window of transactions for structuring patterns.
        Returns an alert if the composite score exceeds the threshold.
        """
        amounts = [t.amount for t in window_txns]
        unique_accounts = set(t.account_id for t in window_txns)
        txn_count = len(window_txns)

        # --- Score components ---

        # 1. Volume score: more txns in window = higher score
        volume_score = min(txn_count / (STRUCTURING_MIN_TXN_COUNT * 2), 1.0)

        # 2. Amount similarity: low CV = amounts are near-identical
        mean_amount = statistics.mean(amounts)
        if mean_amount > 0 and len(amounts) > 1:
            stdev = statistics.stdev(amounts)
            cv = stdev / mean_amount
        else:
            cv = 1.0  # Can't compute — assume diverse

        # Lower CV = more suspicious
        amount_score = max(0, 1.0 - (cv / STRUCTURING_MAX_CV)) if cv <= STRUCTURING_MAX_CV * 3 else 0

        # 3. Account concentration: fewer accounts = more concentrated
        account_ratio = len(unique_accounts) / txn_count
        concentration_score = max(0, 1.0 - (account_ratio / ORGANIC_ACCOUNT_RATIO))

        # --- Composite score ---
        composite = (volume_score * 0.3) + (amount_score * 0.4) + (concentration_score * 0.3)

        if composite < STRUCTURING_SCORE_THRESHOLD:
            return None

        # Determine classification
        if len(unique_accounts) <= STRUCTURING_MAX_UNIQUE_ACCOUNTS and cv <= STRUCTURING_MAX_CV:
            classification = AlertClassification.REQUIRES_REVIEW
            severity = AlertSeverity.CRITICAL
        elif len(unique_accounts) > txn_count * ORGANIC_ACCOUNT_RATIO:
            classification = AlertClassification.LIKELY_NORMAL
            severity = AlertSeverity.INFO
            return None  # Don't flag organic patterns
        else:
            classification = AlertClassification.REQUIRES_REVIEW
            severity = AlertSeverity.WARNING

        # Confidence
        confidence = ConfidenceLevel.HIGH if is_healthy else ConfidenceLevel.LOW

        total_amount = sum(amounts)

        return AnomalyAlert(
            alert_type=AlertType.STRUCTURING_PATTERN,
            classification=classification,
            provider=provider.value,
            agent_id=agent.agent_id,
            agent_name=agent.name,
            severity=severity,
            confidence=confidence,
            confidence_reason=(
                "High confidence — sufficient data and fresh provider feed."
                if is_healthy else
                "Low confidence — provider feed is degraded. Treat with caution."
            ),
            evidence={
                "transactions_count": txn_count,
                "time_window_minutes": STRUCTURING_WINDOW_MINUTES,
                "unique_accounts": len(unique_accounts),
                "total_amount": round(total_amount, 2),
                "mean_amount": round(mean_amount, 2),
                "amount_spread": round(max(amounts) - min(amounts), 2),
                "coefficient_of_variation": round(cv, 4),
                "composite_score": round(composite, 3),
                "volume_score": round(volume_score, 3),
                "amount_similarity_score": round(amount_score, 3),
                "concentration_score": round(concentration_score, 3),
            },
            recommended_action=(
                "Contact agent to verify if this is legitimate holiday demand "
                "before supplying additional float. Review the transaction pattern "
                "with the field officer."
            ),
            time_window_start=window_start,
            time_window_end=window_end,
        )

    # ------------------------------------------------------------------
    # 2. Volume Z-Score Detection
    # ------------------------------------------------------------------

    def _detect_volume_zscore(
        self,
        agent: AgentProfile,
        provider: Provider,
        txns: list[Transaction],
        reference_time: datetime,
        is_healthy: bool = True,
    ) -> list[AnomalyAlert]:
        """
        Rolling z-score on hourly transaction volume.
        Distinguishes organic demand spikes from unusual patterns.
        """
        alerts = []

        # Only look at successful transactions
        success_txns = [t for t in txns if t.status == TransactionStatus.SUCCESS]
        if len(success_txns) < 10:
            return alerts

        # Build hourly volume counts
        hourly_volumes = defaultdict(int)
        hourly_txns = defaultdict(list)
        for t in success_txns:
            hour_key = t.timestamp.replace(minute=0, second=0, microsecond=0)
            hourly_volumes[hour_key] += 1
            hourly_txns[hour_key].append(t)

        if len(hourly_volumes) < 3:
            return alerts

        # Sort hours
        sorted_hours = sorted(hourly_volumes.keys())
        volumes = [hourly_volumes[h] for h in sorted_hours]

        # Compute baseline from first N hours
        baseline_count = min(ZSCORE_BASELINE_HOURS, len(volumes) - 1)
        if baseline_count < 2:
            return alerts

        baseline_volumes = volumes[:baseline_count]
        baseline_mean = statistics.mean(baseline_volumes)
        baseline_stdev = statistics.stdev(baseline_volumes) if len(baseline_volumes) > 1 else 1.0

        if baseline_stdev == 0:
            baseline_stdev = 1.0  # Avoid division by zero

        # Check each hour after baseline
        for idx in range(baseline_count, len(sorted_hours)):
            hour = sorted_hours[idx]
            volume = hourly_volumes[hour]
            z_score = (volume - baseline_mean) / baseline_stdev

            if z_score < ZSCORE_THRESHOLD_SPIKE:
                continue

            # Analyze the hour's transactions for organic vs. concentrated
            hour_txns = hourly_txns[hour]
            unique_accounts = len(set(t.account_id for t in hour_txns))
            amounts = [t.amount for t in hour_txns]

            if len(amounts) > 1:
                amount_cv = statistics.stdev(amounts) / statistics.mean(amounts) if statistics.mean(amounts) > 0 else 0
            else:
                amount_cv = 0

            account_diversity = unique_accounts / len(hour_txns) if hour_txns else 0

            # THREE-WAY CLASSIFICATION
            if z_score >= ZSCORE_THRESHOLD_REVIEW:
                if account_diversity >= ORGANIC_ACCOUNT_RATIO and amount_cv > STRUCTURING_MAX_CV * 2:
                    # High volume + many accounts + varied amounts = organic spike
                    classification = AlertClassification.LIKELY_NORMAL
                    alert_type = AlertType.VOLUME_SPIKE_NORMAL
                    severity = AlertSeverity.INFO
                    recommended_action = (
                        "Elevated transaction volume detected — consistent with seasonal demand. "
                        "No unusual pattern indicators. Monitor for cash availability."
                    )
                else:
                    # High volume + concentrated accounts or similar amounts = needs review
                    classification = AlertClassification.REQUIRES_REVIEW
                    alert_type = AlertType.VOLUME_SPIKE_REVIEW
                    severity = AlertSeverity.WARNING
                    recommended_action = (
                        "Elevated transaction volume with concentrated account activity. "
                        "Review transaction pattern with field officer before major action."
                    )
            else:
                # Moderate z-score — informational
                classification = AlertClassification.LIKELY_NORMAL
                alert_type = AlertType.VOLUME_SPIKE_NORMAL
                severity = AlertSeverity.INFO
                recommended_action = (
                    "Moderately elevated volume — likely normal demand variation. "
                    "Continue standard monitoring."
                )

            confidence = ConfidenceLevel.HIGH if is_healthy else ConfidenceLevel.LOW

            alerts.append(AnomalyAlert(
                alert_type=alert_type,
                classification=classification,
                provider=provider.value,
                agent_id=agent.agent_id,
                agent_name=agent.name,
                severity=severity,
                confidence=confidence,
                confidence_reason=(
                    f"Based on {baseline_count}-hour baseline with {len(success_txns)} total transactions."
                    if is_healthy else
                    "Provider feed degraded — z-score computed on potentially incomplete data."
                ),
                evidence={
                    "hour": hour.isoformat(),
                    "volume_this_hour": volume,
                    "baseline_mean": round(baseline_mean, 2),
                    "baseline_stdev": round(baseline_stdev, 2),
                    "z_score": round(z_score, 2),
                    "unique_accounts": unique_accounts,
                    "account_diversity_ratio": round(account_diversity, 3),
                    "amount_cv": round(amount_cv, 4),
                    "total_amount": round(sum(amounts), 2),
                },
                recommended_action=recommended_action,
                time_window_start=hour,
                time_window_end=hour + timedelta(hours=1),
            ))

        return alerts

    # ------------------------------------------------------------------
    # 3. Feed Degradation Detection
    # ------------------------------------------------------------------

    def _detect_feed_degradation(
        self,
        feed_health: Optional[dict] = None,
    ) -> list[AnomalyAlert]:
        """
        Check all provider feeds for degradation.
        Creates alerts when a provider's data is stale or delayed.
        """
        alerts = []

        for prov in [Provider.BKASH, Provider.NAGAD, Provider.ROCKET]:
            try:
                pipeline = self._registry.get_pipeline(prov)
            except KeyError:
                continue

            if not pipeline.is_healthy:
                alerts.append(AnomalyAlert(
                    alert_type=AlertType.FEED_DEGRADED,
                    classification=AlertClassification.DATA_QUALITY_ISSUE,
                    provider=prov.value,
                    agent_id="ALL",
                    severity=AlertSeverity.WARNING,
                    confidence=ConfidenceLevel.HIGH,
                    confidence_reason="Feed degradation is directly observed, not inferred.",
                    evidence={
                        "provider": prov.value,
                        "feed_healthy": False,
                        "delay_seconds": pipeline.delay_seconds,
                        "affected_agents": pipeline.all_agents_in_feed,
                    },
                    recommended_action=(
                        f"Provider {prov.value} feed is delayed by {pipeline.delay_seconds} seconds. "
                        "All projections and alerts for this provider use stale data. "
                        "Do not make confident decisions based on this provider's data until feed recovers."
                    ),
                ))

        # Also check any overrides from chaos toggle
        if feed_health:
            for prov_name, health in feed_health.items():
                if not health.get("healthy", True) and not any(
                    a.provider == prov_name and a.alert_type == AlertType.FEED_DEGRADED
                    for a in alerts
                ):
                    alerts.append(AnomalyAlert(
                        alert_type=AlertType.FEED_DEGRADED,
                        classification=AlertClassification.DATA_QUALITY_ISSUE,
                        provider=prov_name,
                        agent_id="ALL",
                        severity=AlertSeverity.WARNING,
                        confidence=ConfidenceLevel.HIGH,
                        evidence={
                            "provider": prov_name,
                            "feed_healthy": False,
                            "delay_seconds": health.get("delay_seconds", 0),
                            "source": "chaos_toggle",
                        },
                        recommended_action=(
                            f"Provider {prov_name} feed manually degraded (chaos toggle). "
                            "Confidence levels on all related alerts have been downgraded."
                        ),
                    ))

        return alerts
