"""Deterministic numeric forecasting. No LLM is involved here, ever.

Every function is PURE in (keyword inputs, seed): the same arguments always
produce byte-identical output, so an audit replay reproduces a forecast exactly.
The ensemble spread that yields p10/p90 comes from `random.Random(seed)`, which
is seeded per call and never touches global RNG state.

Each model declares an OPERATING ENVELOPE. Outside it the model does one of two
things and says which, in machine-readable form:

  * DOWNGRADE  - the input is just past a bound (<= `soft_margin` of the range).
                 The input is clamped to the boundary, the interval is widened,
                 `in_envelope=False` and `envelope_note` explains it.
  * ABSTAIN    - the input is far outside the envelope, or missing entirely.
                 `abstained=True`, median/p10/p90 are None. Nothing is
                 extrapolated and no number is invented.

An agent narrating this must not fill in a missing value. `None` means unknown.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

FLOOD_MODEL_VERSION = "flood-depth-curve-1.2.0"
TRAFFIC_MODEL_VERSION = "traffic-degradation-1.1.0"

# ensemble members. 200 is enough for stable 10/90 tails and costs microseconds.
MEMBERS = 200


# ------------------------------------------------------------------ envelope
@dataclass(frozen=True)
class Envelope:
    """The calibrated region a model is allowed to speak inside."""

    name: str
    bounds: Mapping[str, tuple[float, float]]
    max_evidence_age_s: int = 3600
    soft_margin: float = 0.25  # fraction of the range treated as "just outside"

    def check(
        self, values: Mapping[str, float | None], evidence_age_s: int = 0
    ) -> tuple[str, dict[str, float], str | None]:
        """Return (status, clamped_values, note). status: 'in'|'soft'|'abstain'."""
        missing = sorted(k for k, v in values.items() if v is None)
        if missing:
            return "abstain", {}, (
                f"required input(s) missing from the evidence snapshot: "
                f"{', '.join(missing)} - no value was assumed or filled in"
            )

        clamped = {k: float(v) for k, v in values.items()}  # type: ignore[arg-type]
        notes: list[str] = []
        status = "in"
        for key, (lo, hi) in self.bounds.items():
            if key not in clamped:
                continue
            v = clamped[key]
            if lo <= v <= hi:
                continue
            span = (hi - lo) or 1.0
            over = ((lo - v) if v < lo else (v - hi)) / span
            edge = lo if v < lo else hi
            if over > self.soft_margin:
                return "abstain", clamped, (
                    f"{key}={v:g} is {over:.0%} of the calibrated range beyond "
                    f"[{lo:g}, {hi:g}] - outside the {self.name} operating "
                    f"envelope, so this model abstains rather than extrapolate"
                )
            status = "soft"
            clamped[key] = edge
            notes.append(
                f"{key}={v:g} is outside [{lo:g}, {hi:g}] by {over:.0%} of range; "
                f"clamped to {edge:g} and the interval widened"
            )
        if evidence_age_s > self.max_evidence_age_s:
            status = "soft"
            notes.append(
                f"input evidence is {evidence_age_s}s old, beyond the "
                f"{self.max_evidence_age_s}s calibration window; interval widened"
            )
        return status, clamped, "; ".join(notes) or None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "bounds": {k: list(v) for k, v in sorted(self.bounds.items())},
            "max_evidence_age_s": self.max_evidence_age_s,
            "soft_margin": self.soft_margin,
        }


FLOOD_ENVELOPE = Envelope(
    "flood-depth",
    {
        "rain_mm_hr": (0.0, 120.0),
        "water_level_m": (0.0, 8.0),
        "horizon_min": (5.0, 240.0),
    },
)

TRAFFIC_ENVELOPE = Envelope(
    "traffic-degradation",
    {
        "baseline_min": (1.0, 240.0),
        "flood_depth_m": (0.0, 1.0),
        "closed_lane_frac": (0.0, 0.9),
        "horizon_min": (5.0, 240.0),
    },
)


# -------------------------------------------------------------------- result
@dataclass(frozen=True)
class ForecastResult:
    model_version: str
    quantity: str
    unit: str
    horizon_min: int
    median: float | None
    p10: float | None
    p90: float | None
    in_envelope: bool
    envelope_note: str | None
    abstained: bool
    seed: int
    series: tuple[dict[str, float], ...] = ()
    inputs: Mapping[str, Any] = field(default_factory=dict)
    envelope: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Stable ordering so two replays hash identically."""
        return {
            "model_version": self.model_version,
            "quantity": self.quantity,
            "unit": self.unit,
            "horizon_min": self.horizon_min,
            "median": self.median,
            "p10": self.p10,
            "p90": self.p90,
            "in_envelope": self.in_envelope,
            "envelope_note": self.envelope_note,
            "abstained": self.abstained,
            "seed": self.seed,
            "series": [dict(s) for s in self.series],
            "inputs": dict(sorted(self.inputs.items())),
            "envelope": dict(self.envelope),
        }


def _abstain(
    model_version: str, quantity: str, unit: str, horizon_min: int,
    note: str, seed: int, inputs: Mapping[str, Any], envelope: Envelope,
) -> ForecastResult:
    return ForecastResult(
        model_version=model_version, quantity=quantity, unit=unit,
        horizon_min=int(horizon_min), median=None, p10=None, p90=None,
        in_envelope=False, envelope_note=note, abstained=True, seed=seed,
        series=(), inputs=dict(inputs), envelope=envelope.to_dict(),
    )


# ----------------------------------------------------------------- numerics
def _q(sorted_vals: Sequence[float], q: float) -> float:
    """Linear-interpolated quantile. `sorted_vals` must already be sorted."""
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def _steps(horizon_min: float) -> tuple[int, ...]:
    step = 10 if horizon_min > 30 else 5
    pts = list(range(step, int(horizon_min) + 1, step))
    if not pts or pts[-1] != int(horizon_min):
        pts.append(int(horizon_min))
    return tuple(pts)


def _widen(median: float, p10: float, p90: float, factor: float) -> tuple[float, float]:
    """Widen an interval about its median without moving the median."""
    return median - (median - p10) * factor, median + (p90 - median) * factor


# ------------------------------------------------------------- flood model
def _level_at(
    level_m: float, rain_mm_hr: float, drain_mm_hr: float,
    runoff_coeff: float, catchment_gain: float, t_min: float,
) -> float:
    """Absolute water level at the gauge after `t_min`.

    Rain above the drainage capacity becomes runoff and accumulates over the
    catchment (`catchment_gain` is the urban concentration factor: paved area
    delivering into the measured section). Rain below capacity drains away, but
    more slowly than it arrived - standing water leaves at ~35% of the nominal
    rate. Level is floored at zero.

    ponytail: single-reservoir curve, no routing between reaches. It is tuned by
    `catchment_gain` / `drain_capacity_mm_hr`, which is what a real deployment
    calibrates per section. Upgrade path: per-reach routing if one gauge stops
    representing the section.
    """
    if rain_mm_hr > drain_mm_hr:
        net_mm_hr = (rain_mm_hr - drain_mm_hr) * runoff_coeff
    else:
        net_mm_hr = (rain_mm_hr - drain_mm_hr) * 0.35
    rise_m = net_mm_hr * catchment_gain * (t_min / 60.0) / 1000.0
    return max(0.0, level_m + rise_m)


def flood_depth(
    *,
    rain_mm_hr: float | None,
    water_level_m: float | None,
    horizon_min: int = 60,
    flood_threshold_m: float = 3.5,
    drain_capacity_mm_hr: float = 12.0,
    runoff_coeff: float = 0.85,
    catchment_gain: float = 8.0,
    evidence_age_s: int = 0,
    seed: int = 0,
    members: int = MEMBERS,
) -> ForecastResult:
    """Flood depth over the affected surface, from a rainfall / water-level curve.

    The gauge reports an absolute level; the section starts flooding at
    `flood_threshold_m`, so the forecast quantity is the depth ABOVE that
    threshold - which is what the traffic model and any field crew care about.
    Each series point also carries the absolute `level` behind it.

    `rain_mm_hr` or `water_level_m` of None means the sensor value is missing.
    The model abstains - it never substitutes a default.
    """
    inputs = {
        "rain_mm_hr": rain_mm_hr, "water_level_m": water_level_m,
        "horizon_min": horizon_min, "flood_threshold_m": flood_threshold_m,
        "drain_capacity_mm_hr": drain_capacity_mm_hr,
        "runoff_coeff": runoff_coeff, "catchment_gain": catchment_gain,
        "evidence_age_s": evidence_age_s,
    }
    status, clamped, note = FLOOD_ENVELOPE.check(
        {"rain_mm_hr": rain_mm_hr, "water_level_m": water_level_m,
         "horizon_min": float(horizon_min)},
        evidence_age_s,
    )
    if status == "abstain":
        return _abstain(FLOOD_MODEL_VERSION, "flood_depth", "m", horizon_min,
                        note or "outside operating envelope", seed, inputs,
                        FLOOD_ENVELOPE)

    rain = clamped["rain_mm_hr"]
    level = clamped["water_level_m"]
    horizon = int(clamped["horizon_min"])
    steps = _steps(horizon)

    rng = random.Random(seed)
    ens: list[list[float]] = [[] for _ in steps]
    levels: list[list[float]] = [[] for _ in steps]
    for _ in range(members):
        r = rain * max(0.0, rng.gauss(1.0, 0.18))          # gauge/radar spread
        d = drain_capacity_mm_hr * max(0.1, rng.gauss(1.0, 0.25))  # blockage
        c = min(1.0, max(0.1, runoff_coeff * rng.gauss(1.0, 0.10)))
        l0 = max(0.0, level + rng.gauss(0.0, 0.03))        # gauge accuracy
        for i, t in enumerate(steps):
            lvl = _level_at(l0, r, d, c, catchment_gain, t)
            levels[i].append(lvl)
            ens[i].append(max(0.0, lvl - flood_threshold_m))

    widen = 2.0 if status == "soft" else 1.0
    series: list[dict[str, float]] = []
    for i, t in enumerate(steps):
        vals = sorted(ens[i])
        med, p10, p90 = _q(vals, 0.5), _q(vals, 0.10), _q(vals, 0.90)
        if widen != 1.0:
            p10, p90 = _widen(med, p10, p90, widen)
        series.append({"t_min": t, "median": round(med, 4),
                       "p10": round(max(0.0, p10), 4), "p90": round(p90, 4),
                       "level": round(_q(sorted(levels[i]), 0.5), 4)})

    last = series[-1]
    return ForecastResult(
        model_version=FLOOD_MODEL_VERSION, quantity="flood_depth", unit="m",
        horizon_min=horizon, median=last["median"], p10=last["p10"], p90=last["p90"],
        in_envelope=status == "in", envelope_note=note, abstained=False, seed=seed,
        series=tuple(series), inputs=inputs, envelope=FLOOD_ENVELOPE.to_dict(),
    )


# ----------------------------------------------------------- traffic model
# Standing water impedes traffic from ~5cm; at 30cm a road is impassable for
# ordinary vehicles. Lane closure feeds a queueing term that blows up as the
# remaining capacity approaches zero.
DEPTH_IMPEDE_START_M = 0.05
DEPTH_IMPASSABLE_M = 0.30
LANE_WEIGHT = 2.2
DEPTH_WEIGHT = 6.0
MAX_FACTOR = 8.0


def _delay_factor(depth_m: float, closed_lane_frac: float) -> tuple[float, bool]:
    span = DEPTH_IMPASSABLE_M - DEPTH_IMPEDE_START_M
    imp = min(1.0, max(0.0, (depth_m - DEPTH_IMPEDE_START_M) / span))
    open_frac = max(0.1, 1.0 - closed_lane_frac)
    queue = closed_lane_frac / open_frac
    factor = 1.0 + LANE_WEIGHT * queue + DEPTH_WEIGHT * imp
    impassable = depth_m >= DEPTH_IMPASSABLE_M
    return min(factor, MAX_FACTOR), impassable


def travel_time(
    *,
    baseline_min: float | None,
    flood_depth_m: float | None,
    closed_lane_frac: float = 0.0,
    horizon_min: int = 60,
    depth_series: Sequence[Mapping[str, float]] | None = None,
    evidence_age_s: int = 0,
    seed: int = 0,
    members: int = MEMBERS,
) -> ForecastResult:
    """Travel-time degradation on a route, in minutes, with p10-p90 interval.

    `depth_series` (the flood model's own series) chains the two forecasts so
    the traffic curve grows with the water. Without it the depth is held flat.
    A missing baseline or depth makes the model abstain.
    """
    inputs = {
        "baseline_min": baseline_min, "flood_depth_m": flood_depth_m,
        "closed_lane_frac": closed_lane_frac, "horizon_min": horizon_min,
        "chained_to_flood_series": bool(depth_series), "evidence_age_s": evidence_age_s,
    }
    status, clamped, note = TRAFFIC_ENVELOPE.check(
        {"baseline_min": baseline_min, "flood_depth_m": flood_depth_m,
         "closed_lane_frac": closed_lane_frac, "horizon_min": float(horizon_min)},
        evidence_age_s,
    )
    if status == "abstain":
        return _abstain(TRAFFIC_MODEL_VERSION, "travel_time", "min", horizon_min,
                        note or "outside operating envelope", seed, inputs,
                        TRAFFIC_ENVELOPE)

    base = clamped["baseline_min"]
    depth0 = clamped["flood_depth_m"]
    lanes = clamped["closed_lane_frac"]
    horizon = int(clamped["horizon_min"])
    by_t = {int(p["t_min"]): float(p["median"]) for p in (depth_series or ())}
    steps = tuple(sorted(by_t)) if by_t else _steps(horizon)

    rng = random.Random(seed)
    ens: list[list[float]] = [[] for _ in steps]
    impassable_at: int | None = None
    for _ in range(members):
        b = base * max(0.1, rng.gauss(1.0, 0.08))
        dscale = max(0.0, rng.gauss(1.0, 0.15))
        lfrac = min(0.95, max(0.0, lanes * rng.gauss(1.0, 0.10)))
        for i, t in enumerate(steps):
            d = by_t.get(t, depth0) * dscale
            factor, _ = _delay_factor(d, lfrac)
            ens[i].append(b * factor)

    widen = 2.0 if status == "soft" else 1.0
    series: list[dict[str, float]] = []
    for i, t in enumerate(steps):
        vals = sorted(ens[i])
        med, p10, p90 = _q(vals, 0.5), _q(vals, 0.10), _q(vals, 0.90)
        if widen != 1.0:
            p10, p90 = _widen(med, p10, p90, widen)
        series.append({"t_min": t, "median": round(med, 3),
                       "p10": round(max(0.0, p10), 3), "p90": round(p90, 3)})
        if impassable_at is None and _delay_factor(by_t.get(t, depth0), lanes)[1]:
            impassable_at = t

    last = series[-1]
    inputs["impassable_at_min"] = impassable_at
    inputs["baseline_used_min"] = base
    return ForecastResult(
        model_version=TRAFFIC_MODEL_VERSION, quantity="travel_time", unit="min",
        horizon_min=horizon, median=last["median"], p10=last["p10"], p90=last["p90"],
        in_envelope=status == "in", envelope_note=note, abstained=False, seed=seed,
        series=tuple(series), inputs=inputs, envelope=TRAFFIC_ENVELOPE.to_dict(),
    )


if __name__ == "__main__":  # runnable self-check
    a = flood_depth(rain_mm_hr=45.0, water_level_m=3.4, horizon_min=90, seed=7)
    b = flood_depth(rain_mm_hr=45.0, water_level_m=3.4, horizon_min=90, seed=7)
    assert a.to_dict() == b.to_dict(), "same seed must replay exactly"
    assert a.p10 < a.median < a.p90 and a.in_envelope
    assert flood_depth(rain_mm_hr=None, water_level_m=3.4).abstained
    assert flood_depth(rain_mm_hr=900.0, water_level_m=3.4).abstained
    soft = flood_depth(rain_mm_hr=140.0, water_level_m=3.4)  # 17% past 120
    assert not soft.abstained and not soft.in_envelope and soft.envelope_note
    t = travel_time(baseline_min=12.0, flood_depth_m=a.median,
                    closed_lane_frac=0.5, depth_series=a.series, seed=7)
    assert t.median > 12.0 and not t.abstained
    print("forecast self-check ok:", a.median, "m ->", t.median, "min")
