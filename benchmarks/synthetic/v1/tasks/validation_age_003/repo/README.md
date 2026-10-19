# Age validation accepts impossible values

validation.py validates a user's age before persistence. It currently rejects ages above 150 but accepts negative ages, and it also accepts booleans because bool is a subclass of int. Fix validate_age() so it accepts integers in the inclusive range 0..150, rejects booleans with TypeError, and keeps raising ValueError for out-of-range numbers.
