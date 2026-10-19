import pytest

from inventory import Inventory


def test_over_removal_rejected_and_state_unchanged():
    inv = Inventory()
    inv.add("widget", 3)
    with pytest.raises(ValueError):
        inv.remove("widget", 4)
    assert inv.available("widget") == 3


def test_zero_quantity_rejected():
    inv = Inventory()
    with pytest.raises(ValueError):
        inv.add("widget", 0)
    assert inv.available("widget") == 0


def test_negative_quantity_rejected():
    inv = Inventory()
    with pytest.raises(ValueError):
        inv.add("widget", -2)
    with pytest.raises(ValueError):
        inv.remove("widget", -1)


def test_unknown_sku_removal_rejected():
    inv = Inventory()
    with pytest.raises(ValueError):
        inv.remove("ghost", 1)
    assert inv.available("ghost") == 0


def test_exact_removal_allowed():
    inv = Inventory()
    inv.add("widget", 2)
    assert inv.remove("widget", 2) == 0
    assert inv.available("widget") == 0


def test_multiple_skus_independent():
    inv = Inventory()
    inv.add("a", 1)
    inv.add("b", 5)
    inv.remove("b", 4)
    assert inv.available("a") == 1
    assert inv.available("b") == 1
