"""Unit regression tests: SEC-012 (patched deps), SEC-019 (CI supply chain),
SEC-018 (repo deployment config). Static checks only — no network."""

from __future__ import annotations

import re
from importlib.metadata import version
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((REPO / ".github" / "workflows").glob("*.yml"))


def _v(text: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", text)[:3])


def _pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==([^\s;\\]+)", line)
        if m:
            pins[m.group(1).lower().replace("_", "-")] = m.group(2)
    return pins


# --- SEC-012: no known-vulnerable versions of reachable packages --------------

# Minimum patched versions from the audit's OSV evidence.
MINIMUMS = {
    "starlette": "1.3.1",  # GHSA-82w8-qh3p-5jfq, GHSA-7f5h-v6xp-fcq8, GHSA-2c2j-...
    "python-multipart": "0.0.31",  # GHSA-v9pg-7xvm-68hf, GHSA-5rvq-cxj2-64vf, ...
    "jinja2": "3.1.6",  # GHSA-cpwx-vrp4-4pq7
    "python-dotenv": "1.2.2",  # GHSA-mf9w-mj56-hr94
    "anyio": "4.14.2",  # GHSA-5p39-cfhj-2xmp, GHSA-82r6-8w77-94w6
    "mako": "1.4.2",  # GHSA-5639-2j2p-m4mx
}


@pytest.mark.parametrize(("pkg", "minimum"), sorted(MINIMUMS.items()))
def test_installed_version_is_patched(pkg: str, minimum: str) -> None:
    assert _v(version(pkg)) >= _v(minimum), f"{pkg} {version(pkg)} < {minimum}"


@pytest.mark.parametrize(("pkg", "minimum"), sorted(MINIMUMS.items()))
def test_shipped_lock_pins_patched_version(pkg: str, minimum: str) -> None:
    lock = _pins(REPO / "requirements.lock")
    assert pkg in lock, f"{pkg} missing from requirements.lock"
    assert _v(lock[pkg]) >= _v(minimum)


def test_starlette_is_pinned_explicitly() -> None:
    pins = _pins(REPO / "requirements.txt")
    assert "starlette" in pins and "python-multipart" in pins


def test_starlette_parses_range_header_without_quadratic_merge() -> None:
    # GHSA-7f5h-v6xp-fcq8: many overlapping ranges must parse quickly.
    import time

    from starlette.responses import FileResponse

    header = "bytes=" + ",".join(f"{i}-{i + 1}" for i in range(0, 20000, 1))
    resp = FileResponse(__file__)
    start = time.perf_counter()
    try:
        resp._parse_range_header(header, 10**9)
    except Exception:  # noqa: BLE001 — rejecting the header is also fine
        pass
    assert time.perf_counter() - start < 1.0


# --- SEC-019: CI/CD supply chain ----------------------------------------------


def test_workflows_exist() -> None:
    assert {p.name for p in WORKFLOWS} >= {"deploy.yml", "test.yml"}


@pytest.mark.parametrize("wf", WORKFLOWS, ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_commit_sha(wf: Path) -> None:
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)(.*)$", wf.read_text(encoding="utf-8"), re.M)
    assert uses, f"no actions found in {wf.name}"
    for ref, rest in uses:
        if ref.startswith("./"):
            continue
        assert re.fullmatch(r"[\w.\-]+/[\w.\-/]+@[0-9a-f]{40}", ref), f"{wf.name}: {ref}"
        assert re.search(r"#\s*v\d+\.\d+\.\d+", rest), f"{wf.name}: {ref} lacks version comment"


def test_deploy_runs_full_gate_before_build() -> None:
    text = (REPO / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    verify_job = text.split("build-and-push:")[0]
    assert "make PY=python LINT_IMPORTS=lint-imports verify" in verify_job
    assert "test-e2e" in verify_job
    assert "requirements-dev.txt" in verify_job
    assert re.search(r"build-and-push:\s*\n\s*needs:\s*verify", text)


def test_ci_audits_dependencies() -> None:
    for name in ("test.yml", "deploy.yml"):
        text = (REPO / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "make PY=python audit" in text, name
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^audit:\n\t.*pip_audit.*requirements\.lock", makefile, re.M)
    assert "pip-audit" in _pins(REPO / "requirements-dev.txt")


def test_dependabot_covers_actions_and_pip() -> None:
    text = (REPO / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert "package-ecosystem: github-actions" in text
    assert "package-ecosystem: pip" in text
    assert text.count("interval: weekly") >= 2


def test_lockfile_is_hashed_and_agrees_with_requirements() -> None:
    lock_path = REPO / "requirements.lock"
    lock = _pins(lock_path)
    text = lock_path.read_text(encoding="utf-8")
    assert len(lock) >= 20, "lockfile must pin transitive deps too"
    for block in re.split(r"\n(?=[A-Za-z0-9])", text):
        if "==" in block.splitlines()[0]:
            assert "--hash=sha256:" in block, block.splitlines()[0]
    for pkg, pinned in _pins(REPO / "requirements.txt").items():
        assert lock.get(pkg) == pinned, f"{pkg}: requirements.txt {pinned} != lock {lock.get(pkg)} — run `make lock`"


def test_image_installs_with_require_hashes() -> None:
    dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
    assert "--require-hashes -r requirements.lock" in dockerfile


# --- SEC-018: repo deployment config ------------------------------------------


def test_compose_app_port_is_loopback_only() -> None:
    text = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    app_block = text.split("\n  caddy:")[0]
    ports = re.findall(r'^\s*-\s*"?([^"\n]+:8000)"?\s*$', app_block, re.M)
    assert ports, "app port mapping not found"
    for mapping in ports:
        assert mapping.startswith("127.0.0.1:"), mapping


@pytest.mark.parametrize(
    "pattern", [".env", "*.db", ".venv/", ".git/", "docs/", "tests/", "**/*.db", "**/.env"]
)
def test_dockerignore_excludes_secrets_and_state(pattern: str) -> None:
    lines = (REPO / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert pattern in lines


def test_image_runs_unprivileged_with_writable_data_dir_only() -> None:
    dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
    users = re.findall(r"^USER\s+(\S+)", dockerfile, re.M)
    assert users and users[-1] not in {"root", "0"}, "image must not run as root (SEC-018)"
    assert "chown -R" not in dockerfile, "source tree must stay root-owned"
    assert "DATABASE_URL=sqlite:////app/data/quiz.db" in dockerfile
    compose = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    assert "./quiz.db:/app/data/quiz.db" in compose
