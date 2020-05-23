import json
import logging
import warnings

import click
import geopandas as gpd

from invest_heat_islands import geo_utils, settings
from invest_heat_islands.invest import utils


@click.command()
@click.argument('calibration_log_filepath', type=click.Path(exists=True))
@click.argument('agglom_extent_filepath', type=click.Path(exists=True))
@click.argument('agglom_lulc_filepath', type=click.Path(exists=True))
@click.argument('biophysical_table_filepath', type=click.Path(exists=True))
@click.argument('ref_et_filepath', type=click.Path(exists=True))
@click.argument('station_tair_filepath', type=click.Path(exists=True))
@click.argument('station_locations_filepath', type=click.Path(exists=True))
@click.argument('dst_filepath', type=click.Path())
@click.option('--dst-res', type=int, default=200)
def main(calibration_log_filepath, agglom_extent_filepath,
         agglom_lulc_filepath, biophysical_table_filepath, ref_et_filepath,
         station_tair_filepath, station_locations_filepath, dst_filepath,
         dst_res):
    logger = logging.getLogger(__name__)
    # disable InVEST's logging
    for module in ('natcap.invest.urban_cooling_model', 'natcap.invest.utils',
                   'pygeoprocessing.geoprocessing'):
        logging.getLogger(module).setLevel(logging.WARNING)
    # ignore all warnings
    warnings.filterwarnings('ignore')

    # Compute an air temperature array from the calibrated InVEST urban
    # cooling model
    # 0. Preprocess the inputs
    # get the agglomeration extent
    agglom_extent_gdf = gpd.read_file(agglom_extent_filepath)
    crs = agglom_extent_gdf.crs
    ref_geom = agglom_extent_gdf.loc[0]['geometry']

    # use the ref geometry to obtain the reference grid (data array) with the
    # target resolution
    ref_da = geo_utils.get_ref_da(ref_geom, dst_res, dst_fill=0, dst_crs=crs)

    with open(calibration_log_filepath) as src:
        model_params = json.load(src)['args']

    mw = utils.ModelWrapper(agglom_lulc_filepath,
                            biophysical_table_filepath,
                            ref_et_filepath,
                            agglom_extent_filepath,
                            station_tair_filepath,
                            station_locations_filepath,
                            model_params=model_params)
    T_ucm_da = mw.predict_T_da()
    T_ucm_da = ref_da.salem.transform(T_ucm_da, interp='linear')

    # 3. Crop the data array to the valid data region and dump it to a file
    T_ucm_da.salem.roi(geometry=ref_geom, crs=crs).to_netcdf(dst_filepath)
    logger.info("dumped simulated air temperature data array to %s",
                dst_filepath)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format=settings.DEFAULT_LOG_FMT)

    main()
