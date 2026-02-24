"""
Plugin tool registration: create QAction and add to toolbar/menu.
Used by midvatten_plugin.Midvatten to avoid duplicating registration logic.
"""

from pathlib import Path
from typing import Callable, List, Optional

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMenu


def add_plugin_action(
    iface,
    menu: QMenu,
    plugin_dir: Path,
    actions_list: List[QAction],
    icon_path: str,
    text: str,
    callback: Callable,
    enabled_flag: bool = True,
    add_to_menu: bool = False,
    add_to_toolbar: bool = False,
    status_tip: Optional[str] = None,
    whats_this: Optional[str] = None,
    parent=None,
) -> QAction:
    """Create a QAction and optionally add it to the plugin toolbar and menu.

    :param iface: QGIS interface (for addToolBarIcon, addPluginToMenu, mainWindow).
    :param menu: Plugin menu to add the action to when add_to_menu is True.
    :param plugin_dir: Plugin directory (Path) for resolving icon path.
    :param actions_list: List to append the new action to (for unload).
    :param icon_path: Filename under plugin_dir/icons/ (e.g. 'create_new.xpm').
    :param text: Action label text.
    :param callback: Callable invoked when the action is triggered.
    :param enabled_flag: Whether the action is enabled by default.
    :param add_to_menu: If True, add action to the plugin menu.
    :param add_to_toolbar: If True, add action to the Plugins toolbar.
    :param status_tip: Optional status bar text.
    :param whats_this: Optional "What's this" text.
    :param parent: Parent widget for the action (defaults to main window).
    :returns: The created QAction.
    """
    icon_full_path = plugin_dir / "icons" / icon_path
    icon = QIcon(str(icon_full_path))
    action = QAction(icon, text, parent)
    action.triggered.connect(callback)
    action.setEnabled(enabled_flag)

    if parent is None:
        parent = iface.mainWindow()

    if status_tip is not None:
        action.setStatusTip(status_tip)

    if whats_this is not None:
        action.setWhatsThis(whats_this)

    if add_to_toolbar:
        iface.addToolBarIcon(action)

    if add_to_menu:
        iface.addPluginToMenu(menu, action)

    actions_list.append(action)
    return action
