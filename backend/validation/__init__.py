"""
Segment 6: Validation & Metrics Engine
==========================================
Compares analytics output against ground truth injected events.

Metrics computed:
  1. Anomaly Detection — Precision / Recall / F1 on structuring events
  2. False Positive Rate — on legitimate spike (must be 0%)
  3. Shortage Prediction — lead time vs. actual simulated depletion
  4. Narration Safety — banned words scan across all narrations
  5. Case Workflow — lifecycle completeness audit
  6. API Latency — P50/P95 response times (simulated)

Ground truth events (from Segment 1):
  - structuring_burst  → bKash, AGT-SYL-001, 17:10–17:28
  - legitimate_spike   → Nagad, AGT-SYL-002, 18:00–18:45
  - feed_delay         → Rocket, ALL agents, 16:30–16:45
"""

from __future__ import annotations

import re
import time
import statistics
from datetime import datetime, timedelta
from typing import Optional
from collections import defaultdict

from backend.models.alert_models import (
    SystemAlert, AnomalyAlert, LiquidityProjection,
    AlertType, AlertClassification, ConfidenceLevel, AlertSeverity
)
from backend.narration import BANNED_WORDS, BANNED_PATTERN


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Ground truth matching tolerances
GT_TIME_TOLERANCE_MINUTES = 10  # Allow ±10 minute offset for matching
GT_AGENT_STRICT = True          # Require exact agent ID match


# ---------------------------------------------------------------------------
# Anomaly Detection Metrics (Precision / Recall / F1)
# ---------------------------------------------------------------------------

class AnomalyMetrics:
    """
    Computes precision, recall, and F1 for anomaly detection
    against injected ground truth events.
    """

    def __init__(self, ground_truth: list[dict], alerts: list[SystemAlert]):
        self._gt = ground_truth
        self._alerts = alerts
        self._results = {}

    def compute(self) -> dict:
        """
        Compute all anomaly detection metrics.

        Ground truth matching:
          - structuring_burst → should produce STRUCTURING_PATTERN alert
          - legitimate_spike → should NOT produce REQUIRES_REVIEW alert
          - feed_delay → should produce FEED_DEGRADED alert
        """
        structuring_gt = [
            e for e in self._gt if e.get("event_type") == "structuring_burst"
        ]
        legitimate_gt = [
            e for e in self._gt if e.get("event_type") == "legitimate_spike"
        ]
        feed_delay_gt = [
            e for e in self._gt if e.get("event_type") == "feed_delay"
        ]

        # --- Structuring detection metrics ---
        structuring_alerts = [
            a for a in self._alerts
            if a.alert_type == AlertType.STRUCTURING_PATTERN
        ]

        # True positives: structuring GT events matched by structuring alerts
        tp_structuring = 0
        matched_alerts = set()
        for gt_event in structuring_gt:
            gt_agent = gt_event.get("agent_id", "")
            gt_provider = gt_event.get("provider", "")
            gt_start = _parse_dt(gt_event.get("start_time"))
            gt_end = _parse_dt(gt_event.get("end_time"))

            for i, alert in enumerate(structuring_alerts):
                if i in matched_alerts:
                    continue
                if self._matches_gt(alert, gt_agent, gt_provider, gt_start, gt_end):
                    tp_structuring += 1
                    matched_alerts.add(i)
                    break

        fn_structuring = len(structuring_gt) - tp_structuring
        fp_structuring = len(structuring_alerts) - tp_structuring

        precision = tp_structuring / (tp_structuring + fp_structuring) if (tp_structuring + fp_structuring) > 0 else 0
        recall = tp_structuring / (tp_structuring + fn_structuring) if (tp_structuring + fn_structuring) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        # --- False positive rate on legitimate spike ---
        # The legitimate spike should be classified as LIKELY_NORMAL, not REQUIRES_REVIEW
        fp_legitimate = 0
        for gt_event in legitimate_gt:
            gt_agent = gt_event.get("agent_id", "")
            gt_provider = gt_event.get("provider", "")
            gt_start = _parse_dt(gt_event.get("start_time"))
            gt_end = _parse_dt(gt_event.get("end_time"))

            # Check if any REQUIRES_REVIEW or STRUCTURING alert matches this GT event
            for alert in self._alerts:
                if alert.alert_type in (AlertType.STRUCTURING_PATTERN, AlertType.VOLUME_SPIKE_REVIEW):
                    if self._matches_gt(alert, gt_agent, gt_provider, gt_start, gt_end):
                        fp_legitimate += 1

        fp_rate_legitimate = fp_legitimate / max(len(legitimate_gt), 1)

        # --- Feed delay detection ---
        feed_alerts = [
            a for a in self._alerts
            if a.alert_type == AlertType.FEED_DEGRADED
        ]
        feed_detected = len(feed_alerts) > 0 if feed_delay_gt else True

        # Check feed alerts are classified as DATA_QUALITY_ISSUE
        feed_correctly_classified = all(
            a.classification == AlertClassification.DATA_QUALITY_ISSUE
            for a in feed_alerts
        ) if feed_alerts else True

        # --- Three-way classification audit ---
        classification_counts = defaultdict(int)
        for a in self._alerts:
            classification_counts[a.classification.value] += 1

        severity_counts = defaultdict(int)
        for a in self._alerts:
            severity_counts[a.severity.value] += 1

        # --- Confidence distribution ---
        confidence_counts = defaultdict(int)
        for a in self._alerts:
            confidence_counts[a.confidence.value] += 1

        self._results = {
            "structuring_detection": {
                "true_positives": tp_structuring,
                "false_positives": fp_structuring,
                "false_negatives": fn_structuring,
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1_score": round(f1, 4),
                "ground_truth_events": len(structuring_gt),
                "detected_alerts": len(structuring_alerts),
            },
            "legitimate_spike_fp": {
                "false_positives_on_legitimate": fp_legitimate,
                "false_positive_rate": round(fp_rate_legitimate, 4),
                "target": "0% — must not flag legitimate demand as unusual",
                "pass": fp_rate_legitimate == 0,
            },
            "feed_degradation": {
                "ground_truth_events": len(feed_delay_gt),
                "detected": feed_detected,
                "correctly_classified_as_data_quality": feed_correctly_classified,
                "alerts_generated": len(feed_alerts),
            },
            "classification_distribution": dict(classification_counts),
            "severity_distribution": dict(severity_counts),
            "confidence_distribution": dict(confidence_counts),
            "total_alerts": len(self._alerts),
        }
        return self._results

    def _matches_gt(
        self,
        alert: SystemAlert,
        gt_agent: str,
        gt_provider: str,
        gt_start: Optional[datetime],
        gt_end: Optional[datetime],
    ) -> bool:
        """Check if an alert matches a ground truth event."""
        # Agent match (allow 'ALL' to match any)
        if GT_AGENT_STRICT and gt_agent and gt_agent != "ALL":
            if alert.agent_id != gt_agent:
                return False

        # Provider match
        if gt_provider:
            if alert.provider != gt_provider:
                return False

        # Time window overlap (with tolerance)
        if gt_start and gt_end:
            tolerance = timedelta(minutes=GT_TIME_TOLERANCE_MINUTES)
            alert_time = alert.timestamp

            # Check if the alert's anomaly has a time window
            if alert.anomaly_alert and alert.anomaly_alert.time_window_start:
                alert_start = alert.anomaly_alert.time_window_start
                alert_end = alert.anomaly_alert.time_window_end or alert_start + timedelta(minutes=15)
                # Check overlap with tolerance
                if alert_end < gt_start - tolerance or alert_start > gt_end + tolerance:
                    return False
            else:
                # Fall back to alert timestamp
                if alert_time < gt_start - tolerance or alert_time > gt_end + tolerance:
                    return False

        return True


# ---------------------------------------------------------------------------
# Shortage Prediction Metrics
# ---------------------------------------------------------------------------

class ShortagePredictionMetrics:
    """
    Evaluates the accuracy of liquidity shortage predictions.
    Measures lead time: how far in advance did the system warn?
    """

    def __init__(
        self,
        projections: list[LiquidityProjection],
        reference_time: datetime,
    ):
        self._projections = projections
        self._reference_time = reference_time

    def compute(self) -> dict:
        """Compute shortage prediction metrics."""
        shortage_projections = [
            p for p in self._projections
            if p.severity in (AlertSeverity.CRITICAL, AlertSeverity.WARNING)
            and p.minutes_remaining is not None
        ]

        if not shortage_projections:
            return {
                "shortage_alerts_count": 0,
                "message": "No shortage alerts to evaluate.",
                "lead_times": [],
            }

        lead_times = []
        details = []
        for proj in shortage_projections:
            lead_time_minutes = proj.minutes_remaining
            lead_times.append(lead_time_minutes)

            details.append({
                "agent_id": proj.agent_id,
                "provider": proj.provider or "shared_cash",
                "balance_type": proj.balance_type,
                "current_balance": round(proj.current_balance, 2),
                "velocity_per_hour": round(proj.velocity_per_hour, 2),
                "predicted_depletion_minutes": round(lead_time_minutes, 1),
                "confidence": proj.confidence.value,
                "severity": proj.severity.value,
            })

        return {
            "shortage_alerts_count": len(shortage_projections),
            "lead_time_minutes": {
                "min": round(min(lead_times), 1),
                "max": round(max(lead_times), 1),
                "mean": round(statistics.mean(lead_times), 1),
                "median": round(statistics.median(lead_times), 1),
            },
            "all_predictions_have_evidence": all(
                bool(p.evidence) for p in shortage_projections
            ),
            "all_predictions_have_confidence": all(
                p.confidence is not None for p in shortage_projections
            ),
            "details": details,
        }


# ---------------------------------------------------------------------------
# Narration Safety Metrics
# ---------------------------------------------------------------------------

class NarrationSafetyMetrics:
    """
    Scans all narration output for banned words and safety compliance.
    """

    def __init__(self, narrations: list[dict]):
        self._narrations = narrations

    def compute(self) -> dict:
        """Scan all narrations for banned words and disclaimers."""
        total_texts = 0
        violations = []
        missing_disclaimers = []

        for i, narr in enumerate(self._narrations):
            # Check each language variant
            for lang in ["english", "bangla", "banglish"]:
                text = narr.get(lang, "")
                if not text:
                    continue
                total_texts += 1

                # Banned words check
                match = BANNED_PATTERN.search(text)
                if match:
                    violations.append({
                        "narration_index": i,
                        "language": lang,
                        "banned_word": match.group(),
                        "context": text[:100],
                    })

            # Disclaimer check (English only)
            en_text = narr.get("english", "").lower()
            has_disclaimer = (
                "human review" in en_text
                or "not a final" in en_text
                or "requires review" in en_text
            )
            if not has_disclaimer and en_text:
                missing_disclaimers.append({
                    "narration_index": i,
                    "english_text": en_text[:100],
                })

        return {
            "total_narrations": len(self._narrations),
            "total_text_segments_scanned": total_texts,
            "banned_word_violations": len(violations),
            "violation_details": violations,
            "missing_disclaimers": len(missing_disclaimers),
            "disclaimer_details": missing_disclaimers,
            "all_clean": len(violations) == 0,
            "all_have_disclaimers": len(missing_disclaimers) == 0,
            "banned_words_list": BANNED_WORDS,
            "pass": len(violations) == 0 and len(missing_disclaimers) == 0,
        }


# ---------------------------------------------------------------------------
# Case Workflow Audit
# ---------------------------------------------------------------------------

class CaseWorkflowMetrics:
    """
    Audits case workflow completeness:
    - All cases have audit trails
    - State machine transitions are valid
    - Notification logs populated
    """

    VALID_TRANSITIONS = {
        "open": {"assigned"},
        "assigned": {"acknowledged", "escalated", "resolved"},
        "acknowledged": {"escalated", "resolved"},
        "escalated": {"resolved", "escalated"},  # Can re-escalate
        "resolved": {"reopened"},
    }

    def __init__(self, cases: list):
        self._cases = cases

    def compute(self) -> dict:
        """Audit all cases for workflow compliance."""
        total = len(self._cases)
        if total == 0:
            return {
                "total_cases": 0,
                "message": "No cases to audit.",
            }

        has_audit_trail = 0
        has_notifications = 0
        fully_resolved = 0
        invalid_transitions = []
        status_counts = defaultdict(int)

        for case in self._cases:
            case_data = case.model_dump(mode="json") if hasattr(case, 'model_dump') else case

            # Count by status
            status = case_data.get("status", "unknown")
            status_counts[status] += 1

            # Audit trail check
            audit = case_data.get("audit_trail", [])
            if len(audit) > 0:
                has_audit_trail += 1

            # Notification check
            notifs = case_data.get("notification_log", [])
            if len(notifs) > 0:
                has_notifications += 1

            # Resolved check
            if status == "resolved":
                fully_resolved += 1

            # Validate transitions
            for j in range(1, len(audit)):
                from_status = audit[j].get("from_status")
                to_status = audit[j].get("to_status")
                if from_status and to_status:
                    valid = self.VALID_TRANSITIONS.get(from_status, set())
                    if to_status not in valid:
                        invalid_transitions.append({
                            "case_id": case_data.get("case_id"),
                            "from": from_status,
                            "to": to_status,
                            "entry_index": j,
                        })

        return {
            "total_cases": total,
            "status_distribution": dict(status_counts),
            "cases_with_audit_trail": has_audit_trail,
            "cases_with_notifications": has_notifications,
            "fully_resolved": fully_resolved,
            "invalid_transitions": len(invalid_transitions),
            "invalid_transition_details": invalid_transitions,
            "audit_coverage_pct": round(has_audit_trail / total * 100, 1),
            "notification_coverage_pct": round(has_notifications / total * 100, 1),
            "pass": has_audit_trail == total and len(invalid_transitions) == 0,
        }


# ---------------------------------------------------------------------------
# API Latency Metrics (Simulated)
# ---------------------------------------------------------------------------

class LatencyMetrics:
    """
    Records and computes P50/P95 latency for API endpoints.
    Uses in-process timing (not network round-trip) for demo accuracy.
    """

    def __init__(self):
        self._samples: dict[str, list[float]] = defaultdict(list)

    def record(self, endpoint: str, duration_ms: float):
        """Record a latency sample for an endpoint."""
        self._samples[endpoint].append(duration_ms)

    def time_call(self, endpoint: str, func, *args, **kwargs):
        """Time a function call and record the latency."""
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed_ms = (time.perf_counter() - start) * 1000
        self.record(endpoint, elapsed_ms)
        return result, elapsed_ms

    def compute(self) -> dict:
        """Compute P50/P95 for all recorded endpoints."""
        results = {}
        for endpoint, samples in self._samples.items():
            sorted_samples = sorted(samples)
            n = len(sorted_samples)
            if n == 0:
                continue

            p50_idx = int(n * 0.50)
            p95_idx = min(int(n * 0.95), n - 1)

            results[endpoint] = {
                "samples": n,
                "p50_ms": round(sorted_samples[p50_idx], 2),
                "p95_ms": round(sorted_samples[p95_idx], 2),
                "min_ms": round(sorted_samples[0], 2),
                "max_ms": round(sorted_samples[-1], 2),
                "mean_ms": round(statistics.mean(sorted_samples), 2),
            }

        return results


# ---------------------------------------------------------------------------
# Full Validation Report
# ---------------------------------------------------------------------------

class ValidationEngine:
    """
    Orchestrates all validation metrics into a single report.
    This is the entry point for Segment 6.
    """

    def __init__(
        self,
        ground_truth: list[dict],
        alerts: list[SystemAlert],
        projections: list[LiquidityProjection],
        narrations: list[dict],
        cases: list,
        reference_time: datetime,
        latency_metrics: Optional[LatencyMetrics] = None,
    ):
        self._anomaly = AnomalyMetrics(ground_truth, alerts)
        self._shortage = ShortagePredictionMetrics(projections, reference_time)
        self._narration = NarrationSafetyMetrics(narrations)
        self._workflow = CaseWorkflowMetrics(cases)
        self._latency = latency_metrics or LatencyMetrics()
        self._reference_time = reference_time

    def generate_report(self) -> dict:
        """Generate the full validation report."""
        anomaly_metrics = self._anomaly.compute()
        shortage_metrics = self._shortage.compute()
        narration_metrics = self._narration.compute()
        workflow_metrics = self._workflow.compute()
        latency_metrics = self._latency.compute()

        # Compute overall pass/fail
        all_pass = all([
            anomaly_metrics["structuring_detection"]["recall"] >= 1.0,
            anomaly_metrics["legitimate_spike_fp"]["pass"],
            narration_metrics["pass"],
            workflow_metrics.get("pass", True),
        ])

        return {
            "report_generated_at": datetime.utcnow().isoformat(),
            "reference_time": self._reference_time.isoformat(),
            "overall_pass": all_pass,
            "sections": {
                "anomaly_detection": anomaly_metrics,
                "shortage_prediction": shortage_metrics,
                "narration_safety": narration_metrics,
                "case_workflow": workflow_metrics,
                "api_latency": latency_metrics,
            },
            "summary": {
                "structuring_f1": anomaly_metrics["structuring_detection"]["f1_score"],
                "legitimate_fp_rate": anomaly_metrics["legitimate_spike_fp"]["false_positive_rate"],
                "narration_clean": narration_metrics["all_clean"],
                "disclaimers_present": narration_metrics["all_have_disclaimers"],
                "workflow_audit_pass": workflow_metrics.get("pass", True),
                "total_alerts": anomaly_metrics["total_alerts"],
            },
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_dt(value) -> Optional[datetime]:
    """Parse a datetime from string or return as-is."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None
