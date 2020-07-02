import datetime
import logging
import zipfile
from os import path

import click
import pandas as pd
from pylandsat import utils as pylandsat_utils

from lausanne_heat_islands import settings

HOUR_TD = datetime.timedelta(hours=21)


def daily_df_from_meteoswiss_zip(zip_filepath, landsat_datetimes, tair_column):
    with zipfile.ZipFile(zip_filepath) as zf:
        data_fn = next(fn for fn in zf.namelist() if fn.endswith('_data.txt'))
        # METEOSWISS_CSV_KWS = {'delim_whitespace': True, 'na_values': '-'}
        df = pd.read_csv(zf.open(data_fn),
                         delim_whitespace=True,
                         na_values='-')

    # pivot and set datetime index
    df = df.drop(df[df['stn'] == 'stn'].index)
    df = df.pivot(index='time', columns='stn', values=tair_column)
    df.index = pd.to_datetime(df.index.astype(str))

    # get only the values of interest
    return df.loc[landsat_datetimes].reset_index().groupby('time').first()


@click.command()
@click.argument('landsat_tiles_filepath', type=click.Path(exists=True))
@click.argument('station_data_dir', type=click.Path(exists=True))
@click.argument('dst_filepath', type=click.Path())
def main(landsat_tiles_filepath, station_data_dir, dst_filepath):
    logger = logging.getLogger(__name__)

    # get landsat dates
    landsat_dates = [
        pylandsat_utils.meta_from_pid(landsat_tile)['acquisition_date']
        for landsat_tile in pd.read_csv(landsat_tiles_filepath, header=None)[0]
    ]

    # for each date, get the datetime for the hour for which we want to get
    # the temperature
    landsat_datetimes = [
        landsat_date + HOUR_TD for landsat_date in landsat_dates
    ]

    # assemble a data frame of station temperature measurements
    dfs = []

    # 1. MeteoSwiss
    for tair_column in ['tre000s0', 'tre200s0']:
        dfs.append(
            daily_df_from_meteoswiss_zip(
                path.join(station_data_dir,
                          f'meteoswiss-lausanne-{tair_column}.zip'),
                landsat_datetimes, tair_column))

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
    agrometeo_df = pd.read_csv(path.join(station_data_dir,
                                         'agrometeo-tre200s0.csv'),
                               index_col=0,
                               sep=';',
                               na_values='?',
                               skiprows=[1, 2])
    agrometeo_df.index = pd.to_datetime(agrometeo_df.index,
                                        format='%d.%m.%Y %H:%M')

    dfs.append(agrometeo_df.loc[landsat_datetimes])

    # 4. WSL
    wsl_df = pd.read_csv(path.join(station_data_dir, 'WSLLAF.txt'),
                         delim_whitespace=True)
    rename_dict = {
        'JAHR': 'year',
        'MO': 'month',
        'TG': 'day',
        'HH': 'hour',
        'MM': 'minute'
    }
    wsl_df.index = pd.to_datetime(wsl_df[list(
        rename_dict.keys())].rename(columns=rename_dict))

    dfs.append(wsl_df['91'].rename('WSLLAF').loc[landsat_datetimes])

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
