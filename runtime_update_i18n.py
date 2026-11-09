# Copyright (c) serrebidev and contributors
# SPDX-License-Identifier: MIT

"""Localized update workflow layered over the maintainer's updater implementation."""

from __future__ import annotations

import os
import sys

import wx

import main as legacy
from main_ui_i18n import resolved_language, tr_main


_PT_BR = {
    "Updates": "Atualizações",
    "Checking for updates...": "Verificando atualizações...",
    "An update check or install is already in progress.": "Já existe uma verificação ou instalação de atualização em andamento.",
    "You're already on the latest version.": "A versão mais recente já está instalada.",
    "No updates available.": "Nenhuma atualização disponível.",
    "Update Check Failed": "Falha ao verificar atualizações",
    "Update check failed.": "Falha ao verificar atualizações.",
    "Update Available": "Atualização disponível",
    "Update postponed.": "Atualização adiada.",
    "An update is already in progress.": "Já existe uma atualização em andamento.",
    "Updates are only available in the packaged app.": "As atualizações estão disponíveis apenas no aplicativo empacotado.",
    "Install directory not found.": "Diretório de instalação não encontrado.",
    "Downloading update...": "Baixando atualização...",
    "Verifying download...": "Verificando download...",
    "Extracting update...": "Extraindo atualização...",
    "Verifying signature...": "Verificando assinatura...",
    "Preparing restart...": "Preparando reinicialização...",
    "Updating...": "Atualizando...",
    "Updating SerrebiTorrent": "Atualizando o SerrebiTorrent",
    "Applying update...": "Aplicando atualização...",
    "Update prepared. Closing to install...": "Atualização preparada. Fechando para instalar...",
    "Update Failed": "Falha na atualização",
    "Update failed.": "Falha na atualização.",
    "Auto-update is not available for this build.": "A atualização automática não está disponível para esta compilação.",
    "Update canceled.": "Atualização cancelada.",
    "Downloaded update failed SHA-256 verification.": "A atualização baixada falhou na verificação SHA-256.",
    "Extracted update does not contain application files.": "A atualização extraída não contém os arquivos do aplicativo.",
    "Updated executable not found.": "Executável atualizado não encontrado.",
    "Update helper script not found.": "Script auxiliar de atualização não encontrado.",
    "Update prepared. The app will restart after it exits.": "Atualização preparada. O aplicativo será reiniciado após o encerramento.",
}

_PREFIX_PT_BR = (
    ("Update failed: ", "Falha na atualização: "),
    ("Update check failed: ", "Falha ao verificar atualizações: "),
    ("Network error while contacting Forgejo: ", "Erro de rede ao contatar o Forgejo: "),
    ("Network error while downloading update: ", "Erro de rede ao baixar a atualização: "),
    ("Failed to start update helper: ", "Falha ao iniciar o auxiliar de atualização: "),
    ("Authenticode verification failed: ", "Falha na verificação Authenticode: "),
)


def _language(frame):
    try:
        return frame._language()
    except Exception:
        try:
            return frame.config_manager.get_preferences().get("language", "system")
        except Exception:
            return "system"


def tr_update(text, language=None):
    translated = tr_main(text, language)
    if translated != text:
        return translated
    if resolved_language(language) != "pt-BR":
        return text
    if text in _PT_BR:
        return _PT_BR[text]
    for source, target in _PREFIX_PT_BR:
        if text.startswith(source):
            return target + text[len(source):]
    return text


def localized_check_for_updates(self, manual=False):
    language = _language(self)
    if self.update_check_in_progress or self.update_install_in_progress:
        if manual:
            wx.MessageBox(
                tr_update("An update check or install is already in progress.", language),
                tr_update("Updates", language),
                wx.OK | wx.ICON_INFORMATION,
            )
        return
    self.update_check_in_progress = True
    if hasattr(self, "statusbar"):
        self.statusbar.SetStatusText(tr_update("Checking for updates...", language), 0)
    self.thread_pool.submit(self._check_updates_background, manual)


def localized_on_no_update_available(self, manual):
    language = _language(self)
    self.update_check_in_progress = False
    if manual:
        wx.MessageBox(
            tr_update("You're already on the latest version.", language),
            tr_update("Updates", language),
            wx.OK | wx.ICON_INFORMATION,
        )
    if hasattr(self, "statusbar"):
        self.statusbar.SetStatusText(tr_update("No updates available.", language), 0)


def localized_on_update_check_failed(self, message, manual):
    language = _language(self)
    self.update_check_in_progress = False
    localized = tr_update(str(message), language)
    if manual:
        wx.MessageBox(
            localized,
            tr_update("Update Check Failed", language),
            wx.OK | wx.ICON_ERROR,
        )
    if hasattr(self, "statusbar"):
        self.statusbar.SetStatusText(tr_update("Update check failed.", language), 0)


def _localized_prompt_text(info, language):
    notes = str(info.manifest.get("notes_summary") or "").strip()
    if len(notes) > 1200:
        notes = notes[:1200].rstrip() + "..."
    details = (
        f"Versão atual: v{info.current_version}\n"
        f"Versão mais recente: v{info.latest_version}"
    )
    if notes:
        return f"{details}\n\nResumo da versão:\n{notes}\n\nBaixar e instalar agora?"
    return f"{details}\n\nBaixar e instalar agora?"


def localized_prompt_update(self, info):
    language = _language(self)
    try:
        if resolved_language(language) == "pt-BR":
            message = f"Uma nova versão do {legacy.APP_NAME} está disponível.\n\n{_localized_prompt_text(info, language)}"
        else:
            message = f"A new version of {legacy.APP_NAME} is available.\n\n{legacy.updater.build_update_prompt(info)}"
        if wx.MessageBox(
            message,
            tr_update("Update Available", language),
            wx.YES_NO | wx.ICON_INFORMATION,
        ) != wx.YES:
            if hasattr(self, "statusbar"):
                self.statusbar.SetStatusText(tr_update("Update postponed.", language), 0)
            return
        self._start_update_install(info)
    finally:
        self.update_check_in_progress = False


def localized_start_update_install(self, info):
    language = _language(self)
    if self.update_install_in_progress:
        wx.MessageBox(
            tr_update("An update is already in progress.", language),
            tr_update("Updates", language),
            wx.OK | wx.ICON_INFORMATION,
        )
        return
    if not getattr(sys, "frozen", False):
        wx.MessageBox(
            tr_update("Updates are only available in the packaged app.", language),
            tr_update("Updates", language),
            wx.OK | wx.ICON_WARNING,
        )
        return
    install_dir = os.path.dirname(sys.executable)
    if not os.path.isdir(install_dir):
        wx.MessageBox(
            tr_update("Install directory not found.", language),
            tr_update("Updates", language),
            wx.OK | wx.ICON_ERROR,
        )
        return
    self.update_install_in_progress = True
    self.update_progress_canceled = False
    message = tr_update("Downloading update...", language)
    self._show_update_progress(message, 0)
    if hasattr(self, "statusbar"):
        self.statusbar.SetStatusText(message, 0)
    self.thread_pool.submit(self._perform_update_background, info, install_dir)


def localized_show_update_progress(self, message, value=0):
    self._destroy_update_progress()
    language = _language(self)
    translated = tr_update(str(message), language)
    try:
        self.update_progress_dialog = wx.ProgressDialog(
            tr_update("Updating SerrebiTorrent", language),
            translated,
            maximum=100,
            parent=self,
            style=(
                wx.PD_APP_MODAL
                | wx.PD_CAN_ABORT
                | wx.PD_ELAPSED_TIME
                | wx.PD_REMAINING_TIME
                | wx.PD_SMOOTH
            ),
        )
        self.update_progress_dialog.Update(int(value), translated)
    except Exception:
        self.update_progress_dialog = None


def localized_on_update_progress(self, phase, fraction):
    language = _language(self)
    message = tr_update(str(phase or "Updating..."), language)
    if hasattr(self, "statusbar"):
        self.statusbar.SetStatusText(message, 0)
    dialog = self.update_progress_dialog
    if dialog is None:
        return
    try:
        if fraction is None:
            result = dialog.Pulse(message)
        else:
            pct = max(0, min(100, int(float(fraction) * 100)))
            result = dialog.Update(pct, message)
        keep_going = result[0] if isinstance(result, tuple) else bool(result)
        if not keep_going:
            self.update_progress_canceled = True
    except Exception:
        pass


def localized_on_update_started(self, message="Update prepared. The app will restart after it exits."):
    language = _language(self)
    if hasattr(self, "statusbar"):
        self.statusbar.SetStatusText(tr_update("Applying update...", language), 0)
    self._on_update_progress(tr_update("Update prepared. Closing to install...", language), 1.0)
    wx.CallLater(800, self.force_close)


def localized_on_update_failed(self, message):
    language = _language(self)
    self.update_install_in_progress = False
    self._destroy_update_progress()
    localized = tr_update(str(message), language)
    wx.MessageBox(
        f"{tr_update('Update failed.', language)} {localized}",
        tr_update("Update Failed", language),
        wx.OK | wx.ICON_ERROR,
    )
    if hasattr(self, "statusbar"):
        self.statusbar.SetStatusText(tr_update("Update failed.", language), 0)


def install_update_localization():
    legacy.MainFrame.check_for_updates = localized_check_for_updates
    legacy.MainFrame._on_no_update_available = localized_on_no_update_available
    legacy.MainFrame._on_update_check_failed = localized_on_update_check_failed
    legacy.MainFrame._prompt_update = localized_prompt_update
    legacy.MainFrame._start_update_install = localized_start_update_install
    legacy.MainFrame._show_update_progress = localized_show_update_progress
    legacy.MainFrame._on_update_progress = localized_on_update_progress
    legacy.MainFrame._on_update_started = localized_on_update_started
    legacy.MainFrame._on_update_failed = localized_on_update_failed
