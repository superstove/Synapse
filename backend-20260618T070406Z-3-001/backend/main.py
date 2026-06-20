"""VectorShift pipeline analysis + mock execution backend.

Split into three layers so each piece is independently testable:
- `models.py`         pydantic schemas shared by every endpoint.
- `graph.py`          pure graph algorithms (DAG check, Kahn's topo sort).
- `validation.py`     pipeline-shaped checks built on top of the graph layer.
- `execution.py`      mock per-node execution that walks the topo order.
- `storage.py`        SQLAlchemy persistence layer.
- `main.py` (this)    FastAPI routes — thin glue, no business logic.
"""

from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from models import PipelinePayload, SavedPipelineCreate, SavedPipelineOut
from validation import analyze_pipeline
from execution import run_pipeline
from storage import init_db, create_pipeline, list_pipelines, get_pipeline, delete_pipeline

app = FastAPI(title="VectorShift Pipeline Service")

# CRA dev server runs on 3000; permissive CORS is fine for a take-home but
# would be tightened to a domain allowlist in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/")
def read_root() -> Dict[str, str]:
    return {"Ping": "Pong"}


# Lightweight liveness probe — uptime monitors hit this to keep Render
# free-tier instances warm. Cheaper than `/` because there's no DB call,
# no logic, and the response is tiny. Returns 200 with a timestamp so the
# checker can confirm freshness, not just connectivity.
@app.get("/health")
def health() -> Dict[str, Any]:
    import time
    return {"ok": True, "ts": int(time.time())}


# Live pytest runner — shells out to the same pytest invocation a dev would
# run from CLI, parses the summary, returns per-file pass/fail counts. We
# run with `-q` so we don't pay for verbose output and ship JSON to the
# frontend Tests tab. Synchronous + simple — pytest takes ~3s for this suite.
@app.post("/tests/run")
def run_tests() -> Dict[str, Any]:
    import os
    import re
    import subprocess
    import time

    started = time.time()
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", "tests/", "-q", "--tb=no", "--no-header"],
            cwd=backend_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )
        stdout = result.stdout
        elapsed_ms = int((time.time() - started) * 1000)

        # Parse the trailing summary line, e.g. "89 passed, 3 warnings in 3.08s".
        summary_match = re.search(
            r"(\d+) passed|(\d+) failed|(\d+) error|(\d+) skipped", stdout
        )
        passed_match = re.search(r"(\d+) passed", stdout)
        failed_match = re.search(r"(\d+) failed", stdout)
        error_match = re.search(r"(\d+) errors?", stdout)
        skipped_match = re.search(r"(\d+) skipped", stdout)

        # Per-file rollup — scan dotted progress lines that pytest -q emits.
        files: Dict[str, Dict[str, int]] = {}
        for line in stdout.splitlines():
            # Lines that look like "tests/test_graph.py ........"
            file_match = re.match(r"(tests/\S+\.py)\s+([.FEs]+)", line)
            if file_match:
                path, dots = file_match.group(1), file_match.group(2)
                files.setdefault(path, {"passed": 0, "failed": 0, "skipped": 0})
                files[path]["passed"] += dots.count(".")
                files[path]["failed"] += dots.count("F") + dots.count("E")
                files[path]["skipped"] += dots.count("s")

        return {
            "ok": result.returncode == 0,
            "passed": int(passed_match.group(1)) if passed_match else 0,
            "failed": int(failed_match.group(1)) if failed_match else 0,
            "errors": int(error_match.group(1)) if error_match else 0,
            "skipped": int(skipped_match.group(1)) if skipped_match else 0,
            "elapsed_ms": elapsed_ms,
            "files": files,
            "raw_tail": stdout.strip().splitlines()[-3:] if stdout else [],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "passed": 0, "failed": 0, "errors": 1,
                "files": {}, "raw_tail": ["Test run timed out after 60s"]}
    except Exception as exc:
        return {"ok": False, "passed": 0, "failed": 0, "errors": 1,
                "files": {}, "raw_tail": [f"Failed to run pytest: {exc}"]}


@app.post("/pipelines/parse")
def parse_pipeline(payload: PipelinePayload) -> Dict[str, Any]:
    """Analyze the pipeline graph: counts, DAG check, topo order, errors/warnings."""
    return analyze_pipeline(payload)


@app.post("/pipelines/run")
def run_pipeline_endpoint(payload: PipelinePayload) -> Dict[str, Any]:
    """Mock-execute the pipeline in topological order, returning per-node outputs."""
    analysis = analyze_pipeline(payload)
    if not analysis["is_dag"]:
        raise HTTPException(status_code=400, detail="Cannot run: pipeline is not a DAG")
    return run_pipeline(payload, analysis["execution_order"])


# ------- Persistence ---------------------------------------------------------


@app.get("/pipelines", response_model=List[SavedPipelineOut])
def list_saved_pipelines() -> List[SavedPipelineOut]:
    return list_pipelines()


@app.post("/pipelines", response_model=SavedPipelineOut)
def save_pipeline(payload: SavedPipelineCreate) -> SavedPipelineOut:
    return create_pipeline(payload)


@app.get("/pipelines/{pipeline_id}", response_model=SavedPipelineOut)
def load_pipeline(pipeline_id: int) -> SavedPipelineOut:
    pipeline = get_pipeline(pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return pipeline


@app.delete("/pipelines/{pipeline_id}")
def remove_pipeline(pipeline_id: int) -> Dict[str, bool]:
    ok = delete_pipeline(pipeline_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return {"deleted": True}
