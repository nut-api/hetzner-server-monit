from pathlib import Path

import hetzner

PAGE = (Path(__file__).parent / "fixtures" / "order.html").read_text()


def test_parses_dedicated_servers_only():
    products = hetzner.parse(PAGE)
    assert len(products) == 45  # 49 boxes incl. featured duplicates; domain box excluded
    assert all(p.title for p in products.values())


def test_available_product():
    p = hetzner.parse(PAGE)["AX42-1"]
    assert p.available
    assert p.title == "Dedicated Server AX42-1"
    assert p.price == "€ 117.81"
    assert p.specs[1] == "64 GB DDR5 RAM"
    assert p.info_url == "https://www.hetzner.com/dedicated-rootserver/ax42?currency=EUR"
    assert p.order_url == "https://robot.hetzner.com/order/server?product=1719&category=rootserver"


def test_unavailable_product():
    products = hetzner.parse(PAGE)
    assert not products["AX41-1-LTD"].available
    assert not products["AX42-1-LTD"].available


def test_model_extraction_from_unusual_titles():
    products = hetzner.parse(PAGE)
    assert products["GEX45-1"].title == "Dedicated GPU-Server GEX45-1"
    assert products["DX154-1"].title == "Dell PowerEdge™ R470 DX154-1 (17. Generation)"


def test_garbage_page_yields_nothing():
    assert hetzner.parse("<html>maintenance</html>") == {}


def test_unrecognised_button_is_unknown():
    products = hetzner.parse(PAGE.replace("value='Not available'", "value='Ausverkauft'"))
    assert products["AX41-1-LTD"].available is None
    assert products["AX42-1"].available is True


def test_detects_region_settings():
    assert not hetzner.has_settings(PAGE)  # fixture is the default EUR / Germany page
    usd = PAGE.replace('value="USD" id="currency_USD"', 'value="USD" id="currency_USD" checked="checked"')
    assert not hetzner.has_settings(usd)
    assert hetzner.has_settings(usd.replace('<option value="US"', '<option value="US" selected="selected"'))
