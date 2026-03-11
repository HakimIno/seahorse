"""Library of standard SeahorseTeams."""
from __future__ import annotations

from seahorse_ai.teams.base import SeahorseTeam, registry

class DataTeam(SeahorseTeam):
    """Team specialized in database extraction and data visualization."""
    name: str = "DATA"

class HRTeam(SeahorseTeam):
    """Team specialized in HR policies, recruitment, and talent acquisition."""
    name: str = "HR"

class ResearchTeam(SeahorseTeam):
    """Team specialized in deep-web research and strategic analysis."""
    name: str = "RESEARCH"

# Registration
registry.register(DataTeam())
registry.register(HRTeam())
registry.register(ResearchTeam())
