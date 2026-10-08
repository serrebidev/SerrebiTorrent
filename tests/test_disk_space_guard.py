from disk_space_guard import active_download_groups


def test_active_download_groups_collects_only_incomplete_active_torrents():
    torrents = [
        {"hash": "a", "name": "A", "state": 1, "size": 100, "done": 25, "save_path": "/one"},
        {"hash": "b", "name": "B", "state": 1, "size": 200, "done": 50, "save_path": "/one"},
        {"hash": "c", "name": "C", "state": 0, "size": 100, "done": 10, "save_path": "/one"},
        {"hash": "d", "name": "D", "state": 1, "size": 100, "done": 100, "save_path": "/two"},
        {"hash": "e", "name": "E", "state": 1, "size": 0, "done": 0, "save_path": "/two"},
        {"hash": "f", "name": "F", "state": 1, "size": 100, "done": 10, "save_path": ""},
    ]

    assert active_download_groups(torrents) == {
        "/one": [
            {"hash": "a", "name": "A"},
            {"hash": "b", "name": "B"},
        ]
    }


def test_active_download_groups_separates_destinations():
    torrents = [
        {"hash": "a", "name": "A", "state": 1, "size": 100, "done": 25, "save_path": "/one"},
        {"hash": "b", "name": "B", "state": 1, "size": 100, "done": 25, "save_path": "/two"},
    ]

    assert set(active_download_groups(torrents)) == {"/one", "/two"}
