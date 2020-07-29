import datetime
import logging
from os import path

import click
import pandas as pd
import swiss_uhi_utils as suhi
from pylandsat import utils as pylandsat_utils

from lausanne_heat_islands import settings


@click.command()
@click.argument('landsat_tiles_filepath', type=click.Path(exists=True))
@click.argument('station_data_dir', type=click.Path(exists=True))
@click.argument('dst_filepath', type=click.Path())
@click.option('--hour', default=21)
def main(landsat_tiles_filepath, station_data_dir, dst_filepath, hour):
    logger = logging.getLogger(__name__)

    # # read calibration dates
    # calibration_dates = pd.to_datetime(
    #     pd.read_csv(calibration_dates_filepath, header=None)[0]).to_list()

    # # for each date, get the datetime for the hour for which we want to get
    # # the temperature
    # calibration_datetimes = [
    #     calibration_date + HOUR_TD for calibration_date in calibration_dates
    # ]
    # get landsat dates
    landsat_dates = [
        pylandsat_utils.meta_from_pid(landsat_tile)['acquisition_date']
        for landsat_tile in pd.read_csv(landsat_tiles_filepath, header=None)[0]
    ]

    # for each date, get the datetime for the hour for which we want to get
    # the temperature
    hour_td = datetime.timedelta(hours=hour)
    landsat_datetimes = [
        landsat_date + hour_td for landsat_date in landsat_dates
    ]

    # assemble a data frame of station temperature measurements
    dfs = []

    # 1. MeteoSwiss
    for tair_column in ['tre000s0', 'tre200s0']:
        dfs.append(
            suhi.df_from_meteoswiss_zip(
                path.join(station_data_dir,
                          f'meteoswiss-lausanne-{tair_column}.zip'),
                tair_column).loc[landsat_datetimes].reset_index().groupby(
                    'time').first())

    # 2. VaudAir
    vaudair_df = pd.read_excel(path.join(
        station_data_dir,
        'VaudAir_EnvoiTemp20180101-20200128_EPFL_20200129.xlsx'),
                               index_col=0)
    vaudair_df = vaudair_df.iloc[3:]
    vaudair_df.index = pd.to_datetime(vaudair_df.index)
    for column in vaudair_df.columns:
        vaudair_df[column] = pd.to_numeric(vaudair_df[column])

    dfs.append(vaudair_df.loc[landsat_datetimes])

    # 3. Agrometeo
    dfs.append(
        suhi.df_from_agrometeo(
            path.join(station_data_dir,
                      'agrometeo-tre200s0.csv')).loc[landsat_datetimes])

    # 4. WSL
    dfs.append(
        suhi.df_from_wsl(path.join(station_data_dir, 'WSLLAF.txt'),
                         'WSLLAF').loc[landsat_datetimes])

    # assemble the dataframe
    df = pd.concat(dfs, axis=1)
    # keep only the dates in the index
    df.index = pd.Series(df.index).dt.date
    # dump it (need to dump the index in this case)
    df.to_csv(dst_filepath)
    logger.info("dumped air temperature station measurements to %s",
                dst_filepath)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format=settings.DEFAULT_LOG_FMT)

    main()
