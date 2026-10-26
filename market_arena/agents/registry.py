"""Builds LLM-driven agents from config."""

from __future__ import annotations


def build_llm_agent(acfg, arena):
    assets = acfg.assets or arena.assets
    if not acfg.model:
        raise ValueError(f"agent {acfg.id}: LLM agents need a model")
    if acfg.kind == "llm_maker":
        from .llm_maker import LLMMaker

        return LLMMaker(acfg.id, assets, acfg.model, acfg.params)
    if acfg.kind == "llm_taker":
        from .llm_taker import LLMTaker

        return LLMTaker(acfg.id, assets, acfg.model, arena, acfg.params)
    raise ValueError(f"unknown agent kind {acfg.kind}")
