"""CCTV stream worker — watch registered cameras and raise incident signals.

Pipeline per camera:

    RTSP/HTTP frame  ->  YOLO detection  ->  CollisionAnalyzer  ->  signal
                                                    |
                                         accident_detector (corroboration)
                                                    |
                                    public_alert (only once corroborated)

Two properties this module is built around:

**A camera is one witness.** A signal raised here is never enough to warn the
public. It is handed to `accident_detector`, which requires an independent
second source (traffic collapse, a citizen report, another camera) before the
status reaches CORROBORATED and anything is dispatched. A single detector
firing produces a SUSPECTED incident for an operator to look at, and nothing
else. That is the difference between a system that helps and one that cries
wolf until it is switched off.

**A camera must be authorised.** `camera.authorized_by` is NOT NULL and the
worker skips any row without it. Pointing an analyser at a video feed is a
decision someone has to own, and this makes that person a matter of record
rather than a matter of configuration.

The worker samples frames rather than decoding every one: on CPU, YOLO11n runs
at roughly 3-5 fps, and a collision is a multi-second event, so sampling at
2-4 fps loses nothing that matters and leaves the box responsive.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger("auralis.cctv.worker")

# Model choice. yolo11n is the small one and the only sane default on CPU;
# a deployment with a GPU should set AURALIS_CCTV_MODEL=yolo11s.pt or larger.
DEFAULT_MODEL = os.environ.get("AURALIS_CCTV_MODEL", "yolo11n.pt")
DEFAULT_SAMPLE_FPS = float(os.environ.get("AURALIS_CCTV_SAMPLE_FPS", "3"))

_model = None
_model_lock = threading.Lock()
_worker_thread: threading.Thread | None = None
_stop_flag = threading.Event()
_last_status: dict[str, Any] = {}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def get_model():
    """Load the detector once, lazily. Returns None when unavailable."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        try:
            from ultralytics import YOLO

            t0 = time.time()
            _model = YOLO(DEFAULT_MODEL)
            log.info("CCTV detector %s loaded in %.1fs", DEFAULT_MODEL, time.time() - t0)
        except Exception as exc:
            log.error("CCTV detector unavailable: %s", exc)
            _model = None
    return _model


def model_status() -> dict[str, Any]:
    try:
        import ultralytics  # noqa: F401
        installed = True
    except Exception:
        installed = False
    return {
        "detector_installed": installed,
        "model": DEFAULT_MODEL,
        "loaded": _model is not None,
        "sample_fps": DEFAULT_SAMPLE_FPS,
        "worker_running": bool(_worker_thread and _worker_thread.is_alive()),
        "last_cycle": _last_status,
    }


# ─────────────────────────────────────────────────────────── camera registry

@dataclass
class Camera:
    id: str
    tenant_id: str
    name: str
    stream_url: str
    lat: float
    lon: float
    road_segment: str
    enabled: bool
    authorized_by: str
    sample_fps: float
    tuning: dict[str, float]

    @staticmethod
    def from_row(r: dict[str, Any]) -> "Camera":
        try:
            tuning = json.loads(r.get("tuning_json") or "{}")
        except Exception:
            tuning = {}
        return Camera(
            id=r["id"], tenant_id=r["tenant_id"], name=r["name"],
            stream_url=r["stream_url"], lat=r["lat"], lon=r["lon"],
            road_segment=r.get("road_segment") or "",
            enabled=bool(r.get("enabled")),
            authorized_by=r.get("authorized_by") or "",
            sample_fps=float(r.get("sample_fps") or DEFAULT_SAMPLE_FPS),
            tuning=tuning,
        )


def list_cameras(tenant_id: str | None = None, only_enabled: bool = False) -> list[Camera]:
    from services.api.core import db

    q = "SELECT * FROM camera"
    args: list[Any] = []
    where = []
    if tenant_id:
        where.append("tenant_id = ?")
        args.append(tenant_id)
    if only_enabled:
        where.append("enabled = 1")
    if where:
        q += " WHERE " + " AND ".join(where)
    with db.tx() as c:
        try:
            rows = c.execute(q, tuple(args)).fetchall()
        except Exception:
            return []
    return [Camera.from_row(dict(r)) for r in rows]


def register_camera(
    *, name: str, stream_url: str, lat: float, lon: float,
    authorized_by: str, tenant_id: str = "ten_vijayawada",
    road_segment: str = "", sample_fps: float | None = None,
    tuning: dict[str, float] | None = None, enabled: bool = True,
) -> dict[str, Any]:
    """Register a feed for analysis.

    `authorized_by` is required: monitoring a camera is somebody's decision and
    the record has to name them.
    """
    from services.api.core import db

    if not authorized_by.strip():
        return {"status": "error",
                "error": "authorized_by is required: a monitored camera must name who authorised it"}

    cam_id = f"cam_{uuid.uuid4().hex[:10]}"
    with db.tx() as c:
        c.execute(
            "INSERT INTO camera(id, tenant_id, name, stream_url, lat, lon, road_segment, "
            "enabled, authorized_by, sample_fps, tuning_json, registered_at, last_ok_at, "
            "last_error) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cam_id, tenant_id, name, stream_url, lat, lon, road_segment,
             1 if enabled else 0, authorized_by,
             float(sample_fps or DEFAULT_SAMPLE_FPS),
             json.dumps(tuning or {}), _now(), None, None),
        )
    return {"status": "ok", "camera_id": cam_id}


def _mark(cam_id: str, ok: bool, error: str | None) -> None:
    from services.api.core import db

    with db.tx() as c:
        if ok:
            c.execute("UPDATE camera SET last_ok_at = ?, last_error = NULL WHERE id = ?",
                      (_now(), cam_id))
        else:
            c.execute("UPDATE camera SET last_error = ? WHERE id = ?", ((error or "")[:400], cam_id))


# ──────────────────────────────────────────────────────────── stream analysis

def analyze_stream(
    cam: Camera,
    max_seconds: float = 20.0,
    max_frames: int = 60,
) -> dict[str, Any]:
    """Sample a camera for a bounded window and return the signals raised.

    Bounded on purpose: this runs inside a polling loop across many cameras,
    so no single feed may hold the worker.
    """
    import cv2

    from services.api.core.cctv_analysis import CollisionAnalyzer, yolo_to_detections

    model = get_model()
    if model is None:
        return {"status": "unavailable",
                "error": "ultralytics is not installed; run: pip install ultralytics",
                "camera_id": cam.id, "signals": []}

    cap = cv2.VideoCapture(cam.stream_url)
    if not cap.isOpened():
        _mark(cam.id, False, "stream could not be opened")
        return {"status": "error", "error": f"could not open stream for {cam.name}",
                "camera_id": cam.id, "signals": []}

    analyzer = CollisionAnalyzer(cam.tuning)
    # Sample by frame index, not by wall clock. A file decodes far faster than
    # real time, so a clock-based sampler races to the end of it and analyses
    # almost nothing; a stride works for both a file and a live feed.
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    if not (1.0 <= src_fps <= 120.0):
        src_fps = 25.0
    stride = max(1, int(round(src_fps / max(0.5, cam.sample_fps))))
    # Timestamps must advance with the video, or velocity is meaningless.
    frame_dt = 1.0 / src_fps

    started = time.time()
    read_idx = 0
    frames = 0
    signals: list[dict[str, Any]] = []
    last_frame = None
    names = getattr(model, "names", {}) or {}

    try:
        while frames < max_frames and (time.time() - started) < max_seconds:
            ok, frame = cap.read()
            if not ok:
                break
            read_idx += 1
            if (read_idx - 1) % stride:
                continue
            now = started + read_idx * frame_dt
            frames += 1
            last_frame = frame

            try:
                res = model.predict(frame, verbose=False, conf=0.35)[0]
            except Exception as exc:
                _mark(cam.id, False, f"inference failed: {exc}")
                break

            dets = yolo_to_detections(res, names)
            for sig in analyzer.update(dets, now=now):
                signals.append(sig.to_dict())
    finally:
        cap.release()

    _mark(cam.id, True, None)
    return {
        "status": "ok",
        "camera_id": cam.id,
        "camera_name": cam.name,
        "frames_analyzed": frames,
        "elapsed_s": round(time.time() - started, 2),
        "scene": analyzer.snapshot(),
        "signals": signals,
        "frame_available": last_frame is not None,
    }


def _signal_to_incident(cam: Camera, sig: dict[str, Any]) -> dict[str, Any] | None:
    """Hand one camera signal to the corroboration engine.

    Only the signatures that plausibly indicate a collision are escalated.
    A stalled vehicle is worth an operator's attention, not an emergency.
    """
    if sig["kind"] not in ("collision_overlap", "pedestrian_involved"):
        return None
    try:
        from services.api.core.accident_detector import process_emergency_signal

        return process_emergency_signal(
            signal_kind="cctv_collision",
            connector_id=f"conn_camera_{cam.id}",
            latitude=cam.lat,
            longitude=cam.lon,
            payload={
                "camera_id": cam.id,
                "camera_name": cam.name,
                "road_segment": cam.road_segment,
                "detector": DEFAULT_MODEL,
                "signal_kind": sig["kind"],
                "confidence": sig["confidence"],
                "labels": sig["labels"],
                "detail": sig["detail"],
                # Named so nothing downstream can mistake a detector output
                # for an eyewitness account.
                "evidence_class": "machine_inference",
            },
        )
    except Exception as exc:
        log.warning("could not escalate camera signal: %s", exc)
        return None


def poll_once(tenant_id: str | None = None, seconds_per_camera: float = 15.0) -> dict[str, Any]:
    """One pass over every enabled, authorised camera."""
    cams = [c for c in list_cameras(tenant_id, only_enabled=True) if c.authorized_by]
    started = time.time()
    out: list[dict[str, Any]] = []
    escalated = 0

    for cam in cams:
        res = analyze_stream(cam, max_seconds=seconds_per_camera)
        for sig in res.get("signals", []):
            inc = _signal_to_incident(cam, sig)
            if inc:
                escalated += 1
                sig["escalated_to"] = inc.get("incident_id") or inc.get("status")
        out.append(res)

    status = {
        "cameras_polled": len(cams),
        "signals": sum(len(r.get("signals", [])) for r in out),
        "escalated": escalated,
        "elapsed_s": round(time.time() - started, 2),
        "at": _now(),
        "results": out,
    }
    global _last_status
    _last_status = {k: v for k, v in status.items() if k != "results"}
    return status


def _loop(interval_s: float, tenant_id: str | None) -> None:
    while not _stop_flag.is_set():
        try:
            poll_once(tenant_id)
        except Exception:
            log.exception("CCTV poll cycle failed")
        _stop_flag.wait(interval_s)


def start_worker(interval_s: float = 60.0, tenant_id: str | None = None) -> dict[str, Any]:
    """Start the background polling loop, if there is anything to poll."""
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return {"status": "already_running"}
    cams = [c for c in list_cameras(tenant_id, only_enabled=True) if c.authorized_by]
    if not cams:
        return {"status": "idle",
                "reason": "no enabled, authorised camera is registered"}
    _stop_flag.clear()
    _worker_thread = threading.Thread(
        target=_loop, args=(interval_s, tenant_id), daemon=True, name="cctv-worker"
    )
    _worker_thread.start()
    return {"status": "started", "cameras": len(cams), "interval_s": interval_s}


def stop_worker() -> dict[str, Any]:
    _stop_flag.set()
    return {"status": "stopping"}
