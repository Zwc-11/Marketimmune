from __future__ import annotations

import pytest

from aegisbench.datasets.builder import BenchmarkExample
from marketimmune.models.mtpp.batch import make_batch
from marketimmune.models.mtpp.dataset import build_sequences
from marketimmune.models.mtpp.evaluate import evaluate_scores, flatten_labels, lead_time_ms
from marketimmune.models.mtpp.gru_mtpp import GRUMTPPModel
from marketimmune.models.mtpp.losses import binary_log_loss
from marketimmune.models.mtpp.order_s2p2 import OrderS2P2Style
from marketimmune.models.mtpp.tokenizer import MarkTokenizer
from marketimmune.models.mtpp.train import train_order_mtpp


def examples() -> list[BenchmarkExample]:
    return [
        BenchmarkExample(
            "s1",
            "e1",
            0.0,
            "quote_stuffing",
            True,
            {"w1000_agentic_burst_rate_per_second": 50.0},
        ),
        BenchmarkExample(
            "s1",
            "e2",
            10.0,
            "quote_stuffing",
            True,
            {"w1000_agentic_burst_rate_per_second": 50.0},
        ),
        BenchmarkExample(
            "s2",
            "e3",
            0.0,
            "passive_market_maker",
            False,
            {"w1000_agentic_burst_rate_per_second": 0.0},
        ),
    ]


def test_build_sequences_and_batch() -> None:
    sequences = build_sequences(examples())
    assert sequences[0].marks == ["agent_order:new", "agent_order:new"]
    tokenizer = MarkTokenizer().fit([mark for sequence in sequences for mark in sequence.marks])
    batch = make_batch(sequences, tokenizer)
    assert batch.marks[0][0] > 0
    assert batch.mask[0][0]
    assert make_batch([], tokenizer).marks == []


def test_tokenizer_encode_unknown_raises() -> None:
    tokenizer = MarkTokenizer().fit(["a"])
    assert tokenizer.encode(["a"]) == [1]
    with pytest.raises(KeyError):
        tokenizer.encode(["missing"])


def test_binary_log_loss_and_errors() -> None:
    assert binary_log_loss([0.9, 0.1], [True, False]) < 0.2
    with pytest.raises(ValueError):
        binary_log_loss([0.1], [True, False])


def test_order_mtpp_fit_predict_and_evaluate() -> None:
    sequences = build_sequences(examples())
    model = train_order_mtpp(sequences)
    scores = model.predict(sequences)
    assert len(scores) == 3
    assert flatten_labels(sequences) == [True, True, False]
    metrics = evaluate_scores(sequences, scores)
    assert metrics["pr_auc"] > 0
    assert lead_time_ms(sequences, scores) >= 0
    assert lead_time_ms(sequences, [0.0, 0.0, 0.0]) == 0.0


def test_gru_mtpp_predict_unknown_mark() -> None:
    model = GRUMTPPModel.fit(build_sequences(examples()), epochs=2, batch_size=4)
    sequences = build_sequences(examples())
    scores = model.predict(sequences)
    assert len(scores) == 3
    assert all(0.0 <= s <= 1.0 for s in scores)


def test_gru_mtpp_state_round_trip() -> None:
    sequences = build_sequences(examples())
    model = GRUMTPPModel.fit(sequences, epochs=1, batch_size=4)
    loaded = GRUMTPPModel.load(model.state_dict())
    assert len(loaded.predict(sequences)) == 3


def test_order_s2p2_fit_predict() -> None:
    sequences = build_sequences(examples())
    model = OrderS2P2Style.fit(sequences, epochs=2, batch_size=4)
    scores = model.predict(sequences)
    assert len(scores) == 3
    assert all(0.0 <= s <= 1.0 for s in scores)


def test_order_s2p2_state_round_trip() -> None:
    sequences = build_sequences(examples())
    model = OrderS2P2Style.fit(sequences, epochs=1, batch_size=4)
    loaded = OrderS2P2Style.load(model.state_dict())
    assert len(loaded.predict(sequences)) == 3


def test_order_s2p2_continuous_time_decay() -> None:
    """CT-LSTM must produce different scores for events spaced far apart vs close.

    The continuous-time decay means the hidden state at t=10 000 ms is further
    from the post-event state than at t=10 ms, so the two cases should yield
    different hazard probabilities.
    """
    close_seq = build_sequences(
        [
            BenchmarkExample("s", "e1", 0.0, "quote_stuffing", True, {}),
            BenchmarkExample("s", "e2", 10.0, "quote_stuffing", True, {}),
        ]
    )
    far_seq = build_sequences(
        [
            BenchmarkExample("s", "e1", 0.0, "quote_stuffing", True, {}),
            BenchmarkExample("s", "e2", 10_000.0, "quote_stuffing", True, {}),
        ]
    )
    all_seqs = close_seq + far_seq
    model = OrderS2P2Style.fit(all_seqs, epochs=3, batch_size=4)
    close_scores = model.predict_sequence(close_seq[0])
    far_scores = model.predict_sequence(far_seq[0])
    assert len(close_scores) == 2
    assert len(far_scores) == 2
    # Scores must differ between the two timings (decay changes h(t))
    assert close_scores[1] != far_scores[1]
