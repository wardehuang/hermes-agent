"""In-place compaction keeps each carried row's original timestamp (follow-up to #59661).

The gateway rebuilds replay history from stored rows with every role's ``message_uid`` but without
timestamps (only user rows keep one), so a compaction that carries those dicts has to give each its
durable row's timestamp, found by uid even after that row was archived or rewound. Compaction
scaffolding stays new at the boundary and gets compaction time (#121064).
"""

import pytest

from agent.message_metadata import mark_inflight_restatement
from hermes_state import SessionDB

BASE_TS = 1_700_000_000.0
CONVERSATION = (("user", "u0"), ("assistant", "a0"), ("user", "u1"), ("assistant", "a1"))


@pytest.fixture()
def db(tmp_path):
    handle = SessionDB(db_path=tmp_path / "state.db")
    try:
        yield handle
    finally:
        handle.close()


def _active(db):
    rows = db._conn.execute(
        "SELECT role, content, timestamp, message_uid FROM messages "
        "WHERE session_id = 's' AND active = 1 ORDER BY id"
    ).fetchall()
    return {row["content"]: dict(row) for row in rows}


def _seed(db):
    db.create_session("s", source="test")
    for i, (role, content) in enumerate(CONVERSATION):
        db.append_message("s", role=role, content=content, timestamp=BASE_TS + i * 10)
    return _active(db)


def _replay(*rows):
    """Carried dicts as the gateway rebuilds them: role, content and uid, no timestamp."""
    return [{"role": r["role"], "content": r["content"], "message_uid": r["message_uid"]} for r in rows]


def _compact(db, *carried, tail_count, summary="SUMMARY"):
    db.archive_and_compact("s", [{"role": "assistant", "content": summary}, *carried], tail_count=tail_count)


def test_carried_rows_keep_their_original_timestamp(db):
    before = _seed(db)
    _compact(db, *_replay(before["u1"], before["a1"]), tail_count=2)
    after = _active(db)
    assert after["u1"]["timestamp"] == before["u1"]["timestamp"]
    assert after["a1"]["timestamp"] == before["a1"]["timestamp"]


def test_rewritten_copy_is_carried_by_uid_from_an_archived_row(db):
    """A pruned or stubbed copy shares only the uid with its original, which the compaction archives."""
    before = _seed(db)
    (stub,) = _replay(before["a1"])
    stub["content"] = "[pruned]"
    _compact(db, stub, tail_count=0)
    assert _active(db)["[pruned]"]["timestamp"] == before["a1"]["timestamp"]


def test_repeated_compaction_from_rebuilt_dicts_keeps_the_original_timestamp(db):
    before = _seed(db)
    _compact(db, *_replay(before["u1"], before["a1"]), tail_count=2, summary="S1")
    mid = _active(db)
    _compact(db, *_replay(mid["u1"], mid["a1"]), tail_count=2, summary="S2")
    final = _active(db)
    assert final["u1"]["timestamp"] == before["u1"]["timestamp"]
    assert final["a1"]["timestamp"] == before["a1"]["timestamp"]


def test_explicit_timestamp_is_never_overwritten(db):
    before = _seed(db)
    (carried,) = _replay(before["a1"])
    carried["timestamp"] = BASE_TS + 500.0
    _compact(db, carried, tail_count=1)
    assert _active(db)["a1"]["timestamp"] == BASE_TS + 500.0


def test_inflight_restatement_is_new_at_the_boundary(db):
    """#121064: a restated task keeps its uid but takes compaction time, not its original timestamp."""
    before = _seed(db)
    (restated,) = _replay(before["u1"])
    restated["content"] = "[restated] u1"
    mark_inflight_restatement(restated)
    _compact(db, restated, tail_count=0)
    assert _active(db)["[restated] u1"]["timestamp"] > before["u1"]["timestamp"] + 1


def test_dict_without_uid_is_not_matched_by_content(db):
    before = _seed(db)
    _compact(db, {"role": "user", "content": "u1"}, tail_count=0)
    assert _active(db)["u1"]["timestamp"] > before["u1"]["timestamp"] + 1
