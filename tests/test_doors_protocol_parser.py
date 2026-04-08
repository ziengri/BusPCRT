from __future__ import annotations

import pytest

from app.door.doors_protocol_parser import DoorsProtocolParser


def test_parse_valid_packet() -> None:
    parser = DoorsProtocolParser()
    parsed = parser.parse("!DOORS;1=1;2=0;3=1")
    assert parsed == {1: 1, 2: 0, 3: 1}


def test_parse_invalid_prefix() -> None:
    parser = DoorsProtocolParser()
    with pytest.raises(ValueError):
        parser.parse("DOORS;1=1")


def test_parse_empty_token_is_error() -> None:
    parser = DoorsProtocolParser()
    with pytest.raises(ValueError):
        parser.parse("!DOORS;1=1;;3=1")


def test_parse_duplicate_channel_last_wins() -> None:
    parser = DoorsProtocolParser()
    parsed = parser.parse("!DOORS;1=0;2=1;1=1")
    assert parsed == {1: 1, 2: 1}

