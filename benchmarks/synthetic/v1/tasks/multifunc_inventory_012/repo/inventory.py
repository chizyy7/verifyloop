"""Simple in-memory inventory."""


class Inventory:
    """Tracks stock per SKU."""

    def __init__(self):
        self._stock = {}

    def add(self, sku, quantity):
        """Add ``quantity`` units of ``sku``."""
        self._stock[sku] = self._stock.get(sku, 0) + quantity
        return self._stock[sku]

    def remove(self, sku, quantity):
        """Remove ``quantity`` units of ``sku``."""
        self._stock[sku] = self._stock.get(sku, 0) - quantity
        return self._stock[sku]

    def available(self, sku):
        """Return current stock for ``sku``."""
        return self._stock.get(sku, 0)
