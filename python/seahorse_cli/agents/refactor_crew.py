"""
Refactor Crew - Multi-Agent Refactoring Team

Parallel execution of specialized refactoring agents.
"""

import asyncio
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from seahorse_ai.core.llm import get_llm
from seahorse_ai.core.schemas import Message

if TYPE_CHECKING:
    from seahorse_ai.memory.memory import AgentMemory


@dataclass
class RefactorResult:
    """Result from a single refactor agent."""

    agent_name: str
    success: bool
    changes: list[dict[str, Any]]
    explanation: str
    execution_time: float


@dataclass
class RefactorSummary:
    """Aggregated refactor results."""

    results: list[RefactorResult]
    total_changes: int
    conflicts: list[dict[str, Any]]
    execution_time: float


async def _analyze_with_llm(system_prompt: str, code: str, language: str) -> tuple[list[dict], str]:
    """Helper to query the LLM and parse the JSON suggestion output."""
    llm = get_llm("worker")
    prompt = f"Analyze the following {language} code:\n\n```{language}\n{code}\n```"
    messages = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=prompt)
    ]
    try:
        response = await llm.complete(messages)
    except Exception as e:
        return [], f"LLM error: {e}"
    
    content = response.get("content", "")
    
    # Try to extract JSON from markdown blocks
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
    json_str = match.group(1) if match else content
    
    try:
        changes = json.loads(json_str)
        if not isinstance(changes, list):
            changes = []
        return changes, content
    except json.JSONDecodeError:
        return [], f"Failed to parse LLM JSON response: {content[:200]}..."


class PerformanceAnalyst:
    """Agent focused on performance optimizations."""

    name = "performance_analyst"

    async def analyze(
        self,
        code: str,
        file_path: str,
        language: str = "python",
    ) -> RefactorResult:
        """Analyze code for performance issues."""
        start_time = asyncio.get_event_loop().time()

        system_prompt = (
            "You are a performance optimization expert. Review the code for algorithmic "
            "inefficiencies, memory leaks, and slow operations. "
            "Return ONLY a JSON list of dictionaries. Each dictionary must have:\n"
            '{"line_start": int, "line_end": int, "code_before": "str", "code_after": "str", '
            '"title": "str", "description": "str", "severity": "Medium", "confidence": float, '
            '"category": "performance"}'
        )
        
        changes, explanation = await _analyze_with_llm(system_prompt, code, language)
        execution_time = asyncio.get_event_loop().time() - start_time

        return RefactorResult(
            agent_name=self.name,
            success=bool(changes),
            changes=changes,
            explanation=explanation,
            execution_time=execution_time,
        )


class SecurityAuditor:
    """Agent focused on security vulnerabilities."""

    name = "security_auditor"

    async def analyze(
        self,
        code: str,
        file_path: str,
        language: str = "python",
    ) -> RefactorResult:
        """Analyze code for security issues."""
        start_time = asyncio.get_event_loop().time()

        system_prompt = (
            "You are a security auditor. Find vulnerabilities like injections, hardcoded secrets, "
            "and unsafe eval/execution. "
            "Return ONLY a JSON list of dictionaries. Each dictionary must have:\n"
            '{"line_start": int, "line_end": int, "code_before": "str", "code_after": "str", '
            '"title": "str", "description": "str", "severity": "High", "confidence": float, '
            '"category": "security"}'
        )

        changes, explanation = await _analyze_with_llm(system_prompt, code, language)
        execution_time = asyncio.get_event_loop().time() - start_time

        return RefactorResult(
            agent_name=self.name,
            success=bool(changes),
            changes=changes,
            explanation=explanation,
            execution_time=execution_time,
        )


class StyleFixer:
    """Agent focused on code style and best practices."""

    name = "style_fixer"

    async def analyze(
        self,
        code: str,
        file_path: str,
        language: str = "python",
    ) -> RefactorResult:
        """Analyze code for style issues."""
        start_time = asyncio.get_event_loop().time()

        system_prompt = (
            "You are a code style enforcer. Fix variable naming, add missing type hints, "
            "and ensure clean code practices. "
            "Return ONLY a JSON list of dictionaries. Each dictionary must have:\n"
            '{"line_start": int, "line_end": int, "code_before": "str", "code_after": "str", '
            '"title": "str", "description": "str", "severity": "Low", "confidence": float, '
            '"category": "style"}'
        )

        changes, explanation = await _analyze_with_llm(system_prompt, code, language)
        execution_time = asyncio.get_event_loop().time() - start_time

        return RefactorResult(
            agent_name=self.name,
            success=bool(changes),
            changes=changes,
            explanation=explanation,
            execution_time=execution_time,
        )


class TestGenerator:
    """Agent focused on test coverage."""

    name = "test_generator"

    async def analyze(
        self,
        code: str,
        file_path: str,
        language: str = "python",
    ) -> RefactorResult:
        """Generate tests for code."""
        start_time = asyncio.get_event_loop().time()

        system_prompt = (
            "You are a QA automation expert. Suggest adding tests for untested functions. "
            "Return ONLY a JSON list of dictionaries. Each dictionary must have:\n"
            '{"line_start": int, "line_end": int, "code_before": "str", "code_after": "str", '
            '"title": "str", "description": "str", "severity": "Info", "confidence": float, '
            '"category": "testing"}'
        )

        changes, explanation = await _analyze_with_llm(system_prompt, code, language)
        execution_time = asyncio.get_event_loop().time() - start_time

        return RefactorResult(
            agent_name=self.name,
            success=bool(changes),
            changes=changes,
            explanation=explanation,
            execution_time=execution_time,
        )


class RefactorCrew:
    """
    Multi-agent refactoring team.

    Orchestrates parallel execution of specialized refactoring agents
    and aggregates their results.
    """

    def __init__(self, memory: AgentMemory | None = None):
        self.memory = memory

        # Available agents
        self.agents = {
            "performance": PerformanceAnalyst(),
            "security": SecurityAuditor(),
            "style": StyleFixer(),
            "test": TestGenerator(),
        }

    async def refactor_file(
        self,
        file_path: str,
        code: str,
        agent_names: list[str] | None = None,
        language: str = "python",
    ) -> RefactorSummary:
        """
        Refactor a file using multiple agents in parallel.

        Args:
            file_path: Path to the file to refactor
            code: File contents
            agent_names: List of agent names to run (default: all)
            language: Programming language

        Returns:
            Aggregated refactoring results
        """
        start_time = asyncio.get_event_loop().time()

        agent_names = agent_names or list(self.agents.keys())

        agents_to_run = [
            self.agents[name]
            for name in agent_names
            if name in self.agents
        ]

        tasks = [
            agent.analyze(code, file_path, language)
            for agent in agents_to_run
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append(
                    RefactorResult(
                        agent_name=agents_to_run[i].name,
                        success=False,
                        changes=[],
                        explanation=str(result),
                        execution_time=0.0,
                    )
                )
            else:
                processed_results.append(result)

        total_changes = sum(len(r.changes) for r in processed_results if r.success)

        conflicts = self._detect_conflicts(processed_results)

        execution_time = asyncio.get_event_loop().time() - start_time

        return RefactorSummary(
            results=processed_results,
            total_changes=total_changes,
            conflicts=conflicts,
            execution_time=execution_time,
        )

    def _detect_conflicts(
        self,
        results: list[RefactorResult],
    ) -> list[dict[str, Any]]:
        """Detect conflicting changes between agents."""
        return []

    async def apply_changes(
        self,
        file_path: str,
        changes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Apply refactoring changes to a file by replacing blocks sequentially.

        Args:
            file_path: Path to the file
            changes: List of changes to apply

        Returns:
            Result of applying changes
        """
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()

            # Apply robust literal replacement where code_before exists
            applied_count = 0
            for change in sorted(changes, key=lambda c: c.get("line_start", 0), reverse=True):
                before = change.get("code_before", "")
                after = change.get("code_after", "")
                if before and before in content:
                    content = content.replace(before, after, 1)
                    applied_count += 1

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            return {
                "success": True,
                "message": f"Applied {applied_count}/{len(changes)} changes successfully",
                "applied_count": applied_count,
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to apply changes: {e}",
            }
