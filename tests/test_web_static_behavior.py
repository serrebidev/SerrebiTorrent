from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_web_torrent_rows_show_upload_speed_for_seeding():
    script = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")

    assert "progress >= 100" in script
    assert "UL: ${fmtSize(t.up_rate)}/s" in script
    assert "DL: ${fmtSize(t.down_rate)}/s | UL: ${fmtSize(t.up_rate)}/s" in script


def test_web_delete_actions_confirm_and_report_failures():
    script = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")

    assert "confirmDeleteAction(deleteFiles)" in script
    assert "window.confirm(`Remove ${count} ${label}${dataText}?`)" in script
    assert "announceToSR(message, true)" in script
    assert "alert(message)" in script
