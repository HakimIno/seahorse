"""seahorse_ai.tools.visual.project_visualizer — Architectural graphs via ECharts.
"""

from __future__ import annotations

import logging

from seahorse_ai.tools.base import tool

logger = logging.getLogger(__name__)

@tool("Generate a professional module-dependency graph of the project using ECharts.")
async def visualize_project() -> str:
    """Read the Knowledge Graph and compose a force-directed EChart."""
    from seahorse_ai.core.nodes import SeahorseGraphManager
    from seahorse_ai.tools.visual.echarts_composer import echarts_composer
    from seahorse_ai.tools.internal.project_indexer import index_project
    
    # 1. Ensure project is indexed
    await index_project()
    
    memory = SeahorseGraphManager.get_memory()
    graph = memory.inner.graph.read()
    
    nodes = []
    links = []
    
    # Map Rust Graph Nodes/Edges to ECharts formats
    for node_id, node in graph.nodes.items():
        nodes.append({
            "name": node.label,
            "id": node_id,
            "symbolSize": 30 if "crate" in node_id else 20,
            "category": 0 if "crate" in node_id else 1,
            "label": {"show": True}
        })
        
    for edge in graph.edges:
        links.append({
            "source": edge.source,
            "target": edge.target,
            "label": {"show": False, "formatter": edge.predicate}
        })

    option = {
        "title": {
            "text": "Seahorse Project Architecture",
            "subtext": "Knowledge Graph Visualization",
            "left": "center",
            "textStyle": {"fontFamily": "IBMPlexSansThai"}
        },
        "legend": [{"data": ["Crates", "Modules"], "orient": "vertical", "left": "left"}],
        "series": [{
            "type": "graph",
            "layout": "force",
            "data": nodes,
            "links": links,
            "categories": [{"name": "Crates"}, {"name": "Modules"}],
            "roam": True,
            "label": {"position": "right"},
            "force": {"repulsion": 100, "edgeLength": 50}
        }]
    }
    
    return await echarts_composer(option)
