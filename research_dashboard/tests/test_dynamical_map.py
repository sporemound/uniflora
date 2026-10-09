from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from PIL import Image
from pyproj import CRS

from missing_interior_dashboard.dynamical_map import (
    DynamicalGridSlice,
    DynamicalMapError,
    DynamicalPointSlice,
    MapBounds,
    export_dynamical_overlay,
    inverse_mercator_y,
    mercator_resample_grid,
    mercator_y,
    reproject_native_grid,
    select_grid_slice,
)

VALID_TIME = datetime(2026, 8, 2, 20, tzinfo=UTC)
GENERATED_AT = datetime(2026, 8, 2, 21, tzinfo=UTC)


def _grid_slice() -> DynamicalGridSlice:
    values = np.arange(20, dtype=float).reshape(4, 5)
    values[0, 0] = np.nan
    data = xr.DataArray(
        values,
        coords={
            "latitude": [40.0, 41.0, 42.0, 43.0],
            "longitude": [-104.0, -103.0, -102.0, -101.0, -100.0],
        },
        dims=("latitude", "longitude"),
        name="temperature_2m",
    )
    return DynamicalGridSlice(
        layer_id="dynamical-gfs-analysis",
        catalog_id="noaa-gfs-analysis",
        variable="temperature_2m",
        units="degree_Celsius",
        attribution="NOAA GFS from dynamical.org.",
        catalog_url="https://dynamical.org/catalog/noaa-gfs-analysis/",
        valid_time=VALID_TIME,
        data=data,
        bounds=MapBounds(-104.5, 39.5, -99.5, 43.5),
    )


def test_grid_export_creates_transparent_georeferenced_holoviews_image(
    tmp_path: Path,
) -> None:
    bundle = export_dynamical_overlay(
        _grid_slice(),
        tmp_path,
        generated_at=GENERATED_AT,
        public_url="/data/dynamical/dynamical-gfs-analysis.png",
        width=320,
        height=240,
    )

    image = Image.open(bundle.image_path)
    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))

    assert image.mode == "RGBA"
    assert image.size == (320, 240)
    assert image.getchannel("A").getextrema() == (0, 255)
    assert manifest["schemaVersion"] == 1
    assert manifest["datasetId"] == "dynamical-gfs-analysis"
    assert manifest["kind"] == "image"
    assert manifest["url"] == "/data/dynamical/dynamical-gfs-analysis.png"
    assert manifest["coordinates"] == [
        [-104.5, 43.5],
        [-99.5, 43.5],
        [-99.5, 39.5],
        [-104.5, 39.5],
    ]
    assert manifest["generatedAt"] == "2026-08-02T21:00:00Z"
    assert manifest["validTime"] == "2026-08-02T20:00:00Z"
    assert manifest["variable"] == "temperature_2m"
    assert manifest["units"] == "degree_Celsius"
    assert manifest["attribution"] == "NOAA GFS from dynamical.org."
    assert manifest["status"] == "available"
    assert manifest["renderer"] == "holoviews-matplotlib"
    assert len(manifest["image"]["sha256"]) == 64


def test_grid_export_is_byte_reproducible(tmp_path: Path) -> None:
    first = export_dynamical_overlay(
        _grid_slice(),
        tmp_path / "first",
        generated_at=GENERATED_AT,
        width=256,
        height=192,
    )
    second = export_dynamical_overlay(
        _grid_slice(),
        tmp_path / "second",
        generated_at=GENERATED_AT,
        width=256,
        height=192,
    )

    assert first.image_path.read_bytes() == second.image_path.read_bytes()
    assert first.manifest_path.read_bytes() == second.manifest_path.read_bytes()


def test_select_grid_slice_bounds_and_downsamples_without_network() -> None:
    times = np.array(["2026-08-02T19:00", "2026-08-02T20:00"], dtype="datetime64[ns]")
    latitude = np.linspace(30, 50, 81)
    longitude = np.linspace(-120, -80, 161)
    values = np.add.outer(latitude, longitude)
    dataset = xr.Dataset(
        {
            "temperature_2m": (
                ("time", "latitude", "longitude"),
                np.stack([values - 1, values]),
                {"units": "degree_Celsius"},
            )
        },
        coords={"time": times, "latitude": latitude, "longitude": longitude},
        attrs={"attribution": "NOAA GFS from dynamical.org."},
    )

    selected = select_grid_slice(
        dataset,
        layer_id="dynamical-gfs-analysis",
        variable="temperature_2m",
        requested_time=VALID_TIME,
        bounds=MapBounds(-105, 35, -95, 45),
        maximum_width=24,
        maximum_height=20,
    )

    assert selected.valid_time == VALID_TIME
    assert selected.data.dims == ("latitude", "longitude")
    assert selected.data.sizes["longitude"] <= 24
    assert selected.data.sizes["latitude"] <= 20
    assert selected.bounds.west < -104.5
    assert selected.bounds.east > -95.5
    assert np.isfinite(selected.data.values).all()


def test_projected_hrrr_grid_is_reprojected_to_regular_lonlat() -> None:
    x = np.linspace(-1_200_000, 1_200_000, 80)
    y = np.linspace(-800_000, 800_000, 60)
    values = np.add.outer(y / 100_000, x / 100_000)
    data = xr.DataArray(
        values,
        coords={"y": y, "x": x},
        dims=("y", "x"),
        name="composite_reflectivity",
    )
    crs = CRS.from_proj4(
        "+proj=lcc +lat_0=38.5 +lon_0=-97.5 +lat_1=38.5 +lat_2=38.5 "
        "+R=6371229 +units=m +no_defs"
    )
    requested = MapBounds(-108, 32, -87, 46)

    result, result_bounds = reproject_native_grid(
        data,
        crs_wkt=crs.to_wkt(),
        requested_bounds=requested,
        width=96,
        height=80,
    )

    assert result.dims == ("latitude", "longitude")
    assert result.sizes["latitude"] >= 2
    assert result.sizes["longitude"] >= 2
    assert np.isfinite(result.values).any()
    assert requested.west <= result_bounds.west < result_bounds.east <= requested.east
    assert requested.south <= result_bounds.south < result_bounds.north <= requested.north


def test_raster_rows_are_uniform_in_web_mercator_not_latitude() -> None:
    latitude = np.linspace(-80, 80, 33)
    longitude = np.array([-10.0, 0.0, 10.0])
    data = xr.DataArray(
        np.repeat(latitude[:, np.newaxis], longitude.size, axis=1),
        coords={"latitude": latitude, "longitude": longitude},
        dims=("latitude", "longitude"),
        name="latitude_value",
    )
    bounds = MapBounds(-15, -80, 15, 80)

    projected = mercator_resample_grid(data, bounds, rows=17)
    projected_y = projected.mercator_y.to_numpy()
    sampled_latitude = projected.latitude.to_numpy()

    assert np.allclose(np.diff(projected_y), np.diff(projected_y)[0])
    assert not np.allclose(np.diff(sampled_latitude), np.diff(sampled_latitude)[0])
    assert np.allclose(inverse_mercator_y(projected_y), sampled_latitude)
    assert np.allclose(mercator_y(sampled_latitude), projected_y)
    assert projected.values[0].mean() < 0 < projected.values[-1].mean()


def test_asos_points_export_uses_same_image_contract(tmp_path: Path) -> None:
    points = pd.DataFrame(
        {
            "station": ["KSEA", "KPDX", "KGEG"],
            "valid": [VALID_TIME] * 3,
            "longitude": [-122.31, -122.60, -117.53],
            "latitude": [47.45, 45.59, 47.62],
            "value": [24.0, 27.0, 29.0],
            "name": ["Seattle", "Portland", "Spokane"],
            "country": ["US", "US", "US"],
        }
    )
    item = DynamicalPointSlice(
        layer_id="dynamical-asos",
        catalog_id="asos-parquet",
        variable="tmpc",
        units="degree_Celsius",
        attribution="Iowa Environmental Mesonet via dynamical.org.",
        catalog_url="https://dynamical.org/catalog/asos-parquet/",
        valid_time=VALID_TIME,
        points=points,
        bounds=MapBounds(-125, 44, -116, 49),
    )

    bundle = export_dynamical_overlay(
        item,
        tmp_path,
        generated_at=GENERATED_AT,
        width=256,
        height=192,
    )

    image = Image.open(bundle.image_path)
    minimum_alpha, maximum_alpha = image.getchannel("A").getextrema()
    assert minimum_alpha == 0
    assert maximum_alpha > 0
    assert bundle.manifest["datasetId"] == "dynamical-asos"
    assert bundle.manifest["featureCount"] == 3


def test_map_contract_rejects_antimeridian_and_stale_nearest_time() -> None:
    with pytest.raises(DynamicalMapError, match="non-wrapping"):
        MapBounds(170, -20, -170, 20)

    dataset = xr.Dataset(
        {
            "temperature_2m": (
                ("time", "latitude", "longitude"),
                np.ones((1, 2, 2)),
                {"units": "degree_Celsius"},
            )
        },
        coords={
            "time": np.array(["2026-08-01T00:00"], dtype="datetime64[ns]"),
            "latitude": [40, 41],
            "longitude": [-101, -100],
        },
        attrs={"attribution": "NOAA GFS from dynamical.org."},
    )
    with pytest.raises(DynamicalMapError, match="time tolerance"):
        select_grid_slice(
            dataset,
            layer_id="dynamical-gfs-analysis",
            variable="temperature_2m",
            requested_time=VALID_TIME,
            bounds=MapBounds(-102, 39, -99, 42),
        )
