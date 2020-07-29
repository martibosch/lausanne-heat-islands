import logging
from os import environ

import click
import dotenv
import geopandas as gpd
import pandas as pd
import salem
import swiss_uhi_utils as suhi

from lausanne_heat_islands import settings

# 46.519833 degrees in radians
LAUSANNE_LAT = 0.811924


@click.command()
@click.argument('agglom_lulc_filepath', type=click.Path(exists=True))
@click.argument('agglom_extent_filepath', type=click.Path(exists=True))
@click.argument('station_tair_filepath', type=click.Path(exists=True))
@click.argument('dst_filepath', type=click.Path())
@click.option('--buffer-dist', type=float, default=2000)
def main(agglom_lulc_filepath, agglom_extent_filepath, station_tair_filepath,
         dst_filepath, buffer_dist):
    logger = logging.getLogger(__name__)

    # get the reference information: agglomeration extent (geom), raster
    # metadata (data array)
    agglom_extent_gdf = gpd.read_file(agglom_extent_filepath)
    crs = agglom_extent_gdf.crs
    ref_geom = agglom_extent_gdf.loc[0]['geometry'].buffer(buffer_dist)
    # lake_geom = agglom_extent_gdf.loc[1]['geometry']
    # ref_da = suhi.salem_da_from_singleband(agglom_lulc_filepath, name='lulc')
    ref_da = salem.open_xr_dataset(agglom_lulc_filepath)['data']

    # preprocess air temperature station measurements data frame (here we just
    # need the dates)
    # station_tair_df = pd.read_csv(station_tair_filepath, index_col=0)
    # station_tair_df.index = pd.to_datetime(station_tair_df.index)
    dates_ser = pd.to_datetime(pd.read_csv(station_tair_filepath).iloc[:, 0])
    # this is needed to use DigitalOcean spaces
    suhi.settings.METEOSWISS_S3_CLIENT_KWARGS = {
        'endpoint_url': environ.get('S3_ENDPOINT_URL')
    }
    # get the ref. evapotranpiration data array
    ref_eto_da = suhi.get_ref_et_da(dates_ser, ref_geom, LAUSANNE_LAT, crs)

    # align it to the reference raster (i.e., LULC)
    ref_eto_da = suhi.align_ds(ref_eto_da, ref_da)
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
