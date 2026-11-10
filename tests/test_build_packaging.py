import ast
import json
import subprocess
from pathlib import Path

import pytest

from tools import audit_bundle, select_libtorrent_wheel


ROOT = Path(__file__).resolve().parents[1]

# libtorrent names the code reaches for only behind hasattr/getattr, because
# they exist in some libtorrent releases and not others. Everything else must
# exist in the libtorrent the build actually ships.
OPTIONAL_LIBTORRENT_ATTRIBUTES = frozenset(
    {
        "remove_flags_t",
        "resume_data_flags_t",
        "options_t",
        "save_resume_flags_t",
        "make_magnet_uri",
        "write_resume_data_buf",
        "write_resume_data",
    }
)


def test_spec_packages_native_libtorrent_without_broad_dependency_collection():
    spec = (ROOT / "SerrebiTorrent.spec").read_text(encoding="utf-8")

    assert "binaries = [(os.path.abspath(libtorrent_spec.origin), '.')]" in spec
    assert "hiddenimports=['libtorrent']" in spec
    assert "collect_submodules" not in spec
    assert "libcrypto-1_1" not in spec
    assert "libssl-3-x64.dll" not in spec


def test_build_tools_are_not_runtime_requirements():
    runtime = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    build = (ROOT / "requirements-build.txt").read_text(encoding="utf-8").lower()

    assert "pyinstaller" not in runtime
    assert "pywin32" not in runtime
    assert "pyinstaller" in build


def test_native_build_policy_uses_local_windows_ssh_linux_and_actions_macos():
    batch = (ROOT / "build_exe.bat").read_text(encoding="utf-8")
    remote = (ROOT / "tools/build_linux_remote.ps1").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "%LOCALAPPDATA%\\Programs\\Python\\Launcher\\py.exe" in batch
    assert "wsl-build" in remote
    assert "debian:trixie" in remote
    assert "runs-on: macos-15" in workflow
    assert "windows-latest" not in workflow
    assert "ubuntu-latest" not in workflow
    assert "forgejo/upload-artifact@v4" in workflow
    assert "git.serrebiradio.com" in workflow
    assert "FORGEJO_TOKEN" in workflow
    assert "gh release upload" not in workflow


def test_every_libtorrent_attribute_used_exists_in_the_shipped_libtorrent():
    libtorrent = pytest.importorskip("libtorrent")

    # lt.version was removed in libtorrent 2.1 but stayed in clients.py, so the
    # packaged app raised AttributeError on startup. The frozen self-test only
    # touched lt.__version__ and could not see it.
    used = set()
    for source in ROOT.glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8", errors="ignore"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "lt"
            ):
                used.add(node.attr)

    assert used, "expected the code to reference libtorrent as lt"

    missing = sorted(
        name
        for name in used - OPTIONAL_LIBTORRENT_ATTRIBUTES
        if not hasattr(libtorrent, name)
    )
    assert not missing, (
        f"libtorrent {libtorrent.__version__} has no {missing}. "
        "Guard the access and add it to OPTIONAL_LIBTORRENT_ATTRIBUTES, "
        "or use the supported name."
    )


def test_shell_scripts_keep_lf_endings_through_git_archive():
    # build_linux_remote.ps1 ships the source with git archive, which applies
    # the working-tree eol conversion. CRLF here makes bash reject line 2 of
    # build_linux.sh with "set: pipefail: invalid option name".
    scripts = sorted(path.as_posix() for path in ROOT.glob("**/*.sh"))
    assert scripts, "expected at least one shell script in the repository"

    for script in scripts:
        relative = Path(script).relative_to(ROOT).as_posix()
        attribute = subprocess.run(
            ["git", "check-attr", "eol", "--", relative],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert attribute.endswith("eol: lf"), attribute


def test_remote_linux_command_keeps_its_error_handling():
    remote = (ROOT / "tools/build_linux_remote.ps1").read_text(encoding="utf-8")

    # A login shell lets the remote profile print its environment, and a
    # multi-line command string loses the quoting that keeps "set" attached to
    # its options.
    assert "bash -lc" not in remote
    assert "set -Eeuo pipefail; " in remote


def test_linux_bundle_strips_native_debug_symbols():
    spec = (ROOT / "SerrebiTorrent.spec").read_text(encoding="utf-8")

    assert "strip=sys.platform.startswith('linux')" in spec


def test_select_libtorrent_wheel_prefers_stable_version_then_stamp(tmp_path):
    names = [
        "libtorrent-2.0.14+20260815-cp314-cp314-win_amd64.whl",
        "libtorrent-2.1.1+20260814-cp314-cp314-win_amd64.whl",
        "libtorrent-2.1.1+20260816-cp314-cp314-win_amd64.whl",
        "libtorrent-2.2.0+20260816-cp313-cp313-win_amd64.whl",
    ]
    for name in names:
        (tmp_path / name).touch()

    path, version = select_libtorrent_wheel.select_wheel(
        tmp_path, "cp314", "win_amd64"
    )

    assert path.name == names[2]
    assert version == "2.1.1"


def _add_translation_assets(bundle):
    locales = bundle / "locales"
    web_locales = bundle / "web_static" / "locales"
    locales.mkdir(parents=True, exist_ok=True)
    web_locales.mkdir(parents=True, exist_ok=True)
    (locales / "pt-BR.po").write_text(
        'msgid ""\\nmsgstr ""\\n"Language: pt-BR\\\\n"\\n',
        encoding="utf-8",
    )
    (web_locales / "pt-BR.json").write_text(
        json.dumps({
            "language": "pt-BR",
            "name": "Português (Brasil)",
            "translations": {audit_bundle.REQUIRED_WEB_MESSAGES[0]: "Traduzido"},
        }),
        encoding="utf-8",
    )
    (web_locales / "index.json").write_text(
        '{"languages":[{"code":"pt-BR","name":"Português (Brasil)"}]}\n',
        encoding="utf-8",
    )


def test_bundle_audit_rejects_legacy_openssl_on_windows(tmp_path, monkeypatch):
    (tmp_path / "libtorrent.cp314-win_amd64.pyd").touch()
    _add_translation_assets(tmp_path)
    (tmp_path / "libcrypto-1_1.dll").touch()
    monkeypatch.setattr(audit_bundle.sys, "platform", "win32")
    monkeypatch.setattr(
        audit_bundle.sys, "argv", ["audit_bundle.py", str(tmp_path)]
    )

    with pytest.raises(SystemExit, match="Legacy OpenSSL"):
        audit_bundle.main()


def test_bundle_audit_accepts_macos_app_symlinked_extension(tmp_path, monkeypatch):
    # PyInstaller keeps the real binary in Contents/Frameworks and symlinks it
    # into Contents/Resources, which read as two libtorrent extensions.
    frameworks = tmp_path / "Contents" / "Frameworks"
    resources = tmp_path / "Contents" / "Resources"
    frameworks.mkdir(parents=True)
    resources.mkdir(parents=True)
    extension = frameworks / "libtorrent.cpython-314-darwin.so"
    extension.write_bytes(b"native")
    _add_translation_assets(resources)
    try:
        (resources / extension.name).symlink_to(extension)
    except (OSError, NotImplementedError):
        pytest.skip("this platform does not allow creating symlinks here")

    monkeypatch.setattr(audit_bundle.sys, "platform", "darwin")
    monkeypatch.setattr(
        audit_bundle.sys, "argv", ["audit_bundle.py", str(tmp_path)]
    )

    assert audit_bundle.main() == 0


def test_bundle_audit_still_rejects_two_real_extensions(tmp_path, monkeypatch):
    frameworks = tmp_path / "Contents" / "Frameworks"
    resources = tmp_path / "Contents" / "Resources"
    frameworks.mkdir(parents=True)
    resources.mkdir(parents=True)
    (frameworks / "libtorrent.cpython-314-darwin.so").write_bytes(b"native")
    (resources / "libtorrent.cpython-314-darwin.so").write_bytes(b"native")

    monkeypatch.setattr(audit_bundle.sys, "platform", "darwin")
    monkeypatch.setattr(
        audit_bundle.sys, "argv", ["audit_bundle.py", str(tmp_path)]
    )

    with pytest.raises(SystemExit, match="Expected one bundled libtorrent"):
        audit_bundle.main()


def test_bundle_audit_allows_dist_info_wheel_metadata(tmp_path, monkeypatch):
    (tmp_path / "libtorrent.cp314-win_amd64.pyd").touch()
    _add_translation_assets(tmp_path)
    metadata = tmp_path / "flask-3.1.3.dist-info"
    metadata.mkdir()
    (metadata / "WHEEL").touch()
    monkeypatch.setattr(audit_bundle.sys, "platform", "win32")
    monkeypatch.setattr(
        audit_bundle.sys, "argv", ["audit_bundle.py", str(tmp_path)]
    )

    assert audit_bundle.main() == 0
