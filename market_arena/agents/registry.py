"""Builds LLM-driven agents from config."""

from __future__ import annotations


def build_llm_agent(acfg, arena):
    assets = acfg.assets or arena.assets
    if acfg.kind == "rule_investor":
        from .rule_investor import RuleInvestor

        return RuleInvestor(acfg.id, assets, acfg.params, arena.cfg.seed)
    if not acfg.model:
        raise ValueError(f"agent {acfg.id}: LLM agents need a model")
    if acfg.kind == "llm_maker":
        from .llm_maker import LLMMaker

        return LLMMaker(acfg.id, assets, acfg.model, acfg.params)
    if acfg.kind == "llm_taker":
        from .llm_taker import LLMTaker

        return LLMTaker(acfg.id, assets, acfg.model, arena, acfg.params)
    if acfg.kind == "llm_surveillance":
        from .surveillance import LLMSurveillance

        return LLMSurveillance(acfg.id, assets, acfg.model, acfg.params)
    if acfg.kind == "llm_red_team":
        from .red_team import LLMRedTeam

        return LLMRedTeam(acfg.id, assets, arena.cfg.seed + 7, acfg.model, acfg.params)
    if acfg.kind == "llm_central_bank":
        from .central_bank import LLMCentralBank

        return LLMCentralBank(acfg.id, assets, acfg.model, acfg.params)
    if acfg.kind == "llm_wholesaler":
        from .wholesaler import LLMWholesaler

        return LLMWholesaler(acfg.id, assets, acfg.model, acfg.params)
    if acfg.kind == "llm_investor":
        from .llm_investor import LLMInvestor

        return LLMInvestor(acfg.id, assets, acfg.model, acfg.params)
    if acfg.kind == "llm_advisor":
        from .llm_investor import LLMAdvisor

        return LLMAdvisor(acfg.id, assets, acfg.model, acfg.params)
    if acfg.kind == "llm_finfluencer":
        from .llm_investor import LLMFinfluencer

        return LLMFinfluencer(acfg.id, assets, acfg.model, acfg.params)
    if acfg.kind == "llm_injector":
        from .injector import LLMInjector

        return LLMInjector(acfg.id, acfg.params, arena, acfg.model)
    raise ValueError(f"unknown agent kind {acfg.kind}")
