import logging
import os
from os import path

import click
import geopandas as gpd
import pandas as pd
import swiss_uhi_utils as suhi
import xarray as xr

from lausanne_heat_islands import settings, utils


@click.command()
@click.argument('landsat_tiles_filepath', type=click.Path(exists=True))
@click.argument('agglom_extent_filepath', type=click.Path(exists=True))
@click.argument('dst_filepath', type=click.Path())
@click.option('--buffer-dist', default=2000)
def main(landsat_tiles_filepath, agglom_extent_filepath, dst_filepath,
         buffer_dist):
    logger = logging.getLogger(__name__)

    # read list of landsat tiles (product ids) to process
    landsat_tiles = pd.read_csv(landsat_tiles_filepath, header=None)[0]

    # get the agglomeration and lake extents
    agglom_extent_gdf = gpd.read_file(agglom_extent_filepath)
    crs = agglom_extent_gdf.crs
    ref_geom = agglom_extent_gdf.loc[0]['geometry'].buffer(buffer_dist)
    lake_geom = agglom_extent_gdf.loc[1]['geometry']

    # process the list of tiles
    datasets = []
    # use a head-tail pattern to get a reference dataset in the first
    # iteration and use it to align the datasets of further iterations
    landsat_features_kws = dict(landsat_features=['lst', 'ndwi'],
                                ref_geom=ref_geom,
                                water_bodies_geom=lake_geom,
                                crs=crs)
    ref_ds = suhi.get_landsat_features_ds(landsat_tiles[0],
                                          **landsat_features_kws)
    datasets.append(ref_ds)
    for landsat_tile in landsat_tiles[1:]:
        ds = suhi.get_landsat_features_ds(landsat_tile,
                                          ref_ds=ref_ds,
                                          **landsat_features_kws)
        datasets.append(ds)

    agglom_landsat_ds = xr.concat(datasets, dim='time')
    if path.exists(dst_filepath):
        os.remove(dst_filepath)
    agglom_landsat_ds.to_netcdf(dst_filepath)
    logger.info("dumped landsat features dataset to %s", dst_filepath)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format=settings.DEFAULT_LOG_FMT)

    main()
