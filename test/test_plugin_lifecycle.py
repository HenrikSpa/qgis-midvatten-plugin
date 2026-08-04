"""Regression tests for Midvatten plugin signal and UI lifecycle cleanup."""

from unittest import mock

import pytest

import midvatten_plugin
from midvatten_plugin import Midvatten


class FakeSignal:
    def __init__(self):
        self.slots = []
        self.connect_calls = 0
        self.disconnect_calls = 0

    def connect(self, slot):
        self.connect_calls += 1
        self.slots.append(slot)

    def disconnect(self, slot):
        self.disconnect_calls += 1
        try:
            self.slots.remove(slot)
        except ValueError as error:
            raise TypeError("slot is not connected") from error

    def emit(self, *args):
        for slot in tuple(self.slots):
            slot(*args)


class FakeMessageLog:
    def __init__(self):
        self.messageReceived = FakeSignal()


class FakeIface:
    def __init__(self):
        self.projectRead = FakeSignal()
        self.newProjectCreated = FakeSignal()
        self.removeToolBarIcon = mock.Mock()
        self.unregisterMainWindowAction = mock.Mock()


def make_signal_plugin(iface):
    plugin = Midvatten.__new__(Midvatten)
    plugin.iface = iface
    plugin.project_opened = mock.Mock()
    plugin.project_created = mock.Mock()
    plugin._signals_connected = False
    plugin._open_tools = {}
    plugin.actions = []
    plugin._actions_manifest = []
    plugin._qactions = {}
    plugin._submenus = {}
    plugin.menu = None
    plugin.owns_midv_menu = False
    plugin.tool_bar = None
    plugin.action_midvatten_settings = None
    plugin.action_load_layers = None
    plugin.action_about = None
    return plugin


@pytest.fixture
def signal_plugin(monkeypatch):
    iface = FakeIface()
    message_log = FakeMessageLog()
    monkeypatch.setattr(
        midvatten_plugin.QgsApplication,
        "messageLog",
        staticmethod(lambda: message_log),
    )
    plugin = make_signal_plugin(iface)
    log_writer = mock.Mock()
    monkeypatch.setattr(
        midvatten_plugin.common_utils,
        "write_qgs_log_to_file",
        log_writer,
    )
    return plugin, iface, message_log, log_writer


def test_unload_prevents_project_and_message_callbacks(signal_plugin):
    plugin, iface, message_log, log_writer = signal_plugin

    plugin._connect_signals()
    plugin.unload()

    iface.projectRead.emit()
    iface.newProjectCreated.emit()
    message_log.messageReceived.emit("message", "tag", 0)

    plugin.project_opened.assert_not_called()
    plugin.project_created.assert_not_called()
    log_writer.assert_not_called()
    assert not plugin._signals_connected


def test_reload_keeps_each_connection_and_log_once(signal_plugin):
    plugin, iface, message_log, log_writer = signal_plugin

    plugin._connect_signals()
    plugin._connect_signals()
    iface.projectRead.emit()
    iface.newProjectCreated.emit()
    message_log.messageReceived.emit("message", "tag", 0)

    assert iface.projectRead.connect_calls == 1
    assert iface.newProjectCreated.connect_calls == 1
    assert message_log.messageReceived.connect_calls == 1
    plugin.project_opened.assert_called_once_with()
    plugin.project_created.assert_called_once_with()
    log_writer.assert_called_once_with("message", "tag", 0)

    plugin._disconnect_signals()
    plugin._connect_signals()
    iface.projectRead.emit()
    iface.newProjectCreated.emit()
    message_log.messageReceived.emit("message 2", "tag", 1)

    assert iface.projectRead.connect_calls == 2
    assert iface.newProjectCreated.connect_calls == 2
    assert message_log.messageReceived.connect_calls == 2
    assert len(iface.projectRead.slots) == 1
    assert len(iface.newProjectCreated.slots) == 1
    assert len(message_log.messageReceived.slots) == 1
    assert plugin.project_opened.call_count == 2
    assert plugin.project_created.call_count == 2
    assert log_writer.call_count == 2


def test_unload_disposes_owned_ui_and_is_safe_twice():
    iface = FakeIface()
    plugin = make_signal_plugin(iface)
    parent_menu = mock.Mock()
    menu = mock.Mock()
    menu.parentWidget.return_value = parent_menu
    submenu = mock.Mock()
    action_settings = mock.Mock()
    action_manifest = mock.Mock()
    action_about = mock.Mock()
    toolbar = mock.Mock()
    settings_dialog = mock.Mock()
    persistent_tool = mock.Mock()
    owned_actions = (action_settings, action_manifest, action_about)

    plugin.menu = menu
    plugin.owns_midv_menu = True
    plugin._submenus = {"import": submenu}
    plugin.tool_bar = toolbar
    plugin.actions = list(owned_actions)
    plugin._actions_manifest = [mock.sentinel.action_spec]
    plugin._qactions = {"manifest": action_manifest}
    plugin.action_midvatten_settings = action_settings
    plugin.action_load_layers = action_manifest
    plugin.action_about = action_about
    plugin.midvsettingsdialog = settings_dialog
    plugin._open_tools = {"persistent": persistent_tool}

    plugin.unload()

    settings_dialog.close.assert_called_once_with()
    settings_dialog.deleteLater.assert_called_once_with()
    persistent_tool.close.assert_called_once_with()
    persistent_tool.deleteLater.assert_called_once_with()
    toolbar.deleteLater.assert_called_once_with()
    submenu.deleteLater.assert_called_once_with()
    menu.deleteLater.assert_called_once_with()
    parent_menu.removeAction.assert_called_once_with(menu.menuAction.return_value)
    iface.unregisterMainWindowAction.assert_called_once_with(action_settings)
    assert iface.removeToolBarIcon.call_count == len(owned_actions)
    for action in owned_actions:
        action.triggered.disconnect.assert_called_once_with()
        action.deleteLater.assert_called_once_with()

    assert plugin.actions == []
    assert plugin._actions_manifest == []
    assert plugin._qactions == {}
    assert plugin._submenus == {}
    assert plugin._open_tools == {}
    assert plugin.menu is None
    assert plugin.tool_bar is None
    assert plugin.midvsettingsdialog is None

    plugin.unload()

    settings_dialog.close.assert_called_once_with()
    settings_dialog.deleteLater.assert_called_once_with()
    persistent_tool.close.assert_called_once_with()
    persistent_tool.deleteLater.assert_called_once_with()
    toolbar.deleteLater.assert_called_once_with()
    for action in owned_actions:
        action.triggered.disconnect.assert_called_once_with()
        action.deleteLater.assert_called_once_with()
