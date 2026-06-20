"""Graph-algorithm tests — the highest-signal block in this suite.

We test DFS cycle detection and Kahn's topo sort against the same families
of graphs (empty, single, linear, diamond, cycles, disconnected, self-loop,
dangling edges) so any divergence between the two implementations is caught.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graph import is_dag_with_cycle, topological_order


def test_empty_graph_is_dag():
    is_dag, cycle = is_dag_with_cycle([], [])
    assert is_dag is True
    assert cycle is None
    assert topological_order([], []) == []


def test_single_node_is_dag():
    assert is_dag_with_cycle(["a"], []) == (True, None)
    assert topological_order(["a"], []) == ["a"]


def test_linear_chain():
    nodes = ["a", "b", "c"]
    edges = [("a", "b"), ("b", "c")]
    assert is_dag_with_cycle(nodes, edges)[0] is True
    assert topological_order(nodes, edges) == ["a", "b", "c"]


def test_diamond_is_dag():
    nodes = ["a", "b", "c", "d"]
    edges = [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")]
    is_dag, cycle = is_dag_with_cycle(nodes, edges)
    assert is_dag is True
    order = topological_order(nodes, edges)
    # `a` first, `d` last; b/c can come in either order.
    assert order[0] == "a"
    assert order[-1] == "d"
    assert set(order[1:3]) == {"b", "c"}


def test_self_loop_is_cycle():
    is_dag, cycle = is_dag_with_cycle(["a"], [("a", "a")])
    assert is_dag is False
    assert "a" in cycle
    assert topological_order(["a"], [("a", "a")]) is None


def test_two_node_cycle():
    is_dag, cycle = is_dag_with_cycle(["a", "b"], [("a", "b"), ("b", "a")])
    assert is_dag is False
    assert set(cycle) == {"a", "b"}
    assert topological_order(["a", "b"], [("a", "b"), ("b", "a")]) is None


def test_three_node_cycle():
    nodes = ["a", "b", "c"]
    edges = [("a", "b"), ("b", "c"), ("c", "a")]
    is_dag, cycle = is_dag_with_cycle(nodes, edges)
    assert is_dag is False
    assert set(cycle) == {"a", "b", "c"}


def test_disconnected_components_dag():
    nodes = ["a", "b", "c", "d"]
    edges = [("a", "b"), ("c", "d")]
    assert is_dag_with_cycle(nodes, edges)[0] is True
    order = topological_order(nodes, edges)
    assert order.index("a") < order.index("b")
    assert order.index("c") < order.index("d")


def test_dangling_edge_ignored():
    # Edge to a node id we never declared — graph layer should drop it
    # silently rather than crash, since the frontend may strip nodes mid-edit.
    nodes = ["a"]
    edges = [("a", "ghost")]
    assert is_dag_with_cycle(nodes, edges)[0] is True
    assert topological_order(nodes, edges) == ["a"]


def test_cycle_among_subgraph_with_dag_neighbors():
    # a → b ⇄ c → d, the b/c cycle must still be detected.
    nodes = ["a", "b", "c", "d"]
    edges = [("a", "b"), ("b", "c"), ("c", "b"), ("c", "d")]
    is_dag, cycle = is_dag_with_cycle(nodes, edges)
    assert is_dag is False
    assert {"b", "c"} <= set(cycle)
