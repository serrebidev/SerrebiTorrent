import libtorrent_env


def test_prepare_libtorrent_dlls_handles_modules_without_spec(monkeypatch):
    monkeypatch.setattr(libtorrent_env.sys, "platform", "win32")
    monkeypatch.setattr(libtorrent_env, "_BOOTSTRAPPED", False)

    def broken_find_spec(name):
        raise ValueError(f"{name}.__spec__ is not set")

    monkeypatch.setattr(libtorrent_env.importlib.util, "find_spec", broken_find_spec)

    libtorrent_env.prepare_libtorrent_dlls()

    assert libtorrent_env._BOOTSTRAPPED is True


def test_prepare_libtorrent_dlls_retains_add_directory_handles(monkeypatch):
    monkeypatch.setattr(libtorrent_env.sys, "platform", "win32")
    monkeypatch.setattr(libtorrent_env, "_BOOTSTRAPPED", False)
    monkeypatch.setattr(libtorrent_env, "_DLL_DIRECTORY_HANDLES", [])
    monkeypatch.setattr(libtorrent_env.importlib.util, "find_spec", lambda name: None)
    handles = []

    def add_dll_directory(_path):
        handle = object()
        handles.append(handle)
        return handle

    monkeypatch.setattr(libtorrent_env.os, "add_dll_directory", add_dll_directory, raising=False)

    libtorrent_env.prepare_libtorrent_dlls()

    assert libtorrent_env._DLL_DIRECTORY_HANDLES == handles
    assert handles
