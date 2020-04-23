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

from invest_heat_islands import geo_utils, meteoswiss, settings
from invest_heat_islands.regression import utils


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


def predict_T(regr, T_grid_arr, landsat_features_ds, dem_arr, T_nodata=np.nan):
    features = [T_grid_arr.flatten()]
    for landsat_feature in utils.LANDSAT_FEATURES:
        features.append(landsat_features_ds[landsat_feature].values.flatten())
    features.append(dem_arr.flatten())
    X = np.column_stack(features)

    T_pred_arr = np.full(X.shape[0], T_nodata)
    data_idx = ~pd.DataFrame(X).isna().any(axis=1)
    T_pred_arr.ravel()[data_idx] = regr.predict(X[data_idx])

    return T_pred_arr.reshape(T_grid_arr.shape)


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

    # read the dates from the air temperature station measurements data frame
    # we need at least series to groupby year and access the group series
    # whose index will be the dates in its respective year
    date_ser = pd.Series(0,
                         index=pd.to_datetime(
                             pd.read_csv(station_tair_filepath,
                                         index_col=0).index))

    # 1. Prepare the regression features
    # 1.1 meteoswiss grid data temperature
    # prepare remote access to MeteoSwiss grid data
    fs = meteoswiss.get_meteoswiss_fs()
    bucket_name = environ.get('S3_BUCKET_NAME')
    # get the grid temperature map
    T_grid_da = xr.concat([
        xr.DataArray(
            meteoswiss.open_meteoswiss_s3_ds(
                fs,
                bucket_name,
                year,
                meteoswiss.METEOSWISS_GRID_PRODUCT,
                geometry=ref_geom,
                crs=crs,
                roi_kws={'all_touched': True},
            )[meteoswiss.METEOSWISS_GRID_PRODUCT]).sel(time=year_ser.index)
        for year, year_ser in date_ser.groupby(date_ser.index.year)
    ],
                          dim='time')
    # align it
    T_grid_da = ref_da.salem.transform(
        T_grid_da, interp='linear').salem.subset(geometry=data_geom, crs=crs)

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
        landsat_features_ds = landsat_features_ds.assign(
            landsat_features_ds[landsat_feature].groupby('time').map(
                get_savg_feature_ds,
                args=(kernel_dict, ))).drop(landsat_feature)
    landsat_features_ds = landsat_features_ds.salem.subset(geometry=data_geom,
                                                           crs=crs)

    # 1.4 Elevation
    # dem_s3_filepath = path.join(bucket_name, dem_file_key)
    # with fs_s3.open(dem_s3_filepath) as dem_file_obj:
    dem_da = geo_utils.salem_da_from_singleband(swiss_dem_filepath)
    # align it
    dem_arr = T_grid_da.salem.transform(dem_da, interp='linear').values

    # 2. Use the trained regressor to predict the air temperature at the
    #    target resolution
    regr = jl.load(regressor_filepath)
    T_pred_da = xr.DataArray([
        predict_T(regr,
                  T_grid_da.sel(time=date).values,
                  landsat_features_ds.sel(time=date), dem_arr)
        for date in date_ser.index
    ],
                             dims=('time', 'y', 'x'),
                             coords={
                                 'time': date_ser.index,
                                 'y': T_grid_da.y,
                                 'x': T_grid_da.x
                             },
                             attrs=landsat_features_ds.attrs)

    # 3. Crop the data array to the valid data region and dump it to a file
    T_pred_da.salem.roi(geometry=data_geom, crs=crs).to_netcdf(dst_filepath)
    logger.info("dumped predicted air temperature data array to %s",
                dst_filepath)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format=settings.DEFAULT_LOG_FMT)

    # find .env automagically by walking up directories until it's found, then
    # load up the .env entries as environment variables
    dotenv.load_dotenv(dotenv.find_dotenv())

    main()
