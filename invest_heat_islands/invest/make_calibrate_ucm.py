import json
import logging
import tempfile
import warnings

import click
import dotenv
import invest_ucm_calibration as iuc

from invest_heat_islands import settings
from invest_heat_islands.invest import utils as invest_utils


@click.command()
@click.argument('agglom_lulc_filepath', type=click.Path(exists=True))
@click.argument('aoi_vector_filepath', type=click.Path(exists=True))
@click.argument('biophysical_table_filepath', type=click.Path(exists=True))
@click.argument('ref_et_filepath', type=click.Path(exists=True))
@click.argument('station_locations_filepath',
                type=click.Path(exists=True),
                required=False)
@click.argument('station_tair_filepath',
                type=click.Path(exists=True),
                required=False)
@click.argument('dst_filepath', type=click.Path())
@click.option('--x0-tair-avg-radius', type=float, default=500)
@click.option('--x0-green-area-cooling-dist', type=float, default=100)
@click.option('--x0-w-shade', type=float, default=0.6)
@click.option('--x0-w-albedo', type=float, default=0.2)
@click.option('--x0-w-eti', type=float, default=0.2)
@click.option('--metric', default='R2')
@click.option('--stepsize', type=float, default=0.3)
def main(agglom_lulc_filepath, aoi_vector_filepath, biophysical_table_filepath,
         ref_et_filepath, station_locations_filepath, station_tair_filepath,
         dst_filepath, x0_tair_avg_radius, x0_green_area_cooling_dist,
         x0_w_shade, x0_w_albedo, x0_w_eti, metric, stepsize):
    logger = logging.getLogger(__name__)
    # disable InVEST's logging
    for module in ('natcap.invest.urban_cooling_model', 'natcap.invest.utils',
                   'pygeoprocessing.geoprocessing', 'taskgraph.Task'):
        logging.getLogger(module).setLevel(logging.WARNING)
    # ignore all warnings
    warnings.filterwarnings('ignore')

    # tmp_dir = tempfile.mkdtemp()
    with tempfile.TemporaryDirectory() as workspace_dir:
        # dump ref et rasters
        ref_et_raster_filepath_dict = invest_utils.dump_ref_et_rasters(
            ref_et_filepath, workspace_dir)

        # prepare initial solution
        # model_params = {
        #     't_air_average_radius': x0_tair_avg_radius,
        #     'green_area_cooling_distance': x0_green_area_cooling_dist,
        #     'cc_weight_shade': x0_w_shade,
        #     'cc_weight_albedo': x0_w_albedo,
        #     'cc_weight_eti': x0_w_eti
        # }
        initial_solution = [
            x0_tair_avg_radius, x0_green_area_cooling_dist, x0_w_shade,
            x0_w_albedo, x0_w_eti
        ]

        # client = distributed.Client('tcp://165.22.198.117:8786')
        ucm_calibrator = iuc.UCMCalibrator(
            agglom_lulc_filepath,
            biophysical_table_filepath,
            aoi_vector_filepath,
            'factors',
            list(ref_et_raster_filepath_dict.values()),
            station_t_filepath=station_tair_filepath,
            station_locations_filepath=station_locations_filepath,
            workspace_dir=workspace_dir,
            # model_params=model_params,
            initial_solution=initial_solution,
            metric=metric,
            stepsize=stepsize)

        # make it happen
        solution, cost = ucm_calibrator.anneal()
    # # delete the tmp dir
    # shutil.rmtree(tmp_dir)

    # dump the best result
    with open(dst_filepath, 'w') as dst:
        json.dump(
            {
                param_key: param_value
                for param_key, param_value in zip(
                    iuc.settings.DEFAULT_MODEL_PARAMS, solution)
            }, dst)
    logger.info("dumped calibrated parameters (R^2=%f) to %s", 1 - cost,
                dst_filepath)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format=settings.DEFAULT_LOG_FMT)

    # find .env automagically by walking up directories until it's found, then
    # load up the .env entries as environment variables
    dotenv.load_dotenv(dotenv.find_dotenv())

    main()
