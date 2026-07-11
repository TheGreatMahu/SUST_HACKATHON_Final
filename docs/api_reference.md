# API Reference — SuperAgent LiquidityIQ

Complete API reference for the Multi-Provider Liquidity & Anomaly Decision-Support System.

**Base URL:** `http://localhost:8000`  
**Interactive Docs:** `http://localhost:8000/docs` (Swagger UI)

---

## Segment 1 — Data & Provider Isolation

### `GET /health`
Basic health check.

**Response:**
```json
{"status": "ok", "timestamp": "2026-06-05T20:00:00"}
```

---

### `GET /api/v1/system/health`
Provider feed health — shows if any provider data is delayed or missing. Includes chaos toggle state.

**Response:**
```json
{
  "providers": {
    "bkash": {"healthy": true, "delay_seconds": 0, "agent_count": 4},
    "nagad": {"healthy": true, "delay_seconds": 0, "agent_count": 4},
    "rocket": {"healthy": false, "delay_seconds": 900, "agent_count": 3}
  },
  "chaos_state": {
    "degraded_providers": [],
    "all_healthy": true
  }
}
```

---

### `GET /api/v1/data/summary`
Simulation summary — transaction counts, provider counts, ground truth event count.

**Response:**
```json
{
  "total_transactions": 850,
  "providers": ["bkash", "nagad", "rocket"],
  "agent_count": 5,
  "simulation_date": "2026-06-05",
  "simulation_hours": 12,
  "ground_truth_events": 3
}
```

---

### `GET /api/v1/agents`
List all agents with combined provider view (balances always kept separate).

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `area` | string | Filter by area name (e.g., "Sylhet Sadar") |

**Response:**
```json
[
  {
    "agent_id": "AGT-SYL-001",
    "agent_name": "Rahim Uddin MFS Shop",
    "area": "Sylhet Sadar",
    "shared_cash": {"amount": 85000, "data_fresh": true},
    "provider_balances": {
      "bkash": {"provider": "bkash", "emoney_balance": 120000, "emoney_limit": 200000, "data_fresh": true},
      "nagad": {"provider": "nagad", "emoney_balance": 75000, "emoney_limit": 150000, "data_fresh": true}
    },
    "all_data_fresh": true
  }
]
```

---

### `GET /api/v1/agents/{agent_id}`
Combined view for a single agent — shared cash + separate provider balances.

---

### `GET /api/v1/transactions`
Query transactions with optional filters.

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `provider` | string | Filter by provider (bkash/nagad/rocket) |
| `agent_id` | string | Filter by agent ID |
| `since` | ISO datetime | Start of time window |
| `until` | ISO datetime | End of time window |
| `limit` | int | Max results (default: 200, max: 1000) |

---

### `GET /api/v1/providers/{provider_id}/balances`
Provider-specific balances — only that provider's data returned. Enforces provider isolation.

---

## Segment 2 — Analytics Engine

### `GET /api/v1/analytics/liquidity`
Liquidity projections for all agents — time-to-depletion with confidence.

**Response fields per projection:**
| Field | Type | Description |
|-------|------|-------------|
| `agent_id` | string | Agent identifier |
| `balance_type` | string | "shared_cash" or provider name |
| `current_balance` | float | Current balance in BDT |
| `velocity_per_hour` | float | Net outflow rate in BDT/hour |
| `minutes_remaining` | float | Estimated minutes until depletion |
| `confidence` | string | "high" / "medium" / "low" |
| `confidence_reason` | string | Why this confidence level |
| `severity` | string | "critical" / "warning" / "info" |
| `evidence` | object | Literal numbers that produced this projection |

---

### `GET /api/v1/analytics/liquidity/{agent_id}`
Liquidity projection for a single agent — shared cash + per-provider.

---

### `GET /api/v1/analytics/anomalies`
All detected anomalies across all agents and providers.

**Response fields per anomaly:**
| Field | Type | Description |
|-------|------|-------------|
| `alert_type` | string | structuring_pattern / volume_spike_normal / volume_spike_review / feed_degraded |
| `classification` | string | likely_normal / data_quality_issue / requires_review |
| `severity` | string | critical / warning / info |
| `confidence` | string | high / medium / low |
| `evidence` | object | Literal numbers: txn_count, z_score, unique_accounts, amount_cv, etc. |
| `recommended_action` | string | Always a human action |
| `disclaimer` | string | "This is not a final determination..." |

---

### `GET /api/v1/analytics/anomalies/{agent_id}`
Anomalies detected for a single agent.

---

### `GET /api/v1/analytics/alerts`
Combined alerts — liquidity shortages + anomaly detections, sorted by severity.

Every alert carries:
- Confidence level
- Classification (likely_normal / data_quality_issue / requires_review)
- Evidence (the literal numbers that triggered it)
- Recommended action
- Human-review disclaimer

---

## Segment 2 — Chaos Toggle (Scenario C Demo)

### `POST /api/v1/system/chaos/degrade/{provider_id}`
Simulate a provider feed going down. Immediately degrades confidence on all alerts for this provider.

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `delay_seconds` | int | 900 | Simulated delay in seconds |

**Response:**
```json
{
  "status": "degraded",
  "provider": "rocket",
  "message": "Provider rocket feed marked as degraded. All confidence levels for this provider will downgrade."
}
```

---

### `POST /api/v1/system/chaos/restore/{provider_id}`
Restore a previously degraded provider feed.

---

### `GET /api/v1/system/chaos/status`
Current chaos toggle state — which providers are degraded.

---

## Segment 3 — LLM Narration Layer

### `GET /api/v1/narration/alert/{alert_index}`
Generate bilingual narration (Bangla/Banglish/English) for an alert. Uses LLM when API key is available, template fallback otherwise.

**Response:**
```json
{
  "alert_id": "uuid",
  "alert_type": "structuring_pattern",
  "provider": "bkash",
  "agent_id": "AGT-SYL-001",
  "narration": {
    "english": "Unusual transaction activity detected on bkash: ...",
    "bangla": "বিকাশে অস্বাভাবিক লেনদেন সনাক্ত হয়েছে: ...",
    "banglish": "bKash-e unusual transaction detected: ...",
    "narration_mode": "template",
    "generated_at": "2026-06-05T20:00:00"
  }
}
```

---

### `GET /api/v1/narration/alert/{alert_index}/stakeholder/{role}`
Generate stakeholder-specific narration.

**Path Parameters:**
| Param | Values | Description |
|-------|--------|-------------|
| `role` | agent / field_officer / compliance_analyst | Target stakeholder role |

**Framing by role:**
- **agent**: Bangla/Banglish, supportive tone, focus on cash availability
- **field_officer**: Mixed language, coordination focus, visit + check cash
- **compliance_analyst**: English, statistical evidence, escalation checklist

---

### `GET /api/v1/narration/mode`
Check current narration mode — "llm" or "template".

---

## Segment 4 — Case & Coordination Workflow

### `GET /api/v1/cases`
List all cases with optional filters.

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `status` | string | Filter by status (open/assigned/acknowledged/escalated/resolved) |
| `provider` | string | Filter by provider |
| `agent_id` | string | Filter by agent |

---

### `GET /api/v1/cases/summary`
Case board overview — counts by status, open critical cases.

---

### `GET /api/v1/cases/{case_id}`
Get a single case with full audit trail.

---

### `POST /api/v1/cases/create-from-alerts`
Create cases from all current alerts. Each alert gets narrated (Segment 3) and wrapped in a trackable case (Segment 4).

---

### `POST /api/v1/cases/{case_id}/assign`
Assign a case to a stakeholder role.

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `role` | string | field_officer | Stakeholder role to assign |

---

### `POST /api/v1/cases/{case_id}/acknowledge`
Mark a case as acknowledged by its current owner.

---

### `POST /api/v1/cases/{case_id}/escalate`
Escalate a case to the next level in the hierarchy.

**Escalation path:** agent → field_officer → area_manager → central_ops → risk_analyst

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `reason` | string | Reason for escalation |

---

### `POST /api/v1/cases/{case_id}/resolve`
Resolve a case with a closure note.

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `note` | string | Resolution note |

---

### `POST /api/v1/cases/{case_id}/note`
Add a note to a case without changing its status.

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `note` | string | Note text (required) |
| `role` | string | Actor role (default: field_officer) |

---

### `GET /api/v1/cases/{case_id}/audit`
Get the full audit trail for a case.

**Response:**
```json
{
  "case_id": "CASE-ABC12345",
  "status": "resolved",
  "audit_trail": [
    {
      "timestamp": "2026-06-05T17:30:00",
      "actor_id": "SYSTEM",
      "actor_role": "central_ops",
      "action": "created",
      "from_status": null,
      "to_status": "open",
      "note": "Case created from structuring_pattern alert on bkash"
    }
  ],
  "notification_log": [
    {
      "timestamp": "2026-06-05T17:30:00",
      "action": "would_notify",
      "target_role": "field_officer",
      "channel": "app_notification"
    }
  ]
}
```

---

## Segment 6 — Validation & Metrics

### `GET /api/v1/metrics/validation`
Run the full validation report — compares analytics output against ground truth.

Returns precision/recall/F1, false-positive rates, narration safety, workflow audit, and API latency.

---

### `GET /api/v1/metrics/anomaly`
Anomaly detection precision/recall/F1 against ground truth.

---

### `GET /api/v1/metrics/latency`
API latency P50/P95 across all recorded endpoints.

---

### `GET /api/v1/metrics/narration-safety`
Scan all narrations for banned words and disclaimer compliance.

---

### `GET /api/v1/metrics/ground-truth`
Ground truth events summary (for internal validation only).

---

## Endpoint Summary

| Method | Endpoint | Segment | Purpose |
|--------|----------|---------|---------|
| GET | `/health` | 1 | Health check |
| GET | `/api/v1/system/health` | 1 | Provider feed health |
| GET | `/api/v1/data/summary` | 1 | Simulation summary |
| GET | `/api/v1/agents` | 1 | List all agents |
| GET | `/api/v1/agents/{agent_id}` | 1 | Single agent view |
| GET | `/api/v1/transactions` | 1 | Query transactions |
| GET | `/api/v1/providers/{id}/balances` | 1 | Provider-specific balances |
| GET | `/api/v1/analytics/liquidity` | 2 | All liquidity projections |
| GET | `/api/v1/analytics/liquidity/{id}` | 2 | Agent liquidity projection |
| GET | `/api/v1/analytics/anomalies` | 2 | All anomalies |
| GET | `/api/v1/analytics/anomalies/{id}` | 2 | Agent anomalies |
| GET | `/api/v1/analytics/alerts` | 2 | Combined alerts |
| POST | `/api/v1/system/chaos/degrade/{id}` | 2 | Chaos: degrade feed |
| POST | `/api/v1/system/chaos/restore/{id}` | 2 | Chaos: restore feed |
| GET | `/api/v1/system/chaos/status` | 2 | Chaos toggle state |
| GET | `/api/v1/narration/alert/{idx}` | 3 | Bilingual narration |
| GET | `/api/v1/narration/alert/{idx}/stakeholder/{role}` | 3 | Stakeholder framing |
| GET | `/api/v1/narration/mode` | 3 | Narration mode check |
| GET | `/api/v1/cases` | 4 | List cases |
| GET | `/api/v1/cases/summary` | 4 | Case board summary |
| GET | `/api/v1/cases/{id}` | 4 | Single case + audit |
| POST | `/api/v1/cases/create-from-alerts` | 4 | Create cases from alerts |
| POST | `/api/v1/cases/{id}/assign` | 4 | Assign case |
| POST | `/api/v1/cases/{id}/acknowledge` | 4 | Acknowledge case |
| POST | `/api/v1/cases/{id}/escalate` | 4 | Escalate case |
| POST | `/api/v1/cases/{id}/resolve` | 4 | Resolve case |
| POST | `/api/v1/cases/{id}/note` | 4 | Add case note |
| GET | `/api/v1/cases/{id}/audit` | 4 | Audit trail |
| GET | `/api/v1/metrics/validation` | 6 | Full validation report |
| GET | `/api/v1/metrics/anomaly` | 6 | Anomaly P/R/F1 |
| GET | `/api/v1/metrics/latency` | 6 | API latency P50/P95 |
| GET | `/api/v1/metrics/narration-safety` | 6 | Narration safety scan |
| GET | `/api/v1/metrics/ground-truth` | 6 | Ground truth summary |

**Total endpoints: 33**
