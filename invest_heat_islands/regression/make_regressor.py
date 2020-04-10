import logging

import click
import joblib as jl
import pandas as pd
from sklearn import ensemble, metrics

from invest_heat_islands import settings


@click.command()
@click.argument('regression_df_filepath', type=click.Path(exists=True))
@click.argument('dst_filepath', type=click.Path())
@click.option('--target-column', default='tair_station')
def main(regression_df_filepath, dst_filepath, target_column):
    logger = logging.getLogger(__name__)

    regression_df = pd.read_csv(regression_df_filepath, index_col=[0, 1])

    y = regression_df[target_column]
    X = regression_df.drop(target_column, axis=1)
    regr = ensemble.RandomForestRegressor().fit(X, y)
    logger.info("trained random forest regressor with R^2 %.4f and RMSE %.4f",
                regr.score(X, y),
                metrics.mean_squared_error(y, regr.predict(X), squared=False))

    # dump the chosen model
    jl.dump(regr, dst_filepath)
    logger.info("dumped air temperature regressor to %s", dst_filepath)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format=settings.DEFAULT_LOG_FMT)

    main()
