"""Golden benchmark loading and ticket construction."""
import json
from pathlib import Path
from typing import Any

from src import config

DEFAULT_DATASET_PATH = config.ROOT / "data" / "eval_dataset.jsonl"

def load_eval_dataset(path: Path | None = None) -> list[dict[str, Any]]:
    dataset_path = path or DEFAULT_DATASET_PATH
    rows = [json.loads(line) for line in dataset_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [row["id"] for row in rows]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("El dataset debe contener escenarios con ID unico.")
    return rows


def scenario_to_ticket(sc: dict[str, Any]) -> dict[str, Any]:
    ctx = sc.get("context") or {}
    return {
        "id": sc["id"],
        "cliente_id": ctx.get("cliente_id", "C900"),
        "pedido_id": ctx.get("pedido_id"),
        "asunto": f"Eval {sc['id']} ({sc['category']})",
        "mensaje": sc["user_input"],
    }
