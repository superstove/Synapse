"""End-to-end HTTP tests using FastAPI's TestClient."""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

from main import app
from storage import init_db


@pytest.fixture(autouse=True)
def _db():
    init_db()
    yield


client = TestClient(app)


def test_parse_endpoint_returns_required_keys():
    response = client.post("/pipelines/parse", json={"nodes": [], "edges": []})
    assert response.status_code == 200
    body = response.json()
    for key in ("num_nodes", "num_edges", "is_dag", "is_valid", "execution_order", "errors", "warnings"):
        assert key in body


def test_run_rejects_cyclic_pipeline():
    body = {
        "nodes": [
            {"id": "a", "type": "filter", "data": {"condition": "x"}},
            {"id": "b", "type": "filter", "data": {"condition": "y"}},
        ],
        "edges": [
            {"source": "a", "target": "b", "targetHandle": "b-input"},
            {"source": "b", "target": "a", "targetHandle": "a-input"},
        ],
    }
    response = client.post("/pipelines/run", json=body)
    assert response.status_code == 400


def test_run_executes_math_node():
    body = {
        "nodes": [
            {"id": "a", "type": "customInput", "data": {"inputName": "a", "inputType": "Text"}},
            {"id": "b", "type": "customInput", "data": {"inputName": "b", "inputType": "Text"}},
            {"id": "m", "type": "math", "data": {"operator": "+"}},
        ],
        "edges": [
            {"source": "a", "target": "m", "targetHandle": "m-a"},
            {"source": "b", "target": "m", "targetHandle": "m-b"},
        ],
    }
    response = client.post("/pipelines/run", json=body)
    assert response.status_code == 200
    trace = response.json()["trace"]
    assert [step["node_id"] for step in trace][-1] == "m"


def test_save_list_get_delete_pipeline():
    save = client.post("/pipelines", json={
        "name": "demo",
        "payload": {"nodes": [{"id": "x", "type": "customInput", "data": {}}], "edges": []},
    })
    assert save.status_code == 200
    pid = save.json()["id"]

    listing = client.get("/pipelines")
    assert listing.status_code == 200
    assert any(p["id"] == pid for p in listing.json())

    fetched = client.get(f"/pipelines/{pid}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "demo"

    deleted = client.delete(f"/pipelines/{pid}")
    assert deleted.status_code == 200

    missing = client.get(f"/pipelines/{pid}")
    assert missing.status_code == 404
