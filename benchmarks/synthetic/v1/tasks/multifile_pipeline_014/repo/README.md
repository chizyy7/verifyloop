# Cleaning pipeline drops rows before stripping whitespace

The data pipeline spans two modules. transforms.py provides strip_whitespace() and drop_empty(), while pipeline.py composes them in clean(). The stages are applied in the wrong order: drop_empty() runs before whitespace is stripped, so rows containing only spaces survive as 'non-empty', and the later strip leaves them blank. Fix pipeline.clean() so whitespace-only rows are removed, without changing either function in transforms.py.
