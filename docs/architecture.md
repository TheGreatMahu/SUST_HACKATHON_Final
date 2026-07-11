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
