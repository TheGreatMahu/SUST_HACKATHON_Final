"""
Segment 1 Exit Test
====================
Verifies all exit criteria before moving to Segment 2:

[PASS] Combined view shows shared cash + separate provider e-money (never merged)
[PASS] No code path allows bKash pipeline to read Nagad's raw data
[PASS] Ground truth events are present (structuring, legit_spike, feed_delay)
[PASS] Transaction counts are reasonable (> 500 total)
[PASS] Rocket feed is marked as degraded (delayed)
[PASS] Provider boundaries enforced in registry
"""

import sys
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.data.generator import SyntheticDataGenerator
from backend.models.data_models import Provider
from backend.providers.registry import ProviderRegistry, ProviderPipeline


def run_exit_test():
    print("=" * 60)
    print("SEGMENT 1 EXIT TEST")
    print("=" * 60)

    # Generate data
    gen = SyntheticDataGenerator()
    result = gen.generate()
    summary = result["summary"]

    # ----------------------------------------------------------------
    # Test 1: Transaction volume reasonable
    # ----------------------------------------------------------------
    total_txns = summary["total_transactions"]
    assert total_txns > 500, f"FAIL: Expected >500 transactions, got {total_txns}"
    print(f"[PASS] Test 1: {total_txns} transactions generated")

    # ----------------------------------------------------------------
    # Test 2: All 3 providers present
    # ----------------------------------------------------------------
    assert set(summary["providers"]) == {"bkash", "nagad", "rocket"}, "FAIL: Missing providers"
    print(f"[PASS] Test 2: All 3 providers present: {summary['providers']}")

    # ----------------------------------------------------------------
    # Test 3: Ground truth events present
    # ----------------------------------------------------------------
    gt = result["ground_truth"]
    gt_types = {e["event_type"] for e in gt}
    expected_gt = {"structuring_burst", "legitimate_spike", "feed_delay"}
    assert expected_gt == gt_types, f"FAIL: Missing GT events. Got: {gt_types}"
    print(f"[PASS] Test 3: Ground truth events: {gt_types}")

    # ----------------------------------------------------------------
    # Test 4: Build registry and verify isolation
    # ----------------------------------------------------------------
    from backend.models.data_models import ProviderFeed, AgentProfile

    feeds = {
        Provider(k): ProviderFeed(**v)
        for k, v in result["provider_feeds"].items()
    }
    agents = [AgentProfile(**a) for a in result["agents"]]
    pipelines = {prov: ProviderPipeline(prov, feed) for prov, feed in feeds.items()}
    registry = ProviderRegistry(pipelines, agents)

    # Test that bKash pipeline cannot access Nagad data
    bkash_pipeline = registry.get_pipeline(Provider.BKASH)
    bkash_txns = bkash_pipeline.get_transactions()
    cross_provider_leak = [t for t in bkash_txns if t.provider != Provider.BKASH]
    assert len(cross_provider_leak) == 0, f"FAIL: bKash pipeline returned {len(cross_provider_leak)} non-bKash transactions!"
    print(f"[PASS] Test 4: Provider isolation enforced - bKash pipeline returned 0 Nagad/Rocket txns")

    # ----------------------------------------------------------------
    # Test 5: Combined agent view never merges e-money balances
    # ----------------------------------------------------------------
    agent_ids = [a["agent_id"] for a in result["agents"]]
    for agent_id in agent_ids[:3]:
        view = registry.get_combined_agent_view(agent_id)
        assert view is not None, f"FAIL: No view for {agent_id}"

        # Check shared_cash and provider_balances are SEPARATE fields
        assert "shared_cash" in view, f"FAIL: Missing shared_cash in {agent_id}"
        assert "provider_balances" in view, f"FAIL: Missing provider_balances in {agent_id}"

        # Ensure no single "total_balance" field (would imply merging)
        assert "total_balance" not in view, f"FAIL: Found merged total_balance in {agent_id}!"

        # Each provider balance is separately keyed
        for prov_key, bal in view["provider_balances"].items():
            assert bal["provider"] == prov_key, f"FAIL: Provider mismatch in {agent_id}"

    print(f"[PASS] Test 5: All agent views show shared cash + separate provider balances, never merged")

    # ----------------------------------------------------------------
    # Test 6: Rocket feed marked as degraded
    # ----------------------------------------------------------------
    health = registry.health_summary()
    rocket_health = health["providers"]["rocket"]
    assert rocket_health["delay_seconds"] > 0, "FAIL: Rocket should show delay"
    assert not rocket_health["healthy"], "FAIL: Rocket feed should be marked unhealthy"
    print(f"[PASS] Test 6: Rocket feed degraded - delay={rocket_health['delay_seconds']}s, healthy={rocket_health['healthy']}")

    # ----------------------------------------------------------------
    # Test 7: Structuring burst has near-identical amounts + few accounts
    # ----------------------------------------------------------------
    struct_event = next(e for e in gt if e["event_type"] == "structuring_burst")
    struct_txn_ids = set(struct_event["injected_txn_ids"])

    # Find injected structuring txns in the bKash feed
    bkash_txns_all = bkash_pipeline.get_transactions()
    struct_txns = [t for t in bkash_txns_all if t.txn_id in struct_txn_ids]

    assert len(struct_txns) == 18, f"FAIL: Expected 18 structuring txns, got {len(struct_txns)}"

    amounts = [t.amount for t in struct_txns]
    amount_range = max(amounts) - min(amounts)
    assert amount_range < 500, f"FAIL: Structuring amounts too spread: range={amount_range}"

    unique_accounts = len({t.account_id for t in struct_txns})
    assert unique_accounts <= 3, f"FAIL: Structuring used {unique_accounts} accounts (expected <=3)"

    print(f"[PASS] Test 7: Structuring burst - 18 txns, amount_range=BDT{amount_range:.0f}, {unique_accounts} unique accounts")

    # ----------------------------------------------------------------
    # Test 8: Legit spike is organic (many accounts, varied amounts)
    # ----------------------------------------------------------------
    spike_event = next(e for e in gt if e["event_type"] == "legitimate_spike")
    spike_txn_ids = set(spike_event["injected_txn_ids"])

    nagad_pipeline = registry.get_pipeline(Provider.NAGAD)
    nagad_txns_all = nagad_pipeline.get_transactions()
    spike_txns = [t for t in nagad_txns_all if t.txn_id in spike_txn_ids]

    unique_spike_accounts = len({t.account_id for t in spike_txns})
    assert unique_spike_accounts >= 10, f"FAIL: Legit spike only {unique_spike_accounts} accounts (expected >=10)"

    spike_amounts = [t.amount for t in spike_txns]
    spike_range = max(spike_amounts) - min(spike_amounts)
    assert spike_range > 2000, f"FAIL: Legit spike amounts too similar: range={spike_range}"

    print(f"[PASS] Test 8: Legit spike - {unique_spike_accounts} unique accounts, amount_range=BDT{spike_range:.0f}")

    # ----------------------------------------------------------------
    print()
    print("=" * 60)
    print("ALL SEGMENT 1 EXIT TESTS PASSED [8/8]")
    print("=" * 60)
    print()
    print("Summary:")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    run_exit_test()
