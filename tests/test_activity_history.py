import json

from activity_history import ActivityHistory


def test_activity_history_persists_and_caps_entries(tmp_path):
    path = tmp_path / "activity.json"
    history = ActivityHistory(path=str(path), max_entries=2)

    history.append("one", kind="info", timestamp="2026-01-01T10:00:00+00:00")
    history.append("two", kind="success", timestamp="2026-01-01T10:01:00+00:00")
    history.append("three", kind="error", timestamp="2026-01-01T10:02:00+00:00")

    entries = history.entries()
    assert [entry["message"] for entry in entries] == ["two", "three"]
    assert entries[-1]["kind"] == "error"

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert len(saved) == 2


def test_activity_history_recovers_from_invalid_file(tmp_path):
    path = tmp_path / "activity.json"
    path.write_text("{broken", encoding="utf-8")
    history = ActivityHistory(path=str(path))

    assert history.entries() == []

    history.append("recovered", timestamp="2026-01-01T10:00:00+00:00")
    assert history.entries()[0]["message"] == "recovered"


def test_activity_history_clear(tmp_path):
    path = tmp_path / "activity.json"
    history = ActivityHistory(path=str(path))
    history.append("one", timestamp="2026-01-01T10:00:00+00:00")

    history.clear()

    assert history.entries() == []



def test_search_and_export_respects_filter_and_newest_order():
    from activity_history import filter_activity_entries, render_activity_export
    entries = [
        {"timestamp": "2026-01-02T10:00:00", "message": "Download completed", "kind": "success"},
        {"timestamp": "2026-01-01T10:00:00", "message": "Network failed", "kind": "error"},
        {"timestamp": "2025-12-30T10:00:00", "message": "Another download", "kind": "info"},
    ]
    filtered = filter_activity_entries(entries, "DOWNLOAD")
    assert [item["message"] for item in filtered] == ["Download completed", "Another download"]
    assert "Network failed" not in render_activity_export(filtered)
    assert render_activity_export(filtered).splitlines() == [
        "2026-01-02 10:00:00 [success] Download completed",
        "2025-12-30 10:00:00 [info] Another download",
    ]
    assert filter_activity_entries(entries, "2026-01-01") == [entries[1]]


def test_export_sanitizes_multiline_messages():
    from activity_history import format_activity_entry
    assert format_activity_entry({"timestamp": "T", "kind": "error", "message": "one\nnew line"}) == "  [error] one new line"


def test_activity_history_uses_unique_temp_files_for_concurrent_instances(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    path = tmp_path / "activity.json"
    first = ActivityHistory(path=str(path))
    second = ActivityHistory(path=str(path))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(h._write_unlocked, [{"timestamp": "now", "kind": "info", "message": "ok"}]) for h in (first, second)]
        for future in futures:
            future.result(timeout=10)
    assert json.loads(path.read_text(encoding="utf-8"))[0]["message"] == "ok"
    assert not list(tmp_path.glob("*.tmp"))
