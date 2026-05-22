import os
from urllib.parse import quote
from typing import List, Optional, Tuple

import wx

from libtorrent_env import prepare_libtorrent_dlls

prepare_libtorrent_dlls()

try:
    import libtorrent as lt
except Exception:
    lt = None


POPULAR_TRACKERS: List[str] = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://exodus.desync.com:6969/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker2.dler.org:80/announce",
    "udp://tracker.dler.org:6969/announce",
    "https://tracker.tamersunion.org:443/announce",
    "https://tracker.gbitt.info:443/announce",
]


def _torrent_info_hash(info) -> str:
    try:
        if hasattr(info, "info_hashes"):
            hashes = info.info_hashes()
            if hashes.has_v1():
                return str(hashes.v1)
            if hashes.has_v2():
                return str(hashes.v2)
    except Exception:
        pass
    try:
        return str(info.info_hash())
    except Exception:
        return ""


PIECE_SIZE_CHOICES = [
    ("Auto", 0),
    ("16 KiB", 16 * 1024),
    ("32 KiB", 32 * 1024),
    ("64 KiB", 64 * 1024),
    ("128 KiB", 128 * 1024),
    ("256 KiB", 256 * 1024),
    ("512 KiB", 512 * 1024),
    ("1 MiB", 1 * 1024 * 1024),
    ("2 MiB", 2 * 1024 * 1024),
    ("4 MiB", 4 * 1024 * 1024),
]


def _clean_lines(text: str) -> List[str]:
    items: List[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        items.append(line)
    return items


def create_torrent_bytes(
    source_path: str,
    trackers: List[str],
    web_seeds: Optional[List[str]] = None,
    piece_size: int = 0,
    private: bool = False,
    comment: str = "",
    creator: str = "",
    source: str = "",
) -> Tuple[bytes, str, str]:
    """
    Returns: (torrent_bytes, magnet_link, info_hash_hex)

    Notes:
    - Setting private=True sets the 'private' flag in the torrent's info dict.
      Most clients treat this as "disable DHT/PEX/LSD for this torrent".
    """
    if not lt:
        raise RuntimeError("libtorrent is not available. Torrent creation requires python-libtorrent.")

    if not source_path:
        raise ValueError("Source path is required.")
    source_path = os.path.abspath(source_path)

    if not os.path.exists(source_path):
        raise FileNotFoundError(source_path)

    fs = lt.file_storage()

    # add_files can take a directory or a file; it will recurse for directories.
    lt.add_files(fs, source_path)

    # create_torrent signature differs a bit between lt versions; try safest calls.
    if piece_size and piece_size > 0:
        try:
            ct = lt.create_torrent(fs, piece_size)
        except TypeError:
            ct = lt.create_torrent(fs, piece_size=piece_size)
    else:
        ct = lt.create_torrent(fs)

    if private:
        try:
            ct.set_priv(True)
        except Exception:
            # Some versions expose set_priv(bool) as set_priv or set_private
            try:
                ct.set_private(True)
            except Exception:
                pass

    # Trackers
    seen = set()
    tier_mode_each = False  # dialog controls tiering; if callers want, they can order trackers as tiers via duplicates
    tier = 0
    for tr in trackers or []:
        tr = (tr or "").strip()
        if not tr:
            continue
        if tr in seen:
            continue
        seen.add(tr)
        try:
            ct.add_tracker(tr, tier)
        except TypeError:
            ct.add_tracker(tr)
        if tier_mode_each:
            tier += 1

    # Web seeds
    for ws in web_seeds or []:
        ws = (ws or "").strip()
        if not ws:
            continue
        try:
            ct.add_url_seed(ws)
        except Exception:
            # Some bindings call this add_url_seed or add_http_seed
            try:
                ct.add_http_seed(ws)
            except Exception:
                pass

    if comment:
        try:
            ct.set_comment(comment)
        except Exception:
            pass

    if creator:
        try:
            ct.set_creator(creator)
        except Exception:
            pass

    # Hash pieces
    base_path = os.path.dirname(source_path.rstrip("\\/")) or os.path.dirname(source_path) or source_path
    lt.set_piece_hashes(ct, base_path)

    e = ct.generate()

    # Add "source" inside info dict for trackers that expect it.
    if source:
        try:
            info = e["info"]
            info["source"] = source
        except Exception:
            try:
                e["info"]["source"] = source
            except Exception:
                pass

    torrent_bytes = lt.bencode(e)

    info_hash = ""
    try:
        ti = lt.torrent_info(torrent_bytes)
        info_hash = _torrent_info_hash(ti)
    except Exception:
        # Fallback: may not be available on some versions
        info_hash = ""

    magnet = ""
    try:
        if hasattr(lt, "make_magnet_uri"):
            magnet = lt.make_magnet_uri(ti)
    except Exception:
        magnet = ""
    if not magnet and info_hash:
        magnet = f"magnet:?xt=urn:btih:{info_hash}"
        for tr in trackers or []:
            tr = (tr or "").strip()
            if tr:
                magnet += f"&tr={quote(tr, safe='')}"
    return torrent_bytes, magnet, info_hash


class CreateTorrentDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Create Torrent", size=(700, 650))

        self.source_path = ""
        self.output_path = ""

        root = wx.BoxSizer(wx.VERTICAL)

        # Source selection
        root.Add(wx.StaticText(self, label="Source (file or folder):"), 0, wx.ALL, 8)
        src_row = wx.BoxSizer(wx.HORIZONTAL)
        self.src_input = wx.TextCtrl(self, value="")
        src_row.Add(self.src_input, 1, wx.EXPAND | wx.RIGHT, 6)
        pick_file = wx.Button(self, label="File...")
        pick_dir = wx.Button(self, label="Folder...")
        pick_file.Bind(wx.EVT_BUTTON, self.on_pick_file)
        pick_dir.Bind(wx.EVT_BUTTON, self.on_pick_folder)
        src_row.Add(pick_file, 0, wx.RIGHT, 6)
        src_row.Add(pick_dir, 0)
        root.Add(src_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Output selection
        root.Add(wx.StaticText(self, label="Output .torrent file:"), 0, wx.ALL, 8)
        out_row = wx.BoxSizer(wx.HORIZONTAL)
        self.out_input = wx.TextCtrl(self, value="")
        out_row.Add(self.out_input, 1, wx.EXPAND | wx.RIGHT, 6)
        pick_out = wx.Button(self, label="Save As...")
        pick_out.Bind(wx.EVT_BUTTON, self.on_pick_output)
        out_row.Add(pick_out, 0)
        root.Add(out_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Options: private + piece size
        opt_box = wx.StaticBoxSizer(wx.StaticBox(self, label="Torrent Options"), wx.VERTICAL)

        self.private_chk = wx.CheckBox(self, label="Private torrent (disables DHT/PEX/LSD in most clients)")
        self.private_chk.SetValue(False)
        opt_box.Add(self.private_chk, 0, wx.ALL, 6)

        piece_row = wx.BoxSizer(wx.HORIZONTAL)
        piece_row.Add(wx.StaticText(self, label="Piece size:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self.piece_choice = wx.Choice(self, choices=[label for label, _ in PIECE_SIZE_CHOICES])
        self.piece_choice.SetSelection(0)
        piece_row.Add(self.piece_choice, 0)
        opt_box.Add(piece_row, 0, wx.ALL, 6)

        root.Add(opt_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Trackers
        tr_box = wx.StaticBoxSizer(wx.StaticBox(self, label="Trackers"), wx.VERTICAL)
        tr_box.Add(wx.StaticText(self, label="Public tracker list (press Enter to add to Included trackers)."), 0, wx.ALL, 6)

        self._public_tracker_set = set(POPULAR_TRACKERS)

        # Public trackers list (used for quick insertion, not as the source of truth).
        # NOTE: wx.ListBox often does not reliably deliver Enter via EVT_KEY_DOWN on Windows because
        # dialogs have default buttons. We also handle Enter at the dialog level via EVT_CHAR_HOOK.
        self.tr_list = wx.ListBox(self, choices=POPULAR_TRACKERS, style=wx.LB_EXTENDED)
        self.tr_list.Bind(wx.EVT_KEY_DOWN, self.on_public_tracker_key_down)
        try:
            self.tr_list.Bind(wx.EVT_LISTBOX_DCLICK, self.on_public_tracker_activate)
        except Exception:
            pass

        # Catch Enter before the dialog's default button (OK) closes the window.
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)

        tr_box.Add(self.tr_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        tr_box.Add(wx.StaticText(self, label="Included trackers (one per line):"), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        self.trackers_edit = wx.TextCtrl(self, value="", style=wx.TE_MULTILINE | wx.TE_DONTWRAP | wx.HSCROLL)
        self.trackers_edit.SetMinSize((-1, 140))
        tr_box.Add(self.trackers_edit, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        add_row = wx.BoxSizer(wx.HORIZONTAL)
        self.custom_tr_input = wx.TextCtrl(self, value="", style=wx.TE_PROCESS_ENTER)
        add_row.Add(self.custom_tr_input, 1, wx.EXPAND | wx.RIGHT, 6)
        add_btn = wx.Button(self, label="Add Tracker")
        self.remove_tracker_btn = wx.Button(self, label="Remove Selected")
        add_btn.Bind(wx.EVT_BUTTON, self.on_add_tracker)
        self.remove_tracker_btn.Bind(wx.EVT_BUTTON, self.on_remove_selected_trackers)
        self.custom_tr_input.Bind(wx.EVT_TEXT_ENTER, self.on_add_tracker)
        add_row.Add(add_btn, 0, wx.RIGHT, 6)
        add_row.Add(self.remove_tracker_btn, 0)
        tr_box.Add(add_row, 0, wx.EXPAND | wx.ALL, 6)

        # Keep public tracker list out of tab order when private is checked.
        self.private_chk.Bind(wx.EVT_CHECKBOX, self.on_private_toggle)
        self.on_private_toggle(None)

        root.Add(tr_box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Web seeds
        ws_box = wx.StaticBoxSizer(wx.StaticBox(self, label="Web Seeds (optional)"), wx.VERTICAL)
        ws_box.Add(wx.StaticText(self, label="One URL per line (HTTP/HTTPS)."), 0, wx.ALL, 6)
        self.webseeds_input = wx.TextCtrl(self, value="", style=wx.TE_MULTILINE)
        ws_box.Add(self.webseeds_input, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        root.Add(ws_box, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Metadata
        meta_box = wx.StaticBoxSizer(wx.StaticBox(self, label="Metadata (optional)"), wx.VERTICAL)

        meta_box.Add(wx.StaticText(self, label="Comment:"), 0, wx.ALL, 6)
        self.comment_input = wx.TextCtrl(self, value="")
        meta_box.Add(self.comment_input, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        meta_box.Add(wx.StaticText(self, label="Source (written into info dict as 'source'):"), 0, wx.ALL, 6)
        self.source_input = wx.TextCtrl(self, value="")
        meta_box.Add(self.source_input, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        meta_box.Add(wx.StaticText(self, label="Created by:"), 0, wx.ALL, 6)
        self.creator_input = wx.TextCtrl(self, value="SerrebiTorrent")
        meta_box.Add(self.creator_input, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)

        root.Add(meta_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Post-actions
        post_box = wx.StaticBoxSizer(wx.StaticBox(self, label="After Creation"), wx.VERTICAL)
        self.add_to_client_chk = wx.CheckBox(self, label="Add created torrent to the currently connected client")
        self.add_to_client_chk.SetValue(False)
        post_box.Add(self.add_to_client_chk, 0, wx.ALL, 6)

        self.copy_magnet_chk = wx.CheckBox(self, label="Copy magnet link to clipboard")
        self.copy_magnet_chk.SetValue(True)
        post_box.Add(self.copy_magnet_chk, 0, wx.ALL, 6)

        root.Add(post_box, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # Buttons
        btns = wx.StdDialogButtonSizer()
        btns.AddButton(wx.Button(self, wx.ID_OK))
        btns.AddButton(wx.Button(self, wx.ID_CANCEL))
        btns.Realize()
        root.Add(btns, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        self.SetSizer(root)
        self.Center()

    def _auto_output_path(self, src_path: str) -> str:
        if not src_path:
            return ""
        base = os.path.basename(src_path.rstrip("\\/"))
        if not base:
            base = "output"
        name = base
        if name.lower().endswith(".torrent"):
            return os.path.abspath(name)
        return os.path.abspath(name + ".torrent")

    def on_pick_file(self, event):
        with wx.FileDialog(self, "Select File", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                path = dlg.GetPath()
                self.src_input.SetValue(path)
                if not self.out_input.GetValue().strip():
                    self.out_input.SetValue(self._auto_output_path(path))

    def on_pick_folder(self, event):
        with wx.DirDialog(self, "Select Folder") as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                path = dlg.GetPath()
                self.src_input.SetValue(path)
                if not self.out_input.GetValue().strip():
                    self.out_input.SetValue(self._auto_output_path(path))

    def on_pick_output(self, event):
        with wx.FileDialog(
            self,
            "Save Torrent As",
            wildcard="Torrent files (*.torrent)|*.torrent",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.out_input.SetValue(dlg.GetPath())

    def _get_tracker_lines(self) -> List[str]:
        """Return included trackers as a cleaned list (one URL per line)."""
        if not hasattr(self, "trackers_edit") or self.trackers_edit is None:
            return []
        raw = self.trackers_edit.GetValue()
        out: List[str] = []
        for ln in raw.splitlines():
            ln = ln.strip()
            if ln:
                out.append(ln)
        return out

    def _set_tracker_lines(self, lines: List[str]) -> None:
        if not hasattr(self, "trackers_edit") or self.trackers_edit is None:
            return
        self.trackers_edit.SetValue("\n".join(lines))

    def _add_trackers_to_edit(self, trackers_to_add: List[str]) -> None:
        existing = self._get_tracker_lines()
        seen = set(existing)
        changed = False
        for tr in trackers_to_add:
            tr = (tr or "").strip()
            if not tr:
                continue
            if tr not in seen:
                existing.append(tr)
                seen.add(tr)
                changed = True
        if changed:
            self._set_tracker_lines(existing)

    def _remove_trackers_from_edit(self, trackers_to_remove: List[str]) -> None:
        if not trackers_to_remove:
            return
        remove_set = { (t or "").strip() for t in trackers_to_remove if (t or "").strip() }
        if not remove_set:
            return
        existing = self._get_tracker_lines()
        new_lines = [t for t in existing if t.strip() not in remove_set]
        if new_lines != existing:
            self._set_tracker_lines(new_lines)

    def on_public_tracker_activate(self, event):
        """Add selected public tracker(s) to the Included trackers edit field."""
        try:
            sels = list(self.tr_list.GetSelections())
        except Exception:
            try:
                sel = int(self.tr_list.GetSelection())
                sels = [sel] if sel != wx.NOT_FOUND else []
            except Exception:
                sels = []

        if not sels:
            return

        to_add: List[str] = []
        for i in sels:
            try:
                tr = self.tr_list.GetString(i).strip()
            except Exception:
                tr = ""
            if tr:
                to_add.append(tr)

        if to_add:
            self._add_trackers_to_edit(to_add)

        try:
            event.Skip()
        except Exception:
            pass

    def on_public_tracker_key_down(self, event):
        key = event.GetKeyCode()
        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            # Treat Enter as "add selected tracker(s) to edit field".
            self.on_public_tracker_activate(event)
            try:
                event.Skip(False)
            except Exception:
                pass
            return
        try:
            event.Skip()
        except Exception:
            pass

    def on_char_hook(self, event):
        """Ensure Enter on the public tracker list adds the tracker instead of closing the dialog."""
        try:
            key = event.GetKeyCode()
        except Exception:
            key = None

        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            try:
                focus = wx.Window.FindFocus()
            except Exception:
                focus = None

            if focus is self.tr_list:
                self.on_public_tracker_activate(event)
                try:
                    event.Skip(False)
                except Exception:
                    pass
                return

        try:
            event.Skip()
        except Exception:
            pass

    def on_add_tracker(self, event):
        tr = self.custom_tr_input.GetValue().strip()
        if not tr:
            return
        self._add_trackers_to_edit([tr])
        self.custom_tr_input.SetValue("")

    def on_remove_selected_trackers(self, event):
        """Remove selected public tracker(s) from the Included trackers edit field."""
        try:
            sels = list(self.tr_list.GetSelections())
        except Exception:
            try:
                sel = int(self.tr_list.GetSelection())
                sels = [sel] if sel != wx.NOT_FOUND else []
            except Exception:
                sels = []

        if not sels:
            return

        to_remove: List[str] = []
        for i in sels:
            try:
                tr = self.tr_list.GetString(i).strip()
            except Exception:
                tr = ""
            if tr:
                to_remove.append(tr)

        self._remove_trackers_from_edit(to_remove)

    def on_private_toggle(self, event):
        """When private is enabled, ensure public trackers aren't auto-included and list isn't tabbable."""
        is_private = bool(self.private_chk.GetValue())

        # Remove any public trackers from the included list when private is enabled.
        if is_private:
            current = self._get_tracker_lines()
            new_lines = [t for t in current if t.strip() not in self._public_tracker_set]
            if new_lines != current:
                self._set_tracker_lines(new_lines)

        # Keep the public tracker list out of tab order when private is enabled.
        try:
            self.tr_list.Enable(not is_private)
        except Exception:
            try:
                self.tr_list.Disable() if is_private else self.tr_list.Enable(True)
            except Exception:
                pass

        if hasattr(self, "remove_tracker_btn"):
            try:
                self.remove_tracker_btn.Enable(not is_private)
            except Exception:
                pass


        if event is not None:
            try:
                event.Skip()
            except Exception:
                pass

    def get_options(self) -> dict:
        src = self.src_input.GetValue().strip()
        outp = self.out_input.GetValue().strip()
        if not src:
            raise ValueError("Source path is required.")
        if not outp:
            raise ValueError("Output .torrent path is required.")

        piece_size = PIECE_SIZE_CHOICES[self.piece_choice.GetSelection()][1]

        is_private = bool(self.private_chk.GetValue())

        # Trackers come from the edit field (one per line).
        trackers_raw = self._get_tracker_lines()

        # De-duplicate while preserving order.
        trackers: List[str] = []
        seen = set()
        for tr in trackers_raw:
            tr = (tr or "").strip()
            if not tr:
                continue
            if is_private and tr in self._public_tracker_set:
                continue
            if tr in seen:
                continue
            seen.add(tr)
            trackers.append(tr)

        return {
            "source_path": src,
            "output_path": outp,
            "trackers": trackers,
            "web_seeds": _clean_lines(self.webseeds_input.GetValue()),
            "piece_size": piece_size,
            "private": self.private_chk.GetValue(),
            "comment": self.comment_input.GetValue().strip(),
            "creator": self.creator_input.GetValue().strip(),
            "source": self.source_input.GetValue().strip(),
            "add_to_client": self.add_to_client_chk.GetValue(),
            "copy_magnet": self.copy_magnet_chk.GetValue(),
        }
