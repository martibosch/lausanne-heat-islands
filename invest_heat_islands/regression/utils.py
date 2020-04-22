import numpy as np

LANDSAT_RES = 30
LANDSAT_BASE_FEATURES = ['lst', 'ndwi']
AVERAGING_RADII = [0, 200, 400, 600, 800]
LANDSAT_FEATURES = [
    f'{base_feature}_{averaging_radius}'
    for averaging_radius in AVERAGING_RADII
    for base_feature in LANDSAT_BASE_FEATURES
]

TARGET = 'tair_station'
FEATURES = ['tair_grid'] + LANDSAT_FEATURES + ['elev']
REGRESSION_DF_COLUMNS = FEATURES + [TARGET]


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
