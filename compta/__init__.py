"""Registre de recettes du cabinet — noyau métier partagé par les pages Streamlit."""

from . import config, model, store, xlsx_io  # noqa: F401

__all__ = ["config", "model", "store", "xlsx_io"]
