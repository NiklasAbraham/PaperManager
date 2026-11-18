"""The numpy logistic regression, the signals that feed it, and the cold start."""
from __future__ import annotations

import numpy as np
import pytest

from services.feed import model
from tests.feed_helpers import topic_vec


def cluster(topic: int, n: int, tag: str) -> np.ndarray:
    return np.vstack([topic_vec(topic, f"{tag}-{topic}-{i}") for i in range(n)])


def training_set(n_pos=60, n_random_per_topic=40, topics=range(8), pos_topic=0) -> model.TrainingSet:
    rnd = np.vstack([cluster(t, n_random_per_topic, "r") for t in topics])
    return model.TrainingSet(
        pos=cluster(pos_topic, n_pos, "p"), pos_weight=np.ones(n_pos), pos_time=[f"{i:05d}" for i in range(n_pos)],
        neg=np.zeros((0, 384), np.float32), neg_weight=np.zeros(0), random_neg=rnd, signature=("s",))


def test_classifier_ranks_unseen_in_cluster_above_out_of_cluster():
    m = model.fit_model(training_set())
    inside = m.score(cluster(0, 30, "held"))
    outside = m.score(np.vstack([cluster(t, 10, "held") for t in range(1, 8)]))
    assert model.auc(inside, outside) == 1.0
    assert inside.min() > outside.max()
    assert 0.0 <= outside.min() and inside.max() <= 1.0


def test_explicit_negative_pushes_its_cluster_down():
    ts = training_set(n_pos=40)
    # the user also likes topic 1 a little (weak positives) but explicitly rejects topic 2
    ts.pos = np.vstack([ts.pos, cluster(2, 20, "x")])
    ts.pos_weight = np.ones(60)
    ts.pos_time = [f"{i:05d}" for i in range(60)]
    base = model.fit_model(ts).score(cluster(2, 10, "t")).mean()
    ts2 = training_set(n_pos=40)
    ts2.neg, ts2.neg_weight = cluster(2, 40, "neg"), np.ones(40)
    rejected = model.fit_model(ts2).score(cluster(2, 10, "t")).mean()
    assert rejected < base and rejected < 0.1


def test_weights_matter():
    ts = training_set(n_pos=40)
    heavy = training_set(n_pos=40)
    heavy.pos_weight = np.full(40, 5.0)
    a = model.fit_model(ts).score(cluster(0, 10, "h")).mean()
    b = model.fit_model(heavy).score(cluster(0, 10, "h")).mean()
    assert b > a


def test_quality_auc_needs_thirty_positives_and_uses_the_most_recent_as_held_out():
    small = model.fit_model(training_set(n_pos=29))
    assert small.quality is None
    m = model.fit_model(training_set(n_pos=60))
    assert m.quality["positives"] == 60 and m.quality["held_out"] == 12
    assert m.quality["auc"] > 0.95


def test_fit_is_fast_enough_for_a_request():
    import time

    ts = training_set(n_pos=300, n_random_per_topic=600)         # 300 + 4800 rows
    t = time.time()
    model.fit_model(ts)
    assert time.time() - t < 5.0


def test_gradient_descent_fallback_matches_the_ranking(monkeypatch):
    import builtins

    real = builtins.__import__

    def no_scipy(name, *a, **k):
        if name.startswith("scipy"):
            raise ImportError("no scipy here")
        return real(name, *a, **k)

    with monkeypatch.context() as mp:
        mp.setattr(builtins, "__import__", no_scipy)
        m = model.fit_model(training_set(n_pos=40))
    inside = m.score(cluster(0, 20, "held"))
    outside = m.score(np.vstack([cluster(t, 5, "held") for t in range(1, 8)]))
    assert model.auc(inside, outside) > 0.99


def test_fit_logreg_recovers_a_separable_direction():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(400, 5))
    y = (X[:, 0] > 0).astype(float)
    theta, bias = model.fit_logreg(X, y, np.ones(400), C=10.0)
    assert theta[0] > 1.0 and np.abs(theta[1:]).max() < theta[0] / 2
    assert ((model.predict(theta, bias, X) > 0.5) == (y > 0.5)).mean() > 0.95


def test_auc_values():
    assert model.auc(np.array([3, 4]), np.array([1, 2])) == 1.0
    assert model.auc(np.array([1, 2]), np.array([3, 4])) == 0.0
    assert model.auc(np.array([1.0]), np.array([1.0])) == 0.5
    assert model.auc(np.array([]), np.array([1.0])) is None


@pytest.mark.parametrize("rating,bookmarked,status,highlights,expected", [
    (5, False, "unread", 0, (1, 1.0)),
    (4, None, None, None, (1, 1.0)),
    (None, True, "unread", 0, (1, 1.0)),
    (2, True, "read", 3, (1, 1.0)),            # a bookmark outranks a low rating
    (2, False, "read", 3, (-1, 1.0)),
    (1, False, None, 0, (-1, 1.0)),
    (3, False, "read", 0, (1, 0.5)),
    (3, False, "unread", 2, (1, 0.5)),
    (None, False, "read", 2, (1, 0.5)),
    (3, False, "unread", 0, None),
    (None, False, "read", 0, None),
    (None, False, "unread", 0, None),
    (0, False, None, 0, None),                 # a cleared rating
])
def test_library_label(rating, bookmarked, status, highlights, expected):
    assert model.library_label(rating, bookmarked, status, highlights) == expected


def test_random_negatives_weigh_s_times_the_positives():
    ts = training_set(n_pos=10, n_random_per_topic=5)
    X, y, w = model.design_matrix(ts)
    assert w[y == 1].sum() == pytest.approx(10.0)
    assert w[y == 0].sum() == pytest.approx(model.RANDOM_NEGATIVE_SHARE * 10.0)


def test_similarity_scores():
    pos = cluster(0, 3, "p")
    X = np.vstack([cluster(0, 2, "x"), cluster(5, 2, "x")])
    s = model.similarity_scores(pos, X)
    assert s[:2].min() > s[2:].max()
    assert model.similarity_scores(np.zeros((0, 384), np.float32), X).tolist() == [0.0] * 4
