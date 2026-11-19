"""Integración con LangSmith Datasets & Experiments para automatizar evaluaciones."""
import uuid
from pathlib import Path
from typing import Any

from langsmith import Client
from pydantic import BaseModel

from src import config
from src.pipeline.evaluator import DEFAULT_DATASET_PATH, load_eval_dataset

_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


class DatasetSyncResult(BaseModel):
    dataset_name: str
    dataset_id: str
    total_examples: int
    created: bool


def scenario_to_langsmith_example(sc: dict[str, Any], dataset_name: str) -> dict[str, Any]:
    """Convierte una fila de `eval_dataset.jsonl` al formato `(id, inputs, outputs, metadata)` de LangSmith."""
    example_id = str(uuid.uuid5(_NAMESPACE, f"{dataset_name}:{sc['id']}"))
    return {
        "id": example_id,
        "inputs": {
            "id": sc["id"],
            "category": sc["category"],
            "context": sc.get("context") or {},
            "user_input": sc["user_input"],
        },
        "outputs": {
            "expected_routing": sc["expected_routing"],
            "expected_tool_calls": sc["expected_tool_calls"],
            "expected_behavior": sc.get("expected_behavior", ""),
            "pass_fail_criteria": sc.get("pass_fail_criteria") or [],
        },
        "metadata": {
            "scenario_id": sc["id"],
            "category": sc["category"],
            "stage_under_test": (sc.get("context") or {}).get("stage_under_test", "pipeline"),
        },
    }


def sync_dataset_to_langsmith(
    dataset_name: str | None = None,
    *,
    dataset_path: Path | None = None,
    client: Any = None,
) -> DatasetSyncResult:
    """Sincroniza `data/eval_dataset.jsonl` con un Dataset de LangSmith de forma idempotente."""
    name = dataset_name or config.LANGSMITH_DATASET_NAME
    ls_client = client or Client()
    scenarios = load_eval_dataset(dataset_path or DEFAULT_DATASET_PATH)

    created = False
    if ls_client.has_dataset(dataset_name=name):
        dataset = ls_client.read_dataset(dataset_name=name)
    else:
        dataset = ls_client.create_dataset(
            dataset_name=name,
            description=(
                "Golden evaluation dataset (23 escenarios) para el sistema multiagente "
                f"de soporte al cliente de {config.EMPRESA_NOMBRE}."
            ),
        )
        created = True

    existing_by_id = {str(ex.id): ex for ex in ls_client.list_examples(dataset_id=dataset.id)}

    for sc in scenarios:
        ex_data = scenario_to_langsmith_example(sc, name)
        ex_id = ex_data["id"]
        if ex_id in existing_by_id:
            ls_client.update_example(
                example_id=ex_id,
                inputs=ex_data["inputs"],
                outputs=ex_data["outputs"],
                metadata=ex_data["metadata"],
            )
        else:
            ls_client.create_example(
                inputs=ex_data["inputs"],
                outputs=ex_data["outputs"],
                metadata=ex_data["metadata"],
                dataset_id=dataset.id,
                example_id=ex_id,
            )

    return DatasetSyncResult(
        dataset_name=name,
        dataset_id=str(dataset.id),
        total_examples=len(scenarios),
        created=created,
    )
