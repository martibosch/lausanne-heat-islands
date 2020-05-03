from sklearn import metrics

METRIC_COLUMNS = ['R^2', 'MAE', 'RMSE']


def compute_model_perf(obs, pred):
    return [
        metrics.r2_score(obs, pred),
        metrics.mean_absolute_error(obs, pred),
        metrics.mean_squared_error(obs, pred, squared=False),
    ]
