"""Fetch and parse the anonymous Hetzner Robot order page."""

import html
import re
from dataclasses import dataclass

import logging

import aiohttp

ORDER_URL = "https://robot.hetzner.com/order"
# Region form on the order page: USD prices, US customer (0% VAT). Stored in the session cookie.
SETTINGS = {"culture": "en_GB", "currency": "USD", "country": "US"}

log = logging.getLogger(__name__)

_BOX = re.compile(r'<div id="(\d+)" class="box_product">')
_TITLE = re.compile(r'<td class="title">([^<]+)</td>')
_SPEC = re.compile(r"<li class='list'>(.*?)</li>")
_PRICE = re.compile(r'<span class="price price_small">([^<]+)</span>')
_INFO = re.compile(r'<a href="([^"]+)">more information')
_MODEL = re.compile(r"\b([A-Z]{1,4}\d+-\d+(?:-LTD)?)\b")
_CSRF = re.compile(r'name="_csrf_token" value="([0-9a-f]+)"')


@dataclass(frozen=True)
class Product:
    model: str  # e.g. "AX42-1-LTD"
    title: str
    available: bool | None  # None: button not recognised (layout changed?)
    price: str  # e.g. "€ 117.81" (monthly, "from")
    specs: tuple[str, ...]
    info_url: str | None
    product_id: str

    @property
    def order_url(self) -> str:
        # Same page the "Order product" button POSTs to; GET with these params works too.
        return f"https://robot.hetzner.com/order/server?product={self.product_id}&category=rootserver"


def parse(page: str) -> dict[str, Product]:
    """Return dedicated-server products keyed by upper-case model name."""
    products: dict[str, Product] = {}
    starts = list(_BOX.finditer(page))
    for i, m in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(page)
        box = page[m.start():end]
        if 'value="rootserver"' not in box:
            continue
        title_m = _TITLE.search(box)
        if not title_m:
            continue
        title = html.unescape(title_m.group(1)).strip()
        model_m = _MODEL.search(title)
        if not model_m:
            continue
        model = model_m.group(1)
        price_m = _PRICE.search(box)
        info_m = _INFO.search(box)
        products[model] = Product(
            model=model,
            title=title,
            available=_availability(box),
            price=html.unescape(price_m.group(1)).strip() if price_m else "?",
            specs=tuple(html.unescape(s).strip() for s in _SPEC.findall(box)),
            info_url=info_m.group(1) if info_m else None,
            product_id=m.group(1),
        )
    return products


def _availability(box: str) -> bool | None:
    if "value='Order product'" in box:
        return True
    if "value='Not available'" in box:
        return False
    return None


class UnreadablePage(Exception):
    """The order page loaded but no servers could be read from it."""


def has_settings(page: str) -> bool:
    return 'value="USD" id="currency_USD" checked' in page and '<option value="US" selected' in page


async def _text(request) -> str:
    async with request as resp:
        resp.raise_for_status()
        return await resp.text()


async def fetch(session: aiohttp.ClientSession) -> dict[str, Product]:
    timeout = aiohttp.ClientTimeout(total=30)
    page = await _text(session.get(ORDER_URL, timeout=timeout))
    if not has_settings(page):
        # New or expired session: submit the region form; its response is the order page in USD.
        csrf = _CSRF.search(page)
        if csrf:
            data = {**SETTINGS, "_csrf_token": csrf.group(1)}
            page = await _text(session.post(ORDER_URL, data=data, timeout=timeout))
        if not has_settings(page):
            log.warning("could not switch order page to USD/US; prices may include German VAT")
    products = parse(page)
    if not products:
        # Layout changed or we got a maintenance page; don't treat it as "everything sold out".
        raise UnreadablePage("no servers parsed from order page")
    return products
