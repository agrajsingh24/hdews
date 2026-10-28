"""Tests for the evaluation harness mechanics (split, metrics, guards).

The fixture below is generated in-test only to exercise the code paths; its
numbers say nothing about real-world model performance and are never recorded
outside the throwaway test database.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ml import evaluate as ev  # noqa: E402


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


def test_harness_temporal_split_and_metrics(tmp_path):
    path = tmp_path / "d.csv"
    fixture_df().to_csv(path, index=False)
    df = ev.load(path, ev.DEFAULT_FEATURES)
    out = ev.evaluate(df, ev.DEFAULT_FEATURES, "2024-01-01", None)
    assert out["split_strategy"] == "temporal hold-out"
    assert out["train_period"].split(" to ")[1] < "2024-01-01" <= out["test_period"].split(" to ")[0]
    for m in out["results"].values():
        assert {"precision", "recall", "pr_auc", "false_alarm_rate", "missed_event_rate", "median_lead_time_h"} <= set(m)
        assert 0 <= m["pr_auc"] <= 1


def test_geographic_holdout():
    df = fixture_df()
    df["window_end"] = pd.to_datetime(df["window_end"], utc=True)
    df["event_onset"] = pd.to_datetime(df["event_onset"], utc=True, errors="coerce")
    out = ev.evaluate(df, ev.DEFAULT_FEATURES, "2024-01-01", ["south"])
    assert out["regions"] == ["south"] and "geographic" in out["split_strategy"]


def test_synthetic_labels_are_refused(tmp_path):
    path = tmp_path / "s.csv"
    fixture_df(label_source="synthetic demo").to_csv(path, index=False)
    with pytest.raises(ev.DatasetError):
        ev.load(path, ev.DEFAULT_FEATURES)


def test_missing_columns_rejected(tmp_path):
    path = tmp_path / "m.csv"
    fixture_df().drop(columns=["rain_24h_mm"]).to_csv(path, index=False)
    with pytest.raises(ev.DatasetError):
        ev.load(path, ev.DEFAULT_FEATURES)
    assert ev.main(["--dataset", str(path), "--dataset-name", "x", "--dataset-version", "1", "--test-from", "2024-01-01"]) == 2
