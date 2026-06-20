"""Pipeline-shaped validation built on top of `graph.py`.

A real pipeline-builder backend doesn't just answer "is this a DAG?" — it
tells the user *what's wrong* and *what would run*. This module returns:

    {
      num_nodes, num_edges,
      is_dag, is_valid,
      execution_order: [node_id, ...],
      errors:    [{ code, message, node_ids }],
      warnings:  [{ code, message, node_ids }],
    }

`is_valid` is `is_dag and not errors`. Warnings don't block execution.

Node-type expectations (which inputs are required) live in `NODE_SPECS`
below, mirroring the frontend's NODE_CONFIGS. Kept here so the backend can
validate independently of whatever the frontend chose to send.
"""

from typing import Any, Dict, List, Set

from graph import is_dag_with_cycle, topological_order
from models import PipelinePayload


# Required target-handle ids per node type. Pulled from the frontend node
# configs so a node missing a required input is flagged before execution.
NODE_SPECS: Dict[str, Dict[str, List[str]]] = {
    # I/O
    "customInput":  {"required_inputs": [], "outputs": ["value"]},
    "customOutput": {"required_inputs": ["value"], "outputs": []},
    "fileInput":    {"required_inputs": [], "outputs": ["file"]},
    # AI
    "llm":          {"required_inputs": ["system", "prompt"], "outputs": ["response"]},
    "imageGen":     {"required_inputs": ["prompt"], "outputs": ["image"]},
    "embedding":    {"required_inputs": ["text"], "outputs": ["vector"]},
    # Logic / Math
    "math":         {"required_inputs": ["a", "b"], "outputs": ["result"]},
    "conditional":  {"required_inputs": ["input"], "outputs": ["true", "false"]},
    "filter":       {"required_inputs": ["input"], "outputs": ["output"]},
    "merge":        {"required_inputs": ["a", "b"], "outputs": ["merged"]},
    # Data
    "database":     {"required_inputs": [], "outputs": ["rows"]},
    "vectorStore":  {"required_inputs": ["query"], "outputs": ["results"]},
    "knowledge":    {"required_inputs": ["query"], "outputs": ["context"]},
    "apiCall":      {"required_inputs": [], "outputs": ["response"]},
    # Transform
    "text":         {"required_inputs": [], "outputs": ["output"]},
    "jsonParse":    {"required_inputs": ["json"], "outputs": ["value"]},
    "format":       {"required_inputs": ["vars"], "outputs": ["text"]},
    # Integrations
    "webhook":      {"required_inputs": [], "outputs": ["payload"]},
    "slack":        {"required_inputs": ["message"], "outputs": ["sent"]},
    "email":        {"required_inputs": ["body"], "outputs": ["sent"]},
    # Utility
    "delay":        {"required_inputs": ["input"], "outputs": ["output"]},
    "note":         {"required_inputs": [], "outputs": []},
}


def _issue(code: str, message: str, node_ids: List[str] = None) -> Dict[str, Any]:
    return {"code": code, "message": message, "node_ids": node_ids or []}


def _connected_target_handles(node_id: str, edges) -> Set[str]:
    """Return the set of target-handle suffixes wired to a node.

    Edges from the frontend carry targetHandle of the shape `{nodeId}-{handleId}`,
    so we strip the prefix and surface just the handle name (e.g. "prompt").
    """
    connected: Set[str] = set()
    prefix = f"{node_id}-"
    for edge in edges:
        if edge.target != node_id:
            continue
        handle = edge.targetHandle or ""
        if handle.startswith(prefix):
            handle = handle[len(prefix):]
        connected.add(handle)
    return connected


def analyze_pipeline(payload: PipelinePayload) -> Dict[str, Any]:
    nodes = payload.nodes
    edges = payload.edges
    node_ids = [node.id for node in nodes]
    edge_pairs = [(e.source, e.target) for e in edges]

    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    # --- 1. Structural sanity: duplicate ids, edges pointing nowhere -------
    seen_ids: Set[str] = set()
    duplicates: List[str] = []
    for nid in node_ids:
        if nid in seen_ids:
            duplicates.append(nid)
        seen_ids.add(nid)
    if duplicates:
        errors.append(_issue(
            "DUPLICATE_NODE_ID",
            f"Duplicate node ids: {', '.join(sorted(set(duplicates)))}",
            duplicates,
        ))

    dangling: List[str] = []
    for edge in edges:
        if edge.source not in seen_ids or edge.target not in seen_ids:
            dangling.append(f"{edge.source} → {edge.target}")
    if dangling:
        warnings.append(_issue(
            "DANGLING_EDGE",
            f"Edges reference missing nodes: {'; '.join(dangling)}",
        ))

    # --- 2. DAG check ------------------------------------------------------
    is_dag, cycle = is_dag_with_cycle(node_ids, edge_pairs)
    if not is_dag:
        errors.append(_issue(
            "CYCLE_DETECTED",
            f"Pipeline contains a cycle: {' → '.join(cycle or [])}",
            cycle or [],
        ))

    # --- 3. Execution order (None if cyclic) -------------------------------
    order = topological_order(node_ids, edge_pairs) if is_dag else None

    # --- 4. Per-node connection checks -------------------------------------
    incoming_counts: Dict[str, int] = {nid: 0 for nid in node_ids}
    outgoing_counts: Dict[str, int] = {nid: 0 for nid in node_ids}
    for edge in edges:
        if edge.source in incoming_counts:
            outgoing_counts[edge.source] += 1
        if edge.target in incoming_counts:
            incoming_counts[edge.target] += 1

    for node in nodes:
        spec = NODE_SPECS.get(node.type or "", None)
        if spec is None:
            continue  # unknown node type — out of scope for validation.

        connected = _connected_target_handles(node.id, edges)
        missing = [h for h in spec["required_inputs"] if h not in connected]
        if missing:
            errors.append(_issue(
                "MISSING_REQUIRED_INPUT",
                f"Node {node.id} ({node.type}) is missing required input(s): "
                f"{', '.join(missing)}",
                [node.id],
            ))

        # Producer with no downstream consumer = dead branch (warning only —
        # a webhook firing without a downstream node is unusual but legal).
        if spec["outputs"] and outgoing_counts[node.id] == 0 and node.type != "customOutput":
            warnings.append(_issue(
                "DEAD_END",
                f"Node {node.id} ({node.type}) produces output but nothing consumes it.",
                [node.id],
            ))

    # --- 5. Orphans (no edges at all) --------------------------------------
    orphan_ids = [
        nid for nid in node_ids
        if incoming_counts[nid] == 0 and outgoing_counts[nid] == 0 and len(node_ids) > 1
    ]
    if orphan_ids:
        warnings.append(_issue(
            "ORPHAN_NODE",
            f"Disconnected node(s): {', '.join(orphan_ids)}",
            orphan_ids,
        ))

    return {
        "num_nodes": len(nodes),
        "num_edges": len(edges),
        "is_dag": is_dag,
        "is_valid": is_dag and not errors,
        "execution_order": order or [],
        "errors": errors,
        "warnings": warnings,
    }
