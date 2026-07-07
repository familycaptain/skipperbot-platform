"""
Bound test for ev-104 — spec platform.thinking.cycle-log-id-uniqueness.

Root cause: data_layer/thinking_log.py::_new_id was `tl-{uuid4.hex[:8]}` (32-bit), so at
production volume the thinking_log primary key collided (birthday paradox). log_cycle's
INSERT then raised a duplicate-key error, and because thinking_scheduler._run_cycle logs the
SUCCESS-path write inside the try whose `except` records a FAILED cycle (and skips the
_digest_cycle bookkeeping), completed cycles were mislabeled FAILED.

Fix (approved Option B): widen _new_id to full uuid4.hex (128-bit) AND make log_cycle retry
once on a psycopg2.errors.UniqueViolation with a fresh id (catching ONLY the unique-violation
so genuine failures still surface).
"""
import re
from unittest import mock
from datetime import timezone

import psycopg2
import pytest

from data_layer import thinking_log as tl

_ID_RE = re.compile(r"^tl-[0-9a-f]{32}$")  # 'tl-' + full uuid4 hex = 128-bit


def test_new_id_is_128bit_format():
    # (a) FORMAT/WIDTH regression: every id is 'tl-' + 32 lowercase hex chars.
    for _ in range(2000):
        assert _ID_RE.match(tl._new_id()), tl._new_id()


def test_new_id_unique_over_large_n():
    # (b) UNIQUENESS: 100k ids, zero duplicates (32-bit ids would already collide well before
    # this; 128-bit does not).
    n = 100_000
    ids = {tl._new_id() for _ in range(n)}
    assert len(ids) == n


def _uv(msg='duplicate key value violates unique constraint "thinking_log_pkey"'):
    return psycopg2.errors.UniqueViolation(msg)


def test_collision_retries_once_and_succeeds():
    # (c) FORCED COLLISION SUCCEEDS (mirrors the gate-1 reproduction): the first INSERT draws
    # an id already present (UniqueViolation); log_cycle regenerates and retries once, and the
    # cycle is recorded successfully with the fresh id — a colliding draw is NOT a failed cycle.
    ids = []

    def fake_execute(query, params):
        ids.append(params[0])
        if len(ids) == 1:
            raise _uv()
        return 1

    with mock.patch.object(tl, "execute", fake_execute), \
         mock.patch.object(tl, "get_timezone", lambda: timezone.utc), \
         mock.patch.object(tl, "get_log_entry", lambda log_id: {"id": log_id}):
        result = tl.log_cycle(domain="memory", trigger="timer", input_summary="work done")

    assert len(ids) == 2, "expected exactly one retry"
    assert ids[0] != ids[1], "retry must use a freshly-generated id"
    assert result["id"] == ids[1], "log_cycle returns the row actually inserted (the retry id)"


def test_persistent_collision_is_bounded_and_raises():
    # (d) BOUNDED RETRY: if the collision persists on the retry too, log_cycle raises after
    # exactly one retry (never an unbounded loop).
    calls = []

    def always_collide(query, params):
        calls.append(params[0])
        raise _uv()

    with mock.patch.object(tl, "execute", always_collide), \
         mock.patch.object(tl, "get_timezone", lambda: timezone.utc), \
         mock.patch.object(tl, "get_log_entry", lambda log_id: {"id": log_id}):
        with pytest.raises(psycopg2.errors.UniqueViolation):
            tl.log_cycle(domain="memory", trigger="timer")

    assert len(calls) == 2, "exactly one retry, then give up"


def test_non_unique_error_is_reraised_not_retried():
    # (e) OBSERVABILITY PRESERVED: a NON-unique-violation DB error propagates unchanged and is
    # NOT retried, so genuine failures still surface to _run_cycle and log a real FAILED cycle.
    calls = []

    def other_error(query, params):
        calls.append(params[0])
        raise psycopg2.OperationalError("connection reset")

    with mock.patch.object(tl, "execute", other_error), \
         mock.patch.object(tl, "get_timezone", lambda: timezone.utc), \
         mock.patch.object(tl, "get_log_entry", lambda log_id: {"id": log_id}):
        with pytest.raises(psycopg2.OperationalError):
            tl.log_cycle(domain="memory", trigger="timer")

    assert len(calls) == 1, "non-unique errors must NOT be retried"
