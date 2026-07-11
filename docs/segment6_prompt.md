# Segment 6: Development Prompt — Validation, Metrics & Demo

## Objective
Validate the entire system end-to-end against injected ground truth events. Compute measurable metrics that prove the system works as designed. Provide API endpoints for live demo inspection.

## Key Design Decisions

**Why a separate validation module?**
Ground truth should NEVER leak into the analytics or narration layer. The validation module reads ground truth from a separate cache file and compares against analytics output post-hoc. This mirrors how a real audit would work — the detector doesn't know the answer key.

**Metrics computed:**
1. **Anomaly Precision / Recall / F1** — Does the structuring detector catch all injected events? Does it avoid flagging organic demand?
2. **False-Positive Rate on Legitimate Spike** — Must be 0%. The legitimate spike (Nagad, AGT-SYL-002) must be classified as LIKELY_NORMAL, never as REQUIRES_REVIEW.
3. **Shortage Prediction Lead Time** — How many minutes before depletion does the system warn?
4. **Narration Safety** — Regex scan of all narration output for banned words + disclaimer presence.
5. **Case Workflow Audit** — All cases have audit trails, valid transitions, notification logs.
6. **API Latency** — P50/P95 response times via middleware instrumentation.

## Validation Architecture
```
Ground Truth (private)    Analytics Output
        │                        │
        └───── ValidationEngine ──┘
                     │
              ┌──────┼──────┬──────────┬───────────┐
              │      │      │          │           │
           Anomaly  FP   Shortage  Narration   Workflow
           P/R/F1  Rate  Lead Time  Safety      Audit
```

## API Endpoints
| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/v1/metrics/validation` | Full validation report |
| GET | `/api/v1/metrics/anomaly` | Anomaly P/R/F1 only |
| GET | `/api/v1/metrics/latency` | API latency P50/P95 |
| GET | `/api/v1/metrics/narration-safety` | Banned words scan |
| GET | `/api/v1/metrics/ground-truth` | GT events summary |

## Exit Criteria
1. ✅ Structuring burst detected with recall ≥ 1.0
2. ✅ Legitimate spike FP rate = 0%
3. ✅ Feed degradation classified as DATA_QUALITY_ISSUE
4. ✅ All narrations clean of banned words
5. ✅ Human-review disclaimer in all English narrations
6. ✅ Shortage predictions carry confidence + evidence
7. ✅ Full validation report generates without error
8. ✅ Latency metrics compute P50/P95
9. ✅ Workflow audit — 100% coverage, 0 invalid transitions
10. ✅ Three-way classification coverage present

## Files Created
- `backend/validation/__init__.py` — ValidationEngine, AnomalyMetrics, ShortagePredictionMetrics, NarrationSafetyMetrics, CaseWorkflowMetrics, LatencyMetrics
- `tests/test_segment6.py` — 10 exit tests
- `docs/segment6_prompt.md` — This document
