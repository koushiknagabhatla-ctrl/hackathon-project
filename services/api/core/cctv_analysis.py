"""CCTV incident analysis — detect collisions from a camera feed.

The detection chain is object detection -> tracking -> kinematics, which is the
approach the traffic-incident literature settled on and the one that survives
contact with a real street. The previous implementation scored frames on colour
histograms ("orange pixels means fire"), which fires on a sunset, a red bus and
a saree, and is not something anyone should page a crew on.

What this module does:

  1. Runs a YOLO detector on sampled frames and keeps only road users
     (car, truck, bus, motorcycle, bicycle, person).
  2. Tracks each one across frames with IoU association, so a box has a
     history and therefore a velocity.
  3. Looks for the kinematic signatures of a collision:
       * two road users overlap and both stop moving
       * a moving vehicle decelerates abruptly to a halt
       * a vehicle that was moving stays stopped in the scene
       * a person appears next to stopped vehicles after such an event
  4. Emits a signal with a calibrated confidence and the evidence that led to it.

What it deliberately does NOT do:

  * It does not decide an accident happened. One camera is one witness. The
    signal it emits enters `accident_detector` and needs corroboration from an
    independent source before anything is dispatched to the public.
  * It does not identify people or read number plates. Nothing here performs
    biometric identification, and the frames it keeps are evidence snapshots
    of an event, not a surveillance record of who was present.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

log = logging.getLogger("auralis.cctv")

# COCO classes that are road users. Everything else in the frame is scenery.
VEHICLE_CLASSES = {"car", "truck", "bus", "motorcycle", "bicycle"}
PERSON_CLASS = "person"
ROAD_USER_CLASSES = VEHICLE_CLASSES | {PERSON_CLASS}

# --- tuning ---------------------------------------------------------------
# These are the knobs a real deployment needs: a camera 6 m above a junction
# and one 20 m above a highway produce very different pixel velocities, so
# every threshold here is per-camera overridable rather than a constant.
DEFAULTS: dict[str, float] = {
    "min_confidence": 0.35,      # detector score below this is not a road user
    "iou_match": 0.25,           # association threshold between frames
    "track_ttl_s": 2.5,          # keep a lost track this long before dropping
    "overlap_iou": 0.18,         # two boxes this deep into each other "touch"
    "stop_speed_px_s": 14.0,     # below this a track counts as stopped
    "moving_speed_px_s": 45.0,   # above this it was genuinely moving
    "decel_ratio": 0.55,         # speed must fall by this fraction to be abrupt
    "decel_window_s": 1.6,       # ...within this long
    "stopped_dwell_s": 4.0,      # a stopped-after-moving vehicle must persist
    "min_track_age_s": 0.8,      # ignore tracks too young to have a velocity
}


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """Intersection over union of two xyxy boxes."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / ua if ua > 0 else 0.0


def _centre(box: tuple[float, float, float, float]) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


@dataclass
class Track:
    """One road user followed across frames."""
    track_id: int
    label: str
    box: tuple[float, float, float, float]
    first_seen: float
    last_seen: float
    history: list[tuple[float, float, float]] = field(default_factory=list)  # (t, cx, cy)
    peak_speed: float = 0.0
    stopped_since: float | None = None
    flagged: set[str] = field(default_factory=set)

    @property
    def age_s(self) -> float:
        return self.last_seen - self.first_seen

    def speed_px_s(self, window_s: float = 0.8) -> float:
        """Speed over the most recent window, in pixels per second."""
        if len(self.history) < 2:
            return 0.0
        t_end, x_end, y_end = self.history[-1]
        for t, x, y in reversed(self.history[:-1]):
            if t_end - t >= window_s:
                dt = t_end - t
                return math.hypot(x_end - x, y_end - y) / dt if dt > 0 else 0.0
        t0, x0, y0 = self.history[0]
        dt = t_end - t0
        return math.hypot(x_end - x0, y_end - y0) / dt if dt > 0 else 0.0

    def speed_at(self, seconds_ago: float, window_s: float = 0.8) -> float:
        """Speed as it was `seconds_ago`, for comparing before/after."""
        if len(self.history) < 3:
            return 0.0
        t_now = self.history[-1][0]
        target = t_now - seconds_ago
        pts = [p for p in self.history if p[0] <= target]
        if len(pts) < 2:
            return 0.0
        t_end, x_end, y_end = pts[-1]
        for t, x, y in reversed(pts[:-1]):
            if t_end - t >= window_s:
                dt = t_end - t
                return math.hypot(x_end - x, y_end - y) / dt if dt > 0 else 0.0
        return 0.0


@dataclass
class IncidentSignal:
    """A candidate incident observed on one camera."""
    kind: str                 # collision_overlap | abrupt_stop | stalled_vehicle | pedestrian_involved
    confidence: float         # calibrated, and deliberately never 1.0
    observed_at: float
    track_ids: list[int]
    labels: list[str]
    box: tuple[float, float, float, float]
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "confidence": round(self.confidence, 3),
            "observed_at": self.observed_at,
            "track_ids": self.track_ids,
            "labels": self.labels,
            "box": [round(v, 1) for v in self.box],
            "detail": self.detail,
        }


class CollisionAnalyzer:
    """Stateful analyser for a single camera.

    Feed it detections frame by frame with `update()`. It returns any signals
    raised by that frame. Confidence is capped below certainty on purpose:
    a single camera can suggest a collision, never establish one.
    """

    def __init__(self, tuning: dict[str, float] | None = None) -> None:
        self.cfg = {**DEFAULTS, **(tuning or {})}
        self.tracks: dict[int, Track] = {}
        self._next_id = 1
        self._recent: dict[str, float] = {}   # signal kind -> last emit time

    # -- association -------------------------------------------------------
    def _associate(self, detections: list[dict[str, Any]], now: float) -> None:
        unmatched = list(range(len(detections)))
        for tid, tr in list(self.tracks.items()):
            best_i, best_iou = -1, 0.0
            for i in unmatched:
                d = detections[i]
                if d["label"] != tr.label:
                    continue
                s = iou(tr.box, d["box"])
                if s > best_iou:
                    best_i, best_iou = i, s
            if best_i >= 0 and best_iou >= self.cfg["iou_match"]:
                d = detections[best_i]
                unmatched.remove(best_i)
                tr.box = d["box"]
                tr.last_seen = now
                cx, cy = _centre(d["box"])
                tr.history.append((now, cx, cy))
                if len(tr.history) > 90:
                    tr.history = tr.history[-90:]
                sp = tr.speed_px_s()
                tr.peak_speed = max(tr.peak_speed, sp)
                if sp < self.cfg["stop_speed_px_s"]:
                    tr.stopped_since = tr.stopped_since or now
                else:
                    tr.stopped_since = None

        for i in unmatched:
            d = detections[i]
            cx, cy = _centre(d["box"])
            tid = self._next_id
            self._next_id += 1
            self.tracks[tid] = Track(
                track_id=tid, label=d["label"], box=d["box"],
                first_seen=now, last_seen=now, history=[(now, cx, cy)],
            )

        ttl = self.cfg["track_ttl_s"]
        for tid, tr in list(self.tracks.items()):
            if now - tr.last_seen > ttl:
                del self.tracks[tid]

    # -- rules -------------------------------------------------------------
    def _cooled(self, kind: str, now: float, cooldown_s: float = 8.0) -> bool:
        last = self._recent.get(kind, 0.0)
        if now - last < cooldown_s:
            return False
        self._recent[kind] = now
        return True

    def update(self, detections: list[dict[str, Any]], now: float | None = None) -> list[IncidentSignal]:
        """Feed one frame's detections. Returns signals raised by this frame.

        `detections` items: {"label": str, "confidence": float, "box": (x1,y1,x2,y2)}
        """
        now = time.time() if now is None else now
        dets = [
            d for d in detections
            if d.get("label") in ROAD_USER_CLASSES
            and float(d.get("confidence", 0)) >= self.cfg["min_confidence"]
        ]
        self._associate(dets, now)
        signals: list[IncidentSignal] = []

        vehicles = [t for t in self.tracks.values()
                    if t.label in VEHICLE_CLASSES and t.age_s >= self.cfg["min_track_age_s"]]

        # 1. Two road users overlap and both have stopped. The strongest single
        #    camera signature of a collision.
        for i, a in enumerate(vehicles):
            for b in vehicles[i + 1:]:
                ov = iou(a.box, b.box)
                if ov < self.cfg["overlap_iou"]:
                    continue
                a_stopped = a.speed_px_s() < self.cfg["stop_speed_px_s"]
                b_stopped = b.speed_px_s() < self.cfg["stop_speed_px_s"]
                was_moving = (a.peak_speed > self.cfg["moving_speed_px_s"]
                              or b.peak_speed > self.cfg["moving_speed_px_s"])
                if a_stopped and b_stopped and was_moving:
                    key = f"collision_overlap:{min(a.track_id, b.track_id)}:{max(a.track_id, b.track_id)}"
                    if key in a.flagged:
                        continue
                    a.flagged.add(key)
                    b.flagged.add(key)
                    if not self._cooled("collision_overlap", now):
                        continue
                    conf = 0.62 + min(0.16, ov)      # overlap depth adds a little
                    x1 = min(a.box[0], b.box[0]); y1 = min(a.box[1], b.box[1])
                    x2 = max(a.box[2], b.box[2]); y2 = max(a.box[3], b.box[3])
                    signals.append(IncidentSignal(
                        kind="collision_overlap", confidence=min(conf, 0.78),
                        observed_at=now, track_ids=[a.track_id, b.track_id],
                        labels=[a.label, b.label], box=(x1, y1, x2, y2),
                        detail=(f"{a.label} and {b.label} overlapping at IoU {ov:.2f}; "
                                f"both stationary after moving at up to "
                                f"{max(a.peak_speed, b.peak_speed):.0f} px/s"),
                    ))

        # 2. Abrupt deceleration to a halt.
        for t in vehicles:
            if "abrupt_stop" in t.flagged:
                continue
            before = t.speed_at(self.cfg["decel_window_s"])
            after = t.speed_px_s()
            if (before > self.cfg["moving_speed_px_s"]
                    and after < self.cfg["stop_speed_px_s"]
                    and before > 0
                    and (before - after) / before >= self.cfg["decel_ratio"]):
                t.flagged.add("abrupt_stop")
                if not self._cooled("abrupt_stop", now):
                    continue
                signals.append(IncidentSignal(
                    kind="abrupt_stop", confidence=0.45,
                    observed_at=now, track_ids=[t.track_id], labels=[t.label], box=t.box,
                    detail=(f"{t.label} decelerated from {before:.0f} to {after:.0f} px/s "
                            f"within {self.cfg['decel_window_s']:.1f}s"),
                ))

        # 3. A vehicle that was moving is now parked in the scene.
        for t in vehicles:
            if "stalled_vehicle" in t.flagged or t.stopped_since is None:
                continue
            if (t.peak_speed > self.cfg["moving_speed_px_s"]
                    and now - t.stopped_since >= self.cfg["stopped_dwell_s"]):
                t.flagged.add("stalled_vehicle")
                if not self._cooled("stalled_vehicle", now, cooldown_s=20.0):
                    continue
                signals.append(IncidentSignal(
                    kind="stalled_vehicle", confidence=0.35,
                    observed_at=now, track_ids=[t.track_id], labels=[t.label], box=t.box,
                    detail=(f"{t.label} stationary for "
                            f"{now - t.stopped_since:.0f}s after moving"),
                ))

        # 4. A person beside stopped vehicles right after an overlap event.
        people = [t for t in self.tracks.values() if t.label == PERSON_CLASS]
        if people and any(s.kind == "collision_overlap" for s in signals):
            near = [p for p in people
                    if any(iou(p.box, v.box) > 0.02 for v in vehicles)]
            if near and self._cooled("pedestrian_involved", now):
                p = near[0]
                signals.append(IncidentSignal(
                    kind="pedestrian_involved", confidence=0.55,
                    observed_at=now, track_ids=[p.track_id], labels=["person"], box=p.box,
                    detail=f"{len(near)} person(s) adjacent to the involved vehicles",
                ))

        return signals

    def snapshot(self) -> dict[str, Any]:
        """Current scene state, for a health view."""
        return {
            "tracks": len(self.tracks),
            "vehicles": sum(1 for t in self.tracks.values() if t.label in VEHICLE_CLASSES),
            "people": sum(1 for t in self.tracks.values() if t.label == PERSON_CLASS),
        }


def yolo_to_detections(result: Any, names: dict[int, str]) -> list[dict[str, Any]]:
    """Convert one ultralytics Result into this module's detection dicts."""
    out: list[dict[str, Any]] = []
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return out
    for b in boxes:
        try:
            cls = int(b.cls[0])
            conf = float(b.conf[0])
            xyxy = [float(v) for v in b.xyxy[0]]
        except Exception:
            continue
        label = names.get(cls, str(cls))
        if label not in ROAD_USER_CLASSES:
            continue
        out.append({"label": label, "confidence": conf,
                    "box": (xyxy[0], xyxy[1], xyxy[2], xyxy[3])})
    return out
