from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_web_torrent_rows_show_upload_speed_for_seeding():
    script = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")

    assert "progress >= 100" in script
    assert "UL: ${fmtSize(t.up_rate)}/s" in script
    assert "DL: ${fmtSize(t.down_rate)}/s | UL: ${fmtSize(t.up_rate)}/s" in script
