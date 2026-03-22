import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def robust_json_load(text: str) -> Any:
    """Extract and parse JSON from text, handling markdown fences or preamble."""
    text = text.strip()
    # Check for object { }
    start_obj = text.find("{")
    end_obj = text.rfind("}")
    # Check for list [ ]
    start_list = text.find("[")
    end_list = text.rfind("]")

    # Find the outermost structure
    start = -1
    end = -1

    if start_obj != -1 and (start_list == -1 or start_obj < start_list):
        start, end = start_obj, end_obj
    elif start_list != -1:
        start, end = start_list, end_list

    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {}


def split_entities(entity: str) -> list[str]:
    """Split comma/และ/and-separated items into individual facts."""
    # Only split on ", " (comma + space) to avoid splitting "1,200"
    parts = re.split(r",\s+|\sและ\s|\sand\s", entity, flags=re.IGNORECASE)
    items = [p.strip() for p in parts if p.strip() and len(p.strip()) > 3]
    return items if items else [entity]
