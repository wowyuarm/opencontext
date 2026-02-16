"""Tests for opencontext.core.db — Database CRUD, jobs, search."""

import pytest

from opencontext.core.db import Database
from opencontext.core.models import AgentInfo, Event, Job, Session, Turn


@pytest.fixture
def db(tmp_path):
    """Fresh database per test."""
    db = Database(tmp_path / "test.db")
    db.initialize()
    yield db
    db.close()


def _make_session(**overrides) -> Session:
    defaults = dict(
        id="sess-001",
        file_path="/tmp/session.jsonl",
        session_type="claude",
        workspace="/home/yu/projects/foo",
        started_at="2025-01-01 00:00:00",
        last_activity_at="2025-01-01 01:00:00",
        title="Test session",
        summary="A test session",
        total_turns=3,
    )
    defaults.update(overrides)
    return Session(**defaults)


def _make_turn(session_id="sess-001", turn_number=1, **overrides) -> Turn:
    defaults = dict(
        id=f"turn-{session_id}-{turn_number}",
        session_id=session_id,
        turn_number=turn_number,
        user_message="Hello",
        assistant_summary="Hi there",
        title=f"Turn {turn_number}",
        description="A turn",
        model_name="claude-3",
        content_hash=f"hash-{turn_number}",
        timestamp="2025-01-01 00:10:00",
    )
    defaults.update(overrides)
    return Turn(**defaults)


# ── Schema ────────────────────────────────────────────────────────────────────


class TestInitialization:
    def test_creates_tables(self, db):
        conn = db._conn()
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        expected = {"schema_version", "sessions", "turns", "turn_content",
                    "events", "event_sessions", "agent_info", "jobs"}
        assert expected.issubset(tables)

    def test_schema_version_recorded(self, db):
        row = db._conn().execute(
            "SELECT version FROM schema_version LIMIT 1"
        ).fetchone()
        assert row["version"] == 1

    def test_initialize_idempotent(self, db):
        # calling initialize again should not fail
        db.initialize()
        db.initialize()
        row = db._conn().execute(
            "SELECT COUNT(*) as c FROM schema_version"
        ).fetchone()
        assert row["c"] == 1

    def test_read_only_skips_init(self, tmp_path):
        # create a DB first
        rw = Database(tmp_path / "ro.db")
        rw.initialize()
        rw.close()

        ro = Database(tmp_path / "ro.db", read_only=True)
        # should not error
        ro.initialize()
        ro.close()


# ── Sessions ──────────────────────────────────────────────────────────────────


class TestSessions:
    def test_upsert_and_get(self, db):
        s = _make_session()
        db.upsert_session(s)
        got = db.get_session("sess-001")
        assert got is not None
        assert got.id == "sess-001"
        assert got.workspace == "/home/yu/projects/foo"
        assert got.total_turns == 3

    def test_upsert_updates_existing(self, db):
        db.upsert_session(_make_session(title="v1"))
        db.upsert_session(_make_session(title="v2", total_turns=5))
        got = db.get_session("sess-001")
        assert got.title == "v2"
        assert got.total_turns == 5

    def test_get_nonexistent(self, db):
        assert db.get_session("nonexistent") is None

    def test_get_by_prefix(self, db):
        db.upsert_session(_make_session())
        got = db.get_session_by_prefix("sess-0")
        assert got is not None
        assert got.id == "sess-001"

    def test_list_sessions(self, db):
        db.upsert_session(_make_session(id="s1", last_activity_at="2025-01-01"))
        db.upsert_session(_make_session(id="s2", last_activity_at="2025-01-02"))
        sessions = db.list_sessions()
        assert len(sessions) == 2
        # most recent first
        assert sessions[0].id == "s2"

    def test_list_sessions_by_workspace(self, db):
        db.upsert_session(_make_session(id="s1", workspace="/proj/a"))
        db.upsert_session(_make_session(id="s2", workspace="/proj/b"))
        result = db.list_sessions(workspace="/proj/a")
        assert len(result) == 1
        assert result[0].id == "s1"

    def test_update_session_summary(self, db):
        db.upsert_session(_make_session())
        db.update_session_summary("sess-001", "New Title", "New Summary")
        got = db.get_session("sess-001")
        assert got.title == "New Title"
        assert got.summary == "New Summary"
        assert got.summary_updated_at is not None


# ── Turns ─────────────────────────────────────────────────────────────────────


class TestTurns:
    def test_insert_and_get(self, db):
        db.upsert_session(_make_session())
        t = _make_turn()
        db.insert_turn(t)
        turns = db.get_turns("sess-001")
        assert len(turns) == 1
        assert turns[0].user_message == "Hello"

    def test_insert_with_content(self, db):
        db.upsert_session(_make_session())
        t = _make_turn()
        db.insert_turn(t, content="full raw content here")
        content = db.get_turn_content(t.id)
        assert content == "full raw content here"

    def test_duplicate_turn_ignored(self, db):
        db.upsert_session(_make_session())
        t = _make_turn()
        db.insert_turn(t)
        db.insert_turn(t)  # INSERT OR IGNORE
        turns = db.get_turns("sess-001")
        assert len(turns) == 1

    def test_get_turn_by_hash(self, db):
        db.upsert_session(_make_session())
        db.insert_turn(_make_turn(content_hash="abc123"))
        got = db.get_turn_by_hash("sess-001", "abc123")
        assert got is not None
        assert got.content_hash == "abc123"

    def test_get_max_turn_number(self, db):
        db.upsert_session(_make_session())
        db.insert_turn(_make_turn(turn_number=1))
        db.insert_turn(_make_turn(turn_number=5, id="turn-sess-001-5", content_hash="h5"))
        assert db.get_max_turn_number("sess-001") == 5

    def test_max_turn_number_empty(self, db):
        assert db.get_max_turn_number("nonexistent") == 0

    def test_turn_increments_session_count(self, db):
        db.upsert_session(_make_session(total_turns=0))
        db.insert_turn(_make_turn(turn_number=1))
        db.insert_turn(_make_turn(turn_number=2, id="turn-sess-001-2", content_hash="h2"))
        got = db.get_session("sess-001")
        assert got.total_turns == 2


# ── Events ────────────────────────────────────────────────────────────────────


class TestEvents:
    def _make_event(self, **overrides) -> Event:
        defaults = dict(
            id="evt-001",
            title="Test Event",
            description="An event",
            event_type="task",
            status="active",
        )
        defaults.update(overrides)
        return Event(**defaults)

    def test_upsert_and_get(self, db):
        db.upsert_event(self._make_event())
        got = db.get_event("evt-001")
        assert got is not None
        assert got.title == "Test Event"

    def test_list_events(self, db):
        db.upsert_event(self._make_event(id="e1"))
        db.upsert_event(self._make_event(id="e2"))
        events = db.list_events()
        assert len(events) == 2

    def test_event_session_link(self, db):
        db.upsert_session(_make_session(id="s1"))
        db.upsert_session(_make_session(id="s2"))
        db.upsert_event(self._make_event(), session_ids=["s1", "s2"])
        linked = db.get_sessions_for_event("evt-001")
        assert len(linked) == 2


# ── Jobs ──────────────────────────────────────────────────────────────────────


class TestJobs:
    def test_enqueue_and_claim(self, db):
        job_id = db.enqueue_job("turn_summary", "ts:sess-001:1", {"session_id": "sess-001"})
        assert job_id

        job = db.claim_job("worker-1")
        assert job is not None
        assert job.kind == "turn_summary"
        assert job.status == "queued"  # returned before update visible

    def test_dedupe_key_prevents_duplicates(self, db):
        id1 = db.enqueue_job("turn_summary", "dedup-key-1")
        id2 = db.enqueue_job("turn_summary", "dedup-key-1")
        assert id1 == id2

    def test_complete_job(self, db):
        db.enqueue_job("turn_summary", "ts:1")
        job = db.claim_job("w1")
        db.complete_job(job.id)
        # No more jobs to claim
        assert db.claim_job("w1") is None

    def test_fail_job_with_retry(self, db):
        db.enqueue_job("turn_summary", "ts:1")
        job = db.claim_job("w1")
        db.fail_job(job.id, "timeout error", retry=True)
        # Should be claimable again
        retry_job = db.claim_job("w1")
        assert retry_job is not None

    def test_fail_job_permanent(self, db):
        db.enqueue_job("turn_summary", "ts:1")
        job = db.claim_job("w1")
        db.fail_job(job.id, "bad data", retry=False)
        assert db.claim_job("w1") is None

    def test_no_jobs_returns_none(self, db):
        assert db.claim_job("w1") is None


# ── Search ────────────────────────────────────────────────────────────────────


class TestSearch:
    def test_search_sessions_regex(self, db):
        db.upsert_session(_make_session(id="s1", title="Implement auth module"))
        db.upsert_session(_make_session(id="s2", title="Fix database bug"))
        results = db.search_sessions("auth")
        assert len(results) == 1
        assert results[0].id == "s1"

    def test_search_sessions_like(self, db):
        db.upsert_session(_make_session(id="s1", title="Implement auth module"))
        results = db.search_sessions("auth", regex=False)
        assert len(results) == 1

    def test_search_turns(self, db):
        db.upsert_session(_make_session())
        db.insert_turn(_make_turn(title="Add login endpoint"))
        db.insert_turn(_make_turn(turn_number=2, id="t2", title="Fix typo", content_hash="h2"))
        results = db.search_turns("login")
        assert len(results) == 1
        assert results[0]["title"] == "Add login endpoint"

    def test_search_content(self, db):
        db.upsert_session(_make_session())
        db.insert_turn(_make_turn(), content="def authenticate(user, password):")
        results = db.search_content("authenticate")
        assert len(results) == 1

    def test_search_events_regex(self, db):
        db.upsert_event(Event(
            id="e1", title="Deploy v2.0", description="Production deploy",
            event_type="task", status="active",
        ))
        results = db.search_events("deploy", regex=True)
        assert len(results) == 1


# ── Stats ─────────────────────────────────────────────────────────────────────


class TestStats:
    def test_stats_empty(self, db):
        s = db.stats()
        assert s["sessions"] == 0
        assert s["turns"] == 0
        assert s["events"] == 0
        assert s["jobs_pending"] == 0
        assert s["db_size_mb"] >= 0

    def test_stats_with_data(self, db):
        db.upsert_session(_make_session())
        db.insert_turn(_make_turn())
        db.enqueue_job("test", "dk1")
        s = db.stats()
        assert s["sessions"] == 1
        assert s["turns"] == 1
        assert s["jobs_pending"] == 1


# ── Agent Info ────────────────────────────────────────────────────────────────


class TestAgentInfo:
    def test_upsert_and_list(self, db):
        db.upsert_agent_info(AgentInfo(id="a1", name="bot-1"))
        agents = db.list_agent_info()
        assert len(agents) == 1
        assert agents[0].name == "bot-1"

    def test_visibility_filter(self, db):
        db.upsert_agent_info(AgentInfo(id="a1", name="visible-bot"))
        db.upsert_agent_info(AgentInfo(id="a2", name="hidden-bot", visibility="hidden"))
        visible = db.list_agent_info(include_hidden=False)
        assert len(visible) == 1
        all_agents = db.list_agent_info(include_hidden=True)
        assert len(all_agents) == 2
