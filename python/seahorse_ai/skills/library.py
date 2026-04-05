"""Library of core SeahorseSkills (Dynamic Loader)."""

import logging

from seahorse_ai.skills.base import registry
from seahorse_ai.tools import make_default_registry

logger = logging.getLogger(__name__)

# Standard manifest directory
MANIFEST_DIR = "python/seahorse_ai/skills/manifests"


def load_standard_skills():
    """Load and resolve all skills from the manifests directory."""
    try:
        registry.load_plugins(MANIFEST_DIR)
        registry.resolve_tools(make_default_registry())
        logger.info("Successfully loaded %d skills from manifests", len(registry.list_skills()))
    except Exception as e:
        logger.error("Failed to load standard skills: %s", e)


# Auto-load on import to maintain backward compatibility
load_standard_skills()
