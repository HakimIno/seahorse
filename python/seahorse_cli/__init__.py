"""
Seahorse CLI - AI-Powered Coding Assistant

Python module for CLI-specific AI agents and tools.
"""

__version__ = "0.1.0"

from .agents.code_analyst import CodeAnalyst
from .agents.refactor_crew import RefactorCrew
from .tools.code_search import semantic_search
from .tools.ast_parser import parse_python_ast, parse_rust_ast

__all__ = [
    "CodeAnalyst",
    "RefactorCrew",
    "semantic_search",
    "parse_python_ast",
    "parse_rust_ast",
]
