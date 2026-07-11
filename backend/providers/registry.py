"""
Segment 1: Provider Registry — Enforced Isolation Layer
=========================================================
This module is the ONLY authorized place where multiple provider feeds are
touched. It acts as the aggregator node mentioned in the architecture doc.

RULES (enforced by structure, not just convention):
  - bKash pipeline cannot call nagad_pipeline() or rocket_pipeline()
  - Each provider's feed is accessed only through its own ProviderPipeline
  - The ProviderRegistry combines reads but never mixes writes
  - Cross-provider raw data exposure is prevented by returning read-only views
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from backend.models.data_models import (
    Provider, ProviderFeed, ProviderBalance,
    SharedCashBalance, AgentProfile, Transaction
)


class ProviderPipeline:
    """
    Represents one provider's data pipeline.
    Can only read/write its own provider's data.
    """
    def __init__(self, provider: Provider, feed: ProviderFeed):
        self._provider = provider
        self._feed = feed

    @property
    def provider(self) -> Provider:
        return self._provider

    def get_agent_balance(self, agent_id: str) -> Optional[ProviderBalance]:
        for bal in self._feed.agent_balances:
            if bal.agent_id == agent_id and bal.provider == self._provider:
                return bal
        return None

    def get_transactions(
        self,
        agent_id: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> list[Transaction]:
        txns = [t for t in self._feed.transactions if t.provider == self._provider]
        if agent_id:
            txns = [t for t in txns if t.agent_id == agent_id]
        if since:
            txns = [t for t in txns if t.timestamp >= since]
        if until:
            txns = [t for t in txns if t.timestamp <= until]
        return txns

    @property
    def is_healthy(self) -> bool:
        return self._feed.feed_healthy

    @property
    def delay_seconds(self) -> int:
        return self._feed.delay_seconds

    @property
    def all_agents_in_feed(self) -> list[str]:
        return list({b.agent_id for b in self._feed.agent_balances})


class ProviderRegistry:
    """
    The single aggregator node.
    Provides cross-provider READ-ONLY combined views for the analytics engine.
    No provider pipeline can access another's raw feed through this class.
    """
    def __init__(self, pipelines: dict[Provider, ProviderPipeline], agents: list[AgentProfile]):
        self._pipelines = pipelines
        self._agents: dict[str, AgentProfile] = {a.agent_id: a for a in agents}

    def get_pipeline(self, provider: Provider) -> ProviderPipeline:
        """Authorized access to a single provider pipeline."""
        return self._pipelines[provider]

    def get_agent(self, agent_id: str) -> Optional[AgentProfile]:
        return self._agents.get(agent_id)

    def list_agents(self) -> list[AgentProfile]:
        return list(self._agents.values())

    # ------------------------------------------------------------------
    # Aggregated read-only views (the ONLY cross-provider reads allowed)
    # ------------------------------------------------------------------

    def get_combined_agent_view(self, agent_id: str) -> Optional[dict]:
        """
        Returns a read-only combined view:
          - Shared physical cash (single source of truth)
          - Each provider's e-money balance (kept separate, clearly labelled)
          - Data freshness per provider

        NEVER sums e-money balances together.
        """
        agent = self._agents.get(agent_id)
        if not agent:
            return None

        provider_views = {}
        all_fresh = True
        for prov, pipeline in self._pipelines.items():
            if prov not in agent.active_providers:
                continue
            bal = pipeline.get_agent_balance(agent_id)
            if bal:
                provider_views[prov.value] = {
                    "provider": prov.value,
                    "emoney_balance": bal.emoney_balance,
                    "emoney_limit": bal.emoney_limit,
                    "data_fresh": bal.data_fresh,
                    "stale_since": bal.stale_since.isoformat() if bal.stale_since else None,
                    "feed_delay_seconds": pipeline.delay_seconds,
                }
                if not bal.data_fresh:
                    all_fresh = False

        return {
            "agent_id": agent_id,
            "agent_name": agent.name,
            "area": agent.area.value,
            "shared_cash": {
                "amount": agent.shared_cash.cash_amount,
                "data_fresh": agent.shared_cash.data_fresh,
            },
            "provider_balances": provider_views,   # SEPARATE, never summed
            "all_data_fresh": all_fresh,
        }

    def get_area_overview(self, area: Optional[str] = None) -> list[dict]:
        """Aggregate health overview per area, provider-isolated."""
        agents = self.list_agents()
        if area:
            agents = [a for a in agents if a.area.value == area]

        result = []
        for agent in agents:
            view = self.get_combined_agent_view(agent.agent_id)
            if view:
                result.append(view)
        return result

    def get_all_transactions(
        self,
        provider: Optional[Provider] = None,
        agent_id: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> list[Transaction]:
        """
        Cross-provider transaction query — returns combined list for analytics.
        Provider isolation is maintained: the returned objects carry their
        provider field and must never be treated as interchangeable.
        """
        results = []
        pipelines_to_query = (
            [self._pipelines[provider]] if provider
            else list(self._pipelines.values())
        )
        for pipeline in pipelines_to_query:
            results.extend(pipeline.get_transactions(agent_id, since, until))
        results.sort(key=lambda t: t.timestamp)
        return results

    def health_summary(self) -> dict:
        """Overall system health across all providers."""
        return {
            "providers": {
                prov.value: {
                    "healthy": pipeline.is_healthy,
                    "delay_seconds": pipeline.delay_seconds,
                    "agent_count": len(pipeline.all_agents_in_feed),
                }
                for prov, pipeline in self._pipelines.items()
            }
        }
