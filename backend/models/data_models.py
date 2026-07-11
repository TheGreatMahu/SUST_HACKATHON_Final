"""
Segment 1: Core Data Models
Provider-isolated data structures for the Multi-Provider Liquidity & Anomaly system.

ARCHITECTURAL GUARANTEE: Each provider's data is encapsulated in its own model.
No cross-provider field leaks. The aggregator node is the ONLY layer that combines.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
import uuid


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Provider(str, Enum):
    BKASH  = "bkash"
    NAGAD  = "nagad"
    ROCKET = "rocket"


class TransactionType(str, Enum):
    CASH_IN    = "cash_in"
    CASH_OUT   = "cash_out"
    SEND_MONEY = "send_money"
    PAYMENT    = "payment"
    RECHARGE   = "recharge"


class TransactionStatus(str, Enum):
    SUCCESS = "success"
    PENDING = "pending"
    FAILED  = "failed"


class AreaName(str, Enum):
    SYLHET_SADAR  = "Sylhet Sadar"
    ZINDABAZAR    = "Zindabazar"
    AMBARKHANA    = "Ambarkhana"


# ---------------------------------------------------------------------------
# Synthetic Account ID helpers (no real identifiers)
# ---------------------------------------------------------------------------

def synth_account_id(provider: Provider, seed: str) -> str:
    """Generate a stable synthetic account identifier."""
    return f"SYN-{provider.value.upper()[:3]}-{seed}"


def synth_agent_id(area: str, index: int) -> str:
    return f"AGT-{area[:3].upper()}-{index:03d}"


# ---------------------------------------------------------------------------
# Provider-specific Balance (NEVER merged with another provider's balance)
# ---------------------------------------------------------------------------

class ProviderBalance(BaseModel):
    """A single provider's e-money balance for one agent.

    This object is NEVER combined arithmetically with another provider's
    ProviderBalance. Only the aggregator may read multiple of these to build
    a read-only combined view.
    """
    provider: Provider
    agent_id: str
    emoney_balance: float = Field(..., description="Provider e-money balance in BDT")
    emoney_limit: float   = Field(..., description="Provider-set float limit for this agent")
    last_updated: datetime
    data_fresh: bool      = Field(True, description="False when feed is delayed or missing")
    stale_since: Optional[datetime] = None


class SharedCashBalance(BaseModel):
    """Physical cash drawer — shared across all providers, owned by the agent."""
    agent_id: str
    cash_amount: float = Field(..., description="Physical cash on hand in BDT")
    last_updated: datetime
    data_fresh: bool = True
    stale_since: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class AgentProfile(BaseModel):
    agent_id: str
    name: str
    area: AreaName
    thana: str
    district: str = "Sylhet"
    active_providers: list[Provider]
    shared_cash: SharedCashBalance
    provider_balances: dict[Provider, ProviderBalance]  # keyed by provider enum


# ---------------------------------------------------------------------------
# Transactions (provider-scoped)
# ---------------------------------------------------------------------------

class Transaction(BaseModel):
    txn_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    provider: Provider
    agent_id: str
    account_id: str          # synthetic — no real identity
    txn_type: TransactionType
    amount: float
    timestamp: datetime
    status: TransactionStatus
    # Ground-truth injection label (never shown in UI; used only for metrics)
    injected_label: Optional[str] = Field(None, exclude=True)


# ---------------------------------------------------------------------------
# Ground-Truth log entry (private — for Segment 6 metrics only)
# ---------------------------------------------------------------------------

class GroundTruthEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str            # "structuring_burst", "legitimate_spike", "feed_delay"
    provider: Optional[Provider]
    agent_id: str
    start_time: datetime
    end_time: datetime
    injected_txn_ids: list[str] = Field(default_factory=list)
    notes: str = ""


# ---------------------------------------------------------------------------
# Provider Feed (the object a provider pipeline publishes)
# Feed contains ONLY that provider's data — no cross-provider reads allowed
# ---------------------------------------------------------------------------

class ProviderFeed(BaseModel):
    provider: Provider
    snapshot_time: datetime
    agent_balances: list[ProviderBalance]
    transactions: list[Transaction]
    feed_healthy: bool = True
    delay_seconds: int = 0   # simulated network delay
    missing_agents: list[str] = Field(default_factory=list)   # agent IDs with no data in this snapshot
