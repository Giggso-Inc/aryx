"""Conversational CPQ configuration engine — retriever layer only.

Reads product structure and rules from the knowledge graph (FalkorDB +
PostgreSQL), applies auto-fill logic, and drives guided configuration
conversation within the Ask pipeline.

Ingestion is never touched here; all logic operates on already-stored data.
"""
from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr, CpqSession, HidingRule, MenuOption

__all__ = ["CpqEngine", "CpqSession", "ConfigAttr", "HidingRule", "MenuOption"]
