import asyncio

import aiohttp
import pytest

import hetzner
import main
from store import Store


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, embed):
        self.sent.append(embed.title)


@pytest.fixture
def bot(tmp_path, monkeypatch):
    channel = FakeChannel()
    monkeypatch.setattr(main.client, "store", Store(tmp_path / "state.json"))
    monkeypatch.setattr(main.client, "failures", 0)
    monkeypatch.setattr(main.client, "get_channel", lambda _id: channel)
    main.client.store.add(1, "AX42-1", False)
    return main.client, channel


def fetch_returning(result):
    async def fetch(_session):
        if isinstance(result, Exception):
            raise result
        return result

    return fetch


def product(available):
    return hetzner.Product("AX42-1", "Dedicated Server AX42-1", available, "€ 1.00", (), None, "1")


def test_short_outage_keeps_last_state(bot, monkeypatch):
    client, channel = bot
    monkeypatch.setattr(hetzner, "fetch", fetch_returning(aiohttp.ClientError()))
    for _ in range(main.UNKNOWN_AFTER_FAILURES - 1):
        asyncio.run(client.check())
    assert channel.sent == [] and client.store.last["AX42-1"] is False


def test_long_outage_turns_unknown_once(bot, monkeypatch):
    client, channel = bot
    monkeypatch.setattr(hetzner, "fetch", fetch_returning(TimeoutError()))
    for _ in range(main.UNKNOWN_AFTER_FAILURES + 3):
        asyncio.run(client.check())
    assert channel.sent == ["⚪ AX42-1 status unknown"]
    monkeypatch.setattr(hetzner, "fetch", fetch_returning({"AX42-1": product(False)}))
    asyncio.run(client.check())
    assert channel.sent[-1] == "🔴 AX42-1 readable again — not available"
    assert client.failures == 0


def test_unreadable_page_turns_unknown_immediately(bot, monkeypatch):
    client, channel = bot
    monkeypatch.setattr(hetzner, "fetch", fetch_returning(hetzner.UnreadablePage()))
    asyncio.run(client.check())
    assert channel.sent == ["⚪ AX42-1 status unknown"]


def test_available_alert(bot, monkeypatch):
    client, channel = bot
    monkeypatch.setattr(hetzner, "fetch", fetch_returning({"AX42-1": product(True)}))
    asyncio.run(client.check())
    assert channel.sent == ["🟢 AX42-1 is available"]


def test_poll_survives_unexpected_errors(bot, monkeypatch):
    client, _ = bot

    async def boom():
        raise OSError("disk full")

    monkeypatch.setattr(client, "check", boom)
    asyncio.run(client.poll.coro(client))  # must not raise
