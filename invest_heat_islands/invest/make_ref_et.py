import logging
from os import environ

import click
import dotenv
import geopandas as gpd
import pandas as pd
import pyeto
import xarray as xr

from invest_heat_islands import settings, utils

# 46.519833 degrees in radians
LAUSANNE_LAT = 0.811924

METEOSWISS_GRID_PRODUCTS = ['TminD', 'TabsD', 'TmaxD']


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
    fs = utils.get_meteoswiss_fs()
    bucket_name = environ.get('S3_BUCKET_NAME')

    # pre-compute the meteo inputs
    T_ds = xr.concat([
        xr.Dataset({
            meteoswiss_grid_product: utils.open_meteoswiss_s3_ds(
                fs,
                bucket_name,
                year,
                meteoswiss_grid_product,
                geometry=ref_geom,
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
    # select only the meteoswiss product of interest (i.e., TabsD/average
    # temperature)
    T_da = T_ds[utils.METEOSWISS_GRID_PRODUCT]

    # align the reference evapotranspiration data-array to the agglom. LULC
    ref_eto_da.name = 'ref_eto'
    ref_eto_da.attrs = T_da.attrs.copy()
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
