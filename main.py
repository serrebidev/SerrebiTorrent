# ruff: noqa: E402

import wx
import sys
import os
import shutil
import subprocess
from collections import OrderedDict
import time

from libtorrent_env import prepare_libtorrent_dlls

prepare_libtorrent_dlls()

import wx.adv
import threading
import json
import requests # Added for downloading torrent files from URL
import concurrent.futures

from clients import RTorrentClient, QBittorrentClient, TransmissionClient, LocalClient, safe_encode_url
from config_manager import ConfigManager
from session_manager import SessionManager
from rss_manager import RSSManager
import web_server
import updater
from torrent_creator import CreateTorrentDialog, create_torrent_bytes
from torrent_parsing import parse_magnet_infohash, safe_torrent_info_hash


# Constants for List Columns
COL_NAME = 0
COL_SIZE = 1
COL_STATUS = 2
COL_TIME_LEFT = 3
COL_SEEDS = 4
COL_LEECHERS = 5
COL_RATIO = 6
COL_AVAILABILITY = 7

# Rows in the torrent list carry an extra hidden value at the end (info hash).
ROW_HASH_INDEX = -1
APP_NAME = "SerrebiTorrent"


def get_app_icon():
    """Return a wx.Icon for the tray and main window, with a safe fallback."""
    base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    icon_path = os.path.join(base_dir, "icon.ico")

    if os.path.exists(icon_path):
        try:
            return wx.Icon(icon_path, wx.BITMAP_TYPE_ICO)
        except Exception:
            pass

    bmp = wx.ArtProvider.GetBitmap(wx.ART_INFORMATION, wx.ART_OTHER, (16, 16))
    if not bmp.IsOk():
        bmp = wx.Bitmap(16, 16)
        dc = wx.MemoryDC(bmp)
        dc.SetBackground(wx.Brush(wx.Colour(0, 0, 0)))
        dc.Clear()
        dc.SelectObject(wx.NullBitmap)

    fallback_icon = wx.Icon()
    fallback_icon.CopyFromBitmap(bmp)
    return fallback_icon


def fmt_size(size):
    if size == 0:
        return ""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def fmt_ratio(ratio_val):
    """Format ratio consistently across clients.

    Most clients provide ratio as an integer scaled by 1000 (e.g. 1500 == 1.5).
    Some may provide a float (e.g. 1.5).
    """
    try:
        if ratio_val is None:
            return ""
        r = float(ratio_val)
    except Exception:
        return ""
    if r < 0:
        r = 0.0
    # Heuristic: values above 50 are almost certainly scaled by 1000.
    if r > 50.0:
        r = r / 1000.0
    return f"{r:.2f}"


def fmt_availability(avail_val):
    """Format availability (distributed copies) as a short string."""
    try:
        if avail_val is None:
            return "—"
        a = float(avail_val)
    except Exception:
        return "—"
    if a < 0:
        return "—"
    return f"{a:.2f}"


def fmt_eta(seconds):
    """Format an ETA in seconds into a short, screen-reader-friendly string."""
    try:
        if seconds is None:
            return "—"
        seconds = int(seconds)
    except Exception:
        return "—"

    if seconds < 0:
        return "—"
    if seconds == 0:
        return "0s"

    s = seconds
    days = s // 86400
    s %= 86400
    hours = s // 3600
    s %= 3600
    minutes = s // 60
    s %= 60

    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {s}s"
    return f"{s}s"


def fmt_pair(connected, total):
    """Format connected/total counts.

    Uses '?' for unknown values (None, non-numeric, negative).
    """
    def to_int_or_none(v):
        if v is None:
            return None
        try:
            iv = int(v)
        except Exception:
            return None
        if iv < 0:
            return None
        return iv

    c = to_int_or_none(connected)
    t = to_int_or_none(total)

    c_str = str(c) if c is not None else "?"
    t_str = str(t) if t is not None else "?"
    return f"{c_str}/{t_str}"


def clean_status_message(msg):
    """Drop noisy/undefined 'success' messages that some backends return as an error string."""
    if msg is None:
        return ""
    try:
        m = str(msg).strip()
    except Exception:
        return ""
    if not m:
        return ""
    low = m.lower().strip()
    # Common 'no error' strings (not useful to show).
    phrase = "the operation completed successfully"
    if low.rstrip('.').strip() == phrase:
        return ""
    if phrase in low:
        # If the message is only that phrase (possibly with punctuation), drop it.
        remainder = low.replace(phrase, "").strip(" -;:().[]{}\t\r\n")
        if not remainder:
            return ""
    if "the handle is invalid" in low:
        return ""
    if low in ("success", "ok", "no error", "none"):
        return ""
    return m


try:
    import libtorrent as lt
except ImportError:
    lt = None

class AddTorrentDialog(wx.Dialog):
    def __init__(self, parent, name, file_list=None, default_path=""):
        super().__init__(parent, title=f"Add Torrent: {name}", size=(600, 500))
        
        self.file_list = file_list or []
        self.item_map = {} # item_id -> {'name': str, 'size': int, 'idx': int or None}
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Save Path
        path_sizer = wx.BoxSizer(wx.HORIZONTAL)
        path_sizer.Add(wx.StaticText(self, label="Save Path:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.path_input = wx.TextCtrl(self, value=default_path)
        path_sizer.Add(self.path_input, 1, wx.EXPAND | wx.RIGHT, 5)
        browse_btn = wx.Button(self, label="Browse...")
        browse_btn.Bind(wx.EVT_BUTTON, self.on_browse)
        path_sizer.Add(browse_btn, 0)
        sizer.Add(path_sizer, 0, wx.EXPAND | wx.ALL, 10)
        
        # Files Tree
        if self.file_list:
            sizer.Add(wx.StaticText(self, label="Files:"), 0, wx.LEFT | wx.RIGHT, 10)
            
            # Standard TreeCtrl with text-based checkboxes
            self.tree = wx.TreeCtrl(self, style=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT | wx.TR_HAS_BUTTONS | wx.TR_LINES_AT_ROOT)
            self.root = self.tree.AddRoot(name)
            self.item_map[self.root] = {'name': name, 'size': 0, 'idx': None}
            
            self.tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self.on_toggle)
            self.tree.Bind(wx.EVT_KEY_DOWN, self.on_key_down)
            self.tree.Bind(wx.EVT_LEFT_DOWN, self.on_click) 
            self.tree.Bind(wx.EVT_TREE_ITEM_RIGHT_CLICK, self.on_tree_context_menu)

            # Helper to find or create child
            def get_or_create_child(parent_item, text):
                (child, cookie) = self.tree.GetFirstChild(parent_item)
                while child.IsOk():
                    if self.item_map[child]['name'] == text:
                        return child
                    (child, cookie) = self.tree.GetNextChild(parent_item, cookie)
                
                item = self.tree.AppendItem(parent_item, "")
                self.item_map[item] = {'name': text, 'size': 0, 'idx': None}
                self.update_item_label(item, True) # Default checked
                return item

            for idx, (fpath, fsize) in enumerate(self.file_list):
                # Normalize path
                parts = fpath.replace('\\', '/').split('/')
                current_item = self.root
                
                for i, part in enumerate(parts):
                    if i == len(parts) - 1:
                        # Leaf
                        item = self.tree.AppendItem(current_item, "")
                        self.item_map[item] = {'name': part, 'size': fsize, 'idx': idx}
                        self.update_item_label(item, True)
                    else:
                        # Folder
                        current_item = get_or_create_child(current_item, part)
            
            self.tree.ExpandAll()
            
            sizer.Add(self.tree, 1, wx.EXPAND | wx.ALL, 10)
            
            # Select/Deselect Buttons
            btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
            sel_all = wx.Button(self, label="Select All")
            sel_all.Bind(wx.EVT_BUTTON, lambda e: self.set_root_state(True))
            btn_sizer.Add(sel_all, 0, wx.RIGHT, 5)
            
            desel_all = wx.Button(self, label="Deselect All")
            desel_all.Bind(wx.EVT_BUTTON, lambda e: self.set_root_state(False))
            btn_sizer.Add(desel_all, 0)
            
            sizer.Add(btn_sizer, 0, wx.ALIGN_LEFT | wx.LEFT | wx.BOTTOM, 10)
        else:
            sizer.Add(wx.StaticText(self, label="File list not available (Magnet link)."), 0, wx.ALL, 20)
        
        # Dialog Buttons
        btns = wx.StdDialogButtonSizer()
        btns.AddButton(wx.Button(self, wx.ID_OK))
        btns.AddButton(wx.Button(self, wx.ID_CANCEL))
        btns.Realize()
        sizer.Add(btns, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        
        self.SetSizer(sizer)
        self.Center()

    def on_browse(self, event):
        dlg = wx.DirDialog(self, "Choose Download Directory", self.path_input.GetValue())
        if dlg.ShowModal() == wx.ID_OK:
            self.path_input.SetValue(dlg.GetPath())
        dlg.Destroy()

    def update_item_label(self, item, checked):
        data = self.item_map.get(item)
        if not data:
            return
        
        prefix = "[x]" if checked else "[ ]"
        size_str = f" ({fmt_size(data['size'])})" if data['size'] > 0 else ""
        
        label = f"{prefix} {data['name']}{size_str}"
        self.tree.SetItemText(item, label)

    def is_checked(self, item):
        txt = self.tree.GetItemText(item)
        return txt.startswith("[x]")

    def on_toggle(self, event):
        item = event.GetItem()
        if item.IsOk():
            self.toggle_item(item)

    def on_key_down(self, event):
        code = event.GetKeyCode()
        if code == wx.WXK_SPACE:
            item = self.tree.GetSelection()
            if item.IsOk():
                self.toggle_item(item)
        else:
            event.Skip()
            
    def on_click(self, event):
        event.Skip()

    def on_tree_context_menu(self, event):
        item = event.GetItem()
        if not item.IsOk():
            item = self.tree.GetSelection()
        
        if not item.IsOk():
            return

        menu = wx.Menu()
        check_item = menu.Append(wx.ID_ANY, "Check")
        uncheck_item = menu.Append(wx.ID_ANY, "Uncheck")
        menu.AppendSeparator()
        check_all = menu.Append(wx.ID_ANY, "Check All")
        uncheck_all = menu.Append(wx.ID_ANY, "Uncheck All")

        self.Bind(wx.EVT_MENU, lambda e: self.set_item_state_recursive(item, True), check_item)
        self.Bind(wx.EVT_MENU, lambda e: self.set_item_state_recursive(item, False), uncheck_item)
        self.Bind(wx.EVT_MENU, lambda e: self.set_root_state(True), check_all)
        self.Bind(wx.EVT_MENU, lambda e: self.set_root_state(False), uncheck_all)

        self.PopupMenu(menu)
        menu.Destroy()

    def toggle_item(self, item):
        new_state = not self.is_checked(item)
        self.set_item_state_recursive(item, new_state)

    def set_item_state_recursive(self, item, state):
        self.update_item_label(item, state)
        self.update_children(item, state)
        
        # Update parent up the chain
        parent = self.tree.GetItemParent(item)
        while parent.IsOk() and parent != self.root:
            self.update_parent(parent)
            parent = self.tree.GetItemParent(parent)

    def update_children(self, parent, state):
        (child, cookie) = self.tree.GetFirstChild(parent)
        while child.IsOk():
            self.update_item_label(child, state)
            self.update_children(child, state)
            (child, cookie) = self.tree.GetNextChild(parent, cookie)

    def update_parent(self, parent):
        has_checked = False
        (child, cookie) = self.tree.GetFirstChild(parent)
        while child.IsOk():
            if self.is_checked(child):
                has_checked = True
                break
            (child, cookie) = self.tree.GetNextChild(parent, cookie)
        self.update_item_label(parent, has_checked)

    def set_root_state(self, state):
        (child, cookie) = self.tree.GetFirstChild(self.root)
        while child.IsOk():
            self.set_item_state_recursive(child, state)
            (child, cookie) = self.tree.GetNextChild(self.root, cookie)

    def get_selected_path(self):
        return self.path_input.GetValue()

    def get_file_priorities(self):
        if not self.file_list:
            return None
        priorities = [0] * len(self.file_list)
        
        def traverse(item):
            if not item.IsOk():
                return
            
            data = self.item_map.get(item)
            if data and data['idx'] is not None:
                priorities[data['idx']] = 1 if self.is_checked(item) else 0
                
            (child, cookie) = self.tree.GetFirstChild(item)
            while child.IsOk():
                traverse(child)
                (child, cookie) = self.tree.GetNextChild(item, cookie)

        traverse(self.root)
        return priorities


def register_associations():
    """Registers file associations for .torrent and magnet: links on Windows."""
    if sys.platform != 'win32':
        wx.MessageBox("Association is only supported on Windows for now.", "Info")
        return

    try:
        import winreg
        
        exe_path = sys.executable
        if not getattr(sys, 'frozen', False):
            python_exe = sys.executable.replace("python.exe", "pythonw.exe")
            cmd = f'"{python_exe}" "{os.path.abspath(__file__)}" "%1"'
        else:
            cmd = f'"{exe_path}" "%1"'

        # 1. Associate .torrent
        key_path = r"Software\Classes\.torrent"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValue(key, "", winreg.REG_SZ, "SerrebiTorrent.Torrent")

        key_path = r"Software\Classes\SerrebiTorrent.Torrent"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValue(key, "", winreg.REG_SZ, "Torrent File")
            with winreg.CreateKey(key, r"shell\open\command") as cmd_key:
                winreg.SetValue(cmd_key, "", winreg.REG_SZ, cmd)
                
        # 2. Associate magnet:
        key_path = r"Software\Classes\magnet"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValue(key, "", winreg.REG_SZ, "URL:Magnet Link")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
            with winreg.CreateKey(key, r"shell\open\command") as cmd_key:
                winreg.SetValue(cmd_key, "", winreg.REG_SZ, cmd)

        wx.MessageBox("Associations registered successfully!", "Success")
    except Exception as e:
        wx.LogError(f"Failed to register associations: {e}")

class TorrentListCtrl(wx.ListCtrl):
    def __init__(self, parent, id=wx.ID_ANY, pos=wx.DefaultPosition,
                 size=wx.DefaultSize, style=wx.LC_REPORT | wx.LC_VIRTUAL | wx.LC_HRULES | wx.LC_VRULES):
        super().__init__(parent, id, pos, size, style)
        
        self.data = [] # List of dicts
        self.sort_col = -1
        self.sort_asc = True

        self.InsertColumn(COL_NAME, "Name", width=300)
        self.InsertColumn(COL_SIZE, "Size", width=100)
        self.InsertColumn(COL_STATUS, "Status", width=220)
        self.InsertColumn(COL_TIME_LEFT, "Time Left", width=110)
        self.InsertColumn(COL_SEEDS, "Seeds", width=120)
        self.InsertColumn(COL_LEECHERS, "Leechers", width=160)
        self.InsertColumn(COL_RATIO, "Ratio", width=80)
        self.InsertColumn(COL_AVAILABILITY, "Availability", width=110)

        self.SetName("Torrent List")
        self.Bind(wx.EVT_LIST_COL_CLICK, self.on_col_click)

    def OnGetItemText(self, item, col):
        if item >= len(self.data):
            return ""
        try:
            row = self.data[item]
            if col == COL_NAME:
                return str(row.get('name', 'Unknown'))
            if col == COL_SIZE:
                return fmt_size(row.get('size', 0))
            if col == COL_STATUS:
                # Fast pre-calculation
                size = row.get('size', 0)
                done = row.get('done', 0)
                pct = (done / size * 100) if size > 0 else 0
                state = row.get('state', 0)
                hashing = row.get('hashing', 0)
                msg = clean_status_message(row.get('message', ''))
                
                status_str = "Stopped"
                if hashing:
                    status_str = "Checking"
                elif state == 1:
                    if pct >= 100:
                        status_str = "Seeding"
                    else:
                        status_str = f"Downloaded: {pct:.1f}%"
                        down_rate = row.get('down_rate', 0)
                        if down_rate > 0:
                            status_str += f"; {fmt_size(down_rate)}/s"
                if msg:
                    status_str += f" ({msg})"
                return status_str
            if col == COL_TIME_LEFT:
                eta = row.get('eta')
                if eta is None:
                    try:
                        remaining = max(0, int(row.get('size', 0)) - int(row.get('done', 0)))
                        down_rate = int(row.get('down_rate', 0) or 0)
                        eta = int(remaining / down_rate) if down_rate > 0 and remaining > 0 else -1
                    except Exception:
                        eta = -1
                return fmt_eta(eta)
            if col == COL_SEEDS:
                return fmt_pair(row.get('seeds_connected', 0), row.get('seeds_total', 0))
            if col == COL_LEECHERS:
                leechers_str = fmt_pair(row.get('leechers_connected', 0), row.get('leechers_total', 0))
                up_rate = row.get('up_rate', 0)
                if up_rate > 0:
                    leechers_str += f" up: {fmt_size(up_rate)}/s"
                return leechers_str
            if col == COL_RATIO:
                return fmt_ratio(row.get('ratio', 0))
            if col == COL_AVAILABILITY:
                return fmt_availability(row.get('availability'))
            return ""
        except Exception:
            return ""

    def update_data(self, new_data):
        # new_data is list of dicts
        self.data = new_data
        self._apply_sort()
        
        current_count = self.GetItemCount()
        new_count = len(self.data)
        
        if current_count != new_count:
            self.SetItemCount(new_count)
        
        # Always refresh to update text
        self.Refresh()

    def on_col_click(self, event):
        col = event.GetColumn()
        if col == self.sort_col:
            self.sort_asc = not self.sort_asc
        else:
            self.sort_col = col
            self.sort_asc = True
        self._apply_sort()
        self.Refresh()

    def _apply_sort(self):
        if self.sort_col == -1 or not self.data:
            return

        # Map column to sort key
        sort_keys = {
            COL_NAME: 'name',
            COL_SIZE: 'size',
            COL_STATUS: 'state', # Approx
            COL_TIME_LEFT: 'eta',
            COL_SEEDS: 'seeds_connected',
            COL_LEECHERS: 'leechers_connected',
            COL_RATIO: 'ratio',
            COL_AVAILABILITY: 'availability'
        }
        key = sort_keys.get(self.sort_col)
        if not key:
            return

        def sort_key(item):
            val = item.get(key)
            if val is None:
                if key in ('size', 'eta', 'seeds_connected', 'leechers_connected', 'ratio', 'availability'):
                    return -1
                return ""
            return val

        try:
            self.data.sort(key=sort_key, reverse=not self.sort_asc)
        except Exception:
            pass

    def get_selected_hashes(self):
        selection = []
        item = self.GetFirstSelected()
        while item != -1:
            try:
                selection.append(self.data[item]['hash'])
            except Exception:
                pass
            item = self.GetNextSelected(item)
        return selection

class ProfileDialog(wx.Dialog):
    def __init__(self, parent, profile=None):
        title = "Edit Profile" if profile else "Add Profile"
        super().__init__(parent, title=title)
        
        self.profile = profile
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Name
        sizer.Add(wx.StaticText(self, label="Profile Name:"), 0, wx.ALL, 5)
        self.name_input = wx.TextCtrl(self, value=profile['name'] if profile else "")
        sizer.Add(self.name_input, 0, wx.EXPAND | wx.ALL, 5)
        
        # Type
        sizer.Add(wx.StaticText(self, label="Client Type:"), 0, wx.ALL, 5)
        self.type_input = wx.Choice(self, choices=["local", "rtorrent", "qbittorrent", "transmission"])
        self.type_input.Bind(wx.EVT_CHOICE, self.on_type_change)
        if profile:
            self.type_input.SetStringSelection(profile.get('type', 'local'))
        else:
            self.type_input.SetSelection(0)
        sizer.Add(self.type_input, 0, wx.EXPAND | wx.ALL, 5)
        
        # URL / Path (or local download path)
        self.url_label = wx.StaticText(self, label="URL (e.g. scgi://... or http://...):")
        sizer.Add(self.url_label, 0, wx.ALL, 5)

        url_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.url_input = wx.TextCtrl(self, value=profile['url'] if profile else "")
        url_sizer.Add(self.url_input, 1, wx.EXPAND | wx.RIGHT, 5)

        self.url_browse_btn = wx.Button(self, label="Browse...")
        self.url_browse_btn.Bind(wx.EVT_BUTTON, self.on_browse_url_path)
        url_sizer.Add(self.url_browse_btn, 0)

        sizer.Add(url_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        # User
        self.user_label = wx.StaticText(self, label="Username:")
        sizer.Add(self.user_label, 0, wx.ALL, 5)
        self.user_input = wx.TextCtrl(self, value=profile['user'] if profile else "")
        sizer.Add(self.user_input, 0, wx.EXPAND | wx.ALL, 5)
        
        # Pass
        self.pass_label = wx.StaticText(self, label="Password:")
        sizer.Add(self.pass_label, 0, wx.ALL, 5)
        self.pass_input = wx.TextCtrl(self, value=profile['password'] if profile else "", style=wx.TE_PASSWORD)
        sizer.Add(self.pass_input, 0, wx.EXPAND | wx.ALL, 5)
        
        btns = wx.StdDialogButtonSizer()
        btns.AddButton(wx.Button(self, wx.ID_OK))
        btns.AddButton(wx.Button(self, wx.ID_CANCEL))
        btns.Realize()
        sizer.Add(btns, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        
        self.SetSizer(sizer)
        self.Fit()
        self.Center()
        
        # Trigger initial update
        self.on_type_change(None)

    def on_type_change(self, event):
        sel = self.type_input.GetStringSelection()
        if sel == "local":
            self.url_label.SetLabel("Download Path:")
            if hasattr(self, 'url_browse_btn'):
                self.url_browse_btn.Show(True)
            self.user_input.Disable()
            self.pass_input.Disable()
        else:
            self.url_label.SetLabel("URL (e.g. scgi://... or http://...):")
            if hasattr(self, 'url_browse_btn'):
                self.url_browse_btn.Show(False)
            self.user_input.Enable()
            self.pass_input.Enable()

        self.Layout()


    def on_browse_url_path(self, event):
        # Used when profile type is 'local' to choose a download folder.
        start = self.url_input.GetValue().strip()
        if not start or not os.path.isdir(start):
            start = os.path.expanduser("~")
        dlg = wx.DirDialog(self, "Choose Download Folder", start, style=wx.DD_DEFAULT_STYLE)
        if dlg.ShowModal() == wx.ID_OK:
            self.url_input.SetValue(dlg.GetPath())
        dlg.Destroy()

    def GetProfileData(self):
        return {
            "name": self.name_input.GetValue(),
            "type": self.type_input.GetStringSelection(),
            "url": self.url_input.GetValue(),
            "user": self.user_input.GetValue(),
            "password": self.pass_input.GetValue()
        }

class ConnectDialog(wx.Dialog):
    def __init__(self, parent, config_manager):
        super().__init__(parent, title="Connection Manager", size=(500, 300))
        self.cm = config_manager
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # List of Profiles
        self.list_box = wx.ListBox(self, style=wx.LB_SINGLE)
        sizer.Add(self.list_box, 1, wx.EXPAND | wx.ALL, 10)
        
        # Buttons Row
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        add_btn = wx.Button(self, label="Add")
        add_btn.Bind(wx.EVT_BUTTON, self.on_add)
        btn_sizer.Add(add_btn, 0, wx.RIGHT, 5)
        
        edit_btn = wx.Button(self, label="Edit")
        edit_btn.Bind(wx.EVT_BUTTON, self.on_edit)
        btn_sizer.Add(edit_btn, 0, wx.RIGHT, 5)
        
        del_btn = wx.Button(self, label="Delete")
        del_btn.Bind(wx.EVT_BUTTON, self.on_delete)
        btn_sizer.Add(del_btn, 0, wx.RIGHT, 5)
        
        set_def_btn = wx.Button(self, label="Set Default")
        set_def_btn.Bind(wx.EVT_BUTTON, self.on_set_default)
        btn_sizer.Add(set_def_btn, 0, wx.RIGHT, 5)
        
        connect_btn = wx.Button(self, label="Connect")
        connect_btn.Bind(wx.EVT_BUTTON, self.on_connect)
        btn_sizer.Add(connect_btn, 0, wx.LEFT, 20)
        
        close_btn = wx.Button(self, wx.ID_CANCEL, label="Close")
        close_btn.Bind(wx.EVT_BUTTON, lambda evt: self.EndModal(wx.ID_CANCEL))
        btn_sizer.Add(close_btn, 0, wx.LEFT, 10)
        
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        
        self.SetSizer(sizer)
        self.Center()

        try:
            self.SetEscapeId(wx.ID_CANCEL)
        except Exception:
            pass

        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)
        
        self.selected_profile_id = None
        self.refresh_list()

    
    def on_char_hook(self, event):
        try:
            key = event.GetKeyCode()
        except Exception:
            key = None

        if key == wx.WXK_ESCAPE:
            try:
                self.EndModal(wx.ID_CANCEL)
            except Exception:
                try:
                    self.Close()
                except Exception:
                    pass
            return

        try:
            event.Skip()
        except Exception:
            pass

    def refresh_list(self, select_pid=None):
        self.list_box.Clear()
        self.profiles_map = [] # Index -> ID
        
        profiles = self.cm.get_profiles()
        default_id = self.cm.get_default_profile_id()
        
        selection_idx = 0
        
        for pid, p in profiles.items():
            label = p['name']
            if pid == default_id:
                label += " (Default)"
            idx = self.list_box.Append(label)
            self.profiles_map.append(pid)
            if select_pid and pid == select_pid:
                selection_idx = idx
            
        # Select requested or first if any
        if self.profiles_map:
            if selection_idx < self.list_box.GetCount():
                self.list_box.SetSelection(selection_idx)
            else:
                 self.list_box.SetSelection(0)

    def get_selected_id(self):
        sel = self.list_box.GetSelection()
        if sel != wx.NOT_FOUND and sel < len(self.profiles_map):
            return self.profiles_map[sel]
        return None

    def on_add(self, event):
        dlg = ProfileDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            data = dlg.GetProfileData()
            pid = self.cm.add_profile(data['name'], data['type'], data['url'], data['user'], data['password'])
            self.refresh_list(select_pid=pid)
        dlg.Destroy()

    def on_edit(self, event):
        pid = self.get_selected_id()
        if not pid:
            return
        
        p = self.cm.get_profile(pid)
        dlg = ProfileDialog(self, p)
        if dlg.ShowModal() == wx.ID_OK:
            data = dlg.GetProfileData()
            self.cm.update_profile(pid, data['name'], data['type'], data['url'], data['user'], data['password'])
            self.refresh_list(select_pid=pid)
        dlg.Destroy()

    def on_delete(self, event):
        pid = self.get_selected_id()
        if pid and wx.MessageBox("Delete this profile?", "Confirm", wx.YES_NO) == wx.YES:
            self.cm.delete_profile(pid)
            self.refresh_list()

    def on_set_default(self, event):
        pid = self.get_selected_id()
        if pid:
            self.cm.set_default_profile_id(pid)
            self.refresh_list()

    def on_connect(self, event):
        self.selected_profile_id = self.get_selected_id()
        if self.selected_profile_id:
            self.EndModal(wx.ID_OK)
        else:
            wx.MessageBox("Please select a profile to connect.", "Warning")


class PreferencesDialog(wx.Dialog):
    def __init__(self, parent, config_manager):
        super().__init__(parent, title="Local Session Settings", size=(500, 500))
        self.cm = config_manager
        self.prefs = self.cm.get_preferences()
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        notebook = wx.Notebook(self)
        
        # --- General Tab ---
        general_panel = wx.Panel(notebook)
        gen_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Download Path
        gen_sizer.Add(wx.StaticText(general_panel, label="Default Download Path:"), 0, wx.ALL, 5)
        path_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.path_input = wx.TextCtrl(general_panel, value=self.prefs.get('download_path', ''))
        path_sizer.Add(self.path_input, 1, wx.EXPAND | wx.RIGHT, 5)
        browse_btn = wx.Button(general_panel, label="Browse...")
        browse_btn.Bind(wx.EVT_BUTTON, self.on_browse)
        path_sizer.Add(browse_btn, 0)
        gen_sizer.Add(path_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        # Behavior
        self.auto_start_chk = wx.CheckBox(general_panel, label="Automatically start torrents")
        self.auto_start_chk.SetValue(self.prefs.get('auto_start', True))
        gen_sizer.Add(self.auto_start_chk, 0, wx.ALL, 5)
        
        self.min_tray_chk = wx.CheckBox(general_panel, label="Minimize to System Tray")
        self.min_tray_chk.SetValue(self.prefs.get('min_to_tray', True))
        gen_sizer.Add(self.min_tray_chk, 0, wx.ALL, 5)
        
        self.close_tray_chk = wx.CheckBox(general_panel, label="Close to System Tray")
        self.close_tray_chk.SetValue(self.prefs.get('close_to_tray', True))
        gen_sizer.Add(self.close_tray_chk, 0, wx.ALL, 5)

        self.auto_update_chk = wx.CheckBox(general_panel, label="Check for updates automatically on startup")
        self.auto_update_chk.SetValue(self.prefs.get('auto_check_updates', True))
        gen_sizer.Add(self.auto_update_chk, 0, wx.ALL, 5)
        
        general_panel.SetSizer(gen_sizer)
        notebook.AddPage(general_panel, "General")
        
        # --- Connection Tab ---
        conn_panel = wx.Panel(notebook)
        conn_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Limits
        conn_sizer.Add(wx.StaticText(conn_panel, label="Global Limits (0 or -1 for unlimited):"), 0, wx.ALL, 5)
        
        grid = wx.FlexGridSizer(4, 2, 10, 10)
        
        grid.Add(wx.StaticText(conn_panel, label="Download Rate (bytes/s):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.dl_limit = wx.SpinCtrl(conn_panel, min=-1, max=1000000000, initial=self.prefs.get('dl_limit', 0))
        grid.Add(self.dl_limit, 0, wx.EXPAND)
        
        grid.Add(wx.StaticText(conn_panel, label="Upload Rate (bytes/s):"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.ul_limit = wx.SpinCtrl(conn_panel, min=-1, max=1000000000, initial=self.prefs.get('ul_limit', 0))
        grid.Add(self.ul_limit, 0, wx.EXPAND)
        
        grid.Add(wx.StaticText(conn_panel, label="Max Connections:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.max_conn = wx.SpinCtrl(conn_panel, min=-1, max=65535, initial=self.prefs.get('max_connections', -1))
        grid.Add(self.max_conn, 0, wx.EXPAND)
        
        grid.Add(wx.StaticText(conn_panel, label="Max Upload Slots:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.max_slots = wx.SpinCtrl(conn_panel, min=-1, max=65535, initial=self.prefs.get('max_uploads', -1))
        grid.Add(self.max_slots, 0, wx.EXPAND)
        
        conn_sizer.Add(grid, 0, wx.ALL, 10)
        
        # Network
        conn_sizer.Add(wx.StaticLine(conn_panel), 0, wx.EXPAND | wx.ALL, 5)
        
        port_sizer = wx.BoxSizer(wx.HORIZONTAL)
        port_sizer.Add(wx.StaticText(conn_panel, label="Listening Port:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.port_input = wx.SpinCtrl(conn_panel, min=1, max=65535, initial=self.prefs.get('listen_port', 6881))
        port_sizer.Add(self.port_input, 0)
        conn_sizer.Add(port_sizer, 0, wx.ALL, 10)
        
        self.upnp_chk = wx.CheckBox(conn_panel, label="Enable UPnP Port Mapping")
        self.upnp_chk.SetValue(self.prefs.get('enable_upnp', True))
        conn_sizer.Add(self.upnp_chk, 0, wx.ALL, 5)
        
        self.natpmp_chk = wx.CheckBox(conn_panel, label="Enable NAT-PMP Port Mapping")
        self.natpmp_chk.SetValue(self.prefs.get('enable_natpmp', True))
        conn_sizer.Add(self.natpmp_chk, 0, wx.ALL, 5)

        self.dht_chk = wx.CheckBox(conn_panel, label="Enable DHT")
        self.dht_chk.SetValue(self.prefs.get('enable_dht', True))
        conn_sizer.Add(self.dht_chk, 0, wx.ALL, 5)

        self.lsd_chk = wx.CheckBox(conn_panel, label="Enable Local Service Discovery (LSD)")
        self.lsd_chk.SetValue(self.prefs.get('enable_lsd', True))
        conn_sizer.Add(self.lsd_chk, 0, wx.ALL, 5)
        
        conn_panel.SetSizer(conn_sizer)
        notebook.AddPage(conn_panel, "Connection")
        
        # --- Trackers Tab ---
        track_panel = wx.Panel(notebook)
        track_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.track_chk = wx.CheckBox(track_panel, label="Automatically add trackers from URL")
        self.track_chk.SetValue(self.prefs.get('enable_trackers', True))
        track_sizer.Add(self.track_chk, 0, wx.ALL, 5)
        
        track_sizer.Add(wx.StaticText(track_panel, label="Tracker List URL:"), 0, wx.ALL, 5)
        self.track_url_input = wx.TextCtrl(track_panel, value=self.prefs.get('tracker_url', ''))
        track_sizer.Add(self.track_url_input, 0, wx.EXPAND | wx.ALL, 5)
        
        track_panel.SetSizer(track_sizer)
        notebook.AddPage(track_panel, "Trackers")
        
        # --- RSS Tab ---
        rss_settings_panel = wx.Panel(notebook)
        rss_settings_sizer = wx.BoxSizer(wx.VERTICAL)
        
        rss_interval_sizer = wx.BoxSizer(wx.HORIZONTAL)
        rss_interval_sizer.Add(wx.StaticText(rss_settings_panel, label="RSS Update Interval (seconds):"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.rss_interval = wx.SpinCtrl(rss_settings_panel, min=5, max=86400, initial=self.prefs.get('rss_update_interval', 300))
        rss_interval_sizer.Add(self.rss_interval, 0)
        rss_settings_sizer.Add(rss_interval_sizer, 0, wx.ALL, 10)
        
        rss_settings_sizer.Add(wx.StaticLine(rss_settings_panel), 0, wx.EXPAND | wx.ALL, 5)
        
        self.reset_rss_btn = wx.Button(rss_settings_panel, label="Reset RSS (Clear all feeds and rules)")
        self.reset_rss_btn.Bind(wx.EVT_BUTTON, self.on_reset_rss)
        rss_settings_sizer.Add(self.reset_rss_btn, 0, wx.ALL, 10)
        
        rss_settings_panel.SetSizer(rss_settings_sizer)
        notebook.AddPage(rss_settings_panel, "RSS")
        
        # --- Web UI Tab ---
        web_panel = wx.Panel(notebook)
        web_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.web_enabled_chk = wx.CheckBox(web_panel, label="Enable Web UI")
        self.web_enabled_chk.SetValue(self.prefs.get('web_ui_enabled', False))
        web_sizer.Add(self.web_enabled_chk, 0, wx.ALL, 10)
        
        grid = wx.FlexGridSizer(4, 2, 10, 10)
        grid.Add(wx.StaticText(web_panel, label="Bind Host:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.web_host = wx.TextCtrl(web_panel, value=self.prefs.get('web_ui_host', '127.0.0.1'))
        grid.Add(self.web_host, 0, wx.EXPAND)

        grid.Add(wx.StaticText(web_panel, label="Port:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.web_port = wx.SpinCtrl(web_panel, min=1, max=65535, initial=self.prefs.get('web_ui_port', 8080))
        grid.Add(self.web_port, 0, wx.EXPAND)
        
        grid.Add(wx.StaticText(web_panel, label="Username:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.web_user = wx.TextCtrl(web_panel, value=self.prefs.get('web_ui_user', 'admin'))
        grid.Add(self.web_user, 0, wx.EXPAND)
        
        grid.Add(wx.StaticText(web_panel, label="Password:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.web_pass = wx.TextCtrl(web_panel, value=self.prefs.get('web_ui_pass', 'password'), style=wx.TE_PASSWORD)
        grid.Add(self.web_pass, 0, wx.EXPAND)
        
        web_sizer.Add(grid, 0, wx.ALL, 10)
        web_panel.SetSizer(web_sizer)
        notebook.AddPage(web_panel, "Web UI")
        
        # --- Proxy Tab ---
        proxy_panel = wx.Panel(notebook)
        proxy_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Proxy Type
        proxy_sizer.Add(wx.StaticText(proxy_panel, label="Proxy Type:"), 0, wx.ALL, 5)
        self.proxy_type = wx.Choice(proxy_panel, choices=["None", "SOCKS4", "SOCKS5", "HTTP"])
        self.proxy_type.SetSelection(self.prefs.get('proxy_type', 0))
        proxy_sizer.Add(self.proxy_type, 0, wx.EXPAND | wx.ALL, 5)
        
        # Host & Port
        hp_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        hp_sizer.Add(wx.StaticText(proxy_panel, label="Host:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.proxy_host = wx.TextCtrl(proxy_panel, value=self.prefs.get('proxy_host', ''))
        hp_sizer.Add(self.proxy_host, 1, wx.EXPAND | wx.RIGHT, 10)
        
        hp_sizer.Add(wx.StaticText(proxy_panel, label="Port:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.proxy_port = wx.SpinCtrl(proxy_panel, min=1, max=65535, initial=self.prefs.get('proxy_port', 8080))
        hp_sizer.Add(self.proxy_port, 0)
        
        proxy_sizer.Add(hp_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        # Auth
        proxy_sizer.Add(wx.StaticText(proxy_panel, label="Authentication (if required):"), 0, wx.TOP | wx.LEFT, 10)
        
        user_sizer = wx.BoxSizer(wx.HORIZONTAL)
        user_sizer.Add(wx.StaticText(proxy_panel, label="Username:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.proxy_user = wx.TextCtrl(proxy_panel, value=self.prefs.get('proxy_user', ''))
        user_sizer.Add(self.proxy_user, 1, wx.EXPAND)
        proxy_sizer.Add(user_sizer, 0, wx.EXPAND | wx.ALL, 5)
        
        pass_sizer = wx.BoxSizer(wx.HORIZONTAL)
        pass_sizer.Add(wx.StaticText(proxy_panel, label="Password:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        self.proxy_pass = wx.TextCtrl(proxy_panel, value=self.prefs.get('proxy_password', ''), style=wx.TE_PASSWORD)
        pass_sizer.Add(self.proxy_pass, 1, wx.EXPAND)
        proxy_sizer.Add(pass_sizer, 0, wx.EXPAND | wx.ALL, 5)

        proxy_panel.SetSizer(proxy_sizer)
        notebook.AddPage(proxy_panel, "Proxy")
        
        sizer.Add(notebook, 1, wx.EXPAND | wx.ALL, 5)
        
        # Buttons
        btns = wx.StdDialogButtonSizer()
        btns.AddButton(wx.Button(self, wx.ID_OK))
        btns.AddButton(wx.Button(self, wx.ID_CANCEL))
        btns.Realize()
        sizer.Add(btns, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        
        self.SetSizer(sizer)
        self.Center()

    def on_browse(self, event):
        dlg = wx.DirDialog(self, "Choose Download Directory", self.path_input.GetValue())
        if dlg.ShowModal() == wx.ID_OK:
            self.path_input.SetValue(dlg.GetPath())
        dlg.Destroy()

    def on_reset_rss(self, event):
        if wx.MessageBox("Are you sure you want to clear ALL RSS feeds and rules?", "Confirm Reset", wx.YES_NO | wx.ICON_WARNING) == wx.YES:
            try:
                # We need access to the manager. 
                # Since RSSManager is a singleton-like store, we can just instantiate a temporary one
                # OR use the one from main frame.
                # Simplest is just call reset_all on a new instance since it saves to disk.
                mgr = RSSManager()
                mgr.reset_all()
                wx.MessageBox("RSS data reset successfully.", "Success")
            except Exception as e:
                wx.LogError(f"Reset failed: {e}")

    def get_preferences(self):
        return {
            "download_path": self.path_input.GetValue(),
            "auto_start": self.auto_start_chk.GetValue(),
            "min_to_tray": self.min_tray_chk.GetValue(),
            "close_to_tray": self.close_tray_chk.GetValue(),
            "auto_check_updates": self.auto_update_chk.GetValue() if hasattr(self, "auto_update_chk") else self.prefs.get("auto_check_updates", True),
            "dl_limit": self.dl_limit.GetValue(),
            "ul_limit": self.ul_limit.GetValue(),
            "max_connections": self.max_conn.GetValue(),
            "max_uploads": self.max_slots.GetValue(),
            "listen_port": self.port_input.GetValue(),
            "enable_upnp": self.upnp_chk.GetValue(),
            "enable_natpmp": self.natpmp_chk.GetValue(),
            "enable_dht": self.dht_chk.GetValue() if hasattr(self, "dht_chk") else self.prefs.get("enable_dht", True),
            "enable_lsd": self.lsd_chk.GetValue() if hasattr(self, "lsd_chk") else self.prefs.get("enable_lsd", True),
            "enable_trackers": self.track_chk.GetValue(),
            "tracker_url": self.track_url_input.GetValue(),
            "rss_update_interval": self.rss_interval.GetValue(),
            "web_ui_enabled": self.web_enabled_chk.GetValue(),
            "web_ui_host": self.web_host.GetValue(),
            "web_ui_port": self.web_port.GetValue(),
            "web_ui_user": self.web_user.GetValue(),
            "web_ui_pass": self.web_pass.GetValue(),
            "proxy_type": self.proxy_type.GetSelection(),
            "proxy_host": self.proxy_host.GetValue(),
            "proxy_port": self.proxy_port.GetValue(),
            "proxy_user": self.proxy_user.GetValue(),
            "proxy_password": self.proxy_pass.GetValue()
        }


class RemotePreferencesDialog(wx.Dialog):
    # --- qBittorrent Schema ---
    QBIT_CATEGORY_FIELDS = OrderedDict([
        ("General", [
            "locale", "create_subfolder_enabled", "start_paused_enabled", "auto_delete_mode",
            "preallocate_all", "incomplete_files_ext", "auto_tmm_enabled", "torrent_changed_tmm_enabled",
            "save_path_changed_tmm_enabled", "category_changed_tmm_enabled", "save_path",
            "temp_path_enabled", "temp_path", "scan_dirs", "export_dir", "export_dir_fin"
        ]),
        ("Downloads", [
            "autorun_enabled", "autorun_program", "queueing_enabled", "max_active_downloads",
            "max_active_torrents", "max_active_uploads", "dont_count_slow_torrents",
            "slow_torrent_dl_rate_threshold", "slow_torrent_ul_rate_threshold", "slow_torrent_inactive_timer",
            "max_ratio_enabled", "max_ratio", "max_ratio_act", "add_trackers_enabled", "add_trackers",
            "max_seeding_time_enabled", "max_seeding_time", "announce_ip", "announce_to_all_tiers",
            "announce_to_all_trackers", "recheck_completed_torrents", "resolve_peer_countries",
            "save_resume_data_interval", "send_buffer_low_watermark", "send_buffer_watermark",
            "send_buffer_watermark_factor", "socket_backlog_size"
        ]),
        ("Connection", [
            "listen_port", "upnp", "random_port", "max_connec", "max_connec_per_torrent", "max_uploads",
            "max_uploads_per_torrent", "stop_tracker_timeout", "upnp_lease_duration", "outgoing_ports_min",
            "outgoing_ports_max", "current_interface_address", "current_network_interface"
        ]),
        ("Speed", [
            "dl_limit", "up_limit", "alt_dl_limit", "alt_up_limit"
        ]),
        ("BitTorrent", [
            "dht", "pex", "lsd", "encryption", "anonymous_mode", "proxy_type", "proxy_ip",
            "proxy_port", "proxy_peer_connections", "proxy_auth_enabled", "proxy_username",
            "proxy_password", "proxy_torrents_only", "bittorrent_protocol", "enable_piece_extent_affinity",
            "limit_utp_rate", "limit_tcp_overhead", "limit_lan_peers", "async_io_threads", "banned_IPs",
            "checking_memory_use", "disk_cache", "disk_cache_ttl", "embedded_tracker_port",
            "enable_coalesce_read_write", "enable_embedded_tracker", "enable_multi_connections_from_same_ip",
            "enable_os_cache", "enable_upload_suggestions", "file_pool_size", "upload_choking_algorithm",
            "upload_slots_behavior", "utp_tcp_mixed_mode"
        ]),
        ("Scheduler", [
            "scheduler_enabled", "schedule_from_hour", "schedule_from_min", "schedule_to_hour",
            "schedule_to_min", "scheduler_days"
        ]),
        ("Web UI", [
            "web_ui_domain_list", "web_ui_address", "web_ui_port", "web_ui_upnp", "web_ui_username",
            "web_ui_password", "web_ui_csrf_protection_enabled", "web_ui_clickjacking_protection_enabled",
            "web_ui_secure_cookie_enabled", "web_ui_max_auth_fail_count", "web_ui_ban_duration",
            "web_ui_session_timeout", "web_ui_host_header_validation_enabled", "bypass_local_auth",
            "bypass_auth_subnet_whitelist_enabled", "bypass_auth_subnet_whitelist",
            "alternative_webui_enabled", "alternative_webui_path", "use_https", "ssl_key", "ssl_cert",
            "web_ui_https_key_path", "web_ui_https_cert_path", "dyndns_enabled", "dyndns_service",
            "dyndns_username", "dyndns_password", "dyndns_domain", "web_ui_use_custom_http_headers_enabled",
            "web_ui_custom_http_headers"
        ]),
        ("Notifications", [
            "mail_notification_enabled", "mail_notification_sender", "mail_notification_email",
            "mail_notification_smtp", "mail_notification_ssl_enabled", "mail_notification_auth_enabled",
            "mail_notification_username", "mail_notification_password", "rss_refresh_interval",
            "rss_max_articles_per_feed", "rss_processing_enabled", "rss_auto_downloading_enabled",
            "rss_download_repack_proper_episodes", "rss_smart_episode_filters"
        ])
    ])

    QBIT_BOOL_KEYS = {
        "create_subfolder_enabled", "start_paused_enabled", "preallocate_all", "incomplete_files_ext",
        "auto_tmm_enabled", "torrent_changed_tmm_enabled", "save_path_changed_tmm_enabled",
        "category_changed_tmm_enabled", "temp_path_enabled", "mail_notification_enabled",
        "mail_notification_ssl_enabled", "mail_notification_auth_enabled", "autorun_enabled",
        "queueing_enabled", "dont_count_slow_torrents", "max_ratio_enabled", "upnp", "random_port",
        "limit_utp_rate", "limit_tcp_overhead", "limit_lan_peers", "scheduler_enabled", "dht", "pex",
        "lsd", "anonymous_mode", "proxy_peer_connections", "proxy_auth_enabled", "proxy_torrents_only",
        "ip_filter_enabled", "ip_filter_trackers", "web_ui_upnp", "web_ui_csrf_protection_enabled",
        "web_ui_clickjacking_protection_enabled", "web_ui_secure_cookie_enabled",
        "web_ui_host_header_validation_enabled", "bypass_local_auth",
        "bypass_auth_subnet_whitelist_enabled", "alternative_webui_enabled", "use_https",
        "dyndns_enabled", "rss_processing_enabled", "rss_auto_downloading_enabled",
        "rss_download_repack_proper_episodes", "add_trackers_enabled",
        "web_ui_use_custom_http_headers_enabled", "max_seeding_time_enabled",
        "announce_to_all_tiers", "announce_to_all_trackers", "enable_piece_extent_affinity",
        "enable_coalesce_read_write", "enable_embedded_tracker",
        "enable_multi_connections_from_same_ip", "enable_os_cache", "enable_upload_suggestions",
        "recheck_completed_torrents", "resolve_peer_countries"
    }

    QBIT_MULTILINE_FIELDS = {
        "add_trackers", "banned_IPs", "bypass_auth_subnet_whitelist",
        "web_ui_custom_http_headers", "rss_smart_episode_filters", "ssl_key", "ssl_cert"
    }

    QBIT_JSON_FIELDS = {"scan_dirs"}
    QBIT_PASSWORD_FIELDS = {"proxy_password", "mail_notification_password", "web_ui_password", "dyndns_password"}

    QBIT_ENUM_CHOICES = {
        "scheduler_days": [
            ("Every day", 0), ("Every weekday", 1), ("Every weekend", 2), ("Every Monday", 3),
            ("Every Tuesday", 4), ("Every Wednesday", 5), ("Every Thursday", 6),
            ("Every Friday", 7), ("Every Saturday", 8), ("Every Sunday", 9)
        ],
        "encryption": [
            ("Prefer encryption", 0), ("Force encryption on", 1), ("Force encryption off", 2)
        ],
        "proxy_type": [
            ("Proxy disabled", -1), ("HTTP (no auth)", 1), ("SOCKS5 (no auth)", 2),
            ("HTTP (with auth)", 3), ("SOCKS5 (with auth)", 4), ("SOCKS4 (no auth)", 5)
        ],
        "dyndns_service": [
            ("Use DyDNS", 0), ("Use NOIP", 1)
        ],
        "max_ratio_act": [
            ("Pause torrent", 0), ("Remove torrent", 1)
        ],
        "bittorrent_protocol": [
            ("TCP and uTP", 0), ("TCP", 1), ("uTP", 2)
        ],
        "upload_choking_algorithm": [
            ("Round-robin", 0), ("Fastest upload", 1), ("Anti-leech", 2)
        ],
        "upload_slots_behavior": [
            ("Fixed slots", 0), ("Upload-rate based", 1)
        ],
        "utp_tcp_mixed_mode": [
            ("Prefer TCP", 0), ("Peer proportional", 1)
        ]
    }

    # --- Transmission Schema ---
    TRANS_CATEGORY_FIELDS = OrderedDict([
        ("Speed", [
            "speed_limit_down_enabled", "speed_limit_down",
            "speed_limit_up_enabled", "speed_limit_up"
        ]),
        ("Scheduling", [
            "alt_speed_enabled", "alt_speed_down", "alt_speed_up",
            "alt_speed_time_enabled", "alt_speed_time_begin", "alt_speed_time_end",
            "alt_speed_time_day"
        ]),
        ("Network", [
            "peer_port", "peer_port_random_on_start",
            "port_forwarding_enabled", "utp_enabled",
            "dht_enabled", "pex_enabled", "lpd_enabled", "encryption",
            "blocklist_enabled", "blocklist_url"
        ]),
        ("Limits", [
            "peer_limit_global", "peer_limit_per_torrent",
            "idle_seeding_limit_enabled", "idle_seeding_limit",
            "seedRatioLimited", "seedRatioLimit"
        ]),
        ("Queue", [
            "download_queue_enabled", "download_queue_size",
            "seed_queue_enabled", "seed_queue_size"
        ]),
        ("Files", [
            "download_dir", "incomplete_dir_enabled", "incomplete_dir",
            "rename_partial_files", "trash_original_torrent_files",
            "start_added_torrents", "cache_size_mb"
        ]),
        ("Scripts", [
            "script_torrent_done_enabled", "script_torrent_done_filename"
        ])
    ])
    
    TRANS_BOOL_KEYS = {
        "speed_limit_down_enabled", "speed_limit_up_enabled",
        "alt_speed_enabled", "alt_speed_time_enabled",
        "peer_port_random_on_start", "port_forwarding_enabled",
        "utp_enabled", "dht_enabled", "pex_enabled", "lpd_enabled",
        "blocklist_enabled", "idle_seeding_limit_enabled", "seedRatioLimited",
        "download_queue_enabled", "seed_queue_enabled",
        "incomplete_dir_enabled", "rename_partial_files",
        "trash_original_torrent_files", "start_added_torrents",
        "script_torrent_done_enabled"
    }
    
    # --- rTorrent Schema ---
    RTORRENT_CATEGORY_FIELDS = OrderedDict([
        ("Speed", ["dl_limit", "ul_limit"]),
        ("Network", ["port_range", "dht_mode", "pex_enabled", "use_udp_trackers", "encryption", "proxy_address"]),
        ("Limits", ["max_peers", "min_peers", "max_uploads"]),
        ("General", ["directory_default", "check_hash"])
    ])
    RTORRENT_BOOL_KEYS = {"check_hash", "pex_enabled", "use_udp_trackers"}
    RTORRENT_ENUM_CHOICES = {
        "dht_mode": [("Auto", "auto"), ("On", "on"), ("Off", "off")]
    }

    # --- Local Schema ---
    LOCAL_CATEGORY_FIELDS = OrderedDict([
        ("General", ["download_path", "auto_start", "min_to_tray", "close_to_tray"]),
        ("Connection", ["dl_limit", "ul_limit", "max_connections", "max_uploads", "listen_port", "enable_upnp", "enable_natpmp", "enable_dht", "enable_lsd"]),
        ("Trackers", ["enable_trackers", "tracker_url"]),
        ("RSS", ["rss_update_interval"]),
        ("Web UI", ["web_ui_enabled", "web_ui_port", "web_ui_user", "web_ui_pass"]),
        ("Proxy", ["proxy_type", "proxy_host", "proxy_port", "proxy_user", "proxy_password"])
    ])
    LOCAL_BOOL_KEYS = {"auto_start", "min_to_tray", "close_to_tray", "enable_upnp", "enable_natpmp", "enable_dht", "enable_lsd", "enable_trackers", "web_ui_enabled"}
    LOCAL_ENUM_CHOICES = {
        "proxy_type": [("None", 0), ("SOCKS4", 1), ("SOCKS5", 2), ("HTTP", 3)]
    }

    def __init__(self, parent, prefs, client_name="qBittorrent"):
        super().__init__(parent, title=f"{client_name} Remote Settings", size=(900, 640))
        self.prefs = OrderedDict(prefs or {})
        self.field_controls = {}
        self.client_name = client_name

        # Select Schema
        if client_name == "Transmission":
            self.CATEGORY_FIELDS = self.TRANS_CATEGORY_FIELDS
            self.BOOL_KEYS = self.TRANS_BOOL_KEYS
            self.MULTILINE_FIELDS = set()
            self.JSON_FIELDS = set()
            self.PASSWORD_FIELDS = set()
            self.ENUM_CHOICES = {}
        elif client_name == "rTorrent":
            self.CATEGORY_FIELDS = self.RTORRENT_CATEGORY_FIELDS
            self.BOOL_KEYS = self.RTORRENT_BOOL_KEYS
            self.MULTILINE_FIELDS = set()
            self.JSON_FIELDS = set()
            self.PASSWORD_FIELDS = set()
            self.ENUM_CHOICES = self.RTORRENT_ENUM_CHOICES
        elif client_name == "Local":
            self.CATEGORY_FIELDS = self.LOCAL_CATEGORY_FIELDS
            self.BOOL_KEYS = self.LOCAL_BOOL_KEYS
            self.MULTILINE_FIELDS = set()
            self.JSON_FIELDS = set()
            self.PASSWORD_FIELDS = {"proxy_password", "web_ui_pass"}
            self.ENUM_CHOICES = self.LOCAL_ENUM_CHOICES
        else:
            # Default to qBittorrent
            self.CATEGORY_FIELDS = self.QBIT_CATEGORY_FIELDS
            self.BOOL_KEYS = self.QBIT_BOOL_KEYS
            self.MULTILINE_FIELDS = self.QBIT_MULTILINE_FIELDS
            self.JSON_FIELDS = self.QBIT_JSON_FIELDS
            self.PASSWORD_FIELDS = self.QBIT_PASSWORD_FIELDS
            self.ENUM_CHOICES = self.QBIT_ENUM_CHOICES

        sizer = wx.BoxSizer(wx.VERTICAL)

        notebook = wx.Notebook(self)
        assigned = set()

        for category, keys in self.CATEGORY_FIELDS.items():
            selected_keys = [key for key in keys if key in self.prefs]
            if not selected_keys:
                continue
            panel = self._build_category_panel(notebook, category, selected_keys)
            notebook.AddPage(panel, category)
            assigned.update(selected_keys)

        # For qBittorrent, show advanced/remaining. For others, maybe not necessary or confusing.
        # But good to show unclassified keys if any.
        remaining = [k for k in self.prefs if k not in assigned]
        if remaining:
            panel = self._build_category_panel(notebook, "Other", remaining)
            notebook.AddPage(panel, "Other")

        if notebook.GetPageCount() == 0:
            placeholder = wx.Panel(notebook)
            placeholder_sizer = wx.BoxSizer(wx.VERTICAL)
            placeholder_sizer.Add(
                wx.StaticText(placeholder, label="Remote client did not return any recognized preferences."),
                1,
                wx.ALL | wx.EXPAND,
                10
            )
            placeholder.SetSizer(placeholder_sizer)
            notebook.AddPage(placeholder, "Preferences")

        sizer.Add(notebook, 1, wx.EXPAND | wx.ALL, 5)

        btns = wx.StdDialogButtonSizer()
        btns.AddButton(wx.Button(self, wx.ID_OK))
        btns.AddButton(wx.Button(self, wx.ID_CANCEL))
        btns.Realize()
        sizer.Add(btns, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        self.SetSizer(sizer)
        self.Layout()
        self.Center()

    def _build_category_panel(self, parent, category, keys):
        panel = wx.ScrolledWindow(parent, style=wx.VSCROLL)
        panel.SetScrollRate(0, 10)
        panel.SetMinSize((840, 360))
        layout = wx.BoxSizer(wx.VERTICAL)

        for key in keys:
            field = self._create_field(panel, key)
            layout.Add(field, 0, wx.EXPAND | wx.ALL, 4)

        panel.SetSizer(layout)
        panel.Layout()
        panel.FitInside()
        return panel

    def _create_field(self, panel, key):
        value = self.prefs.get(key)
        field_type = self._determine_field_type(key, value)
        field_sizer = wx.BoxSizer(wx.HORIZONTAL)

        if field_type == "bool":
            label = self._format_label(key)
            control = wx.CheckBox(panel, label=label)
            control.SetValue(bool(value))
            field_sizer.Add(control, 1, wx.ALIGN_CENTER_VERTICAL)
        else:
            label_ctrl = wx.StaticText(panel, label=f"{self._format_label(key)}:")
            field_sizer.Add(label_ctrl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
            control = self._create_non_bool_control(panel, key, value, field_type)
            field_sizer.Add(control, 1, wx.EXPAND)

        self.field_controls[key] = {
            "control": control,
            "type": field_type,
            "choices": self.ENUM_CHOICES.get(key)
        }
        return field_sizer

    def _create_non_bool_control(self, panel, key, value, field_type):
        if field_type == "choice":
            choices = [label for label, _ in self.ENUM_CHOICES.get(key, [])]
            control = wx.Choice(panel, choices=choices)
            selection = 0
            for idx, (_, val) in enumerate(self.ENUM_CHOICES.get(key, [])):
                if val == value:
                    selection = idx
                    break
            control.SetSelection(selection)
            return control

        style = 0
        if key in self.MULTILINE_FIELDS or field_type == "json":
            style |= wx.TE_MULTILINE
        if key in self.PASSWORD_FIELDS:
            style |= wx.TE_PASSWORD

        control = wx.TextCtrl(panel, style=style | wx.TE_RICH2 if field_type == "json" else style)

        if field_type == "json":
            payload = json.dumps(value, indent=2) if value else ""
            control.SetValue(payload)
            control.SetMinSize((420, 100))
            control.SetToolTip("Enter a JSON object (e.g. {\"/watched\": \"/home/user\"}).")
            return control

        text_value = ""
        if value is not None:
            text_value = str(value)
        control.SetValue(text_value)
        control.SetMinSize((420, 24 if not (style & wx.TE_MULTILINE) else 100))
        if key in self.PASSWORD_FIELDS:
            control.SetHint("Leave blank to retain the current password.")
        return control

    def _determine_field_type(self, key, value):
        if key in self.BOOL_KEYS:
            return "bool"
        if isinstance(value, bool):
            return "bool"
        if key in self.ENUM_CHOICES:
            return "choice"
        if key in self.JSON_FIELDS or isinstance(value, (dict, list)):
            return "json"
        if isinstance(value, float):
            return "float"
        if isinstance(value, int):
            return "int"
        return "string"

    def _format_label(self, key):
        label = key.replace("_", " ").title()
        replacements = {
            "Web Ui": "Web UI",
            "Ssl": "SSL",
            "Http": "HTTP",
            "Dns": "DNS",
            "Ip": "IP",
            "Ut P": "uTP",
            "Tcp": "TCP",
            "Lng": "LNG"
        }
        for old, new in replacements.items():
            label = label.replace(old, new)
        return label

    def GetPreferences(self):
        prefs = {}
        for key, meta in self.field_controls.items():
            control = meta["control"]
            field_type = meta["type"]

            if field_type == "bool":
                prefs[key] = bool(control.GetValue())
                continue

            if field_type == "choice":
                selection = control.GetSelection()
                choices = meta.get("choices") or []
                if choices and selection >= 0:
                    prefs[key] = choices[selection][1]
                continue

            text = control.GetValue()

            if field_type == "json":
                stripped = text.strip()
                if not stripped:
                    prefs[key] = {}
                    continue
                try:
                    prefs[key] = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSON for {self._format_label(key)}: {exc}")
                continue

            if field_type == "int":
                stripped = text.strip()
                if stripped == "":
                    prefs[key] = self.prefs.get(key, 0)
                    continue
                try:
                    prefs[key] = int(stripped)
                except ValueError as exc:
                    raise ValueError(f"Invalid integer for {self._format_label(key)}: {exc}")
                continue

            if field_type == "float":
                stripped = text.strip()
                if stripped == "":
                    prefs[key] = self.prefs.get(key, 0.0)
                    continue
                try:
                    prefs[key] = float(stripped)
                except ValueError as exc:
                    raise ValueError(f"Invalid number for {self._format_label(key)}: {exc}")
                continue

            if key in self.PASSWORD_FIELDS and not text:
                continue

            prefs[key] = text

        return prefs

class FilesListCtrl(wx.ListCtrl):
    def __init__(self, parent):
        super().__init__(parent, style=wx.LC_REPORT | wx.LC_VIRTUAL | wx.LC_HRULES | wx.LC_VRULES)
        self.InsertColumn(0, "Name", width=400)
        self.InsertColumn(1, "Size", width=100)
        self.InsertColumn(2, "Progress", width=100)
        self.InsertColumn(3, "Priority", width=100)
        self.data = []

    def set_data(self, data):
        self.data = data
        self.SetItemCount(len(data))
        self.Refresh()

    def OnGetItemText(self, item, col):
        if item >= len(self.data):
            return ""
        row = self.data[item]
        if col == 0:
            return os.path.basename(row['name'])
        if col == 1:
            size = row['size']
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if size < 1024:
                    return f"{size:.1f} {unit}"
                size /= 1024
            return f"{size:.1f} PB"
        if col == 2:
            return f"{row['progress']*100:.1f}%"
        if col == 3:
            p = row['priority']
            if p == 0:
                return "Skip"
            if p == 1:
                return "Normal"
            if p == 2:
                return "High"
            return str(p)
        return ""

class PeersListCtrl(wx.ListCtrl):
    def __init__(self, parent):
        super().__init__(parent, style=wx.LC_REPORT | wx.LC_VIRTUAL | wx.LC_HRULES | wx.LC_VRULES)
        self.InsertColumn(0, "IP", width=150)
        self.InsertColumn(1, "Client", width=150)
        self.InsertColumn(2, "Progress", width=80)
        self.InsertColumn(3, "Down Speed", width=100)
        self.InsertColumn(4, "Up Speed", width=100)
        self.data = []

    def set_data(self, data):
        self.data = data
        self.SetItemCount(len(data))
        self.Refresh()

    def OnGetItemText(self, item, col):
        if item >= len(self.data):
            return ""
        row = self.data[item]
        if col == 0:
            return row['address']
        if col == 1:
            return row['client']
        if col == 2:
            return f"{row['progress']*100:.1f}%"
        if col == 3:
            return self.fmt_speed(row['down_rate'])
        if col == 4:
            return self.fmt_speed(row['up_rate'])
        return ""

    def fmt_speed(self, rate):
        if rate <= 0:
            return "0 B/s"
        for unit in ['B/s', 'KB/s', 'MB/s', 'GB/s']:
            if rate < 1024:
                return f"{rate:.1f} {unit}"
            rate /= 1024
        return f"{rate:.1f} TB/s"

class TrackersListCtrl(wx.ListCtrl):
    def __init__(self, parent):
        super().__init__(parent, style=wx.LC_REPORT | wx.LC_VIRTUAL | wx.LC_HRULES | wx.LC_VRULES)
        self.InsertColumn(0, "URL", width=300)
        self.InsertColumn(1, "Status", width=100)
        self.InsertColumn(2, "Peers", width=80)
        self.InsertColumn(3, "Message", width=300)
        self.data = []

    def set_data(self, data):
        self.data = data
        self.SetItemCount(len(data))
        self.Refresh()

    def OnGetItemText(self, item, col):
        if item >= len(self.data):
            return ""
        row = self.data[item]
        if col == 0:
            return row['url']
        if col == 1:
            return row['status']
        if col == 2:
            return str(row['peers'])
        if col == 3:
            return row['message']
        return ""

class TorrentDetailsPanel(wx.Panel):
    def __init__(self, parent, frame):
        super().__init__(parent)
        self.frame = frame
        self.current_hash = None
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.notebook = wx.Notebook(self)
        self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, lambda e: self.refresh_tab())
        
        # Files Tab
        self.files_panel = wx.Panel(self.notebook)
        fp_sizer = wx.BoxSizer(wx.VERTICAL)
        self.files_list = FilesListCtrl(self.files_panel)
        self.files_list.Bind(wx.EVT_CONTEXT_MENU, self.on_files_context_menu)
        self.files_list.Bind(wx.EVT_RIGHT_DOWN, self.on_files_context_menu)
        fp_sizer.Add(self.files_list, 1, wx.EXPAND)
        self.files_panel.SetSizer(fp_sizer)
        
        # Peers Tab
        self.peers_panel = wx.Panel(self.notebook)
        pp_sizer = wx.BoxSizer(wx.VERTICAL)
        self.peers_list = PeersListCtrl(self.peers_panel)
        pp_sizer.Add(self.peers_list, 1, wx.EXPAND)
        self.peers_panel.SetSizer(pp_sizer)

        # Trackers Tab
        self.trackers_panel = wx.Panel(self.notebook)
        tp_sizer = wx.BoxSizer(wx.VERTICAL)
        self.trackers_list = TrackersListCtrl(self.trackers_panel)
        tp_sizer.Add(self.trackers_list, 1, wx.EXPAND)
        self.trackers_panel.SetSizer(tp_sizer)

        self.notebook.AddPage(self.files_panel, "Files")
        self.notebook.AddPage(self.peers_panel, "Peers")
        self.notebook.AddPage(self.trackers_panel, "Trackers")
        
        sizer.Add(self.notebook, 1, wx.EXPAND)
        self.SetSizer(sizer)

    def load_torrent(self, info_hash):
        self.current_hash = info_hash
        self.refresh_tab()

    def refresh_tab(self):
        if not self.current_hash or not self.frame.client:
            self.files_list.set_data([])
            self.peers_list.set_data([])
            self.trackers_list.set_data([])
            return
            
        sel = self.notebook.GetSelection()
        if sel == 0: # Files
            self.frame.thread_pool.submit(self._fetch_files, self.current_hash)
        elif sel == 1: # Peers
            self.frame.thread_pool.submit(self._fetch_peers, self.current_hash)
        elif sel == 2: # Trackers
            self.frame.thread_pool.submit(self._fetch_trackers, self.current_hash)

    def _fetch_files(self, info_hash):
        try:
            files = self.frame.client.get_files(info_hash)
            wx.CallAfter(self.files_list.set_data, files)
        except Exception:
            pass

    def _fetch_peers(self, info_hash):
        try:
            peers = self.frame.client.get_peers(info_hash)
            wx.CallAfter(self.peers_list.set_data, peers)
        except Exception:
            pass

    def _fetch_trackers(self, info_hash):
        try:
            trackers = self.frame.client.get_trackers(info_hash)
            wx.CallAfter(self.trackers_list.set_data, trackers)
        except Exception:
            pass

    def on_files_context_menu(self, event):
        if not self.files_list.GetSelectedItemCount():
            return
        
        menu = wx.Menu()
        prio_menu = wx.Menu()
        
        high = prio_menu.Append(wx.ID_ANY, "High")
        normal = prio_menu.Append(wx.ID_ANY, "Normal")
        skip = prio_menu.Append(wx.ID_ANY, "Skip")
        
        menu.AppendSubMenu(prio_menu, "Priority")
        
        self.Bind(wx.EVT_MENU, lambda e: self.set_priority(2), high)
        self.Bind(wx.EVT_MENU, lambda e: self.set_priority(1), normal)
        self.Bind(wx.EVT_MENU, lambda e: self.set_priority(0), skip)
        
        self.PopupMenu(menu)
        menu.Destroy()

    def set_priority(self, priority):
        if not self.current_hash or not self.frame.client:
            return
        
        # Get selected indices
        item = self.files_list.GetFirstSelected()
        indices = []
        while item != -1:
            indices.append(self.files_list.data[item]['index'])
            item = self.files_list.GetNextSelected(item)
            
        if indices:
            self.frame.thread_pool.submit(self._set_priority_bg, self.current_hash, indices, priority)

    def _set_priority_bg(self, info_hash, indices, priority):
        try:
            # Batch optimization if possible? Client supports list?
            # Our BaseClient interface is per-file: set_file_priority(hash, idx, prio)
            # We can loop here.
            for idx in indices:
                self.frame.client.set_file_priority(info_hash, idx, priority)
            
            # Refresh
            self._fetch_files(info_hash)
        except Exception:
            pass

class TaskBarIcon(wx.adv.TaskBarIcon):
    def __init__(self, frame):
        super().__init__()
        self.frame = frame
        self.SetIcon(get_app_icon(), APP_NAME)
        # Bind both double click and single click (UP) to restore.
        # This ensures Enter (often mapped to click/dblclick) and single left click open the app.
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, self.on_restore)
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_UP, self.on_restore)

    def CreatePopupMenu(self):
        menu = wx.Menu()

        start_all_item = menu.Append(wx.ID_ANY, "Start All")
        stop_all_item = menu.Append(wx.ID_ANY, "Stop All")
        self.Bind(wx.EVT_MENU, self.on_start_all, start_all_item)
        self.Bind(wx.EVT_MENU, self.on_stop_all, stop_all_item)

        # Switch Profile submenu (mirrors File -> Connect)
        switch_menu = wx.Menu()
        try:
            profiles = self.frame.config_manager.get_profiles() or {}
        except Exception:
            profiles = {}

        try:
            default_id = self.frame.config_manager.get_default_profile_id()
        except Exception:
            default_id = None

        current_id = getattr(self.frame, "current_profile_id", None)

        if profiles:
            def _sort_key(kv):
                pid, p = kv
                return str(p.get("name", pid)).lower()

            for pid, p in sorted(profiles.items(), key=_sort_key):
                label = str(p.get("name") or pid)
                if default_id and pid == default_id:
                    label += " (Default)"
                if current_id and pid == current_id:
                    label += " (Current)"
                item = switch_menu.Append(wx.ID_ANY, label, "Connect to this profile")
                self.Bind(wx.EVT_MENU, lambda evt, pid=pid: self._on_switch_profile_pid(pid), item)

            switch_menu.AppendSeparator()

        manage_item = switch_menu.Append(wx.ID_ANY, "Connection Manager...", "Add/edit/delete profiles and connect")
        self.Bind(wx.EVT_MENU, self.on_connection_manager, manage_item)

        menu.AppendSubMenu(switch_menu, "Switch Profile")

        menu.AppendSeparator()
        settings_menu = wx.Menu()
        try:
            local_settings_item = settings_menu.Append(wx.ID_PREFERENCES, "Local Session Settings...")
        except Exception:
            local_settings_item = settings_menu.Append(wx.ID_ANY, "Local Session Settings...")
        self.Bind(wx.EVT_MENU, self.on_local_settings, local_settings_item)

        settings_menu.AppendSeparator()

        qbit_settings_item = settings_menu.Append(wx.ID_ANY, "qBittorrent Remote Settings...")
        trans_settings_item = settings_menu.Append(wx.ID_ANY, "Transmission Remote Settings...")
        rtorrent_settings_item = settings_menu.Append(wx.ID_ANY, "rTorrent Remote Settings...")

        is_qbit = isinstance(self.frame.client, QBittorrentClient) and self.frame.connected
        is_trans = isinstance(self.frame.client, TransmissionClient) and self.frame.connected
        is_rtorrent = isinstance(self.frame.client, RTorrentClient) and self.frame.connected

        qbit_settings_item.Enable(is_qbit)
        trans_settings_item.Enable(is_trans)
        rtorrent_settings_item.Enable(is_rtorrent)

        self.Bind(wx.EVT_MENU, self.on_remote_settings, qbit_settings_item)
        self.Bind(wx.EVT_MENU, self.on_remote_settings, trans_settings_item)
        self.Bind(wx.EVT_MENU, self.on_remote_settings, rtorrent_settings_item)

        menu.AppendSubMenu(settings_menu, "Settings")

        open_item = menu.Append(wx.ID_ANY, f"Open {APP_NAME}")
        self.Bind(wx.EVT_MENU, self.on_restore, open_item)

        menu.AppendSeparator()
        exit_item = menu.Append(wx.ID_EXIT, "Exit")
        self.Bind(wx.EVT_MENU, self.on_exit, exit_item)
        return menu

    def on_double_click(self, event):
        self.on_restore(event)

    def on_restore(self, event):
        self.frame.show_from_tray()

    def _on_switch_profile_pid(self, profile_id):
        # Restore the UI first so screen readers land correctly, then connect.
        wx.CallAfter(self.frame.show_from_tray)
        wx.CallAfter(self.frame.connect_profile, profile_id)

    def on_connection_manager(self, event):
        wx.CallAfter(self.frame.show_from_tray)
        wx.CallAfter(self.frame.on_connect, None)

    def on_local_settings(self, event):
        wx.CallAfter(self.frame.show_from_tray)
        wx.CallAfter(self.frame.on_prefs, None)

    def on_remote_settings(self, event):
        wx.CallAfter(self.frame.show_from_tray)
        wx.CallAfter(self.frame.on_remote_preferences, None)


    def on_start(self, event):
        wx.CallAfter(self.frame.on_start, None)

    def on_stop(self, event):
        wx.CallAfter(self.frame.on_stop, None)

    def on_pause(self, event):
        wx.CallAfter(self.frame.on_pause, None)

    def on_resume(self, event):
        wx.CallAfter(self.frame.on_resume, None)

    def on_switch_profile(self, profile_id):
        wx.CallAfter(self.frame.connect_profile, profile_id)
    def on_start_all(self, event):
        wx.CallAfter(self.frame.start_all_torrents)

    def on_stop_all(self, event):
        wx.CallAfter(self.frame.stop_all_torrents)


    def on_exit(self, event):
        self.frame.force_close()

class ArticleListCtrl(wx.ListCtrl):
    def __init__(self, parent, panel):
        super().__init__(parent, style=wx.LC_REPORT | wx.LC_VIRTUAL)
        self.panel = panel
        self.InsertColumn(0, "Title", width=400)
        self.InsertColumn(1, "Link", width=300)

    def OnGetItemText(self, item, col):
        if item < len(self.panel.current_articles):
            a = self.panel.current_articles[item]
            if col == 0:
                return a['title']
            if col == 1:
                return a['link']
        return ""

class RuleEditDialog(wx.Dialog):
    def __init__(self, parent, manager, rule=None):
        title = "Edit RSS Rule" if rule else "Add RSS Rule"
        super().__init__(parent, title=title, size=(500, 500))
        self.manager = manager
        self.rule = rule or {'pattern': '', 'type': 'accept', 'scope': None, 'enabled': True}
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Pattern
        sizer.Add(wx.StaticText(self, label="Regex Pattern:"), 0, wx.ALL, 5)
        self.pattern_input = wx.TextCtrl(self, value=self.rule['pattern'])
        sizer.Add(self.pattern_input, 0, wx.EXPAND | wx.ALL, 5)
        
        # Type
        sizer.Add(wx.StaticText(self, label="Rule Type:"), 0, wx.ALL, 5)
        self.type_choice = wx.Choice(self, choices=["accept", "reject"])
        self.type_choice.SetStringSelection(self.rule.get('type', 'accept'))
        sizer.Add(self.type_choice, 0, wx.EXPAND | wx.ALL, 5)
        
        # Scope (Feeds)
        sizer.Add(wx.StaticText(self, label="Apply to Feeds (Uncheck all for Global):"), 0, wx.ALL, 5)
        
        self.feeds_list = [] # List of URLs
        display_names = []
        for url, data in self.manager.feeds.items():
            self.feeds_list.append(url)
            display_names.append(data.get('alias') or url)
            
        self.check_list = wx.CheckListBox(self, choices=display_names)
        
        # Set initial checks
        scope = self.rule.get('scope')
        if scope:
            for i, url in enumerate(self.feeds_list):
                if url in scope:
                    self.check_list.Check(i)
                    
        sizer.Add(self.check_list, 1, wx.EXPAND | wx.ALL, 5)
        
        # Buttons
        btns = wx.StdDialogButtonSizer()
        btns.AddButton(wx.Button(self, wx.ID_OK))
        btns.AddButton(wx.Button(self, wx.ID_CANCEL))
        btns.Realize()
        sizer.Add(btns, 0, wx.ALIGN_CENTER | wx.ALL, 10)
        
        self.SetSizer(sizer)
        self.Center()

    def get_rule_data(self):
        checked_indices = self.check_list.GetCheckedItems()
        scope = None
        if checked_indices:
            scope = [self.feeds_list[i] for i in checked_indices]
            
        return {
            'pattern': self.pattern_input.GetValue(),
            'type': self.type_choice.GetStringSelection(),
            'scope': scope,
            'enabled': self.rule.get('enabled', True)
        }

class RulesManagerDialog(wx.Dialog):
    def __init__(self, parent, manager):
        super().__init__(parent, title="RSS Rules Manager", size=(750, 450))
        self.manager = manager
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self.list.InsertColumn(0, "Type", width=80)
        self.list.InsertColumn(1, "Pattern", width=350)
        self.list.InsertColumn(2, "Scope", width=100)
        self.list.InsertColumn(3, "Enabled", width=80)
        
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_edit)
        
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 10)
        
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        add_btn = wx.Button(self, label="Add Rule")
        add_btn.Bind(wx.EVT_BUTTON, self.on_add)
        btn_sizer.Add(add_btn, 0, wx.RIGHT, 5)
        
        edit_btn = wx.Button(self, label="Edit Rule")
        edit_btn.Bind(wx.EVT_BUTTON, self.on_edit)
        btn_sizer.Add(edit_btn, 0, wx.RIGHT, 5)
        
        del_btn = wx.Button(self, label="Delete")
        del_btn.Bind(wx.EVT_BUTTON, self.on_delete)
        btn_sizer.Add(del_btn, 0, wx.RIGHT, 5)
        
        toggle_btn = wx.Button(self, label="Toggle")
        toggle_btn.Bind(wx.EVT_BUTTON, self.on_toggle)
        btn_sizer.Add(toggle_btn, 0, wx.RIGHT, 5)
        
        close_btn = wx.Button(self, wx.ID_OK, label="Close")
        btn_sizer.Add(close_btn, 0)
        
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)
        
        self.SetSizer(sizer)
        self.refresh_list()

    def refresh_list(self):
        self.list.DeleteAllItems()
        for i, rule in enumerate(self.manager.rules):
            idx = self.list.InsertItem(i, rule.get('type', 'accept').title())
            self.list.SetItem(idx, 1, rule['pattern'])
            
            scope = rule.get('scope')
            scope_str = "Global"
            if isinstance(scope, list):
                if not scope:
                    scope_str = "None (No feeds)"
                elif len(scope) == 1:
                    scope_str = "1 feed"
                else:
                    scope_str = f"{len(scope)} feeds"
            
            self.list.SetItem(idx, 2, scope_str)
            self.list.SetItem(idx, 3, "Yes" if rule.get('enabled', True) else "No")

    def on_add(self, event):
        dlg = RuleEditDialog(self, self.manager)
        if dlg.ShowModal() == wx.ID_OK:
            data = dlg.get_rule_data()
            if data['pattern']:
                self.manager.add_rule(data['pattern'], data['type'], data['scope'])
                self.refresh_list()
        dlg.Destroy()

    def on_edit(self, event):
        sel = self.list.GetFirstSelected()
        if sel != -1:
            rule = self.manager.rules[sel]
            dlg = RuleEditDialog(self, self.manager, rule)
            if dlg.ShowModal() == wx.ID_OK:
                data = dlg.get_rule_data()
                self.manager.update_rule(sel, data)
                self.refresh_list()
            dlg.Destroy()

    def on_delete(self, event):
        sel = self.list.GetFirstSelected()
        if sel != -1:
            self.manager.remove_rule(sel)
            self.refresh_list()

    def on_toggle(self, event):
        sel = self.list.GetFirstSelected()
        if sel != -1:
            rule = self.manager.rules[sel]
            rule['enabled'] = not rule.get('enabled', True)
            self.manager.save()
            self.refresh_list()

class RSSPanel(wx.Panel):
    def __init__(self, parent, frame):
        super().__init__(parent)
        self.frame = frame
        self.manager = RSSManager()
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Toolbar
        tb_sizer = wx.BoxSizer(wx.HORIZONTAL)
        add_btn = wx.Button(self, label="Add Feed")
        add_btn.Bind(wx.EVT_BUTTON, self.on_add_feed)
        tb_sizer.Add(add_btn, 0, wx.RIGHT, 5)
        
        del_btn = wx.Button(self, label="Remove Feed")
        del_btn.Bind(wx.EVT_BUTTON, self.on_remove_feed)
        tb_sizer.Add(del_btn, 0, wx.RIGHT, 5)
        
        refresh_btn = wx.Button(self, label="Refresh All")
        refresh_btn.Bind(wx.EVT_BUTTON, self.on_refresh_all)
        tb_sizer.Add(refresh_btn, 0, wx.RIGHT, 5)
        
        rules_btn = wx.Button(self, label="Rules")
        rules_btn.Bind(wx.EVT_BUTTON, self.on_rules)
        tb_sizer.Add(rules_btn, 0, wx.RIGHT, 5)

        import_btn = wx.Button(self, label="Import FlexGet")
        import_btn.Bind(wx.EVT_BUTTON, self.on_import_flexget)
        tb_sizer.Add(import_btn, 0)
        
        sizer.Add(tb_sizer, 0, wx.ALL | wx.EXPAND, 5)
        
        # Splitter
        self.splitter = wx.SplitterWindow(self, style=wx.SP_3D | wx.SP_LIVE_UPDATE)
        
        # Feed List
        self.feed_list = wx.ListBox(self.splitter, style=wx.LB_SINGLE)
        self.feed_list.Bind(wx.EVT_LISTBOX, self.on_feed_selected)
        
        # Article List
        self.article_list = ArticleListCtrl(self.splitter, self)
        self.article_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_download_article)
        
        self.splitter.SplitVertically(self.feed_list, self.article_list, 200)
        sizer.Add(self.splitter, 1, wx.EXPAND)
        
        self.SetSizer(sizer)
        
        self.current_articles = []
        self.refresh_feeds_list()

    def refresh_feeds_list(self):
        self.feed_list.Clear()
        for url in self.manager.feeds:
            data = self.manager.feeds[url]
            alias = data.get('alias')
            label = alias if alias else url
            if data.get('last_error'):
                label += " (Error)"
            self.feed_list.Append(label, url) # Store url as client data

    def on_add_feed(self, event):
        dlg = wx.TextEntryDialog(self, "Enter RSS Feed URL:", "Add Feed")
        if dlg.ShowModal() == wx.ID_OK:
            url = dlg.GetValue()
            if self.manager.add_feed(url):
                self.refresh_feeds_list()
                self.frame.thread_pool.submit(self._update_feed, url)
        dlg.Destroy()

    def on_remove_feed(self, event):
        sel = self.feed_list.GetSelection()
        if sel != wx.NOT_FOUND:
            url = self.feed_list.GetClientData(sel)
            if wx.MessageBox(f"Remove feed {url}?", "Confirm", wx.YES_NO) == wx.YES:
                self.manager.remove_feed(url)
                self.refresh_feeds_list()
                self.article_list.SetItemCount(0)
                self.current_articles = []

    def on_import_flexget(self, event):
        with wx.FileDialog(self, "Import FlexGet Config", wildcard="YAML files (*.yml;*.yaml)|*.yml;*.yaml",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            path = fileDialog.GetPath()
            try:
                feeds, rules = self.manager.import_flexget_config(path)
                wx.MessageBox(f"Imported {feeds} feeds and {rules} rules.", "Import Complete", wx.OK | wx.ICON_INFORMATION)
                self.refresh_feeds_list()
                self.on_refresh_all(None)
            except Exception as e:
                wx.MessageBox(f"Import Failed: {e}", "Error", wx.OK | wx.ICON_ERROR)

    def on_refresh_all(self, event):
        for url in self.manager.feeds:
            self.frame.thread_pool.submit(self._update_feed, url)

    def _update_feed(self, url):
        articles = self.manager.fetch_feed(url)
        # Check auto download (scoped to this feed URL)
        matches = self.manager.get_matches(articles, feed_url=url)
        for m in matches:
            if self.frame.client:
                try:
                    self.frame.client.add_torrent_url(m['link'])
                    wx.CallAfter(self.frame.statusbar.SetStatusText, f"Auto-added from RSS: {m['title']}", 0)
                except Exception as e:
                    print(f"Auto-add error: {e}")
        
        wx.CallAfter(self.refresh_feeds_list)
        wx.CallAfter(self.refresh_articles_if_selected, url)

    def refresh_articles_if_selected(self, url):
        sel = self.feed_list.GetSelection()
        if sel != wx.NOT_FOUND:
            sel_url = self.feed_list.GetClientData(sel)
            if sel_url == url:
                self.load_articles(url)

    def on_feed_selected(self, event):
        sel = self.feed_list.GetSelection()
        if sel != wx.NOT_FOUND:
            url = self.feed_list.GetClientData(sel)
            self.load_articles(url)

    def load_articles(self, url):
        data = self.manager.feeds.get(url)
        if data:
            self.current_articles = data.get('articles', [])
            self.article_list.SetItemCount(len(self.current_articles))
            self.article_list.Refresh()

    def on_download_article(self, event):
        idx = event.GetIndex()
        if 0 <= idx < len(self.current_articles):
            article = self.current_articles[idx]
            self.frame.statusbar.SetStatusText(f"Adding torrent: {article['title']}...", 0)
            self.frame.thread_pool.submit(self.download_article, article)

    def download_article(self, article):
        url = article['link']
        if self.frame.client:
            try:
                self.frame.client.add_torrent_url(url)
                wx.CallAfter(self.frame.statusbar.SetStatusText, f"Added from RSS: {article['title']}", 0)
            except Exception as e:
                wx.CallAfter(wx.LogError, f"Failed to add from RSS: {e}")

    def on_rules(self, event):
        dlg = RulesManagerDialog(self, self.manager)
        dlg.ShowModal()
        dlg.Destroy()

class MainFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title=APP_NAME, size=(1200, 800))
        
        self.config_manager = ConfigManager()
        
        # Start Global Session (Background Local Mode)
        try:
            SessionManager.get_instance()
        except Exception as e:
            print(f"Failed to start local background session: {e}")

        self.client = None
        self.connected = False
        self.all_torrents = []
        self.data_lock = threading.RLock()
        self.current_filter = "All"
        self.current_profile_id = None
        self.client_generation = 0
        self.client_default_save_path = None
        self.known_hashes = set()
        self.pending_add_baseline = None
        self.pending_auto_start = False
        self.pending_auto_start_attempts = 0
        self.pending_hash_starts = set()
        self.pending_cli_arg = None
        self.thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        self.update_check_in_progress = False
        self.update_install_in_progress = False
        self._auto_update_calllater = None
        self.refreshing = False
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_timer, self.timer)
        
        self.rss_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_rss_timer, self.rss_timer)
        
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_ICONIZE, self.on_minimize)
        
        # Taskbar Icon
        self.tb_icon = TaskBarIcon(self)
        self.SetIcon(get_app_icon())
        
        # Menu Bar
        self._build_menu_bar()

        # Splitter Window
        self.splitter = wx.SplitterWindow(self, style=wx.SP_3D | wx.SP_LIVE_UPDATE)
        self.right_splitter = wx.SplitterWindow(self.splitter, style=wx.SP_3D | wx.SP_LIVE_UPDATE)
        
        # Sidebar
        self.sidebar = wx.TreeCtrl(self.splitter, style=wx.TR_DEFAULT_STYLE | wx.TR_HIDE_ROOT | wx.TR_NO_LINES | wx.TR_FULL_ROW_HIGHLIGHT)
        self.sidebar.Bind(wx.EVT_TREE_SEL_CHANGED, self.on_filter_change)
        self.sidebar.SetName("Categories")
        self.root_id = self.sidebar.AddRoot("Root")
        self.cat_ids = {}
        self.cat_ids["All"] = self.sidebar.AppendItem(self.root_id, "All")
        self.cat_ids["Downloading"] = self.sidebar.AppendItem(self.root_id, "Downloading")
        self.cat_ids["Finished"] = self.sidebar.AppendItem(self.root_id, "Finished")
        self.cat_ids["Seeding"] = self.sidebar.AppendItem(self.root_id, "Seeding")
        self.cat_ids["Stopped"] = self.sidebar.AppendItem(self.root_id, "Stopped")
        self.cat_ids["Failed"] = self.sidebar.AppendItem(self.root_id, "Failed")
        self.trackers_root = self.sidebar.AppendItem(self.root_id, "Trackers")
        self.rss_id = self.sidebar.AppendItem(self.root_id, "RSS")
        self.tracker_items = {} 
        self.sidebar.SelectItem(self.cat_ids["All"])
        self.sidebar.ExpandAll()

        # List
        self.torrent_list = TorrentListCtrl(self.right_splitter)
        self.torrent_list.Bind(wx.EVT_KEY_DOWN, self.on_list_key)
        self.torrent_list.Bind(wx.EVT_CONTEXT_MENU, self.on_context_menu)
        self.torrent_list.Bind(wx.EVT_RIGHT_DOWN, self.on_context_menu)
        self.torrent_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_torrent_selected)
        
        # Details Panel
        self.details_panel = TorrentDetailsPanel(self.right_splitter, self)
        
        # Setup Splitters
        self.right_splitter.SplitHorizontally(self.torrent_list, self.details_panel, -200)
        self.right_splitter.SetMinimumPaneSize(100)
        self.right_splitter.SetSashGravity(1.0) # Bottom fixed size-ish
        
        # RSS Panel (Hidden initially)
        self.rss_panel = RSSPanel(self.splitter, self)
        self.rss_panel.Hide()
        
        self.splitter.SplitVertically(self.sidebar, self.right_splitter, 220)
        self.splitter.SetMinimumPaneSize(150)

        self.statusbar = self.CreateStatusBar(2)
        self.statusbar.SetStatusText("Disconnected", 0)

        
        self.Center()
        
        # Initialize preferred path
        self._update_client_default_save_path()
        self._update_web_ui()

        # Start RSS Timer
        rss_interval = self.config_manager.get_preferences().get('rss_update_interval', 300)
        self.rss_timer.Start(rss_interval * 1000)

        # Attempt auto-connect
        wx.CallAfter(self.try_auto_connect)
        self._schedule_auto_update_check()

    def show_from_tray(self):
        if not self.IsShown():
            self.Show()
        if self.IsIconized():
            self.Restore()
        self.Raise()

    def _build_menu_bar(self):
        """Build or rebuild the menu bar.

        The Connect entry is a submenu when profiles exist, enabling quick switching.
        """
        menubar = wx.MenuBar()

        # ----- File menu -----
        file_menu = wx.Menu()

        profiles = self.config_manager.get_profiles()
        self._connect_menu_id_to_profile = {}

        if profiles:
            connect_menu = wx.Menu()
            default_id = self.config_manager.get_default_profile_id()

            # Sort profiles by name for predictable navigation.
            def _sort_key(kv):
                pid, p = kv
                return str(p.get("name", pid)).lower()

            for pid, p in sorted(profiles.items(), key=_sort_key):
                label = str(p.get("name") or pid)
                if default_id and pid == default_id:
                    label += " (Default)"
                item = connect_menu.Append(wx.ID_ANY, label, "Connect to this profile")
                self._connect_menu_id_to_profile[item.GetId()] = pid
                self.Bind(wx.EVT_MENU, self.on_connect_profile_menu, item)

            # Put the Connection Manager entry at the bottom of the submenu,
            # after all existing profile choices.
            connect_menu.AppendSeparator()
            manage_item = connect_menu.Append(
                wx.ID_ANY,
                "Connection Manager...\tCtrl+Shift+C",
                "Add/edit/delete profiles and connect"
            )
            self.Bind(wx.EVT_MENU, self.on_connect, manage_item)

            file_menu.AppendSubMenu(connect_menu, "&Connect", "Connect or switch profile")
        else:
            connect_item = file_menu.Append(
                wx.ID_ANY,
                "&Connect...\tCtrl+Shift+C",
                "Manage Profiles & Connect"
            )
            self.Bind(wx.EVT_MENU, self.on_connect, connect_item)

        add_file_item = file_menu.Append(
            wx.ID_ANY,
            "&Add Torrent File...\tCtrl+O",
            "Add a torrent from a local file"
        )
        add_url_item = file_menu.Append(
            wx.ID_ANY,
            "Add &URL/Magnet...\tCtrl+U",
            "Add a torrent from a URL or Magnet link"
        )
        create_torrent_item = file_menu.Append(
            wx.ID_ANY,
            "Create &Torrent...\tCtrl+N",
            "Create a .torrent file from a file or folder"
        )
        file_menu.AppendSeparator()
        exit_item = file_menu.Append(wx.ID_EXIT, "E&xit", "Exit application")
        menubar.Append(file_menu, "&File")

        # ----- Actions menu -----
        actions_menu = wx.Menu()
        start_item = actions_menu.Append(wx.ID_ANY, "&Start\tCtrl+S", "Start selected torrents")
        pause_item = actions_menu.Append(wx.ID_ANY, "&Pause\tCtrl+P", "Pause selected torrents")
        resume_item = actions_menu.Append(wx.ID_ANY, "&Resume\tCtrl+R", "Resume selected torrents")
        actions_menu.AppendSeparator()
        recheck_item = actions_menu.Append(wx.ID_ANY, "Force Re&check", "Force a recheck/verification (if supported)")
        reannounce_item = actions_menu.Append(wx.ID_ANY, "Force Reannoun&ce", "Force an immediate tracker announce (if supported)")
        actions_menu.AppendSeparator()
        copy_hash_item = actions_menu.Append(wx.ID_ANY, "Copy &Info Hash\tCtrl+I", "Copy the info hash for selected torrents")
        copy_magnet_item = actions_menu.Append(wx.ID_ANY, "Copy &Magnet Link\tCtrl+M", "Copy a magnet link for selected torrents")
        open_folder_item = actions_menu.Append(wx.ID_ANY, "Open Download &Folder", "Open the download folder (if available)")
        actions_menu.AppendSeparator()
        remove_item = actions_menu.Append(wx.ID_ANY, "&Remove\tDel", "Remove selected torrents")
        remove_data_item = actions_menu.Append(wx.ID_ANY, "Remove with &Data\tShift+Del", "Remove selected torrents and data")
        select_all_item = actions_menu.Append(wx.ID_SELECTALL, "Select &All\tCtrl+A", "Select all torrents")
        menubar.Append(actions_menu, "&Actions")

        # ----- Tools menu -----
        tools_menu = wx.Menu()
        assoc_item = tools_menu.Append(wx.ID_ANY, "Register &Associations", "Associate .torrent and magnet links with this app")
        update_item = tools_menu.Append(wx.ID_ANY, "Check for &Updates...\tF5", "Check for updates")
        tools_menu.AppendSeparator()
        
        self.qbit_remote_prefs_item = tools_menu.Append(wx.ID_ANY, "qBittorrent Remote &Settings...", "Edit connected qBittorrent settings")
        self.trans_remote_prefs_item = tools_menu.Append(wx.ID_ANY, "Transmission Remote &Settings...", "Edit connected Transmission settings")
        self.rtorrent_remote_prefs_item = tools_menu.Append(wx.ID_ANY, "rTorrent Remote &Settings...", "Edit connected rTorrent settings")
        tools_menu.AppendSeparator()
        local_settings_item = tools_menu.Append(
            wx.ID_PREFERENCES,
            "Local Session &Settings...\tCtrl+,",
            "Configure local session and application settings",
        )
        
        self.qbit_remote_prefs_item.Enable(False)
        self.trans_remote_prefs_item.Enable(False)
        self.rtorrent_remote_prefs_item.Enable(False)
        
        menubar.Append(tools_menu, "&Tools")
        
        # ----- Help menu -----
        help_menu = wx.Menu()
        about_item = help_menu.Append(wx.ID_ABOUT, "&About SerrebiTorrent", "About this application")
        menubar.Append(help_menu, "&Help")

        self.SetMenuBar(menubar)

        # Bind actions for the non-connect file menu items.
        self.Bind(wx.EVT_MENU, self.on_add_file, add_file_item)
        self.Bind(wx.EVT_MENU, self.on_add_url, add_url_item)
        self.Bind(wx.EVT_MENU, self.on_create_torrent, create_torrent_item)
        self.Bind(wx.EVT_MENU, self.on_prefs, local_settings_item)
        self.Bind(wx.EVT_MENU, lambda e: self.Close(force=True), exit_item)

        # Bind actions menu.
        self.Bind(wx.EVT_MENU, self.on_start, start_item)
        self.Bind(wx.EVT_MENU, self.on_pause, pause_item)
        self.Bind(wx.EVT_MENU, self.on_resume, resume_item)
        self.Bind(wx.EVT_MENU, self.on_recheck, recheck_item)
        self.Bind(wx.EVT_MENU, self.on_reannounce, reannounce_item)
        self.Bind(wx.EVT_MENU, self.on_copy_info_hash, copy_hash_item)
        self.Bind(wx.EVT_MENU, self.on_copy_magnet, copy_magnet_item)
        self.Bind(wx.EVT_MENU, self.on_open_download_folder, open_folder_item)
        self.Bind(wx.EVT_MENU, self.on_remove, remove_item)
        self.Bind(wx.EVT_MENU, self.on_remove_data, remove_data_item)
        self.Bind(wx.EVT_MENU, self.on_select_all, select_all_item)

        # Tools menu extras.
        self.Bind(wx.EVT_MENU, lambda e: register_associations(), assoc_item)
        self.Bind(wx.EVT_MENU, self.on_check_updates, update_item)
        self.Bind(wx.EVT_MENU, self.on_remote_preferences, self.qbit_remote_prefs_item)
        self.Bind(wx.EVT_MENU, self.on_remote_preferences, self.trans_remote_prefs_item)
        self.Bind(wx.EVT_MENU, self.on_remote_preferences, self.rtorrent_remote_prefs_item)
        
        # Help menu
        self.Bind(wx.EVT_MENU, self.on_about, about_item)

        # Keep the remote-preferences menu in sync with connection state.
        self._update_remote_prefs_menu_state()
        # Accelerator table: ensure shortcuts work regardless of focus.
        accel_entries = [
            (wx.ACCEL_CTRL, ord('A'), select_all_item.GetId()),
            (wx.ACCEL_CTRL, ord('S'), start_item.GetId()),
            (wx.ACCEL_CTRL, ord('P'), pause_item.GetId()),
            (wx.ACCEL_CTRL, ord('R'), resume_item.GetId()),
            (wx.ACCEL_NORMAL, wx.WXK_DELETE, remove_item.GetId()),
            (wx.ACCEL_SHIFT, wx.WXK_DELETE, remove_data_item.GetId()),
            (wx.ACCEL_CTRL, ord('O'), add_file_item.GetId()),
            (wx.ACCEL_CTRL, ord('U'), add_url_item.GetId()),
            (wx.ACCEL_CTRL, ord('N'), create_torrent_item.GetId()),
            (wx.ACCEL_CTRL, ord('I'), copy_hash_item.GetId()),
            (wx.ACCEL_CTRL, ord('M'), copy_magnet_item.GetId()),
            (wx.ACCEL_CTRL, ord(','), local_settings_item.GetId()),
        ]
        self.SetAcceleratorTable(wx.AcceleratorTable(accel_entries))


    def on_connect_profile_menu(self, event):
        pid = getattr(self, "_connect_menu_id_to_profile", {}).get(event.GetId())
        if not pid:
            return
        self.connect_profile(pid)


    def _update_client_default_save_path(self):
        prefs = self.config_manager.get_preferences()
        fallback = prefs.get('download_path', '')
        self.client_default_save_path = fallback
        if not self.client:
            return
        generation = self.client_generation
        client = self.client
        self.thread_pool.submit(self._fetch_client_default_save_path, client, generation, fallback)

    def _fetch_client_default_save_path(self, client, generation, fallback):
        path = fallback
        if client:
            try:
                candidate = client.get_default_save_path()
                if candidate is not None:
                    path = candidate
            except Exception:
                pass
        wx.CallAfter(self._apply_client_default_save_path, generation, path)

    def _apply_client_default_save_path(self, generation, path):
        if generation != self.client_generation:
            return
        self.client_default_save_path = path

    def _update_web_ui(self):
        prefs = self.config_manager.get_preferences()
        web_server.WEB_CONFIG['app'] = self
        web_server.WEB_CONFIG['client'] = self.client
        web_server.WEB_CONFIG['enabled'] = prefs.get('web_ui_enabled', False)
        web_server.WEB_CONFIG['host'] = prefs.get('web_ui_host', '127.0.0.1')
        web_server.WEB_CONFIG['port'] = prefs.get('web_ui_port', 8080)
        web_server.WEB_CONFIG['username'] = prefs.get('web_ui_user', 'admin')
        web_server.WEB_CONFIG['password'] = prefs.get('web_ui_pass', 'password')
        
        if web_server.WEB_CONFIG['enabled']:
            try:
                web_server.start_web_ui()
            except Exception as e:
                wx.LogMessage(f"Error starting Web UI: {e}")

    def _schedule_auto_update_check(self):
        prefs = self.config_manager.get_preferences()
        if self._auto_update_calllater:
            try:
                self._auto_update_calllater.Stop()
            except Exception as e:
                wx.LogWarning(f"Failed to stop auto-update timer: {e}")
            self._auto_update_calllater = None
        if prefs.get("auto_check_updates", True):
            self._auto_update_calllater = wx.CallLater(3000, self.check_for_updates, False)

    def on_check_updates(self, event):
        self.check_for_updates(True)
    
    def on_about(self, event):
        from app_version import APP_VERSION
        info = wx.adv.AboutDialogInfo()
        info.SetName("SerrebiTorrent")
        info.SetVersion(APP_VERSION)
        info.SetDescription("A Windows desktop torrent manager designed for keyboard-first use and screen readers.")
        info.SetCopyright("Copyright © 2025-2026 serrebidev and contributors")
        info.SetWebSite("https://github.com/serrebidev/SerrebiTorrent")
        info.AddDeveloper("serrebidev")
        wx.adv.AboutBox(info)

    def check_for_updates(self, manual=False):
        if self.update_check_in_progress or self.update_install_in_progress:
            if manual:
                wx.MessageBox("An update check or install is already in progress.", "Updates", wx.OK | wx.ICON_INFORMATION)
            return
        self.update_check_in_progress = True
        if hasattr(self, "statusbar"):
            self.statusbar.SetStatusText("Checking for updates...", 0)
        self.thread_pool.submit(self._check_updates_background, manual)

    def _check_updates_background(self, manual):
        try:
            info = updater.check_for_update()
            if info is None:
                wx.CallAfter(self._on_no_update_available, manual)
            else:
                wx.CallAfter(self._prompt_update, info)
        except updater.RateLimitError as e:
            wx.CallAfter(self._on_update_check_failed, str(e), manual)
        except Exception as e:
            wx.CallAfter(self._on_update_check_failed, f"Update check failed: {e}", manual)
        finally:
            self.update_check_in_progress = False

    def _on_no_update_available(self, manual):
        if manual:
            wx.MessageBox("You're already on the latest version.", "Updates", wx.OK | wx.ICON_INFORMATION)
        if hasattr(self, "statusbar"):
            self.statusbar.SetStatusText("No updates available.", 0)

    def _on_update_check_failed(self, message, manual):
        if manual:
            wx.MessageBox(message, "Update Check Failed", wx.OK | wx.ICON_ERROR)
        if hasattr(self, "statusbar"):
            self.statusbar.SetStatusText("Update check failed.", 0)

    def _prompt_update(self, info):
        message = f"A new version of {APP_NAME} is available.\n\n{updater.build_update_prompt(info)}"
        if wx.MessageBox(message, "Update Available", wx.YES_NO | wx.ICON_INFORMATION) != wx.YES:
            if hasattr(self, "statusbar"):
                self.statusbar.SetStatusText("Update postponed.", 0)
            return
        self._start_update_install(info)

    def _start_update_install(self, info):
        if self.update_install_in_progress:
            wx.MessageBox("An update is already in progress.", "Updates", wx.OK | wx.ICON_INFORMATION)
            return
        if not getattr(sys, "frozen", False):
            wx.MessageBox("Updates are only available in the packaged app.", "Updates", wx.OK | wx.ICON_WARNING)
            return
        install_dir = os.path.dirname(sys.executable)
        if not os.path.isdir(install_dir):
            wx.MessageBox("Install directory not found.", "Updates", wx.OK | wx.ICON_ERROR)
            return
        self.update_install_in_progress = True
        if hasattr(self, "statusbar"):
            self.statusbar.SetStatusText("Downloading update...", 0)
        self.thread_pool.submit(self._perform_update_background, info, install_dir)

    def _perform_update_background(self, info, install_dir):
        try:
            parent_dir = os.path.dirname(install_dir)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            staging_root = os.path.join(parent_dir, f"{APP_NAME}_Update_{timestamp}")
            os.makedirs(staging_root, exist_ok=True)

            zip_name = str(info.manifest.get("asset_filename") or f"{APP_NAME}-v{info.latest_version}.zip")
            zip_path = os.path.join(staging_root, zip_name)
            updater.download_file(str(info.manifest.get("download_url")), zip_path)

            expected = str(info.manifest.get("sha256", "")).lower()
            actual = updater.compute_sha256(zip_path).lower()
            if expected != actual:
                raise updater.UpdateError("Downloaded update failed SHA-256 verification.")

            updater.extract_zip(zip_path, staging_root)
            new_dir = updater.find_app_dir(staging_root)
            if not new_dir:
                raise updater.UpdateError("Extracted update does not contain application files.")
            new_exe = os.path.join(new_dir, updater.APP_EXE_NAME)
            if not os.path.isfile(new_exe):
                raise updater.UpdateError("Updated executable not found.")

            updater.verify_authenticode(new_exe, updater.get_allowed_thumbprints(info.manifest))

            helper_src = os.path.join(new_dir, "update_helper.bat")
            if not os.path.isfile(helper_src):
                helper_src = os.path.join(install_dir, "update_helper.bat")
            
            if not os.path.isfile(helper_src):
                raise updater.UpdateError("Update helper script not found.")
            helper_copy = os.path.join(staging_root, "update_helper.bat")
            shutil.copy2(helper_src, helper_copy)

            # Create a simple batch launcher for the update
            bat_launcher = os.path.join(staging_root, "launch_update.bat")
            bat_content = f'@echo off\ncall "{helper_copy}" {os.getpid()} "{install_dir}" "{new_dir}" "{updater.APP_EXE_NAME}"\n'
            with open(bat_launcher, "w") as f:
                f.write(bat_content)
            
            # Create a VBScript to run the batch file invisibly
            vbs_launcher = os.path.join(staging_root, "launch_update.vbs")
            vbs_content = f'CreateObject("WScript.Shell").Run Chr(34) & "{bat_launcher}" & Chr(34), 0, False\n'
            with open(vbs_launcher, "w") as f:
                f.write(vbs_content)
            
            # Launch VBScript with hidden window
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE
            
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            subprocess.Popen(
                ["wscript.exe", "//nologo", vbs_launcher],
                creationflags=flags,
                startupinfo=startupinfo,
                cwd=parent_dir
            )
            wx.CallAfter(self._on_update_started)
        except Exception as e:
            wx.CallAfter(self._on_update_failed, str(e))

    def _on_update_started(self):
        if hasattr(self, "statusbar"):
            self.statusbar.SetStatusText("Applying update...", 0)
        wx.MessageBox(
            "The update has been downloaded and verified. The app will now close to install it.",
            "Updating",
            wx.OK | wx.ICON_INFORMATION,
        )
        self.force_close()

    def _on_update_failed(self, message):
        self.update_install_in_progress = False
        wx.MessageBox(f"Update failed: {message}", "Update Failed", wx.OK | wx.ICON_ERROR)
        if hasattr(self, "statusbar"):
            self.statusbar.SetStatusText("Update failed.", 0)

    def _update_remote_prefs_menu_state(self):
        # Enable specific remote preferences items based on connection
        is_qbit = isinstance(self.client, QBittorrentClient) and self.connected
        is_trans = isinstance(self.client, TransmissionClient) and self.connected
        is_rtorrent = isinstance(self.client, RTorrentClient) and self.connected
        
        if hasattr(self, "qbit_remote_prefs_item"):
            self.qbit_remote_prefs_item.Enable(is_qbit)
        if hasattr(self, "trans_remote_prefs_item"):
            self.trans_remote_prefs_item.Enable(is_trans)
        if hasattr(self, "rtorrent_remote_prefs_item"):
            self.rtorrent_remote_prefs_item.Enable(is_rtorrent)

    def _prepare_auto_start(self):
        if not self.client:
            return

        self.pending_add_baseline = set(self.known_hashes)
        self.pending_auto_start = True
        self.pending_auto_start_attempts = 0
        self.pending_hash_starts = set()

    def _maybe_hash_from_torrent_bytes(self, data):
        return safe_torrent_info_hash(data)

    def _maybe_hash_from_magnet(self, url):
        return parse_magnet_infohash(url)

    def _add_torrent_file_background(self, client, generation, data, save_path, priorities, status_msg):
        try:
            if generation != self.client_generation:
                return
            if not client:
                raise RuntimeError("No client connected.")
            client.add_torrent_file(data, save_path, priorities)
            wx.CallAfter(self._on_action_complete, status_msg)
        except Exception as e:
            wx.CallAfter(self._on_action_error, f"Failed to add torrent: {e}")

    def _add_magnet_background(self, client, generation, url, save_path, status_msg):
        try:
            if generation != self.client_generation:
                return
            trackers = self.fetch_trackers()
            if trackers:
                import urllib.parse
                for t in trackers:
                    url += f"&tr={urllib.parse.quote(t)}"
            if not client:
                raise RuntimeError("No client connected.")
            client.add_torrent_url(url, save_path)
            wx.CallAfter(self._on_action_complete, status_msg)
        except Exception as e:
            wx.CallAfter(self._on_action_error, f"Failed to add magnet: {e}")

    def _process_cli_arg(self, arg):
        if not self.connected or not self.client:
            wx.LogError("Not connected to any client.")
            return

        generation = self.client_generation
        client = self.client

        if arg.startswith("magnet:"):
            self._prepare_auto_start()
            hash_hint = self._maybe_hash_from_magnet(arg)
            if hash_hint:
                self.pending_hash_starts.add(hash_hint)
            self.statusbar.SetStatusText("Adding magnet link from CLI...", 0)
            self.thread_pool.submit(
                self._add_magnet_background, client, generation, arg, None, "Magnet link added from CLI"
            )
            return

        if os.path.exists(arg):
            try:
                with open(arg, 'rb') as f:
                    content = f.read()
            except Exception as e:
                wx.LogError(f"Failed to read torrent file: {e}")
                return

            self._prepare_auto_start()
            hash_hint = self._maybe_hash_from_torrent_bytes(content)
            if hash_hint:
                self.pending_hash_starts.add(hash_hint)
            self.statusbar.SetStatusText("Adding torrent file from CLI...", 0)
            self.thread_pool.submit(
                self._add_torrent_file_background,
                client,
                generation,
                content,
                None,
                None,
                "Torrent file added from CLI",
            )
            return

        wx.LogError(f"Invalid argument: {arg}")

    def _auto_start_hashes(self, generation, hashes):
        try:
            import time
            time.sleep(0.3)
            for h in hashes:
                if generation != self.client_generation:
                    return
                if self.client:
                    self.client.start_torrent(h)
            wx.CallAfter(self.statusbar.SetStatusText, "Auto-started new torrent(s)", 0)
            wx.CallAfter(self.refresh_data)
        except Exception as e:
            wx.CallAfter(self.statusbar.SetStatusText, f"Auto-start failed: {e}", 0)

    def on_prefs(self, event):
        dlg = PreferencesDialog(self, self.config_manager)
        if dlg.ShowModal() == wx.ID_OK:
            prefs = dlg.get_preferences()
            self.config_manager.set_preferences(prefs)
            # Apply to session immediately
            try:
                SessionManager.get_instance().apply_preferences(prefs)
            except Exception as e:
                wx.LogError(f"Failed to apply settings: {e}")
            self._update_client_default_save_path()
            self._update_web_ui()
            self._schedule_auto_update_check()
            
            # Update RSS timer interval
            interval = prefs.get('rss_update_interval', 300)
            self.rss_timer.Start(interval * 1000)
            
            # Refresh RSS view in case of reset
            if hasattr(self, 'rss_panel'):
                self.rss_panel.manager.load()
                self.rss_panel.refresh_feeds_list()
                self.rss_panel.article_list.SetItemCount(0)
                self.rss_panel.current_articles = []
            
        dlg.Destroy()

    def on_remote_preferences(self, event):
        if not self.connected:
            return

        name = "Remote Client"
        if isinstance(self.client, QBittorrentClient):
            name = "qBittorrent"
        elif isinstance(self.client, RTorrentClient):
            name = "rTorrent"
        elif isinstance(self.client, TransmissionClient):
            name = "Transmission"
        elif isinstance(self.client, LocalClient):
            name = "Local"

        self.statusbar.SetStatusText(f"Fetching {name} preferences...", 0)
        self.thread_pool.submit(self._fetch_remote_preferences)

    def _fetch_remote_preferences(self):
        try:
            prefs = self.client.get_app_preferences()
            if prefs is None:
                wx.CallAfter(wx.MessageBox, "Failed to retrieve preferences from remote client. The client might not support this feature or there is a connection issue.", "Error", wx.OK | wx.ICON_ERROR)
                wx.CallAfter(self.statusbar.SetStatusText, "Failed to fetch preferences", 0)
                return
            wx.CallAfter(self._show_remote_preferences_dialog, prefs)
        except Exception as e:
            wx.CallAfter(wx.LogError, f"Failed to fetch remote preferences: {e}")
            wx.CallAfter(self.statusbar.SetStatusText, "Error fetching preferences", 0)

    def _show_remote_preferences_dialog(self, prefs):
        if prefs is None:
            wx.MessageBox("Failed to retrieve preferences from remote client.", "Error", wx.OK | wx.ICON_ERROR)
            return

        client_name = "Remote"
        if isinstance(self.client, QBittorrentClient):
            client_name = "qBittorrent"
        elif isinstance(self.client, RTorrentClient):
            client_name = "rTorrent"
        elif isinstance(self.client, TransmissionClient):
            client_name = "Transmission"
        elif isinstance(self.client, LocalClient):
            client_name = "Local"

        dlg = RemotePreferencesDialog(self, prefs, client_name)
        if dlg.ShowModal() == wx.ID_OK:
            try:
                parsed = dlg.GetPreferences()
                self.thread_pool.submit(self._apply_remote_preferences, parsed)
            except ValueError as e:
                wx.MessageBox(f"{e}", "Error", wx.OK | wx.ICON_ERROR)
        dlg.Destroy()

    def _apply_remote_preferences(self, prefs):
        try:
            self.client.set_app_preferences(prefs)
            name = "Remote"
            if isinstance(self.client, QBittorrentClient):
                name = "qBittorrent"
            elif isinstance(self.client, RTorrentClient):
                name = "rTorrent"
            elif isinstance(self.client, TransmissionClient):
                name = "Transmission"
            elif isinstance(self.client, LocalClient):
                name = "Local"
            
            wx.CallAfter(self.statusbar.SetStatusText, f"{name} preferences saved", 0)
            wx.CallAfter(self._update_client_default_save_path)
        except Exception as e:
            wx.CallAfter(wx.LogError, f"Failed to update remote preferences: {e}")

    def on_minimize(self, event):
        prefs = self.config_manager.get_preferences()
        if prefs.get('min_to_tray', True):
            self.Hide()
        else:
            event.Skip()

    def on_close(self, event):
        if event.CanVeto():
            prefs = self.config_manager.get_preferences()
            if prefs.get('close_to_tray', True):
                self.Hide()
                event.Veto()
                return

        self.force_close()

    def force_close(self):
        # Save local state
        self.tb_icon.RemoveIcon()
        self.tb_icon.Destroy()
        try:
            # Provide visual feedback since save_state can take a few seconds
            wx.BeginBusyCursor()
            try:
                SessionManager.get_instance().save_state()
            finally:
                wx.EndBusyCursor()
        except Exception:
            pass
        self.Destroy()
        sys.exit(0)

    def connect_profile(self, pid):
        p = self.config_manager.get_profile(pid)
        if not p:
            return
        
        self.current_profile_id = pid
        self.client_default_save_path = None
        self.client_generation += 1

        # Reset state before connecting
        self.timer.Stop()
        self.connected = False
        self.client = None
        self.all_torrents = []
        self.torrent_list.update_data([])
        self.statusbar.SetStatusText("Connecting...", 0)
        self.known_hashes.clear()
        self.pending_add_baseline = None
        self.pending_auto_start = False
        self.pending_auto_start_attempts = 0
        self.pending_hash_starts = set()
        self._update_remote_prefs_menu_state()
        
        generation = self.client_generation
        self.thread_pool.submit(self._connect_profile_background, p, generation)

    def _connect_profile_background(self, profile, generation):
        client = None
        error = None
        try:
            if profile['type'] == 'local':
                client = LocalClient(profile['url'])
            elif profile['type'] == 'rtorrent':
                client = RTorrentClient(profile['url'], profile['user'], profile['password'])
            elif profile['type'] == 'qbittorrent':
                client = QBittorrentClient(profile['url'], profile['user'], profile['password'])
            elif profile['type'] == 'transmission':
                client = TransmissionClient(profile['url'], profile['user'], profile['password'])
            else:
                raise ValueError(f"Unknown profile type: {profile.get('type')}")
            
            if client:
                client.test_connection()
        except Exception as e:
            error = e

        wx.CallAfter(self._on_connect_complete, generation, profile, client, error)

    def _on_connect_complete(self, generation, profile, client, error):
        if generation != self.client_generation:
            return

        if error or not client:
            wx.LogError(f"Connection failed: {error}")
            self.connected = False
            self.client = None
            self.statusbar.SetStatusText("Connection Failed", 0)
            self._update_remote_prefs_menu_state()
            return

        self.client = client
        self.connected = True
        self._update_client_default_save_path()
        self._update_web_ui()

        status_msg = f"Connected to {profile.get('name', 'Profile')}"
        if profile.get('type') != 'local':
            status_msg += " (Local session active)"

        self.statusbar.SetStatusText(status_msg, 0)
        self.refresh_data()
        self.timer.Start(2000) # Refresh every 2 seconds
        self._update_remote_prefs_menu_state()

        if self.pending_cli_arg:
            arg = self.pending_cli_arg
            self.pending_cli_arg = None
            self._process_cli_arg(arg)

    def on_connect(self, event):
        dlg = ConnectDialog(self, self.config_manager)
        if dlg.ShowModal() == wx.ID_OK:
            pid = dlg.selected_profile_id
            self.connect_profile(pid)
        dlg.Destroy()
        # Profiles may have been added/edited; rebuild the menu bar to reflect changes.
        self._build_menu_bar()

    def on_timer(self, event):
        if self.connected:
            self.refresh_data()
            if hasattr(self, 'details_panel'):
                self.details_panel.refresh_tab()

    def on_rss_timer(self, event):
        if hasattr(self, 'rss_panel'):
            self.rss_panel.on_refresh_all(None)

    def refresh_data(self):
        if not self.client or self.refreshing:
            return
        
        self.refreshing = True
        filter_mode = self.current_filter
        generation = self.client_generation
        self.thread_pool.submit(self._fetch_and_process_data, filter_mode, generation)

    def get_all_torrents_safe(self):
        with self.data_lock:
            return list(self.all_torrents)

    def _fetch_and_process_data(self, filter_mode, generation):
        try:
            torrents = self.client.get_torrents_full()
            
            display_data = []
            stats = {"All": 0, "Downloading": 0, "Finished": 0, "Seeding": 0, "Stopped": 0, "Failed": 0}
            tracker_counts = {}
            
            for t in torrents:
                # Fast pre-calculation for filtering and stats
                size = t.get('size', 0)
                done = t.get('done', 0)
                pct = (done / size * 100) if size > 0 else 0
                state = t.get('state', 0)
                msg = t.get('message', '')
                tracker_domain = t.get('tracker_domain', 'Unknown') or 'Unknown'
                
                is_seeding = (state == 1 and pct >= 100)
                is_stopped = (state == 0)
                is_error = bool(msg and clean_status_message(msg))
                
                stats["All"] += 1
                if state == 1 and pct < 100:
                    stats["Downloading"] += 1
                if pct >= 100:
                    stats["Finished"] += 1
                if is_seeding:
                    stats["Seeding"] += 1
                if is_stopped:
                    stats["Stopped"] += 1
                if is_error:
                    stats["Failed"] += 1
                
                tracker_counts[tracker_domain] = tracker_counts.get(tracker_domain, 0) + 1
                    
                include = False
                if filter_mode == "All":
                    include = True
                elif filter_mode == "Downloading" and state == 1 and pct < 100:
                    include = True
                elif filter_mode == "Finished" and pct >= 100:
                    include = True
                elif filter_mode == "Seeding" and is_seeding:
                    include = True
                elif filter_mode == "Stopped" and is_stopped:
                    include = True
                elif filter_mode == "Failed" and is_error:
                    include = True
                elif filter_mode == tracker_domain:
                    include = True
                
                if include:
                    # Keep raw data for virtual list formatting
                    display_data.append(t)
            
            g_down, g_up = 0, 0
            try:
                g_down, g_up = self.client.get_global_stats()
            except Exception:
                pass
            
            wx.CallAfter(self._on_refresh_complete, generation, torrents, display_data, stats, tracker_counts, g_down, g_up)
            
        except Exception as e:
            wx.CallAfter(self._on_refresh_error, generation, e)

    def _on_refresh_complete(self, generation, torrents, display_data, stats, tracker_counts, g_down, g_up):
        self.refreshing = False
        if not self.connected or generation != self.client_generation:
            return

        with self.data_lock:
            self.all_torrents = torrents
        self.torrent_list.update_data(display_data)
        current_hashes = {t.get('hash') for t in torrents if t.get('hash')}
        self.known_hashes = current_hashes
        
        for key, item_id in self.cat_ids.items():
            self.sidebar.SetItemText(item_id, f"{key} ({stats[key]})")
            
        # Update Trackers
        # 1. Update or Add
        for tracker, count in tracker_counts.items():
            label = f"{tracker} ({count})"
            if tracker in self.tracker_items:
                # Update existing
                item_id = self.tracker_items[tracker]
                if self.sidebar.GetItemText(item_id) != label:
                    self.sidebar.SetItemText(item_id, label)
            else:
                # Add new
                item_id = self.sidebar.AppendItem(self.trackers_root, label)
                self.tracker_items[tracker] = item_id
        
        # 2. Remove old (optional, but good for cleanup)
        to_remove = []
        for tracker, item_id in self.tracker_items.items():
            if tracker not in tracker_counts:
                self.sidebar.Delete(item_id)
                to_remove.append(tracker)
        for t in to_remove:
            del self.tracker_items[t]
            
        self.sidebar.Expand(self.trackers_root)

        self.statusbar.SetStatusText(f"DL: {fmt_size(g_down)}/s | UL: {fmt_size(g_up)}/s", 1)

        if self.pending_auto_start:
            target_hashes = set(current_hashes)
            if self.pending_hash_starts:
                target_hashes |= self.pending_hash_starts
            if self.pending_add_baseline is not None:
                target_hashes = target_hashes - self.pending_add_baseline

            if target_hashes:
                self.pending_auto_start = False
                self.pending_add_baseline = None
                self.pending_auto_start_attempts = 0
                self.pending_hash_starts.clear()
                self.thread_pool.submit(self._auto_start_hashes, generation, target_hashes)
            else:
                self.pending_auto_start_attempts += 1
                if self.pending_auto_start_attempts >= 5:
                    self.pending_auto_start = False
                    self.pending_add_baseline = None
                    self.pending_auto_start_attempts = 0
                    self.pending_hash_starts.clear()

    def _on_refresh_error(self, generation, e):
        self.refreshing = False
        if generation != self.client_generation:
            return
        print(f"Refresh error: {e}")

    def fetch_trackers(self):
        prefs = self.config_manager.get_preferences()
        if not prefs.get('enable_trackers', True):
            return []
        
        url = prefs.get('tracker_url', '')
        if not url:
            return []

        try:
            # Simple caching
            if hasattr(self, '_cached_trackers') and self._cached_trackers:
                return self._cached_trackers

            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                trackers = [line.strip() for line in r.text.splitlines() if line.strip()]
                self._cached_trackers = trackers
                return trackers
        except Exception as e:
            print(f"Failed to fetch trackers: {e}")
        return []

    def _get_default_save_path(self):
        if self.client_default_save_path is not None:
            return self.client_default_save_path
        return self.config_manager.get_preferences().get('download_path', '')

    def on_add_file(self, event):
        with wx.FileDialog(self, "Open Torrent File", wildcard="Torrent files (*.torrent)|*.torrent",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_CANCEL:
                return
            path = fileDialog.GetPath()
            try:
                with open(path, 'rb') as f:
                    data = f.read()
                
                # Parse torrent info for dialog
                file_list = []
                name = "Unknown"
                if lt:
                    try:
                        info = lt.torrent_info(data)
                        name = info.name()
                        num = info.num_files()
                        file_list = [(info.files().file_path(i), info.files().file_size(i)) for i in range(num)]
                    except Exception:
                        pass

                # Use the cached client default (remote path when connected, fallback to preferences)
                default_path = self._get_default_save_path()
                
                dlg = AddTorrentDialog(self, name, file_list, default_path)
                if dlg.ShowModal() == wx.ID_OK:
                    save_path = dlg.get_selected_path()
                    if not save_path:
                        save_path = None
                    priorities = dlg.get_file_priorities()
                    hash_hint = self._maybe_hash_from_torrent_bytes(data)
                    
                    if self.client:
                        self._prepare_auto_start()
                        if hash_hint:
                            self.pending_hash_starts.add(hash_hint)
                        generation = self.client_generation
                        client = self.client
                        self.statusbar.SetStatusText("Adding torrent...", 0)
                        self.thread_pool.submit(
                            self._add_torrent_file_background,
                            client,
                            generation,
                            data,
                            save_path,
                            priorities,
                            "Torrent added",
                        )
                dlg.Destroy()

            except Exception as e:
                wx.LogError(f"Error adding file: {e}")

    def on_add_url(self, event):
        dlg = wx.TextEntryDialog(self, "Enter Magnet Link or URL:", "Add Torrent")
        if dlg.ShowModal() == wx.ID_OK:
            url = dlg.GetValue()
            if self.client:
                try:
                    default_path = self._get_default_save_path()

                    if url.startswith("magnet:"):
                        adlg = AddTorrentDialog(self, "Magnet Link", None, default_path)
                        if adlg.ShowModal() == wx.ID_OK:
                            save_path = adlg.get_selected_path() or None
                            hash_hint = self._maybe_hash_from_magnet(url)
                            self._prepare_auto_start()
                            if hash_hint:
                                self.pending_hash_starts.add(hash_hint)
                            generation = self.client_generation
                            client = self.client
                            self.statusbar.SetStatusText("Adding magnet link...", 0)
                            self.thread_pool.submit(
                                self._add_magnet_background,
                                client,
                                generation,
                                url,
                                save_path,
                                "Magnet link added",
                            )
                        adlg.Destroy()
                    elif url.startswith(("http://", "https://")):
                        self.statusbar.SetStatusText("Downloading torrent file...", 0)
                        self.thread_pool.submit(self._download_and_add_torrent, url, default_path)
                except Exception as e:
                    wx.LogError(f"Error adding URL: {e}")
        dlg.Destroy()

    def _download_and_add_torrent(self, url, default_path):
        try:
            r = requests.get(safe_encode_url(url), timeout=30)
            r.raise_for_status()
            data = r.content
            wx.CallAfter(self._show_add_after_download, data, default_path)
        except Exception as e:
            wx.CallAfter(wx.LogError, f"Failed to download torrent from URL: {e}")

    def _show_add_after_download(self, data, default_path):
        file_list = []
        name = "Unknown"
        if lt:
            try:
                info = lt.torrent_info(data)
                name = info.name()
                num = info.num_files()
                file_list = [(info.files().file_path(i), info.files().file_size(i)) for i in range(num)]
            except Exception:
                pass
        
        adlg = AddTorrentDialog(self, name, file_list, default_path)
        if adlg.ShowModal() == wx.ID_OK:
            save_path = adlg.get_selected_path() or None
            priorities = adlg.get_file_priorities()
            hash_hint = self._maybe_hash_from_torrent_bytes(data)
            if not self.client:
                wx.LogError("Not connected to any client.")
                adlg.Destroy()
                return
            self._prepare_auto_start()
            if hash_hint:
                self.pending_hash_starts.add(hash_hint)
            generation = self.client_generation
            client = self.client
            self.statusbar.SetStatusText("Adding torrent...", 0)
            self.thread_pool.submit(
                self._add_torrent_file_background,
                client,
                generation,
                data,
                save_path,
                priorities,
                "Torrent added",
            )
        adlg.Destroy()

    def _apply_to_selected(self, action, label):
        if not self.client or not action:
            if hasattr(self, "statusbar"):
                self.statusbar.SetStatusText("Not connected to any client.", 0)
            return

        hashes = self.torrent_list.get_selected_hashes()
        if not hashes:
            message = f"No torrents selected to {label.lower()}."
            if hasattr(self, "statusbar"):
                self.statusbar.SetStatusText(message, 0)
            else:
                print(message)
            return

        self.statusbar.SetStatusText(f"{label}ing torrents...", 0)
        self.thread_pool.submit(self._apply_background, action, hashes, label)

    def _apply_background(self, action, hashes, label):
        try:
            for h in hashes:
                action(h)
            wx.CallAfter(self._on_action_complete, f"{label} complete")
        except Exception as e:
            wx.CallAfter(self._on_action_error, f"Failed to {label.lower()} torrent: {e}")

    def _get_all_hashes(self):
        hashes = []
        try:
            torrents = self.all_torrents if hasattr(self, 'all_torrents') and self.all_torrents else []
            for t in torrents:
                if isinstance(t, dict):
                    h = t.get('hash')
                else:
                    h = None
                if h:
                    hashes.append(str(h))
        except Exception:
            pass
        # De-duplicate but keep order
        seen = set()
        out = []
        for h in hashes:
            if h in seen:
                continue
            seen.add(h)
            out.append(h)
        return out

    def _apply_background_bulk(self, action, hashes, label):
        failed = 0
        last_error = None
        try:
            for h in hashes:
                try:
                    action(h)
                except Exception as e:
                    failed += 1
                    last_error = e
            if failed == 0:
                wx.CallAfter(self._on_action_complete, f"{label} complete")
            else:
                wx.CallAfter(self.statusbar.SetStatusText, f"{label} complete ({failed} failed). Last error: {last_error}", 0)
                wx.CallAfter(self.refresh_data)
        except Exception as e:
            wx.CallAfter(self._on_action_error, f"Failed to {label.lower()}: {e}")

    def start_all_torrents(self):
        if not self.client or not hasattr(self.client, 'start_torrent'):
            if hasattr(self, 'statusbar'):
                self.statusbar.SetStatusText('Not connected to any client.', 0)
            return
        hashes = self._get_all_hashes()
        if not hashes:
            if hasattr(self, 'statusbar'):
                self.statusbar.SetStatusText('No torrents to start.', 0)
            return
        if hasattr(self, 'statusbar'):
            self.statusbar.SetStatusText('Starting all torrents...', 0)
        self.thread_pool.submit(self._apply_background_bulk, self.client.start_torrent, hashes, 'Start all')

    def stop_all_torrents(self):
        if not self.client or not hasattr(self.client, 'stop_torrent'):
            if hasattr(self, 'statusbar'):
                self.statusbar.SetStatusText('Not connected to any client.', 0)
            return
        hashes = self._get_all_hashes()
        if not hashes:
            if hasattr(self, 'statusbar'):
                self.statusbar.SetStatusText('No torrents to stop.', 0)
            return
        if hasattr(self, 'statusbar'):
            self.statusbar.SetStatusText('Stopping all torrents...', 0)
        self.thread_pool.submit(self._apply_background_bulk, self.client.stop_torrent, hashes, 'Stop all')

    def on_start(self, event):
        action = self.client.start_torrent if self.client else None
        self._apply_to_selected(action, "Start")

    def on_stop(self, event):
        action = self.client.stop_torrent if self.client else None
        self._apply_to_selected(action, "Stop")

    def on_pause(self, event):
        action = self.client.stop_torrent if self.client else None
        self._apply_to_selected(action, "Pause")

    def on_resume(self, event):
        action = self.client.start_torrent if self.client else None
        self._apply_to_selected(action, "Resume")


    def on_recheck(self, event):
        if not self.client or not hasattr(self.client, "recheck_torrent"):
            self.statusbar.SetStatusText("Recheck not supported by this client.", 0)
            return
        try:
            # Probe support
            pass
        except Exception:
            pass
        self._apply_to_selected(self.client.recheck_torrent, "Recheck")

    def on_reannounce(self, event):
        if not self.client or not hasattr(self.client, "reannounce_torrent"):
            self.statusbar.SetStatusText("Reannounce not supported by this client.", 0)
            return
        self._apply_to_selected(self.client.reannounce_torrent, "Reannounce")

    def _set_clipboard_text(self, text: str) -> bool:
        try:
            if not wx.TheClipboard.Open():
                return False
            wx.TheClipboard.SetData(wx.TextDataObject(text))
            wx.TheClipboard.Close()
            return True
        except Exception:
            try:
                wx.TheClipboard.Close()
            except Exception:
                pass
            return False

    def _get_selected_torrent_objects(self):
        hashes = self.torrent_list.get_selected_hashes()
        if not hashes:
            return [], []
        tmap = {}
        for t in self.all_torrents:
            h = t.get("hash")
            if h:
                tmap[h] = t
        objs = []
        missing = []
        for h in hashes:
            t = tmap.get(h)
            if t:
                objs.append(t)
            else:
                missing.append(h)
        return objs, missing

    def on_copy_info_hash(self, event):
        objs, missing = self._get_selected_torrent_objects()
        hashes = [t.get("hash") for t in objs if t.get("hash")] + missing
        hashes = [h for h in hashes if h]
        if not hashes:
            self.statusbar.SetStatusText("No torrents selected.", 0)
            return
        text = "\n".join(hashes)
        if self._set_clipboard_text(text):
            self.statusbar.SetStatusText("Info hash copied to clipboard.", 0)
        else:
            self.statusbar.SetStatusText("Failed to access clipboard.", 0)

    def on_copy_magnet(self, event):
        objs, missing = self._get_selected_torrent_objects()
        hashes = [t.get("hash") for t in objs if t.get("hash")] + missing
        hashes = [h for h in hashes if h]
        if not hashes:
            self.statusbar.SetStatusText("No torrents selected.", 0)
            return

        magnets = []
        for h in hashes:
            magnets.append(f"magnet:?xt=urn:btih:{h}")

        text = "\n".join(magnets)
        if self._set_clipboard_text(text):
            self.statusbar.SetStatusText("Magnet link(s) copied to clipboard.", 0)
        else:
            self.statusbar.SetStatusText("Failed to access clipboard.", 0)

    def _open_path(self, path: str):
        if not path or not os.path.isdir(path):
            return False
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
                return True
            if sys.platform == "darwin":
                subprocess.Popen(["open", path])
                return True
            subprocess.Popen(["xdg-open", path])
            return True
        except Exception:
            return False

    def on_open_download_folder(self, event):
        objs, missing = self._get_selected_torrent_objects()
        if not objs:
            self.statusbar.SetStatusText("No torrent selected.", 0)
            return
        # open the first selected torrent folder
        t = objs[0]
        path = t.get("save_path") or ""
        if not path:
            # fallback to client default save path
            path = self.client_default_save_path or ""
        if self._open_path(path):
            self.statusbar.SetStatusText("Opened download folder.", 0)
        else:
            self.statusbar.SetStatusText("Download folder not available.", 0)

    def on_create_torrent(self, event):
        dlg = CreateTorrentDialog(self)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                dlg.Destroy()
                return
            try:
                opts = dlg.get_options()
            except Exception as e:
                dlg.Destroy()
                wx.MessageBox(str(e), "Create Torrent", wx.OK | wx.ICON_ERROR)
                return
            dlg.Destroy()
        except Exception:
            try:
                dlg.Destroy()
            except Exception:
                pass
            raise

        if not lt:
            wx.MessageBox("libtorrent is not available. Torrent creation requires python-libtorrent.", "Create Torrent", wx.OK | wx.ICON_ERROR)
            return

        source_path = opts["source_path"]
        output_path = opts["output_path"]

        progress = wx.ProgressDialog(
            "Create Torrent",
            "Hashing pieces and generating torrent metadata...",
            maximum=100,
            parent=self,
            style=wx.PD_APP_MODAL | wx.PD_PULSE | wx.PD_ELAPSED_TIME,
        )

        result = {"torrent_bytes": None, "magnet": "", "info_hash": "", "error": None}

        def worker():
            try:
                torrent_bytes, magnet, info_hash = create_torrent_bytes(
                    source_path=source_path,
                    trackers=opts.get("trackers", []),
                    web_seeds=opts.get("web_seeds", []),
                    piece_size=opts.get("piece_size", 0),
                    private=opts.get("private", False),
                    comment=opts.get("comment", ""),
                    creator=opts.get("creator", ""),
                    source=opts.get("source", ""),
                )
                # Write output
                out_dir = os.path.dirname(os.path.abspath(output_path))
                if out_dir and not os.path.isdir(out_dir):
                    os.makedirs(out_dir, exist_ok=True)
                with open(output_path, "wb") as f:
                    f.write(torrent_bytes)
                result["torrent_bytes"] = torrent_bytes
                result["magnet"] = magnet
                result["info_hash"] = info_hash
            except Exception as e:
                result["error"] = str(e)

        th = threading.Thread(target=worker, daemon=True)
        th.start()

        def poll():
            if th.is_alive():
                try:
                    progress.Pulse()
                except Exception:
                    pass
                wx.CallLater(200, poll)
                return
            try:
                progress.Destroy()
            except Exception:
                pass

            if result["error"]:
                wx.MessageBox(result["error"], "Create Torrent", wx.OK | wx.ICON_ERROR)
                return

            # Optional clipboard copy
            if opts.get("copy_magnet") and result.get("magnet"):
                self._set_clipboard_text(result["magnet"])

            # Optional add to client
            if opts.get("add_to_client") and self.client:
                try:
                    # Add torrent file content; prompt for save path via existing dialog
                    with open(output_path, "rb") as f:
                        content = f.read()
                    self._prepare_auto_start()
                    generation = self.client_generation
                    client = self.client
                    self.statusbar.SetStatusText("Adding created torrent...", 0)
                    self.thread_pool.submit(
                        self._add_torrent_file_background,
                        client,
                        generation,
                        content,
                        None,
                        None,
                        "Created torrent added",
                    )
                except Exception as e:
                    wx.MessageBox(f"Created torrent, but failed to add to client: {e}", "Create Torrent", wx.OK | wx.ICON_WARNING)

            msg = f"Torrent created:\n{output_path}"
            if result.get("info_hash"):
                msg += f"\nInfo Hash: {result['info_hash']}"
            if result.get("magnet"):
                msg += "\nMagnet copied to clipboard." if opts.get("copy_magnet") else f"\nMagnet: {result['magnet']}"
            wx.MessageBox(msg, "Create Torrent", wx.OK | wx.ICON_INFORMATION)

        wx.CallLater(200, poll)

    def on_remove(self, event):
        hashes = self.torrent_list.get_selected_hashes()
        if hashes and wx.MessageBox(f"Remove {len(hashes)} torrents?", "Confirm", wx.YES_NO) == wx.YES:
            self.statusbar.SetStatusText("Removing torrents...", 0)
            self.thread_pool.submit(self._remove_background, hashes, False)
            
    def on_remove_data(self, event):
        hashes = self.torrent_list.get_selected_hashes()
        if not hashes:
            return
        count = len(hashes)
        label = 'torrent' if count == 1 else 'torrents'
        if wx.MessageBox(f"Remove {count} {label} AND DATA?", "Confirm", wx.YES_NO | wx.ICON_WARNING) != wx.YES:
            return
        self.statusbar.SetStatusText("Removing torrents and data...", 0)
        self.thread_pool.submit(self._remove_background, hashes, True)

    def _remove_background(self, hashes, with_data):
        try:
            if hasattr(self.client, 'remove_torrents'):
                self.client.remove_torrents(hashes, with_data)
            else:
                for h in hashes:
                    if with_data:
                        self.client.remove_torrent_with_data(h)
                    else:
                        self.client.remove_torrent(h)
            wx.CallAfter(self._on_action_complete, "Removed torrents")
        except Exception as e:
            wx.CallAfter(self._on_action_error, f"Remove failed: {e}")

    def _on_action_complete(self, msg):
        self.statusbar.SetStatusText(msg, 0)
        self.refresh_data()

    def _on_action_error(self, msg):
         wx.MessageBox(msg, "Error", wx.OK | wx.ICON_ERROR)
         self.statusbar.SetStatusText("Error occurred", 0)

    def on_select_all(self, event):
        count = self.torrent_list.GetItemCount()
        for i in range(count):
            self.torrent_list.Select(i)

    def on_filter_change(self, event):
        item = event.GetItem()
        if not item.IsOk():
            return

        target_window = self.right_splitter
        if item == self.rss_id:
            target_window = self.rss_panel

        current_window = self.splitter.GetWindow2()
        
        if current_window != target_window:
            if current_window:
                self.splitter.ReplaceWindow(current_window, target_window)
                current_window.Hide()
            else:
                # If unsplit, split it again
                self.splitter.SplitVertically(self.sidebar, target_window, 220)
            target_window.Show()

        if item != self.rss_id:
            text = self.sidebar.GetItemText(item)
            if "(" in text:
                text = text.rsplit(" (", 1)[0]
            self.current_filter = text
            self.refresh_data()

    def on_torrent_selected(self, event):
        # Update details panel
        hashes = self.torrent_list.get_selected_hashes()
        if hashes:
            self.details_panel.load_torrent(hashes[0])
        else:
            self.details_panel.load_torrent(None)
        event.Skip()

    def on_list_key(self, event):
        event.Skip()

    def on_context_menu(self, event):
        menu = wx.Menu()

        start = menu.Append(wx.ID_ANY, "Start")
        pause = menu.Append(wx.ID_ANY, "Pause")
        resume = menu.Append(wx.ID_ANY, "Resume")

        menu.AppendSeparator()
        recheck = menu.Append(wx.ID_ANY, "Force Recheck")
        reannounce = menu.Append(wx.ID_ANY, "Force Reannounce")

        menu.AppendSeparator()
        copy_hash = menu.Append(wx.ID_ANY, "Copy Info Hash")
        copy_magnet = menu.Append(wx.ID_ANY, "Copy Magnet Link")
        open_folder = menu.Append(wx.ID_ANY, "Open Download Folder")

        menu.AppendSeparator()
        remove = menu.Append(wx.ID_ANY, "Remove")
        remove_data = menu.Append(wx.ID_ANY, "Remove with Data")

        self.Bind(wx.EVT_MENU, self.on_start, start)
        self.Bind(wx.EVT_MENU, self.on_pause, pause)
        self.Bind(wx.EVT_MENU, self.on_resume, resume)
        self.Bind(wx.EVT_MENU, self.on_recheck, recheck)
        self.Bind(wx.EVT_MENU, self.on_reannounce, reannounce)
        self.Bind(wx.EVT_MENU, self.on_copy_info_hash, copy_hash)
        self.Bind(wx.EVT_MENU, self.on_copy_magnet, copy_magnet)
        self.Bind(wx.EVT_MENU, self.on_open_download_folder, open_folder)
        self.Bind(wx.EVT_MENU, self.on_remove, remove)
        self.Bind(wx.EVT_MENU, self.on_remove_data, remove_data)

        self.PopupMenu(menu)
        menu.Destroy()

    def try_auto_connect(self):
        default_id = self.config_manager.get_default_profile_id()
        if default_id:
             self.connect_profile(default_id)
        
        # Check for CLI args
        if len(sys.argv) > 1:
            self.pending_cli_arg = sys.argv[1]
            # If not connected and no default, prompt for a profile.
            if not self.connected and not default_id:
                self.on_connect(None)
            elif self.connected:
                arg = self.pending_cli_arg
                self.pending_cli_arg = None
                self._process_cli_arg(arg)

        if not self.connected and not default_id and not self.pending_cli_arg:
            self.on_connect(None)

if __name__ == "__main__":
    try:
        print("Starting application...")
        app = wx.App(False) # False = don't redirect stdout/stderr to window
        print("wx.App initialized.")

        # Single Instance Check
        name = f"SerrebiTorrent-{wx.GetUserId()}"
        checker = wx.SingleInstanceChecker(name)
        if checker.IsAnotherRunning():
            wx.MessageBox("Another instance of SerrebiTorrent is already running.", "Error", wx.OK | wx.ICON_ERROR)
            sys.exit(0)

        frame = MainFrame()
        print("MainFrame initialized.")
        frame.Show()
        print("MainFrame shown. Entering MainLoop.")
        app.MainLoop()
        print("MainLoop exited.")
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        input("Press Enter to exit...")
