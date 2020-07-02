import logging
import tempfile
from os import path

import click
import geopandas as gpd
import numpy as np
import pandas as pd
import pylandsat
import salem
import xarray as xr
from rio_toa import brightness_temp

from lausanne_heat_islands import settings, utils

DATETIME_FMT = '%Y-%m-%d'

LANDSAT_FILES = ['B3.TIF', 'B4.TIF', 'B5.TIF', 'B10.TIF', 'MTL.txt']
LANDSAT_META_KEYS = ['RADIOMETRIC_RESCALING', 'TIRS_THERMAL_CONSTANTS']
LANDSAT_NODATA = 0

# TODO: the "parameters" should be customizable by means of arguments or a
# settings module
C = 0.005
ndvi_soil = 0.2
ndvi_veg = 0.5
eps_water = 0.991
eps_soil = 0.996
eps_veg = 0.973

lambd = 10.895e-9
rho = 1.439e-2  # 6.626e-34 * 2.998e8 / 1.38e-23


def compute_ndvi(landsat_ds):
    # ground emissivity (bands 4 and 5)
    b4_arr = landsat_ds['red'].values.astype(np.int32)
    b5_arr = landsat_ds['nir'].values.astype(np.int32)
    # nan values and zero division
    b4_plus_b5_arr = b5_arr + b4_arr

    return np.where(b4_plus_b5_arr == 0, LANDSAT_NODATA,
                    (b5_arr - b4_arr) / b4_plus_b5_arr)


def compute_ndwi(landsat_ds):
    # NDWI
    b3_arr = landsat_ds['green'].astype(np.int32)
    b5_arr = landsat_ds['nir'].astype(np.int32)
    b3_plus_b5_arr = b3_arr + b5_arr
    ndwi_arr = np.where(b3_plus_b5_arr == 0, LANDSAT_NODATA,
                        (b3_arr - b5_arr) / b3_plus_b5_arr)
    return ndwi_arr


def compute_lst(landsat_ds, mtl_dict, water_body_mask):
    # brightness temperature (band 10)
    radio_rescale = mtl_dict['RADIOMETRIC_RESCALING']
    thermal_constants = mtl_dict['TIRS_THERMAL_CONSTANTS']
    bt_arr = brightness_temp.brightness_temp(
        landsat_ds['tirs'].values, radio_rescale['RADIANCE_MULT_BAND_10'],
        radio_rescale['RADIANCE_ADD_BAND_10'],
        thermal_constants['K1_CONSTANT_BAND_10'],
        thermal_constants['K2_CONSTANT_BAND_10']) - 273.15

    ndvi_arr = compute_ndvi(landsat_ds)
    min_ndvi = ndvi_arr.min()
    pv_arr = np.square((ndvi_arr - min_ndvi) / (ndvi_arr.max() - min_ndvi))

    eps_arr = np.zeros_like(pv_arr)
    eps_arr[water_body_mask] = eps_water
    eps_arr[(ndvi_arr < ndvi_soil) & ~water_body_mask] = eps_soil
    mid_cond = (ndvi_arr >= ndvi_soil) & (ndvi_arr <
                                          ndvi_veg) & ~water_body_mask
    pv_mid_arr = pv_arr[mid_cond]
    eps_arr[mid_cond] = eps_veg * pv_mid_arr + eps_soil * (1 - pv_mid_arr) + C
    eps_arr[(ndvi_arr >= ndvi_veg) & ~water_body_mask] = eps_veg

    # land surface temperature (putting it all together)
    # lst_arr = bt_arr / (1 + (lambd * bt_arr / rho) * np.log(eps_arr))
    lst_arr = bt_arr / (1 + (lambd * bt_arr / rho) * np.log(eps_arr))
    # correct for potential infinities arising from divisions by zero
    # (landsat 8's nodata)
    # lst_arr[~landsat_mask] = landsat_meta['nodata']
    # return np.nan_to_num(lst_arr, LANDSAT_NODATA)
    return lst_arr


def get_landsat_features_ds(landsat_tile,
                            ref_ds=None,
                            ref_geom=None,
                            lake_geom=None,
                            crs=None,
                            roi=False,
                            subset_kws=None,
                            roi_kws=None):
    product = pylandsat.Product(landsat_tile)

    with tempfile.TemporaryDirectory() as tmp_dir:
        product.download(tmp_dir, files=LANDSAT_FILES)

        landsat_tile_dir = path.join(tmp_dir, landsat_tile)

        scene = pylandsat.Scene(landsat_tile_dir)
        bands = scene.available_bands()
        band_filepaths = [getattr(scene, band).fpath for band in bands]

        # create xarray dataset
        landsat_ds = xr.Dataset({
            band: salem.open_xr_dataset(band_filepath)['data']
            for band, band_filepath in zip(bands, band_filepaths)
        })
    # projection attributes need to be set before any geo-transformation
    proj_attrs = landsat_ds[bands[0]].attrs.copy()
    landsat_ds.attrs = proj_attrs

    # landsat metadata that will be used below
    mtl_dict = scene.mtl

    # crop/align to the reference extent
    if ref_ds is None:
        landsat_ds = utils.clip_ds_to_extent(landsat_ds,
                                             geometry=ref_geom,
                                             crs=crs,
                                             roi=roi,
                                             subset_kws=subset_kws,
                                             roi_kws=roi_kws)
    else:
        landsat_ds = ref_ds.salem.transform(landsat_ds, interp='linear')

    # the lake mask needs to be boolean for NumPy slicing to work properly
    lake_mask = landsat_ds.salem.grid.region_of_interest(geometry=lake_geom,
                                                         crs=crs).astype(bool)

    # LST
    lst_arr = compute_lst(landsat_ds, mtl_dict, lake_mask)
    # NDWI
    # get the maximum NDWI value on land and apply it to all water surfaces
    # TODO: erode lake extent mask so that we are sure to get the maximum NDWI
    # value on land
    ndwi_arr = compute_ndwi(landsat_ds)
    ndwi_arr[lake_mask] = ndwi_arr.max()

    # assemble the final dataset
    dims = ('y', 'x')
    coords = {
        'x': landsat_ds.salem.grid.x_coord,
        'y': landsat_ds.salem.grid.y_coord
    }
    landsat_features_ds = xr.Dataset(
        {
            'lst': xr.DataArray(lst_arr, dims=dims, coords=coords),
            'ndwi': xr.DataArray(ndwi_arr, dims=dims, coords=coords)
        },
        attrs=proj_attrs)
    # add the date
    landsat_features_ds = landsat_features_ds.assign_coords({
        'time':
        pd.to_datetime(mtl_dict['PRODUCT_METADATA']['DATE_ACQUIRED'])
    })

    return landsat_features_ds


@click.command()
@click.argument('landsat_tiles_filepath', type=click.Path(exists=True))
@click.argument('agglom_extent_filepath', type=click.Path(exists=True))
@click.argument('dst_filepath', type=click.Path())
@click.option('--buffer-dist', default=2000)
def main(landsat_tiles_filepath, agglom_extent_filepath, dst_filepath,
         buffer_dist):
    logger = logging.getLogger(__name__)

    # read list of landsat tiles (product ids) to process
    landsat_tiles = pd.read_csv(landsat_tiles_filepath, header=None)[0]

    # get the agglomeration and lake extents
    agglom_extent_gdf = gpd.read_file(agglom_extent_filepath)
    crs = agglom_extent_gdf.crs
    ref_geom = agglom_extent_gdf.loc[0]['geometry'].buffer(buffer_dist)
    lake_geom = agglom_extent_gdf.loc[1]['geometry']

    # process the list of tiles
    datasets = []
    # use a head-tail pattern to get a reference dataset in the first
    # iteration and use it to align the datasets of further iterations
    ref_ds = get_landsat_features_ds(landsat_tiles[0],
                                     ref_geom=ref_geom,
                                     lake_geom=lake_geom,
                                     crs=crs)
    datasets.append(ref_ds)
    for landsat_tile in landsat_tiles[1:]:
        ds = get_landsat_features_ds(landsat_tile,
                                     ref_ds=ref_ds,
                                     lake_geom=lake_geom,
                                     crs=crs)
        datasets.append(ds)

    agglom_landsat_ds = xr.concat(datasets, dim='time')
    agglom_landsat_ds.to_netcdf(dst_filepath)
    logger.info("dumped landsat features dataset to %s", dst_filepath)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format=settings.DEFAULT_LOG_FMT)

    main()
