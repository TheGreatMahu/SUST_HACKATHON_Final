# SuperAgent LiquidityIQ 🏦

**bKash presents SUST CSE Carnival 2026 — Codex Community Hackathon**

Multi-Provider Liquidity & Anomaly Decision-Support System

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    FRONTEND (React/Vite)                  │
│  ┌─────────────────┐    ┌──────────────────────────────┐ │
│  │  Agent View     │    │  Ops / Risk Reviewer View    │ │
│  │  (Bangla-first) │    │  (English, desktop)          │ │
│  └────────┬────────┘    └──────────────┬───────────────┘ │
└───────────┼─────────────────────────────┼────────────────┘
            │             REST API         │
┌───────────▼─────────────────────────────▼────────────────┐
│                   FASTAPI BACKEND                         │
│  ┌─────────────────────────────────────────────────────┐  │
│  │              Analytics Engine (Segment 2)           │  │
│  │  Liquidity Projection │ Anomaly Detector │ Fallback │  │
│  └───────────────────────┬─────────────────────────────┘  │
│  ┌────────────────────────▼────────────────────────────┐  │
│  │           LLM Narration Layer (Segment 3)           │  │
│  │  Bilingual alerts │ Stakeholder-specific framing    │  │
│  └───────────────────────┬─────────────────────────────┘  │
│  ┌────────────────────────▼────────────────────────────┐  │
│  │         Case & Coordination Workflow (Seg 4)        │  │
│  │  Alert → Case → Owner → Escalation → Resolution    │  │
│  └───────────────────────┬─────────────────────────────┘  │
│  ┌────────────────────────▼────────────────────────────┐  │
│  │           Provider Registry (Segment 1)             │  │
│  │  bKash Pipeline │ Nagad Pipeline │ Rocket Pipeline  │  │
│  │       ↑ ISOLATION BOUNDARY — no cross-reads ↑       │  │
│  └─────────────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────────────────┐  │
│  │        Synthetic Data Generator (Segment 1)         │  │
│  │  Poisson arrivals │ Pre-Eid surge │ GT injection    │  │
│  └─────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

## 📋 Submission Checklist

- [x] **Segment 1** — Synthetic Data & Provider Isolation ✅
- [x] **Segment 2** — Core Analytics Engine (Liquidity + Anomaly) ✅
- [x] **Segment 3** — LLM Narration Layer (Bilingual) ✅
- [x] **Segment 4** — Case & Coordination Workflow ✅
- [ ] **Segment 5** — Two-Sided Dashboard
- [ ] **Segment 6** — Validation, Metrics, Demo

## 🚀 Setup & Run

### Prerequisites
- Python 3.11+
- Node.js 20+ (for frontend, Segment 5)
- OpenAI API key (for Segment 3)

### Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --app-dir ..
```

### Run Segment 1 Exit Test
```bash
python tests/test_segment1.py
```

### API Documentation
Visit `http://localhost:8000/docs` for interactive Swagger UI.

## 📊 Data & Simulation Note

### How data was created
- **Providers simulated**: bKash, Nagad, Rocket (logically isolated)
- **Agents**: 5 agents across 3 areas (Sylhet Sadar, Zindabazar, Ambarkhana)
- **Simulation date**: Pre-Eid day (June 5, 2026) — 8 AM to 8 PM
- **Arrival process**: Poisson modulated by time-of-day + 1.8× pre-Eid multiplier
- **Seed**: Fixed (42) for reproducibility

### Ground-truth injected events
| Event | Type | Provider | Agent | Window |
|-------|------|----------|-------|--------|
| Structuring burst | 18 near-identical cash-outs, 3 accounts | bKash | AGT-SYL-001 | 17:10–17:28 |
| Legitimate spike | High volume, 35+ distinct accounts | Nagad | AGT-SYL-002 | 18:00–18:45 |
| Feed delay | 15-min provider outage | Rocket | All agents | 16:30–16:45 |

### Assumptions & Limitations
- Cash balances are not updated transactionally (snapshots only in Segment 1)
- Transaction failure rate: 3% uniform (real failure rates vary by provider and txn type)
- No real customer PII — all identifiers are synthetic
- Provider limits are illustrative, not official bKash/Nagad/Rocket figures

## 🔒 Responsible Design

- **No fraud determinations**: All risk signals use "unusual activity" / "requires review" language
- **Human review required**: No automatic blocking, freezing, or accusation
- **Provider isolation**: bKash logic cannot read Nagad/Rocket data
- **Synthetic data only**: No real customer identities, balances, or credentials
- **Confidence degradation**: Stale/missing data explicitly downgrades confidence

## 📐 Architecture Diagram

See `docs/architecture.md` for the full component diagram.

## 📏 Measured Metrics (Segment 6)

To be populated after Segment 2 completes. Target metrics:
- Anomaly precision / recall / F1 on injected structuring events
- False-positive rate on legitimate spike (must be 0%)
- Shortage prediction lead time vs. actual simulated depletion
- API P50/P95 latency at simulated load

---

*This is a hackathon prototype. It does not connect to real wallets, real customer accounts, or any production financial infrastructure.*
