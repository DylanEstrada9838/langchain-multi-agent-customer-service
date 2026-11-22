"""Stable evaluation fingerprints used by the runner and offline CI."""
import hashlib
import json
from dataclasses import asdict

from src import config
from src.agents import get_active_versions, load_spec
from src.data.repositories import EVALUATION_DATE
from src.pipeline.eval_dataset import load_eval_dataset

BENCHMARK_SCHEMA = 2


def _digest(value) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fixture_settings() -> dict:
    return {
        key: getattr(config, key) for key in (
            "EMPRESA_NOMBRE", "DIAS_DEVOLUCION_ESTANDAR", "DIAS_DEVOLUCION_VIP", "FAKER_LOCALE",
            "FAKER_SEED", "NUM_CLIENTES", "NUM_PEDIDOS", "NUM_PRODUCTOS", "NUM_INCIDENCIAS", "MAX_QA_RETRIES",
        )
    }


def benchmark_fingerprint() -> str:
    return _digest({
        "schema": BENCHMARK_SCHEMA,
        "scenarios": sorted(load_eval_dataset(), key=lambda row: row["id"]),
        "fixture_date": EVALUATION_DATE.isoformat(),
        "fixture_settings": _fixture_settings(),
        "assertion_code": (config.ROOT / "src/pipeline/scenario_checks.py").read_text(encoding="utf-8"),
    })


def source_fingerprint(versions: dict[str, str]) -> str:
    paths = [*config.ROOT.glob("src/**/*.py")]
    paths.extend(config.ROOT / name for name in ("main.py", "requirements.txt", "requirements-ci.txt"))
    paths.extend(config.ROOT / "src/agents/specs" / agent / f"{version}.yaml" for agent, version in versions.items())
    return _digest({
        path.relative_to(config.ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in paths
    })


def evaluation_provenance(versions: dict[str, str]) -> dict:
    return {
        "benchmark_fingerprint": benchmark_fingerprint(),
        "source_fingerprint": source_fingerprint(versions),
        "fixture_date": EVALUATION_DATE.isoformat(),
        "models": {agent: asdict(load_spec(agent, version).model_config) for agent, version in versions.items()},
        "fixture_settings": _fixture_settings(),
    }


def validate_full_report(report: dict) -> None:
    versions = get_active_versions()
    if report.get("versions") != versions:
        raise ValueError("Report agent versions do not match active_versions.yaml.")
    expected = sorted(row["id"] for row in load_eval_dataset())
    if report.get("partial") is not False or report.get("scenario_ids") != expected or report.get("total_examples") != len(expected):
        raise ValueError("Report does not cover the full golden dataset.")
    provenance = report.get("provenance") or {}
    if (provenance.get("source_fingerprint") != source_fingerprint(versions)
            or provenance.get("benchmark_fingerprint") != benchmark_fingerprint()
            or provenance.get("fixture_date") != EVALUATION_DATE.isoformat()):
        raise ValueError("Report provenance differs from the checked-out benchmark or runtime.")
    models = provenance.get("models") or {}
    if models.keys() != versions.keys() or any(not cfg.get("model_name") or not cfg.get("provider") for cfg in models.values()):
        raise ValueError("Report is missing resolved model settings.")
    if report.get("passed") is not True:
        raise ValueError("Report did not pass the quality gate.")
