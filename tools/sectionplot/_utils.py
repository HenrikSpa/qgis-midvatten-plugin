#! /usr/bin/env python
"""
_utils.py — shared helpers for the sectionplot package.

These functions are used by both _sectionplot.py and the sub-modules
(painters.py, legend.py) without creating circular imports.
"""


def get_plot_label_name(label: str, labels: list) -> str:
    """Return *label*, appending a numeric suffix if already present in *labels*."""
    label_occurence = labels.count(label)
    if not label_occurence:
        return label
    else:
        return label + "_" + str(label_occurence + 1)


def get_legend_items_labels(plot_items: list) -> tuple:
    """Return (items, labels) from *plot_items*, skipping items with skip_legend=True."""
    legend_items = [p for p in plot_items if not getattr(p, "skip_legend", False)]
    labels = [p.get_label() for p in legend_items]
    return legend_items, labels
