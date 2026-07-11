# Architecture — SuperAgent LiquidityIQ

## Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FRONTEND LAYER                               │
│                                                                      │
│  ┌──────────────────────────┐  ┌──────────────────────────────────┐ │
│  │    AGENT VIEW (Mobile)   │  │  OPS / RISK VIEW (Desktop)       │ │
│  │  • Bangla-first UI       │  │  • English                       │ │
│  │  • Cash runway timer     │  │  • Area-level map/hotspot        │ │
│  │  • Provider bars (sep.)  │  │  • Case board + audit trail      │ │
│  │  • Bilingual alerts      │  │  • Provider-scoped data only     │ │
│  └──────────┬───────────────┘  └─────────────────┬────────────────┘ │
└─────────────┼─────────────────────────────────────┼─────────────────┘
              │           REST + WebSocket           │
┌─────────────▼─────────────────────────────────────▼─────────────────┐
│                         FASTAPI BACKEND                               │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │                    ANALYTICS ENGINE (Seg 2)                     │ │
│  │                                                                 │ │
│  │  ┌─────────────────────┐  ┌──────────────────────────────────┐ │ │
│  │  │  Liquidity Projector│  │     Anomaly Detector             │ │ │
│  │  │  • Cash velocity    │  │  • Structuring scorer            │ │ │
│  │  │  • Time-to-depletion│  │  • Rolling z-score               │ │ │
│  │  │  • Per-provider     │  │  • 3-way: spike/data/review      │ │ │
│  │  │  • Confidence score │  │  • Confidence score              │ │ │
│  │  └─────────────────────┘  └──────────────────────────────────┘ │ │
│  │                                                                 │ │
│  │  ┌─────────────────────────────────────────────────────────┐   │ │
│  │  │              Fallback / Chaos Handler                   │   │ │
│  │  │  Feed missing → confidence degrades → safe fallback     │   │ │
│  │  └─────────────────────────────────────────────────────────┘   │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │                   LLM NARRATION LAYER (Seg 3)                   │ │
│  │  Input: structured alert object → Output: bilingual text         │ │
│  │  Stakeholder framing: agent / field officer / risk analyst        │ │
│  │  Banned words enforced in system prompt                          │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │              CASE & COORDINATION WORKFLOW (Seg 4)               │ │
│  │  Open → Assigned → Acknowledged → Escalated → Resolved          │ │
│  │  Audit trail: every state change logged                         │ │
│  │  Ownership: agent→field officer→area mgr→central ops→risk       │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                       │
│  ╔═════════════════════════════════════════════════════════════════╗ │
│  ║            PROVIDER REGISTRY — ISOLATION BOUNDARY              ║ │
│  ║                                                                 ║ │
│  ║  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐ ║ │
│  ║  │ bKash        │  │ Nagad        │  │ Rocket               │ ║ │
│  ║  │ Pipeline     │  │ Pipeline     │  │ Pipeline             │ ║ │
│  ║  │              │  │              │  │                      │ ║ │
│  ║  │ CANNOT read  │  │ CANNOT read  │  │ CANNOT read          │ ║ │
│  ║  │ Nagad/Rocket │  │ bKash/Rocket │  │ bKash/Nagad          │ ║ │
│  ║  └──────────────┘  └──────────────┘  └──────────────────────┘ ║ │
│  ║       Only ProviderRegistry aggregator can read across          ║ │
│  ╚═════════════════════════════════════════════════════════════════╝ │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │              SYNTHETIC DATA GENERATOR (Seg 1)                   │ │
│  │  Poisson arrivals × TOD multiplier × 1.8× pre-Eid surge        │ │
│  │  GT Event 1: Structuring burst (bKash, 17:10–17:28)            │ │
│  │  GT Event 2: Legitimate spike  (Nagad, 18:00–18:45)            │ │
│  │  GT Event 3: Feed delay        (Rocket, 16:30–16:45)           │ │
│  └─────────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────┘
```

## Data Flow

```
SyntheticDataGenerator
    │
    ├──▶ ProviderFeed[bKash]  ──▶ bKashPipeline  ─┐
    ├──▶ ProviderFeed[Nagad]  ──▶ NagadPipeline  ──┼──▶ ProviderRegistry
    └──▶ ProviderFeed[Rocket] ──▶ RocketPipeline ─┘         │
                                                              │
                                                    AnalyticsEngine
                                                              │
                                                    LLMNarrationLayer
                                                              │
                                                    CaseWorkflow
                                                              │
                                                    FastAPI Routes
                                                              │
                                                    Frontend Views
```

## Provider Boundary Contract

| What is allowed | What is NOT allowed |
|-----------------|---------------------|
| bKash pipeline reads bKash transactions | bKash pipeline reading Nagad balances |
| ProviderRegistry combining for display | Any pipeline modifying another's data |
| Analytics engine querying Registry | Direct inter-pipeline communication |
| Alert shows "bKash balance low" | Alert implying Nagad can fill bKash shortage |
| Confidence degrades when Rocket is stale | Silent confident output with stale Rocket data |

## Alert Lifecycle

```
Detection (Analytics Engine)
    │
    ▼
Alert Created (type, evidence, confidence, provider scope)
    │
    ▼
LLM Narration (bilingual text generated)
    │
    ▼
Case Opened (status=Open, owner=unassigned)
    │
    ▼
Case Assigned (status=Assigned, owner=field_officer)
    │
    ▼
Acknowledged (status=Acknowledged, timestamp logged)
    │
    ├──▶ Resolved (issue addressed, closure note added)
    │
    └──▶ Escalated (status=Escalated, owner=area_manager or risk_analyst)
              │
              └──▶ Resolved
```

## Guardrails (enforced throughout)

1. **Never write "fraud"** — use "unusual activity requiring review"
2. **Never display a merged wallet balance** — cash and e-money are always separate
3. **No PIN/OTP/credential fields** — not even placeholders
4. **Every alert carries confidence + evidence** — no bare "risk: high" badges
5. **Human review disclaimer** lives inside every alert card in the UI

## Frontend Architecture (Segment 5)

```
frontend/index.html — Single-File SPA (1,406 lines)
├── Design System (CSS custom properties)
│   ├── Dark theme with bKash pink (#e9149e) accent
│   ├── Confidence colors: green/amber/red
│   └── Inter + Noto Sans Bengali fonts
├── Layout Shell (CSS Grid)
│   ├── Top Bar (brand, role switcher, chaos toggle, sim clock)
│   ├── Sidebar Navigation (9 pages across 4 sections)
│   └── Main Content (page-switched views)
├── Role Switcher
│   ├── Agent — Bangla-first, mobile-optimized, supportive tone
│   ├── Field Officer — mixed language, coordination focus
│   └── Ops — English, full analytics, case management
└── JavaScript (vanilla, no framework)
    ├── apiFetch() — centralized API caller with error toasts
    ├── Page loaders (loadSummary, loadAlerts, loadCases, etc.)
    ├── Bilingual tab switching (EN / BN / Banglish)
    └── Case action handlers (assign, acknowledge, escalate, resolve)
```

### Why single-file SPA?
- **Zero build tooling** — open in browser, no `npm install` or bundler
- **Demo reliability** — no transpilation bugs, no hydration failures
- **Judge accessibility** — one file to review, easy to verify no banned words
- **Portable** — works on any machine with a browser and the backend running

### API Communication
All data flows through REST `fetch()` calls to the FastAPI backend. No WebSocket is used (unnecessary for the demo's polling model). The frontend never stores state locally — every view re-fetches from the backend, ensuring both sides of the dashboard always reflect the same truth.

## Validation Layer (Segment 6)

```
Ground Truth (private, never exposed via API)
        │
        └─── ValidationEngine ──── Analytics Output
                    │
             ┌──────┼──────┬──────────┬───────────┐
             │      │      │          │           │
          Anomaly  FP   Shortage  Narration   Workflow
          P/R/F1  Rate  Lead Time  Safety      Audit
```

The validation module reads ground truth from `backend/data/ground_truth.json` and compares against analytics output post-hoc. The detector never sees the answer key — this mirrors how a real audit works.

## Complete Endpoint Inventory (33 endpoints)

| Seg | Method | Endpoint | Purpose |
|-----|--------|----------|---------|
| 1 | GET | `/health` | Health check |
| 1 | GET | `/api/v1/system/health` | Provider feed health |
| 1 | GET | `/api/v1/data/summary` | Simulation summary |
| 1 | GET | `/api/v1/agents` | List all agents |
| 1 | GET | `/api/v1/agents/{id}` | Single agent view |
| 1 | GET | `/api/v1/transactions` | Query transactions |
| 1 | GET | `/api/v1/providers/{id}/balances` | Provider-specific balances |
| 2 | GET | `/api/v1/analytics/liquidity` | Liquidity projections |
| 2 | GET | `/api/v1/analytics/liquidity/{id}` | Agent liquidity |
| 2 | GET | `/api/v1/analytics/anomalies` | All anomalies |
| 2 | GET | `/api/v1/analytics/anomalies/{id}` | Agent anomalies |
| 2 | GET | `/api/v1/analytics/alerts` | Combined alerts |
| 2 | POST | `/api/v1/system/chaos/degrade/{id}` | Chaos: degrade feed |
| 2 | POST | `/api/v1/system/chaos/restore/{id}` | Chaos: restore feed |
| 2 | GET | `/api/v1/system/chaos/status` | Chaos toggle state |
| 3 | GET | `/api/v1/narration/alert/{idx}` | Bilingual narration |
| 3 | GET | `/api/v1/narration/alert/{idx}/stakeholder/{role}` | Stakeholder framing |
| 3 | GET | `/api/v1/narration/mode` | Narration mode |
| 4 | GET | `/api/v1/cases` | List cases |
| 4 | GET | `/api/v1/cases/summary` | Case board summary |
| 4 | GET | `/api/v1/cases/{id}` | Single case + audit |
| 4 | POST | `/api/v1/cases/create-from-alerts` | Create cases |
| 4 | POST | `/api/v1/cases/{id}/assign` | Assign case |
| 4 | POST | `/api/v1/cases/{id}/acknowledge` | Acknowledge case |
| 4 | POST | `/api/v1/cases/{id}/escalate` | Escalate case |
| 4 | POST | `/api/v1/cases/{id}/resolve` | Resolve case |
| 4 | POST | `/api/v1/cases/{id}/note` | Add case note |
| 4 | GET | `/api/v1/cases/{id}/audit` | Audit trail |
| 6 | GET | `/api/v1/metrics/validation` | Full validation report |
| 6 | GET | `/api/v1/metrics/anomaly` | Anomaly P/R/F1 |
| 6 | GET | `/api/v1/metrics/latency` | API latency P50/P95 |
| 6 | GET | `/api/v1/metrics/narration-safety` | Narration safety |
| 6 | GET | `/api/v1/metrics/ground-truth` | GT summary |

## Project File Structure

```
SuperAgent-LiquidityIQ/
├── backend/
│   ├── main.py                     # FastAPI app, all routes, startup logic
│   ├── models/
│   │   ├── data_models.py          # Core Pydantic models (Transaction, Agent, Feed...)
│   │   └── alert_models.py         # Alert envelope, confidence, classification
│   ├── data/
│   │   ├── generator.py            # Synthetic data generator (Seg 1)
│   │   ├── generated_data.json     # [gitignored] Generated simulation data
│   │   └── ground_truth.json       # [gitignored] Private GT events
│   ├── providers/
│   │   └── registry.py             # ProviderRegistry + ProviderPipeline isolation
│   ├── analytics/
│   │   ├── __init__.py
│   │   ├── liquidity.py            # Liquidity projector (Seg 2)
│   │   ├── anomaly.py              # Anomaly detector — structuring + z-score (Seg 2)
│   │   └── fallback.py             # Chaos toggle, AlertBuilder, confidence (Seg 2)
│   ├── narration/
│   │   └── __init__.py             # NarrationEngine, LLM + template modes (Seg 3)
│   ├── workflow/
│   │   └── __init__.py             # CaseManager, state machine, audit trail (Seg 4)
│   └── validation/
│       └── __init__.py             # ValidationEngine, all metrics (Seg 6)
├── frontend/
│   └── index.html                  # Two-sided dashboard SPA (Seg 5)
├── tests/
│   ├── test_segment1.py            # 8 exit tests
│   ├── test_segment2.py            # 7 exit tests
│   ├── test_segment3_4.py          # 8 exit tests
│   ├── test_segment5.py            # 11 exit tests
│   └── test_segment6.py            # 10 exit tests
├── docs/
│   ├── architecture.md             # This document
│   ├── api_reference.md            # Complete API reference (33 endpoints)
│   ├── development_prompts.md      # Segment 1 development prompt
│   ├── segment2_prompt.md          # Segment 2 development prompt
│   ├── segment3_4_prompt.md        # Segments 3 & 4 development prompt
│   ├── segment5_prompt.md          # Segment 5 development prompt
│   ├── segment6_prompt.md          # Segment 6 development prompt
│   ├── llm_prompts.md              # LLM system prompts & schemas
│   ├── data_simulation_note.md     # Data generation methodology
│   └── responsible_design.md       # Safety, privacy, limitations
├── .env.example                    # Environment config template
├── .gitignore
├── requirements.txt
└── README.md                       # Project overview & setup
```
