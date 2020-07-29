import json
import logging
import warnings

import click
import geopandas as gpd
import swiss_uhi_utils as suhi

from lausanne_heat_islands import settings
from lausanne_heat_islands.invest import utils as invest_utils


@click.command()
@click.argument('calibrated_params_filepath', type=click.Path(exists=True))
@click.argument('agglom_extent_filepath', type=click.Path(exists=True))
@click.argument('agglom_lulc_filepath', type=click.Path(exists=True))
@click.argument('biophysical_table_filepath', type=click.Path(exists=True))
@click.argument('ref_et_filepath', type=click.Path(exists=True))
@click.argument('station_tair_filepath', type=click.Path(exists=True))
@click.argument('station_locations_filepath', type=click.Path(exists=True))
@click.argument('dst_filepath', type=click.Path())
@click.option('--dst-res', type=int, default=200)
def main(calibrated_params_filepath, agglom_extent_filepath,
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

    with open(calibrated_params_filepath) as src:
        model_params = json.load(src)

    # 1. Predict an air temperature data array
    ucm_wrapper = invest_utils.UCMWrapper(agglom_lulc_filepath,
                                          biophysical_table_filepath,
                                          ref_et_filepath,
                                          station_tair_filepath,
                                          station_locations_filepath,
                                          extra_ucm_args=model_params)
    T_ucm_da = ucm_wrapper.predict_t_da()

    # 2. Use the ref geometry to obtain the reference grid (data array) with
    #    the target resolution and align the predicted temperature data array
    #    to it
    ref_da = suhi.get_ref_da(ref_geom, dst_res, fill=0, crs=crs)
    T_ucm_da = ref_da.salem.transform(T_ucm_da, interp='linear')

    # 3. Crop the data array to the valid data region and dump it to a file
    T_ucm_da.salem.roi(geometry=ref_geom, crs=crs).to_netcdf(dst_filepath)
    logger.info("dumped simulated air temperature data array to %s",
                dst_filepath)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format=settings.DEFAULT_LOG_FMT)

    main()
