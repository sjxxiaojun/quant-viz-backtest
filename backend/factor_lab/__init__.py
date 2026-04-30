__all__ = [
    "FactorLabConfig",
    "run_factor_lab",
    "load_latest_result",
    "calculate_ml_factor_ranker_signals",
    "calculate_ml_factor_filter_signals",
]


def __getattr__(name):
    if name in {"FactorLabConfig", "run_factor_lab", "load_latest_result"}:
        from . import pipeline

        return getattr(pipeline, name)
    if name in {"calculate_ml_factor_filter_signals", "calculate_ml_factor_ranker_signals"}:
        from . import strategy

        return getattr(strategy, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
