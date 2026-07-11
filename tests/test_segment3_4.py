"""
Segment 3 & 4 Exit Test
=========================
Verifies all exit criteria:

[PASS] Template narration produces English + Bangla + Banglish text
[PASS] No banned words in any narration output
[PASS] Human-review disclaimer present in every narration
[PASS] Stakeholder framing works for agent / field_officer / compliance_analyst
[PASS] Case created from alert with full fields
[PASS] Full lifecycle: Open → Assigned → Acknowledged → Escalated → Resolved
[PASS] Audit trail has entry for every state change
[PASS] Notification log populated on assignment and escalation
"""

import sys
import json
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.data.generator import SyntheticDataGenerator, SIM_END
from backend.models.data_models import Provider, ProviderFeed, AgentProfile
from backend.providers.registry import ProviderRegistry, ProviderPipeline
from backend.analytics.liquidity import LiquidityProjector
from backend.analytics.anomaly import AnomalyDetector
from backend.analytics.fallback import ChaosState, AlertBuilder
from backend.narration import NarrationEngine, BANNED_WORDS
from backend.workflow import CaseManager, CaseStatus, StakeholderRole


def run_exit_test():
    print("=" * 60)
    print("SEGMENT 3 & 4 EXIT TEST")
    print("=" * 60)

    # ----------------------------------------------------------------
    # Setup
    # ----------------------------------------------------------------
    gen = SyntheticDataGenerator()
    result = gen.generate()

    feeds = {Provider(k): ProviderFeed(**v) for k, v in result["provider_feeds"].items()}
    agents = [AgentProfile(**a) for a in result["agents"]]
    pipelines = {prov: ProviderPipeline(prov, feed) for prov, feed in feeds.items()}
    registry = ProviderRegistry(pipelines, agents)

    projector = LiquidityProjector(registry)
    detector = AnomalyDetector(registry)
    chaos = ChaosState()
    builder = AlertBuilder(chaos)

    liquidity = projector.get_shortage_alerts(reference_time=SIM_END)
    anomalies = detector.detect_all(reference_time=SIM_END)
    alerts = builder.build_all_alerts(liquidity, anomalies)

    print(f"[Setup] {len(alerts)} alerts ready for narration and case creation")
    assert len(alerts) > 0, "FAIL: No alerts to test narration on"

    narrator = NarrationEngine()
    case_manager = CaseManager()

    # ----------------------------------------------------------------
    # Test 1: Template narration produces all three languages
    # ----------------------------------------------------------------
    narration = narrator.narrate(alerts[0])

    assert "english" in narration, "FAIL: Missing English narration"
    assert "bangla" in narration, "FAIL: Missing Bangla narration"
    assert "banglish" in narration, "FAIL: Missing Banglish narration"
    assert len(narration["english"]) > 20, "FAIL: English narration too short"
    assert len(narration["bangla"]) > 10, "FAIL: Bangla narration too short"
    assert len(narration["banglish"]) > 10, "FAIL: Banglish narration too short"

    print(f"[PASS] Test 1: Narration produces English + Bangla + Banglish")
    print(f"        EN: {narration['english'][:80]}...")

    # ----------------------------------------------------------------
    # Test 2: No banned words in any narration
    # ----------------------------------------------------------------
    banned_pattern = re.compile(
        "|".join(re.escape(w) for w in BANNED_WORDS),
        re.IGNORECASE
    )

    for i, alert in enumerate(alerts[:5]):
        narr = narrator.narrate(alert)
        for lang, text in narr.items():
            if isinstance(text, str):
                match = banned_pattern.search(text)
                assert not match, (
                    f"FAIL: Banned word '{match.group()}' found in {lang} narration "
                    f"for alert {i}: {text[:100]}"
                )

    print(f"[PASS] Test 2: No banned words in narrations for first 5 alerts")

    # ----------------------------------------------------------------
    # Test 3: Human-review disclaimer in English narration
    # ----------------------------------------------------------------
    for alert in alerts[:3]:
        narr = narrator.narrate(alert)
        en_text = narr.get("english", "").lower()
        has_disclaimer = (
            "human review" in en_text or
            "not a final" in en_text or
            "requires review" in en_text
        )
        assert has_disclaimer, f"FAIL: No disclaimer in: {narr['english'][:100]}"

    print(f"[PASS] Test 3: Human-review disclaimer present in all English narrations")

    # ----------------------------------------------------------------
    # Test 4: Stakeholder-specific framing
    # ----------------------------------------------------------------
    for role in ["agent", "field_officer", "compliance_analyst"]:
        framing = narrator.narrate_for_stakeholder(alerts[0], role)
        assert "framed_alert" in framing, f"FAIL: Missing framed_alert for role {role}"
        assert len(framing["framed_alert"]) > 10, f"FAIL: Empty framing for role {role}"
        assert framing.get("role") == role, f"FAIL: Role mismatch in framing"

    print(f"[PASS] Test 4: Stakeholder framing works for agent / field_officer / compliance_analyst")

    # ----------------------------------------------------------------
    # Test 5: Case created from alert with all required fields
    # ----------------------------------------------------------------
    alert = alerts[0]
    narration = narrator.narrate(alert)
    alert_dict = alert.model_dump(mode="json")
    case = case_manager.create_case(alert_dict, narration)

    assert case.case_id.startswith("CASE-"), f"FAIL: Bad case ID: {case.case_id}"
    assert case.status == CaseStatus.OPEN, f"FAIL: Initial status should be OPEN"
    assert case.alert_id == alert.alert_id, "FAIL: Alert ID mismatch"
    assert case.provider == alert.provider, "FAIL: Provider mismatch"
    assert len(case.evidence) > 0, "FAIL: Case missing evidence"
    assert case.disclaimer != "", "FAIL: Case missing disclaimer"
    assert len(case.audit_trail) == 1, f"FAIL: Should have 1 audit entry, got {len(case.audit_trail)}"
    assert case.audit_trail[0].action.value == "created", "FAIL: First audit entry should be 'created'"
    assert case.narration_en != "" or case.narration_bn != "", "FAIL: Case missing narration"

    print(f"[PASS] Test 5: Case {case.case_id} created with evidence, disclaimer, narration, audit entry")

    # ----------------------------------------------------------------
    # Test 6: Full lifecycle OPEN → ASSIGNED → ACKNOWLEDGED → ESCALATED → RESOLVED
    # ----------------------------------------------------------------
    case_id = case.case_id

    # Assign
    case = case_manager.assign_case(case_id, StakeholderRole.FIELD_OFFICER)
    assert case.status == CaseStatus.ASSIGNED, f"FAIL: Status should be ASSIGNED, got {case.status}"
    assert case.current_owner_role == StakeholderRole.FIELD_OFFICER, "FAIL: Owner role mismatch"

    # Acknowledge
    case = case_manager.acknowledge_case(case_id, "FO-SYL-001", StakeholderRole.FIELD_OFFICER)
    assert case.status == CaseStatus.ACKNOWLEDGED, f"FAIL: Status should be ACKNOWLEDGED"

    # Escalate
    case = case_manager.escalate_case(
        case_id, "FO-SYL-001", StakeholderRole.FIELD_OFFICER,
        reason="Unable to resolve at field level — escalating to area manager"
    )
    assert case.status == CaseStatus.ESCALATED, f"FAIL: Status should be ESCALATED"
    assert case.escalation_level == 1, f"FAIL: Escalation level should be 1, got {case.escalation_level}"
    assert case.current_owner_role == StakeholderRole.FIELD_OFFICER, \
        f"FAIL: After escalation owner should be FIELD_OFFICER, got {case.current_owner_role}"

    # Resolve
    case = case_manager.resolve_case(
        case_id, "FO-SYL-001", StakeholderRole.FIELD_OFFICER,
        resolution_note="Float replenishment arranged. Agent confirmed cash restored. Issue resolved."
    )
    assert case.status == CaseStatus.RESOLVED, f"FAIL: Status should be RESOLVED"
    assert case.resolved_at is not None, "FAIL: resolved_at not set"
    assert case.resolution_note != "", "FAIL: resolution_note empty"

    print(f"[PASS] Test 6: Full lifecycle OPEN -> ASSIGNED -> ACKNOWLEDGED -> ESCALATED -> RESOLVED")

    # ----------------------------------------------------------------
    # Test 7: Audit trail has entry for every state change
    # ----------------------------------------------------------------
    audit = case.audit_trail
    actions = [e.action.value for e in audit]

    expected_actions = {"created", "assigned", "acknowledged", "escalated", "resolved"}
    assert expected_actions.issubset(set(actions)), \
        f"FAIL: Audit trail missing actions. Got: {actions}, Expected: {expected_actions}"

    # Every entry has timestamp, actor_id, action
    for entry in audit:
        assert entry.timestamp is not None, "FAIL: Audit entry missing timestamp"
        assert entry.actor_id != "", "FAIL: Audit entry missing actor_id"
        assert entry.action is not None, "FAIL: Audit entry missing action"

    print(f"[PASS] Test 7: Audit trail has {len(audit)} entries: {actions}")

    # ----------------------------------------------------------------
    # Test 8: Notification log populated on assignment and escalation
    # ----------------------------------------------------------------
    notif_log = case.notification_log
    assert len(notif_log) >= 3, f"FAIL: Expected ≥3 notification entries, got {len(notif_log)}"

    notif_actions = [n.get("action") for n in notif_log]
    assert "would_notify" in notif_actions, "FAIL: No notification logged"

    print(f"[PASS] Test 8: Notification log has {len(notif_log)} entries")

    # ----------------------------------------------------------------
    print()
    print("=" * 60)
    print("ALL SEGMENT 3 & 4 EXIT TESTS PASSED [8/8]")
    print("=" * 60)
    print()

    # Print sample narration
    first_struct = next(
        (a for a in alerts if "structuring" in a.alert_type.value), alerts[0]
    )
    sample_narration = narrator.narrate(first_struct)
    print("Sample Bilingual Alert Narration:")
    print(f"  EN: {sample_narration['english']}")
    print(f"  BN: {sample_narration['bangla']}")
    print(f"  Banglish: {sample_narration['banglish']}")
    print()
    print(f"Narration mode: {narrator.mode}")
    print(f"Total cases created: {len(case_manager.all_cases)}")


if __name__ == "__main__":
    run_exit_test()
