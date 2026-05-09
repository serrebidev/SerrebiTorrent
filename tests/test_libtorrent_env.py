import libtorrent_env


def test_prepare_libtorrent_dlls_handles_modules_without_spec(monkeypatch):
    monkeypatch.setattr(libtorrent_env.sys, "platform", "win32")
    monkeypatch.setattr(libtorrent_env, "_BOOTSTRAPPED", False)

    def broken_find_spec(name):
        raise ValueError(f"{name}.__spec__ is not set")

    monkeypatch.setattr(libtorrent_env.importlib.util, "find_spec", broken_find_spec)

    libtorrent_env.prepare_libtorrent_dlls()

    assert libtorrent_env._BOOTSTRAPPED is True
