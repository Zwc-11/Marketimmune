"""Tests for dashboard JSON API validators."""
from __future__ import annotations

import pytest

from dashboard.api_validators import parse_loop_run_request, parse_simulator_control_request


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({}, ("medium", 30)),
        ({"difficulty": "HARD", "limit": "12"}, ("hard", 12)),
    ],
)
def test_parse_loop_run_request_valid(payload, expected):
    parsed, error = parse_loop_run_request(payload)
    assert error == {}
    assert parsed == expected


@pytest.mark.parametrize(
    "payload",
    [
        {"difficulty": "extreme"},
        {"limit": 0},
        {"limit": 900},
        {"limit": "slow"},
        "not-a-dict",
    ],
)
def test_parse_loop_run_request_invalid(payload):
    parsed, error = parse_loop_run_request(payload)
    assert parsed is None
    assert "error" in error


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {},
            {
                "scenario": "spoofing_layering",
                "symbol": "BTCUSDT",
                "limit": 1440,
                "speed": 10,
                "replay_date": None,
            },
        ),
        (
            {
                "scenario": "quote_stuffing",
                "symbol": "btc-perp",
                "limit": "500",
                "speed": "25",
                "date": "2025-10-12",
            },
            {
                "scenario": "quote_stuffing",
                "symbol": "BTC-PERP",
                "limit": 500,
                "speed": 25,
                "replay_date": "2025-10-12",
            },
        ),
    ],
)
def test_parse_simulator_control_request_valid(payload, expected):
    parsed, error = parse_simulator_control_request(payload)
    assert error == {}
    assert parsed == expected


@pytest.mark.parametrize(
    "payload",
    [
        {"scenario": "unknown_playbook"},
        {"limit": 0},
        {"limit": 20_000},
        {"speed": 0},
        {"speed": 101},
        {"date": "Oct-12-2025"},
        {"symbol": ""},
        "not-a-dict",
    ],
)
def test_parse_simulator_control_request_invalid(payload):
    parsed, error = parse_simulator_control_request(payload)
    assert parsed is None
    assert "error" in error
    assert "code" in error
