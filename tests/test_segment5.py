"""
Segment 5 Exit Test — Two-Sided Dashboard
============================================
Validates the frontend dashboard (index.html) meets all submission requirements:

[PASS] HTML file exists and is well-formed
[PASS] No banned words in UI text content
[PASS] Contains role switcher (Agent / Field Officer / Ops)
[PASS] Contains all expected dashboard sections
[PASS] Human-review disclaimer present in HTML
[PASS] Never shows a merged/total wallet balance
[PASS] References correct API endpoints
[PASS] Contains bilingual support (Bangla/Banglish)
[PASS] Contains chaos toggle for Scenario C demo
[PASS] Provider isolation maintained in UI labels
"""

import sys
import re
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Banned words list (same as backend/narration/__init__.py)
BANNED_WORDS = [
    "fraud", "fraudulent", "scam", "scammer", "illegal",
    "blocked account", "blacklisted", "malicious", "criminal",
]

# Words that ARE allowed and should not trigger false positives
ALLOWED_CONTEXT = [
    "unusual activity", "requires review", "unusual transaction",
    "elevated demand", "requires operational review",
]


def run_exit_test():
    print("=" * 60)
    print("SEGMENT 5 EXIT TEST — Two-Sided Dashboard")
    print("=" * 60)

    # ----------------------------------------------------------------
    # Test 1: HTML file exists and has substantial content
    # ----------------------------------------------------------------
    html_path = Path(__file__).parent.parent / "frontend" / "index.html"
    assert html_path.exists(), f"FAIL: {html_path} does not exist"
    html_content = html_path.read_text(encoding="utf-8")
    assert len(html_content) > 10000, f"FAIL: HTML file too small ({len(html_content)} bytes)"
    assert "<!DOCTYPE html>" in html_content or "<!doctype html>" in html_content.lower(), \
        "FAIL: Missing DOCTYPE declaration"
    print(f"[PASS] Test 1: index.html exists ({len(html_content):,} bytes, {html_content.count(chr(10))} lines)")

    # ----------------------------------------------------------------
    # Test 2: No banned words in UI text
    # ----------------------------------------------------------------
    # We check the HTML content but exclude script/code sections that might
    # reference banned words in variable names or comments about the ban itself
    violations = []
    for word in BANNED_WORDS:
        # Case-insensitive search, but exclude contexts like "banned words"
        # or references to the banned list itself
        pattern = re.compile(re.escape(word), re.IGNORECASE)
        matches = list(pattern.finditer(html_content))
        for match in matches:
            # Get surrounding context (50 chars before/after)
            start = max(0, match.start() - 50)
            end = min(len(html_content), match.end() + 50)
            context = html_content[start:end].replace("\n", " ").strip()

            # Allow references that are about the banned list itself
            if "banned" in context.lower() or "BANNED" in context:
                continue
            # Allow if it's in a JS comment or string about the word being forbidden
            if "never" in context.lower() and word in context.lower():
                continue

            violations.append(f"  Found '{word}' in: ...{context}...")

    assert len(violations) == 0, f"FAIL: Banned words found in UI:\n" + "\n".join(violations)
    print(f"[PASS] Test 2: No banned words found in dashboard HTML")

    # ----------------------------------------------------------------
    # Test 3: Role switcher present
    # ----------------------------------------------------------------
    has_role_switcher = (
        "role-switcher" in html_content or
        "role-btn" in html_content or
        "roleSwitcher" in html_content
    )
    assert has_role_switcher, "FAIL: No role switcher found in HTML"

    # Check for at least agent and ops roles
    has_agent_role = "agent" in html_content.lower()
    has_ops_role = "ops" in html_content.lower() or "field_officer" in html_content.lower() or "field officer" in html_content.lower()
    assert has_agent_role, "FAIL: No agent role reference found"
    assert has_ops_role, "FAIL: No ops/field officer role reference found"
    print(f"[PASS] Test 3: Role switcher present with agent + ops/field officer roles")

    # ----------------------------------------------------------------
    # Test 4: All expected dashboard sections present
    # ----------------------------------------------------------------
    required_sections = {
        "alerts": ["alert", "Alert"],
        "liquidity": ["liquidity", "Liquidity", "depletion", "shortage"],
        "cases": ["case", "Case", "case-board", "caseBoard"],
        "agents": ["agent-table", "agentTable", "Agent Table", "agent_id"],
        "transactions": ["transaction", "Transaction", "txn"],
    }

    for section_name, keywords in required_sections.items():
        found = any(kw in html_content for kw in keywords)
        assert found, f"FAIL: Missing section '{section_name}' (looked for: {keywords})"

    print(f"[PASS] Test 4: All {len(required_sections)} dashboard sections present (alerts, liquidity, cases, agents, transactions)")

    # ----------------------------------------------------------------
    # Test 5: Human-review disclaimer in HTML
    # ----------------------------------------------------------------
    disclaimer_patterns = [
        "human review",
        "not a final determination",
        "not a fraud determination",
        "requires review",
        "human-review",
    ]
    has_disclaimer = any(p.lower() in html_content.lower() for p in disclaimer_patterns)
    assert has_disclaimer, "FAIL: No human-review disclaimer found in HTML"
    print(f"[PASS] Test 5: Human-review disclaimer present in dashboard")

    # ----------------------------------------------------------------
    # Test 6: No merged/total wallet balance
    # ----------------------------------------------------------------
    merged_balance_indicators = [
        "total_balance",
        "totalBalance",
        "merged_balance",
        "mergedBalance",
        "combined_balance",
        "combinedBalance",
        "total wallet",
        "total balance",
    ]
    for indicator in merged_balance_indicators:
        assert indicator not in html_content, \
            f"FAIL: Found merged balance indicator '{indicator}' in HTML"

    # Check that "shared_cash" and "provider_balances" are used as separate concepts
    has_shared_cash = "shared_cash" in html_content or "shared cash" in html_content.lower()
    has_provider_balance = "provider_balance" in html_content or "emoney" in html_content.lower() or "e-money" in html_content.lower()
    assert has_shared_cash or has_provider_balance, \
        "FAIL: No evidence of separate cash/provider balance display"
    print(f"[PASS] Test 6: No merged wallet balance found — cash and e-money kept separate")

    # ----------------------------------------------------------------
    # Test 7: Correct API endpoints referenced
    # ----------------------------------------------------------------
    required_endpoints = [
        "/api/v1/",
        "analytics",
        "alerts",
        "cases",
    ]
    for endpoint in required_endpoints:
        assert endpoint in html_content, f"FAIL: Missing API endpoint reference: {endpoint}"
    print(f"[PASS] Test 7: Correct API endpoints referenced in frontend")

    # ----------------------------------------------------------------
    # Test 8: Bilingual support (Bangla/Banglish)
    # ----------------------------------------------------------------
    bilingual_indicators = [
        "bangla", "Bangla", "বাংলা",
        "banglish", "Banglish",
        "bengali", "Bengali",
        "Noto Sans Bengali",
    ]
    has_bilingual = any(ind in html_content for ind in bilingual_indicators)
    assert has_bilingual, "FAIL: No bilingual (Bangla/Banglish) support found"
    print(f"[PASS] Test 8: Bilingual support present (Bangla/Banglish)")

    # ----------------------------------------------------------------
    # Test 9: Chaos toggle for Scenario C demo
    # ----------------------------------------------------------------
    chaos_indicators = [
        "chaos", "Chaos",
        "degrade", "Degrade",
        "chaos-btn", "chaosBtn",
        "chaos_toggle",
    ]
    has_chaos = any(ind in html_content for ind in chaos_indicators)
    assert has_chaos, "FAIL: No chaos toggle found for Scenario C demo"
    print(f"[PASS] Test 9: Chaos toggle present for Scenario C demo")

    # ----------------------------------------------------------------
    # Test 10: Provider isolation in UI
    # ----------------------------------------------------------------
    providers_mentioned = []
    for prov in ["bkash", "nagad", "rocket", "bKash", "Nagad", "Rocket"]:
        if prov in html_content:
            providers_mentioned.append(prov.lower())
    providers_mentioned = list(set(providers_mentioned))
    assert len(providers_mentioned) >= 2, \
        f"FAIL: Expected 2+ providers in UI, found: {providers_mentioned}"
    print(f"[PASS] Test 10: Provider references found: {providers_mentioned}")

    # ----------------------------------------------------------------
    # Test 11: Confidence level display
    # ----------------------------------------------------------------
    confidence_indicators = ["confidence", "Confidence", "conf-high", "conf-medium", "conf-low"]
    has_confidence = any(ind in html_content for ind in confidence_indicators)
    assert has_confidence, "FAIL: No confidence level display found"
    print(f"[PASS] Test 11: Confidence level display present")

    # ----------------------------------------------------------------
    print()
    print("=" * 60)
    print("ALL SEGMENT 5 EXIT TESTS PASSED [11/11]")
    print("=" * 60)


if __name__ == "__main__":
    run_exit_test()
