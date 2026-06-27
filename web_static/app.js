let torrentsMap = new Map();
let domRows = new Map(); 
let selectedHashes = new Set();
let currentFilter = 'All';
let currentProfileId = null;
let lastFocusedHash = null;
let lastUserActivity = 0;
let refreshIntervalId = null;

// Virtual Scrolling Config
const ROW_HEIGHT = 40;
const VIEWPORT_BUFFER = 10; 
let visibleTorrents = []; 

// Throttling
let lastProfileFetch = 0;
let detailsTimeout = null;
let csrfToken = null;

async function ensureCsrfToken() {
    if (csrfToken) return csrfToken;
    const res = await fetch('/api/v2/auth/csrf');
    if (res.status === 403) {
        window.location.href = '/login.html';
        throw new Error('Unauthorized');
    }
    const data = await res.json();
    csrfToken = data.csrf_token;
    return csrfToken;
}

async function apiFetch(url, options = {}) {
    const method = (options.method || 'GET').toUpperCase();
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
        const token = await ensureCsrfToken();
        const headers = new Headers(options.headers || {});
        headers.set('X-CSRF-Token', token);
        options.headers = headers;
    }
    const res = await fetch(url, options);
    if (res.status === 403) {
        csrfToken = null;
        window.location.href = '/login.html';
    }
    return res;
}

const els = {
    tbody: () => document.getElementById('torrentTableBody'),
    table: () => document.getElementById('torrentTable'),
    container: () => document.getElementById('tableScrollContainer'),
    contextMenu: () => document.getElementById('contextMenu'),
    selectAllCheck: () => document.getElementById('selectAllCheck'),
    aria: () => document.getElementById('aria-announcer'),
    stretcher: () => document.getElementById('tableStretcher'),
    sidebarNav: () => document.getElementById('sidebarNav'),
    actionsBtn: () => document.getElementById('torrentActionsBtn'),
    refreshRateInput: () => document.getElementById('webRefreshRate')
};

// Initialization
window.addEventListener('DOMContentLoaded', () => {
    const container = els.container();
    if (container) {
        container.addEventListener('scroll', () => {
            window.requestAnimationFrame(renderVirtualRows);
        });
    }

    document.querySelectorAll('.modal').forEach((modal) => {
        modal.setAttribute('inert', '');
        modal.addEventListener('show.bs.modal', () => modal.removeAttribute('inert'));
        modal.addEventListener('hidden.bs.modal', () => modal.setAttribute('inert', ''));
    });

    // Initial fetch
    refreshData(true);
    if (window.fetchProfiles) window.fetchProfiles(); 
    startRefreshLoop();

    // Refresh rate listener
    const rr = els.refreshRateInput();
    if (rr) {
        rr.addEventListener('change', () => {
            startRefreshLoop();
        });
    }

    // Aggressive global context menu suppression and handling for the torrent list area
    document.addEventListener('contextmenu', (e) => {
        const tableContainer = els.container();
        // Check if click is anywhere inside the torrent list container
        const torrentListSection = e.target.closest('.torrent-list-container');
        
        if (torrentListSection) {
            e.preventDefault();
            e.stopPropagation();
            
            const row = e.target.closest('tr[data-hash]');
            showContextMenu(e, row);
            return false;
        }
    }, true);

    const actionsBtn = els.actionsBtn();
    if (actionsBtn) {
        actionsBtn.addEventListener('shown.bs.dropdown', () => {
            // Force focus into the menu to trap NVDA focus
            const menu = document.getElementById('contextMenu');
            if (menu) {
                const firstItem = menu.querySelector('.dropdown-item');
                if (firstItem) {
                    // Short delay ensures Bootstrap animations/positioning don't interfere
                    setTimeout(() => {
                        firstItem.focus();
                        announceToSR("Action menu opened. Use arrow keys to navigate.", true);
                    }, 100);
                }
            }
        });
    }
 
    document.addEventListener('mousedown', (e) => {
        lastUserActivity = Date.now();
    });

    const selectAllCheck = els.selectAllCheck();
    if (selectAllCheck) {
        selectAllCheck.onchange = (e) => {
            if (e.target.checked) {
                visibleTorrents.forEach(t => selectedHashes.add(t.hash));
                announceToSR(`Selected all ${visibleTorrents.length} torrents`);
            } else {
                selectedHashes.clear();
                announceToSR("Selection cleared");
            }
            updateSelectionVisuals();
            updateDetailsDebounced();
        };
    }

    if (actionsBtn) {
        actionsBtn.addEventListener('show.bs.dropdown', (e) => {
            if (selectedHashes.size === 0) {
                e.preventDefault();
                announceToSR("Please select at least one torrent first.", true);
            } else {
                lastUserActivity = Date.now();
                announceToSR("Menu opened", true);
            }
        });
        actionsBtn.addEventListener('hidden.bs.dropdown', () => {
            announceToSR("Menu closed");
            if (lastFocusedHash) {
                setTimeout(() => focusRow(lastFocusedHash, true), 10);
            }
        });
    }

    // Add Torrent Form Handler
    const addTorrentForm = document.getElementById('addTorrentForm');
    if (addTorrentForm) {
        addTorrentForm.onsubmit = async (e) => {
            e.preventDefault();
            const formData = new FormData();
            formData.append('urls', document.getElementById('torrentUrls').value);
            formData.append('savepath', document.getElementById('torrentSavePath').value);
            const files = document.getElementById('torrentFiles').files;
            for (let i = 0; i < files.length; i++) {
                formData.append('torrents', files[i]);
            }
            const res = await apiFetch('/api/v2/torrents/add', { method: 'POST', body: formData });
            if (res.ok) {
                const modal = bootstrap.Modal.getInstance(document.getElementById('addTorrentModal'));
                if (modal) modal.hide();
                e.target.reset();
                refreshData(true); 
            } else {
                alert("Failed to add torrent: " + await res.text());
            }
        };
    }

    document.addEventListener('click', (e) => {
        const link = e.target.closest('.sidebar-link');
        if (!link) return;
        e.preventDefault();
        activateSidebarLink(link, e);
    });

    document.addEventListener('keydown', (e) => {
        // Handle Context Menu via Keyboard (Applications Key or Shift+F10)
        if (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10')) {  
            const inTorrentList = document.activeElement.closest('.torrent-list-container');
            
            if (inTorrentList) {
                e.preventDefault();
                e.stopPropagation();
                const activeRow = document.activeElement.closest('tr[data-hash]');
                const targetRow = activeRow || (lastFocusedHash ? domRows.get(lastFocusedHash) : null);
                showContextMenu(e, targetRow);
                return false;
            }
        }

        if (document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA') return;

        const sidebarNav = els.sidebarNav();
        if (sidebarNav && sidebarNav.contains(document.activeElement)) {
            handleSidebarNavigation(e);
            return;
        }

        lastUserActivity = Date.now();
        if (visibleTorrents.length === 0) return;

        // Arrow Key Navigation Logic
        const navKeys = ['ArrowDown', 'ArrowUp', 'Home', 'End', 'PageUp', 'PageDown'];
        if (navKeys.includes(e.key)) {
            // We already returned early if in INPUT/TEXTAREA or Sidebar.
            // So we can safely capture these keys for the main torrent list.
            e.preventDefault();
            
            let currentIndex = -1;
            const focusedRow = document.activeElement.closest('tr[data-hash]');
            if (focusedRow) {
                currentIndex = visibleTorrents.findIndex(t => t.hash === focusedRow.dataset.hash);
            } else if (lastFocusedHash) {
                currentIndex = visibleTorrents.findIndex(t => t.hash === lastFocusedHash);
            }

            let nextIndex = currentIndex;
            if (e.key === 'ArrowDown') nextIndex++;
            else if (e.key === 'ArrowUp') nextIndex--;
            else if (e.key === 'Home') nextIndex = 0;
            else if (e.key === 'End') nextIndex = visibleTorrents.length - 1;
            else if (e.key === 'PageDown') nextIndex += 10;
            else if (e.key === 'PageUp') nextIndex -= 10;

            if (nextIndex < 0) nextIndex = 0;
            if (nextIndex >= visibleTorrents.length) nextIndex = visibleTorrents.length - 1;

            if (visibleTorrents.length > 0) {
                if (e.shiftKey && currentIndex !== -1) {
                    // Range selection
                    const start = Math.min(currentIndex, nextIndex);
                    const end = Math.max(currentIndex, nextIndex);
                    for (let i = start; i <= end; i++) {
                        selectedHashes.add(visibleTorrents[i].hash);
                    }
                    lastFocusedHash = visibleTorrents[nextIndex].hash;
                    updateSelectionVisuals();
                    focusRow(lastFocusedHash);
                    updateDetailsDebounced();
                } else if (e.ctrlKey) {
                    // Just move focus
                    focusRow(visibleTorrents[nextIndex].hash);
                } else {
                    // Normal navigation
                    navigateToIndex(nextIndex);
                }
            }
            return;
        }

        // Ctrl+A Select All
        if ((e.ctrlKey || e.metaKey) && e.key === 'a') {
            e.preventDefault();
            visibleTorrents.forEach(t => selectedHashes.add(t.hash));
            updateSelectionVisuals();
            announceToSR(`Selected all ${visibleTorrents.length} torrents`);
            return;
        }
    });

    // --- Settings & Remote Prefs Logic ---
    const settingsModal = document.getElementById('settingsModal');
    if (settingsModal) {
        settingsModal.addEventListener('show.bs.modal', loadAppSettings);
    }
    
    const remoteTab = document.getElementById('remote-settings-tab');
    if (remoteTab) {
        remoteTab.addEventListener('shown.bs.tab', loadRemoteSettings);
    }
    
    const settingsForm = document.getElementById('settingsForm');
    if (settingsForm) {
        settingsForm.onsubmit = async (e) => {
            e.preventDefault();
            const fd = new FormData(settingsForm);
            const data = {};
            for (const [key, value] of fd.entries()) {
                data[key] = value;
            }
            const minTray = document.getElementById('minToTray');
            if (minTray) data['min_to_tray'] = !!minTray.checked;
            
            try {
                const res = await apiFetch('/api/v2/app/prefs', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(data)
                });
                if (res.ok) {
                    alert('Settings saved.');
                    const modal = bootstrap.Modal.getInstance(settingsModal);
                    if(modal) modal.hide();
                } else {
                    alert('Error saving settings.');
                }
            } catch (err) { console.error(err); alert('Error saving settings.'); }
        };
    }
    
    const remoteForm = document.getElementById('remoteSettingsForm');
    if (remoteForm) {
        remoteForm.onsubmit = async (e) => {
            e.preventDefault();
            const data = {};
            const inputs = remoteForm.querySelectorAll('input, select');
            inputs.forEach(input => {
                const key = input.name;
                if (!key) return;
                if (input.type === 'checkbox') {
                    data[key] = input.checked; 
                } else if (input.type === 'number') {
                    data[key] = parseFloat(input.value);
                } else {
                    data[key] = input.value;
                }
            });
            
            try {
                const res = await apiFetch('/api/v2/app/remote_prefs', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(data)
                });
                if (res.ok) {
                    alert('Remote settings saved.');
                } else {
                    alert('Error saving remote settings: ' + await res.text());
                }
            } catch (err) { console.error(err); alert('Error saving remote settings.'); }
        };
    }
});

function startRefreshLoop() {
    if (refreshIntervalId) clearInterval(refreshIntervalId);
    let rate = 2000;
    const input = els.refreshRateInput();
    if (input && input.value) rate = parseInt(input.value);
    if (rate < 500) rate = 500;
    refreshIntervalId = setInterval(() => refreshData(), rate);
}

function handleSidebarNavigation(e) {
    const links = Array.from(document.querySelectorAll('.sidebar-link'));
    if (links.length === 0) return;

    let currentIndex = links.indexOf(document.activeElement);
    if (currentIndex === -1) {
        currentIndex = links.findIndex(l => l.classList.contains('active'));
        if (currentIndex === -1) currentIndex = 0;
    }

    let nextIndex = -1;
    if (e.key === 'ArrowDown') nextIndex = (currentIndex + 1) % links.length;
    else if (e.key === 'ArrowUp') nextIndex = (currentIndex - 1 + links.length) % links.length;
    else if (e.key === 'Home') nextIndex = 0;
    else if (e.key === 'End') nextIndex = links.length - 1;
    else if (e.key === 'Enter' || e.key === ' ') { 
        e.preventDefault(); 
        activateSidebarLink(links[currentIndex], e); 
        return; 
    }

    if (nextIndex !== -1) {
        e.preventDefault();
        const target = links[nextIndex];
        // Roving tabindex
        links.forEach(l => l.setAttribute('tabindex', '-1'));
        target.setAttribute('tabindex', '0');
        target.focus();
        
        // Auto-activate on arrow navigation for better UX (like desktop)
        activateSidebarLink(target, e);
    }
}

async function refreshData(force = false) {
    // If user is actively typing or interacting, skip background refresh unless forced
    if (!force && Date.now() - lastUserActivity < 1000) return;
    
    try {
        const isFirstLoad = torrentsMap.size === 0;
        // Get the full list from the client directly, info only provides MainFrame's filtered list
        const res = await fetch('/api/v2/torrents/all');
        if (res.status === 403) { window.location.href = '/login.html'; return; }
        const torrentsList = await res.json();
        
        // Also get stats from info
        const infoRes = await fetch('/api/v2/torrents/info');
        const infoData = await infoRes.json();
        
        syncTorrentsMap(Array.isArray(torrentsList) ? torrentsList : []);
        updateFilteredList();
        renderVirtualRows();
        updateSidebarStats(infoData.stats, infoData.trackers);
        
        const now = Date.now();
        if (now - lastProfileFetch > 30000) { 
            if (window.fetchProfiles) window.fetchProfiles(); 
            lastProfileFetch = now; 
        }

        if (isFirstLoad && visibleTorrents.length > 0) {
            // Focus the first torrent on very first load
            setTimeout(() => focusRow(visibleTorrents[0].hash, true), 100);
        } else if (lastFocusedHash) {
            focusRow(lastFocusedHash, false);
        }
    } catch (e) { console.error("Refresh error", e); }
}

function syncTorrentsMap(newData) {
    const newHashes = new Set(newData.map(t => t.hash));
    for (const h of torrentsMap.keys()) {
        if (!newHashes.has(h)) {
            torrentsMap.delete(h);
            const tr = domRows.get(h);
            if (tr) { tr.remove(); domRows.delete(h); }
            selectedHashes.delete(h);
        }
    }
    newData.forEach(t => torrentsMap.set(t.hash, t));
}

function updateFilteredList() {
    visibleTorrents = Array.from(torrentsMap.values()).filter(t => {
        if (currentFilter === 'All') return true;
        if (currentFilter === 'RSS') return false;
        const pct = t.size > 0 ? (t.done / t.size * 100) : 0;
        if (currentFilter === 'Downloading') return t.state === 1 && (pct < 100);
        if (currentFilter === 'Seeding') return t.state === 1 && (pct >= 100);
        if (currentFilter === 'Finished') return pct >= 100;
        if (currentFilter === 'Stopped') return t.state === 0;
        if (currentFilter === 'Failed') {
            const msg = (t.message || '').toLowerCase();
            return msg && !msg.includes('success') && !msg.includes('ok');
        }
        if (t.tracker_domain === currentFilter) return true;
        return false;
    });
    visibleTorrents.sort((a, b) => a.name.localeCompare(b.name));
    
    const table = els.table();
    if (table) table.setAttribute('aria-rowcount', visibleTorrents.length);
    const stretcher = els.stretcher();
    if (stretcher) stretcher.style.height = (visibleTorrents.length * ROW_HEIGHT) + 'px';
}

function renderVirtualRows() {
    const container = els.container();
    const tbody = els.tbody();
    if (!container || !tbody) return;
    const startIndex = Math.max(0, Math.floor(container.scrollTop / ROW_HEIGHT) - VIEWPORT_BUFFER);
    const endIndex = Math.min(visibleTorrents.length - 1, Math.ceil((container.scrollTop + container.clientHeight) / ROW_HEIGHT) + VIEWPORT_BUFFER);
    const visibleSubList = visibleTorrents.slice(startIndex, endIndex + 1);
    const visibleHashes = new Set(visibleSubList.map(t => t.hash));

    tbody.style.transform = `translateY(${startIndex * ROW_HEIGHT}px)`;

    for (const [hash, tr] of domRows.entries()) {
        if (!visibleHashes.has(hash) && hash !== lastFocusedHash) {
            tr.remove(); domRows.delete(hash);
        }
    }
    visibleSubList.forEach((t, i) => {
        const absoluteIndex = startIndex + i;
        let tr = domRows.get(t.hash);
        if (!tr) { tr = createRowElement(t); domRows.set(t.hash, tr); }
        updateRowData(tr, t, absoluteIndex);
        if (tbody.children[i] !== tr) tbody.insertBefore(tr, tbody.children[i] || null);
    });
    updateSelectionVisuals();
}

function createRowElement(t) {
    const tr = document.createElement('tr');
    tr.dataset.hash = t.hash;
    tr.style.height = ROW_HEIGHT + 'px';
    tr.setAttribute('role', 'row');
    tr.setAttribute('aria-label', t.name);
    tr.tabIndex = -1;
    
    tr.innerHTML = `
        <td role="gridcell"><input type="checkbox" class="row-check" tabindex="-1"></td>
        <td role="gridcell" class="col-name"></td>
        <td role="gridcell" class="col-size text-nowrap"></td>
        <td role="gridcell" class="col-status text-nowrap"></td>
        <td role="gridcell"><div class="progress" aria-hidden="true"><div class="progress-bar"></div></div></td>
        <td role="gridcell" class="col-speed text-nowrap"></td>
    `;
    
    const check = tr.querySelector('.row-check');
    check.onclick = (e) => { e.stopPropagation(); toggleSelection(t.hash); };

    tr.onclick = (e) => { 
        if (e.ctrlKey || e.metaKey) toggleSelection(t.hash); 
        else selectByHash(t.hash); 
    };
    tr.addEventListener('focus', () => { lastFocusedHash = t.hash; });
    return tr;
}

function updateRowData(tr, t, absIndex) {
    const progress = t.size > 0 ? (t.done / t.size * 100).toFixed(1) : 0;
    const isSelected = selectedHashes.has(t.hash);
    const statusText = t.state === 1 ? (progress >= 100 ? 'Seeding' : 'Downloading') : 'Paused';
    const speedText = progress >= 100
        ? `UL: ${fmtSize(t.up_rate)}/s`
        : `DL: ${fmtSize(t.down_rate)}/s | UL: ${fmtSize(t.up_rate)}/s`;
    
    tr.setAttribute('aria-rowindex', absIndex + 1);
    tr.setAttribute('aria-selected', isSelected);
    
    const check = tr.querySelector('.row-check');
    check.checked = isSelected;
    check.setAttribute('aria-label', `Select ${t.name}`);
    
    const nameCell = tr.querySelector('.col-name');
    if (nameCell.textContent !== t.name) { nameCell.textContent = t.name; nameCell.title = t.name; }
    
    const sizeCell = tr.querySelector('.col-size');
    const sz = fmtSize(t.size);
    if (sizeCell.textContent !== sz) sizeCell.textContent = sz;
    
    const statusCell = tr.querySelector('.col-status');
    if (statusCell.textContent !== statusText) statusCell.textContent = statusText;
    
    const bar = tr.querySelector('.progress-bar');
    bar.style.width = progress + '%';
    bar.textContent = progress + '%';
    
    const speedCell = tr.querySelector('.col-speed');
    if (speedCell.textContent !== speedText) speedCell.textContent = speedText;

    tr.classList.toggle('selected', isSelected);
}

function navigateToIndex(index) {
    if (index < 0 || index >= visibleTorrents.length) return;
    const t = visibleTorrents[index];
    selectedHashes.clear();
    selectedHashes.add(t.hash);
    lastFocusedHash = t.hash;
    scrollToRow(t.hash, index);
    renderVirtualRows();
    focusRow(t.hash);
    updateDetailsDebounced();
}

function selectByHash(hash) {
    selectedHashes.clear();
    selectedHashes.add(hash);
    lastFocusedHash = hash;
    updateSelectionVisuals();
    focusRow(hash);
    updateDetailsDebounced();
}

function toggleSelection(hash) {
    if (selectedHashes.has(hash)) selectedHashes.delete(hash);
    else selectedHashes.add(hash);
    lastFocusedHash = hash;
    updateSelectionVisuals();
    updateDetailsDebounced();
}

function focusRow(hash, shouldPerformFocus = true) {
    lastFocusedHash = hash;
    const row = domRows.get(hash) || document.querySelector(`tr[data-hash="${hash}"]`);
    if (row) {
        document.querySelectorAll('#torrentTableBody tr').forEach(tr => tr.tabIndex = -1);
        row.tabIndex = 0;
        if (shouldPerformFocus && document.activeElement !== row) row.focus();
    }
}

function scrollToRow(hash, index) {
    const container = els.container();
    const targetTop = index * ROW_HEIGHT;
    if (targetTop < container.scrollTop) container.scrollTop = targetTop;
    else if (targetTop + ROW_HEIGHT > container.scrollTop + container.clientHeight) {
        container.scrollTop = targetTop - container.clientHeight + ROW_HEIGHT;
    }
}

function updateSelectionVisuals() {
    domRows.forEach((tr, hash) => {
        const isSelected = selectedHashes.has(hash);
        tr.setAttribute('aria-selected', isSelected);
        tr.classList.toggle('selected', isSelected);
        const check = tr.querySelector('.row-check');
        if (check) check.checked = isSelected;
    });
    const allSelected = visibleTorrents.length > 0 && visibleTorrents.every(t => selectedHashes.has(t.hash));
    const selectAllCheck = els.selectAllCheck();
    if (selectAllCheck) { 
        selectAllCheck.checked = allSelected; 
        selectAllCheck.indeterminate = !allSelected && selectedHashes.size > 0; 
    }
}

function updateSidebarStats(stats, trackers) {
    if (!stats) return;
    const trackerList = document.getElementById('trackerList');
    if (trackerList && trackers) {
        trackerList.innerHTML = '';
        Object.entries(trackers).sort((a,b)=>b[1]-a[1]).forEach(([domain, count]) => {
            const isActive = currentFilter === domain;
            const a = document.createElement('a');
            a.href = '#';
            a.className = `sidebar-link ${isActive ? 'active' : ''}`;
            a.dataset.filter = domain;
            a.role = 'option';
            a.setAttribute('aria-selected', isActive);
            a.tabIndex = isActive ? 0 : -1;
            a.textContent = `${domain} (${count})`;
            trackerList.appendChild(a);
        });
    }
}

function activateSidebarLink(link, event) {
    if (!link) return;
    const profileId = link.dataset.profileId;
    const filter = link.dataset.filter;
    if (profileId) switchProfile(profileId, event);
    else if (filter) setFilter(filter, event);
}

function setFilter(f, event) {
    if (event) event.preventDefault();
    currentFilter = f;
    selectedHashes.clear();
    lastFocusedHash = null;
    
    document.querySelectorAll('.sidebar-link').forEach(l => {
        const isActive = l.dataset.filter === f;
        l.classList.toggle('active', isActive);
        l.setAttribute('aria-selected', isActive);
        l.tabIndex = isActive ? 0 : -1;
    });

    updateFilteredList();
    const container = els.container();
    if (container) container.scrollTop = 0;
    renderVirtualRows();
    if (visibleTorrents.length > 0) focusRow(visibleTorrents[0].hash, true);
}

window.fetchProfiles = async function() {
    try {
        const res = await fetch('/api/v2/profiles');
        const data = await res.json();
        const list = document.getElementById('profileList');
        if (!list) return;
        list.innerHTML = '';
        currentProfileId = data.current_id;
        for (const id in data.profiles) {
            const p = data.profiles[id];
            const isActive = id === data.current_id;
            const a = document.createElement('a');
            a.href = '#';
            a.className = `sidebar-link ${isActive ? 'active' : ''}`;
            a.dataset.profileId = id;
            a.role = 'option';
            a.setAttribute('aria-selected', isActive);
            a.tabIndex = isActive ? 0 : -1;
            a.textContent = `${p.name} (${p.type})`;
            list.appendChild(a);
        }
    } catch (e) {
        console.error("fetchProfiles failed:", e);
    }
}

async function switchProfile(id, event) {
    if (event) event.preventDefault();
    if (id === currentProfileId) return;
    announceToSR("Switching client profile...");
    const fd = new FormData(); fd.append('id', id);
    const res = await apiFetch('/api/v2/profiles/switch', { method: 'POST', body: fd });
    if (res.ok) { 
        selectedHashes.clear(); 
        lastFocusedHash = null; 
        lastUserActivity = 0; 
        currentProfileId = id; 
        torrentsMap.clear(); 
        domRows.forEach(tr => tr.remove());
        domRows.clear();
        visibleTorrents = [];
        
        // Update Sidebar visual state immediately
        document.querySelectorAll('.sidebar-link[data-profile-id]').forEach(l => {
            const isActive = l.dataset.profileId === id;
            l.classList.toggle('active', isActive);
            l.setAttribute('aria-selected', isActive);
            l.tabIndex = isActive ? 0 : -1;
        });

        lastProfileFetch = 0; // Force re-fetch next cycle
        if (window.fetchProfiles) window.fetchProfiles(); // Or just call it now
        
        setTimeout(() => refreshData(true), 500); 
    }
}

function updateDetailsDebounced() { if (detailsTimeout) clearTimeout(detailsTimeout); detailsTimeout = setTimeout(updateDetails, 200); }

function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

async function updateDetails() {
    const detailPane = document.getElementById('details-general');
    if (selectedHashes.size === 0) { detailPane.innerHTML = '<p>Select a torrent.</p>'; return; }
    if (selectedHashes.size > 1) { detailPane.innerHTML = `<p>${selectedHashes.size} torrents selected.</p>`; return; }
    const hash = Array.from(selectedHashes)[0];
    const t = torrentsMap.get(hash);
    if (!t) return;
    // Escape torrent-supplied fields (name/hash/save_path) to prevent DOM XSS.
    detailPane.innerHTML = `<h3 class="fs-5">${escapeHtml(t.name)}</h3><p>Size: ${fmtSize(t.size)}<br>Hash: ${escapeHtml(t.hash)}<br>Path: ${escapeHtml(t.save_path || 'N/A')}</p>`;
}

async function doAction(action, deleteFiles = false) {
    if (selectedHashes.size === 0) return;
    if (action === 'delete' && !confirmDeleteAction(deleteFiles)) return;
    const formData = new FormData();
    formData.append('hashes', Array.from(selectedHashes).join('|'));
    if (deleteFiles) formData.append('deleteFiles', 'true');
    try {
        const res = await apiFetch(`/api/v2/torrents/${action}`, { method: 'POST', body: formData });
        if (res.ok) {
            hideContextMenu();
            setTimeout(() => refreshData(true), 100);
            return;
        }
        const message = (await res.text()) || `Failed to ${action} torrent(s).`;
        announceToSR(message, true);
        alert(message);
    } catch (err) {
        const message = `Failed to ${action} torrent(s): ${err?.message || err}`;
        announceToSR(message, true);
        alert(message);
    }
}

function confirmDeleteAction(deleteFiles) {
    const count = selectedHashes.size;
    const label = count === 1 ? 'torrent' : 'torrents';
    const dataText = deleteFiles ? ' and delete downloaded data' : '';
    return window.confirm(`Remove ${count} ${label}${dataText}?`);
}

function fmtSize(bytes) {
    if (!bytes || bytes === 0) return "0 B";
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return parseFloat((bytes / Math.pow(1024, i)).toFixed(2)) + ' ' + units[i];
}

async function logout() { await apiFetch('/api/v2/auth/logout', { method: 'POST' }); window.location.href = '/login.html'; }

function announceToSR(m, assertive = false) {
    const a = els.aria();
    if (a) {
        a.setAttribute('aria-live', assertive ? 'assertive' : 'polite');
        a.textContent = '';
        setTimeout(() => { a.textContent = m; }, 50);
    }
}

function applyTheme(theme) {
    if (theme === 'dark') { document.body.classList.add('dark-mode'); localStorage.setItem('web-theme', 'dark'); } 
    else { document.body.classList.remove('dark-mode'); localStorage.setItem('web-theme', 'light'); }
}

function showContextMenu(e, anchorRow = null) {
    const row = anchorRow || (e?.target && e.target.closest ? e.target.closest('tr[data-hash]') : null);
    if (row && row.dataset && row.dataset.hash && !selectedHashes.has(row.dataset.hash)) {
        selectByHash(row.dataset.hash);
    }

    const btn = els.actionsBtn();
    if (btn) {
        btn.focus();
        const dd = bootstrap.Dropdown.getOrCreateInstance(btn);
        dd.show();
    }
}

function hideContextMenu() { 
    const btn = els.actionsBtn();
    if (btn) {
        const dd = bootstrap.Dropdown.getInstance(btn);
        if (dd) dd.hide();
    }
}

function toggleSelectAllBtn() {
    const isAllSelected = visibleTorrents.length > 0 && visibleTorrents.every(t => selectedHashes.has(t.hash));
    if (isAllSelected) {
        selectedHashes.clear();
        announceToSR("Selection cleared");
    } else {
        visibleTorrents.forEach(t => selectedHashes.add(t.hash));
        announceToSR(`Selected all ${visibleTorrents.length} torrents`);
    }
    updateSelectionVisuals();
    updateDetailsDebounced();
}

function copyToClipboard(type) {
    if (selectedHashes.size === 0) return;
    let text = "";
    if (type === 'hash') {
        text = Array.from(selectedHashes).join('\n');
    } else {
        text = Array.from(selectedHashes).map(h => `magnet:?xt=urn:btih:${h}`).join('\n');
    }
    navigator.clipboard.writeText(text).then(() => {
        announceToSR("Copied to clipboard");
    });
    hideContextMenu();
}

async function loadAppSettings() {
    try {
        const res = await fetch('/api/v2/app/prefs');
        const prefs = await res.json();
        const form = document.getElementById('settingsForm');
        if (!form) return;
        
        // Reset form
        form.reset();
        
        // Populate
        for (const key in prefs) {
            const el = form.elements[key];
            if (el) {
                if (el.type === 'checkbox') el.checked = prefs[key];
                else el.value = prefs[key];
            }
        }
        if (prefs.min_to_tray !== undefined) {
            const cb = document.getElementById('minToTray');
            if(cb) cb.checked = prefs.min_to_tray;
        }
        
    } catch (e) { console.error("Load app settings error", e); }
}

async function loadRemoteSettings() {
    const container = document.getElementById('remoteSettingsFields');
    if (!container) return;
    container.innerHTML = '<p class="text-muted">Loading...</p>';
    
    try {
        const res = await fetch('/api/v2/app/remote_prefs');
        const data = await res.json();
        
        if (!data.prefs) {
            container.innerHTML = '<div class="alert alert-info">No remote settings available (or Local client active).</div>';
            return;
        }
        
        container.innerHTML = '';
        
        // Sort keys for consistent display
        const keys = Object.keys(data.prefs).sort();
        
        keys.forEach(key => {
            const val = data.prefs[key];
            const type = typeof val;
            
            const col = document.createElement('div');
            col.className = 'col-md-6 mb-3';
            
            const label = document.createElement('label');
            label.className = 'form-label small text-muted text-uppercase';
            label.textContent = key.replace(/_/g, ' ');
            label.htmlFor = 'rem_' + key;
            
            let input;
            if (type === 'boolean' || (val === 0 || val === 1) && (key.includes('enable') || key.includes('check'))) {
                col.className = 'col-md-6 mb-3 form-check ps-5 pt-4';
                input = document.createElement('input');
                input.type = 'checkbox';
                input.className = 'form-check-input';
                input.checked = !!val;
                label.className = 'form-check-label';
                col.appendChild(input);
                col.appendChild(label);
            } else {
                input = document.createElement('input');
                input.className = 'form-control form-control-sm';
                if (type === 'number') input.type = 'number';
                else input.type = 'text';
                input.value = val;
                
                col.appendChild(label);
                col.appendChild(input);
            }
            
            input.id = 'rem_' + key;
            input.name = key;
            
            container.appendChild(col);
        });
        
    } catch (e) {
        console.error("Load remote settings error", e);
        container.innerHTML = '<div class="alert alert-danger">Failed to load settings.</div>';
    }
}
