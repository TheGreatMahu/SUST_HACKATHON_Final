# Data & Simulation Note

## Overview

All data in this prototype is **100% synthetic**. No real customer identities, balances, transaction histories, or credentials were used at any stage.

## Generation Methodology

### Agent Ecosystem
- **5 agents** across **3 thanas** (Sylhet Sadar, Zindabazar, Ambarkhana)
- Each agent has one **shared physical cash drawer** and separate e-money balances for each of their active providers
- Providers per agent: some serve all 3 (bKash + Nagad + Rocket), others serve 2

### Synthetic Identifiers
| Identifier type | Format | Example |
|----------------|--------|---------|
| Agent ID | `AGT-{AREA}-{INDEX}` | `AGT-SYL-001` |
| Account ID | `SYN-{PROV}-{AGENT}-{N}` | `SYN-BKA-AGT-SYL-001-0023` |
| Transaction ID | UUID4 | `550e8400-e29b-41d4-...` |

No names, phone numbers, NID numbers, or other PII are present.

### Transaction Arrival Process

```
rate(hour) = BASE_RATE × TOD_MULTIPLIER[hour] × PRE_EID_MULTIPLIER
```

- **BASE_RATE**: 4 transactions/hour/provider/agent during normal daytime
- **Pre-Eid multiplier**: 1.8× applied uniformly (simulates Eid-ul-Adha eve surge)
- **Time-of-day multipliers**:
  - Morning (8–9): 0.6–1.0×
  - Midday (12): 1.8× (lunch peak)
  - Evening (17–18): 2.5–3.0× (pre-Eid rush)
- **Arrival distribution**: Poisson (Poisson samples rounded to integer counts per hour)
- **Random seed**: 42 (fully reproducible)

### Balance Initialization
| Provider | e-Money range | Limit |
|----------|--------------|-------|
| bKash    | BDT 80,000–140,000 | BDT 200,000 |
| Nagad    | BDT 50,000–100,000 | BDT 150,000 |
| Rocket   | BDT 30,000–70,000  | BDT 100,000 |

Shared physical cash: BDT 60,000–120,000 per agent

### Transaction Type Distribution
| Type | Weight | Pre-Eid rationale |
|------|--------|------------------|
| Cash-out | 52% | Dominant — family cash needs before Eid |
| Cash-in | 20% | Float replenishment |
| Send money | 15% | Remittances to family |
| Payment | 8% | Bills, purchases |
| Recharge | 5% | Mobile top-ups |

### Transaction failure rate: 3% uniform

---

## Ground-Truth Injected Events

Three labeled events are deliberately injected into the synthetic data. Their ground-truth log is saved to `backend/data/ground_truth.json` and is **never exposed through the API** (used only by the Segment 6 validation module).

### Event 1: Structuring Burst
- **Type**: Anomaly — structuring/smurfing pattern
- **Provider**: bKash
- **Agent**: AGT-SYL-001
- **Window**: 17:10 – 17:28 (18 minutes)
- **Pattern**: 18 cash-out transactions
  - Amounts: BDT 9,500 ± 150 (near-identical, within BDT 300 spread)
  - Distinct accounts: exactly 3 (high concentration)
  - Each account appears 6 times
- **Expected behavior**: Anomaly detector MUST flag this
- **Expected false-positive rate**: 0% on legitimate spike (Event 2)

### Event 2: Legitimate Demand Spike
- **Type**: Normal — pre-Eid demand
- **Provider**: Nagad
- **Agent**: AGT-SYL-002
- **Window**: 18:00 – 18:45
- **Pattern**: 35 transactions
  - Amounts: varied (BDT 500–15,000, range > BDT 5,000)
  - Distinct accounts: 35+ (many unique customers)
  - Mix of cash-out and send-money
- **Expected behavior**: Anomaly detector MUST NOT flag this (false positive test)
- **Anomaly label**: None — clean organic spike

### Event 3: Provider Feed Delay
- **Type**: Data quality / reliability incident
- **Provider**: Rocket
- **Agents**: All agents
- **Window**: 16:30 – 16:45 (15 minutes)
- **Pattern**: Zero Rocket transactions generated in this window (feed silent)
- **Expected behavior**: Confidence must visibly degrade; system must warn about missing data; no confident conclusions may be drawn about Rocket balances

---

## Assumptions

1. Cash balance is treated as a snapshot (opening balance minus net cash flow implied by transaction types). Real-time cash tracking is simulated, not implemented as a live ledger.
2. Provider e-money limits are illustrative. Actual limits set by bKash, Nagad, and Rocket are not represented.
3. Transaction amounts use a log-uniform distribution to approximate realistic MFS transaction skew (most are small, some are large).
4. The "baseline" transaction rate (4/hour) is an approximation. Real agent throughput varies significantly by location, season, and day of week.
5. The 3% failure rate is uniform. Real failure rates vary by provider, transaction type, and network conditions.

## Limitations

1. No multi-agent coordination in the transaction data — transactions are generated independently per agent.
2. No circular or chained transactions simulated (would require a graph model).
3. Cash balance is not tracked in real-time within the generator; it is computed analytically by the analytics engine in Segment 2.
4. Provider feed "delay" is simulated by omitting transactions and flagging the feed; real delays would involve timestamp discrepancies and buffering.

## False-Positive Risk

The structuring detector is tuned specifically for the injected pattern. Real production deployment would require:
- Broader baseline data
- Per-agent historical calibration
- Human review for all flagged cases (never automated action)

Expected false positives in this simulation: **0 on the legitimate spike window** (the key test case). Real-world false-positive rate for a structuring detector of this type is typically 5–15% without calibration.
