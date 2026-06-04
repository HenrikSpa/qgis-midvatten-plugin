"""Dialog to resolve duplicate timestamps in the logger editor.

Reads the editor's classification and calls its buffer resolution operations
(all undoable and persisted on Save). Visual comparison is delegated to the
editor's plot via _focus_plot_on_instants.
"""

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


def _tr(text: str) -> str:
    return QCoreApplication.translate("ResolveDuplicatesDialog", text)


class ResolveDuplicatesDialog(QDialog):
    def __init__(self, editor, parent=None):
        super().__init__(parent or editor)
        self._editor = editor
        self.setWindowTitle(_tr("Resolve duplicate timestamps"))
        self.resize(640, 480)
        self._outer = QVBoxLayout(self)
        self._body_holder = QVBoxLayout()
        self._outer.addLayout(self._body_holder)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        self._outer.addWidget(buttons)
        self._rebuild()

    # --- data helpers -------------------------------------------------
    def _groups(self) -> list:
        return self._editor._classify_duplicates()

    def _bucket_counts(self, groups: list | None = None) -> dict:
        counts = {"redundant": 0, "cross_source": 0, "conflict": 0}
        for g in self._groups() if groups is None else groups:
            counts[g["kind"]] += 1
        return counts

    def _cross_source_values(self, groups: list | None = None) -> list:
        """Distinct sources appearing in cross-source groups (for keep choices)."""
        sources = []
        for g in self._groups() if groups is None else groups:
            if g["kind"] != "cross_source":
                continue
            for r in g["rows"]:
                if r["source"] not in sources:
                    sources.append(r["source"])
        return sources

    def _show_on_plot_button(self, kind: str) -> QPushButton:
        """A 'Show on plot' button that focuses the plot on this kind's instants."""
        btn = QPushButton(_tr("Show on plot"), self)
        btn.clicked.connect(
            lambda: self._on_show_instants(
                [g["instant"] for g in self._groups() if g["kind"] == kind]
            )
        )
        return btn

    # --- actions ------------------------------------------------------
    def _on_remove_redundant(self) -> None:
        self._editor._remove_redundant_duplicates()
        self._after_change()

    def _on_keep_source(self, keep_source: str) -> None:
        self._editor._remove_cross_source_overlaps(keep_source)
        self._after_change()

    def _on_show_instants(self, instants: list) -> None:
        self._editor._focus_plot_on_instants(instants)

    def _after_change(self) -> None:
        try:
            self._editor.update_plot()
        except Exception:
            pass
        self._rebuild()

    # --- view ---------------------------------------------------------
    def _clear_body(self) -> None:
        while self._body_holder.count():
            item = self._body_holder.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

    def _rebuild(self) -> None:
        self._clear_body()
        groups = self._groups()
        counts = self._bucket_counts(groups)

        if not groups:
            self._body_holder.addWidget(
                QLabel(_tr("No duplicate timestamps remain."), self)
            )
            return

        # Bucket 1 — redundant
        if counts["redundant"]:
            box = QGroupBox(
                _tr("Redundant (identical values) — %s") % counts["redundant"], self
            )
            lay = QVBoxLayout(box)
            lay.addWidget(
                QLabel(
                    _tr("Keeps the higher datetime-precision row, drops the rest."),
                    self,
                )
            )
            row = QHBoxLayout()
            btn = QPushButton(
                _tr("Remove %s redundant row(s)")
                % sum(len(g["rows"]) - 1 for g in groups if g["kind"] == "redundant"),
                self,
            )
            btn.clicked.connect(self._on_remove_redundant)
            row.addWidget(btn)
            row.addWidget(self._show_on_plot_button("redundant"))
            row.addStretch()
            lay.addLayout(row)
            self._body_holder.addWidget(box)

        # Bucket 2 — cross-source
        if counts["cross_source"]:
            box = QGroupBox(
                _tr("Different sources — %s") % counts["cross_source"], self
            )
            lay = QVBoxLayout(box)
            lay.addWidget(
                QLabel(_tr("Keep one source at the overlapping instants:"), self)
            )
            for src in self._cross_source_values(groups):
                row = QHBoxLayout()
                label = src if (src and str(src).strip()) else _tr("(no source)")
                keep_btn = QPushButton(_tr("Keep '%s'") % label, self)
                keep_btn.clicked.connect(
                    lambda _checked=False, s=src: self._on_keep_source(s)
                )
                row.addWidget(keep_btn)
                row.addStretch()
                lay.addLayout(row)
            lay.addWidget(self._show_on_plot_button("cross_source"))
            self._body_holder.addWidget(box)

        # Bucket 3 — conflicts. Not enumerated value-by-value: there can be tens
        # of thousands. Point the user at the plot to compare and resolve via the
        # existing "Separate by datetime precision" + select + delete flow.
        if counts["conflict"]:
            box = QGroupBox(
                _tr("Conflicts (values differ) — %s") % counts["conflict"], self
            )
            lay = QVBoxLayout(box)
            lay.addWidget(
                QLabel(
                    _tr(
                        "These rows share a timestamp and source but differ in"
                        " value. Use 'Show on plot' to compare them, then keep the"
                        " correct line with 'Separate by datetime precision',"
                        " select it and delete the other."
                    ),
                    self,
                )
            )
            lay.addWidget(self._show_on_plot_button("conflict"))
            self._body_holder.addWidget(box)
