import logging
from os import environ, path

import click
import dotenv
import fsspec
import geopandas as gpd
import pandas as pd
import pyeto
import xarray as xr

from lausanne_heat_islands import settings, utils

# 46.519833 degrees in radians
LAUSANNE_LAT = 0.811924

# constants useful for geo-operations
METEOSWISS_CRS = 'epsg:21781'
DROP_DIMS = ['lon', 'lat', 'dummy', 'swiss_coordinates']
RENAME_DIMS_MAP = {'chx': 'x', 'chy': 'y'}

# meteoswiss grid products needed to compute the reference evapotranspiration
METEOSWISS_GRID_PRODUCTS = ['TminD', 'TabsD', 'TmaxD']

# constants related to s3 remote file system
METEOSWISS_GRID_DATA_PREFIX = 'meteoswiss'
CACHE_STORAGE_DIR = path.join(path.dirname(utils.PACKAGE_ROOT),
                              'data/.meteoswiss-cache')


# meteoswiss utils
def preprocess_meteoswiss_ds(ds):
    # set crs attribute to dataset and all data variables individually
    ds.attrs['pyproj_srs'] = METEOSWISS_CRS
    for data_var in list(ds.data_vars):
        ds[data_var].attrs['pyproj_srs'] = METEOSWISS_CRS

    # drop unnecessary dimensions and rename the others so that salem can
    # understand the grid
    return ds.drop(DROP_DIMS).rename(RENAME_DIMS_MAP)


def open_meteoswiss_s3_ds(fs,
                          bucket_name,
                          year,
                          product,
                          open_kws=None,
                          shape=None,
                          geom=None,
                          crs=None,
                          preprocess=False,
                          roi=True,
                          prefix=None,
                          subset_kws=None,
                          roi_kws=None):
    if prefix is None:
        prefix = METEOSWISS_GRID_DATA_PREFIX
    file_key = path.join(
        bucket_name, prefix, product,
        f'{product}_ch01r.swisscors_{year}01010000_{year}12310000.nc')
    with fs.open(file_key) as file_obj:
        if open_kws is None:
            open_kws = {}
        ds = xr.open_dataset(file_obj, **open_kws)

    if shape is not None or geom is not None:
        ds = utils.clip_ds_to_extent(preprocess_meteoswiss_ds(ds),
                                     shape=shape,
                                     geom=geom,
                                     crs=crs,
                                     roi=roi,
                                     subset_kws=subset_kws,
                                     roi_kws=roi_kws)
    elif preprocess:
        ds = preprocess_meteoswiss_ds(ds)

    return ds


# other utils to compute the reference evapotranspiration
def compute_solar_radiation(date):
    lat = LAUSANNE_LAT
    day_of_year = date.timetuple().tm_yday
    sol_dec = pyeto.sol_dec(day_of_year)
    sha = pyeto.sunset_hour_angle(lat, sol_dec)
    ird = pyeto.inv_rel_dist_earth_sun(day_of_year)
    return pyeto.et_rad(lat, sol_dec, sha, ird)


def compute_ref_eto(day_ds):
    return pyeto.hargreaves(
        day_ds['TminD'], day_ds['TabsD'], day_ds['TmaxD'],
        compute_solar_radiation(pd.to_datetime(day_ds.time.values)))


@click.command()
@click.argument('agglom_lulc_filepath', type=click.Path(exists=True))
@click.argument('agglom_extent_filepath', type=click.Path(exists=True))
@click.argument('station_tair_filepath', type=click.Path(exists=True))
@click.argument('dst_filepath', type=click.Path())
@click.option('--buffer-dist', type=float, default=2000)
def main(agglom_lulc_filepath, agglom_extent_filepath, station_tair_filepath,
         dst_filepath, buffer_dist):
    logger = logging.getLogger(__name__)

    # get the agglomeration extent
    agglom_extent_gdf = gpd.read_file(agglom_extent_filepath)
    crs = agglom_extent_gdf.crs
    ref_geom = agglom_extent_gdf.loc[0]['geometry'].buffer(buffer_dist)
    # lake_geom = agglom_extent_gdf.loc[1]['geometry']

    # preprocess air temperature station measurements data frame (here we just
    # need the dates)
    station_tair_df = pd.read_csv(station_tair_filepath, index_col=0)
    station_tair_df.index = pd.to_datetime(station_tair_df.index)

    # prepare remote access to MeteoSwiss grid data
    fs = fsspec.filesystem(
        # 'filecache',
        'simplecache',
        target_protocol='s3',
        target_options=dict(
            profile=environ.get('S3_PROFILE_NAME'),
            client_kwargs={'endpoint_url': environ.get('S3_ENDPOINT_URL')}),
        cache_storage=CACHE_STORAGE_DIR)
    bucket_name = environ.get('S3_BUCKET_NAME')

    # pre-compute the meteo inputs
    T_ds = xr.concat([
        xr.Dataset({
            meteoswiss_grid_product: open_meteoswiss_s3_ds(
                fs,
                bucket_name,
                year,
                meteoswiss_grid_product,
                geom=ref_geom,
                crs=crs,
                roi_kws={'all_touched': True},
            )[meteoswiss_grid_product]
            for meteoswiss_grid_product in METEOSWISS_GRID_PRODUCTS
        }).sel(time=year_df.index) for year, year_df in
        station_tair_df.groupby(station_tair_df.index.year)
    ],
                     dim='time')

    # reference evapotranspiration
    ref_eto_da = T_ds.groupby('time').map(compute_ref_eto)

    # align the reference evapotranspiration data-array to the agglom. LULC
    ref_eto_da.name = 'ref_eto'
    ref_eto_da.attrs = T_ds[list(T_ds.data_vars)[0]].attrs.copy()
    ref_da = utils.salem_da_from_singleband(agglom_lulc_filepath, name='lulc')
    ref_eto_da = ref_da.salem.transform(ref_eto_da, interp='linear')

    # dump it
    ref_eto_da.to_netcdf(dst_filepath)
    logger.info("dumped reference evapotranspiration data-array to %s",
                dst_filepath)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format=settings.DEFAULT_LOG_FMT)

    # find .env automagically by walking up directories until it's found, then
    # load up the .env entries as environment variables
    dotenv.load_dotenv(dotenv.find_dotenv())

    main()
