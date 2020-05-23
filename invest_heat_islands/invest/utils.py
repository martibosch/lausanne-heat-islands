import tempfile
from os import path

import dask
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
                 aoi_vector_filepath, ref_et_filepath, station_tair_filepath,
                 station_locations_filepath, extra_ucm_args, **kwargs):
        ref_et_dir = tempfile.mkdtemp()
        ref_et_raster_filepath_dict = dump_ref_et_rasters(
            ref_et_filepath, ref_et_dir)
        self.dates = list(ref_et_raster_filepath_dict.keys())
        super(UCMWrapper, self).__init__(
            lulc_raster_filepath,
            biophysical_table_filepath,
            aoi_vector_filepath,
            'factors',
            list(ref_et_raster_filepath_dict.values()),
            station_t_filepath=station_tair_filepath,
            station_locations_filepath=station_locations_filepath,
            extra_ucm_args=extra_ucm_args,
            **kwargs)

    @property
    def grid_x(self):
        try:
            return self._grid_x
        except AttributeError:
            cols = np.arange(self.meta['width'])
            x, _ = transform.xy(self.meta['transform'], cols, cols)
            self._grid_x = x
            return self._grid_x

    @property
    def grid_y(self):
        try:
            return self._grid_y
        except AttributeError:
            rows = np.arange(self.meta['height'])
            _, y = transform.xy(self.meta['transform'], rows, rows)
            self._grid_y = y
            return self._grid_y

    def predict_t_da(self):
        if len(self.ref_et_raster_filepaths) == 1:
            T_arrs = [self.predict_t_arr(0)]
        else:
            pred_delayed = [
                dask.delayed(self.predict_t_arr)(i)
                for i in range(len(self.ref_et_raster_filepaths))
            ]

            T_arrs = list(
                dask.compute(*pred_delayed,
                             scheduler='processes',
                             num_workers=self.num_workers))
        T_da = xr.DataArray(T_arrs,
                            dims=('time', 'y', 'x'),
                            coords={
                                'time': self.dates,
                                'y': self.grid_y,
                                'x': self.grid_x
                            },
                            name='T',
                            attrs={'pyproj_srs': self.meta['crs'].to_proj4()})
        return T_da.groupby(
            'time').apply(lambda x: x.where(self.data_mask, np.nan))

    def get_comparison_df(self):
        tair_pred_df = pd.DataFrame(index=self.station_tair_df.columns)

        T_da = self.predict_t_da()
        for date, date_da in T_da.groupby('time'):
            tair_pred_df[date] = date_da.values[self.station_rows, self.
                                                station_cols]
        tair_pred_df = tair_pred_df.transpose()

        # comparison_df['err'] = comparison_df['pred'] - comparison_df['obs']
        # comparison_df['sq_err'] = comparison_df['err']**2
        return pd.concat([self.station_tair_df.stack(),
                          tair_pred_df.stack()],
                         axis=1).reset_index().rename(columns={
                             'level_0': 'date',
                             'level_1': 'station',
                             0: 'obs',
                             1: 'pred'
                         })
