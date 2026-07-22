"""Benchmark fixed-width DiverOffice MON parsing without database work."""

from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "_pkgroot"))

from midvatten.tools.import_logger import (  # noqa: E402
    DiverOfficeBaroParser,
    DiverOfficeParser,
)
from midvatten.tools.import_logger import parsers as logger_parsers  # noqa: E402


def build_mon(
    row_count: int,
    baro: bool = False,
    *,
    start: datetime | None = None,
    step: timedelta | None = None,
    location: str | None = None,
) -> str:
    channel_1 = "PRESSURE" if baro else "WATER HEAD (WC)"
    location = location or ("benchmark_baro" if baro else "benchmark_head")
    start = start or datetime(2025, 1, 1)
    step = step or timedelta(minutes=1)
    rows = [
        "[Logger settings]",
        f"  Location                ={location}",
        "  Number of channels      =2",
        "[Channel 1]",
        f"  Identification          ={channel_1}",
        "[Channel 2]",
        "  Identification          =TEMPERATURE",
        "[Data]",
        str(row_count),
    ]
    for index in range(row_count):
        stamp = start + step * index
        value = 100.308 if index == row_count - 1 else 99.900
        rows.append(f"{stamp:%Y/%m/%d %H:%M:%S}.0{value:13.3f}{5.0:12.3f}")
    rows.append("END OF DATA FILE OF DATALOGGER FOR WINDOWS")
    return "\n".join(rows) + "\n"


def median_runtime(row_count: int, repeats: int) -> float:
    content = build_mon(row_count)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".mon", delete=False
    ) as handle:
        handle.write(content)
        path = Path(handle.name)
    try:
        DiverOfficeParser.parse(str(path), "utf-8")
        timings = []
        for _ in range(repeats):
            started = time.perf_counter()
            DiverOfficeParser.parse(str(path), "utf-8")
            timings.append(time.perf_counter() - started)
        return statistics.median(timings)
    finally:
        path.unlink()


def median_transform_runtime(row_count: int, repeats: int) -> tuple[float, int]:
    """Benchmark the planned typed-frame operations without database I/O."""
    source = pd.DataFrame(
        {
            "date_time": pd.date_range("2025-01-01", periods=row_count, freq="min"),
            "head_cm": 99.9,
            "temp_degc": 5.0,
            "cond_mscm": float("nan"),
            "baro_cmh2o": float("nan"),
        }
    )
    memory_bytes = int(source.memory_usage(index=True, deep=True).sum())

    def transform() -> pd.DataFrame:
        result = source.copy()
        result["date_time"] = (
            result["date_time"]
            .dt.tz_localize("UTC", ambiguous="infer", nonexistent="shift_forward")
            .dt.tz_convert("Europe/Stockholm")
            .dt.tz_localize(None)
        )
        result = result.loc[
            result["date_time"].between(
                result["date_time"].iloc[0],
                result["date_time"].iloc[-1],
                inclusive="both",
            )
        ].reset_index(drop=True)
        result = result.loc[
            result["date_time"] > pd.Timestamp("2024-12-31")
        ].reset_index(drop=True)
        result = result.assign(obsid="benchmark")
        database_frame = result.copy()
        database_frame["date_time"] = database_frame["date_time"].dt.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        return database_frame.astype(object).where(database_frame.notna(), None)

    transform()
    timings = []
    for _ in range(repeats):
        started = time.perf_counter()
        transform()
        timings.append(time.perf_counter() - started)
    return statistics.median(timings), memory_bytes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--transform", action="store_true")
    args = parser.parse_args()
    median = median_runtime(args.rows, args.repeats)
    print(f"parser_module={logger_parsers.__file__}")
    print(f"rows={args.rows} repeats={args.repeats} median_seconds={median:.6f}")
    if args.transform:
        transform_median, frame_bytes = median_transform_runtime(
            args.rows, args.repeats
        )
        print(
            f"transform_median_seconds={transform_median:.6f} "
            f"canonical_frame_bytes={frame_bytes}"
        )


if __name__ == "__main__":
    main()
