import pytest

from beer.commands import (
    parse_command,
    ChatCommand,
    FireCommand,
    QuitCommand,
    CommandParseError,
)

def test_chat_basic():
    cmd = parse_command("CHAT Hello world")
    assert isinstance(cmd, ChatCommand)
    assert cmd.text == "Hello world"


def test_chat_whitespace_and_case():
    cmd = parse_command("  chat   hi there  ")
    assert isinstance(cmd, ChatCommand)
    assert cmd.text == "hi there"


def test_fire_valid_A1():
    cmd = parse_command("FIRE A1")
    assert isinstance(cmd, FireCommand)
    assert (cmd.row, cmd.col) == (0, 0)


def test_fire_valid_J10():
    cmd = parse_command("fire j10")
    assert isinstance(cmd, FireCommand)
    assert (cmd.row, cmd.col) == (9, 9)


def test_fire_invalid_coord():
    with pytest.raises(CommandParseError):
        parse_command("FIRE K1")


def test_fire_missing_arg():
    with pytest.raises(CommandParseError):
        parse_command("FIRE")


def test_quit():
    cmd = parse_command("QUIT")
    assert isinstance(cmd, QuitCommand)


def test_unknown_command():
    with pytest.raises(CommandParseError):
        parse_command("HELLO there")


def test_empty_line():
    with pytest.raises(CommandParseError):
        parse_command("    ")
