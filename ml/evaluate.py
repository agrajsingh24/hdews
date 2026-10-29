"""Evaluation harness for HDEWS hazard models.

Benchmarks simple models against labelled, time-aligned data with a temporal
(and optional geographic) hold-out, and reports precision, recall, PR-AUC,
false-alarm rate, missed-event rate and lead time. Results are written to the
`evaluation_runs` table only with --record.

No suitable labelled dataset exists in this repository, so this harness has NOT
been run on real data. It refuses rows whose label_source is "synthetic".

Input CSV schema (one row per site per assessment window):
  site_id, region, window_end (UTC ISO-8601), label (0/1: event within the forecast horizon),
  label_source (e.g. "GSI inventory v2024.1"), event_id (blank for negatives),
  event_onset (UTC ISO-8601, blank for negatives), then numeric feature columns
  named in --features (default: rain_1h_mm, rain_3h_mm, rain_24h_mm, soil_moisture_pct,
  displacement_24h_mm, river_level_m, river_rise_1h_m). Features must be computed only
  from data observed at or before window_end (no leakage).

Usage:
  python -m ml.evaluate --dataset labelled.csv --dataset-name NAME --dataset-version V \
      --test-from 2024-01-01 [--test-regions R1,R2] [--record]
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_score, recall_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

DEFAULT_FEATURES = ["rain_1h_mm", "rain_3h_mm", "rain_24h_mm", "soil_moisture_pct",
                    "displacement_24h_mm", "river_level_m", "river_rise_1h_m"]
REQUIRED = ["site_id", "region", "window_end", "label", "label_source"]


class DatasetError(ValueError):
    pass


def load(path: str | Path, features: list[str]) -> pd.DataFrame:
    try:
        df = pd.read_csv(path)
    except FileNotFoundError:
        raise DatasetError(f"dataset file not found: {path}")
    except pd.errors.EmptyDataError:
        raise DatasetError("dataset file is empty")
    except (pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise DatasetError(f"dataset is not a readable CSV: {exc}")
    if df.empty:
        raise DatasetError("dataset has no rows")
    missing = [c for c in REQUIRED + features if c not in df.columns]
    if missing:
        raise DatasetError(f"missing columns: {missing}")
    if df["label_source"].isna().any():
        raise DatasetError("every row needs a label_source")
    if df["label_source"].astype(str).str.lower().str.contains("synthetic").any():
        raise DatasetError("dataset contains synthetic labels; evaluation on synthetic data would be misleading")
    try:
        df["window_end"] = pd.to_datetime(df["window_end"], utc=True)
    except (ValueError, TypeError) as exc:
        raise DatasetError(f"window_end must be ISO-8601 timestamps: {exc}")
    if "event_onset" in df.columns:
        df["event_onset"] = pd.to_datetime(df["event_onset"], utc=True, errors="coerce")
    if df["label"].isna().any() or not set(df["label"].unique()) <= {0, 1}:
        raise DatasetError("label must be 0 or 1 on every row")
    df["label"] = df["label"].astype(int)
    for f in features:
        if not pd.api.types.is_numeric_dtype(df[f]):
            raise DatasetError(f"feature '{f}' must be numeric (blank cells are allowed for missing values)")
        if np.isinf(df[f].to_numpy(dtype=float)).any():
            raise DatasetError(f"feature '{f}' contains infinite values")
    if "event_id" in df.columns:
        if df.loc[df["label"] == 1, "event_id"].isna().any():
            raise DatasetError("every positive row needs an event_id when the event_id column is present")
    if "event_onset" in df.columns:
        # Leakage guard: a positive window must end before (or at) the event onset; otherwise its
        # features include measurements recorded during or after the event.
        pos = df[(df["label"] == 1) & df["event_onset"].notna()]
        late = pos[pos["window_end"] > pos["event_onset"]]
        if len(late):
            raise DatasetError(f"{len(late)} positive row(s) end after their event onset (leakage); "
                               "build features only from data observed before the event")
    return df.sort_values("window_end").reset_index(drop=True)


def split(df: pd.DataFrame, test_from: str, test_regions: list[str] | None):
    cut = pd.Timestamp(test_from, tz="UTC")
    test_mask = df["window_end"] >= cut
    if test_regions:
        test_mask &= df["region"].isin(test_regions)
        train_mask = (df["window_end"] < cut) & ~df["region"].isin(test_regions)
    else:
        train_mask = df["window_end"] < cut
    train, test = df[train_mask], df[test_mask]
    if train["label"].sum() < 1 or test["label"].sum() < 1:
        raise DatasetError("both train and test periods need at least one positive event")
    return train, test


def lead_times_h(test: pd.DataFrame, alerts: np.ndarray) -> list[float]:
    """Hours between the first alerted window and event onset, per detected event."""
    if "event_id" not in test.columns or "event_onset" not in test.columns:
        return []
    out = []
    t = test.assign(alert=alerts)
    for _, g in t[t["label"] == 1].groupby("event_id"):
        fired = g[g["alert"] == 1]
        onset = g["event_onset"].iloc[0]
        if len(fired) and pd.notna(onset):
            out.append(round((onset - fired["window_end"].min()).total_seconds() / 3600, 2))
    return out


def metrics(test: pd.DataFrame, scores: np.ndarray, threshold: float) -> dict:
    y = test["label"].to_numpy()
    pred = (scores >= threshold).astype(int)
    negatives = (y == 0).sum()
    events = test.loc[test["label"] == 1, "event_id"].nunique() if "event_id" in test.columns else int(y.sum())
    detected = (test.assign(p=pred)[test["label"] == 1].groupby("event_id")["p"].max().sum()
                if "event_id" in test.columns else int((pred & y).sum()))
    leads = lead_times_h(test, pred)
    return {
        "precision": round(float(precision_score(y, pred, zero_division=0)), 3),
        "recall": round(float(recall_score(y, pred, zero_division=0)), 3),
        "pr_auc": round(float(average_precision_score(y, scores)), 3),
        "false_alarm_rate": round(float(((pred == 1) & (y == 0)).sum() / negatives), 3) if negatives else None,
        "missed_event_rate": round(1 - detected / events, 3) if events else None,
        "median_lead_time_h": float(np.median(leads)) if leads else None,
        "decision_threshold": threshold,
        "positive_rate_test": round(float(y.mean()), 4),
    }


def evaluate(df: pd.DataFrame, features: list[str], test_from: str, test_regions: list[str] | None, seed: int = 0) -> dict:
    train, test = split(df, test_from, test_regions)
    models = {
        "logistic_regression": make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                             LogisticRegression(max_iter=1000, class_weight="balanced")),
        "random_forest": make_pipeline(SimpleImputer(strategy="median"),
                                       RandomForestClassifier(n_estimators=300, min_samples_leaf=3, class_weight="balanced",
                                                              random_state=seed)),
    }
    results = {}
    for name, model in models.items():
        model.fit(train[features], train["label"])
        scores = model.predict_proba(test[features])[:, 1]
        results[name] = metrics(test, scores, 0.5)
    return {
        "results": results,
        "train_period": f"{train['window_end'].min():%Y-%m-%d} to {train['window_end'].max():%Y-%m-%d}",
        "test_period": f"{test['window_end'].min():%Y-%m-%d} to {test['window_end'].max():%Y-%m-%d}",
        "regions": sorted(test["region"].unique().tolist()),
        "n_test_events": int(test.loc[test["label"] == 1, "event_id"].nunique() if "event_id" in test.columns else test["label"].sum()),
        "n_test_negatives": int((test["label"] == 0).sum()),
        "split_strategy": "temporal hold-out" + (" + geographic hold-out" if test_regions else ""),
    }


def record(db_url: str, out: dict, model: str, args) -> list[str]:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from app import clock
    from app.db import Database
    db = Database(db_url)
    ids = []
    with db.tx() as tx:
        for name, m in out["results"].items():
            run_id = "ev_" + uuid.uuid4().hex[:10]
            tx.insert("evaluation_runs", {
                "id": run_id, "created_at": clock.now_iso(), "model_name": name, "model_version": model,
                "dataset_name": args.dataset_name, "dataset_version": args.dataset_version, "dataset_kind": "real_labelled",
                "split_strategy": out["split_strategy"], "train_period": out["train_period"], "test_period": out["test_period"],
                "regions": json.dumps(out["regions"]), "n_test_events": out["n_test_events"],
                "n_test_negatives": out["n_test_negatives"], "metrics": json.dumps(m), "calibrated": 0,
                "limitations": args.limitations, "created_by": "ml.evaluate",
            })
            ids.append(run_id)
    return ids


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", required=True)
    p.add_argument("--dataset-name", required=True)
    p.add_argument("--dataset-version", required=True)
    p.add_argument("--test-from", required=True, help="UTC date; windows on/after it form the test set")
    p.add_argument("--test-regions", default="", help="comma-separated regions held out for geographic testing")
    p.add_argument("--features", default=",".join(DEFAULT_FEATURES))
    p.add_argument("--limitations", default="Uncalibrated scores; see dataset documentation for reporting biases.")
    p.add_argument("--record", action="store_true", help="write results to the HDEWS evaluation_runs table")
    p.add_argument("--database-url", default=None)
    args = p.parse_args(argv)
    features = [f for f in args.features.split(",") if f]
    try:
        df = load(args.dataset, features)
        out = evaluate(df, features, args.test_from, [r for r in args.test_regions.split(",") if r] or None)
    except DatasetError as exc:
        print(f"Dataset rejected: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2))
    if args.record:
        if not args.database_url:
            sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
            from app.config import load_settings
            args.database_url = load_settings().database_url
        print("Recorded runs:", record(args.database_url, out, "sklearn-" + __import__("sklearn").__version__, args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
