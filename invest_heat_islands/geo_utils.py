import numpy as np
import salem  # noqa: F401
import xarray as xr
from rasterio import transform

# constants useful for geo-operations
CRS = 'epsg:2056'


def align_ds(ds, ref_ds, interp='linear'):
    if ds.name is None:
        ds.name = ''  # salem needs some name to align the ds/da
    return ref_ds.salem.transform(ds, interp=interp)


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


def _calculate_transform(geom, dst_res):
    west, south, east, north = geom.bounds
    dst_height, dst_width = tuple(
        int(np.ceil(diff / dst_res)) for diff in [north - south, east - west])
    dst_transform = transform.from_origin(west, north, dst_res, dst_res)

    return dst_transform, (dst_height, dst_width)


def get_ref_da(ref_geom, dst_res, dst_fill=0, dst_crs=None):
    if dst_crs is None:
        dst_crs = CRS
    ref_transform, (ref_height,
                    ref_width) = _calculate_transform(ref_geom, dst_res)
    rows = np.arange(ref_height)
    cols = np.arange(ref_width)
    xs, _ = transform.xy(ref_transform, cols, cols)
    _, ys = transform.xy(ref_transform, rows, rows)
    ref_da = xr.DataArray(dst_fill, dims=('y', 'x'), coords={'y': ys, 'x': xs})
    ref_da.attrs['pyproj_srs'] = dst_crs

    return ref_da
