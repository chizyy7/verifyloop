import pytest

from inventory import Inventory


def test_add_and_read():
    inv = Inventory()
    assert inv.add("widget", 5) == 5
    assert inv.available("widget") == 5


def test_remove_reduces_stock():
    inv = Inventory()
    inv.add("widget", 5)
    assert inv.remove("widget", 2) == 3


def test_unknown_sku_is_zero():
    assert Inventory().available("nope") == 0


def test_over_removal_rejected():
    inv = Inventory()
    inv.add("widget", 3)
    with pytest.raises(ValueError):
        inv.remove("widget", 4)
    assert inv.available("widget") == 3
