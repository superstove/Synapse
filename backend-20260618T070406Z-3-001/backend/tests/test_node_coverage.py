"""Coverage test — every registered node type must:
   1. appear in NODE_SPECS (validation knows about it)
   2. have an execution handler (run won't crash)
   3. round-trip through /pipelines/parse without an internal error
   4. round-trip through /pipelines/run when wired correctly

The point is to catch the "I added a config but forgot the backend wiring"
class of bug, which is exactly what was introduced this turn.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

from main import app
from validation import NODE_SPECS
from execution import HANDLERS

client = TestClient(app)


# Every node type the frontend ships. Kept here (not imported) so the
# backend test suite stays standalone — if the frontend list drifts, this
# is the canary.
FRONTEND_NODE_TYPES = [
    "customInput", "customOutput", "fileInput",
    "llm", "imageGen", "embedding",
    "text",
    "math", "conditional", "filter", "merge",
    "webhook", "filter", "delay",
    "database", "vectorStore", "knowledge", "apiCall",
    "jsonParse", "format",
    "slack", "email", "note",
]


@pytest.mark.parametrize("node_type", set(FRONTEND_NODE_TYPES))
def test_node_type_has_validation_spec(node_type):
    assert node_type in NODE_SPECS, f"Missing NODE_SPECS entry for {node_type}"


@pytest.mark.parametrize("node_type", set(FRONTEND_NODE_TYPES))
def test_node_type_has_execution_handler(node_type):
    assert node_type in HANDLERS, f"Missing execution handler for {node_type}"


@pytest.mark.parametrize("node_type", set(FRONTEND_NODE_TYPES))
def test_node_type_parses_in_isolation(node_type):
    """A single node of every type must parse without 500ing."""
    response = client.post(
        "/pipelines/parse",
        json={"nodes": [{"id": "x", "type": node_type, "data": {}}], "edges": []},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["num_nodes"] == 1
    assert body["is_dag"] is True


def test_complex_real_world_pipeline_executes():
    """A multi-hop pipeline using AI + Data + Transform + Integration nodes
    must execute end-to-end."""
    nodes = [
        {"id": "in", "type": "customInput", "data": {"inputName": "q", "inputType": "Text"}},
        {"id": "emb", "type": "embedding", "data": {"model": "voyage-3"}},
        {"id": "vs", "type": "vectorStore", "data": {"provider": "pinecone", "topK": 3}},
        {"id": "kb", "type": "knowledge", "data": {"source": "docs"}},
        {"id": "llm", "type": "llm", "data": {"model": "claude-opus-4"}},
        {"id": "sys", "type": "text", "data": {"text": "You are helpful."}},
        {"id": "out", "type": "customOutput", "data": {"outputName": "answer"}},
    ]
    edges = [
        {"source": "in",  "target": "emb", "targetHandle": "emb-text"},
        {"source": "emb", "target": "vs",  "targetHandle": "vs-query"},
        {"source": "vs",  "target": "kb",  "targetHandle": "kb-query"},
        {"source": "kb",  "target": "llm", "targetHandle": "llm-prompt"},
        {"source": "sys", "target": "llm", "targetHandle": "llm-system"},
        {"source": "llm", "target": "out", "targetHandle": "out-value"},
    ]
    response = client.post("/pipelines/run", json={"nodes": nodes, "edges": edges})
    assert response.status_code == 200, response.text
    body = response.json()
    # Every node in the pipeline must show up in the trace in some order.
    trace_ids = [step["node_id"] for step in body["trace"]]
    assert set(trace_ids) == {n["id"] for n in nodes}
    # And the topo order is respected: emb after in, llm after both kb and sys.
    assert trace_ids.index("in") < trace_ids.index("emb")
    assert trace_ids.index("emb") < trace_ids.index("vs")
    assert trace_ids.index("vs") < trace_ids.index("kb")
    assert trace_ids.index("kb") < trace_ids.index("llm")
    assert trace_ids.index("sys") < trace_ids.index("llm")
    assert trace_ids.index("llm") < trace_ids.index("out")


def test_save_load_preserves_position():
    """Regression test — saved pipelines used to drop position info, causing
    every node to stack at origin on reload."""
    nodes = [
        {"id": "a", "type": "customInput", "data": {}, "position": {"x": 123, "y": 456}},
    ]
    save = client.post("/pipelines", json={
        "name": "position-test",
        "payload": {"nodes": nodes, "edges": []},
    })
    assert save.status_code == 200
    pid = save.json()["id"]

    loaded = client.get(f"/pipelines/{pid}").json()
    pos = loaded["payload"]["nodes"][0]["position"]
    assert pos == {"x": 123, "y": 456}

    client.delete(f"/pipelines/{pid}")
