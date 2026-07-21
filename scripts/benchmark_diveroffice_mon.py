"""Benchmark fixed-width DiverOffice MON parsing without database work."""

from __future__ import annotations

import argparse
import statistics
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

from midvatten.tools.import_logger import DiverOfficeBaroParser, DiverOfficeParser


def build_mon(row_count: int, baro: bool = False) -> str:
    channel_1 = "PRESSURE" if baro else "WATER HEAD (WC)"
    location = "benchmark_baro" if baro else "benchmark_head"
    start = datetime(2025, 1, 1)
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
        stamp = start + timedelta(minutes=index)
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
        DiverOfficeParser.parse(str(path), "utf-8", interactive=False)
        timings = []
        for _ in range(repeats):
            started = time.perf_counter()
            DiverOfficeParser.parse(str(path), "utf-8", interactive=False)
            timings.append(time.perf_counter() - started)
        return statistics.median(timings)
    finally:
        path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    median = median_runtime(args.rows, args.repeats)
    print(f"rows={args.rows} repeats={args.repeats} median_seconds={median:.6f}")


if __name__ == "__main__":
    main()
