import tempfile
from os import path

import invest_ucm_calibration as iuc
import numpy as np
import pandas as pd
import rasterio as rio
import salem  # noqa: F401
import xarray as xr
from rasterio import transform


def _get_ref_eto_filepath(date, dst_dir):
    return path.join(
        dst_dir, f'ref_eto_{pd.to_datetime(date).strftime("%Y-%m-%d")}.tif')


def dump_ref_et_rasters(ref_et_filepath, dst_dir):
    ref_et_da = xr.open_dataarray(ref_et_filepath)

    # prepare metadata to dump the potential evapotranspiration rasters
    ref_et_da.name = 'ref_et'
    grid = ref_et_da.salem.grid
    width = grid.nx
    height = grid.ny
    west, east, south, north = grid.extent
    # prepare metadata to dump the potential evapotranspiration rasters
    meta = dict(driver='GTiff',
                dtype=ref_et_da.dtype,
                nodata=np.nan,
                width=width,
                height=height,
                count=1,
                transform=transform.from_bounds(west, south, east, north,
                                                width, height),
                crs=ref_et_da.attrs['pyproj_srs'])

    ref_et_raster_filepath_dict = {}
    for date, ref_et_day_da in ref_et_da.groupby('time'):
        ref_et_raster_filepath = _get_ref_eto_filepath(date, dst_dir)
        with rio.open(ref_et_raster_filepath, 'w', **meta) as dst:
            dst.write(ref_et_day_da.values, 1)
        ref_et_raster_filepath_dict[date] = ref_et_raster_filepath

    return ref_et_raster_filepath_dict


class UCMWrapper(iuc.UCMWrapper):
    def __init__(self, lulc_raster_filepath, biophysical_table_filepath,
                 ref_et_filepath, station_tair_filepath,
                 station_locations_filepath, extra_ucm_args, **kwargs):
        ref_et_dir = tempfile.mkdtemp()
        ref_et_raster_filepath_dict = dump_ref_et_rasters(
            ref_et_filepath, ref_et_dir)
        self.dates = list(ref_et_raster_filepath_dict.keys())
        super(UCMWrapper, self).__init__(
            lulc_raster_filepath,
            biophysical_table_filepath,
            'factors',
            list(ref_et_raster_filepath_dict.values()),
            station_t_filepath=station_tair_filepath,
            station_locations_filepath=station_locations_filepath,
            extra_ucm_args=extra_ucm_args,
            **kwargs)
