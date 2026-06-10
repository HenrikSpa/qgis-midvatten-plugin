"""Synthetic TEM (transient electromagnetic) inversion data for tests/demos.

Generates geologically-plausible layered resistivity soundings along a
section line, serialised exactly as the ``tem_data`` schema documents:
``thickness`` and ``resistivity`` are TEXT columns holding a list literal,
e.g. ``"[1.0, 4.0, 5.0]"`` (see definitions/create_db.sql).

The ``fmt`` argument lets callers emit the same numbers in the alternative
string forms an external numpy-based exporter might produce, so the parser
in painters.parse_tem_number_list can be exercised end-to-end:

  - ``"plain"``      -> ``[1.0, 4.0, 5.0]``            (the documented format)
  - ``"numpy_repr"`` -> ``[np.float64(1.0), ...]``     (numpy 2.x scalar repr)
  - ``"nan_inf"``    -> ``[1.0, nan, inf]``             (missing/clipped layers)
"""

# A plausible four-layer glacial/sedimentary column (southern Sweden style):
# (material, base_thickness_m, base_resistivity_ohm_m)
LAYER_PROFILE: list[tuple[str, float, float]] = [
    ("clay", 3.0, 18.0),
    ("sand", 6.0, 220.0),
    ("till", 8.0, 650.0),
    ("bedrock", 12.0, 2600.0),
]


def _fmt_values(values: list[float], fmt: str) -> str:
    if fmt == "numpy_repr":
        return "[" + ", ".join(f"np.float64({float(v)})" for v in values) + "]"
    if fmt == "nan_inf":
        # Emit nan/inf tokens verbatim (what str(list-with-nan) produces).
        toks = []
        for v in values:
            if v is None:
                toks.append("nan")
            elif v == float("inf"):
                toks.append("inf")
            else:
                toks.append(str(float(v)))
        return "[" + ", ".join(toks) + "]"
    # plain: the documented "[1.0, 4.0, 5.0]" format
    return "[" + ", ".join(str(float(v)) for v in values) + "]"


def synthetic_soundings(
    obsid: str,
    inversion_name: str,
    n_positions: int = 5,
    spacing_m: float = 25.0,
    surface_masl: float = 50.0,
    fmt: str = "plain",
) -> list[dict]:
    """Return tem_data rows for one inversion model along a line.

    Each sounding sits at an increasing ``length`` along the line, with a
    gently dipping surface, a 4-layer model whose thicknesses/resistivities
    drift slightly per position, and a depth-of-investigation that deepens
    along the line. Deterministic (no randomness) so tests are stable.
    """
    rows = []
    for i in range(n_positions):
        length = i * spacing_m
        # Gentle, deterministic variation per position.
        drift = 1.0 + 0.05 * i
        thickness = [round(t * drift, 2) for _m, t, _r in LAYER_PROFILE]
        resistivity = [round(r * drift, 1) for _m, _t, r in LAYER_PROFILE]
        elevation = round(surface_masl - 0.4 * i, 2)  # surface dips along line
        doi = round(20.0 + 1.5 * i, 2)  # depth of investigation deepens
        data_fit = round(1.0 + 0.3 * i, 2)  # RMS misfit %, grows slightly

        if fmt == "nan_inf" and i == n_positions - 1:
            # Last sounding: a missing top layer (nan) and a clipped
            # bedrock resistivity (inf) — the kind of thing a real
            # exporter writes for undefined/over-range cells.
            resistivity = [
                float("inf") if j == len(resistivity) - 1 else r
                for j, r in enumerate(resistivity)
            ]
            thickness_vals = [None if j == 0 else t for j, t in enumerate(thickness)]
        else:
            thickness_vals = thickness

        rows.append(
            {
                "obsid": obsid,
                "inversion_name": inversion_name,
                "length": float(length),
                "elevation": elevation,
                "data_fit": data_fit,
                "doi": doi,
                "thickness": _fmt_values(thickness_vals, fmt),
                "resistivity": _fmt_values(resistivity, fmt),
                "comment": f"synthetic {fmt} sounding {i} of {inversion_name}",
            }
        )
    return rows
