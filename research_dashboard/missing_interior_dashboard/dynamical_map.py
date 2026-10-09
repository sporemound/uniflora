from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from typing import Any

import colorcet as cc
import holoviews as hv
import matplotlib
import numpy as np
import pandas as pd
import xarray as xr

# Dynamical map export is always a headless producer operation.  Select the
# non-interactive backend before pyplot is imported by HoloViews' renderer.
matplotlib.use("Agg", force=True)
plt = import_module("matplotlib.pyplot")

MAP_SCHEMA_VERSION = 1
MAP_IMAGE_FILENAME = "dynamical-overlay.png"
MAP_MANIFEST_FILENAME = "dynamical-overlay.json"
MAX_MERCATOR_LATITUDE = 85.051129
ASOS_BASE_URL = "https://data.source.coop/dynamical/asos-parquet"


class DynamicalMapError(ValueError):
    """Raised when a request cannot produce a bounded, georeferenced overlay."""


@dataclass(frozen=True, slots=True)
class DynamicalLayerDefinition:
    layer_id: str
    catalog_id: str
    catalog_url: str
    default_variable: str
    time_tolerance: timedelta


DYNAMICAL_LAYERS: Mapping[str, DynamicalLayerDefinition] = {
    "dynamical-asos": DynamicalLayerDefinition(
        layer_id="dynamical-asos",
        catalog_id="asos-parquet",
        catalog_url="https://dynamical.org/catalog/asos-parquet/",
        default_variable="tmpc",
        time_tolerance=timedelta(minutes=90),
    ),
    "dynamical-gfs-analysis": DynamicalLayerDefinition(
        layer_id="dynamical-gfs-analysis",
        catalog_id="noaa-gfs-analysis",
        catalog_url="https://dynamical.org/catalog/noaa-gfs-analysis/",
        default_variable="temperature_2m",
        time_tolerance=timedelta(minutes=90),
    ),
    "dynamical-hrrr-analysis": DynamicalLayerDefinition(
        layer_id="dynamical-hrrr-analysis",
        catalog_id="noaa-hrrr-analysis",
        catalog_url="https://dynamical.org/catalog/noaa-hrrr-analysis/",
        default_variable="composite_reflectivity",
        time_tolerance=timedelta(minutes=90),
    ),
    "dynamical-mrms-analysis": DynamicalLayerDefinition(
        layer_id="dynamical-mrms-analysis",
        catalog_id="noaa-mrms-conus-analysis-hourly",
        catalog_url="https://dynamical.org/catalog/noaa-mrms-conus-analysis-hourly/",
        default_variable="precipitation_surface",
        time_tolerance=timedelta(minutes=90),
    ),
    "dynamical-imerg-late": DynamicalLayerDefinition(
        layer_id="dynamical-imerg-late",
        catalog_id="nasa-imerg-analysis-late",
        catalog_url="https://dynamical.org/catalog/nasa-imerg-analysis-late/",
        default_variable="precipitation_surface",
        time_tolerance=timedelta(minutes=45),
    ),
}

ASOS_VARIABLE_UNITS: Mapping[str, str] = {
    "tmpf": "degree_Fahrenheit",
    "tmpc": "degree_Celsius",
    "dwpf": "degree_Fahrenheit",
    "dwpc": "degree_Celsius",
    "relh": "percent",
    "drct": "degree",
    "sknt": "knot",
    "gust": "knot",
    "alti": "inch_Hg",
    "mslp": "hPa",
    "vsby": "mile",
    "p01i": "inch",
    "p01m": "mm",
}

FIXED_VALUE_RANGES: Mapping[tuple[str, str], tuple[float, float]] = {
    ("temperature_2m", "degree_Celsius"): (-40.0, 45.0),
    ("temperature_2m", "K"): (233.15, 318.15),
    ("composite_reflectivity", "dBZ"): (-10.0, 75.0),
    ("relative_humidity_2m", "percent"): (0.0, 100.0),
    ("total_cloud_cover_atmosphere", "percent"): (0.0, 100.0),
    ("precipitation_surface", "kg m-2 s-1"): (0.0, 0.02),
    ("precipitation_surface", "mm hr-1"): (0.0, 50.0),
    ("tmpc", "degree_Celsius"): (-40.0, 50.0),
    ("tmpf", "degree_Fahrenheit"): (-40.0, 122.0),
    ("relh", "percent"): (0.0, 100.0),
}


@dataclass(frozen=True, slots=True)
class MapBounds:
    west: float
    south: float
    east: float
    north: float

    def __post_init__(self) -> None:
        values = (self.west, self.south, self.east, self.north)
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
            raise DynamicalMapError("map bounds must contain finite numbers")
        if not -180 <= self.west < self.east <= 180:
            raise DynamicalMapError(
                "map bounds must be a non-wrapping longitude interval within -180..180"
            )
        if not -MAX_MERCATOR_LATITUDE <= self.south < self.north <= MAX_MERCATOR_LATITUDE:
            raise DynamicalMapError(
                "map latitude bounds must fit the Web Mercator display domain"
            )

    @property
    def maplibre_coordinates(self) -> list[list[float]]:
        """Return MapLibre image-source corners: NW, NE, SE, SW."""

        return [
            [float(self.west), float(self.north)],
            [float(self.east), float(self.north)],
            [float(self.east), float(self.south)],
            [float(self.west), float(self.south)],
        ]


@dataclass(frozen=True, slots=True)
class DynamicalGridSlice:
    layer_id: str
    catalog_id: str
    variable: str
    units: str
    attribution: str
    catalog_url: str
    valid_time: datetime
    data: xr.DataArray
    bounds: MapBounds


@dataclass(frozen=True, slots=True)
class DynamicalPointSlice:
    layer_id: str
    catalog_id: str
    variable: str
    units: str
    attribution: str
    catalog_url: str
    valid_time: datetime
    points: pd.DataFrame
    bounds: MapBounds


@dataclass(frozen=True, slots=True)
class DynamicalOverlayBundle:
    directory: Path
    image_path: Path
    manifest_path: Path
    manifest: dict[str, Any]


def _utc(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DynamicalMapError(f"{label} must include a timezone")
    return value.astimezone(UTC)


def _iso_utc(value: datetime) -> str:
    return _utc(value, label="timestamp").isoformat(timespec="seconds").replace("+00:00", "Z")


def _layer(layer_id: str) -> DynamicalLayerDefinition:
    try:
        return DYNAMICAL_LAYERS[layer_id]
    except KeyError as exc:
        supported = ", ".join(sorted(DYNAMICAL_LAYERS))
        raise DynamicalMapError(
            f"unsupported Dynamical layer {layer_id!r}; choose one of: {supported}"
        ) from exc


def _coordinate_indices(values: np.ndarray, low: float, high: float) -> slice:
    if values.ndim != 1 or values.size < 2:
        raise DynamicalMapError("spatial coordinates must be one-dimensional with two points")
    numeric = np.asarray(values, dtype=float)
    if not np.isfinite(numeric).all():
        raise DynamicalMapError("spatial coordinates contain non-finite values")
    matching = np.flatnonzero((numeric >= low) & (numeric <= high))
    if matching.size:
        first = int(matching.min())
        last = int(matching.max())
    else:
        nearest = int(np.nanargmin(np.abs(numeric - ((low + high) / 2))))
        first = last = nearest
    # A rendered raster needs at least two cell centers. Include one cell of
    # context where possible, which also prevents tiny report envelopes from
    # disappearing on coarser GFS grids.
    first = max(0, first - 1)
    last = min(numeric.size - 1, last + 1)
    if first == last:
        if last < numeric.size - 1:
            last += 1
        elif first > 0:
            first -= 1
    return slice(first, last + 1)


def _thin_spatial(
    data: xr.DataArray,
    *,
    x_dimension: str,
    y_dimension: str,
    maximum_width: int,
    maximum_height: int,
) -> xr.DataArray:
    if maximum_width < 2 or maximum_height < 2:
        raise DynamicalMapError("maximum raster dimensions must each be at least two")
    x_stride = max(1, math.ceil(data.sizes[x_dimension] / maximum_width))
    y_stride = max(1, math.ceil(data.sizes[y_dimension] / maximum_height))
    return data.isel(
        {
            x_dimension: slice(None, None, x_stride),
            y_dimension: slice(None, None, y_stride),
        }
    )


def _coordinate_edges(values: np.ndarray, *, minimum: float, maximum: float) -> tuple[float, float]:
    numeric = np.asarray(values, dtype=float)
    if numeric.ndim != 1 or numeric.size < 2:
        raise DynamicalMapError("an overlay axis requires at least two coordinate centers")
    ordered = np.sort(numeric)
    lower = ordered[0] - ((ordered[1] - ordered[0]) / 2)
    upper = ordered[-1] + ((ordered[-1] - ordered[-2]) / 2)
    return max(minimum, float(lower)), min(maximum, float(upper))


def mercator_y(latitude: float | np.ndarray) -> float | np.ndarray:
    """Project latitude to the dimensionless Web Mercator Y coordinate."""

    numeric = np.asarray(latitude, dtype=float)
    clipped = np.clip(numeric, -MAX_MERCATOR_LATITUDE, MAX_MERCATOR_LATITUDE)
    projected = np.log(np.tan((np.pi / 4) + (np.deg2rad(clipped) / 2)))
    return float(projected) if projected.ndim == 0 else projected


def inverse_mercator_y(value: float | np.ndarray) -> float | np.ndarray:
    """Return latitude for a dimensionless Web Mercator Y coordinate."""

    numeric = np.asarray(value, dtype=float)
    latitude = np.rad2deg((2 * np.arctan(np.exp(numeric))) - (np.pi / 2))
    return float(latitude) if latitude.ndim == 0 else latitude


def mercator_resample_grid(data: xr.DataArray, bounds: MapBounds, *, rows: int) -> xr.DataArray:
    """Resample latitude rows onto the uniform Mercator grid used by MapLibre."""

    if rows < 2:
        raise DynamicalMapError("Mercator raster requires at least two rows")
    if set(data.dims) != {"latitude", "longitude"}:
        raise DynamicalMapError("Mercator raster input must use latitude and longitude")
    south_y = float(mercator_y(bounds.south))
    north_y = float(mercator_y(bounds.north))
    step = (north_y - south_y) / rows
    target_y = south_y + ((np.arange(rows, dtype=float) + 0.5) * step)
    target_latitude = inverse_mercator_y(target_y)
    interpolated = data.interp(
        latitude=xr.DataArray(target_latitude, dims=("mercator_y",)),
        method="linear",
    )
    interpolated = interpolated.assign_coords(mercator_y=("mercator_y", target_y))
    return interpolated.transpose("mercator_y", "longitude")


def _regular_lonlat_slice(
    selected: xr.DataArray,
    *,
    bounds: MapBounds,
    maximum_width: int,
    maximum_height: int,
) -> tuple[xr.DataArray, MapBounds]:
    longitude_window = _coordinate_indices(
        np.asarray(selected.coords["longitude"].values), bounds.west, bounds.east
    )
    latitude_window = _coordinate_indices(
        np.asarray(selected.coords["latitude"].values), bounds.south, bounds.north
    )
    selected = selected.isel(longitude=longitude_window, latitude=latitude_window)
    selected = _thin_spatial(
        selected,
        x_dimension="longitude",
        y_dimension="latitude",
        maximum_width=maximum_width,
        maximum_height=maximum_height,
    ).compute()
    if float(selected.longitude[0]) > float(selected.longitude[-1]):
        selected = selected.sortby("longitude")
    if float(selected.latitude[0]) > float(selected.latitude[-1]):
        selected = selected.sortby("latitude")
    selected = selected.transpose("latitude", "longitude")
    west, east = _coordinate_edges(
        selected.longitude.values, minimum=-180, maximum=180
    )
    south, north = _coordinate_edges(
        selected.latitude.values,
        minimum=-MAX_MERCATOR_LATITUDE,
        maximum=MAX_MERCATOR_LATITUDE,
    )
    return selected, MapBounds(west=west, south=south, east=east, north=north)


def _projected_native_window(
    data: xr.DataArray,
    *,
    bounds: MapBounds,
    crs_wkt: str,
    maximum_width: int,
    maximum_height: int,
) -> xr.DataArray:
    from pyproj import CRS, Transformer

    source_crs = CRS.from_wkt(crs_wkt)
    transformer = Transformer.from_crs("EPSG:4326", source_crs, always_xy=True)
    samples = np.linspace(0, 1, 17)
    longitudes = np.concatenate(
        [
            bounds.west + ((bounds.east - bounds.west) * samples),
            bounds.west + ((bounds.east - bounds.west) * samples),
            np.full_like(samples, bounds.west),
            np.full_like(samples, bounds.east),
        ]
    )
    latitudes = np.concatenate(
        [
            np.full_like(samples, bounds.south),
            np.full_like(samples, bounds.north),
            bounds.south + ((bounds.north - bounds.south) * samples),
            bounds.south + ((bounds.north - bounds.south) * samples),
        ]
    )
    projected_x, projected_y = transformer.transform(longitudes, latitudes)
    finite = np.isfinite(projected_x) & np.isfinite(projected_y)
    if not finite.any():
        raise DynamicalMapError("requested bounds cannot be transformed to the dataset CRS")
    x_window = _coordinate_indices(
        np.asarray(data.coords["x"].values),
        float(np.min(projected_x[finite])),
        float(np.max(projected_x[finite])),
    )
    y_window = _coordinate_indices(
        np.asarray(data.coords["y"].values),
        float(np.min(projected_y[finite])),
        float(np.max(projected_y[finite])),
    )
    selected = data.isel(x=x_window, y=y_window)
    return _thin_spatial(
        selected,
        x_dimension="x",
        y_dimension="y",
        maximum_width=maximum_width,
        maximum_height=maximum_height,
    ).compute()


def reproject_native_grid(
    data: xr.DataArray,
    *,
    crs_wkt: str,
    requested_bounds: MapBounds,
    width: int,
    height: int,
) -> tuple[xr.DataArray, MapBounds]:
    """Reproject a native x/y model grid to a regular WGS84 image grid."""

    import cartopy.crs as ccrs
    import geoviews as gv
    from geoviews.operation import project_image
    from geoviews.util import proj_to_cartopy
    from pyproj import CRS, Proj

    if set(data.dims) != {"x", "y"}:
        raise DynamicalMapError("native projected data must contain only x and y dimensions")
    source_crs = proj_to_cartopy(Proj(CRS.from_wkt(crs_wkt)))
    x = np.asarray(data.coords["x"].values, dtype=float)
    y = np.asarray(data.coords["y"].values, dtype=float)
    values = np.asarray(data.transpose("y", "x").values, dtype=float)
    element = gv.Image(
        (x, y, values),
        kdims=["x", "y"],
        vdims=[data.name or "value"],
        crs=source_crs,
    )
    projected = project_image(
        element,
        projection=ccrs.PlateCarree(),
        width=width,
        height=height,
        fast=False,
    )
    longitude = np.asarray(projected.dimension_values(0, expanded=False), dtype=float)
    latitude = np.asarray(projected.dimension_values(1, expanded=False), dtype=float)
    projected_values = np.ma.asarray(projected.dimension_values(2, flat=False)).filled(np.nan)
    result = xr.DataArray(
        projected_values,
        coords={"latitude": latitude, "longitude": longitude},
        dims=("latitude", "longitude"),
        name=data.name,
        attrs=dict(data.attrs),
    )
    longitude_window = _coordinate_indices(longitude, requested_bounds.west, requested_bounds.east)
    latitude_window = _coordinate_indices(latitude, requested_bounds.south, requested_bounds.north)
    result = result.isel(longitude=longitude_window, latitude=latitude_window)
    if float(result.longitude[0]) > float(result.longitude[-1]):
        result = result.sortby("longitude")
    if float(result.latitude[0]) > float(result.latitude[-1]):
        result = result.sortby("latitude")
    west, east = _coordinate_edges(result.longitude.values, minimum=-180, maximum=180)
    south, north = _coordinate_edges(
        result.latitude.values,
        minimum=-MAX_MERCATOR_LATITUDE,
        maximum=MAX_MERCATOR_LATITUDE,
    )
    clipped_bounds = MapBounds(
        west=max(requested_bounds.west, west),
        south=max(requested_bounds.south, south),
        east=min(requested_bounds.east, east),
        north=min(requested_bounds.north, north),
    )
    return result, clipped_bounds


def _selected_valid_time(value: object) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(UTC)
    else:
        timestamp = timestamp.tz_convert(UTC)
    return timestamp.to_pydatetime()


def select_grid_slice(
    dataset: xr.Dataset,
    *,
    layer_id: str,
    variable: str,
    requested_time: datetime,
    bounds: MapBounds,
    maximum_width: int = 512,
    maximum_height: int = 512,
) -> DynamicalGridSlice:
    """Select and compute one bounded map slice from an already-open dataset."""

    definition = _layer(layer_id)
    if definition.catalog_id == "asos-parquet":
        raise DynamicalMapError("ASOS is a point dataset; use fetch_asos_slice")
    if variable not in dataset.data_vars:
        raise DynamicalMapError(
            f"{variable!r} is not present in Dynamical dataset {definition.catalog_id!r}"
        )
    requested = _utc(requested_time, label="requested time")
    target = np.datetime64(requested.replace(tzinfo=None), "ns")
    try:
        selected = dataset[variable].sel(time=target, method="nearest")
    except (KeyError, ValueError) as exc:
        raise DynamicalMapError("dataset does not expose a selectable time coordinate") from exc
    actual_time = _selected_valid_time(selected.coords["time"].item())
    if abs(actual_time - requested) > definition.time_tolerance:
        raise DynamicalMapError(
            f"nearest {definition.catalog_id} value is outside the permitted time tolerance"
        )
    selected = selected.squeeze(drop=True)

    if {"latitude", "longitude"}.issubset(selected.dims):
        rendered_data, rendered_bounds = _regular_lonlat_slice(
            selected,
            bounds=bounds,
            maximum_width=maximum_width,
            maximum_height=maximum_height,
        )
    elif {"x", "y"}.issubset(selected.dims):
        if "spatial_ref" not in dataset.variables:
            raise DynamicalMapError("projected dataset does not expose spatial_ref metadata")
        crs_wkt = str(dataset["spatial_ref"].attrs.get("crs_wkt", "")).strip()
        if not crs_wkt:
            raise DynamicalMapError("projected dataset spatial_ref does not contain crs_wkt")
        native = _projected_native_window(
            selected,
            bounds=bounds,
            crs_wkt=crs_wkt,
            maximum_width=maximum_width,
            maximum_height=maximum_height,
        )
        rendered_data, rendered_bounds = reproject_native_grid(
            native,
            crs_wkt=crs_wkt,
            requested_bounds=bounds,
            width=maximum_width,
            height=maximum_height,
        )
    else:
        raise DynamicalMapError(
            "weather variable must use latitude/longitude or projected x/y map dimensions"
        )

    values = np.asarray(rendered_data.values, dtype=float)
    if not np.isfinite(values).any():
        raise DynamicalMapError("selected Dynamical slice contains no finite values")
    units = str(dataset[variable].attrs.get("units", "unknown")).strip() or "unknown"
    attribution = str(dataset.attrs.get("attribution", "")).strip()
    if not attribution:
        raise DynamicalMapError("Dynamical dataset does not provide attribution metadata")
    return DynamicalGridSlice(
        layer_id=layer_id,
        catalog_id=definition.catalog_id,
        variable=variable,
        units=units,
        attribution=attribution,
        catalog_url=definition.catalog_url,
        valid_time=actual_time,
        data=rendered_data,
        bounds=rendered_bounds,
    )


def fetch_grid_slice(
    *,
    layer_id: str,
    variable: str | None,
    requested_time: datetime,
    bounds: MapBounds,
    maximum_width: int = 512,
    maximum_height: int = 512,
    opener: Callable[[str], xr.Dataset] | None = None,
) -> DynamicalGridSlice:
    """Open an official Dynamical catalog dataset and compute a bounded slice."""

    definition = _layer(layer_id)
    if definition.catalog_id == "asos-parquet":
        raise DynamicalMapError("ASOS is a point dataset; use fetch_asos_slice")
    if opener is None:
        try:
            dynamical_catalog = import_module("dynamical_catalog")
        except ImportError as exc:
            raise DynamicalMapError(
                "real Dynamical reads require dynamical-catalog>=0.7"
            ) from exc
        opener = dynamical_catalog.open
    dataset = opener(definition.catalog_id)
    try:
        return select_grid_slice(
            dataset,
            layer_id=layer_id,
            variable=variable or definition.default_variable,
            requested_time=requested_time,
            bounds=bounds,
            maximum_width=maximum_width,
            maximum_height=maximum_height,
        )
    finally:
        dataset.close()


def fetch_asos_slice(
    *,
    variable: str | None,
    requested_time: datetime,
    bounds: MapBounds,
    maximum_points: int = 5_000,
    connection_factory: Callable[[], Any] | None = None,
) -> DynamicalPointSlice:
    """Query nearest-in-window ASOS/AWOS station observations with DuckDB."""

    definition = _layer("dynamical-asos")
    selected_variable = variable or definition.default_variable
    if selected_variable not in ASOS_VARIABLE_UNITS:
        supported = ", ".join(sorted(ASOS_VARIABLE_UNITS))
        raise DynamicalMapError(f"unsupported ASOS variable; choose one of: {supported}")
    if not 1 <= maximum_points <= 10_000:
        raise DynamicalMapError("maximum ASOS points must be within 1..10000")
    requested = _utc(requested_time, label="requested time")
    start = requested - definition.time_tolerance
    end = requested + definition.time_tolerance
    years = range(start.year, end.year + 1)
    urls = [f"{ASOS_BASE_URL}/year={year}/data.parquet" for year in years]
    if connection_factory is None:
        try:
            duckdb = import_module("duckdb")
        except ImportError as exc:
            raise DynamicalMapError("ASOS reads require duckdb>=1.3") from exc
        connection_factory = duckdb.connect
    connection = connection_factory()
    try:
        frame = connection.execute(
            f"""
            SELECT station, valid, longitude, latitude, {selected_variable}, name, country
            FROM (
              SELECT
                station,
                valid,
                longitude,
                latitude,
                {selected_variable},
                name,
                country,
                ROW_NUMBER() OVER (
                  PARTITION BY station
                  ORDER BY abs(epoch(valid) - epoch(?))
                ) AS nearest_rank
              FROM read_parquet(?, hive_partitioning=true)
              WHERE valid >= ?
                AND valid <= ?
                AND longitude >= ?
                AND longitude <= ?
                AND latitude >= ?
                AND latitude <= ?
                AND {selected_variable} IS NOT NULL
            )
            WHERE nearest_rank = 1
            ORDER BY station
            LIMIT ?
            """,
            [
                requested,
                urls,
                start,
                end,
                bounds.west,
                bounds.east,
                bounds.south,
                bounds.north,
                maximum_points,
            ],
        ).fetchdf()
    finally:
        connection.close()
    if frame.empty:
        raise DynamicalMapError("no ASOS/AWOS observations matched the requested map window")
    frame = frame.rename(columns={selected_variable: "value"})
    frame["longitude"] = pd.to_numeric(frame["longitude"], errors="coerce")
    frame["latitude"] = pd.to_numeric(frame["latitude"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["longitude", "latitude", "value"]
    )
    if frame.empty:
        raise DynamicalMapError("ASOS/AWOS query returned no finite map values")
    return DynamicalPointSlice(
        layer_id=definition.layer_id,
        catalog_id=definition.catalog_id,
        variable=selected_variable,
        units=ASOS_VARIABLE_UNITS[selected_variable],
        attribution=(
            "Iowa Environmental Mesonet ASOS/AWOS observations republished by dynamical.org."
        ),
        catalog_url=definition.catalog_url,
        valid_time=requested,
        points=frame,
        bounds=bounds,
    )


def _value_range(
    values: np.ndarray,
    requested: tuple[float, float] | None,
    *,
    variable: str,
    units: str,
) -> tuple[float, float]:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        raise DynamicalMapError("overlay contains no finite values")
    if requested is None and (variable, units) in FIXED_VALUE_RANGES:
        return FIXED_VALUE_RANGES[(variable, units)]
    if requested is None:
        lower, upper = np.nanpercentile(finite, [2, 98])
        if not math.isfinite(float(lower)) or not math.isfinite(float(upper)):
            raise DynamicalMapError("overlay value range is not finite")
        if math.isclose(float(lower), float(upper)):
            padding = max(abs(float(lower)) * 0.01, 0.5)
            lower -= padding
            upper += padding
        return float(lower), float(upper)
    lower, upper = requested
    if not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper:
        raise DynamicalMapError("explicit overlay value range must be finite and increasing")
    return float(lower), float(upper)


def _color_map(variable: str):
    normalized = variable.casefold()
    if "temperature" in normalized or normalized in {"tmpc", "tmpf", "dwpc", "dwpf"}:
        palette = cc.cm.CET_D1A
    elif "precip" in normalized or normalized in {"p01i", "p01m"}:
        palette = cc.cm.CET_L17
    elif "reflectivity" in normalized:
        palette = cc.cm.CET_CBL2
    else:
        palette = cc.cm.CET_L18
    return palette.with_extremes(bad=(0, 0, 0, 0))


def _save_figure(
    figure,
    path: Path,
    *,
    bounds: MapBounds,
    width: int,
    height: int,
    color_map,
    render_y_bounds: tuple[float, float] | None = None,
) -> None:
    if not 64 <= width <= 2_048 or not 64 <= height <= 2_048:
        raise DynamicalMapError("overlay dimensions must each be within 64..2048 pixels")
    dpi = 100
    figure.set_size_inches(width / dpi, height / dpi, forward=True)
    figure.patch.set_alpha(0)
    south_y, north_y = render_y_bounds or (bounds.south, bounds.north)
    for axis in figure.axes:
        axis.set_position([0, 0, 1, 1])
        axis.set_xlim(bounds.west, bounds.east)
        axis.set_ylim(south_y, north_y)
        axis.set_aspect("auto")
        axis.set_axis_off()
        axis.patch.set_alpha(0)
        for image in axis.get_images():
            image.set_cmap(color_map)
            image.set_interpolation("nearest")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb", suffix=".png", dir=path.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        figure.savefig(
            temporary_path,
            format="png",
            dpi=dpi,
            transparent=True,
            bbox_inches=None,
            pad_inches=0,
            metadata={"Software": "HoloViews/Matplotlib Dynamical map producer"},
        )
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _render_grid(
    item: DynamicalGridSlice,
    image_path: Path,
    *,
    width: int,
    height: int,
    value_range: tuple[float, float] | None,
) -> tuple[float, float]:
    data = item.data.transpose("latitude", "longitude")
    values = np.asarray(data.values, dtype=float)
    limits = _value_range(
        values,
        value_range,
        variable=item.variable,
        units=item.units,
    )
    color_map = _color_map(item.variable)
    mercator_data = mercator_resample_grid(data, item.bounds, rows=height)
    south_y = float(mercator_y(item.bounds.south))
    north_y = float(mercator_y(item.bounds.north))
    hv.extension("matplotlib")
    image = hv.Image(
        (
            np.asarray(mercator_data.longitude.values, dtype=float),
            np.asarray(mercator_data.mercator_y.values, dtype=float),
            np.ma.masked_invalid(np.asarray(mercator_data.values, dtype=float)),
        ),
        bounds=(item.bounds.west, south_y, item.bounds.east, north_y),
        kdims=["longitude", "mercator_y"],
        vdims=[item.variable],
    ).opts(
        backend="matplotlib",
        cmap=color_map,
        clim=limits,
        colorbar=False,
        xaxis=None,
        yaxis=None,
        show_frame=False,
    )
    figure = hv.render(image, backend="matplotlib")
    try:
        _save_figure(
            figure,
            image_path,
            bounds=item.bounds,
            width=width,
            height=height,
            color_map=color_map,
            render_y_bounds=(south_y, north_y),
        )
    finally:
        plt.close(figure)
    return limits


def _render_points(
    item: DynamicalPointSlice,
    image_path: Path,
    *,
    width: int,
    height: int,
    value_range: tuple[float, float] | None,
) -> tuple[float, float]:
    limits = _value_range(
        item.points["value"].to_numpy(dtype=float),
        value_range,
        variable=item.variable,
        units=item.units,
    )
    color_map = _color_map(item.variable)
    points_frame = item.points.copy()
    points_frame["mercator_y"] = mercator_y(points_frame["latitude"].to_numpy(dtype=float))
    south_y = float(mercator_y(item.bounds.south))
    north_y = float(mercator_y(item.bounds.north))
    hv.extension("matplotlib")
    points = hv.Points(
        points_frame,
        kdims=["longitude", "mercator_y"],
        vdims=["value", "station", "valid", "name", "country"],
    ).opts(
        backend="matplotlib",
        color="value",
        cmap=color_map,
        clim=limits,
        colorbar=False,
        s=34,
        alpha=0.95,
        edgecolor="white",
        linewidth=0.75,
        xlim=(item.bounds.west, item.bounds.east),
        ylim=(south_y, north_y),
        xaxis=None,
        yaxis=None,
        show_frame=False,
    )
    figure = hv.render(points, backend="matplotlib")
    try:
        _save_figure(
            figure,
            image_path,
            bounds=item.bounds,
            width=width,
            height=height,
            color_map=color_map,
            render_y_bounds=(south_y, north_y),
        )
    finally:
        plt.close(figure)
    return limits


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_dynamical_overlay(
    item: DynamicalGridSlice | DynamicalPointSlice,
    output_directory: Path,
    *,
    generated_at: datetime,
    public_url: str = MAP_IMAGE_FILENAME,
    image_filename: str = MAP_IMAGE_FILENAME,
    manifest_filename: str = MAP_MANIFEST_FILENAME,
    width: int = 512,
    height: int = 512,
    value_range: tuple[float, float] | None = None,
) -> DynamicalOverlayBundle:
    """Render a HoloViews overlay and its directly consumable MapLibre manifest."""

    generated = _utc(generated_at, label="generation time")
    if not public_url or any(character in public_url for character in ("\n", "\r")):
        raise DynamicalMapError("public overlay URL must be a nonblank single-line value")
    for filename, label in (
        (image_filename, "image filename"),
        (manifest_filename, "manifest filename"),
    ):
        if (
            not filename
            or Path(filename).name != filename
            or any(character in filename for character in ("\n", "\r"))
        ):
            raise DynamicalMapError(f"{label} must be a plain nonblank filename")
    output_directory.mkdir(parents=True, exist_ok=True)
    image_path = output_directory / image_filename
    manifest_path = output_directory / manifest_filename
    if isinstance(item, DynamicalGridSlice):
        limits = _render_grid(
            item,
            image_path,
            width=width,
            height=height,
            value_range=value_range,
        )
        feature_count = None
    else:
        limits = _render_points(
            item,
            image_path,
            width=width,
            height=height,
            value_range=value_range,
        )
        feature_count = len(item.points)
    manifest: dict[str, Any] = {
        "schemaVersion": MAP_SCHEMA_VERSION,
        "datasetId": item.layer_id,
        "catalogId": item.catalog_id,
        "kind": "image",
        "url": public_url,
        "coordinates": item.bounds.maplibre_coordinates,
        "generatedAt": _iso_utc(generated),
        "validTime": _iso_utc(item.valid_time),
        "variable": item.variable,
        "units": item.units,
        "attribution": item.attribution,
        "status": "available",
        "renderer": "holoviews-matplotlib",
        "catalogUrl": item.catalog_url,
        "image": {
            "filename": image_path.name,
            "width": width,
            "height": height,
            "sha256": _sha256(image_path),
            "valueRange": [limits[0], limits[1]],
        },
    }
    if feature_count is not None:
        manifest["featureCount"] = feature_count
    encoded = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        suffix=".json",
        dir=output_directory,
        delete=False,
    ) as temporary:
        temporary.write(encoded)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    try:
        os.replace(temporary_path, manifest_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return DynamicalOverlayBundle(
        directory=output_directory,
        image_path=image_path,
        manifest_path=manifest_path,
        manifest=manifest,
    )


def fetch_and_export_dynamical_overlay(
    *,
    layer_id: str,
    variable: str | None,
    requested_time: datetime,
    bounds: MapBounds,
    output_directory: Path,
    generated_at: datetime,
    public_url: str = MAP_IMAGE_FILENAME,
    width: int = 512,
    height: int = 512,
) -> DynamicalOverlayBundle:
    """Opt-in real-data command path; importing this module never opens the network."""

    if layer_id == "dynamical-asos":
        item: DynamicalGridSlice | DynamicalPointSlice = fetch_asos_slice(
            variable=variable,
            requested_time=requested_time,
            bounds=bounds,
        )
    else:
        item = fetch_grid_slice(
            layer_id=layer_id,
            variable=variable,
            requested_time=requested_time,
            bounds=bounds,
            maximum_width=width,
            maximum_height=height,
        )
    return export_dynamical_overlay(
        item,
        output_directory,
        generated_at=generated_at,
        public_url=public_url,
        width=width,
        height=height,
    )


__all__ = [
    "ASOS_VARIABLE_UNITS",
    "DYNAMICAL_LAYERS",
    "MAP_IMAGE_FILENAME",
    "MAP_MANIFEST_FILENAME",
    "DynamicalGridSlice",
    "DynamicalMapError",
    "DynamicalOverlayBundle",
    "DynamicalPointSlice",
    "MapBounds",
    "export_dynamical_overlay",
    "fetch_and_export_dynamical_overlay",
    "fetch_asos_slice",
    "fetch_grid_slice",
    "inverse_mercator_y",
    "mercator_resample_grid",
    "mercator_y",
    "reproject_native_grid",
    "select_grid_slice",
]
