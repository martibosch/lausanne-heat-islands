import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib import colors
from shapely import geometry
from sklearn import metrics

# PLOTS
# ugly hardcoded for the legend of the error classes in map `plot_T_maps`
ERR_CLASSES = [-5, -3, -1, 1, 3, 5]  # station markers
ERR_BOUNDARIES = [-12, -6, -2, 2, 6, 12]  # map pixels


def plot_pred_obs(comparison_df):
    fig, ax = plt.subplots()
    sns.scatterplot(x='obs', y='pred', data=comparison_df, ax=ax)
    text_kws = dict(transform=ax.transAxes)
    obs_ser, pred_ser = comparison_df['obs'], comparison_df['pred']
    r_sq = metrics.r2_score(obs_ser, pred_ser)
    mae = metrics.mean_absolute_error(obs_ser, pred_ser)
    rmse = metrics.mean_squared_error(obs_ser, pred_ser, squared=False)
    ax.text(0.06, 0.88, f'$R^2 = {r_sq:.4}$', **text_kws)
    ax.text(0.06, 0.80, f'$MAE = {mae:.4} \degree C$', **text_kws)
    ax.text(0.06, 0.72, f'$RMSE = {rmse:.4} \degree C$', **text_kws)
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
    df['err'] = df['pred'] - df['obs']

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
                err_classes=None,
                **plot_kws):
    g = T_da.rename({
        'time': 'date'
    }).plot(
        x='x',
        y='y',
        col='date',
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
            comparison_df['date'],
            geometry=list(
                comparison_df['station'].map(lambda stn: geometry.Point(
                    *station_location_df.loc[stn][['x', 'y']]))))
        err_gdf['err'] = comparison_df['pred'] - comparison_df['obs']

        if err_classes is None:
            err_classes = ERR_CLASSES
        err_gdf['err_class'] = np.digitize(err_gdf['err'], err_classes) - 1

        palette = sns.color_palette('coolwarm', n_colors=len(err_classes) - 1)
        cmap = colors.ListedColormap(palette)

        # set black edge color for markers
        plt.rcParams.update(**{'scatter.edgecolors': 'k'})

        # plot the stations
        for (_, date_gdf), ax in zip(err_gdf.groupby('date'), flat_axes):
            date_gdf.plot(column='err_class', ax=ax, cmap=cmap)
            # ax.set_xticks([])
            # ax.set_yticks([])
        # generate a legend and place it in the last (empty) axis
        for start, end, color in zip(err_classes, err_classes[1:], palette):
            last_ax.plot(0, 0, 'o', c=color, label=f'[{start}, {end})')
        last_ax.legend(
            loc='center',
            facecolor='white',
            title='Regression error $\hat{T} - T_{obs}$ [$\degree$C]')
        fig.colorbar(g._mappables[-1],
                     ax=last_ax,
                     label='Map temperature $\hat{T}$ [$\degree$C]',
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
                     shrink=.8,
                     boundaries=ERR_BOUNDARIES)

    # g.add_colorbar()
    fig.subplots_adjust(hspace=-.5)
    # fig.savefig('../reports/figures/spatial-regression-maps.png')
    return g


def plot_comparison_hists(T_diff_da, station_tair_df):
    # figwidth, figheight = plt.rcParams['figure.figsize']
    # fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(2 * figwidth, figheight))
    fig, ax = plt.subplots()

    # histograms by date
    # for date in T_diff_da['time']:
    #     sns.distplot(T_diff_da.sel(time=date),
    #                  label=pd.to_datetime(date.item()).strftime('%d-%m-%Y'),
    #                  ax=ax)
    sns.distplot(T_diff_da, ax=ax)
    ax.set_ylabel('$P \; (\hat{T}_{sr} - \hat{T}_{ucm})$')
    ax.set_xlabel('$\hat{T}_{sr} - \hat{T}_{ucm}$')
    # ax.legend(loc='center right', bbox_to_anchor=(1.4, .5))
    # axin2 = ax.inset_axes([.72, .75, .24, .2])

    # diff vs observed temperature in inset
    # [.04, .75, .24, .2]
    axin = ax.inset_axes([.72, .72, .24, .24])
    sns.scatterplot(
        x=station_tair_df.mean(axis=1),
        y=T_diff_da.mean(['x', 'y']),
        hue=pd.to_datetime(T_diff_da['time'].values).strftime('%d-%m-%Y'),
        # alpha=0.4,  # default for seaborn distplots
        # legend=False,
        ax=axin)
    axin.axhline(color='gray', linestyle='--', linewidth=1)
    axin.set_ylim([-3, 3])
    axin.set_yticks([-2, 0, 2])
    axin.set_ylabel('$\hat{\mu}$', rotation=0, verticalalignment='center')
    axin.set_xlabel('$T_{obs}$')
    # place the inset axis' legend outside the main axis
    handles, labels = axin.get_legend_handles_labels()
    ax.legend(handles, labels, loc='center right', bbox_to_anchor=(1.34, .5))
    axin.get_legend().remove()

    # # overall histogram in inset
    # axin2 = ax.inset_axes([.72, .75, .24, .2])
    # sns.distplot(T_diff_da, ax=axin2)
    # axin2.set_ylabel('')
    # axin2.set_yticks([])
    # axin2.set_xlabel('')

    return fig
