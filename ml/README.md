# ML evaluation

* `evaluate.py` — benchmarks Logistic Regression and Random Forest on a labelled CSV with a **temporal** hold-out (`--test-from`) and optional **geographic** hold-out (`--test-regions`). Reports precision, recall, PR-AUC, false-alarm rate, missed-event rate and median lead time (when `event_id` and `event_onset` are provided). `--record` writes results to `evaluation_runs`, which the Model & evaluation page then displays.
* `model_cards/baseline-rules-v0.1.md` — card for the rules currently in use.

**Status: not run on real data.** No suitable labelled inventory is available in this repository. The harness refuses rows whose `label_source` contains "synthetic". Its tests (`backend/tests/test_ml_harness.py`) use an in-test fixture solely to check code paths.

Before recording a run: define labels with domain experts; build features only from data observed at or before each window end (no leakage); document reporting biases and class imbalance; compare against the baseline rules; do not show scores as probabilities unless calibration has been performed and evaluated.

Column schema: see the docstring at the top of `evaluate.py`.
