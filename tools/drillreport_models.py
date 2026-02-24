"""
Dataclasses for drill report row structures.
Maps database row tuples to named attributes for clearer, safer access.
"""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ObsPointsRow:
    """Row from obs_points table. Fields match create_db.sql schema order."""

    obsid: str
    name: Optional[str]
    place: Optional[str]
    type: Optional[str]
    length: Optional[float]
    drillstop: Optional[str]
    diam: Optional[float]
    material: Optional[str]
    screen: Optional[str]
    capacity: Optional[str]
    drilldate: Optional[str]
    wmeas_yn: Optional[int]
    wlogg_yn: Optional[int]
    east: Optional[float]
    north: Optional[float]
    ne_accur: Optional[float]
    ne_source: Optional[str]
    h_toc: Optional[float]
    h_tocags: Optional[float]
    h_gs: Optional[float]
    h_accur: Optional[float]
    h_syst: Optional[str]
    h_source: Optional[str]
    source: Optional[str]
    com_onerow: Optional[str]
    com_html: Optional[str]
    geometry: Optional[Any] = None

    @classmethod
    def from_row(cls, row: tuple, columns: list[str]) -> "ObsPointsRow":
        """Build ObsPointsRow from a database row tuple and column names."""
        value_by_name = dict(zip(columns, row))
        return cls(
            obsid=value_by_name.get("obsid", ""),
            name=value_by_name.get("name"),
            place=value_by_name.get("place"),
            type=value_by_name.get("type"),
            length=value_by_name.get("length"),
            drillstop=value_by_name.get("drillstop"),
            diam=value_by_name.get("diam"),
            material=value_by_name.get("material"),
            screen=value_by_name.get("screen"),
            capacity=value_by_name.get("capacity"),
            drilldate=value_by_name.get("drilldate"),
            wmeas_yn=value_by_name.get("wmeas_yn"),
            wlogg_yn=value_by_name.get("wlogg_yn"),
            east=value_by_name.get("east"),
            north=value_by_name.get("north"),
            ne_accur=value_by_name.get("ne_accur"),
            ne_source=value_by_name.get("ne_source"),
            h_toc=value_by_name.get("h_toc"),
            h_tocags=value_by_name.get("h_tocags"),
            h_gs=value_by_name.get("h_gs"),
            h_accur=value_by_name.get("h_accur"),
            h_syst=value_by_name.get("h_syst"),
            h_source=value_by_name.get("h_source"),
            source=value_by_name.get("source"),
            com_onerow=value_by_name.get("com_onerow"),
            com_html=value_by_name.get("com_html"),
            geometry=value_by_name.get("geometry"),
        )


@dataclass
class StratigraphyRow:
    """Row from stratigraphy table."""

    obsid: str
    stratid: int
    depthtop: Optional[float]
    depthbot: Optional[float]
    geology: Optional[str]
    geoshort: Optional[str]
    capacity: Optional[str]
    development: Optional[str]
    comment: Optional[str]

    @classmethod
    def from_row(cls, row: tuple, columns: list[str]) -> "StratigraphyRow":
        """Build StratigraphyRow from a database row tuple and column names."""
        value_by_name = dict(zip(columns, row))
        return cls(
            obsid=value_by_name.get("obsid", ""),
            stratid=value_by_name.get("stratid", 0),
            depthtop=value_by_name.get("depthtop"),
            depthbot=value_by_name.get("depthbot"),
            geology=value_by_name.get("geology"),
            geoshort=value_by_name.get("geoshort"),
            capacity=value_by_name.get("capacity"),
            development=value_by_name.get("development"),
            comment=value_by_name.get("comment"),
        )
