from os import environ, path

import fsspec
import xarray as xr

from invest_heat_islands import geo_utils

# constants useful for geo-operations
METEOSWISS_CRS = 'epsg:21781'
DROP_DIMS = ['lon', 'lat', 'dummy', 'swiss_coordinates']
RENAME_DIMS_MAP = {'chx': 'x', 'chy': 'y'}

# we work with average temperatures
METEOSWISS_GRID_PRODUCT = 'TabsD'

# constants related to s3 remote file system
METEOSWISS_GRID_DATA_PREFIX = 'meteoswiss'
CACHE_STORAGE_DIR = path.join(
    path.dirname(path.dirname(path.abspath(__file__))),
    'data/.meteoswiss-cache')


# meteoswiss
def get_meteoswiss_fs():
    return fsspec.filesystem(
        # 'filecache',
        'simplecache',
        target_protocol='s3',
        target_options=dict(
            profile=environ.get('S3_PROFILE_NAME'),
            client_kwargs={'endpoint_url': environ.get('S3_ENDPOINT_URL')}),
        cache_storage=CACHE_STORAGE_DIR)


def preprocess_meteoswiss_ds(ds):
    # set crs attribute to dataset and all data variables individually
    ds.attrs['pyproj_srs'] = METEOSWISS_CRS
    for data_var in list(ds.data_vars):
        ds[data_var].attrs['pyproj_srs'] = METEOSWISS_CRS

    # drop unnecessary dimensions and rename the others so that salem can
    # understand the grid
    return ds.drop(DROP_DIMS).rename(RENAME_DIMS_MAP)


def open_meteoswiss_s3_ds(fs,
                          bucket_name,
                          year,
                          product,
                          open_kws=None,
                          shape=None,
                          geometry=None,
                          crs=None,
                          preprocess=False,
                          roi=True,
                          prefix=None,
                          subset_kws=None,
                          roi_kws=None):
    if prefix is None:
        prefix = METEOSWISS_GRID_DATA_PREFIX
    file_key = path.join(
        bucket_name, prefix, product,
        f'{product}_ch01r.swisscors_{year}01010000_{year}12310000.nc')
    with fs.open(file_key) as file_obj:
        if open_kws is None:
            open_kws = {}
        ds = xr.open_dataset(file_obj, **open_kws)

    if shape is not None or geometry is not None:
        ds = geo_utils.clip_ds_to_extent(preprocess_meteoswiss_ds(ds),
                                         shape=shape,
                                         geometry=geometry,
                                         crs=crs,
                                         roi=roi,
                                         subset_kws=subset_kws,
                                         roi_kws=roi_kws)
    elif preprocess:
        ds = preprocess_meteoswiss_ds(ds)

    return ds
