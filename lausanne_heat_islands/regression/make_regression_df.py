import logging

import click
import geopandas as gpd
import numpy as np
import pandas as pd
import salem
import xarray as xr

from lausanne_heat_islands import settings, utils
from lausanne_heat_islands.regression import utils as regr_utils


def get_savg_feature_arr(landsat_feature_da, station_tair_df,
                         station_location_gser, kernel_dict):
    # prepare final array
    landsat_feature_arr = np.zeros(
        (len(kernel_dict) + 1, *station_tair_df.shape),
        dtype=station_tair_df.values.dtype)

    # TODO: what is the best way to nest the i, j for loops?
    # we assume that reading the TIF files is the most expensive operation and
    # thus nest the loops accordingly (but further profiling would be
    # interesting)
    grid = landsat_feature_da.salem.grid
    width, height = grid.nx, grid.ny
    cols, rows = landsat_feature_da.salem.grid.transform(
        station_location_gser.x,
        station_location_gser.y,
        crs=station_location_gser.crs,
        nearest=True)

    for j, dt in enumerate(station_tair_df.index):
        landsat_arr = landsat_feature_da.sel(time=dt).values

        # first (i=0), no averaging
        landsat_feature_arr[0][j] = landsat_arr[rows, cols]
        for i, (pixel_radius, kernel_arr) in enumerate(kernel_dict.items(),
                                                       start=1):
            padded_landsat_arr = np.zeros(
                (height + 2 * pixel_radius, width + 2 * pixel_radius),
                dtype=landsat_arr.dtype)
            padded_landsat_arr[pixel_radius:height +
                               pixel_radius, pixel_radius:width +
                               pixel_radius] = landsat_arr
            kernel_height, kernel_width = kernel_arr.shape
            date_radius_row = []
            for row, col in zip(rows, cols):
                # print(i, j, row, col, row - pixel_radius,
                #       row + pixel_radius + 1, col - pixel_radius,
                #       col + pixel_radius + 1)
                # conv = kernel_arr * padded_landsat_arr[
                #     row - pixel_radius:row + pixel_radius + 1,
                #     col - pixel_radius:col + pixel_radius + 1]
                conv = kernel_arr * padded_landsat_arr[row:row +
                                                       kernel_height, col:col +
                                                       kernel_width]
                date_radius_row.append(conv.sum() / np.count_nonzero(conv))
            landsat_feature_arr[i][j] = date_radius_row

    # now we swap the axes to get an array where the first, second and third
    # axes correspond to the stations, dates and averaging radii respectively.
    return np.swapaxes(landsat_feature_arr, 0, 2)


@click.command()
@click.argument('station_locations_filepath', type=click.Path(exists=True))
@click.argument('station_tair_filepath', type=click.Path(exists=True))
@click.argument('landsat_features_filepath', type=click.Path(exists=True))
@click.argument('dst_filepath', type=click.Path())
def main(station_locations_filepath, station_tair_filepath,
         landsat_features_filepath, dst_filepath):
    logger = logging.getLogger(__name__)

    # preprocess geo data frame of station locations (and altitude)
    station_location_df = pd.read_csv(station_locations_filepath, index_col=0)

    # landsat features
    landsat_features_ds = xr.open_dataset(landsat_features_filepath)

    # reproject the `station_tair_df`
    station_location_gser = gpd.GeoSeries(gpd.points_from_xy(
        station_location_df['x'], station_location_df['y']),
                                          crs=utils.CRS)
    station_location_landsat_gser = station_location_gser.to_crs(
        landsat_features_ds.attrs['pyproj_srs'])

    # preprocess air temperature station measurements data frame
    # by selecting the columns of `station_location_df.index` we ensure that
    # the list of stations is in the same order in both data frames
    station_tair_df = pd.read_csv(station_tair_filepath,
                                  index_col=0)[station_location_df.index]
    station_tair_df.index = pd.to_datetime(station_tair_df.index)

    # prepare regression data frame
    regression_df = pd.DataFrame(0,
                                 index=station_tair_df.index,
                                 columns=pd.MultiIndex.from_product(
                                     (station_tair_df.columns,
                                      regr_utils.REGRESSION_DF_COLUMNS)))

    # 1. target
    for column in station_tair_df.columns:
        # df[(column, target)] = tair_station_df[column]
        regression_df[(column, 'tair_station')] = station_tair_df[column]

    # 2. features
    # 2.1 and 2.2 - LST and NDWI
    # first prepare the kernels to spatially average the landsat features
    kernel_dict = regr_utils.get_kernel_dict()
    for landsat_feature in regr_utils.LANDSAT_BASE_FEATURES:
        landsat_feature_da = landsat_features_ds[landsat_feature]
        landsat_feature_da.attrs = landsat_features_ds.attrs.copy()
        landsat_savg_feature_arr = get_savg_feature_arr(
            landsat_feature_da, station_tair_df, station_location_landsat_gser,
            kernel_dict)
        for station_column, station_feature_arr in zip(
                station_tair_df.columns, landsat_savg_feature_arr):
            for i, multi_column in enumerate([
                (station_column, f'{landsat_feature}_{radius}')
                    for radius in regr_utils.AVERAGING_RADII
            ]):
                regression_df[multi_column] = station_feature_arr[:, i]

    # 2.3 - ELEV
    for station_column in station_tair_df.columns:
        regression_df[(
            station_column,
            'elev')] = station_location_df.loc[station_column, 'alt']

    # dump it (need to dump the index here)
    # use the `[utils.REGRESSION_DF_COLUMNS]` to ensure a consistent column
    # ordering after `stack`
    regression_df.stack(level=0)[
        regr_utils.REGRESSION_DF_COLUMNS].dropna().to_csv(dst_filepath)
    logger.info("dumped air temperature regression data frame to %s",
                dst_filepath)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format=settings.DEFAULT_LOG_FMT)

    main()
