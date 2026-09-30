"""Importing this package registers every built-in workflow in WORKFLOWS."""
from .base import WORKFLOWS, Workflow, register
from . import create, restyle, edit, instrumental, cover  # noqa: F401  (registration side effect)

__all__ = ["WORKFLOWS", "Workflow", "register"]
