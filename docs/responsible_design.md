# Responsible Design Note

## Overview

This prototype is a **decision-support tool** only. It is designed to help human operators understand a complex situation — not to make decisions for them.

---

## What This Prototype Does NOT Do

| Action | Why it is excluded |
|--------|-------------------|
| Declare fraud or accuse anyone | Risk signals are probabilistic; human review is required before any real-world action |
| Block transactions, accounts, or agents | No prototype has the authority to do this; doing so would require regulatory approval and due process |
| Freeze or move funds | Out of scope; would require real financial system integration which this prototype intentionally lacks |
| Access real provider APIs, wallets, or balances | Only simulated/synthetic data is used |
| Convert balances between providers | Real interoperability requires provider agreements; this prototype never implies or suggests this |
| Collect PINs, OTPs, or passwords | No credential fields exist anywhere in the codebase |
| Make final compliance or regulatory decisions | These require qualified compliance professionals |

---

## Language and Framing

**Banned words** — never appear in UI, alerts, API responses, code comments, or documentation:
- "fraud" / "fraudulent"
- "scam"
- "illegal"
- "blocked account"
- "suspicious activity" (replaced with "unusual activity requiring review")

**Approved language**:
- "unusual transaction velocity detected"
- "requires operational review"
- "pattern flagged for human review"
- "anticipated seasonal demand spike"
- "elevated activity — likely normal; confirm before action"

---

## Human Review Requirement

Every risk alert in this system includes:
1. **Confidence level** (e.g., "High Confidence", "Low Confidence – Stale Data")
2. **Evidence** — the literal numbers that triggered the flag (count, amount range, account concentration)
3. **Uncertainty statement** — what the flag might represent (could be seasonal, could be data quality)
4. **Recommended next step** — always a human action (review, contact agent, escalate to risk team)
5. **Disclaimer** — "This is not a fraud determination. Human review is required before any action."

---

## Privacy

- All identifiers are synthetic (`AGT-`, `SYN-` prefixed)
- No names, phone numbers, NID numbers, or addresses
- No real transaction data
- No production API connections
- Data generation is deterministic with a fixed seed — fully reproducible

---

## False Positives

This prototype explicitly acknowledges false positive risk:
- A demand spike (e.g., Eid, payday) looks similar to some anomaly patterns
- The system includes a **legitimate spike test case** (Ground Truth Event 2) to verify the detector does not flag organic high-volume periods
- All flagged cases include uncertainty language
- Operators are trained to expect false positives and are instructed to confirm before escalating

---

## Provider Boundaries

- Each provider's data is isolated at the architecture level
- The prototype does not imply that one provider can see, control, or influence another's balance or operations
- Coordination features notify and assign; they do not bypass provider authorization
- No cross-provider balance transfers are suggested or implied

---

## Auditability

- Every case action (open, assign, acknowledge, escalate, resolve) is logged with:
  - Timestamp
  - Actor ID (role-based, synthetic)
  - Action performed
  - Data state at time of action
- Audit trail is append-only (no deletions)
- All alert evidence is stored with the alert (not reconstructed later)

---

## Limitations Stated Clearly

1. This is a 24-hour hackathon prototype, not a production system
2. It has not been validated on real transaction data
3. It has not received regulatory review or approval
4. The anomaly detector parameters are tuned for the synthetic scenario
5. Performance under real production load has not been tested
6. The LLM narration layer is probabilistic and its outputs must be reviewed by a human before any communication to agents or customers
