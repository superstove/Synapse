"""Pure graph algorithms — no FastAPI / pydantic imports here.

Two separate algorithms because they answer different questions:

* `is_dag_with_cycle`: DFS three-color marking. Best when you only need a
  yes/no for cycle existence and want to *report which nodes form the cycle*.
* `topological_order`: Kahn's algorithm (BFS with in-degree zero queue).
  Best when you need the actual execution order. Returns None if a cycle
  exists, so it doubles as a second cycle check — both algorithms agree
  on `is_dag` for a given graph.
"""

from collections import deque
from typing import Dict, List, Optional, Tuple


def _build_adjacency(node_ids: List[str], edges: List[Tuple[str, str]]) -> Dict[str, List[str]]:
    adjacency: Dict[str, List[str]] = {node_id: [] for node_id in node_ids}
    for source, target in edges:
        if source in adjacency and target in adjacency:
            adjacency[source].append(target)
    return adjacency


def is_dag_with_cycle(
    node_ids: List[str], edges: List[Tuple[str, str]]
) -> Tuple[bool, Optional[List[str]]]:
    """Iterative three-color DFS.

    Returns `(is_dag, cycle_path)`. `cycle_path` is the list of node ids that
    form the discovered cycle (the back edge target through the GRAY stack
    back to itself), useful for human-readable error messages.

    Complexity: O(V + E). Each node transitions WHITE → GRAY → BLACK exactly
    once; each edge is inspected once while its source is GRAY. Iterative
    stack avoids Python's recursion limit on deep graphs.
    """
    WHITE, GRAY, BLACK = 0, 1, 2

    adjacency = _build_adjacency(node_ids, edges)
    color: Dict[str, int] = {node_id: WHITE for node_id in adjacency}
    # parent map lets us reconstruct the cycle once we hit a back edge.
    parent: Dict[str, Optional[str]] = {node_id: None for node_id in adjacency}

    for start in adjacency:
        if color[start] != WHITE:
            continue
        stack: List[Tuple[str, iter]] = [(start, iter(adjacency[start]))]
        color[start] = GRAY
        while stack:
            node_id, neighbors = stack[-1]
            next_neighbor = next(neighbors, None)
            if next_neighbor is None:
                color[node_id] = BLACK
                stack.pop()
                continue
            if next_neighbor not in color:
                continue
            neighbor_color = color[next_neighbor]
            if neighbor_color == GRAY:
                # Walk parent chain from node_id back to next_neighbor.
                cycle = [next_neighbor, node_id]
                cursor = parent[node_id]
                while cursor is not None and cursor != next_neighbor:
                    cycle.append(cursor)
                    cursor = parent[cursor]
                cycle.reverse()
                return False, cycle
            if neighbor_color == WHITE:
                parent[next_neighbor] = node_id
                color[next_neighbor] = GRAY
                stack.append((next_neighbor, iter(adjacency[next_neighbor])))
    return True, None


def topological_order(
    node_ids: List[str], edges: List[Tuple[str, str]]
) -> Optional[List[str]]:
    """Kahn's algorithm.

    Repeatedly remove a node with in-degree 0, push it onto the order, and
    decrement in-degree on its successors. If we drain every node, the order
    is valid; if any node remains with non-zero in-degree, a cycle exists
    and we return None.

    Why use this *in addition to* DFS: Kahn's naturally produces a stable,
    left-to-right execution order that's intuitive for a pipeline UI — node
    A is always before node B if A feeds B. DFS post-order would also work
    but reads "right to left" without a reverse.

    Complexity: O(V + E). Each node enters and leaves the queue once; each
    edge is decremented once.
    """
    adjacency = _build_adjacency(node_ids, edges)
    in_degree: Dict[str, int] = {node_id: 0 for node_id in adjacency}
    for source in adjacency:
        for target in adjacency[source]:
            in_degree[target] += 1

    # Stable ordering: process nodes in their original insertion order so a
    # given pipeline always produces the same execution_order (helpful for
    # demo recordings and test assertions).
    queue: deque = deque([nid for nid in adjacency if in_degree[nid] == 0])
    order: List[str] = []

    while queue:
        node_id = queue.popleft()
        order.append(node_id)
        for neighbor in adjacency[node_id]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(order) != len(adjacency):
        return None  # cycle present.
    return order
