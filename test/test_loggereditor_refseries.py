"""Tests for the logger editor reference subplot feature."""

import json

import pandas as pd
import pytest

from midvatten.tools.loggereditor_refseries import RefSeriesDialog, _NORM_MODES, _STYLES
from midvatten.tools.utils.db_utils.dialect import ident


# ---------------------------------------------------------------------------
# Standalone mirror of LoggerEditor._build_ref_query (tested in isolation)
# ---------------------------------------------------------------------------


def _build_ref_query(conn, s: dict) -> tuple:
    ph = conn.placeholder()
    sql = f"SELECT {ident(s['x_col'])}, {ident(s['y_col'])} FROM {ident(s['table'])}"
    where_parts: list = []
    params: list = []
    for f in s.get("filters", []):
        if not f.get("values"):
            continue
        placeholders = ", ".join([ph] * len(f["values"]))
        where_parts.append(f"{ident(f['col'])} IN ({placeholders})")
        params.extend(f["values"])
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    sql += f" ORDER BY {ident(s['x_col'])}"
    return sql, params


class _StubConn:
    def __init__(self, ph="?"):
        self._ph = ph

    def placeholder(self):
        return self._ph


_BASE = {
    "table": "meteo",
    "x_col": "date_time",
    "y_col": "rdep",
    "filters": [],
    "resample": "",
    "resample_agg": "sum",
    "interpolate": False,
    "normalize": "",
    "normalize_date": "",
    "scale": 1.0,
    "style": "step-pre",
    "label": "",
}


# ---------------------------------------------------------------------------
# SQL building
# ---------------------------------------------------------------------------


def test_build_ref_query_no_filters():
    sql, params = _build_ref_query(_StubConn(), _BASE)
    assert '"date_time"' in sql
    assert '"rdep"' in sql
    assert '"meteo"' in sql
    assert "WHERE" not in sql
    assert params == []
    assert sql.endswith('ORDER BY "date_time"')


def test_build_ref_query_single_filter():
    s = {**_BASE, "filters": [{"col": "obsid", "values": ["A01", "A02"]}]}
    sql, params = _build_ref_query(_StubConn(), s)
    assert '"obsid" IN (?, ?)' in sql
    assert params == ["A01", "A02"]


def test_build_ref_query_multi_filter():
    s = {
        **_BASE,
        "filters": [
            {"col": "obsid", "values": ["A01"]},
            {"col": "parameter", "values": ["rain", "snow"]},
        ],
    }
    sql, params = _build_ref_query(_StubConn(), s)
    assert '"obsid" IN (?)' in sql
    assert '"parameter" IN (?, ?)' in sql
    assert " AND " in sql
    assert params == ["A01", "rain", "snow"]


def test_build_ref_query_postgres_placeholder():
    s = {**_BASE, "filters": [{"col": "obsid", "values": ["X"]}]}
    sql, params = _build_ref_query(_StubConn("%s"), s)
    assert '"obsid" IN (%s)' in sql
    assert params == ["X"]


def test_build_ref_query_empty_filter_values_skipped():
    s = {**_BASE, "filters": [{"col": "obsid", "values": []}]}
    sql, params = _build_ref_query(_StubConn(), s)
    assert "WHERE" not in sql
    assert params == []


# ---------------------------------------------------------------------------
# Normalisation + pipeline (pure pandas)
# ---------------------------------------------------------------------------


def _apply_pipeline(ts: pd.Series, s: dict) -> pd.Series:
    if s.get("resample"):
        ts = getattr(ts.resample(s["resample"]), s.get("resample_agg", "mean"))()
    if s.get("interpolate"):
        ts = ts.interpolate(method="time")
    norm = s.get("normalize", "")
    if norm == "date" and s.get("normalize_date"):
        ref_val = ts.asof(pd.Timestamp(s["normalize_date"]))
        if pd.notna(ref_val):
            ts = ts - ref_val
    elif norm == "mean":
        ts = ts - ts.mean()
    elif norm == "zscore":
        std = ts.std()
        if std > 0:
            ts = (ts - ts.mean()) / std
    return ts * s.get("scale", 1.0)


def _ts(values, freq="D"):
    idx = pd.date_range("2024-01-01", periods=len(values), freq=freq)
    return pd.Series(values, index=idx, dtype=float)


def test_normalize_date():
    result = _apply_pipeline(
        _ts([10.0, 20.0, 30.0]),
        {**_BASE, "normalize": "date", "normalize_date": "2024-01-01"},
    )
    assert result.iloc[0] == pytest.approx(0.0)
    assert result.iloc[1] == pytest.approx(10.0)


def test_normalize_mean():
    result = _apply_pipeline(_ts([1.0, 3.0, 5.0]), {**_BASE, "normalize": "mean"})
    assert result.mean() == pytest.approx(0.0)
    assert result.iloc[0] == pytest.approx(-2.0)


def test_normalize_zscore():
    result = _apply_pipeline(
        _ts([1.0, 2.0, 3.0, 4.0, 5.0]), {**_BASE, "normalize": "zscore"}
    )
    assert result.mean() == pytest.approx(0.0, abs=1e-10)
    assert result.std() == pytest.approx(1.0, rel=1e-6)


def test_scale_applied_after_normalize():
    result = _apply_pipeline(
        _ts([0.0, 10.0]),
        {**_BASE, "normalize": "date", "normalize_date": "2024-01-01", "scale": 0.1},
    )
    assert result.iloc[1] == pytest.approx(1.0)


def test_resample_sum():
    ts = pd.Series(
        [1.0] * 10,
        index=pd.date_range("2024-01-01", periods=10, freq="6h"),
        dtype=float,
    )
    result = _apply_pipeline(ts, {**_BASE, "resample": "1D", "resample_agg": "sum"})
    assert result.iloc[0] == pytest.approx(4.0)


def test_interpolate_fills_nans_after_resample():
    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    ts = pd.Series([0.0, float("nan"), float("nan"), float("nan"), 4.0], index=dates)
    result = _apply_pipeline(ts, {**_BASE, "interpolate": True})
    assert result.isna().sum() == 0
    assert result.iloc[2] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Settings serialisation roundtrip
# ---------------------------------------------------------------------------


def test_settings_roundtrip():
    series = [
        {**_BASE, "label": "Precip"},
        {**_BASE, "y_col": "head_cm", "normalize": "zscore"},
    ]
    assert json.loads(json.dumps(series)) == series


def test_settings_roundtrip_empty():
    assert json.loads(json.dumps([])) == []


def test_settings_invalid_json_raises():
    with pytest.raises(json.JSONDecodeError):
        json.loads("not valid json")


# ---------------------------------------------------------------------------
# RefSeriesDialog.to_dict / from_dict  (no DB required — combos may be empty)
# ---------------------------------------------------------------------------


def test_to_dict_structure():
    dlg = RefSeriesDialog()
    d = dlg.to_dict()
    assert d["x_col"] == "date_time"
    assert d["style"] in _STYLES
    assert d["normalize"] in _NORM_MODES
    assert isinstance(d["scale"], float)
    assert isinstance(d["filters"], list)
    assert isinstance(d["interpolate"], bool)
    assert "table" in d
    assert "y_col" in d


def test_from_dict_roundtrip_no_filters():
    """from_dict with no filters → to_dict preserves all scalar fields."""
    original = {
        **_BASE,
        "resample": "1D",
        "resample_agg": "sum",
        "interpolate": True,
        "normalize": "mean",
        "normalize_date": "2024-06-15",
        "scale": 2.5,
        "style": "step-pre",
        "label": "My label",
    }
    dlg = RefSeriesDialog.from_dict(original)
    result = dlg.to_dict()
    assert result["resample"] == "1D"
    assert result["resample_agg"] == "sum"
    assert result["interpolate"] is True
    assert result["normalize"] == "mean"
    assert result["scale"] == pytest.approx(2.5)
    assert result["style"] == "step-pre"
    assert result["label"] == "My label"
