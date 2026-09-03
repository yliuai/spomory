from datetime import UTC, datetime, timedelta

from memory_core.usage import UsageTracker


def test_active_users_since_counts_distinct_recent_users():
    tracker = UsageTracker(":memory:")
    tracker.record_event("u1", "add_memory")
    tracker.record_event("u1", "search_memory")
    tracker.record_event("u2", "add_memory")

    assert tracker.active_users_since(7) == 2
    assert tracker.event_count("u1") == 2
    assert tracker.event_count("u1", "add_memory") == 1


def test_active_users_since_excludes_stale_events():
    tracker = UsageTracker(":memory:")
    stale = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    tracker._conn.execute(
        "INSERT INTO usage_events (user_id, event_type, created_at) VALUES (?, ?, ?)",
        ("old-user", "add_memory", stale),
    )
    tracker._conn.commit()
    tracker.record_event("fresh-user", "add_memory")

    assert tracker.active_users_since(7) == 1
