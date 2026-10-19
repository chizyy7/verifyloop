# Currency rounding uses banker's rounding

money.py rounds monetary amounts to two decimal places for invoices. It uses the built-in round(), which applies banker's rounding and binary floating point, so 2.675 becomes 2.67 instead of the invoicing rule 2.68. Implement round_cents() using decimal arithmetic with ROUND_HALF_UP and return a float rounded to two decimal places.
