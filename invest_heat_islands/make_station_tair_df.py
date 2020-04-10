import datetime
import logging
import zipfile
from os import path

import click
import pandas as pd
from pylandsat import utils as pylandsat_utils

from invest_heat_islands import settings

DAY_TD = datetime.timedelta(1)

# def daily_df_from_meteoswiss_zip(zip_filepath, landsat_dates):
#     with zipfile.ZipFile(zip_filepath) as zf:
#         data_fn = next(
#             fn for fn in zf.namelist() if fn.endswith('_data.txt'))
#         df = pd.read_csv(zf.open(data_fn), **utils.METEOSWISS_CSV_KWS)
#     data_col = df.columns[-1]
#     df = df.drop(df[df['stn'] == 'stn'].index)
#     reshaped_df = df.pivot(index='time', columns='stn', values=data_col)
#     reshaped_df.index = pd.to_datetime(reshaped_df.index.astype(str))
#     # TODO: how to deal with NaNs?
#     if data_col == 'tre000s0':
#         day_dfs = []
#         for landsat_date in landsat_dates:
#             start_dt = datetime.datetime(*(int(s)
#                                            for s in landsat_date.split('-')))
#             day_df = reshaped_df[
#                 (reshaped_df.index >= start_dt)
#                 & (reshaped_df.index < start_dt + utils.DAY_TD)].copy()
#             for column in day_df.columns:
#                 day_df[column] = pd.to_numeric(day_df[column])
#             day_dfs.append(day_df.resample('D').mean())
#     else:  # data_col == 'tre200dx'
#         #
#         day_dfs = [
#             reshaped_df[reshaped_df.index == landsat_date]
#             for landsat_date in landsat_dates
#         ]
#     return pd.concat(day_dfs)


def _df_meteoswiss_zip(zip_filepath, tair_column, read_csv_kws=None):
    if read_csv_kws is None:
        read_csv_kws = {}
    if 'na_values' not in read_csv_kws:
        read_csv_kws['na_values'] = '-'
    with zipfile.ZipFile(zip_filepath) as zf:
        data_fn = next(fn for fn in zf.namelist() if fn.endswith('_data.txt'))
        # METEOSWISS_CSV_KWS = {'delim_whitespace': True, 'na_values': '-'}
        df = pd.read_csv(zf.open(data_fn), **read_csv_kws)

    df = df.drop(df[df['stn'] == 'stn'].index)
    reshaped_df = df.pivot(index='time', columns='stn', values=tair_column)
    reshaped_df.index = pd.to_datetime(reshaped_df.index.astype(str))

    return reshaped_df


def daily_df_from_meteoswiss_day_zip(zip_filepath,
                                     landsat_dates,
                                     tair_column='tre200d0'):
    df = _df_meteoswiss_zip(zip_filepath,
                            tair_column,
                            read_csv_kws={'sep': ';'})

    return pd.concat(
        [df[df.index == landsat_date] for landsat_date in landsat_dates])


def daily_df_from_meteoswiss_10min_zip(zip_filepath,
                                       landsat_dates,
                                       tair_column='tre000s0'):
    df = _df_meteoswiss_zip(zip_filepath,
                            tair_column,
                            read_csv_kws={'delim_whitespace': True})
    day_dfs = []
    for landsat_date in landsat_dates:
        # start_dt = datetime.datetime(*(int(s)
        #                                for s in landsat_date.split('-')))
        # day_df = df[(df.index >= start_dt)
        #             & (df.index < start_dt + DAY_TD)].copy()
        day_df = df[(df.index >= landsat_date)
                    & (df.index < landsat_date + DAY_TD)].copy()
        for column in day_df.columns:
            day_df[column] = pd.to_numeric(day_df[column])
        day_dfs.append(day_df.resample('D').mean())

    return pd.concat(day_dfs)


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

    # assemble a data frame of station temperature measurements
    daily_dfs = []

    # 1. MeteoSwiss

    # 1.1 Air temperature (10 min)
    daily_dfs.append(
        daily_df_from_meteoswiss_10min_zip(
            path.join(station_data_dir, 'meteoswiss-lausanne-tair-10min.zip'),
            landsat_dates))

    # 1.2 Air temperature (daily)
    for station_zip in ('meteoswiss-NABLAU-tair-day.zip',
                        'meteoswiss-PUY-tair-day.zip'):
        daily_dfs.append(
            daily_df_from_meteoswiss_day_zip(
                path.join(station_data_dir, station_zip), landsat_dates))

    # 2. VaudAir
    df = pd.read_excel(path.join(
        station_data_dir,
        'VaudAir_EnvoiTemp20180101-20200128_EPFL_20200129.xlsx'),
                       index_col=0)
    df = df.iloc[3:]
    df.index = pd.to_datetime(df.index)
    for column in df.columns:
        df[column] = pd.to_numeric(df[column])

    daily_df = df.resample('D').mean()
    daily_dfs.append(
        pd.concat([
            daily_df[daily_df.index == landsat_date]
            for landsat_date in landsat_dates
        ]))

    # 3. Agrometeo
    df = pd.read_csv(path.join(station_data_dir, 'agrometeo-tair-avg.csv'),
                     index_col=0,
                     sep=';',
                     skiprows=[1, 2])
    df.index = pd.to_datetime(df.index, format='%d.%m.%Y')

    daily_dfs.append(
        pd.concat(
            [df[df.index == landsat_date] for landsat_date in landsat_dates]))

    # 4. WSL
    df = pd.read_csv(path.join(station_data_dir, 'WSLLAF.txt'),
                     delim_whitespace=True)
    rename_dict = {
        'JAHR': 'year',
        'MO': 'month',
        'TG': 'day',
        'HH': 'hour',
        'MM': 'minute'
    }
    df.index = pd.to_datetime(df[list(
        rename_dict.keys())].rename(columns=rename_dict))
    df = df['91'].resample('D').mean().rename('WSLLAF')
    daily_dfs.append(
        pd.concat(
            [df[df.index == landsat_date] for landsat_date in landsat_dates]))

    # dump it (need to dump the index here)
    pd.concat(daily_dfs, axis=1).to_csv(dst_filepath)
    logger.info("dumped air temperature station measurements to %s",
                dst_filepath)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format=settings.DEFAULT_LOG_FMT)

    main()
