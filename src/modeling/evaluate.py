"""
2.3 — Métricas de avaliação.

Fornece métricas num limiar dado (precision/recall/F1/FPR + matriz de confusão)
e métricas independentes de limiar (PR-AUC, ROC-AUC), além da escolha de limiar
por F1 feita SÓ no treino (evita leakage do teste).
"""
from __future__ import annotations

import numpy as np
from sklearn.metrics import (average_precision_score, confusion_matrix,
                             precision_recall_curve, roc_auc_score)


def metrics_at(y_true, y_prob, threshold: float) -> dict:
    y_pred = (y_prob >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) else 0.0)
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    return {"threshold": round(threshold, 4), "precision": round(precision, 4),
            "recall": round(recall, 4), "f1": round(f1, 4),
            "fpr": round(fpr, 5), "tp": int(tp), "fp": int(fp),
            "fn": int(fn), "tn": int(tn)}


def threshold_independent(y_true, y_prob) -> dict:
    return {"pr_auc": round(average_precision_score(y_true, y_prob), 4),
            "roc_auc": round(roc_auc_score(y_true, y_prob), 4)}


def best_f1_threshold(y_true, y_prob) -> float:
    """Limiar que maximiza F1 — calculado no TREINO e aplicado ao teste."""
    prec, rec, thr = precision_recall_curve(y_true, y_prob)
    f1 = np.where((prec + rec) > 0, 2 * prec * rec / (prec + rec), 0.0)
    # prec/rec têm 1 elemento a mais que thr
    best = int(np.argmax(f1[:-1])) if len(thr) else 0
    return float(thr[best]) if len(thr) else 0.5
