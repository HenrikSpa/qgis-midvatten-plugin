"""Integration smoke tests for the bulk obsid editor wired into Interlab4Import.

Exercises the integration between start_import and ObsidAssignmentDialog using
a real SpatiaLite DB.  The dialog itself is replaced with a passthrough fake
that sets .outcome and leaves .editor_rows as populated by group_editor_rows so
fan_out_filled_rows can inspect them.
"""

from __future__ import annotations

import gc
from unittest import mock

import pytest

from midvatten.test import utils_for_tests
from midvatten.tools.obsid_assignment_dialog import DialogOutcome
from midvatten.tools.utils import common_utils, db_utils


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _dialog_that_applies_as_is(
    editor_rows, existing_obsids, reload_callback=None, parent=None
):
    """Fake dialog that returns APPLY without modifying rows."""
    fake = mock.MagicMock()
    fake.editor_rows = editor_rows
    fake.outcome = DialogOutcome.APPLY
    fake.exec_ = lambda: None
    return fake


def _dialog_that_cancels(
    editor_rows, existing_obsids, reload_callback=None, parent=None
):
    """Fake dialog that returns CANCEL."""
    fake = mock.MagicMock()
    fake.editor_rows = editor_rows
    fake.outcome = DialogOutcome.CANCEL
    fake.exec_ = lambda: None
    return fake


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.spatialite
class TestInterlab4BulkEditorIntegration(utils_for_tests.MidvattenTestSpatialiteDbSv):
    """Full-DB integration tests that verify the dialog/cache wiring."""

    def teardown_method(self):
        gc.collect()
        super().teardown_method()

    # -- common lab-file fixture -----------------------------------------

    _INTERLAB4_LINES_2ROWS = (
        "#Interlab",
        "#Version=4.0",
        "#Tecken=UTF-8",
        "#Textavgränsare=Nej",
        "#Decimaltecken=,",
        "#Provadm",
        "Lablittera;Namn;Adress;Postnr;Ort;Kommunkod;Projekt;Laboratorium;"
        "Provtyp;Provtagare;Registertyp;ProvplatsID;Provplatsnamn;"
        "Specifik provplats;Provtagningsorsak;Provtyp;Provtypspecifikation;"
        "Bedömning;Kemisk bedömning;Mikrobiologisk bedömning;Kommentar;År;"
        "Provtagningsdatum;Provtagningstid;Inlämningsdatum;Inlämningstid;",
        "DM-2773;MFR;;;;;;;NSG;DV;;;VattA;SpA;;Dricksvatten;"
        "Utgående;Nej;Tjänligt;;;2010;2010-09-07;10:15;2010-09-07;14:15;",
        "DM-2774;MFR;;;;;;;NSG;DV;;;VattB;SpB;;Dricksvatten;"
        "Utgående;Nej;Tjänligt;;;2010;2010-09-07;11:00;2010-09-07;14:15;",
        "#Provdat",
        "Lablittera;Metodbeteckning;Parameter;Mätvärdetext;Mätvärdetal;"
        "Mätvärdetalanm;Enhet;Rapporteringsgräns;Detektionsgräns;"
        "Mätosäkerhet;Mätvärdespår;Parameterbedömning;Kommentar;",
        "DM-2773;Metod-1;Kalium;;5;;mg/l;;;;;;;",
        "DM-2774;Metod-1;Kalium;;3;;mg/l;;;;;;;",
        "#Slut",
    )

    def _setup_obsids(self, *obsids):
        for obs in obsids:
            db_utils.sql_alter_db(f"INSERT INTO obs_points (obsid) VALUES ('{obs}')")

    def _setup_cache(self, spec, namn, obsid):
        db_utils.sql_alter_db(
            "INSERT INTO zz_interlab4_obsid_assignment "
            "(specifik_provplats, provplatsnamn, obsid) "
            f"VALUES ('{spec}', '{namn}', '{obsid}')"
        )

    # -- tests ----------------------------------------------------------

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_cached_rows_imported_directly_without_notfoundquestion(
        self, mock_messagebar
    ):
        """When the dialog returns APPLY with both rows pre-filled from cache,
        the import runs and NotFoundQuestion is never called."""
        from midvatten.tools.import_interlab4 import Interlab4Import
        from midvatten.test import mocks_for_tests

        self._setup_obsids("obsid1", "obsid2")
        self._setup_cache("SpA", "VattA", "obsid1")
        self._setup_cache("SpB", "VattB", "obsid2")

        importer = Interlab4Import(self.iface, self.midvatten.ms)

        with (
            common_utils.tempinput(
                "\n".join(self._INTERLAB4_LINES_2ROWS), "utf-8"
            ) as filename,
            mock.patch(
                "midvatten.tools.import_interlab4.ObsidAssignmentDialog",
                side_effect=_dialog_that_applies_as_is,
            ),
            mock.patch(
                "midvatten.tools.utils.midvatten_utils.QtWidgets.QFileDialog.getOpenFileNames",
                return_value=[[filename]],
            ),
            mock.patch(
                "midvatten.tools.import_data_to_db.common_utils.Askuser",
                mocks_for_tests.mock_askuser.get_v,
            ),
            mock.patch(
                "midvatten.tools.utils.common_utils.NotFoundQuestion"
            ) as mock_nfq,
            mock.patch(
                "midvatten.tools.import_data_to_db.common_utils.pop_up_info",
                autospec=True,
            ),
        ):
            importer.init_gui()
            importer.select_files_button.click()
            importer.use_obsid_assignment_table.setChecked(True)
            importer.start_import_button.click()

        print(mock_messagebar.mock_calls)

        # Both lablitteras were assigned by cache; NotFoundQuestion should NOT fire.
        assert not mock_nfq.called, (
            "NotFoundQuestion should not be called when all rows are cached"
        )

        result = db_utils.sql_load_fr_db(
            "SELECT obsid, report FROM w_qual_lab ORDER BY report"
        )
        assert result[0] is True
        rows = result[1]
        assert len(rows) == 2
        reports = {r[1]: r[0] for r in rows}
        assert reports.get("DM-2773") == "obsid1"
        assert reports.get("DM-2774") == "obsid2"

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_uncached_rows_fall_through_to_notfoundquestion(self, mock_messagebar):
        """When the dialog returns APPLY with no obsids set (no cache), unfilled
        rows fall through to the NotFoundQuestion fallback and are imported."""
        from midvatten.tools.import_interlab4 import Interlab4Import
        from midvatten.test import mocks_for_tests

        self._setup_obsids("anobsid")

        importer = Interlab4Import(self.iface, self.midvatten.ms)

        with (
            common_utils.tempinput(
                "\n".join(self._INTERLAB4_LINES_2ROWS), "utf-8"
            ) as filename,
            mock.patch(
                "midvatten.tools.import_interlab4.ObsidAssignmentDialog",
                side_effect=_dialog_that_applies_as_is,
            ),
            mock.patch(
                "midvatten.tools.utils.midvatten_utils.QtWidgets.QFileDialog.getOpenFileNames",
                return_value=[[filename]],
            ),
            mock.patch(
                "midvatten.tools.import_data_to_db.common_utils.Askuser",
                mocks_for_tests.mock_askuser.get_v,
            ),
            mock.patch(
                "midvatten.tools.utils.common_utils.NotFoundQuestion"
            ) as mock_nfq,
            mock.patch(
                "midvatten.tools.import_data_to_db.common_utils.pop_up_info",
                autospec=True,
            ),
        ):
            mock_nfq.return_value.answer = "ok"
            mock_nfq.return_value.value = "anobsid"
            mock_nfq.return_value.reuse_column = "obsid"

            importer.init_gui()
            importer.select_files_button.click()
            # use_obsid_assignment_table is not checked → no cache
            importer.use_obsid_assignment_table.setChecked(False)
            importer.start_import_button.click()

        print(mock_messagebar.mock_calls)

        # NotFoundQuestion should have been called (rows were not cache-filled).
        assert mock_nfq.called, (
            "NotFoundQuestion should be called when rows are not in cache"
        )

        result = db_utils.sql_load_fr_db(
            "SELECT obsid, report FROM w_qual_lab ORDER BY report"
        )
        assert result[0] is True
        rows = result[1]
        assert len(rows) == 2
        for obsid, _ in rows:
            assert obsid == "anobsid"

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_cancel_dialog_aborts_import(self, mock_messagebar):
        """When the dialog returns CANCEL, start_import bails out and nothing
        is written to w_qual_lab."""
        from midvatten.tools.import_interlab4 import Interlab4Import

        self._setup_obsids("obsid1")
        self._setup_cache("SpA", "VattA", "obsid1")

        importer = Interlab4Import(self.iface, self.midvatten.ms)

        with (
            common_utils.tempinput(
                "\n".join(self._INTERLAB4_LINES_2ROWS), "utf-8"
            ) as filename,
            mock.patch(
                "midvatten.tools.import_interlab4.ObsidAssignmentDialog",
                side_effect=_dialog_that_cancels,
            ),
            mock.patch(
                "midvatten.tools.utils.midvatten_utils.QtWidgets.QFileDialog.getOpenFileNames",
                return_value=[[filename]],
            ),
            mock.patch(
                "midvatten.tools.import_data_to_db.common_utils.pop_up_info",
                autospec=True,
            ),
        ):
            importer.init_gui()
            importer.select_files_button.click()
            importer.use_obsid_assignment_table.setChecked(True)
            importer.start_import_button.click()

        print(mock_messagebar.mock_calls)

        result = db_utils.sql_load_fr_db("SELECT COUNT(*) FROM w_qual_lab")
        assert result[1][0][0] == 0, "No rows should be imported after CANCEL"

    @mock.patch("midvatten.tools.utils.common_utils.MessagebarAndLog")
    def test_new_cache_rows_written_after_apply(self, mock_messagebar):
        """fan_out_filled_rows new (non-cached) rows written by the dialog are
        stored in zz_interlab4_obsid_assignment after APPLY."""
        from midvatten.tools.import_interlab4 import Interlab4Import
        from midvatten.test import mocks_for_tests

        self._setup_obsids("obsid1", "obsid2")

        def _dialog_fills_rows(
            editor_rows, existing_obsids, reload_callback=None, parent=None
        ):
            """Fake dialog that fills all clean rows with obsid1/obsid2."""
            obsids = iter(["obsid1", "obsid2"])
            for row in editor_rows:
                if not row.is_override:
                    row.obsid = next(obsids, "obsid1")
            fake = mock.MagicMock()
            fake.editor_rows = editor_rows
            fake.outcome = DialogOutcome.APPLY
            fake.exec_ = lambda: None
            return fake

        importer = Interlab4Import(self.iface, self.midvatten.ms)

        with (
            common_utils.tempinput(
                "\n".join(self._INTERLAB4_LINES_2ROWS), "utf-8"
            ) as filename,
            mock.patch(
                "midvatten.tools.import_interlab4.ObsidAssignmentDialog",
                side_effect=_dialog_fills_rows,
            ),
            mock.patch(
                "midvatten.tools.utils.midvatten_utils.QtWidgets.QFileDialog.getOpenFileNames",
                return_value=[[filename]],
            ),
            mock.patch(
                "midvatten.tools.import_data_to_db.common_utils.Askuser",
                mocks_for_tests.mock_askuser.get_v,
            ),
            mock.patch(
                "midvatten.tools.import_data_to_db.common_utils.pop_up_info",
                autospec=True,
            ),
        ):
            importer.init_gui()
            importer.select_files_button.click()
            importer.use_obsid_assignment_table.setChecked(True)
            importer.start_import_button.click()

        print(mock_messagebar.mock_calls)

        # Data imported correctly.
        result = db_utils.sql_load_fr_db(
            "SELECT obsid, report FROM w_qual_lab ORDER BY report"
        )
        assert result[0] is True
        rows = result[1]
        assert len(rows) == 2

        # New assignments written to cache.
        cache = db_utils.sql_load_fr_db(
            "SELECT specifik_provplats, provplatsnamn, obsid "
            "FROM zz_interlab4_obsid_assignment ORDER BY obsid"
        )
        assert cache[0] is True
        cache_rows = cache[1]
        assert len(cache_rows) == 2
        cache_map = {(r[0], r[1]): r[2] for r in cache_rows}
        assert cache_map.get(("SpA", "VattA")) == "obsid1"
        assert cache_map.get(("SpB", "VattB")) == "obsid2"
