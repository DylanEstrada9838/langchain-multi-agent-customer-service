"""Capa de datos: políticas, inicialización de base de datos (SQLite/PostgreSQL) y repositorio."""
from src.data.policies import POLITICAS
from src.data.repositories import SupportRepository, get_repo, init_db

__all__ = ["POLITICAS", "SupportRepository", "get_repo", "init_db"]
