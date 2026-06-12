"""GUI classes for managing plot templates and matplotlib styles.

PlotTemplates backs the template chooser in the section plot,
MatplotlibStyles the style chooser in the custom plot.
"""

import ast
import copy
import json
import os
from typing import Callable, Optional, TYPE_CHECKING

import matplotlib as mpl
from matplotlib import pyplot as plt
from qgis.PyQt import QtCore, QtWidgets
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QDesktopServices

from midvatten.tools.utils import message_utils, midvatten_utils
from midvatten.tools.utils.common_utils import (
    general_exception_handler,
    get_save_file_name_no_extension,
)
from midvatten.tools.utils.dialog_utils import Askuser
from midvatten.tools.utils.exceptions import UsageError, UserInterruptError
from midvatten.tools.utils.string_utils import (
    anything_to_string_representation,
    returnunicode,
)

if TYPE_CHECKING:
    from midvatten.tools.midvsettings import MidvSettings


class PlotTemplates:
    def __init__(
        self,
        plot_object,
        template_list,
        edit_button,
        load_button,
        save_as_button,
        import_button,
        remove_button,
        template_folder: str,
        templates_settingskey: str,
        loaded_template_settingskey: str,
        fallback_template: dict,
        msettings: Optional["MidvSettings"] = None,
    ):

        # Gui objects
        self.template_list = template_list
        self.edit_button = edit_button
        self.load_button = load_button
        self.save_as_button = save_as_button
        self.import_button = import_button
        self.remove_button = remove_button

        self.ms = msettings
        self.templates = {}
        self.loaded_template = {}

        self.template_folder = template_folder
        self.fallback_template = fallback_template
        self.templates_settingskey = templates_settingskey
        self.loaded_template_settingskey = loaded_template_settingskey

        self.templates = {}

        self.import_saved_templates()
        self.import_from_template_folder()

        try:
            self.loaded_template = self.string_to_dict(
                self.ms.settingsdict[self.loaded_template_settingskey]
            )
        except Exception:
            message_utils.MessagebarAndLog.warning(
                bar_msg=returnunicode(
                    QCoreApplication.translate(
                        "PlotTemplates",
                        "Failed to load saved template, loading default template instead.",
                    )
                )
            )
        if self.loaded_template:
            message_utils.MessagebarAndLog.info(
                log_msg=returnunicode(
                    QCoreApplication.translate(
                        "PlotTemplates", "Loaded template from midvatten settings %s."
                    )
                )
                % self.loaded_template_settingskey
            )

        default_filename = os.path.join(self.template_folder, "default.txt")

        if not self.loaded_template:
            if not os.path.isfile(default_filename):
                message_utils.MessagebarAndLog.warning(
                    bar_msg=returnunicode(
                        QCoreApplication.translate(
                            "PlotTemplates",
                            "Default template not found, loading hard coded default template.",
                        )
                    )
                )
            else:
                try:
                    self.load(self.templates[default_filename]["template"])
                except Exception as e:
                    message_utils.MessagebarAndLog.warning(
                        bar_msg=returnunicode(
                            QCoreApplication.translate(
                                "PlotTemplates",
                                "Failed to load default template, loading hard coded default template.",
                            )
                        ),
                        log_msg=returnunicode(
                            QCoreApplication.translate("PlotTemplates", "Error msg %s")
                        )
                        % str(e),
                    )
            if self.loaded_template:
                message_utils.MessagebarAndLog.info(
                    log_msg=returnunicode(
                        QCoreApplication.translate(
                            "PlotTemplates",
                            "Loaded template from default template file.",
                        )
                    )
                )

        if not self.loaded_template:
            self.loaded_template = self.fallback_template
            if self.loaded_template:
                message_utils.MessagebarAndLog.info(
                    log_msg=returnunicode(
                        QCoreApplication.translate(
                            "PlotTemplates",
                            "Loaded template from default hard coded template.",
                        )
                    )
                )

        self.edit_button.clicked.connect(lambda x: self.edit())
        self.load_button.clicked.connect(lambda x: self.load())
        self.save_as_button.clicked.connect(lambda x: self.save_as())
        self.import_button.clicked.connect(lambda x: self.import_templates())
        self.remove_button.clicked.connect(lambda x: self.remove())

    @general_exception_handler
    def edit(self) -> None:
        old_string = self.readable_output(self.loaded_template)

        msg = returnunicode(
            QCoreApplication.translate(
                "StoredSettings",
                "Replace the settings string with a new settings string.",
            )
        )
        new_string = QtWidgets.QInputDialog.getText(
            None,
            returnunicode(
                QCoreApplication.translate("StoredSettings", "Edit settings")
            ),
            msg,
            QtWidgets.QLineEdit.Normal,
            old_string,
        )
        if not new_string[1]:
            raise UserInterruptError()

        as_dict = self.string_to_dict(returnunicode(new_string[0]))

        self.loaded_template = as_dict

    @general_exception_handler
    def load(self, template: Optional[dict] = None):
        if isinstance(template, dict):
            self.loaded_template = template
        else:
            selected = self.template_list.selectedItems()
            if selected:
                filename = selected[0].filename
                template = self.parse_template(filename)
                if template:
                    self.templates[filename] = template
                self.loaded_template = self.templates[filename]["template"]

    @general_exception_handler
    def save_as(self) -> None:
        filename = get_save_file_name_no_extension(
            parent=None,
            caption=returnunicode(
                QCoreApplication.translate("PlotTemplates", "Choose a file name")
            ),
            directory="",
            filter="txt (*.txt)",
        )
        as_str = self.readable_output(self.loaded_template)
        with open(filename, "w", encoding="utf8") as of:
            of.write(as_str)

        name = os.path.splitext(os.path.basename(filename))[0]
        template = copy.deepcopy(self.loaded_template)
        self.templates[filename] = {
            "filename": filename,
            "template": template,
            "name": name,
        }

        self.update_settingsdict()
        self.update_template_list()

    @general_exception_handler
    def import_templates(self, filenames: Optional[list[str]] = None):
        if filenames is None:
            filenames = midvatten_utils.select_files(only_one_file=False, extension="")
        templates = {}
        if filenames:
            for filename in filenames:
                if not filename:
                    continue

                processed_before = filename in list(self.templates.keys())
                processed_now = filename in list(templates.keys())

                if not processed_before and not processed_now:
                    template = self.parse_template(filename)
                    if template:
                        templates[filename] = template

        self.templates.update(templates)
        self.update_settingsdict()
        self.update_template_list()

    @general_exception_handler
    def remove(self) -> None:
        selected = self.template_list.selectedItems()
        if selected:
            filename = selected[0].filename
            del self.templates[filename]
            self.update_settingsdict()
            self.update_template_list()

    @general_exception_handler
    def import_from_template_folder(self) -> None:
        for root, dirs, files in os.walk(self.template_folder):
            if files:
                filenames = [os.path.join(root, filename) for filename in files]
                self.import_templates(filenames)

    @general_exception_handler
    def import_saved_templates(self) -> None:
        filenames = [
            x for x in self.ms.settingsdict[self.templates_settingskey].split(";") if x
        ]
        if filenames:
            message_utils.MessagebarAndLog.info(
                log_msg=returnunicode(
                    QCoreApplication.translate("", "Loading saved templates %s")
                )
                % "\n".join(filenames)
            )
            self.import_templates(filenames)

    def parse_template(self, filename: str) -> dict:
        name = os.path.splitext(os.path.basename(filename))[0]
        if not os.path.isfile(filename):
            raise UsageError(
                returnunicode(
                    QCoreApplication.translate("PlotTemplates", '"%s" was not a file.')
                )
                % filename
            )
        try:
            with open(filename, encoding="utf-8") as f:
                lines = "".join([line for line in f if line])
        except Exception as e:
            message_utils.MessagebarAndLog.critical(
                bar_msg=returnunicode(
                    QCoreApplication.translate(
                        "PlotTemplates",
                        "Loading template %s failed, see log message panel",
                    )
                )
                % filename,
                log_msg=returnunicode(
                    QCoreApplication.translate(
                        "PlotTemplates", "Reading file failed, msg:\n%s"
                    )
                )
                % returnunicode(str(e)),
            )
            raise

        if lines:
            try:
                template = self.string_to_dict("".join(lines))
            except Exception as e:
                message_utils.MessagebarAndLog.critical(
                    bar_msg=returnunicode(
                        QCoreApplication.translate(
                            "PlotTemplates",
                            "Loading template %s failed, see log message panel",
                        )
                    )
                    % filename,
                    log_msg=returnunicode(
                        QCoreApplication.translate(
                            "PlotTemplates", "Parsing file rows failed, msg:\n%s"
                        )
                    )
                    % returnunicode(str(e)),
                )
                raise
            else:
                return {"filename": filename, "template": template, "name": name}
        else:
            return {}

    def update_settingsdict(self) -> None:
        self.ms.settingsdict[self.templates_settingskey] = ";".join(
            list(self.templates.keys())
        )
        self.ms.save_settings(self.templates_settingskey)

    def update_template_list(self) -> None:
        self.template_list.clear()
        for filename, template in sorted(
            iter(self.templates.items()), key=lambda x: os.path.basename(x[0])
        ):
            qlistwidgetitem = QtWidgets.QListWidgetItem()
            qlistwidgetitem.setText(template["name"])
            qlistwidgetitem.filename = template["filename"]
            self.template_list.addItem(qlistwidgetitem)

    def readable_output(self, a_dict: Optional[dict] = None) -> str:
        if a_dict is None:
            a_dict = self.loaded_template
        return anything_to_string_representation(
            a_dict,
            itemjoiner=",\n",
            pad="    ",
            dictformatter="{\n%s}",
            listformatter="[\n%s]",
            tupleformatter="(\n%s, )",
        )

    def string_to_dict(self, the_string: str):
        the_string = returnunicode(the_string)
        if not the_string:
            return ""
        try:
            try:
                as_dict = json.loads(the_string)
            except (json.JSONDecodeError, ValueError):
                as_dict = ast.literal_eval(the_string)
        except Exception as e:
            message_utils.MessagebarAndLog.warning(
                bar_msg=returnunicode(
                    QCoreApplication.translate(
                        "StoredSettings",
                        "Translating string to dict failed, see log message panel",
                    )
                ),
                log_msg=returnunicode(
                    QCoreApplication.translate(
                        "StoredSettings", "Error %s\nfor string\n%s"
                    )
                )
                % (str(e), the_string),
            )
        else:
            return as_dict


def _sanitize_mplstyle_content(content: str) -> tuple[str, list[str]]:
    """Return (cleaned_content, skipped_keys) after dropping keys unknown to this matplotlib."""
    lines = []
    skipped: list[str] = []
    for line in content.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            lines.append(line)
            continue
        if ":" not in stripped:
            lines.append(line)
            continue
        key, _, _ = stripped.partition(":")
        key = key.strip()
        if key in mpl.rcParams:
            lines.append(line)
        else:
            skipped.append(key)
    return "".join(lines), skipped


class _FixStylesDialog(QtWidgets.QDialog):
    """Dialog that lets the user inspect and fix .mplstyle files in the stylelib."""

    def __init__(
        self,
        style_folder: str,
        style_extension: str,
        parent: Optional[QtWidgets.QWidget] = None,
    ):
        super().__init__(parent)
        self.style_folder = style_folder
        self.style_extension = style_extension
        self.fixed_any = False
        self._setup_ui()
        self._scan()

    def _setup_ui(self) -> None:
        self.setWindowTitle(
            QCoreApplication.translate("_FixStylesDialog", "Fix style files")
        )
        layout = QtWidgets.QVBoxLayout(self)

        layout.addWidget(
            QtWidgets.QLabel(
                QCoreApplication.translate(
                    "_FixStylesDialog",
                    "Select style files to fix (unknown rcParams keys will be removed):",
                )
            )
        )

        self._list = QtWidgets.QListWidget()
        self._list.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._list)

        sel_row = QtWidgets.QHBoxLayout()
        btn_all = QtWidgets.QPushButton(
            QCoreApplication.translate("_FixStylesDialog", "Select all")
        )
        btn_none = QtWidgets.QPushButton(
            QCoreApplication.translate("_FixStylesDialog", "Deselect all")
        )
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_none.clicked.connect(lambda: self._set_all(False))
        sel_row.addWidget(btn_all)
        sel_row.addWidget(btn_none)
        sel_row.addStretch()
        layout.addLayout(sel_row)

        btn_row = QtWidgets.QHBoxLayout()
        self._fix_btn = QtWidgets.QPushButton(
            QCoreApplication.translate("_FixStylesDialog", "Fix selected")
        )
        close_btn = QtWidgets.QPushButton(
            QCoreApplication.translate("_FixStylesDialog", "Close")
        )
        self._fix_btn.clicked.connect(self._fix_selected)
        close_btn.clicked.connect(self.accept)
        btn_row.addStretch()
        btn_row.addWidget(self._fix_btn)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self.resize(520, 320)

    def _scan(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        self._info: dict = {}

        if os.path.isdir(self.style_folder):
            for fname in sorted(os.listdir(self.style_folder)):
                if not fname.endswith(self.style_extension):
                    continue
                fpath = os.path.join(self.style_folder, fname)
                try:
                    with open(fpath, encoding="utf-8") as f:
                        raw = f.read()
                    content, skipped = _sanitize_mplstyle_content(raw)
                except Exception:
                    content, skipped = "", []

                style_name = os.path.splitext(fname)[0]
                self._info[fname] = (fpath, content, skipped)

                item = QtWidgets.QListWidgetItem()
                if skipped:
                    label = QCoreApplication.translate(
                        "_FixStylesDialog", "%s  —  %d unknown key(s): %s"
                    ) % (style_name, len(skipped), ", ".join(skipped))
                    item.setCheckState(QtCore.Qt.Checked)
                else:
                    label = (
                        QCoreApplication.translate("_FixStylesDialog", "%s  —  OK")
                        % style_name
                    )
                    item.setCheckState(QtCore.Qt.Unchecked)
                item.setText(label)
                item.setData(QtCore.Qt.UserRole, fname)
                self._list.addItem(item)

        self._list.blockSignals(False)
        self._update_fix_btn()

    def _set_all(self, checked: bool) -> None:
        state = QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(state)
        self._list.blockSignals(False)
        self._update_fix_btn()

    def _on_item_changed(self, _item: QtWidgets.QListWidgetItem) -> None:
        self._update_fix_btn()

    def _update_fix_btn(self) -> None:
        any_checked = any(
            self._list.item(i).checkState() == QtCore.Qt.Checked
            for i in range(self._list.count())
        )
        self._fix_btn.setEnabled(any_checked)

    def _fix_selected(self) -> None:
        fixed: list[str] = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() != QtCore.Qt.Checked:
                continue
            fname = item.data(QtCore.Qt.UserRole)
            fpath, content, skipped = self._info.get(fname, (None, "", []))
            if not fpath or not skipped:
                continue
            try:
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(content)
                fixed.append(os.path.splitext(fname)[0])
                self.fixed_any = True
            except Exception as e:
                message_utils.MessagebarAndLog.warning(
                    bar_msg=QCoreApplication.translate(
                        "_FixStylesDialog", "Failed to fix style file '%s'."
                    )
                    % fname,
                    log_msg=str(e),
                )
        if fixed:
            message_utils.MessagebarAndLog.info(
                bar_msg=QCoreApplication.translate(
                    "_FixStylesDialog",
                    "Fixed %d style file(s): %s",
                )
                % (len(fixed), ", ".join(fixed))
            )
            self._scan()


class MatplotlibStyles:
    def __init__(
        self,
        plot_object,
        style_list,
        import_button,
        open_folder_button,
        available_settings_button,
        save_as_button,
        fix_styles_button,
        last_used_style_settingskey: str,
        defaultstyle_stylename: tuple[str, str],
        msettings: Optional["MidvSettings"] = None,
    ):

        # Gui objects
        self.style_list = style_list
        self.import_button = import_button
        self.open_folder_button = open_folder_button
        self.available_settings_button = available_settings_button
        self.save_as_button = save_as_button
        self.fix_styles_button = fix_styles_button

        self.style_extension = ".mplstyle"
        self.style_folder = os.path.join(mpl.get_configdir(), "stylelib")
        if os.path.isdir(mpl.get_configdir()):
            if os.path.exists(self.style_folder):
                if not os.path.isdir(self.style_folder):
                    message_utils.MessagebarAndLog.warning(
                        bar_msg=returnunicode(
                            QCoreApplication.translate(
                                "MatplotlibStyles",
                                """Matplotlib style folder %s was not a directory!""",
                            )
                        )
                        % self.style_folder
                    )
            else:
                try:
                    os.makedirs(self.style_folder)
                except Exception as e:
                    message_utils.MessagebarAndLog.warning(
                        bar_msg=returnunicode(
                            QCoreApplication.translate(
                                "MatplotlibStyles",
                                """Could not create style folder %s, see log message panel!""",
                            )
                        )
                        % self.style_folder,
                        log_msg=str(e),
                    )
                else:
                    message_utils.MessagebarAndLog.info(
                        bar_msg=returnunicode(
                            QCoreApplication.translate(
                                "MatplotlibStyles",
                                """Matplotlib style folder created %s.""",
                            )
                        )
                        % self.style_folder
                    )
        else:
            message_utils.MessagebarAndLog.warning(
                bar_msg=returnunicode(
                    QCoreApplication.translate(
                        "MatplotlibStyles",
                        """Matplotlib config directory not found. User styles not used.""",
                    )
                )
            )

        if not os.path.isdir(self.style_folder):
            os.mkdir(self.style_folder)

        self.ms = msettings

        self.defaultstyle_stylename = defaultstyle_stylename

        self.last_used_style_settingskey = last_used_style_settingskey

        # Always write the Midvatten default so the installed copy stays current.
        self.save_style_to_stylelib(self.defaultstyle_stylename)
        self.update_style_list()
        try:
            last_used_style = self.ms.settingsdict[self.last_used_style_settingskey]
        except Exception:
            message_utils.MessagebarAndLog.warning(
                bar_msg=returnunicode(
                    QCoreApplication.translate(
                        "MatplotlibStyles",
                        "Failed to load saved style, loading default style instead.",
                    )
                )
            )
        else:
            self.select_style_in_list(last_used_style)

        self.import_button.clicked.connect(lambda x: self.import_style())
        self.open_folder_button.clicked.connect(lambda x: self.open_folder())
        self.available_settings_button.clicked.connect(
            lambda x: self.available_settings_to_log()
        )
        self.save_as_button.clicked.connect(lambda x: self.save_as())
        self.fix_styles_button.clicked.connect(lambda x: self.fix_styles())

    @general_exception_handler
    def fix_styles(self) -> None:
        """Open a dialog where the user can select which style files to sanitize."""
        dialog = _FixStylesDialog(self.style_folder, self.style_extension)
        dialog.exec_()
        if dialog.fixed_any:
            self.update_style_list()

    def save_style_to_stylelib(self, stylestring_stylename: tuple[str, str]) -> None:
        filename = self.filename_from_style(stylestring_stylename[1])
        content, skipped = _sanitize_mplstyle_content(stylestring_stylename[0])
        if skipped:
            message_utils.MessagebarAndLog.warning(
                bar_msg=returnunicode(
                    QCoreApplication.translate(
                        "MatplotlibStyles",
                        "Style '%s': removed %d rcParams key(s) not supported by this matplotlib version (see log).",
                    )
                )
                % (stylestring_stylename[1], len(skipped)),
                log_msg=returnunicode(
                    QCoreApplication.translate(
                        "MatplotlibStyles",
                        "Style '%s': removed unsupported rcParams keys: %s",
                    )
                )
                % (stylestring_stylename[1], ", ".join(skipped)),
            )
        with open(filename, "w", encoding="utf-8") as of:
            of.write(content)
        mpl.style.reload_library()

    def get_selected_style(self) -> Optional[str]:
        selected = self.style_list.selectedItems()
        if selected:
            return selected[0].text()

    def filename_from_style(self, style: str) -> str:
        filename = os.path.join(self.style_folder, style + self.style_extension)
        return filename

    @general_exception_handler
    def load(
        self,
        drawfunc: Callable,
        plot_widget_navigationtoolbar_name: Optional[tuple] = None,
    ) -> None:
        # mpl.rcdefaults()
        fallback_style = "fallback_" + self.defaultstyle_stylename[1]
        self.save_style_to_stylelib([self.defaultstyle_stylename[0], fallback_style])
        styles = [
            self.get_selected_style(),
            self.defaultstyle_stylename[1],
            fallback_style,
            "default",
        ]

        use_style = None
        for _style in styles:
            if not _style:
                continue
            try:
                with plt.style.context(_style):
                    pass
            except Exception as e:
                # Before falling back, try to auto-fix the style file by removing unknown keys.
                style_file = self.filename_from_style(_style)
                if os.path.isfile(style_file):
                    try:
                        with open(style_file, encoding="utf-8") as rf:
                            raw = rf.read()
                        content, skipped = _sanitize_mplstyle_content(raw)
                        if skipped:
                            with open(style_file, "w", encoding="utf-8") as wf:
                                wf.write(content)
                            mpl.style.reload_library()
                            with plt.style.context(_style):
                                pass
                            message_utils.MessagebarAndLog.warning(
                                bar_msg=returnunicode(
                                    QCoreApplication.translate(
                                        "MatplotlibStyles",
                                        "Style '%s': auto-removed %d unsupported rcParams key(s) (see log).",
                                    )
                                )
                                % (_style, len(skipped)),
                                log_msg=returnunicode(
                                    QCoreApplication.translate(
                                        "MatplotlibStyles",
                                        "Style '%s': auto-removed unsupported rcParams keys: %s",
                                    )
                                )
                                % (_style, ", ".join(skipped)),
                            )
                            use_style = _style
                            break
                    except Exception:
                        pass
                message_utils.MessagebarAndLog.warning(
                    bar_msg=returnunicode(
                        QCoreApplication.translate(
                            "MatplotlibStyles",
                            "Failed to load style, check style settings in %s.",
                        )
                    )
                    % self.filename_from_style(_style),
                    log_msg=returnunicode(
                        QCoreApplication.translate("MatplotlibStyles", "Error msg %s")
                    )
                    % str(e),
                )
            else:
                use_style = _style
                break

        if use_style is not None:
            with mpl.style.context(use_style, after_reset=True):
                drawfunc()
            if plot_widget_navigationtoolbar_name is not None:
                navigationtoolbar = getattr(
                    plot_widget_navigationtoolbar_name[0],
                    plot_widget_navigationtoolbar_name[1],
                )
                navigationtoolbar.midv_use_style = use_style
        else:
            drawfunc()

    @general_exception_handler
    def import_style(self, filenames: Optional[list[str]] = None) -> None:
        if filenames is None:
            filenames = midvatten_utils.select_files(only_one_file=False, extension="")
        if filenames:
            for filename in filenames:
                if not filename:
                    continue

                folder, _filename = os.path.split(filename)
                basename, ext = os.path.splitext(_filename)
                newname = basename + self.style_extension
                new_fullname = os.path.join(self.style_folder, newname)
                if os.path.isfile(new_fullname):
                    answer = Askuser(
                        question="YesNo",
                        msg=returnunicode(
                            QCoreApplication.translate(
                                "MatplotlibStyles", "The style file existed. Overwrite?"
                            )
                        ),
                    )
                    if not answer:
                        return
                with open(filename, encoding="utf-8", errors="replace") as rf:
                    raw = rf.read()
                content, skipped = _sanitize_mplstyle_content(raw)
                with open(new_fullname, "w", encoding="utf-8") as wf:
                    wf.write(content)
                if skipped:
                    message_utils.MessagebarAndLog.warning(
                        bar_msg=returnunicode(
                            QCoreApplication.translate(
                                "MatplotlibStyles",
                                "Imported style '%s': removed %d rcParams key(s) not supported by this matplotlib version (see log).",
                            )
                        )
                        % (basename, len(skipped)),
                        log_msg=returnunicode(
                            QCoreApplication.translate(
                                "MatplotlibStyles",
                                "Imported style '%s': removed unsupported rcParams keys: %s",
                            )
                        )
                        % (basename, ", ".join(skipped)),
                    )
            self.update_style_list()

    @general_exception_handler
    def save_as(self) -> None:
        filename = get_save_file_name_no_extension(
            parent=None,
            caption=returnunicode(
                QCoreApplication.translate("MatplotlibStyles", "Choose a file name")
            ),
            directory=self.style_folder,
            filter="mplstyle (*.mplstyle)",
        )
        if not filename.endswith(".mplstyle"):
            basename, ext = os.path.splitext(filename)
            filename = basename + ".mplstyle"
        with plt.style.context(self.get_selected_style()):
            rcparams = self.rcparams()
        with open(filename, "w", encoding="utf8") as of:
            of.write(rcparams)
        self.update_style_list()

    @general_exception_handler
    def open_folder(self) -> None:
        url = QtCore.QUrl(self.style_folder, QtCore.QUrl.TolerantMode)
        QDesktopServices.openUrl(url)

    def update_settingsdict(self) -> None:
        self.ms.settingsdict[self.last_used_style_settingskey] = (
            self.get_selected_style()
        )
        self.ms.save_settings(self.last_used_style_settingskey)

    def update_style_list(self) -> None:
        mpl.style.reload_library()
        selected_style = self.get_selected_style()
        self.style_list.clear()
        for style in sorted(plt.style.available):
            qlistwidgetitem = QtWidgets.QListWidgetItem()
            qlistwidgetitem.setText(style)
            self.style_list.addItem(qlistwidgetitem)
            if style == selected_style:
                qlistwidgetitem.setSelected(True)

    def available_settings_to_log(self) -> None:
        rows = self.rcparams()
        message_utils.MessagebarAndLog.info(
            bar_msg=returnunicode(
                QCoreApplication.translate(
                    "MatplotlibStyles", "rcParams written to log, see log messages"
                )
            ),
            log_msg=rows,
        )

    def rcparams(self) -> str:
        def format_v(v) -> str:
            if isinstance(v, (list, tuple)):
                if v:
                    return ",".join([str(_v) for _v in v])
                else:
                    return ""
            else:
                return str(v)

        return "\n".join(
            [f"{str(k)}: {format_v(v)}" for k, v in sorted(mpl.rcParams.items())]
        )

    def select_style_in_list(self, style: str) -> None:
        for idx in range(self.style_list.count()):
            item = self.style_list.item(idx)
            if item.text() == style:
                item.setSelected(True)
            else:
                item.setSelected(False)
