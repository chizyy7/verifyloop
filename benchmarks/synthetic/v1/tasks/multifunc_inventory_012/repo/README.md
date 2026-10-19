# Inventory allows negative stock and invalid quantities

inventory.py implements an Inventory class used by the order service. remove() subtracts without checking available stock, so stock can go negative; add() accepts zero and negative quantities; and remove() on an unknown SKU creates a negative entry. Fix the class so add() requires a positive integer quantity, remove() raises ValueError when stock is insufficient or the SKU is unknown, and failed operations leave the inventory unchanged.
