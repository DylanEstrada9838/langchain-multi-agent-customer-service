"""Configuración global: carga de .env y constantes de entorno."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


EMPRESA_NOMBRE = os.getenv("EMPRESA_NOMBRE", "TechStore")
DIAS_DEVOLUCION_ESTANDAR = _env_int("DIAS_DEVOLUCION_ESTANDAR", 30)
DIAS_DEVOLUCION_VIP = _env_int("DIAS_DEVOLUCION_VIP", 60)
FAKER_LOCALE = os.getenv("FAKER_LOCALE", "es_ES")
FAKER_SEED = _env_int("FAKER_SEED", 42)
NUM_CLIENTES = _env_int("NUM_CLIENTES", 50)
NUM_PEDIDOS = _env_int("NUM_PEDIDOS", 150)
NUM_PRODUCTOS = _env_int("NUM_PRODUCTOS", 25)
NUM_INCIDENCIAS = _env_int("NUM_INCIDENCIAS", 5)
OUTPUT_DIR = ROOT / os.getenv("OUTPUT_DIR", "outputs")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(ROOT / 'data' / 'soporte.db').as_posix()}")

# Configuración por defecto del LLM y versionado de agentes
DEFAULT_LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
DEFAULT_LLM_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
DEFAULT_LLM_TEMPERATURE = _env_float("LLM_TEMPERATURE", 0.2)
DEFAULT_LLM_MAX_TOKENS = _env_int("LLM_MAX_TOKENS", 1500)
DEFAULT_LLM_TIMEOUT = _env_int("LLM_TIMEOUT_SECONDS", 60)
MAX_QA_RETRIES = _env_int("MAX_QA_RETRIES", 1)
LANGSMITH_DATASET_NAME = os.getenv("LANGSMITH_DATASET_NAME", "techstore-support-golden-v1")
