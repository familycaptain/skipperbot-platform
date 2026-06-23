"""Connector loader — MODEL_FLEXIBILITY (issue #44, spec mf-connector-loader).

``load_all_connectors()`` registers the built-in connectors, then discovers EXTERNAL
connectors from a gitignored ``models/`` folder — each ``models/<name>/connector.py`` exposes
a ``connector()`` entrypoint returning ``(ConnectorDescriptor, chat_provider, embedding_provider)``.
Mirrors ``app_platform/loader.py``: directory scan + dynamic import + register, skip-with-warning
on error, never crash boot. CORE NEVER IMPORTS A CONNECTOR — discovery is by path only, so the
dependency stays one-directional (connectors -> core, never core -> connector).

When ``models/`` is absent or empty the external scan is inert (no user-facing flow this issue;
the downloaded-connector trust model is deferred — security review).
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _repo_root() -> Path:
    # providers/connectors/loader.py -> repo root is two parents up from providers/
    return Path(__file__).resolve().parents[2]


def load_all_connectors(models_dir: str | Path | None = None,
                        *, register_builtins: bool = True) -> list[str]:
    """Register built-ins + external connectors. Returns the list of registered names."""
    names: list[str] = []
    if register_builtins:
        try:
            from providers.connectors import builtins as _builtins
            names += _builtins.register_builtins()
        except Exception as e:   # never let a built-in error crash boot
            logger.error("CONNECTOR LOADER: built-in registration failed: %s", e)
    if models_dir is None:
        models_dir = _repo_root() / "models"
    names += _load_external(Path(models_dir))
    return names


def _load_external(models_dir: Path) -> list[str]:
    out: list[str] = []
    if not models_dir.is_dir():
        return out   # inert when the folder doesn't exist
    for child in sorted(models_dir.iterdir()):
        entry = child / "connector.py"
        if not child.is_dir() or not entry.exists():
            continue
        try:
            out.append(_load_one(child.name, entry))
        except Exception as e:
            logger.warning("CONNECTOR LOADER: skipping %s — %s", child.name, e)
    return out


def _load_one(dir_name: str, entry: Path) -> str:
    spec = importlib.util.spec_from_file_location(f"skipperbot_model_{dir_name}", entry)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load connector at {entry}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "connector"):
        raise AttributeError("connector.py must expose a connector() entrypoint")
    descriptor, chat, embedding = mod.connector()
    descriptor.validate()
    if chat is None and embedding is None:
        raise ValueError(f"connector {descriptor.name!r} registered no chat/embedding provider")
    from providers import registry   # lazy import; loader is the only core->registry caller here
    registry.register_model_provider(descriptor.name, chat=chat, embedding=embedding,
                                     descriptor=descriptor)
    return descriptor.name
