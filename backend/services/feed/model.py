"""The relevance model: an L2-regularised logistic regression in numpy.

Inputs are the unit embeddings of the shared bge-small model (384 dimensions, nothing
standardised), a bias is added. Training data: the user's positives and negatives, plus a
random sample of stored candidates as extra negatives (Scholar Inbox, Flicke et al. 2025).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger(__name__)

MIN_POSITIVES = 10          # below this: rank by similarity instead of a classifier
EVAL_MIN_POSITIVES = 30     # from here on a held-out AUC is reported
HOLD_OUT = 0.2
KEPT_WEIGHT = 0.3            # a paper the user added or put in a project, without any rating
RANDOM_NEGATIVES_MAX = 5000
RANDOM_NEGATIVE_SHARE = 1.0  # S: the random negatives together weigh S x the positives
DEFAULT_C = 1.0
FIT_MAX_ROWS = 6000          # larger training sets are fitted in the background
MODEL_MAX_AGE = 24 * 3600

# ── signals of the library ────────────────────────────────────────────────────


def library_label(rating, bookmarked, status, highlights, kept: bool = False) -> tuple[int, float] | None:
    """(label, weight) a library paper gives, or None when it says nothing.

    rating >= 4 or bookmarked: positive 1.0. rating <= 2: negative 1.0. A paper that was read
    and has highlights, or has rating 3 together with one of those, is a weaker positive, 0.5.
    A bookmark outranks a low rating: the user kept it. ``kept`` (the user added the paper or
    put it in a project) is the weakest positive, ``KEPT_WEIGHT``; the weight of a paper is the
    maximum over its signals, never the sum, and an explicit low rating still wins.
    """
    try:
        r = int(rating) if rating is not None else 0
    except (TypeError, ValueError):
        r = 0
    if bookmarked is True or r >= 4:
        return 1, 1.0
    if 1 <= r <= 2:
        return -1, 1.0
    read = status == "read"
    marked = (highlights or 0) > 0
    if (read and marked) or (r == 3 and (read or marked)):
        return 1, 0.5
    return (1, KEPT_WEIGHT) if kept else None


# ── training set ──────────────────────────────────────────────────────────────

@dataclass
class TrainingSet:
    pos: np.ndarray                      # (p, 384)
    pos_weight: np.ndarray               # (p,)
    pos_time: list[str]                  # when each positive was added (for the hold-out)
    neg: np.ndarray                      # explicit negatives (n, 384)
    neg_weight: np.ndarray
    random_neg: np.ndarray               # random candidates (m, 384)
    signature: tuple = ()

    @property
    def n_rows(self) -> int:
        return len(self.pos) + len(self.neg) + len(self.random_neg)


def stack(rows: list[np.ndarray], dim: int = 384) -> np.ndarray:
    return np.vstack(rows).astype(np.float32) if rows else np.zeros((0, dim), dtype=np.float32)


def design_matrix(ts: TrainingSet) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """X, y (0/1) and sample weights. Random negatives share S x the total positive weight."""
    pos_w = ts.pos_weight
    X = np.vstack([ts.pos, ts.neg, ts.random_neg])
    y = np.concatenate([np.ones(len(ts.pos)), np.zeros(len(ts.neg) + len(ts.random_neg))])
    rand_w = np.full(len(ts.random_neg), RANDOM_NEGATIVE_SHARE * float(pos_w.sum()) / max(1, len(ts.random_neg)))
    w = np.concatenate([pos_w, ts.neg_weight, rand_w])
    return X.astype(np.float64), y, w


# ── fitting ───────────────────────────────────────────────────────────────────

def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 0.5 * (1.0 + np.tanh(0.5 * z))


def fit_logreg(X: np.ndarray, y: np.ndarray, w: np.ndarray, C: float = DEFAULT_C,
               max_iter: int = 200) -> tuple[np.ndarray, float]:
    """Minimise sum_i w_i * logloss_i + ||theta||^2 / (2C); the bias is not penalised.
    L-BFGS from scipy when it can be imported, otherwise gradient descent with momentum."""
    n, d = X.shape

    def loss_grad(theta: np.ndarray) -> tuple[float, np.ndarray]:
        z = X @ theta[:d] + theta[d]
        # log(1 + e^z) - y z, stable
        loss = float(np.sum(w * (np.logaddexp(0.0, z) - y * z)) + 0.5 / C * theta[:d] @ theta[:d])
        r = w * (_sigmoid(z) - y)
        g = np.empty(d + 1)
        g[:d] = X.T @ r + theta[:d] / C
        g[d] = r.sum()
        return loss, g

    theta0 = np.zeros(d + 1)
    try:
        from scipy.optimize import minimize
    except Exception:  # noqa: BLE001 — no scipy: plain gradient descent
        minimize = None
    if minimize is not None:
        res = minimize(loss_grad, theta0, jac=True, method="L-BFGS-B", options={"maxiter": max_iter})
        theta = res.x
    else:
        theta, vel = theta0, np.zeros_like(theta0)
        lr = 1.0 / (float(w.sum()) * 0.5 + 1.0 / C)   # 1 / Lipschitz bound (unit rows plus bias)
        for _ in range(max_iter * 5):
            _, g = loss_grad(theta + 0.9 * vel)
            vel = 0.9 * vel - lr * g
            theta = theta + vel
    return theta[:d].astype(np.float32), float(theta[d])


def predict(theta: np.ndarray, bias: float, X: np.ndarray) -> np.ndarray:
    return _sigmoid(X.astype(np.float64) @ theta.astype(np.float64) + bias)


def auc(pos_scores: np.ndarray, neg_scores: np.ndarray) -> float | None:
    """ROC AUC: the chance that a random positive scores above a random negative (ties half)."""
    if len(pos_scores) == 0 or len(neg_scores) == 0:
        return None
    neg = np.sort(neg_scores)
    below = np.searchsorted(neg, pos_scores, side="left")
    equal = np.searchsorted(neg, pos_scores, side="right") - below
    return float((below.sum() + 0.5 * equal.sum()) / (len(pos_scores) * len(neg)))


@dataclass
class Model:
    theta: np.ndarray
    bias: float
    signature: tuple
    fitted_at: float = field(default_factory=time.time)
    quality: dict | None = None
    positives: int = 0

    def score(self, X: np.ndarray) -> np.ndarray:
        return predict(self.theta, self.bias, X)


def fit_model(ts: TrainingSet, C: float = DEFAULT_C) -> Model:
    """Fit on the whole training set; with enough positives also measure how well a model
    trained without the 20 % most recently added positives ranks them above random candidates."""
    X, y, w = design_matrix(ts)
    theta, bias = fit_logreg(X, y, w, C)
    model = Model(theta, bias, ts.signature, positives=len(ts.pos))
    if len(ts.pos) >= EVAL_MIN_POSITIVES and len(ts.random_neg) >= 10:
        order = np.argsort(np.array(ts.pos_time, dtype=object), kind="stable")
        k = max(1, int(round(HOLD_OUT * len(order))))
        held, kept = order[-k:], order[:-k]
        sub = TrainingSet(ts.pos[kept], ts.pos_weight[kept], [ts.pos_time[i] for i in kept],
                          ts.neg, ts.neg_weight, ts.random_neg)
        Xs, ys, ws = design_matrix(sub)
        th, b = fit_logreg(Xs, ys, ws, C)
        value = auc(predict(th, b, ts.pos[held]), predict(th, b, ts.random_neg))
        if value is not None:
            model.quality = {"auc": round(value, 3), "positives": len(ts.pos), "held_out": int(k)}
    return model


def similarity_scores(positives: np.ndarray, X: np.ndarray) -> np.ndarray:
    """Cold start: the largest cosine similarity of each row of X to any positive."""
    if len(positives) == 0 or len(X) == 0:
        return np.zeros(len(X), dtype=np.float32)
    return (X @ positives.T).max(axis=1)
