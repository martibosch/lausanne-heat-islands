import salem  # noqa: F401
import xarray as xr

# constants useful for geo-operations
CRS = 'epsg:2056'


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
