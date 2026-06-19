"""Repo root, location-independent — for tests that need to resolve repo-relative paths.

This module lives at the repo root, so ``ROOT`` is simply its own directory. Tests import it
(``__import__("repo_paths").ROOT``) instead of counting ``..`` from ``__file__`` — which broke
when tests moved to ``apps/<app>/tests/`` at varying depths. The repo root is on ``sys.path``
during a test run (discovery's top-level dir), so this import always resolves.
"""
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
