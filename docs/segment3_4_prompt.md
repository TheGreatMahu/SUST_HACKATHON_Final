# Segment 3 & 4: Development Prompt — Narration & Case Workflow

## Segment 3: LLM Narration Layer

### Objective
Turn already-decided structured alerts (from Segment 2) into bilingual, stakeholder-appropriate human-readable text. The LLM **never decides risk** — it only phrases a decision already made transparently.

### Key Design Decisions

**Why LLM only here?**
The analytics engine (Segment 2) is deterministic — explainable and auditable. Introducing LLM into scoring would make the system a black box. The narration layer is the safe boundary: all numbers are already locked in, the LLM only chooses words.

**Three narration modes:**
1. `Bilingual Alert` — English + proper Bangla script + Banglish (romanized Bengali for low-end phones)
2. `Stakeholder Framing` — same alert, three different framings:
   - **Agent**: Bangla/Banglish, supportive, focus on "what to do right now"
   - **Field Officer**: Mixed language, coordination focus, visit + check cash
   - **Compliance Analyst**: English, statistical evidence, z-scores, escalation checklist

**Fallback strategy:**
If OpenAI API key is missing or call fails, template-based narration kicks in automatically. Templates use the same structured evidence to produce consistent output — rubric score is not dependent on an API key being present during demo.

**Banned words enforcement (two layers):**
1. System prompt — LLM instructed not to use banned words
2. Post-processing sanitizer — regex scan on all output, replaces violations with "unusual activity"

### Banned Words List
`fraud`, `fraudulent`, `scam`, `illegal`, `blocked`, `suspicious`, `malicious`, `criminal`, `blacklisted`

### Approved Terms
`unusual transaction velocity`, `elevated seasonal demand`, `requires operational review`, `unusual activity`, `pattern requires review`

### Exit Criteria (all passed)
1. ✅ Narration produces English + Bangla + Banglish
2. ✅ No banned words in any output (regex verified)
3. ✅ Human-review disclaimer in every English narration
4. ✅ Stakeholder framing produces role-appropriate output for all 3 roles
5. ✅ Narration mode auto-detects (llm vs. template)

### Files Created
- `backend/narration/__init__.py` — NarrationEngine, LLMNarrator, TemplateNarrator

---

## Segment 4: Case & Coordination Workflow

### Objective
Every alert becomes a trackable, ownable, auditable case. This is the rubric's "who received it, who owns it, what was the recommended action, what was the final status."

### State Machine
```
OPEN -> ASSIGNED -> ACKNOWLEDGED -> ESCALATED -> RESOLVED
```

### Ownership Hierarchy (Escalation Path)
```
agent (0) -> field_officer (1) -> area_manager (2) -> central_ops (3) -> risk_analyst (4)
```

### Audit Trail Design
- **Append-only** — no deletions ever
- Every entry records: timestamp, actor_id, actor_role, action, from_status, to_status, note
- Designed for rubric requirement: "important alerts, ownership changes, acknowledgements, escalations, evidence, and resolution actions should be traceable"

### Notification Log
- Every state change logs a `would_notify` entry with: target_role, target_id, channel, message
- Demo-safe: does not actually send notifications (no external deps), just proves the intent
- In production, would connect to SMS gateway / push notification service

### Key API Endpoints
| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/v1/cases/create-from-alerts` | Create cases from all current alerts (with narration) |
| GET | `/api/v1/cases` | List all cases (filterable) |
| POST | `/api/v1/cases/{id}/assign` | Assign to stakeholder |
| POST | `/api/v1/cases/{id}/acknowledge` | Mark acknowledged |
| POST | `/api/v1/cases/{id}/escalate` | Escalate to next level |
| POST | `/api/v1/cases/{id}/resolve` | Resolve with note |
| GET | `/api/v1/cases/{id}/audit` | Full audit trail |

### Exit Criteria (all passed)
1. ✅ Case created with all fields (evidence, disclaimer, narration, audit entry)
2. ✅ Full lifecycle: OPEN -> ASSIGNED -> ACKNOWLEDGED -> ESCALATED -> RESOLVED
3. ✅ Audit trail has 5 entries covering every state change
4. ✅ Notification log populated on assignment and escalation
5. ✅ Resolution note, resolved_at, resolved_by all set on resolve

### Files Created
- `backend/workflow/__init__.py` — CaseManager, Case, AuditEntry, state machine
