"""Telemetry aggregation service for Oddcrawler dashboard."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from urllib.request import urlopen

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from oddcrawler.config import load_app_config
from scripts import update_blocklist

RUNS_BASE = Path("var/runs")
DEFAULT_TELEMETRY_LIMIT = 200
ROOT = Path(__file__).resolve().parents[3]
PIPELINE_SCRIPT = ROOT / "scripts" / "run_pipeline.py"

_APP_CONFIG = load_app_config()
_dashboard_cfg = _APP_CONFIG.get("dashboard", {}) if isinstance(_APP_CONFIG, dict) else {}
_blocklist_cfg = _dashboard_cfg.get("blocklist", {}) if isinstance(_dashboard_cfg, dict) else {}

BLOCKLIST_SOURCE_URL = str(_blocklist_cfg.get("source_url") or "https://urlhaus.abuse.ch/downloads/text/")
BLOCKLIST_REFRESH_SECONDS = int(_blocklist_cfg.get("refresh_seconds") or 21600)
BLOCKLIST_MAX_HOSTS = int(_blocklist_cfg.get("max_hosts") or 2000)
BLOCKLIST_AUTO_REFRESH = bool(_blocklist_cfg.get("auto_refresh", False))

BLOCKLIST_RAW_PATH = ROOT / "var" / "oddcrawler" / "safety" / "urlhaus.txt"
BLOCKLIST_OUTPUT_PATH = ROOT / "config" / "safety" / "blocklist_hosts.txt"
BLOCKLIST_STATUS: Dict[str, Optional[Any]] = {
    "last_run": None,
    "last_error": None,
    "host_count": 0,
}
_BLOCKLIST_THREAD_STARTED = False


def _load_json(path: Path) -> Optional[Mapping[str, Any]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, Mapping) else None


def _build_links(run_dir: Path) -> Dict[str, str]:
    links: Dict[str, str] = {}
    summary = run_dir / "reports" / "summary.json"
    metrics = run_dir / "metrics.json"
    telemetry = run_dir / "telemetry.jsonl"
    frontier = run_dir / "state" / "frontier.json"

    if summary.exists():
        links["summary"] = str(summary)
    if metrics.exists():
        links["metrics"] = str(metrics)
    if telemetry.exists():
        links["telemetry"] = str(telemetry)
    if frontier.exists():
        links["frontier"] = str(frontier)
    return links


def _update_blocklist_status(host_count: int, error: Optional[str]) -> None:
    BLOCKLIST_STATUS["last_run"] = datetime.now(timezone.utc).isoformat()
    BLOCKLIST_STATUS["host_count"] = host_count
    BLOCKLIST_STATUS["last_error"] = error


def refresh_blocklist_from_source() -> Dict[str, Any]:
    BLOCKLIST_RAW_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload: Optional[str] = None
    try:
        with urlopen(BLOCKLIST_SOURCE_URL, timeout=30) as handle:
            payload = handle.read().decode("utf-8")
    except Exception as exc:  # pragma: no cover - network failure
        _update_blocklist_status(host_count=BLOCKLIST_STATUS.get("host_count") or 0, error=str(exc))
        raise

    assert payload is not None
    BLOCKLIST_RAW_PATH.write_text(payload, encoding="utf-8")
    hosts = update_blocklist.extract_hosts(payload.splitlines())
    trimmed = sorted(hosts)[: max(1, BLOCKLIST_MAX_HOSTS)]
    update_blocklist.write_blocklist(trimmed, BLOCKLIST_OUTPUT_PATH)
    _update_blocklist_status(host_count=len(trimmed), error=None)
    return {"hosts": len(trimmed)}


def _blocklist_refresh_worker() -> None:  # pragma: no cover - background thread
    while True:
        try:
            refresh_blocklist_from_source()
        except Exception:
            # status already recorded in helper
            pass
        time.sleep(max(300, BLOCKLIST_REFRESH_SECONDS))


def ensure_blocklist_refresher() -> None:
    global _BLOCKLIST_THREAD_STARTED
    if _BLOCKLIST_THREAD_STARTED or not BLOCKLIST_AUTO_REFRESH:
        return
    _BLOCKLIST_THREAD_STARTED = True
    thread = threading.Thread(target=_blocklist_refresh_worker, name="blocklist-refresh", daemon=True)
    thread.start()


def _derive_hourly_cap(metrics: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "cap_hits": metrics.get("llm_hourly_cap_hits", 0),
        "last_wait_seconds": metrics.get("last_llm_hourly_wait_seconds", 0.0),
    }


def _normalize_run(run_dir: Path, meta: Optional[Mapping[str, Any]] = None) -> Optional[Dict[str, Any]]:
    summary = _load_json(run_dir / "reports" / "summary.json") or {}
    metrics = _load_json(run_dir / "metrics.json") or {}
    telemetry_path = run_dir / "telemetry.jsonl"
    if not summary and not metrics and not telemetry_path.exists() and not meta:
        return None

    run_id = run_dir.name
    started = summary.get("run_started_at") or metrics.get("run_started_at")
    if not started and meta:
        started = meta.get("started_at")
    updated = summary.get("last_updated_at") or metrics.get("last_updated_at")
    if not updated and telemetry_path.exists():
        updated = datetime.fromtimestamp(telemetry_path.stat().st_mtime, tz=timezone.utc).isoformat()
    if not updated and meta:
        updated = meta.get("started_at")

    pages_processed = summary.get("pages_processed") or metrics.get("pages_processed") or 0
    actions = summary.get("actions") or metrics.get("actions") or {}
    llm_usage = summary.get("llm_usage") or metrics.get("llm_usage") or {}

    run_info = {
        "run_id": run_id,
        "path": str(run_dir),
        "started_at": started,
        "last_updated_at": updated,
        "pages_processed": pages_processed,
        "actions": actions,
        "llm_usage": llm_usage,
        "summary": summary,
        "metrics": metrics,
        "hourly_cap": _derive_hourly_cap(metrics),
        "links": _build_links(run_dir),
    }
    return run_info
    return run_info


def collect_runs(base_dir: Path = RUNS_BASE) -> List[Dict[str, Any]]:
    if not base_dir.exists():
        return []
    active_meta = CONTROLLER.active_metadata()
    runs: List[Dict[str, Any]] = []
    for child in sorted(base_dir.iterdir()):
        if not child.is_dir():
            continue
        metadata = active_meta.get(child.name)
        record = _normalize_run(child, meta=metadata)
        if record:
            runs.append(record)
    runs.sort(key=lambda item: item.get("last_updated_at") or "", reverse=True)
    return runs


def get_run(run_id: str, base_dir: Path = RUNS_BASE) -> Dict[str, Any]:
    run_dir = base_dir / run_id
    if not run_dir.exists() or not run_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    record = _normalize_run(run_dir)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No telemetry available for run '{run_id}'")
    return record


def read_telemetry_tail(run_id: str, limit: int = DEFAULT_TELEMETRY_LIMIT, base_dir: Path = RUNS_BASE) -> List[Mapping[str, Any]]:
    run_dir = base_dir / run_id
    telemetry_path = run_dir / "telemetry.jsonl"
    if not telemetry_path.exists():
        raise HTTPException(status_code=404, detail=f"Telemetry not found for run '{run_id}'")

    buffer: deque[str] = deque(maxlen=max(1, limit))
    with telemetry_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            buffer.append(line.strip())

    events: List[Mapping[str, Any]] = []
    for line in buffer:
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, Mapping):
            events.append(event)
    return events


app = FastAPI(title="Oddcrawler Dashboard")


UI_DIR = Path(__file__).resolve().parents[3] / "dashboard" / "ui"
app.mount("/ui", StaticFiles(directory=UI_DIR, html=True), name="dashboard-ui")
if not RUNS_BASE.exists():
    RUNS_BASE.mkdir(parents=True, exist_ok=True)

ensure_blocklist_refresher()


class StartRunRequest(BaseModel):
    run_dir: Optional[str] = Field(
        default=None,
        description="Optional run directory path. Defaults to var/runs/<timestamp>.",
    )
    max_pages: Optional[int] = Field(default=None, ge=1, description="Optional max pages to crawl.")
    sleep_seconds: Optional[float] = Field(default=0.0, ge=0.0, description="Optional delay between pages.")
    config: Optional[str] = Field(default=None, description="Custom config YAML path.")


class RunInfo(BaseModel):
    run_id: str
    run_dir: str
    pid: int
    returncode: Optional[int]
    started_at: str


class RunController:
    def __init__(self, *, root: Path, script: Path, interpreter: str) -> None:
        self._root = root
        self._script = script
        self._interpreter = interpreter
        self._lock = threading.Lock()
        self._processes: Dict[str, subprocess.Popen] = {}
        self._meta: Dict[str, Dict[str, Any]] = {}

    def list_active(self) -> List[RunInfo]:
        with self._lock:
            records: List[RunInfo] = []
            for run_id, proc in list(self._processes.items()):
                returncode = proc.poll()
                if returncode is not None:
                    # process finished, cleanup
                    self._processes.pop(run_id, None)
                    continue
                meta = self._meta.get(run_id, {})
                records.append(
                    RunInfo(
                        run_id=run_id,
                        run_dir=str(meta.get("run_dir", "")),
                        pid=getattr(proc, "pid", -1),
                        returncode=returncode,
                        started_at=meta.get("started_at", ""),
                    )
                )
            return records

    def active_metadata(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            snapshot: Dict[str, Dict[str, Any]] = {}
            for run_id, meta in self._meta.items():
                if run_id in self._processes:
                    snapshot[run_id] = dict(meta)
            return snapshot

    def start(self, payload: StartRunRequest) -> RunInfo:
        if not self._script.exists():
            raise HTTPException(status_code=500, detail=f"Pipeline script not found at {self._script}")

        with self._lock:
            run_dir = Path(payload.run_dir) if payload.run_dir else RUNS_BASE / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            run_dir = run_dir.resolve()
            if not run_dir.is_relative_to(self._root):
                raise HTTPException(status_code=400, detail="run_dir must be inside the repository directory.")
            run_dir.mkdir(parents=True, exist_ok=True)

            run_id = run_dir.name
            if run_id in self._processes:
                raise HTTPException(status_code=409, detail=f"Run '{run_id}' is already active.")

            cmd = [self._interpreter, str(self._script), "--run-dir", str(run_dir)]
            if payload.config:
                cmd.extend(["--config", payload.config])
            if payload.max_pages is not None:
                cmd.extend(["--max-pages", str(payload.max_pages)])
            if payload.sleep_seconds:
                cmd.extend(["--sleep-seconds", str(payload.sleep_seconds)])

            try:
                proc = subprocess.Popen(cmd, cwd=self._root)
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Failed to start pipeline: {exc}") from exc

            self._processes[run_id] = proc
            self._meta[run_id] = {
                "run_dir": run_dir,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }

            return RunInfo(
                run_id=run_id,
                run_dir=str(run_dir),
                pid=proc.pid,
                returncode=None,
                started_at=self._meta[run_id]["started_at"],
            )

    def stop(self, run_id: str) -> RunInfo:
        with self._lock:
            proc = self._processes.get(run_id)
            meta = self._meta.get(run_id, {})
            if proc is None:
                raise HTTPException(status_code=404, detail=f"Run '{run_id}' is not active.")
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            returncode = proc.poll()
            self._processes.pop(run_id, None)
            return RunInfo(
                run_id=run_id,
                run_dir=str(meta.get("run_dir", "")),
                pid=getattr(proc, "pid", -1),
                returncode=returncode,
                started_at=meta.get("started_at", ""),
            )


CONTROLLER = RunController(root=ROOT, script=PIPELINE_SCRIPT, interpreter=sys.executable)


@app.get("/maintenance/blocklist/status")
def blocklist_status() -> JSONResponse:
    return JSONResponse(
        {
            "last_run": BLOCKLIST_STATUS.get("last_run"),
            "last_error": BLOCKLIST_STATUS.get("last_error"),
            "host_count": BLOCKLIST_STATUS.get("host_count", 0),
            "refresh_seconds": BLOCKLIST_REFRESH_SECONDS,
            "auto_refresh": BLOCKLIST_AUTO_REFRESH,
        }
    )


@app.post("/maintenance/blocklist/refresh")
def trigger_blocklist_refresh() -> JSONResponse:
    try:
        result = refresh_blocklist_from_source()
    except Exception as exc:  # pragma: no cover - network failure
        raise HTTPException(status_code=502, detail=f"Blocklist refresh failed: {exc}") from exc
    return JSONResponse({"status": "ok", **result})


@app.get("/runs")
def list_runs() -> JSONResponse:
    return JSONResponse({"runs": collect_runs()})


@app.get("/runs/active")
def list_active_runs() -> JSONResponse:
    return JSONResponse({"active_runs": [item.dict() for item in CONTROLLER.list_active()]})


@app.post("/runs/start")
def start_run(payload: StartRunRequest = Body(default_factory=StartRunRequest)) -> JSONResponse:
    info = CONTROLLER.start(payload)
    return JSONResponse({"run": info.dict()})


@app.post("/runs/{run_id}/stop")
def stop_run(run_id: str) -> JSONResponse:
    info = CONTROLLER.stop(run_id)
    return JSONResponse({"run": info.dict()})


@app.get("/runs/{run_id}")
def fetch_run(run_id: str) -> JSONResponse:
    return JSONResponse(get_run(run_id))


@app.get("/runs/{run_id}/telemetry")
def fetch_telemetry(
    run_id: str,
    limit: int = Query(DEFAULT_TELEMETRY_LIMIT, ge=1, le=2000),
) -> JSONResponse:
    events = read_telemetry_tail(run_id, limit=limit)
    return JSONResponse({"run_id": run_id, "events": events})


@app.get("/")
def root_redirect() -> FileResponse:
    index_path = UI_DIR / "index.html"
    return FileResponse(index_path)


__all__ = [
    "app",
    "collect_runs",
    "get_run",
    "read_telemetry_tail",
    "RunController",
    "StartRunRequest",
    "CONTROLLER",
]
