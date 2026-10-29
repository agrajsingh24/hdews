"""Tests for the evaluation harness mechanics (split, metrics, guards).

The fixture below is generated in-test only to exercise the code paths; its
numbers say nothing about real-world model performance and are never recorded
outside the throwaway test database.
"""
import sys
from pathlib import Path

import os

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.services.risk_engine import MLModelInterface  # noqa: E402

# The ML evaluation harness is an optional offline tool (numpy/pandas/scikit-learn); the backend never imports
# it. Some machines cannot load these compiled packages, e.g. Windows Smart App Control / WDAC refusing
# pandas' unsigned extension ("DLL load failed while importing nattype: An Application Control policy has
# blocked this file", OS error 4551). A module-level ImportError used to abort collection of the WHOLE suite.
# Here the module is skipped with the reason shown; CI sets HDEWS_REQUIRE_ML=1 so a broken install fails loudly.
try:
    import numpy as np
    import pandas as pd
    from ml import evaluate as ev
except ImportError as exc:
    if os.environ.get("HDEWS_REQUIRE_ML") == "1":
        raise
    pytest.skip(f"ML evaluation stack unavailable ({exc}). The backend does not depend on it; "
                "set HDEWS_REQUIRE_ML=1 to treat this as an error.", allow_module_level=True)


def fixture_df(label_source="unit-test fixture"):
    rng = np.random.default_rng(1)
    rows = []
    times = pd.date_range("2022-06-01", "2024-09-30", freq="7D", tz="UTC")
    for i, t in enumerate(times):
        for region in ("north", "south"):
            event = int(i % 9 == 0)
            rain = rng.gamma(2, 10) + (80 if event else 0)
            rows.append({"site_id": f"S-{region}", "region": region, "window_end": t.isoformat(), "label": event,
                         "label_source": label_source, "event_id": f"E{i}-{region}" if event else "",
                         "event_onset": (t + pd.Timedelta(hours=6)).isoformat() if event else "",
                         "rain_1h_mm": rain / 10, "rain_3h_mm": rain / 4, "rain_24h_mm": rain,
                         "soil_moisture_pct": 25 + rng.normal() + (12 if event else 0), "displacement_24h_mm": abs(rng.normal(0.3, 0.2)),
                         "river_level_m": 2 + rng.normal(0, .2), "river_rise_1h_m": rng.normal(0, .05)})
    return pd.DataFrame(rows)


def write(tmp_path, df, name="d.csv"):
    p = tmp_path / name
    df.to_csv(p, index=False)
    return p


def test_harness_temporal_split_and_metrics(tmp_path):
    df = ev.load(write(tmp_path, fixture_df()), ev.DEFAULT_FEATURES)
    out = ev.evaluate(df, ev.DEFAULT_FEATURES, "2024-01-01", None)
    assert out["split_strategy"] == "temporal hold-out"
    assert out["train_period"].split(" to ")[1] < "2024-01-01" <= out["test_period"].split(" to ")[0]
    for m in out["results"].values():
        assert {"precision", "recall", "pr_auc", "false_alarm_rate", "missed_event_rate", "median_lead_time_h"} <= set(m)
        assert 0 <= m["pr_auc"] <= 1


def test_geographic_holdout_excludes_test_regions_from_training():
    df = fixture_df()
    df["window_end"] = pd.to_datetime(df["window_end"], utc=True)
    df["event_onset"] = pd.to_datetime(df["event_onset"], utc=True, errors="coerce")
    train, test = ev.split(df, "2024-01-01", ["south"])
    assert set(train["region"]) == {"north"} and set(test["region"]) == {"south"}
    assert train["window_end"].max() < pd.Timestamp("2024-01-01", tz="UTC") <= test["window_end"].min()
    out = ev.evaluate(df, ev.DEFAULT_FEATURES, "2024-01-01", ["south"])
    assert out["regions"] == ["south"] and "geographic" in out["split_strategy"]


def test_metric_calculation_on_a_hand_checked_case():
    test = pd.DataFrame({"label": [1, 1, 0, 0, 0, 1], "event_id": ["A", "A", None, None, None, "B"],
                         "window_end": pd.to_datetime(["2024-01-01T00:00Z", "2024-01-01T06:00Z", "2024-01-02T00:00Z",
                                                       "2024-01-03T00:00Z", "2024-01-04T00:00Z", "2024-01-05T00:00Z"], utc=True),
                         "event_onset": pd.to_datetime(["2024-01-01T12:00Z", "2024-01-01T12:00Z", None, None, None,
                                                        "2024-01-05T03:00Z"], utc=True)})
    scores = np.array([0.9, 0.2, 0.7, 0.1, 0.1, 0.3])
    m = ev.metrics(test, scores, 0.5)
    assert m["precision"] == 0.5          # TP=1 (A at 00:00), FP=1
    assert m["recall"] == round(1 / 3, 3)  # 1 of 3 positive windows
    assert m["false_alarm_rate"] == round(1 / 3, 3)
    assert m["missed_event_rate"] == 0.5   # event B never alerted
    assert m["median_lead_time_h"] == 12.0


def test_reproducible_with_fixed_seed(tmp_path):
    df = ev.load(write(tmp_path, fixture_df()), ev.DEFAULT_FEATURES)
    a = ev.evaluate(df, ev.DEFAULT_FEATURES, "2024-01-01", None, seed=7)
    b = ev.evaluate(df, ev.DEFAULT_FEATURES, "2024-01-01", None, seed=7)
    assert a == b


@pytest.mark.parametrize("mutate,message", [
    (lambda df: df.assign(label_source="synthetic demo"), "synthetic"),
    (lambda df: df.drop(columns=["rain_24h_mm"]), "missing columns"),
    (lambda df: df.assign(label=df["label"].replace(1, 2)), "label must be"),
    (lambda df: df.assign(rain_1h_mm="lots"), "must be numeric"),
    (lambda df: df.assign(rain_1h_mm=np.inf), "infinite"),
    (lambda df: df.assign(window_end="not a date"), "ISO-8601"),
    (lambda df: df.assign(event_onset=df["window_end"]).assign(
        window_end=lambda d: (pd.to_datetime(d["window_end"]) + pd.Timedelta(hours=1)).astype(str)), "leakage"),
    (lambda df: df.assign(event_id=""), "event_id"),
    (lambda df: df.iloc[0:0], "no rows"),
])
def test_invalid_datasets_rejected(tmp_path, mutate, message):
    with pytest.raises(ev.DatasetError, match=message):
        ev.load(write(tmp_path, mutate(fixture_df())), ev.DEFAULT_FEATURES)


def test_missing_and_empty_files_rejected(tmp_path):
    """Previously an unhandled FileNotFoundError / EmptyDataError traceback."""
    with pytest.raises(ev.DatasetError, match="not found"):
        ev.load(tmp_path / "nope.csv", ev.DEFAULT_FEATURES)
    (tmp_path / "empty.csv").write_text("", encoding="utf-8")
    with pytest.raises(ev.DatasetError, match="empty"):
        ev.load(tmp_path / "empty.csv", ev.DEFAULT_FEATURES)
    assert ev.main(["--dataset", str(tmp_path / "nope.csv"), "--dataset-name", "x", "--dataset-version", "1",
                    "--test-from", "2024-01-01"]) == 2


def test_single_class_and_imbalanced_data(tmp_path):
    df = fixture_df().assign(label=0, event_id="", event_onset="")
    with pytest.raises(ev.DatasetError, match="positive"):
        ev.evaluate(ev.load(write(tmp_path, df), ev.DEFAULT_FEATURES), ev.DEFAULT_FEATURES, "2024-01-01", None)
    out = ev.evaluate(ev.load(write(tmp_path, fixture_df(), "i.csv"), ev.DEFAULT_FEATURES), ev.DEFAULT_FEATURES, "2024-01-01", None)
    assert out["results"]["random_forest"]["positive_rate_test"] < 0.2  # imbalance is reported, not hidden


def test_nan_features_are_imputed_not_fatal(tmp_path):
    df = fixture_df()
    df.loc[::3, "soil_moisture_pct"] = np.nan
    out = ev.evaluate(ev.load(write(tmp_path, df), ev.DEFAULT_FEATURES), ev.DEFAULT_FEATURES, "2024-01-01", None)
    assert out["results"]


def test_record_writes_versioned_runs_marked_uncalibrated(tmp_path, env):
    from app.db import Database
    from app.seed import seed
    url = f"sqlite:///{tmp_path}/r.db"
    seed(Database(url), quiet=True)
    p = write(tmp_path, fixture_df())
    assert ev.main(["--dataset", str(p), "--dataset-name", "fixture", "--dataset-version", "0",
                    "--test-from", "2024-01-01", "--record", "--database-url", url]) == 0
    with Database(url).tx() as tx:
        runs = tx.all("SELECT * FROM evaluation_runs")
    assert len(runs) == 2 and all(r["calibrated"] == 0 and r["model_version"].startswith("sklearn-") for r in runs)


def test_unvalidated_model_refused_and_validated_one_registered():
    class Unvalidated:
        name, version, validated = "rf", "0", False

    class Validated:
        name, version, validated = "rf", "1", True
    with pytest.raises(ValueError):
        MLModelInterface.register("landslide", Unvalidated())
    try:
        MLModelInterface.register("landslide", Validated())
        assert MLModelInterface.get("landslide").version == "1"
    finally:
        MLModelInterface.clear()
