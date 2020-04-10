from os import environ, path

import fsspec
import numpy as np
import salem  # noqa: F401
import xarray as xr

# constants useful for geo-operations
CRS = 'epsg:2056'
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

# landsat features and spatial averaging
LANDSAT_RES = 30
LANDSAT_BASE_FEATURES = ['lst', 'ndwi']
AVERAGING_RADII = [0, 200, 400, 600, 800]


# geo xarray
def salem_da_from_singleband(raster_filepath, name=None):
    if name is None:
        name = ''  # salem needs a ds/da name (even empty)
    raster_da = xr.open_rasterio(raster_filepath).isel(band=0)
    raster_da.name = name
    raster_da.attrs['pyproj_srs'] = raster_da.crs

    return raster_da


def clip_ds_to_extent(ds,
                      shape=None,
                      geometry=None,
                      crs=None,
                      roi=True,
                      subset_kws=None,
                      roi_kws=None):
    if subset_kws is None:
        subset_kws = {}
    if roi_kws is None:
        roi_kws = {}

    if shape is not None:
        subset_kws['shape'] = shape
        if roi:
            roi_kws['shape'] = shape
    elif geometry is not None:
        subset_kws['geometry'] = geometry
        subset_kws['crs'] = crs
        if roi:
            roi_kws['geometry'] = geometry
            roi_kws['crs'] = crs
    subset_ds = ds.salem.subset(**subset_kws)
    if roi:
        return subset_ds.salem.roi(**roi_kws)
    return subset_ds


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
        ds = clip_ds_to_extent(preprocess_meteoswiss_ds(ds),
                               shape=shape,
                               geometry=geometry,
                               crs=crs,
                               roi=roi,
                               subset_kws=subset_kws,
                               roi_kws=roi_kws)
    elif preprocess:
        ds = preprocess_meteoswiss_ds(ds)

    return ds


# landsat features and spatial averaging
def _get_circular_kernel(radius):
    kernel_pixel_len = 2 * radius + 1

    y, x = np.ogrid[-radius:kernel_pixel_len -
                    radius, -radius:kernel_pixel_len - radius]
    mask = x * x + y * y <= radius * radius

    kernel = np.zeros((kernel_pixel_len, kernel_pixel_len), dtype=np.float32)
    kernel[mask] = 1

    return kernel


def get_kernel_dict(averaging_radii=None, res=LANDSAT_RES):
    if averaging_radii is None:
        averaging_radii = AVERAGING_RADII

    kernel_dict = {}
    # do not add a kernel for radius 0 (unnecessary convolution)
    if averaging_radii[0] == 0:
        radii = averaging_radii[1:]
    else:
        radii = averaging_radii
    for radius in radii:
        pixel_radius = int(radius / res)
        kernel_dict[pixel_radius] = _get_circular_kernel(pixel_radius)

    return kernel_dict
