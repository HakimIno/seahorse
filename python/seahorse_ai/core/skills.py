"""Skills Loader — context-aware domain knowledge injection.

Loads relevant skills from .claude/skills/ based on query context
and injects them into the AI's system prompt for better responses.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


class SkillLoader:
    """Load and inject domain-specific skills from .claude/skills/."""

    def __init__(self, skills_dir: Path | None = None):
        """Initialize the skill loader.

        Args:
            skills_dir: Path to .claude/skills/ directory (default: auto-detect)
        """
        if skills_dir is None:
            # Try to find .claude/skills/ from current directory
            current = Path.cwd()
            for parent in [current] + list(current.parents):
                candidate = parent / ".claude" / "skills"
                if candidate.exists() and candidate.is_dir():
                    skills_dir = candidate
                    break

        self.skills_dir = Path(skills_dir) if skills_dir else None
        logger.info("SkillLoader initialized with skills_dir: %s", self.skills_dir)

        # Skill keywords for relevance detection
        self.skill_keywords = {
            "architecture": [
                "design", "architecture", "system design", "pattern",
                "scalability", "structure", "component", "module",
                "microservice", "monolith", "distributed"
            ],
            "rust-core": [
                "rust", "tokio", "async", "performance", "memory",
                "hnsw", "wasmtime", "axum", "tower", "trait",
                "lifetime", "ownership", "borrowing"
            ],
            "ffi-bridge": [
                "ffi", "pyo3", "binding", "bridge", "interface",
                "cffi", "extension", "module", "rust-python",
                "zero-copy", "gil", "embedding"
            ],
            "python-ai": [
                "llm", "agent", "planning", "react", "tool", "langchain",
                "prompt", "completion", "openai", "claude", "ai",
                "machine learning", "nlp", "embedding", "vector"
            ],
            "performance": [
                "performance", "optimization", "speed", "latency",
                "throughput", "benchmark", "profile", "cache",
                "memory", "cpu", "fast", "slow"
            ],
            "testing": [
                "test", "pytest", "unit test", "integration", "mock",
                "fixture", "coverage", "tdd", "assert", "verify"
            ],
            "code-review": [
                "review", "refactor", "clean up", "improve", "fix",
                "best practice", "quality", "maintainability"
            ],
            "release": [
                "release", "deploy", "version", "changelog", "tag",
                "publish", "distribution", "package", "wheel"
            ],
            "refactor": [
                "refactor", "restructure", "reorganize", "rewrite",
                "improve", "simplify", "cleanup", "rearchitecture"
            ],
        }

    def load_skill(self, skill_name: str) -> str:
        """Load a specific skill file.

        Args:
            skill_name: Name of the skill (e.g., "rust-core")

        Returns:
            Skill content as string, or empty string if not found
        """
        if self.skills_dir is None:
            return ""

        skill_path = self.skills_dir / skill_name / "SKILL.md"

        if not skill_path.exists():
            logger.warning("Skill not found: %s", skill_path)
            return ""

        try:
            content = skill_path.read_text(encoding="utf-8", errors="replace")

            # Truncate very long skills to avoid context overflow
            max_length = 3000
            if len(content) > max_length:
                content = content[:max_length] + "\n\n... (truncated for length)"

            logger.debug("Loaded skill: %s (%d chars)", skill_name, len(content))
            return content

        except Exception as e:
            logger.error("Failed to load skill %s: %s", skill_name, e)
            return ""

    def detect_relevant_skills(self, user_query: str) -> list[str]:
        """Detect which skills are relevant based on query keywords.

        Args:
            user_query: The user's query or request

        Returns:
            List of relevant skill names (ordered by relevance)
        """
        query_lower = user_query.lower()

        # Score each skill by keyword matches
        skill_scores = {}

        for skill_name, keywords in self.skill_keywords.items():
            score = 0
            matched_keywords = []

            for keyword in keywords:
                if keyword.lower() in query_lower:
                    score += 1
                    matched_keywords.append(keyword)

            if score > 0:
                skill_scores[skill_name] = (score, matched_keywords)

        # Sort by score (descending) and return skill names
        sorted_skills = sorted(
            skill_scores.items(),
            key=lambda x: x[1][0],
            reverse=True
        )

        result = [skill for skill, (score, _) in sorted_skills]

        if result:
            logger.info(
                "Detected relevant skills: %s (scores: %s)",
                result,
                [(s, skill_scores[s][0]) for s in result]
            )

        return result

    def build_context(self, user_query: str, max_skills: int = 3) -> str:
        """Build context from relevant skills.

        Args:
            user_query: The user's query or request
            max_skills: Maximum number of skills to include (default: 3)

        Returns:
            Formatted context string with relevant skills
        """
        relevant_skills = self.detect_relevant_skills(user_query)

        if not relevant_skills:
            return ""

        # Limit to max_skills
        selected_skills = relevant_skills[:max_skills]

        context_parts = []

        for skill in selected_skills:
            content = self.load_skill(skill)

            if content:
                # Add skill header and content
                context_parts.append(f"## 📚 Domain Knowledge: {skill}\n")
                context_parts.append(content)
                context_parts.append("\n---\n")

        if not context_parts:
            return ""

        result = "\n".join(context_parts)

        logger.info(
            "Built context from %d skills (total %d chars)",
            len(selected_skills),
            len(result)
        )

        return result

    def list_available_skills(self) -> list[str]:
        """List all available skills in the skills directory.

        Returns:
            List of skill names
        """
        if self.skills_dir is None:
            return []

        skills = []

        for skill_dir in self.skills_dir.iterdir():
            if skill_dir.is_dir():
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    skills.append(skill_dir.name)

        return sorted(skills)

    def get_skill_summary(self, skill_name: str) -> str:
        """Get a brief summary of a skill (first few lines).

        Args:
            skill_name: Name of the skill

        Returns:
            Brief summary or error message
        """
        if self.skills_dir is None:
            return "Skills directory not configured"

        skill_path = self.skills_dir / skill_name / "SKILL.md"

        if not skill_path.exists():
            return f"Skill not found: {skill_name}"

        try:
            content = skill_path.read_text(encoding="utf-8", errors="replace")

            # Get first 3 non-empty lines
            lines = [
                line.strip()
                for line in content.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]

            summary = " ".join(lines[:3])

            if len(summary) > 200:
                summary = summary[:200] + "..."

            return summary

        except Exception as e:
            return f"Error reading skill: {e}"


# Global skill loader instance
_skill_loader: SkillLoader | None = None


def get_skill_loader() -> SkillLoader:
    """Get or create the global skill loader instance.

    Returns:
        SkillLoader instance
    """
    global _skill_loader

    if _skill_loader is None:
        _skill_loader = SkillLoader()

    return _skill_loader


def inject_skills_context(user_query: str, max_skills: int = 3) -> str:
    """Convenience function to inject skills context into a prompt.

    Args:
        user_query: The user's query or request
        max_skills: Maximum number of skills to include

    Returns:
        Formatted context string, or empty string if no relevant skills
    """
    loader = get_skill_loader()
    return loader.build_context(user_query, max_skills)
