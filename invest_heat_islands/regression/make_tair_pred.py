import logging
from os import environ

import click
import dotenv
import geopandas as gpd
import joblib as jl
import numpy as np
import pandas as pd
import xarray as xr
from rasterio import features, transform
from scipy import ndimage as ndi

from invest_heat_islands import settings, utils


def get_savg_feature_ds(day_da, kernel_dict):
    ds = day_da.to_dataset()
    name = day_da.name
    # drop the feature
    ds = ds.drop_vars(name)
    # first: radius 0 (no averaging)
    ds[f'{name}_0'] = day_da
    for pixel_radius, averaging_radius in zip(kernel_dict,
                                              utils.AVERAGING_RADII[1:]):
        kernel_arr = kernel_dict[pixel_radius]
        ds[f'{name}_{averaging_radius}'] = xr.apply_ufunc(
            lambda da: ndi.convolve(da, kernel_arr) / kernel_arr.sum(), day_da)
    return ds


def salem_da_from_singleband(raster_filepath, name=None):
    if name is None:
        name = ''  # salem needs a ds/da name (even empty)
    raster_da = xr.open_rasterio(raster_filepath).isel(band=0)
    raster_da.name = name
    raster_da.attrs['pyproj_srs'] = raster_da.crs

    return raster_da


@click.command()
@click.argument('agglom_extent_filepath', type=click.Path(exists=True))
@click.argument('station_tair_filepath', type=click.Path(exists=True))
@click.argument('landsat_features_filepath', type=click.Path(exists=True))
@click.argument('swiss_dem_filepath', type=click.Path(exists=True))
@click.argument('regressor_filepath', type=click.Path(exists=True))
@click.argument('dst_filepath', type=click.Path())
@click.option('--dst-res', type=int, default=200)
@click.option('--buffer-dist', type=int, default=2000)
def main(agglom_extent_filepath, station_tair_filepath,
         landsat_features_filepath, swiss_dem_filepath, regressor_filepath,
         dst_filepath, dst_res, buffer_dist):
    logger = logging.getLogger(__name__)

    # Compute an air temperature array from the trained regressor
    # 0. Preprocess the inputs
    # get the agglomeration extent
    agglom_extent_gdf = gpd.read_file(agglom_extent_filepath)
    crs = agglom_extent_gdf.crs
    data_geom = agglom_extent_gdf.loc[0]['geometry']
    # add a buffer to compute the convolution features well
    ref_geom = data_geom.buffer(buffer_dist)

    # use the bounds of the ref geometry to obtain the reference grid with the
    # target resolution
    west, south, east, north = ref_geom.bounds
    ref_nodata = 0
    ref_height, ref_width = tuple(
        int(np.ceil(diff / dst_res)) for diff in [north - south, east - west])
    ref_transform = transform.from_origin(west, north, dst_res, dst_res)
    rows = np.arange(ref_height)
    cols = np.arange(ref_width)
    xs, _ = transform.xy(ref_transform, cols, cols)
    _, ys = transform.xy(ref_transform, rows, rows)
    ref_da = xr.DataArray(ref_nodata,
                          dims=('y', 'x'),
                          coords={
                              'y': ys,
                              'x': xs
                          })
    ref_da.attrs['pyproj_srs'] = crs

    # burn the data geometry into the reference grid in order to have a data
    # mask
    data_mask = features.rasterize([(data_geom, 1)],
                                   out_shape=ref_da.shape,
                                   fill=ref_nodata,
                                   transform=ref_transform).astype(bool)

    # read the dates from the air temperature station measurements data frame
    # we need at least series to groupby year and access the group series
    # whose index will be the dates in its respective year
    date_ser = pd.Series(0,
                         index=pd.to_datetime(
                             pd.read_csv(station_tair_filepath,
                                         index_col=0).index))

    # 1. Prepare the regression features
    feature_columns = []
    # 1.1 meteoswiss grid data temperature
    # prepare remote access to MeteoSwiss grid data
    fs = utils.get_meteoswiss_fs()
    bucket_name = environ.get('S3_BUCKET_NAME')
    # get the grid temperature map
    T_grid_da = xr.concat([
        xr.DataArray(
            utils.open_meteoswiss_s3_ds(
                fs,
                bucket_name,
                year,
                utils.METEOSWISS_GRID_PRODUCT,
                geometry=ref_geom,
                crs=crs,
                roi_kws={'all_touched': True},
            )[utils.METEOSWISS_GRID_PRODUCT]).sel(time=year_ser.index)
        for year, year_ser in date_ser.groupby(date_ser.index.year)
    ],
                          dim='time')
    # align it
    T_grid_da = ref_da.salem.transform(T_grid_da, interp='linear')
    # add it to the feature matrix
    feature_columns.append(T_grid_da.values.flatten())

    # 1.2-1.3 Landsat features
    # open the dataset
    landsat_features_ds = xr.open_dataset(landsat_features_filepath)
    # note that we need to forward the dataset attributes to its data variables
    for data_var in landsat_features_ds.data_vars:
        landsat_features_ds[data_var].attrs = landsat_features_ds.attrs.copy()
    # align it
    landsat_features_ds = ref_da.salem.transform(landsat_features_ds,
                                                 interp='linear')
    # spatial averaging
    kernel_dict = utils.get_kernel_dict(res=dst_res)
    for landsat_feature in utils.LANDSAT_BASE_FEATURES:
        landsat_savg_feature_ds = landsat_features_ds[landsat_feature].groupby(
            'time').map(get_savg_feature_ds, args=(kernel_dict, ))
        for data_var in landsat_savg_feature_ds.data_vars:
            feature_columns.append(
                landsat_savg_feature_ds[data_var].values.flatten())

    # 1.4 Elevation
    # dem_s3_filepath = path.join(bucket_name, dem_file_key)
    # with fs_s3.open(dem_s3_filepath) as dem_file_obj:
    dem_da = salem_da_from_singleband(swiss_dem_filepath)
    # align it
    dem_da = ref_da.salem.transform(dem_da, interp='linear')
    dem_flat_arr = dem_da.values.flatten()
    feature_columns.append(np.concatenate([dem_flat_arr for _ in date_ser]))

    # 2. Use the trained regressor to predict the air temperature at the
    #    target resolution
    X = np.column_stack(feature_columns)
    regr = jl.load(regressor_filepath)
    # filter out the nodata values
    # nodata_idx = (ref_da.values != nodata).flatten()
    data_idx = data_mask.flatten()
    data_idx = np.concatenate([data_idx for _ in date_ser])
    # predict and reshape into a data array
    T_pred_arr = np.full(X.shape[0], np.nan, dtype=X.dtype)
    T_pred_arr.ravel()[data_idx] = regr.predict(X[data_idx])
    T_pred_da = xr.DataArray(T_pred_arr.reshape(
        tuple((len(date_ser), *ref_da.shape))),
                             dims=('time', 'y', 'x'),
                             coords={
                                 'time': date_ser.index,
                                 'y': ys,
                                 'x': xs
                             },
                             attrs=landsat_features_ds.attrs)

    # 3. Crop the data array to the valid data region and dump it to a file
    T_pred_da.salem.subset(geometry=data_geom, crs=crs).to_netcdf(dst_filepath)
    logger.info("dumped predicted air temperature data array to %s",
                dst_filepath)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format=settings.DEFAULT_LOG_FMT)

    # find .env automagically by walking up directories until it's found, then
    # load up the .env entries as environment variables
    dotenv.load_dotenv(dotenv.find_dotenv())

    main()
