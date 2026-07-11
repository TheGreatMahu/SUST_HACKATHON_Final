"""
Segment 1: Synthetic Data Generator
=====================================
Generates a full simulated day of multi-provider MFS agent activity.

Design principles:
- Poisson arrival process modulated by time-of-day multipliers
- Pre-Eid evening surge applied
- Three labeled ground-truth events are injected at specific timestamps
- Provider boundaries enforced: each provider feed is generated independently

Ground-truth events injected:
  1. STRUCTURING_BURST  — near-identical amounts, short window, few accounts  (bKash, Agent-001)
  2. LEGITIMATE_SPIKE   — high volume but organic, no anomaly label          (Nagad, Agent-002)
  3. FEED_DELAY         — Rocket feed goes silent for 15 minutes             (Rocket, all agents)
"""

import random
import math
import uuid
from datetime import datetime, timedelta
from pathlib import Path
import json

from backend.models.data_models import (
    Provider, TransactionType, TransactionStatus,
    AreaName, AgentProfile, SharedCashBalance, ProviderBalance,
    Transaction, GroundTruthEvent, ProviderFeed,
    synth_account_id, synth_agent_id
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SEED = 42
SIM_DATE = datetime(2026, 6, 5)          # Day before Eid-ul-Adha (simulated)
SIM_START = SIM_DATE.replace(hour=8, minute=0, second=0)
SIM_END   = SIM_DATE.replace(hour=20, minute=0, second=0)

PROVIDERS = [Provider.BKASH, Provider.NAGAD, Provider.ROCKET]

AREAS = [
    {"name": AreaName.SYLHET_SADAR,  "thana": "Sylhet Sadar"},
    {"name": AreaName.ZINDABAZAR,    "thana": "Zindabazar"},
    {"name": AreaName.AMBARKHANA,    "thana": "Ambarkhana"},
]

# Agents: 5 agents, spread across 3 areas
AGENT_CONFIGS = [
    {"index": 1, "area_idx": 0, "name": "Rahim Uddin MFS Shop",   "providers": [Provider.BKASH, Provider.NAGAD, Provider.ROCKET]},
    {"index": 2, "area_idx": 0, "name": "Karim Telecom",          "providers": [Provider.BKASH, Provider.NAGAD]},
    {"index": 3, "area_idx": 1, "name": "Bismillah Mobile Shop",  "providers": [Provider.NAGAD, Provider.ROCKET]},
    {"index": 4, "area_idx": 1, "name": "Zindabazar MFS Point",   "providers": [Provider.BKASH, Provider.ROCKET]},
    {"index": 5, "area_idx": 2, "name": "Ambarkhana Digital",     "providers": [Provider.BKASH, Provider.NAGAD, Provider.ROCKET]},
]

# Base transaction rate: transactions per hour per provider per agent (during daytime)
BASE_RATE = 4.0

# Time-of-day multipliers (index = hour 0-23)
TOD_MULTIPLIER = {
    8: 0.6, 9: 1.0, 10: 1.2, 11: 1.4,
    12: 1.8, 13: 1.6, 14: 1.4, 15: 1.2,
    16: 1.4, 17: 2.5,  # pre-Eid evening peak
    18: 3.0, 19: 2.0, 20: 0.5
}

# Pre-Eid multiplier applied uniformly to all providers
PRE_EID_MULTIPLIER = 1.8

# Transaction type distribution (cash_out heavy for pre-Eid)
TXN_TYPE_WEIGHTS = {
    TransactionType.CASH_OUT:   0.52,
    TransactionType.CASH_IN:    0.20,
    TransactionType.SEND_MONEY: 0.15,
    TransactionType.PAYMENT:    0.08,
    TransactionType.RECHARGE:   0.05,
}

# Amount ranges by type (BDT)
AMOUNT_RANGES = {
    TransactionType.CASH_OUT:   (500,  20000),
    TransactionType.CASH_IN:    (500,  30000),
    TransactionType.SEND_MONEY: (200,  10000),
    TransactionType.PAYMENT:    (50,   5000),
    TransactionType.RECHARGE:   (50,   500),
}

# Provider e-money limits
EMONEY_LIMITS = {
    Provider.BKASH:  200000,
    Provider.NAGAD:  150000,
    Provider.ROCKET: 100000,
}

# Opening balances (provider e-money)
OPENING_EMONEY = {
    Provider.BKASH:  (80000,  140000),
    Provider.NAGAD:  (50000,  100000),
    Provider.ROCKET: (30000,   70000),
}

# Opening physical cash
OPENING_CASH = (60000, 120000)

# Ground-truth injection windows
GT_STRUCTURING_START = SIM_DATE.replace(hour=17, minute=10)
GT_STRUCTURING_END   = SIM_DATE.replace(hour=17, minute=28)
GT_STRUCTURING_AGENT = "AGT-SYL-001"
GT_STRUCTURING_PROV  = Provider.BKASH

GT_LEGIT_SPIKE_START = SIM_DATE.replace(hour=18, minute=0)
GT_LEGIT_SPIKE_END   = SIM_DATE.replace(hour=18, minute=45)
GT_LEGIT_SPIKE_AGENT = "AGT-SYL-002"
GT_LEGIT_SPIKE_PROV  = Provider.NAGAD

GT_FEED_DELAY_START  = SIM_DATE.replace(hour=16, minute=30)
GT_FEED_DELAY_END    = SIM_DATE.replace(hour=16, minute=45)
GT_FEED_DELAY_PROV   = Provider.ROCKET


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def rng(seed: int = SEED):
    r = random.Random(seed)
    return r

def poisson_arrivals(rate_per_hour: float, duration_minutes: float, r: random.Random) -> list[float]:
    """Return sorted list of offsets (in seconds) for Poisson arrivals."""
    n = r.randint(0, int(rate_per_hour * duration_minutes / 60 * 3))
    arrivals = sorted(r.uniform(0, duration_minutes * 60) for _ in range(n))
    return arrivals

def pick_txn_type(r: random.Random) -> TransactionType:
    types = list(TXN_TYPE_WEIGHTS.keys())
    weights = list(TXN_TYPE_WEIGHTS.values())
    return r.choices(types, weights=weights, k=1)[0]

def pick_amount(txn_type: TransactionType, r: random.Random) -> float:
    lo, hi = AMOUNT_RANGES[txn_type]
    # Log-normal-ish: sample uniformly in log space
    log_lo, log_hi = math.log(lo), math.log(hi)
    return round(math.exp(r.uniform(log_lo, log_hi)), -1)  # round to nearest 10

def pick_account(provider: Provider, agent_id: str, account_pool: list[str], r: random.Random) -> str:
    return r.choice(account_pool)


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class SyntheticDataGenerator:
    def __init__(self):
        self.r = rng(SEED)
        self.agents: list[AgentProfile] = []
        self.provider_feeds: dict[Provider, ProviderFeed] = {}
        self.ground_truth: list[GroundTruthEvent] = []
        self.all_transactions: list[Transaction] = []

    # ------------------------------------------------------------------
    # Step 1: Build agent profiles
    # ------------------------------------------------------------------
    def _build_agents(self) -> list[AgentProfile]:
        agents = []
        for cfg in AGENT_CONFIGS:
            area_info = AREAS[cfg["area_idx"]]
            agent_id = synth_agent_id(area_info["name"].value, cfg["index"])
            providers = cfg["providers"]

            shared_cash = SharedCashBalance(
                agent_id=agent_id,
                cash_amount=self.r.uniform(*OPENING_CASH),
                last_updated=SIM_START,
            )

            provider_balances: dict[Provider, ProviderBalance] = {}
            for prov in providers:
                lo, hi = OPENING_EMONEY[prov]
                provider_balances[prov] = ProviderBalance(
                    provider=prov,
                    agent_id=agent_id,
                    emoney_balance=round(self.r.uniform(lo, hi), 2),
                    emoney_limit=EMONEY_LIMITS[prov],
                    last_updated=SIM_START,
                )

            agents.append(AgentProfile(
                agent_id=agent_id,
                name=cfg["name"],
                area=area_info["name"],
                thana=area_info["thana"],
                active_providers=providers,
                shared_cash=shared_cash,
                provider_balances=provider_balances,
            ))
        return agents

    # ------------------------------------------------------------------
    # Step 2: Build account pools per provider (synthetic IDs only)
    # ------------------------------------------------------------------
    def _build_account_pools(self) -> dict[tuple[str, Provider], list[str]]:
        pools: dict[tuple[str, Provider], list[str]] = {}
        for agent in self.agents:
            for prov in agent.active_providers:
                key = (agent.agent_id, prov)
                pool = [synth_account_id(prov, f"{agent.agent_id}-{i:04d}") for i in range(60)]
                pools[key] = pool
        return pools

    # ------------------------------------------------------------------
    # Step 3: Generate organic transactions for one agent+provider combo
    # ------------------------------------------------------------------
    def _gen_organic_txns(
        self,
        agent_id: str,
        provider: Provider,
        account_pool: list[str],
    ) -> list[Transaction]:
        txns = []
        current = SIM_START
        seed_offset = hash(f"{agent_id}-{provider.value}") % 10000

        while current < SIM_END:
            hour = current.hour
            tod_mult = TOD_MULTIPLIER.get(hour, 1.0)
            effective_rate = BASE_RATE * tod_mult * PRE_EID_MULTIPLIER

            # Skip Rocket feed delay window
            if provider == Provider.ROCKET and GT_FEED_DELAY_START <= current <= GT_FEED_DELAY_END:
                current += timedelta(minutes=1)
                continue

            arrivals = poisson_arrivals(effective_rate, 60, rng(seed_offset))
            for offset_sec in arrivals:
                ts = current + timedelta(seconds=offset_sec)
                if ts >= SIM_END:
                    break

                # Skip structuring window (will inject separately)
                if (provider == GT_STRUCTURING_PROV
                        and agent_id == GT_STRUCTURING_AGENT
                        and GT_STRUCTURING_START <= ts <= GT_STRUCTURING_END):
                    continue

                txn_type = pick_txn_type(self.r)
                amount   = pick_amount(txn_type, self.r)
                account  = pick_account(provider, agent_id, account_pool, self.r)

                txns.append(Transaction(
                    provider=provider,
                    agent_id=agent_id,
                    account_id=account,
                    txn_type=txn_type,
                    amount=amount,
                    timestamp=ts,
                    status=TransactionStatus.SUCCESS if self.r.random() > 0.03 else TransactionStatus.FAILED,
                ))
                seed_offset += 1

            current += timedelta(hours=1)

        return txns

    # ------------------------------------------------------------------
    # Step 4: Inject structuring burst (Ground Truth Event 1)
    # ------------------------------------------------------------------
    def _inject_structuring(self, account_pool: list[str]) -> tuple[list[Transaction], GroundTruthEvent]:
        """
        Inject a structuring/smurfing pattern:
        - 18 transactions in 18 minutes
        - Amounts: near-identical, clustered around 9,500 BDT ± 200
        - Only 3 distinct accounts (high concentration)
        - All cash_out on bKash, agent AGT-SYL-001
        """
        structuring_accounts = account_pool[:3]   # only 3 distinct accounts
        txns = []
        base_amount = 9500.0
        txn_ids = []

        for i in range(18):
            ts = GT_STRUCTURING_START + timedelta(minutes=i)
            amount = round(base_amount + self.r.uniform(-150, 150), -1)
            account = structuring_accounts[i % 3]

            t = Transaction(
                provider=GT_STRUCTURING_PROV,
                agent_id=GT_STRUCTURING_AGENT,
                account_id=account,
                txn_type=TransactionType.CASH_OUT,
                amount=amount,
                timestamp=ts,
                status=TransactionStatus.SUCCESS,
            )
            t._injected_label = "structuring_burst"
            txns.append(t)
            txn_ids.append(t.txn_id)

        gt_event = GroundTruthEvent(
            event_type="structuring_burst",
            provider=GT_STRUCTURING_PROV,
            agent_id=GT_STRUCTURING_AGENT,
            start_time=GT_STRUCTURING_START,
            end_time=GT_STRUCTURING_END,
            injected_txn_ids=txn_ids,
            notes="18 near-identical cash-out transactions in 18 minutes from 3 accounts",
        )
        return txns, gt_event

    # ------------------------------------------------------------------
    # Step 5: Inject legitimate spike (Ground Truth Event 2)
    # ------------------------------------------------------------------
    def _inject_legit_spike(self, account_pool: list[str]) -> tuple[list[Transaction], GroundTruthEvent]:
        """
        Inject an organic pre-Eid demand spike:
        - High volume but many distinct accounts
        - Varied amounts (not near-identical)
        - Normal organic pattern — should NOT trigger anomaly
        """
        txns = []
        txn_ids = []
        n = 35  # elevated count, but organic

        for i in range(n):
            ts = GT_LEGIT_SPIKE_START + timedelta(minutes=self.r.uniform(0, 45))
            txn_type = TransactionType.CASH_OUT if self.r.random() < 0.7 else TransactionType.SEND_MONEY
            amount = pick_amount(txn_type, self.r)
            account = self.r.choice(account_pool)  # many distinct accounts

            t = Transaction(
                provider=GT_LEGIT_SPIKE_PROV,
                agent_id=GT_LEGIT_SPIKE_AGENT,
                account_id=account,
                txn_type=txn_type,
                amount=amount,
                timestamp=ts,
                status=TransactionStatus.SUCCESS,
            )
            t._injected_label = "legitimate_spike"
            txns.append(t)
            txn_ids.append(t.txn_id)

        gt_event = GroundTruthEvent(
            event_type="legitimate_spike",
            provider=GT_LEGIT_SPIKE_PROV,
            agent_id=GT_LEGIT_SPIKE_AGENT,
            start_time=GT_LEGIT_SPIKE_START,
            end_time=GT_LEGIT_SPIKE_END,
            injected_txn_ids=txn_ids,
            notes="Legitimate pre-Eid demand spike — high volume, many distinct accounts, varied amounts. Must NOT be flagged as anomaly.",
        )
        return txns, gt_event

    # ------------------------------------------------------------------
    # Step 6: Inject feed delay (Ground Truth Event 3)
    # ------------------------------------------------------------------
    def _inject_feed_delay(self) -> GroundTruthEvent:
        """
        Rocket feed goes silent for GT_FEED_DELAY_START to GT_FEED_DELAY_END.
        No transactions are generated in that window for any agent (already skipped in _gen_organic_txns).
        The GroundTruthEvent marks when the feed resumes.
        """
        return GroundTruthEvent(
            event_type="feed_delay",
            provider=GT_FEED_DELAY_PROV,
            agent_id="ALL",
            start_time=GT_FEED_DELAY_START,
            end_time=GT_FEED_DELAY_END,
            notes="Rocket provider feed delayed for 15 minutes. All Rocket data from this window is missing. Confidence must degrade.",
        )

    # ------------------------------------------------------------------
    # Master generate() call
    # ------------------------------------------------------------------
    def generate(self) -> dict:
        print("[Segment 1] Building agent profiles...")
        self.agents = self._build_agents()
        account_pools = self._build_account_pools()

        all_transactions: list[Transaction] = []
        gt_events: list[GroundTruthEvent] = []

        print("[Segment 1] Generating organic transactions...")
        for agent in self.agents:
            for prov in agent.active_providers:
                pool = account_pools[(agent.agent_id, prov)]
                txns = self._gen_organic_txns(agent.agent_id, prov, pool)
                all_transactions.extend(txns)

        print("[Segment 1] Injecting ground-truth events...")

        # GT Event 1: structuring
        struct_pool = account_pools.get((GT_STRUCTURING_AGENT, GT_STRUCTURING_PROV), [])
        if struct_pool:
            struct_txns, struct_gt = self._inject_structuring(struct_pool)
            all_transactions.extend(struct_txns)
            gt_events.append(struct_gt)

        # GT Event 2: legitimate spike
        spike_pool = account_pools.get((GT_LEGIT_SPIKE_AGENT, GT_LEGIT_SPIKE_PROV), [])
        if spike_pool:
            spike_txns, spike_gt = self._inject_legit_spike(spike_pool)
            all_transactions.extend(spike_txns)
            gt_events.append(spike_gt)

        # GT Event 3: feed delay
        delay_gt = self._inject_feed_delay()
        gt_events.append(delay_gt)

        # Sort all transactions by timestamp
        all_transactions.sort(key=lambda t: t.timestamp)
        self.all_transactions = all_transactions

        print(f"[Segment 1] Generated {len(all_transactions)} total transactions.")
        print(f"[Segment 1] Ground-truth events: {[e.event_type for e in gt_events]}")

        # Build provider feeds (provider-isolated snapshots)
        provider_feeds: dict[str, ProviderFeed] = {}
        for prov in PROVIDERS:
            prov_txns = [t for t in all_transactions if t.provider == prov]
            prov_balances = []
            for agent in self.agents:
                if prov in agent.provider_balances:
                    bal = agent.provider_balances[prov]
                    # Mark stale for Rocket during delay window
                    if (prov == Provider.ROCKET
                            and GT_FEED_DELAY_START <= SIM_START <= GT_FEED_DELAY_END):
                        bal = bal.model_copy(update={"data_fresh": False, "stale_since": GT_FEED_DELAY_START})
                    prov_balances.append(bal)

            feed_healthy = not (prov == Provider.ROCKET)  # Rocket had a delay
            provider_feeds[prov.value] = ProviderFeed(
                provider=prov,
                snapshot_time=SIM_END,
                agent_balances=prov_balances,
                transactions=prov_txns,
                feed_healthy=feed_healthy,
                delay_seconds=900 if prov == Provider.ROCKET else 0,
                missing_agents=[],
            )

        self.provider_feeds = provider_feeds
        self.ground_truth   = gt_events

        return {
            "agents": [a.model_dump(mode="json") for a in self.agents],
            "provider_feeds": {k: v.model_dump(mode="json") for k, v in provider_feeds.items()},
            "ground_truth": [e.model_dump(mode="json") for e in gt_events],
            "summary": {
                "total_transactions": len(all_transactions),
                "agents": len(self.agents),
                "providers": [p.value for p in PROVIDERS],
                "sim_date": SIM_DATE.isoformat(),
                "ground_truth_events": len(gt_events),
                "txns_by_provider": {
                    prov.value: len([t for t in all_transactions if t.provider == prov])
                    for prov in PROVIDERS
                },
                "txns_by_type": {
                    tt.value: len([t for t in all_transactions if t.txn_type == tt])
                    for tt in TransactionType
                },
            }
        }
