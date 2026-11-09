from pathlib import Path

import runtime_update_i18n


def test_update_messages_translate_to_pt_br():
    messages = (
        "Updates",
        "Checking for updates...",
        "You're already on the latest version.",
        "Update Available",
        "Downloading update...",
        "Verifying signature...",
        "Update failed.",
    )
    for source in messages:
        assert runtime_update_i18n.tr_update(source, "pt-BR") != source


def test_update_prefix_translation_preserves_detail():
    assert runtime_update_i18n.tr_update(
        "Network error while contacting Forgejo: boom", "pt-BR"
    ) == "Erro de rede ao contatar o Forgejo: boom"


def test_runtime_installs_update_localization_lazily():
    source = Path("runtime_actions_i18n.py").read_text(encoding="utf-8")
    assert "install_update_localization" in source
    assert "install_localized_runtime_components" in source
