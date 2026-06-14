"""Evolve — Skipper's self-maintaining SDLC engine.

This package is the implementation of the `evolve` Capability described in
specs/EVOLVE.md and seeded as a C/F/S tree under specs/evolve/.

Build status (the deterministic, no-LLM substrate is real and unit-tested;
the agent/runtime/UI layers are staged for box-1/box-2 and the platform):

  cfs-store      — schema.py, store.py, variance.py     [BUILT + tested]
  process-engine — engine/{model,instance,walker,mermaid}.py [BUILT + tested]
  agents         — agents/{base,runner}.py + prompts/   [framework staged]
  intake         — apps/evolve/intake/*                 [TODO — GitHub connector]
  gates/app-ui   — apps/evolve/{gates,ui}/*             [TODO — needs platform]

The substrate has no dependency on the running platform or on Claude, so it is
importable and testable standalone (`python3 -m unittest discover -s tests`).
Platform integration (Postgres projection, thinking-domain registration) lives
behind thin adapters that are written but not exercised until the platform
hosts this app.
"""
