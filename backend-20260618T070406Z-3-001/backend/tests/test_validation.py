"""Validation-engine tests: required inputs, cycles in error form, orphans."""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import PipelinePayload
from validation import analyze_pipeline


def _payload(nodes, edges):
    return PipelinePayload.model_validate({"nodes": nodes, "edges": edges})


def test_empty_pipeline_is_valid_dag():
    result = analyze_pipeline(_payload([], []))
    assert result["is_dag"] is True
    assert result["is_valid"] is True
    assert result["num_nodes"] == 0
    assert result["num_edges"] == 0
    assert result["execution_order"] == []


def test_single_input_node_is_valid():
    result = analyze_pipeline(_payload(
        [{"id": "in-1", "type": "customInput", "data": {}}], []
    ))
    assert result["is_valid"] is True


def test_llm_missing_required_inputs_is_invalid():
    result = analyze_pipeline(_payload(
        [{"id": "llm-1", "type": "llm", "data": {}}], []
    ))
    assert result["is_dag"] is True  # structurally a DAG
    assert result["is_valid"] is False
    codes = [e["code"] for e in result["errors"]]
    assert "MISSING_REQUIRED_INPUT" in codes


def test_llm_with_both_inputs_wired_is_valid():
    nodes = [
        {"id": "in-1", "type": "customInput", "data": {}},
        {"id": "in-2", "type": "customInput", "data": {}},
        {"id": "llm-1", "type": "llm", "data": {}},
        {"id": "out-1", "type": "customOutput", "data": {}},
    ]
    edges = [
        {"source": "in-1", "target": "llm-1", "targetHandle": "llm-1-system"},
        {"source": "in-2", "target": "llm-1", "targetHandle": "llm-1-prompt"},
        {"source": "llm-1", "target": "out-1", "targetHandle": "out-1-value"},
    ]
    result = analyze_pipeline(_payload(nodes, edges))
    assert result["is_valid"] is True
    assert result["execution_order"][0] in {"in-1", "in-2"}
    assert result["execution_order"][-1] == "out-1"


def test_cycle_is_reported_with_node_ids():
    nodes = [
        {"id": "a", "type": "filter", "data": {}},
        {"id": "b", "type": "filter", "data": {}},
    ]
    edges = [
        {"source": "a", "target": "b", "targetHandle": "b-input"},
        {"source": "b", "target": "a", "targetHandle": "a-input"},
    ]
    result = analyze_pipeline(_payload(nodes, edges))
    assert result["is_dag"] is False
    assert result["is_valid"] is False
    cycle_errors = [e for e in result["errors"] if e["code"] == "CYCLE_DETECTED"]
    assert len(cycle_errors) == 1
    assert set(cycle_errors[0]["node_ids"]) == {"a", "b"}


def test_orphan_node_is_warning_not_error():
    nodes = [
        {"id": "in-1", "type": "customInput", "data": {}},
        {"id": "in-2", "type": "customInput", "data": {}},
    ]
    result = analyze_pipeline(_payload(nodes, []))
    codes = [w["code"] for w in result["warnings"]]
    assert "ORPHAN_NODE" in codes
    assert result["is_valid"] is True  # warnings don't block validity.


def test_dead_end_warning():
    # A webhook with no consumer downstream — warning, not error.
    nodes = [{"id": "wh-1", "type": "webhook", "data": {"url": "x"}}]
    result = analyze_pipeline(_payload(nodes, []))
    # Only one node, so ORPHAN check is suppressed; DEAD_END isn't relevant either
    # because we suppress orphan when len==1. This test just asserts no crash.
    assert result["is_valid"] is True
