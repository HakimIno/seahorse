import logging
import json
from datetime import datetime
from typing import Any
from seahorse_ai.engines.graph_db import GraphManager

logger = logging.getLogger(__name__)

class HindsightVisualizer:
    def __init__(self):
        self.graph = GraphManager()

    async def generate_mermaid(self) -> str:
        """Generate a Mermaid.js flowchart string from the knowledge graph."""
        rels = await self.graph.get_all_relationships()
        if not rels:
            return "graph TD\n  EmptyGraph[Knowledge Graph is Empty]"
        
        lines = ["graph TD"]
        # Use descriptive styles
        lines.append("  classDef person fill:#f9f,stroke:#333,stroke-width:4px;")
        lines.append("  classDef entity fill:#bbf,stroke:#333,stroke-width:2px;")
        
        seen_edges = set()
        
        for r in rels:
            src = r['source'].replace(" ", "_").replace("-", "_")
            tgt = r['target'].replace(" ", "_").replace("-", "_")
            rel = r['relationship']
            
            edge = f"  {src}({r['source']}) -->|{rel}| {tgt}({r['target']})"
            if edge not in seen_edges:
                lines.append(edge)
                seen_edges.add(edge)
                
            # Apply styles
            if r['source_type'] == 'PERSON':
                lines.append(f"  class {src} person")
            if r['target_type'] == 'PERSON':
                lines.append(f"  class {tgt} person")

        return "\n".join(lines)

    async def generate_d3_json(self) -> str:
        """Generate JSON format for D3.js force-directed graph."""
        rels = await self.graph.get_all_relationships()
        nodes = {}
        links = []
        
        for r in rels:
            s = r['source']
            o = r['target']
            if s not in nodes:
                nodes[s] = {"id": s, "group": 1, "type": r['source_type']}
            if o not in nodes:
                nodes[o] = {"id": o, "group": 2, "type": r['target_type']}
            
            links.append({
                "source": s,
                "target": o,
                "value": 1,
                "label": r['relationship']
            })
            
        return json.dumps({
            "nodes": list(nodes.values()),
            "links": links
        }, indent=2)

    async def generate_academic_ui(self, title: str = "Hindsight Knowledge Graph") -> str:
        """Generate a standalone HTML file with professional academic styling."""
        d3_json = await self.generate_d3_json()
        
        html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{title}}</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600&family=Lora:ital,wght@0,400;0,700;1,400&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-color: #ffffff;
            --text-primary: #1a1a1a;
            --text-secondary: #666666;
            --accent-blue: #2563eb;
            --border-color: #e5e7eb;
            --node-person: #ef4444;
            --node-entity: #3b82f6;
            --node-record: #10b981;
        }}

        body {{
            font-family: 'Inter', sans-serif;
            margin: 0;
            background-color: var(--bg-color);
            color: var(--text-primary);
            display: flex;
            height: 100vh;
            overflow: hidden;
        }}

        /* Sidebar Styling (Academic Format) */
        #sidebar {{
            width: 320px;
            border-right: 1px solid var(--border-color);
            padding: 40px 24px;
            display: flex;
            flex-direction: column;
            background: #fafafa;
        }}

        h1 {{
            font-family: 'Lora', serif;
            font-size: 1.5rem;
            font-weight: 700;
            margin: 0 0 8px 0;
            letter-spacing: -0.02em;
        }}

        .subtitle {{
            font-size: 0.875rem;
            color: var(--text-secondary);
            margin-bottom: 32px;
            line-height: 1.5;
        }}

        .stats-box {{
            background: white;
            border: 1px solid var(--border-color);
            padding: 16px;
            border-radius: 8px;
            margin-bottom: 24px;
        }}

        .stat-item {{
            display: flex;
            justify-content: space-between;
            margin-bottom: 8px;
            font-size: 0.9rem;
        }}

        .stat-value {{
            font-weight: 600;
        }}

        /* Graph Canvas */
        #canvas {{
            flex-grow: 1;
            position: relative;
            cursor: grab;
        }}

        #canvas:active {{ cursor: grabbing; }}

        .node circle {{
            stroke: #fff;
            stroke-width: 2px;
            transition: r 0.2s ease;
        }}

        .node text {{
            font-size: 11px;
            font-weight: 500;
            pointer-events: none;
            fill: var(--text-primary);
        }}

        .link {{
            stroke: #999;
            stroke-opacity: 0.4;
            stroke-width: 1px;
        }}

        .link-text {{
            font-size: 9px;
            fill: #aaa;
            pointer-events: none;
        }}

        .tooltip {{
            position: absolute;
            background: rgba(255, 255, 255, 0.95);
            border: 1px solid var(--border-color);
            padding: 12px;
            border-radius: 6px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.05);
            font-size: 0.8rem;
            pointer-events: none;
            opacity: 0;
        }}
    </style>
</head>
<body>
    <div id="sidebar">
        <h1>Hindsight Graph</h1>
        <p class="subtitle">Neural network of extracted entities and relationships within the Seahorse memory system.</p>
        
        <div class="stats-box">
            <div class="stat-item"><span>Total Entities</span><span class="stat-value" id="count-nodes">-</span></div>
            <div class="stat-item"><span>Relationships</span><span class="stat-value" id="count-links">-</span></div>
        </div>

        <div style="margin-top: auto; font-size: 0.75rem; color: #aaa;">
            Reference: Seahorse Hindsight Reasoning Engine v1.2<br>
            Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}
        </div>
    </div>

    <div id="canvas"></div>
    <div class="tooltip" id="tooltip"></div>

    <script>
        const data = {d3_json};
        
        document.getElementById('count-nodes').innerText = data.nodes.length;
        document.getElementById('count-links').innerText = data.links.length;

        const width = window.innerWidth - 320;
        const height = window.innerHeight;

        const svg = d3.select("#canvas").append("svg")
            .attr("width", width)
            .attr("height", height)
            .call(d3.zoom().on("zoom", function (event) {{
                container.attr("transform", event.transform);
            }}));

        const container = svg.append("g");

        const simulation = d3.forceSimulation(data.nodes)
            .force("link", d3.forceLink(data.links).id(d => d.id).distance(120))
            .force("charge", d3.forceManyBody().strength(-300))
            .force("center", d3.forceCenter(width / 2, height / 2))
            .force("collision", d3.forceCollide().radius(40));

        const link = container.append("g")
            .selectAll("line")
            .data(data.links)
            .join("line")
            .attr("class", "link");

        const edgeText = container.append("g")
            .selectAll("text")
            .data(data.links)
            .join("text")
            .attr("class", "link-text")
            .text(d => d.label);

        const node = container.append("g")
            .selectAll(".node")
            .data(data.nodes)
            .join("g")
            .attr("class", "node")
            .call(d3.drag()
                .on("start", dragstarted)
                .on("drag", dragged)
                .on("end", dragended));

        node.append("circle")
            .attr("r", 8)
            .attr("fill", d => {{
                if (d.type === 'PERSON') return "#ef4444";
                if (d.type === 'HindsightRecord') return "#10b981";
                return "#3b82f6";
            }});

        node.append("text")
            .attr("dx", 12)
            .attr("dy", 4)
            .text(d => d.id);

        simulation.on("tick", () => {{
            link
                .attr("x1", d => d.source.x)
                .attr("y1", d => d.source.y)
                .attr("x2", d => d.target.x)
                .attr("y2", d => d.target.y);

            node
                .attr("transform", d => `translate(${{d.x}}, ${{d.y}})`);

            edgeText
                .attr("x", d => (d.source.x + d.target.x) / 2)
                .attr("y", d => (d.source.y + d.target.y) / 2);
        }});

        function dragstarted(event, d) {{
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
        }}

        function dragged(event, d) {{
            d.fx = event.x;
            d.fy = event.y;
        }}

        function dragended(event, d) {{
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
        }}
    </script>
</body>
</html>"""
        return html_template
