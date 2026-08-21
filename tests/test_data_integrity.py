"""Data-integrity gates.

These are the tests that stop fabricated data reaching a user, and stop
fabricated data reaching the real world. They are release gates, not
suggestions. If one fails, the fix is the code, never the test.

Run: python -m pytest tests/test_data_integrity.py -q
"""

from __future__ import annotations

import importlib
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

WORLD_TABLES = [
    "asset", "asset_dependency", "incident", "evidence", "claim",
    "forecast", "plan", "action", "work_order",
    "emergency_contact", "registered_device",
]
CONFIG_TABLES = [
    "tenant", "principal", "connector", "policy_bundle",
    "tool_manifest", "model_version",
]


def _boot_and_count(mock_mode: str, tmp_db: Path) -> dict[str, int]:
    """Boot the API in a subprocess so MOCK_MODE is read fresh, then count."""
    script = (
        "import json;"
        "from fastapi.testclient import TestClient;"
        "from services.api.main import app;"
        "from services.api.core import db;"
        "c=TestClient(app);c.__enter__();"
        "conn=db.get_conn();"
        f"tabs={WORLD_TABLES + CONFIG_TABLES!r};"
        "out={};"
        "\nfor t in tabs:\n"
        "    try: out[t]=conn.execute('SELECT COUNT(*) c FROM '+t).fetchone()['c']\n"
        "    except Exception: out[t]=-1\n"
        "print('COUNTS='+json.dumps(out))"
    )
    env = {**os.environ, "MOCK_MODE": mock_mode, "AURALIS_DB": str(tmp_db)}
    res = subprocess.run(
        [sys.executable, "-c", script], cwd=REPO, env=env,
        capture_output=True, text=True, timeout=180,
    )
    line = next(
        (l for l in res.stdout.splitlines() if l.startswith("COUNTS=")), None
    )
    assert line, f"boot produced no counts.\nstdout:{res.stdout}\nstderr:{res.stderr}"
    import json as _json

    return _json.loads(line[len("COUNTS="):])


def test_no_fabricated_world_data_when_mock_mode_is_off(tmp_path):
    """THE gate. With MOCK_MODE off, not one row of invented world data."""
    counts = _boot_and_count("false", tmp_path / "off.db")

    for table in WORLD_TABLES:
        assert counts[table] in (0, -1), (
            f"{table} has {counts[table]} rows with MOCK_MODE=false. "
            "Fabricated world data must never load on the real path."
        )


def test_configuration_still_loads_when_mock_mode_is_off(tmp_path):
    """The gate must not break the platform: config is not world data."""
    counts = _boot_and_count("false", tmp_path / "cfg.db")

    for table in CONFIG_TABLES:
        assert counts[table] > 0, (
            f"{table} is empty with MOCK_MODE=false. Tenant, identities, "
            "policy bundle and tool manifests are configuration and must load."
        )


def test_mock_mode_on_actually_loads_the_demonstration_world(tmp_path):
    """If MOCK_MODE is on, the simulation must genuinely populate."""
    counts = _boot_and_count("true", tmp_path / "on.db")

    assert counts["incident"] > 0
    assert counts["evidence"] > 0
    assert counts["asset"] > 0


def test_no_dialable_phone_numbers_anywhere_in_source():
    """No source file may contain a dialable Indian mobile number.

    A simulated contact carrying a real-format number can reach a real person
    who has nothing to do with this system.
    """
    # +91 followed by a 10-digit number starting 6-9 is a dialable Indian mobile.
    dialable = re.compile(r"\+91[\s-]?[6-9]\d{9}")
    offenders: list[str] = []

    for path in REPO.rglob("*.py"):
        if "node_modules" in path.parts or "__pycache__" in path.parts:
            continue
        if path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for n, line in enumerate(text.splitlines(), 1):
            if dialable.search(line) and "docstring-example" not in line:
                offenders.append(f"{path.relative_to(REPO)}:{n}: {line.strip()[:90]}")

    assert not offenders, (
        "Dialable phone numbers found in source:\n" + "\n".join(offenders)
    )


def test_seed_never_asserts_consent():
    """`consent_verified=1` may only be written by the configured-contact
    loader, never by seeding. Consent is given by a person, never defaulted."""
    seed_src = (REPO / "services/api/core/seed.py").read_text(encoding="utf-8")

    # Isolate seed_simulation, the only place that inserts demo contacts.
    sim = seed_src.split("def seed_simulation", 1)
    assert len(sim) == 2, "seed_simulation not found"

    for line in sim[1].splitlines():
        if "emergency_contact" in line or "cnt_" in line:
            assert '", 1, 1)' not in line, (
                f"simulated contact asserts consent_verified=1: {line.strip()[:100]}"
            )


def test_outbound_dispatch_is_blocked_under_simulation(monkeypatch):
    """A fabricated incident must never summon a real responder."""
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.setenv("ERSS_112_GATEWAY_URL", "https://example.invalid/cad")
    monkeypatch.setenv("ERSS_112_API_KEY", "test-key-not-real")

    from services.api.core import config as config_mod

    importlib.reload(config_mod)
    from services.api.adapters import emergency_dispatch

    importlib.reload(emergency_dispatch)

    result = emergency_dispatch.create_emergency_dispatch_request(
        incident_id="inc_simulated",
        service_type="ambulance",
        severity="critical",
        latitude=16.5062,
        longitude=80.6480,
        road_segment="test-segment",
        evidence_ids=[],
    )

    assert result["transmitted"] is False
    assert result["confirmed"] is False
    assert result["status"] == "blocked_simulation_barrier"

    monkeypatch.setenv("MOCK_MODE", "false")
    importlib.reload(config_mod)
    importlib.reload(emergency_dispatch)


def test_outbound_disabled_by_default_even_on_the_real_path(monkeypatch):
    """Credentials alone must not be enough to contact emergency services."""
    monkeypatch.setenv("MOCK_MODE", "false")
    monkeypatch.delenv("ALLOW_OUTBOUND_NOTIFICATIONS", raising=False)
    monkeypatch.setenv("ERSS_112_GATEWAY_URL", "https://example.invalid/cad")
    monkeypatch.setenv("ERSS_112_API_KEY", "test-key-not-real")

    from services.api.core import config as config_mod

    importlib.reload(config_mod)
    from services.api.adapters import emergency_dispatch

    importlib.reload(emergency_dispatch)

    result = emergency_dispatch.create_emergency_dispatch_request(
        incident_id="inc_real",
        service_type="ambulance",
        severity="critical",
        latitude=16.5062,
        longitude=80.6480,
        road_segment="test-segment",
        evidence_ids=[],
    )

    assert result["transmitted"] is False
    assert result["status"] == "blocked_outbound_disabled"


def test_ui_never_silently_substitutes_demo_data():
    """No page may fall back from live data to bundled fixtures.

    The pattern `const x = apiData ?? FIXTURE_X` renders demo content as though
    it were observed whenever the API is unreachable. On the audit screen that
    meant showing "chain intact" without ever running a verification; on the
    public portal it would mean publishing a fabricated all-clear.

    Fixtures are still allowed behind an explicit MOCK_MODE check in
    lib/api.ts, which tags the response so the UI can label it.
    """
    web = REPO / "apps" / "web"
    if not web.exists():
        return

    bad = re.compile(r"\?\?\s*(FIXTURE_[A-Z_]+|[A-Z_]{4,})\b")
    allowed_files = {"api.ts", "fixtures"}
    offenders: list[str] = []

    for path in list(web.rglob("*.tsx")) + list(web.rglob("*.ts")):
        parts = set(path.parts)
        if "node_modules" in parts or ".next" in parts:
            continue
        if path.name in allowed_files or "fixtures" in parts:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            m = bad.search(line)
            if not m:
                continue
            token = m.group(1)
            # Constant lookup defaults (META.R0, SEVERITY_META.info) are fine;
            # only bundled demo payloads are the problem.
            if token.startswith("FIXTURE_") or token in {
                "CITY", "OPS", "AUDIT", "CHAIN", "TWIN", "EVIDENCE",
                "INCIDENTS", "POLICY_DECISIONS", "PUBLIC_STATUS",
                "INCIDENT_DETAIL",
            }:
                offenders.append(f"{path.relative_to(REPO)}:{n}: {line.strip()[:90]}")

    assert not offenders, (
        "UI falls back to demo data without labelling it:\n" + "\n".join(offenders)
    )


def test_no_secrets_committed_in_source():
    """No live-looking API key may sit in source."""
    patterns = [
        re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}"),
        re.compile(r"sk-[A-Za-z0-9]{32,}"),
        re.compile(r"AIza[0-9A-Za-z\-_]{30,}"),
    ]
    offenders: list[str] = []

    for ext in ("*.py", "*.ts", "*.tsx", "*.json"):
        for path in REPO.rglob(ext):
            if "node_modules" in path.parts or "__pycache__" in path.parts:
                continue
            if path.name == Path(__file__).name:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pat in patterns:
                if pat.search(text):
                    offenders.append(str(path.relative_to(REPO)))

    assert not offenders, f"possible committed secrets: {offenders}"
