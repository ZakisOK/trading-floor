"""Tests for Redis Streams topology constants."""
from src.streams.topology import AUDIT, CONSUMER_GROUPS, MARKET_DATA, ORDERS


def test_stream_names_are_prefixed() -> None:
    assert MARKET_DATA.startswith("stream:")
    assert ORDERS.startswith("stream:")
    assert AUDIT.startswith("stream:")


def test_all_consumer_groups_present() -> None:
    assert "market_analysts" in CONSUMER_GROUPS
    assert "risk_managers" in CONSUMER_GROUPS
    assert "executors" in CONSUMER_GROUPS
    assert "audit_writer" in CONSUMER_GROUPS
