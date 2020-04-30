import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
from matplotlib import colors
from shapely import geometry


def plot_pred_obs(comparison_df, r_sq=None):
    fig, ax = plt.subplots()
    sns.scatterplot(x='obs', y='pred', data=comparison_df, ax=ax)
    text_kws = dict(transform=ax.transAxes)
    # we could also use `np.sqrt(np.mean(comparison_df['err']**2))`
    rmse = np.sqrt(np.mean((comparison_df['pred'] - comparison_df['obs'])**2))
    if r_sq is None:
        rmse_y = 0.85
    else:
        rmse_y = 0.75
        ax.text(0.08, 0.85, f'$R^2 = {r_sq:.4}$', **text_kws)
    ax.text(0.08, rmse_y, f'$RMSE = {rmse:.4} \degree C$', **text_kws)
    ax.set_ylabel('$\hat{T}$')
    ax.set_xlabel('$T_{obs}$')

    return fig


def plot_err_elev_obs(comparison_df):
    figwidth, figheight = plt.rcParams['figure.figsize']
    fig, axes = plt.subplots(1, 2, figsize=(2 * figwidth, figheight))

    # rename to have a nicer legend, also use str formatting for the date
    # also creating a new data frame (after `rename` avoids reference issues
    df = comparison_df.rename(columns={'date': 'Date'})
    df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')

    ax_elev = axes[0]
    sns.scatterplot(x='elev',
                    y='err',
                    hue='Date',
                    data=df,
                    ax=ax_elev,
                    legend=False)
    ax_elev.set_xlabel('Elevation [m]')
    ax_elev.set_ylabel('$\hat{T} - T_{obs}$')

    ax_y = axes[1]
    sns.scatterplot(x='obs', y='err', hue='Date', data=df, ax=ax_y)
    ax_y.set_xlabel('$T_{obs}$')
    ax_y.set_ylabel('')
    ax_y.legend(loc='center right', bbox_to_anchor=(1.4, .5))

    for ax in axes:
        ax.axhline(color='gray', linestyle='--', linewidth=1)

    return fig


def plot_T_maps(T_da,
                station_location_df,
                num_cols=3,
                comparison_df=None,
                num_classes=9,
                **plot_kws):
    g = T_da.plot(
        x='x',
        y='y',
        col='time',
        col_wrap=num_cols,
        # cbar_kwargs={
        #     'shrink': .2,
        #     'pad': 0.02,
        # }
        add_colorbar=False,
        **plot_kws)

    # post-processing
    fig = g.fig
    flat_axes = g.axes.flatten()

    # prepare last axis for the legend
    last_ax = flat_axes[-1]
    last_ax.set_visible(True)
    last_ax.axis('off')

    if comparison_df is not None:
        err_gdf = gpd.GeoDataFrame(
            comparison_df[['err', 'date']],
            geometry=list(
                comparison_df['station'].map(lambda stn: geometry.Point(
                    *station_location_df.loc[stn][['x', 'y']]))))

        ceil = int(
            np.ceil(max(abs(err_gdf['err'].max()), abs(err_gdf['err'].min()))))
        classes = np.linspace(-ceil, ceil, num_classes)
        err_gdf['err_class'] = np.digitize(err_gdf['err'], classes) - 1

        palette = sns.color_palette('coolwarm', n_colors=num_classes - 1)
        cmap = colors.ListedColormap(palette)

        # set black edge color for markers
        plt.rcParams.update(**{'scatter.edgecolors': 'k'})

        # plot the stations
        for (_, date_gdf), ax in zip(err_gdf.groupby('date'), flat_axes):
            date_gdf.plot(column='err_class', ax=ax, cmap=cmap)
            # ax.set_xticks([])
            # ax.set_yticks([])
        # generate a legend and place it in the last (empty) axis
        for start, end, color in zip(classes, classes[1:], palette):
            last_ax.plot(0, 0, 'o', c=color, label=f'[{start}, {end})')
        last_ax.legend(loc='center',
                       facecolor='white',
                       title='Regression error $\hat{T} - T$ [$\degree$C]')
        fig.colorbar(g._mappables[-1],
                     ax=last_ax,
                     label='Map temperature $T$ [$\degree$C]',
                     shrink=.45)

    else:
        station_gser = gpd.GeoSeries(
            gpd.points_from_xy(station_location_df['x'],
                               station_location_df['y']))

        # invisibly plot the stations in each map axis just so that the axis
        # limits and aspect ratio are set correctly
        for ax in flat_axes[:-1]:
            station_gser.plot(ax=ax, alpha=0)

        fig.colorbar(g._mappables[-1],
                     ax=last_ax,
                     label='$\hat{T}_{sr} - \hat{T}_{ucm}$ [$\degree$C]',
                     orientation='horizontal',
                     fraction=.55,
                     shrink=.8)

    # g.add_colorbar()
    fig.subplots_adjust(hspace=-.5)
    # fig.savefig('../reports/figures/spatial-regression-maps.png')
    return g
