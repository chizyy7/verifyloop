# JSON loader swallows every error

storage.py contains load_json(), which wraps the whole read in 'except Exception' and returns the default value. This hides corrupted files and programming errors. Fix it so that only a missing file returns the default; malformed JSON raises ValueError with the original exception chained; and other OSError conditions propagate unchanged.
