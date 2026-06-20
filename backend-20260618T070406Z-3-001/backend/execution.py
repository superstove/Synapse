"""Mock pipeline execution engine.

Walks the topological order produced by validation.analyze_pipeline and
produces a deterministic per-node output. Each node type has a small
handler that consumes the upstream outputs (looked up by the edge graph)
and produces a value.

This is intentionally a *mock* — no real LLM calls, no network — because:
1. The take-home doesn't require real execution.
2. Determinism makes the demo and the tests reliable.
3. The interesting engineering question is "how does the dataflow work?",
   not "does OpenAI's API key still work?".

Each handler returns a `{ value, log }` pair; the response is a flat
`{ node_id: { value, log, type } }` map plus a flat `trace[]` in execution
order so the frontend can animate nodes lighting up sequentially.
"""

import re
import time
from typing import Any, Callable, Dict, List

from models import PipelinePayload


# Re-used from the frontend TextNode — variables are valid JS identifiers
# surrounded by {{ }} with optional whitespace.
VARIABLE_REGEX = re.compile(r"\{\{\s*([A-Za-z_$][A-Za-z0-9_$]*)\s*\}\}")


def _resolve_incoming(
    node_id: str,
    edges,
    outputs: Dict[str, Any],
) -> Dict[str, Any]:
    """For a given node, collect the values feeding each of its target handles.

    Returns `{ handle_name: upstream_value }`. Handle names are the bare
    suffix (e.g. "prompt"), matching `validation.NODE_SPECS`.
    """
    incoming: Dict[str, Any] = {}
    prefix = f"{node_id}-"
    for edge in edges:
        if edge.target != node_id:
            continue
        handle = edge.targetHandle or ""
        if handle.startswith(prefix):
            handle = handle[len(prefix):]
        # The upstream node's output is stored under its node id; we take the
        # whole value bag. Real pipelines would also distinguish by source
        # handle (so an LLM with multiple outputs could route differently);
        # we keep it simple and just use the producing node's primary value.
        upstream = outputs.get(edge.source)
        if upstream is not None:
            incoming[handle] = upstream.get("value")
    return incoming


# ----- Per-node handlers -----------------------------------------------------


def _run_input(node, incoming):
    name = node.data.get("inputName", node.id)
    sample = node.data.get("inputType", "Text") == "File" and "<file.png>" or f"sample for {name}"
    return {"value": sample, "log": f"emit {name!r} = {sample!r}"}


def _run_output(node, incoming):
    value = incoming.get("value", "<no input>")
    return {"value": value, "log": f"capture output: {value!r}"}


def _run_llm(node, incoming):
    system = incoming.get("system", "(no system prompt)")
    prompt = incoming.get("prompt", "(no prompt)")
    fake = f"[LLM mock] response to {prompt!r} (system={system!r})"
    return {"value": fake, "log": f"prompt={prompt!r} system={system!r}"}


def _run_text(node, incoming):
    template = node.data.get("text", "")
    # Substitute every {{var}} with the upstream value wired to that variable
    # handle. Unwired variables are left as-is so the user can see the gap.
    def replace(match):
        name = match.group(1)
        return str(incoming.get(f"var-{name}", incoming.get(name, match.group(0))))
    rendered = VARIABLE_REGEX.sub(replace, template)
    return {"value": rendered, "log": f"rendered {len(rendered)} chars"}


def _run_math(node, incoming):
    op = node.data.get("operator", "+")
    a = incoming.get("a")
    b = incoming.get("b")
    try:
        a_num, b_num = float(a), float(b)
    except (TypeError, ValueError):
        return {"value": None, "log": f"inputs not numeric (a={a!r}, b={b!r})"}
    result = {
        "+": a_num + b_num,
        "-": a_num - b_num,
        "*": a_num * b_num,
        "/": (a_num / b_num) if b_num != 0 else None,
    }.get(op)
    return {"value": result, "log": f"{a_num} {op} {b_num} = {result}"}


def _run_conditional(node, incoming):
    val = incoming.get("input")
    truthy = bool(val)
    # Mock branches by emitting on whichever side won; the value passes through.
    return {"value": val, "log": f"branch={'true' if truthy else 'false'}"}


def _run_webhook(node, incoming):
    url = node.data.get("url", "")
    return {"value": {"status": 200, "url": url}, "log": f"POST {url} (mock 200 OK)"}


def _run_filter(node, incoming):
    condition = node.data.get("condition", "")
    val = incoming.get("input")
    # Mock: pass-through if condition non-empty, drop otherwise.
    passes = bool(condition)
    return {
        "value": val if passes else None,
        "log": f"condition={condition!r} → {'pass' if passes else 'drop'}",
    }


def _run_delay(node, incoming):
    ms = node.data.get("delayMs", 0)
    return {"value": incoming.get("input"), "log": f"delay {ms}ms (mocked, not slept)"}


def _run_file_input(node, incoming):
    accept = node.data.get("fileType", "*/*")
    return {"value": f"<mock-file accept={accept}>", "log": f"emit mock file ({accept})"}


def _run_image_gen(node, incoming):
    model = node.data.get("model", "dalle-3")
    size = node.data.get("size", "1024x1024")
    prompt = incoming.get("prompt", "(no prompt)")
    return {
        "value": {"url": f"https://mock.cdn/{model}.png", "size": size, "prompt": prompt},
        "log": f"{model} generated {size} from {prompt!r}",
    }


def _run_embedding(node, incoming):
    model = node.data.get("model", "text-embedding-3")
    text = incoming.get("text", "")
    # Mock vector — 4-dim is enough to display in the UI without flooding it.
    vec = [round(0.1 * (i + 1) * (len(str(text)) % 7 + 1), 3) for i in range(4)]
    return {"value": vec, "log": f"{model} → 4-dim mock vector"}


def _run_merge(node, incoming):
    return {
        "value": {"a": incoming.get("a"), "b": incoming.get("b")},
        "log": "combined a + b into object",
    }


def _run_database(node, incoming):
    engine = node.data.get("engine", "postgres")
    query = node.data.get("query", "")
    return {
        "value": [{"id": 1, "name": "Mock row"}],
        "log": f"{engine}: {query[:40]!r} → 1 row (mocked)",
    }


def _run_vector_store(node, incoming):
    provider = node.data.get("provider", "pinecone")
    top_k = int(node.data.get("topK", 5))
    query = incoming.get("query", "")
    return {
        "value": [{"id": f"doc-{i}", "score": round(0.95 - i * 0.05, 3)} for i in range(top_k)],
        "log": f"{provider} returned top-{top_k} for {str(query)[:30]!r}",
    }


def _run_knowledge(node, incoming):
    source = node.data.get("source", "kb")
    query = incoming.get("query", "")
    return {
        "value": f"[KB:{source}] context for {query!r}",
        "log": f"looked up {source}",
    }


def _run_api_call(node, incoming):
    method = node.data.get("method", "GET")
    url = node.data.get("url", "")
    return {
        "value": {"status": 200, "url": url, "method": method},
        "log": f"{method} {url} → 200 OK (mocked)",
    }


def _run_json_parse(node, incoming):
    import json
    path = node.data.get("path", "")
    raw = incoming.get("json")
    try:
        data = raw if isinstance(raw, (dict, list)) else json.loads(str(raw))
    except (ValueError, TypeError):
        return {"value": None, "log": f"invalid JSON input"}
    # Tiny dotted-path resolver: "data.items[0].name"
    cursor = data
    if path:
        for part in path.replace("[", ".").replace("]", "").split("."):
            if not part:
                continue
            try:
                cursor = cursor[int(part)] if part.isdigit() else cursor.get(part)
            except (AttributeError, KeyError, TypeError, IndexError):
                cursor = None
                break
    return {"value": cursor, "log": f"path={path!r}"}


def _run_format(node, incoming):
    template = node.data.get("template", "")
    vars_in = incoming.get("vars")
    if isinstance(vars_in, dict):
        try:
            rendered = template.format(**vars_in)
        except (KeyError, IndexError, ValueError):
            rendered = template
    else:
        rendered = template.replace("{{value}}", str(vars_in))
    return {"value": rendered, "log": f"rendered {len(rendered)} chars"}


def _run_slack(node, incoming):
    channel = node.data.get("channel", "")
    return {
        "value": {"ok": True, "channel": channel},
        "log": f"posted to {channel} (mocked)",
    }


def _run_email(node, incoming):
    to = node.data.get("to", "")
    subject = node.data.get("subject", "")
    return {
        "value": {"ok": True, "to": to, "subject": subject},
        "log": f"sent to {to} (mocked)",
    }


def _run_note(node, incoming):
    return {"value": None, "log": "note (no-op)"}


HANDLERS: Dict[str, Callable] = {
    "customInput": _run_input,
    "customOutput": _run_output,
    "fileInput": _run_file_input,
    "llm": _run_llm,
    "imageGen": _run_image_gen,
    "embedding": _run_embedding,
    "text": _run_text,
    "math": _run_math,
    "conditional": _run_conditional,
    "merge": _run_merge,
    "webhook": _run_webhook,
    "filter": _run_filter,
    "delay": _run_delay,
    "database": _run_database,
    "vectorStore": _run_vector_store,
    "knowledge": _run_knowledge,
    "apiCall": _run_api_call,
    "jsonParse": _run_json_parse,
    "format": _run_format,
    "slack": _run_slack,
    "email": _run_email,
    "note": _run_note,
}


def run_pipeline(payload: PipelinePayload, execution_order: List[str]) -> Dict[str, Any]:
    """Walk the topological order, running each node's handler with its
    resolved incoming values, and return both a flat outputs map and an
    ordered trace the frontend can animate."""
    started = time.time()
    nodes_by_id = {node.id: node for node in payload.nodes}
    outputs: Dict[str, Any] = {}
    trace: List[Dict[str, Any]] = []

    for node_id in execution_order:
        node = nodes_by_id.get(node_id)
        if node is None:
            continue
        handler = HANDLERS.get(node.type or "")
        incoming = _resolve_incoming(node_id, payload.edges, outputs)
        if handler is None:
            result = {"value": None, "log": f"no handler for type {node.type!r}"}
        else:
            result = handler(node, incoming)
        result["type"] = node.type
        outputs[node_id] = result
        trace.append({
            "node_id": node_id,
            "type": node.type,
            "incoming": incoming,
            "value": result["value"],
            "log": result["log"],
        })

    return {
        "outputs": outputs,
        "trace": trace,
        "elapsed_ms": int((time.time() - started) * 1000),
    }
