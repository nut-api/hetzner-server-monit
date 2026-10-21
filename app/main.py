"""Discord bot: watch Hetzner dedicated server models and alert when they come in stock."""

import logging
import os

import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks

import hetzner
from store import Change, Store

POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "60"))
STATE_PATH = os.environ.get("STATE_PATH", "state.json")
USER_AGENT = "hetzner-server-monit (+https://github.com/nut-api/hetzner-server-monit)"
UNKNOWN_AFTER_FAILURES = 10  # consecutive failed fetches before watched models turn unknown

log = logging.getLogger("monit")


class Monit(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.store = Store(STATE_PATH)
        self.products: dict[str, hetzner.Product] = {}  # latest scrape
        self.session: aiohttp.ClientSession | None = None  # created in setup_hook (needs the loop)
        self.failures = 0  # consecutive failed fetches

    async def setup_hook(self) -> None:
        self.session = aiohttp.ClientSession(headers={"User-Agent": USER_AGENT})
        await self.tree.sync()
        self.poll.start()

    async def close(self) -> None:
        if self.session:
            await self.session.close()
        await super().close()

    @tasks.loop(seconds=POLL_SECONDS)
    async def poll(self) -> None:
        try:
            await self.check()
        except Exception:  # an escaped exception would stop the loop for good
            log.exception("poll failed")

    async def check(self) -> None:
        try:
            products = await hetzner.fetch(self.session)
            self.failures = 0
        except hetzner.UnreadablePage:
            self.failures = 0
            log.error("order page loaded but no servers could be read; layout changed?")
            products = {}
        except (aiohttp.ClientError, TimeoutError):
            self.failures += 1
            log.exception("fetching order page failed (%d in a row)", self.failures)
            if self.failures < UNKNOWN_AFTER_FAILURES:
                return  # keep last known state through short outages
            products = {}
        self.products = products
        for change in self.store.apply(products):
            try:
                channel = self.get_channel(change.channel_id) or await self.fetch_channel(change.channel_id)
                await channel.send(embed=alert_embed(change))
            except discord.DiscordException:
                log.exception("sending alert for %s failed", change.model)

    @poll.before_loop
    async def before_poll(self) -> None:
        await self.wait_until_ready()


GREEN, RED, GREY = 0x2ECC71, 0xE74C3C, 0x95A5A6


def icon(available: bool | None) -> str:
    return {True: "🟢", False: "🔴", None: "⚪"}[available]


def state(available: bool | None) -> str:
    return {True: "available", False: "not available", None: "unknown"}[available]


def product_embed(title: str, p: hetzner.Product) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        url=p.order_url if p.available else None,
        color={True: GREEN, False: RED, None: GREY}[p.available],
        description="\n".join(p.specs),
    )
    embed.add_field(name="Price", value=f"from {p.price} / month")
    if p.available:
        embed.add_field(name="Order", value=f"[Order {p.model}]({p.order_url})")
    if p.info_url:
        embed.add_field(name="Info", value=f"[{p.model} details]({p.info_url})")
    return embed


def alert_embed(change: Change) -> discord.Embed:
    if change.available:
        return product_embed(f"🟢 {change.model} is available", change.product)
    if change.available is None:
        return discord.Embed(
            title=f"⚪ {change.model} status unknown",
            url=hetzner.ORDER_URL,
            color=GREY,
            description="Can't read this server on Hetzner's order page — the page layout may have changed, "
            "the model was removed, or the page is unreachable. Monitoring continues.",
        )
    if change.was is None:
        return discord.Embed(title=f"🔴 {change.model} readable again — not available", color=RED)
    return discord.Embed(title=f"🔴 {change.model} sold out", color=RED)


client = Monit()


@client.tree.command(description="Watch a Hetzner server model; alerts go to this channel")
@app_commands.describe(model="Model name, e.g. AX42-1")
async def add(interaction: discord.Interaction, model: str) -> None:
    model = model.strip().upper()
    if not client.products:
        await interaction.response.send_message("Can't read Hetzner's order page right now, try again later.", ephemeral=True)
        return
    product = client.products.get(model)
    if product is None:
        await interaction.response.send_message(f"Unknown model `{model}`.", ephemeral=True)
        return
    client.store.add(interaction.channel_id, model, product.available)
    embed = product_embed(f"Watching {model} — {icon(product.available)} {state(product.available)}", product)
    embed.set_footer(text=product.title)
    await interaction.response.send_message(embed=embed)


@add.autocomplete("model")
async def add_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    current = current.upper()
    return [
        app_commands.Choice(name=f"{m} ({state(p.available)})", value=m)
        for m, p in sorted(client.products.items())
        if current in m
    ][:25]


@client.tree.command(description="Stop watching a server model")
@app_commands.describe(model="Model name, e.g. AX42-1")
async def remove(interaction: discord.Interaction, model: str) -> None:
    model = model.strip().upper()
    if client.store.remove(interaction.channel_id, model):
        await interaction.response.send_message(f"Stopped watching **{model}** in this channel.")
    else:
        await interaction.response.send_message(f"`{model}` is not watched in this channel.", ephemeral=True)


@remove.autocomplete("model")
async def remove_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    current = current.upper()
    return [app_commands.Choice(name=m, value=m) for m in client.store.watched(interaction.channel_id) if current in m][:25]


@client.tree.command(name="list", description="Show server models watched in this channel")
async def list_(interaction: discord.Interaction) -> None:
    watched = client.store.watched(interaction.channel_id)
    if not watched:
        await interaction.response.send_message("Nothing watched in this channel. Use `/add`.", ephemeral=True)
        return
    embed = discord.Embed(title="Watched servers", url=hetzner.ORDER_URL)
    for model in watched[:25]:  # Discord caps an embed at 25 fields
        p = client.products.get(model)
        if p:
            name = f"{icon(p.available)} {model} — {state(p.available)}"
            price = f"from {p.price} / month" + (f" · [Order]({p.order_url})" if p.available else "")
            value = "\n".join([*p.specs, price])
        else:
            name, value = f"⚪ {model} — unknown", "Not found on the order page."
        embed.add_field(name=name, value=value, inline=False)
    if len(watched) > 25:
        embed.set_footer(text=f"+{len(watched) - 25} more not shown")
    await interaction.response.send_message(embed=embed)


if __name__ == "__main__":
    discord.utils.setup_logging()
    client.run(os.environ["DISCORD_TOKEN"], log_handler=None)
