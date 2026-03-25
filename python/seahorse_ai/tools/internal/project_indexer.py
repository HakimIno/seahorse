"""seahorse_ai.tools.internal.project_indexer — Codebase mapping into Knowledge Graph.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

@tool("Scan the current project and index its structure into the long-term knowledge graph.")
async def index_project(root_path: str = ".") -> str:
    """Index crates, modules, and file relationships."""
    from seahorse_ai.core.nodes import SeahorseGraphManager
    
    memory = SeahorseGraphManager.get_memory()
    root = Path(root_path).resolve()
    
    indexed_count = 0
    relationships_count = 0
    
    # 1. Map Crates (Rust)
    crates_dir = root / "crates"
    if crates_dir.exists():
        for item in crates_dir.iterdir():
            if item.is_dir() and (item / "Cargo.toml").exists():
                memory.add_node(f"crate:{item.name}", "Rust Crate", None)
                memory.add_edge("project:seahorse", f"crate:{item.name}", "CONTAINS_CRATE", 1.0)
                indexed_count += 1
                relationships_count += 1
                
    # 2. Map Python Modules
    python_dir = root / "python"
    if python_dir.exists():
        for item in python_dir.iterdir():
            if item.is_dir() and (item / "__init__.py").exists():
                memory.add_node(f"module:{item.name}", "Python Module", None)
                memory.add_edge("project:seahorse", f"module:{item.name}", "CONTAINS_MODULE", 1.0)
                indexed_count += 1
                relationships_count += 1

    return f"Project indexed: {indexed_count} entities, {relationships_count} relationships stored in Knowledge Graph."
