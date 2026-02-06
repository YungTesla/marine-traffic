"""Training script for XGBoost encounter risk classifier."""

import argparse
import logging
import json
from pathlib import Path

import numpy as np
import joblib
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.metrics import classification_report, confusion_matrix
from xgboost import XGBClassifier

from src.ml.data_extraction import extract_encounters
from src.ml.risk_classifier import prepare_data, FEATURE_COLUMNS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def train(
    db_path: str | None = None,
    n_folds: int = 5,
    save_path: str = "models/risk_xgboost.json",
):
    """Train risk classification model with stratified k-fold cross-validation."""

    # Extract data
    logger.info("Extracting encounter features...")
    df = extract_encounters(db_path)

    if df.empty or len(df) < 20:
        logger.error("Not enough encounters (%d). Need at least 20.", len(df))
        return

    X, y, le = prepare_data(df)
    logger.info("Dataset: %d encounters, %d features, classes: %s",
                len(X), X.shape[1], dict(zip(le.classes_, np.bincount(y))))

    # Cross-validated predictions for evaluation
    model = XGBClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.1,
        objective="multi:softmax",
        num_class=len(le.classes_),
        eval_metric="mlogloss",
        random_state=42,
    )

    skf = StratifiedKFold(n_splits=min(n_folds, min(np.bincount(y))), shuffle=True, random_state=42)
    y_pred = cross_val_predict(model, X, y, cv=skf)

    # Classification report
    report = classification_report(y, y_pred, target_names=le.classes_)
    logger.info("\n=== CLASSIFICATION REPORT (Cross-Validated) ===\n%s", report)

    # Confusion matrix
    cm = confusion_matrix(y, y_pred)
    logger.info("Confusion Matrix:\n%s", cm)

    # Train final model on all data
    model.fit(X, y)

    # Feature importance
    importances = dict(zip(FEATURE_COLUMNS, model.feature_importances_))
    sorted_imp = sorted(importances.items(), key=lambda x: x[1], reverse=True)
    logger.info("\n=== FEATURE IMPORTANCE ===")
    for feat, imp in sorted_imp:
        logger.info("  %s: %.4f", feat, imp)

    # SHAP analysis (optional, if shap is installed)
    try:
        import shap
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X)
        # Save SHAP summary plot
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(10, 8))
        shap.summary_plot(shap_values, X, feature_names=FEATURE_COLUMNS, show=False)
        shap_path = Path(save_path).parent / "shap_risk_summary.png"
        plt.savefig(shap_path, dpi=150, bbox_inches="tight")
        plt.close()
        logger.info("SHAP summary plot saved to %s", shap_path)
    except ImportError:
        logger.info("Install 'shap' for SHAP feature importance plots.")

    # Save model
    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    model.save_model(save_path)

    # Save label encoder mapping
    le_path = Path(save_path).with_suffix(".labels.json")
    with open(le_path, "w") as f:
        json.dump({"classes": list(le.classes_)}, f)

    logger.info("Model saved to %s", save_path)
    logger.info("Label mapping saved to %s", le_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train encounter risk classifier")
    parser.add_argument("--db", type=str, default=None, help="Path to SQLite database")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--save-path", type=str, default="models/risk_xgboost.json")
    args = parser.parse_args()

    train(db_path=args.db, n_folds=args.folds, save_path=args.save_path)
