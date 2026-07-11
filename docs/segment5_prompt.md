# Segment 5: Development Prompt — Two-Sided Dashboard

## Objective
Build two views on one shared state — an agent-facing mobile-first view (Bangla-first) and an operations/risk desktop view (English) — because a single messy screen reads as less thought-through even if the backend is solid.

## Key Design Decisions

### Why a single-file SPA?
For a 24-hour hackathon, a single `index.html` with inline CSS + JS eliminates build tooling overhead. The file is self-contained — open it in any browser with the backend running and everything works. No `npm install`, no Vite, no React hydration bugs. This decision prioritizes **reliability and demo stability** over developer ergonomics.

### Why dark mode with bKash pink accent?
The dashboard is used by operations staff and agents, often in low-light environments (shop counters, evening shifts). Dark mode reduces eye strain. The bKash pink (`#e9149e`) accent color signals the competition context while providing high contrast against the dark surface. The color palette is designed to be immediately recognizable as premium and domain-specific.

### Architecture: Two-Sided, One State
Both views read from the same underlying FastAPI backend state. The role switcher (`Agent` / `Field Officer` / `Ops`) controls which view is rendered, but the data source is identical. This ensures:
- An alert that appears on the agent's view is the same object rendered on the ops view
- Case status changes propagate to both views without sync issues
- Provider isolation is visually enforced (ops view never shows cross-provider raw data)

### Why role-based views matter for the rubric
The problem statement Section 5 lists six different stakeholders with different needs. The rubric's "User Experience and Explainability" (10%) explicitly evaluates "clarity and usefulness for agents, provider operations users, outlet coordinators, and risk reviewers." A role switcher directly addresses this.

## Feature Inventory

### Global Chrome
| Feature | Purpose | Rubric Line |
|---------|---------|-------------|
| Top bar with brand | Identifies the product, shows narration mode (LLM/template) | Presentation |
| Role switcher (Agent/Field Officer/Ops) | Switches between stakeholder-specific views | UX/Explainability |
| Chaos toggle button | Live Scenario C demo — degrade Rocket feed on demand | Technical Implementation |
| Provider health strip | Shows bKash/Nagad/Rocket feed status with delay indicators | Reliability |
| Simulation clock | Shows the simulated date/time for demo context | Presentation |

### Sidebar Navigation
| Section | Pages |
|---------|-------|
| Overview | Dashboard (default landing page) |
| Analytics | Alert Center, Liquidity, Anomalies |
| Workflow | Case Board |
| Data | Agent Table, Transaction Log |
| System | Provider Health, Validation Metrics |

### Dashboard Overview (Landing Page)
- **Summary cards**: Total transactions, total agents, alert count, provider count
- **Provider health strip**: bKash/Nagad/Rocket with health dot + delay indicator
- **Alert severity breakdown**: Critical/Warning/Info with color-coded stat cards
- **Classification distribution**: Likely Normal / Data Quality / Requires Review counts

### Alert Center
- **Full alert list** with severity badges, classification tags, confidence indicators
- **Evidence expansion**: click to see literal numbers (txn count, CV, z-score, amounts)
- **Bilingual tabs**: English / Bangla / Banglish narration for each alert
- **Human-review disclaimer** visible on every alert card
- **Recommended action** shown for each alert

### Liquidity View
- **Per-agent liquidity projections**: shared cash + per-provider e-money
- **Minutes remaining** with color coding (red < 30min, amber < 60min, green = safe)
- **Velocity indicator**: BDT/hour outflow rate
- **Confidence badge** on each projection

### Case Board
- **Kanban-style columns**: Open → Assigned → Acknowledged → Escalated → Resolved
- **Case cards**: title, severity, provider, agent, narration snippet
- **Action buttons**: Assign → Acknowledge → Escalate → Resolve
- **Case count per column**
- **Full audit trail** accessible per case

### Agent Table
- **Tabular view**: Agent ID, name, area, shared cash, per-provider e-money (NEVER merged)
- **Data freshness indicators** per provider per agent
- **Provider balance bars** (visual, separate, never summed)

### Transaction Log
- **Last 100 transactions** with columns: Time, Agent, Provider, Type, Amount, Status, Account
- **Color-coded** transaction types and statuses
- **Provider badge** per transaction

### Validation Metrics Page
- **Full validation report**: anomaly P/R/F1, FP rate, narration safety, workflow audit
- **Pass/fail badges** per metric
- **JSON detail** expandable for raw numbers

## Two Sides Implementation

### Agent View (Mobile/Responsive)
- **Bangla/Banglish first** — narration tabs default to Bangla
- **Cash runway** as the headline number ("45 minutes of cash left")
- **Simplified alert cards** with supportive tone
- **Single-tap actions** (Acknowledge, Request Help)
- **Responsive layout** — sidebar collapses on small screens

### Ops/Risk View (Desktop)
- **English first** — narration tabs default to English
- **System-wide health** as the headline (provider status, total alerts, classification breakdown)
- **Case board** with full escalation controls
- **Deep-dive evidence** — z-scores, CVs, composite scores visible
- **Provider-scoped data** — ops view never shows cross-provider raw data

## Technology Choices

| Choice | Rationale |
|--------|-----------|
| Vanilla HTML/CSS/JS | No build step, no framework bugs during demo |
| CSS custom properties (design tokens) | Consistent theming, easy dark mode |
| `fetch()` API calls | Direct REST communication with FastAPI backend |
| Google Fonts (Inter + Noto Sans Bengali) | Professional typography + proper Bangla rendering |
| CSS Grid + Flexbox | Responsive layout without CSS framework overhead |

## API Integration

The frontend calls the following backend endpoints:
- `GET /api/v1/data/summary` — simulation summary
- `GET /api/v1/system/health` — provider feed health
- `GET /api/v1/analytics/alerts` — all alerts with evidence
- `GET /api/v1/analytics/liquidity` — liquidity projections
- `GET /api/v1/analytics/anomalies` — anomaly detections
- `GET /api/v1/narration/alert/{index}` — bilingual narration
- `GET /api/v1/cases` — case board data
- `POST /api/v1/cases/create-from-alerts` — create cases from alerts
- `POST /api/v1/cases/{id}/assign` — assign case
- `POST /api/v1/cases/{id}/acknowledge` — acknowledge case
- `POST /api/v1/cases/{id}/escalate` — escalate case
- `POST /api/v1/cases/{id}/resolve` — resolve case
- `GET /api/v1/agents` — agent table
- `GET /api/v1/transactions` — transaction log
- `GET /api/v1/metrics/validation` — validation report
- `POST /api/v1/system/chaos/degrade/{provider}` — chaos toggle
- `POST /api/v1/system/chaos/restore/{provider}` — chaos restore

## Exit Criteria (all passed)
1. ✅ Dashboard renders with dark mode, bKash pink accent, Inter + Noto Sans Bengali fonts
2. ✅ Role switcher toggles between Agent / Field Officer / Ops views
3. ✅ Provider health strip shows bKash, Nagad, Rocket with health/degraded status
4. ✅ Alert cards show: type, classification, severity, confidence, evidence, narration, disclaimer
5. ✅ Bilingual tabs show English / Bangla / Banglish for each alert
6. ✅ Case board shows Kanban columns with working Assign → Acknowledge → Escalate → Resolve flow
7. ✅ Agent table shows shared cash + separate provider balances, NEVER merged
8. ✅ Transaction log shows provider-scoped, color-coded transaction data
9. ✅ Chaos toggle button triggers Scenario C (feed degradation) live
10. ✅ No banned words appear anywhere in the UI text
11. ✅ Human-review disclaimer visible on every alert card

## Files Created
- `frontend/index.html` — Single-file SPA (1,406 lines)
