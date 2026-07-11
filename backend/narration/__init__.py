"""
Segment 3: LLM Narration Layer
=================================
Turns structured, already-decided alerts into human-readable, bilingual,
stakeholder-appropriate text. The LLM NEVER decides risk — it only phrases
a decision already made transparently in Segment 2.

Two narration modes:
  1. Bilingual Alert Narration — Bangla/Banglish + English
  2. Stakeholder-Specific Framing — agent vs. field officer vs. compliance

Fallback: template-based narration when OpenAI API key is not available.

BANNED WORDS (enforced in system prompt + post-processing validation):
  - "fraud", "fraudulent", "scam", "illegal", "blocked", "suspicious"
  - "malicious", "criminal", "blacklisted"

APPROVED LANGUAGE:
  - "unusual transaction velocity", "requires operational review"
  - "elevated seasonal demand", "unusual activity", "pattern requires review"
"""

from __future__ import annotations

import os
import json
import re
from typing import Optional
from datetime import datetime

from backend.models.alert_models import (
    SystemAlert, AnomalyAlert, LiquidityProjection,
    AlertType, AlertClassification, ConfidenceLevel, AlertSeverity
)

# ---------------------------------------------------------------------------
# Safety Guardrails
# ---------------------------------------------------------------------------

BANNED_WORDS = [
    "fraud", "fraudulent", "scam", "scammer", "illegal",
    "blocked account", "blacklisted", "malicious", "criminal",
    "suspicious activity", "suspicious",
]

BANNED_PATTERN = re.compile(
    "|".join(re.escape(w) for w in BANNED_WORDS),
    re.IGNORECASE
)

HUMAN_REVIEW_DISCLAIMER_EN = (
    "This is not a final determination. Human review is required before any action."
)
HUMAN_REVIEW_DISCLAIMER_BN = (
    "এটি কোনো চূড়ান্ত সিদ্ধান্ত নয়। যেকোনো পদক্ষেপ নেওয়ার আগে মানুষের মাধ্যমে যাচাইকরণ প্রয়োজন।"
)


def sanitize_output(text: str) -> str:
    """Remove any banned words that might slip through the LLM."""
    result = BANNED_PATTERN.sub("unusual activity", text)
    return result


def validate_narration(text: str) -> bool:
    """Check that narration contains no banned words."""
    return not BANNED_PATTERN.search(text)


# ---------------------------------------------------------------------------
# System Prompts
# ---------------------------------------------------------------------------

BILINGUAL_SYSTEM_PROMPT = """You are a bilingual Operations Assistant for MFS (Mobile Financial Services) agent networks in Bangladesh.
Your job is to translate structured alert data into clear, natural, and helpful summaries in both English and Bengali (Bangla/Banglish).

CRITICAL SECURITY AND STYLE RULES — FOLLOW EXACTLY:
1. NEVER use the words: "fraud", "fraudulent", "scam", "illegal", "blocked", "suspicious", "malicious", "criminal", or "blacklisted".
2. Instead use: "unusual transaction velocity", "pattern requires review", "unusual activity", "elevated demand", or "requires operational review".
3. Clearly state the confidence level and the exact evidence numbers provided.
4. Always append a human-review disclaimer at the end.
5. Format the output as a JSON object with exactly three keys: "english", "bangla", and "banglish".
6. Keep each summary to 2-3 sentences maximum. Be clear and direct.
7. For Bangla, use proper Bengali script. For Banglish, use romanized Bengali that an agent can read on a basic phone.
8. Include specific numbers from the evidence (transaction counts, amounts, time windows).

Respond ONLY with valid JSON. No markdown, no extra text."""

STAKEHOLDER_SYSTEM_PROMPT = """You are an MFS Operations Analyst. Frame the provided alert for the specified stakeholder role.

Roles and framing rules:
1. "agent" — Focus on: cash availability, immediate safe actions (call field officer, check cash drawer). Use supportive, non-accusatory Bangla/Banglish tone. Keep it simple.
2. "field_officer" — Focus on: territory coordination, visiting the outlet, checking physical cash, arranging float support. Use mixed Bangla-English operational tone.
3. "compliance_analyst" — Focus on: statistical evidence (z-scores, CVs, counts), transaction timings, account concentrations, escalation checklist. Use formal English.

CRITICAL RULES:
- NEVER use "fraud", "scam", "illegal", "suspicious", "blocked", "malicious".
- Use "unusual activity", "requires review", "elevated demand" instead.
- Always include the confidence level and key evidence numbers.
- End with human-review disclaimer.

Respond ONLY with valid JSON: {"framed_alert": "...", "language": "..."}"""


# ---------------------------------------------------------------------------
# Template-Based Fallback Narration (no API key needed)
# ---------------------------------------------------------------------------

class TemplateNarrator:
    """
    Template-based narration — works without OpenAI API.
    Produces bilingual alerts from structured data using pre-written templates.
    """

    def narrate_alert(self, alert: SystemAlert) -> dict:
        """Generate bilingual narration from templates."""
        if alert.alert_type == AlertType.STRUCTURING_PATTERN:
            return self._narrate_structuring(alert)
        elif alert.alert_type == AlertType.LIQUIDITY_SHORTAGE:
            return self._narrate_liquidity(alert)
        elif alert.alert_type == AlertType.FEED_DEGRADED:
            return self._narrate_feed_degraded(alert)
        elif alert.alert_type in (AlertType.VOLUME_SPIKE_NORMAL, AlertType.VOLUME_SPIKE_REVIEW):
            return self._narrate_volume_spike(alert)
        else:
            return self._narrate_generic(alert)

    def frame_for_stakeholder(self, alert: SystemAlert, role: str) -> dict:
        """Frame alert for a specific stakeholder role."""
        narration = self.narrate_alert(alert)

        if role == "agent":
            return {
                "framed_alert": narration.get("bangla", narration.get("english", "")),
                "language": "bangla",
                "role": "agent",
            }
        elif role == "field_officer":
            return {
                "framed_alert": narration.get("banglish", narration.get("english", "")),
                "language": "banglish",
                "role": "field_officer",
            }
        elif role == "compliance_analyst":
            return {
                "framed_alert": narration.get("english", ""),
                "language": "english",
                "role": "compliance_analyst",
            }
        else:
            return {
                "framed_alert": narration.get("english", ""),
                "language": "english",
                "role": role,
            }

    # --- Template methods ---

    def _narrate_structuring(self, alert: SystemAlert) -> dict:
        ev = alert.evidence
        txn_count = ev.get("transactions_count", "N/A")
        window = ev.get("time_window_minutes", "N/A")
        accounts = ev.get("unique_accounts", "N/A")
        total = ev.get("total_amount", 0)
        spread = ev.get("amount_spread", "N/A")
        confidence = alert.confidence.value.upper()

        english = (
            f"Unusual transaction activity detected on {alert.provider}: "
            f"{txn_count} cash-outs occurred within {window} minutes from only "
            f"{accounts} accounts, totaling BDT {total:,.0f}. "
            f"Amount spread: BDT {spread}. Confidence: {confidence}. "
            f"Recommended: {alert.recommended_action} "
            f"{HUMAN_REVIEW_DISCLAIMER_EN}"
        )

        bangla = (
            f"{alert.provider}-এ অস্বাভাবিক লেনদেন সনাক্ত হয়েছে: "
            f"গত {window} মিনিটে মাত্র {accounts}টি অ্যাকাউন্ট থেকে "
            f"{txn_count}টি ক্যাশ-আউট করা হয়েছে, যার মোট পরিমাণ "
            f"{total:,.0f} টাকা। আত্মবিশ্বাস: {'উচ্চ' if confidence == 'HIGH' else 'মাঝারি' if confidence == 'MEDIUM' else 'নিম্ন'}। "
            f"{HUMAN_REVIEW_DISCLAIMER_BN}"
        )

        banglish = (
            f"{alert.provider}-e unusual transaction detected: "
            f"last {window} minutes-e matro {accounts}ta account theke "
            f"{txn_count}ta cash-out kora hoyeche, total amount {total:,.0f} taka. "
            f"Confidence: {confidence}. "
            f"Human review proyojon — eta kono final determination na."
        )

        return {"english": english, "bangla": bangla, "banglish": banglish}

    def _narrate_liquidity(self, alert: SystemAlert) -> dict:
        ev = alert.evidence
        balance = ev.get("current_balance", 0)
        velocity = ev.get("net_outflow", 0)
        proj = alert.liquidity_projection
        minutes = proj.minutes_remaining if proj else None
        confidence = alert.confidence.value.upper()

        time_str = f"{minutes:.0f} minutes" if minutes else "soon"
        time_bn = f"{minutes:.0f} মিনিট" if minutes else "শীঘ্রই"

        english = (
            f"Liquidity pressure detected for agent {alert.agent_id}: "
            f"{alert.provider} balance is BDT {balance:,.0f}, "
            f"projected to deplete in approximately {time_str}. "
            f"Net outflow rate: BDT {velocity:,.0f}/hour. "
            f"Confidence: {confidence}. "
            f"{HUMAN_REVIEW_DISCLAIMER_EN}"
        )

        bangla = (
            f"বর্তমান লেনদেনের ধারা অনুযায়ী পরবর্তী {time_bn}র মধ্যে "
            f"আপনার {alert.provider} ব্যালেন্স শেষ হয়ে যেতে পারে। "
            f"বর্তমান ব্যালেন্স: {balance:,.0f} টাকা। "
            f"নিরাপদভাবে সেবা সচল রাখতে আপনার ফিল্ড অফিসারের সাথে যোগাযোগ করুন। "
            f"{HUMAN_REVIEW_DISCLAIMER_BN}"
        )

        banglish = (
            f"Apnar {alert.provider} balance BDT {balance:,.0f} ache, "
            f"projected depletion {time_str}-er moddhe. "
            f"Field officer-er sathe jogajog korun. "
            f"Confidence: {confidence}."
        )

        return {"english": english, "bangla": bangla, "banglish": banglish}

    def _narrate_feed_degraded(self, alert: SystemAlert) -> dict:
        ev = alert.evidence
        delay = ev.get("delay_seconds", 0)
        provider = alert.provider

        english = (
            f"Provider {provider} data feed is delayed by {delay} seconds. "
            f"All projections for this provider use stale data. "
            f"Do not make confident decisions until feed recovers. "
            f"{HUMAN_REVIEW_DISCLAIMER_EN}"
        )

        bangla = (
            f"{provider} প্রোভাইডারের ডেটা ফিড {delay} সেকেন্ড বিলম্বিত। "
            f"এই প্রোভাইডারের সব প্রক্ষেপণ পুরানো ডেটা ব্যবহার করছে। "
            f"ফিড পুনরুদ্ধার না হওয়া পর্যন্ত এই ডেটার উপর নির্ভর করে সিদ্ধান্ত নেবেন না। "
            f"{HUMAN_REVIEW_DISCLAIMER_BN}"
        )

        banglish = (
            f"{provider} data feed {delay} seconds delayed. "
            f"Sob projection stale data use korche. "
            f"Feed recover na howar porjonto confident decision neben na."
        )

        return {"english": english, "bangla": bangla, "banglish": banglish}

    def _narrate_volume_spike(self, alert: SystemAlert) -> dict:
        ev = alert.evidence
        volume = ev.get("volume_this_hour", "N/A")
        z_score = ev.get("z_score", "N/A")
        accounts = ev.get("unique_accounts", "N/A")
        confidence = alert.confidence.value.upper()

        if alert.classification == AlertClassification.LIKELY_NORMAL:
            english = (
                f"Elevated transaction volume on {alert.provider} for agent {alert.agent_id}: "
                f"{volume} transactions this hour (z-score: {z_score}), "
                f"{accounts} distinct accounts. Pattern is consistent with seasonal demand. "
                f"No unusual indicators. Confidence: {confidence}. "
                f"{HUMAN_REVIEW_DISCLAIMER_EN}"
            )
            bangla = (
                f"{alert.provider}-এ স্বাভাবিকের তুলনায় বেশি লেনদেন হয়েছে — "
                f"এই ঘণ্টায় {volume}টি লেনদেন, {accounts}টি ভিন্ন অ্যাকাউন্ট। "
                f"এটি মৌসুমী চাহিদার সাথে সামঞ্জস্যপূর্ণ। "
                f"{HUMAN_REVIEW_DISCLAIMER_BN}"
            )
        else:
            english = (
                f"Elevated activity requiring review on {alert.provider} for agent {alert.agent_id}: "
                f"{volume} transactions this hour (z-score: {z_score}), "
                f"only {accounts} distinct accounts. "
                f"Pattern requires operational review. Confidence: {confidence}. "
                f"{HUMAN_REVIEW_DISCLAIMER_EN}"
            )
            bangla = (
                f"{alert.provider}-এ অস্বাভাবিক মাত্রায় লেনদেন হচ্ছে — "
                f"এই ঘণ্টায় {volume}টি লেনদেন, মাত্র {accounts}টি অ্যাকাউন্ট। "
                f"লেনদেনের ধরণটি পর্যালোচনা প্রয়োজন। "
                f"{HUMAN_REVIEW_DISCLAIMER_BN}"
            )

        banglish = (
            f"{alert.provider}-e ei ghontay {volume}ta transaction hoyeche, "
            f"{accounts}ta unique account. Z-score: {z_score}. "
            f"Confidence: {confidence}."
        )

        return {"english": english, "bangla": bangla, "banglish": banglish}

    def _narrate_generic(self, alert: SystemAlert) -> dict:
        confidence = alert.confidence.value.upper()
        return {
            "english": f"{alert.title}. Confidence: {confidence}. {HUMAN_REVIEW_DISCLAIMER_EN}",
            "bangla": f"{alert.title}. আত্মবিশ্বাস: {confidence}. {HUMAN_REVIEW_DISCLAIMER_BN}",
            "banglish": f"{alert.title}. Confidence: {confidence}.",
        }


# ---------------------------------------------------------------------------
# OpenAI-Powered Narration (used when API key is available)
# ---------------------------------------------------------------------------

class LLMNarrator:
    """
    OpenAI-powered narration — produces higher quality bilingual text.
    Falls back to TemplateNarrator if API key is missing or call fails.
    """

    def __init__(self):
        self._template = TemplateNarrator()
        self._client = None
        self._model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        api_key = os.getenv("OPENAI_API_KEY", "")
        if api_key and api_key != "your_openai_api_key_here":
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=api_key)
                print("[Segment 3] OpenAI client initialized.")
            except Exception as e:
                print(f"[Segment 3] OpenAI init failed: {e}. Using template fallback.")
        else:
            print("[Segment 3] No OpenAI API key. Using template-based narration.")

    @property
    def is_llm_available(self) -> bool:
        return self._client is not None

    def narrate_alert(self, alert: SystemAlert) -> dict:
        """Generate bilingual narration — tries LLM first, falls back to template."""
        if not self._client:
            return self._template.narrate_alert(alert)

        try:
            return self._llm_narrate(alert)
        except Exception as e:
            print(f"[Segment 3] LLM narration failed: {e}. Using template fallback.")
            return self._template.narrate_alert(alert)

    def frame_for_stakeholder(self, alert: SystemAlert, role: str) -> dict:
        """Frame alert for stakeholder — tries LLM first, falls back to template."""
        if not self._client:
            return self._template.frame_for_stakeholder(alert, role)

        try:
            return self._llm_frame(alert, role)
        except Exception as e:
            print(f"[Segment 3] LLM framing failed: {e}. Using template fallback.")
            return self._template.frame_for_stakeholder(alert, role)

    def _llm_narrate(self, alert: SystemAlert) -> dict:
        """Call OpenAI for bilingual narration."""
        user_prompt = json.dumps({
            "alert_type": alert.alert_type.value,
            "classification": alert.classification.value,
            "provider": alert.provider,
            "agent_id": alert.agent_id,
            "agent_name": alert.agent_name,
            "severity": alert.severity.value,
            "confidence": alert.confidence.value,
            "evidence": alert.evidence,
            "recommended_action": alert.recommended_action,
        }, indent=2, default=str)

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": BILINGUAL_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=600,
        )

        content = response.choices[0].message.content.strip()
        # Parse JSON response
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]

        result = json.loads(content)

        # Sanitize — remove any banned words that slipped through
        for key in ["english", "bangla", "banglish"]:
            if key in result:
                result[key] = sanitize_output(result[key])

        return result

    def _llm_frame(self, alert: SystemAlert, role: str) -> dict:
        """Call OpenAI for stakeholder-specific framing."""
        user_prompt = json.dumps({
            "target_role": role,
            "alert_details": {
                "alert_type": alert.alert_type.value,
                "provider": alert.provider,
                "agent_id": alert.agent_id,
                "agent_name": alert.agent_name,
                "severity": alert.severity.value,
                "confidence": alert.confidence.value,
                "evidence": alert.evidence,
                "title": alert.title,
                "summary": alert.summary,
                "recommended_action": alert.recommended_action,
            }
        }, indent=2, default=str)

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": STAKEHOLDER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=400,
        )

        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]

        result = json.loads(content)
        if "framed_alert" in result:
            result["framed_alert"] = sanitize_output(result["framed_alert"])
        result["role"] = role

        return result


# ---------------------------------------------------------------------------
# Narration Engine — single entry point for the rest of the system
# ---------------------------------------------------------------------------

class NarrationEngine:
    """
    Single entry point for all narration.
    Automatically uses LLM when available, template otherwise.
    Applies post-processing safety checks to all output.
    """

    def __init__(self):
        self._narrator = LLMNarrator()
        self._template = TemplateNarrator()

    @property
    def mode(self) -> str:
        return "llm" if self._narrator.is_llm_available else "template"

    def narrate(self, alert: SystemAlert) -> dict:
        """Generate bilingual narration for an alert."""
        result = self._narrator.narrate_alert(alert)

        # Post-processing safety check
        for key in ["english", "bangla", "banglish"]:
            if key in result:
                result[key] = sanitize_output(result[key])

        result["narration_mode"] = self.mode
        result["generated_at"] = datetime.utcnow().isoformat()
        return result

    def narrate_for_stakeholder(self, alert: SystemAlert, role: str) -> dict:
        """Generate stakeholder-specific narration."""
        result = self._narrator.frame_for_stakeholder(alert, role)

        if "framed_alert" in result:
            result["framed_alert"] = sanitize_output(result["framed_alert"])

        result["narration_mode"] = self.mode
        result["generated_at"] = datetime.utcnow().isoformat()
        return result

    def narrate_batch(self, alerts: list[SystemAlert]) -> list[dict]:
        """Narrate all alerts in a batch."""
        return [self.narrate(alert) for alert in alerts]
