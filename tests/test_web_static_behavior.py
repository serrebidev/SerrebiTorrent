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
    assert "'Remove {count} torrent and delete downloaded data?'" in script
    assert "window.confirm(translate(key).replace('{count}', String(count)))" in script
    assert "const key = count === 1 ? 'Remove {count} torrent?' : 'Remove {count} torrents?';" in script
    assert "announceToSR(message, true)" in script
    assert "alert(message)" in script


def test_web_modal_controls_have_explicit_accessible_labels():
    markup = (ROOT / "web_static" / "index.html").read_text(encoding="utf-8")

    expected = [
        'aria-labelledby="addProfileModalLabel"',
        'for="profName"',
        'for="profType"',
        'for="profUrl"',
        'for="profUser"',
        'for="profPass"',
        'aria-labelledby="addTorrentModalLabel"',
        'for="torrentUrls"',
        'for="torrentFiles"',
        'for="torrentSavePath"',
        'aria-labelledby="settingsModalLabel"',
        'for="settingsDownloadPath"',
        'for="settingsRssInterval"',
        'for="settingsDlLimit"',
        'for="settingsUlLimit"',
        'for="webTheme"',
        'for="webRefreshRate"',
    ]

    for token in expected:
        assert token in markup


def test_web_status_filters_use_single_delegated_activation_path():
    markup = (ROOT / "web_static" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")

    assert 'onclick="setFilter(' not in markup
    assert "const link = e.target.closest('.sidebar-link');" in script
    assert "activateSidebarLink(link, e);" in script



def test_web_profile_switch_reports_http_and_network_failures():
    script = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")

    start = script.index("async function switchProfile")
    end = script.index("function updateDetailsDebounced", start)
    block = script[start:end]

    assert "if (!res.ok)" in block
    assert "await res.text()" in block
    assert "announceToSR(message, true)" in block
    assert "alert(message)" in block
    assert "catch (err)" in block



def test_web_clipboard_failures_are_announced_and_visible():
    script = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")

    start = script.index("async function copyToClipboard")
    end = script.index("async function loadAppSettings", start)
    block = script[start:end]

    assert "try {" in block
    assert "} catch (err) {" in block
    assert "announceToSR(message, true)" in block
    assert "alert(message)" in block
    assert "Failed to copy to clipboard." in block


def test_web_settings_load_failures_are_announced_and_visible():
    script = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")

    start = script.index("async function loadAppSettings")
    end = script.index("async function loadRemoteSettings", start)
    block = script[start:end]

    assert "Failed to load settings." in block
    assert "announceToSR(message, true)" in block
    assert "alert(message)" in block


def test_web_profile_load_failure_is_announced_once_until_success():
    script = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")

    start = script.index("window.fetchProfiles = async function()")
    end = script.index("async function switchProfile", start)
    block = script[start:end]

    assert "list.dataset.loadError !== 'true'" in block
    assert "list.dataset.loadError = 'true'" in block
    assert "delete list.dataset.loadError" in block
    assert "announceToSR(message, true)" in block



def test_remote_settings_load_failure_is_accessible():
    script = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")

    start = script.index("async function loadRemoteSettings")
    # loadRemoteSettings is the last function in app.js; slice to end of file
    block = script[start:]

    assert "alertBox.setAttribute('role', 'alert')" in block
    assert "announceToSR(message, true)" in block
    assert "Failed to load settings." in block



def test_web_form_actions_and_refresh_failures_are_announced():
    script = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")

    assert 'const rawMessage = (await res.text()) || "Torrent added."' in script
    assert 'const message = rawMessage === "Ok." ? translate("Torrent added.") : translate(rawMessage);' in script
    assert 'announceToSR(message, rawMessage.includes("duplicate"))' in script
    assert "Failed to add torrent:" in script
    assert "announceToSR(message, true)" in script
    assert "const message = (window.SerrebiI18n?.t || ((value) => value))('Settings saved.');" in script
    assert "const message = (window.SerrebiI18n?.t || ((value) => value))('Error saving settings.');" in script
    assert "const message = (window.SerrebiI18n?.t || ((value) => value))('Remote settings saved.');" in script
    assert "(window.SerrebiI18n?.t || ((value) => value))('Error saving remote settings.')" in script
    assert "let refreshErrorActive = false;" in script
    assert "if (!refreshErrorActive)" in script
    assert "refreshErrorActive = false;" in script



def test_web_add_profile_form_posts_and_reports_failures():
    script = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")

    assert "document.getElementById('addProfileForm')" in script
    assert "apiFetch('/api/v2/profiles/add'" in script
    assert "formData.append('name'" in script
    assert "formData.append('type'" in script
    assert "formData.append('url'" in script
    assert "formData.append('user'" in script
    assert "formData.append('password'" in script
    assert "announceToSR('Profile created.')" in script
    assert "announceToSR(message, true)" in script
    assert "if (window.fetchProfiles) await window.fetchProfiles()" in script



def test_web_clipboard_handles_missing_api_synchronously():
    script = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
    start = script.index("async function copyToClipboard")
    block = script[start: start + 1300]

    assert "if (!navigator.clipboard || typeof navigator.clipboard.writeText !== 'function')" in block
    assert "await navigator.clipboard.writeText(text)" in block
    assert "} catch (err) {" in block
    assert "} finally {" in block
    assert "hideContextMenu();" in block



def test_web_partial_torrent_add_is_announced_and_visible():
    script = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
    assert "if (res.status === 207)" in script
    assert 'announceToSR(message, true);' in script
    assert 'alert(message);' in script
    assert "Check the torrent list before retrying." not in script



def test_web_select_all_button_exposes_toggle_state():
    markup = (ROOT / "web_static" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")

    assert 'id="selectAllBtn"' in markup
    assert 'aria-pressed="false"' in markup
    assert "selectAllBtn.setAttribute('aria-pressed', allSelected ? 'true' : 'false')" in script



def test_web_settings_tabs_have_explicit_tabpanel_relationships():
    markup = (ROOT / "web_static" / "index.html").read_text(encoding="utf-8")

    assert 'id="settings-app" role="tabpanel" aria-labelledby="app-settings-tab"' in markup
    assert 'id="settings-remote" role="tabpanel" aria-labelledby="remote-settings-tab"' in markup
    assert 'id="settings-web" role="tabpanel" aria-labelledby="web-settings-tab"' in markup


def test_web_refresh_rate_is_bounded_and_persisted():
    from pathlib import Path

    html = Path("web_static/index.html").read_text(encoding="utf-8")
    js = Path("web_static/app.js").read_text(encoding="utf-8")

    assert 'id="webRefreshRate"' in html
    assert 'min="500"' in html
    assert 'max="60000"' in html
    assert "localStorage.getItem('web-refresh-rate')" in js
    assert "localStorage.setItem('web-refresh-rate'" in js


def test_remote_profile_form_exposes_field_semantics():
    from pathlib import Path
    html = Path("web_static/index.html").read_text(encoding="utf-8")
    assert 'id="profUrl"' in html and 'type="text"' in html and 'autocomplete="url"' in html
    assert 'id="profUser"' in html and 'autocomplete="username"' in html
    assert 'id="profPass"' in html and 'autocomplete="current-password"' in html

def test_web_theme_is_restored_from_local_storage():
    from pathlib import Path
    js = Path("web_static/app.js").read_text(encoding="utf-8")
    assert "localStorage.getItem('web-theme')" in js
    assert "themeSelect.value = savedTheme" in js


def test_remote_settings_preserve_structured_values_as_json():
    from pathlib import Path
    js = Path("web_static/app.js").read_text(encoding="utf-8")
    assert "remoteForm.querySelectorAll('input, select, textarea')" in js
    assert "input.dataset.valueType === 'json'" in js
    assert "data[key] = JSON.parse(input.value)" in js
    assert "input = document.createElement('textarea')" in js
    assert "input.dataset.valueType = 'json'" in js
    assert "input.value = JSON.stringify(val, null, 2)" in js
    assert "Invalid JSON in remote settings." in js


def test_web_bulk_actions_batch_server_limited_selections():
    script = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")

    start = script.index("async function doAction")
    end = script.index("function confirmDeleteAction", start)
    block = script[start:end]

    assert "const batchSize = 100;" in block
    assert "hashes.slice(offset, offset + batchSize)" in block
    assert "formData.append('hashes', batch.join('|'))" in block
    assert "completed += batch.length" in block
    assert "were already processed" in block


def test_web_bulk_action_partial_failure_refreshes_processed_state():
    script = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
    start = script.index("async function doAction")
    end = script.index("function confirmDeleteAction", start)
    block = script[start:end]

    assert block.count("if (completed > 0)") >= 2
    assert block.count("await refreshData(true);") >= 2


def test_web_bulk_delete_reports_http_207_as_partial_failure():
    script = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")
    start = script.index("async function doAction")
    end = script.index("function confirmDeleteAction", start)
    block = script[start:end]

    partial = block.index("if (res.status === 207)")
    generic_failure = block.index("if (!res.ok)")
    completed = block.index("completed += batch.length")

    assert partial < generic_failure < completed
    assert "await refreshData(true);" in block[partial:generic_failure]
    assert "announceToSR(message, true);" in block[partial:generic_failure]


def test_web_torrent_and_profile_fields_avoid_text_autocorrection():
    markup = (ROOT / "web_static" / "index.html").read_text(encoding="utf-8")

    assert 'id="torrentUrls" rows="3" autocomplete="off" autocapitalize="none" spellcheck="false"' in markup
    assert 'id="torrentFiles" accept=".torrent,application/x-bittorrent" multiple' in markup
    assert 'id="torrentSavePath" autocomplete="off" spellcheck="false"' in markup
    assert 'id="profUrl"' in markup and 'autocapitalize="none" spellcheck="false"' in markup
    assert 'id="profUser"' in markup and 'spellcheck="false"' in markup


def test_web_progress_cell_exposes_percentage_to_screen_readers():
    script = (ROOT / "web_static" / "app.js").read_text(encoding="utf-8")

    assert 'class="col-progress"' in script
    assert "progressCell.setAttribute(" in script
    assert "'aria-label'" in script
    assert "`${(window.SerrebiI18n?.t || ((value) => value))('Progress')} ${progress}%`" in script
    assert 'class="progress" aria-hidden="true"' in script


def test_web_toolbar_actions_have_contextual_accessible_names():
    page = (ROOT / "web_static" / "index.html").read_text(encoding="utf-8")
    for label in (
        "Refresh torrent list",
        "Start selected torrents",
        "Pause selected torrents",
        "Remove selected torrents",
    ):
        assert f'aria-label="{label}"' in page
        assert f'title="{label}"' in page


def test_web_torrent_name_filter_combines_with_sidebar_filters():
    index = Path("web_static/index.html").read_text(encoding="utf-8")
    app = Path("web_static/app.js").read_text(encoding="utf-8")

    assert 'id="torrentNameFilter"' in index
    assert 'type="search"' in index
    assert 'aria-label="Search"' in index
    assert "let torrentNameQuery = '';" in app
    assert "torrentNameFilter.addEventListener('input'" in app
    assert "if (!matchesFilter) return false;" in app
    assert "includes(torrentNameQuery)" in app


def test_web_torrent_name_filter_has_keyboard_shortcuts():
    app = Path("web_static/app.js").read_text(encoding="utf-8")

    assert "e.key === '/'" in app
    assert "torrentNameFilter.focus()" in app
    assert "torrentNameFilter.select()" in app
    assert "document.activeElement === torrentNameFilter && e.key === 'Escape'" in app
    assert "torrentNameFilter.dispatchEvent(new Event('input'" in app


def test_web_ctrl_shift_a_clears_selection():
    app = Path("web_static/app.js").read_text(encoding="utf-8")

    assert "e.shiftKey" in app
    assert "selectedHashes.clear();" in app
    assert "('Selection cleared')" in app
    assert "e.key.toLowerCase() === 'a'" in app

def test_web_announces_newly_completed_downloads_without_initial_false_positive():
    app = Path("web_static/app.js").read_text(encoding="utf-8")
    index = Path("web_static/index.html").read_text(encoding="utf-8")
    server = Path("web_server.py").read_text(encoding="utf-8")

    assert "let announceDownloadComplete = false;" in app
    assert "void loadCompletionAnnouncementPreference();" in app
    assert "if (!isFirstLoad)" in app
    assert "previousComplete" in app
    assert "currentComplete" in app
    assert "Download complete: {name}" in app
    assert "{count} downloads completed." in app
    assert 'id="announceDownloadComplete"' in index
    assert "'announce_download_complete'" in server


def test_web_torrent_table_supports_accessible_sorting():
    index = Path("web_static/index.html").read_text(encoding="utf-8")
    app = Path("web_static/app.js").read_text(encoding="utf-8")

    for key in ("name", "size", "status", "progress", "speed"):
        assert f'data-sort-key="{key}"' in index
    assert 'aria-sort="ascending"' in index
    assert "let torrentSortKey = 'name';" in app
    assert "let torrentSortAscending = true;" in app
    assert "function updateSortHeaders()" in app
    assert "'aria-sort'" in app
    assert "speed: (torrent) =>" in app
    assert "progress: progressValue" in app
    assert "Sorted by {label}." in app


def test_web_detail_tables_support_click_header_sorting():
    app = Path("web_static/app.js").read_text(encoding="utf-8")

    assert "const detailSortState = {" in app
    assert "function applyDetailSort(kind, rows, valueFor)" in app
    assert "function buildDetailHeader(kind, columns, rerender)" in app
    assert "button.dataset.detailSortKey = key;" in app
    assert "'aria-sort'" in app
    for kind in ("files", "peers", "trackers"):
        assert f"buildDetailHeader('{kind}', [" in app
        assert f"applyDetailSort('{kind}', {kind}, " in app
    for key in ("down_rate", "up_rate", "priority"):
        assert f"{key}: (" in app


def test_web_actions_can_start_and_stop_all_loaded_torrents():
    index = Path("web_static/index.html").read_text(encoding="utf-8")
    app = Path("web_static/app.js").read_text(encoding="utf-8")

    assert "doActionAll('resume', 'Start All')" in index
    assert "doActionAll('pause', 'Stop All')" in index
    assert "function doActionAll(action, actionLabel)" in app
    assert "torrentsMap.keys()" in app
    assert "hashesOverride" in app
    assert "const hashes = hashesOverride ? Array.from(hashesOverride) : Array.from(selectedHashes);" in app
