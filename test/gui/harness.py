"""GUI test harness for the Midvatten plugin, run inside a real QGIS.

This is the *test* counterpart to the wiki screenshot ``Context`` described in
``docs/GUI_AUTOMATION.md``. It adds the two things a screenshot grabber lacks:

* **Automatic oracles** -- a ``QgsMessageLog`` listener, a ``sys.excepthook``
  chain and a Qt message handler, so that *any* traceback or unexpected
  ``Qgis.Critical`` that a scene provokes is recorded and fails the test, even
  when a window did open and looked fine.
* **Assertion helpers** on ``Context`` -- ``db_scalar``, ``on_screen`` -- plus
  ``sweep_action``, the generalized dispatch-one-action-and-classify-the-outcome
  used by the coverage sweep.

Never imported on the host; it imports ``qgis`` and the plugin.
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

import qgis.utils
from qgis.core import Qgis, QgsApplication, QgsProject
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QEventLoop, QTimer, qInstallMessageHandler, QtMsgType
from qgis.PyQt.QtWidgets import QApplication, QDialog, QWidget

from midvatten.tools.utils.db_utils.dialect import ident
from midvatten.tools.utils.db_utils.execution import sql_load_fr_db


# --------------------------------------------------------------------------
# Oracles
# --------------------------------------------------------------------------
class Oracles:
    """Captures everything that should fail a test but does not raise on its own:
    QGIS message-log entries, unhandled Python tracebacks, and Qt critical/fatal
    messages. Entries are appended in order, so a scene asks "what was logged
    since I started?" by remembering a checkpoint (the list lengths) and slicing."""

    def __init__(self) -> None:
        self.messages: list[dict] = []        # {tag, level, text}
        self.tracebacks: list[dict] = []       # {text}
        self._installed = False
        self._orig_excepthook = None
        self._orig_qt_handler = None

    def install(self) -> None:
        if self._installed:
            return
        self._installed = True
        QgsApplication.messageLog().messageReceived.connect(self._on_message)
        self._orig_excepthook = sys.excepthook
        sys.excepthook = self._on_excepthook
        self._orig_qt_handler = qInstallMessageHandler(self._on_qt_message)

    def _on_message(self, text: str, tag: str, level) -> None:
        self.messages.append({"tag": tag, "level": int(level), "text": text})

    def _on_excepthook(self, exc_type, exc_value, exc_tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb)).strip()
        self.tracebacks.append({"text": text})
        if self._orig_excepthook is not None:
            self._orig_excepthook(exc_type, exc_value, exc_tb)

    def _on_qt_message(self, msg_type, context, message) -> None:
        # Only the genuinely bad Qt levels; QtWarningMsg is far too noisy under Xvfb.
        if msg_type in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            self.tracebacks.append({"text": f"Qt {msg_type}: {message}"})
        if self._orig_qt_handler is not None:
            try:
                self._orig_qt_handler(msg_type, context, message)
            except Exception:
                pass

    # -- querying since a checkpoint ------------------------------------
    def checkpoint(self) -> tuple[int, int]:
        return len(self.messages), len(self.tracebacks)

    def since(self, cp: tuple[int, int]) -> tuple[list[dict], list[dict]]:
        return self.messages[cp[0]:], self.tracebacks[cp[1]:]


# --------------------------------------------------------------------------
# Context
# --------------------------------------------------------------------------
class Context:
    def __init__(self, plugin, iface, out_dir: Path, oracles: Oracles,
                 default_selection: tuple[str, str] | None = None):
        self.plugin = plugin
        self.iface = iface
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.oracles = oracles
        # A (layer_name, expression) the plugin-specific runner supplies so most
        # needs_selection tools take their happy path. Fixture/plugin knowledge
        # lives with the runner, not in this shared class.
        self.default_selection = default_selection
        self._modal_count = 0
        self._modal_log: list[str] = []
        self._reaper: QTimer | None = None

    @staticmethod
    def _dismiss(w: QWidget) -> None:
        """Close a window the right way: reject a dialog, close anything else."""
        try:
            w.reject() if isinstance(w, QDialog) else w.close()
        except RuntimeError:
            pass

    # -- continuous modal reaper ---------------------------------------
    def install_modal_reaper(self, interval_ms: int = 700) -> None:
        """A modal dialog blocks whatever triggered it until it is closed. A
        per-action one-shot misses modals that appear *late* (a QMessageBox a
        tool pops after some work), which then hang the whole run. This timer
        runs for the life of the process and dismisses any modal the instant it
        sees one, recording its class so sweep_action can attribute it."""
        def reap():
            dlg = QApplication.activeModalWidget()
            if dlg is not None:
                self._modal_count += 1
                cls = type(dlg).__name__
                self._modal_log.append(cls)
                self.grab(dlg, f"modal_{self._modal_count:03d}_{cls}")
                self._dismiss(dlg)
        self._reaper = QTimer()
        self._reaper.timeout.connect(reap)
        self._reaper.start(interval_ms)

    # -- time -----------------------------------------------------------
    def wait(self, ms: int) -> None:
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    # -- layers ---------------------------------------------------------
    def layer(self, name: str):
        # Deliberately tolerant (returns None on miss), unlike layer_utils.
        # find_layer which raises -- the sweep must survive a missing layer.
        layers = QgsProject.instance().mapLayersByName(name)
        return layers[0] if layers else None

    def activate(self, layer_name: str):
        lyr = self.layer(layer_name)
        if lyr is not None:
            self.iface.setActiveLayer(lyr)
        return lyr

    def select_some(self, layer_name: str, expression: str | None = None, limit: int = 5) -> int:
        """Select a handful of features so needs_selection actions take their
        happy path. Prefer an explicit expression; otherwise the first `limit`
        features by id."""
        lyr = self.layer(layer_name)
        if lyr is None:
            return 0
        if expression:
            lyr.selectByExpression(expression)
        else:
            ids = [f.id() for f in lyr.getFeatures()][:limit]
            lyr.selectByIds(ids)
        return lyr.selectedFeatureCount()

    def clear_selections(self) -> None:
        for lyr in QgsProject.instance().mapLayers().values():
            try:
                lyr.removeSelection()
            except (AttributeError, RuntimeError):
                pass

    # -- db -------------------------------------------------------------
    def db_scalar(self, sql: str):
        ok, rows = sql_load_fr_db(sql, print_error_message_in_bar=False)
        if not ok or not rows:
            return None
        return rows[0][0]

    def db_count(self, table: str) -> int | None:
        val = self.db_scalar(f"SELECT count(*) FROM {ident(table)}")
        return None if val is None else int(val)

    # -- widgets --------------------------------------------------------
    def on_screen(self, widget: QWidget) -> bool:
        if widget is None or not widget.isVisible():
            return False
        screen = widget.screen() or QApplication.primaryScreen()
        geom = screen.geometry()
        top_left = widget.mapToGlobal(widget.rect().topLeft())
        return (top_left.x() >= geom.x() - 50 and top_left.y() >= geom.y() - 50
                and widget.width() > 0 and widget.height() > 0)

    def grab(self, widget: QWidget, name: str) -> Path | None:
        try:
            self.wait(150)
            widget.raise_()
            QApplication.processEvents()
            pix = widget.grab()
            path = self.out_dir / f"{name}.png"
            if pix.save(str(path)):
                return path
        except (RuntimeError, AttributeError):
            pass
        return None

    def close_tools(self) -> None:
        for w in list(QApplication.topLevelWidgets()):
            if w is self.iface.mainWindow() or not w.isVisible():
                continue
            self._dismiss(w)
        self.wait(250)

    # -- the coverage sweep --------------------------------------------
    def _prepare(self, spec) -> None:
        """Set the minimal preconditions each ActionSpec declares so _dispatch
        does not bail out before reaching the tool. The runner-supplied
        default_selection is a broadly-useful base (it satisfies the many
        needs_selection tools that read the active layer's selection); the
        declared active layer (if any) is activated and selected on top."""
        self.clear_selections()
        if self.default_selection is not None:
            layer_name, expression = self.default_selection
            self.select_some(layer_name, expression)
            self.activate(layer_name)
        if spec.needs_active_layer:
            lyr = self.activate(spec.needs_active_layer)
            if lyr is not None and lyr.selectedFeatureCount() == 0:
                self.select_some(spec.needs_active_layer)
        elif spec.needs_selection:
            active = self.iface.activeLayer()
            if active is not None and active.selectedFeatureCount() == 0:
                self.select_some(active.name())

    def sweep_action(self, spec) -> dict:
        """Dispatch one action exactly as a menu click would; the continuous
        modal reaper dismisses any modal it opens. Classify the outcome. Never
        raises. Requires install_modal_reaper() to have been called."""
        self._prepare(spec)
        cp = self.oracles.checkpoint()
        modal_before = self._modal_count

        before = {sip.unwrapinstance(w) for w in QApplication.topLevelWidgets()}
        dispatch_error = None
        try:
            self.plugin._dispatch(spec)
        except Exception:
            dispatch_error = traceback.format_exc().strip().splitlines()[-1]
        self.wait(1200)

        modal_seen = self._modal_count > modal_before
        modal_cls = self._modal_log[-1] if modal_seen else None
        msgs, tbs = self.oracles.since(cp)
        crit = [m for m in msgs if m["level"] >= int(Qgis.Critical)]
        warn = [m for m in msgs if m["level"] == int(Qgis.Warning)]

        # New non-modal, visible top-level window (persistent tools land in
        # _open_tools; others are found by diffing top-level widgets).
        persistent = self.plugin._open_tools.get(spec.id)
        window = None
        if isinstance(persistent, QWidget) and persistent.isVisible():
            window = persistent
        else:
            new = [w for w in QApplication.topLevelWidgets()
                   if sip.unwrapinstance(w) not in before and w.isVisible()
                   and w is not self.iface.mainWindow()]
            if new:
                window = max(new, key=lambda w: w.width() * w.height())

        result: dict = {"id": spec.id, "label": spec.label, "menu": spec.menu}
        if dispatch_error or tbs:
            result["status"] = "FAIL"
            result["detail"] = dispatch_error or tbs[-1]["text"].splitlines()[-1]
        elif crit:
            result["status"] = "FAIL"
            result["detail"] = "Qgis.Critical: " + crit[-1]["text"].strip().replace("\n", " ")[:200]
        elif window is not None:
            result["status"] = "ok"
            result["detail"] = f"window {type(window).__name__}"
            result["on_screen"] = self.on_screen(window)
            self.grab(window, f"sweep_{spec.id}")
        elif modal_seen:
            result["status"] = "ok"
            result["detail"] = f"modal {modal_cls}"
        elif warn:
            result["status"] = "blocked"
            result["detail"] = "warning: " + warn[-1]["text"].strip().replace("\n", " ")[:200]
        else:
            result["status"] = "no-window"
            result["detail"] = "dispatch returned, no window and no message"

        if tbs:
            result["tracebacks"] = [t["text"].splitlines()[-1] for t in tbs]
        self.close_tools()
        self.clear_selections()
        return result
