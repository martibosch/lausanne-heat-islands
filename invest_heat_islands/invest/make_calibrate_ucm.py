import json
import logging
import tempfile
import warnings

import click
import dotenv

from invest_heat_islands import settings
from invest_heat_islands.invest import utils


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
@click.option('--stepsize', type=float, default=0.3)
@click.option('--accept-coeff', type=float, default=2)
@click.option('--num-iters', type=int, default=100)
def main(agglom_lulc_filepath, aoi_vector_filepath, biophysical_table_filepath,
         ref_et_filepath, station_locations_filepath, station_tair_filepath,
         dst_filepath, x0_tair_avg_radius, x0_green_area_cooling_dist,
         x0_w_shade, x0_w_albedo, x0_w_eti, stepsize, accept_coeff, num_iters):
    logger = logging.getLogger(__name__)
    # disable InVEST's logging
    for module in ('natcap.invest.urban_cooling_model', 'natcap.invest.utils',
                   'pygeoprocessing.geoprocessing'):
        logging.getLogger(module).setLevel(logging.WARNING)
    # ignore all warnings
    warnings.filterwarnings('ignore')

    # tmp_dir = tempfile.mkdtemp()
    with tempfile.TemporaryDirectory() as tmp_dir:
        # wrapper to calibrate the model (with simulated annealing)
        mw = utils.ModelWrapper(agglom_lulc_filepath,
                                biophysical_table_filepath,
                                ref_et_filepath,
                                aoi_vector_filepath,
                                station_tair_filepath,
                                station_locations_filepath,
                                workspace_dir=tmp_dir)
        # prepare initial solution for the calibration from the script args
        x0 = [
            x0_tair_avg_radius, x0_green_area_cooling_dist, x0_w_shade,
            x0_w_albedo, x0_w_eti
        ]
        # make it happen
        states, rmses = mw.calibrate(x0,
                                     stepsize=stepsize,
                                     accept_coeff=accept_coeff,
                                     num_iters=num_iters,
                                     print_func=logger.info)
    # # delete the tmp dir
    # shutil.rmtree(tmp_dir)

    # dump the best result
    with open(dst_filepath, 'w') as dst:
        json.dump(
            {
                'args': {
                    param_key: mw.base_args[param_key]
                    for param_key in utils.DEFAULT_MODEL_PARAMS
                },
                'states': states,
                'rmses': rmses
            }, dst)
    logger.info("dumped calibration log and best parameters to %s",
                dst_filepath)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format=settings.DEFAULT_LOG_FMT)

    # find .env automagically by walking up directories until it's found, then
    # load up the .env entries as environment variables
    dotenv.load_dotenv(dotenv.find_dotenv())

    main()
