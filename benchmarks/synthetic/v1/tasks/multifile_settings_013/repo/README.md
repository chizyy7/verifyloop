# Settings loader mutates shared defaults across modules

The configuration package has two modules: defaults.py holds a module-level DEFAULTS dictionary including a nested 'headers' mapping, and settings.py merges caller overrides into it. load_settings() currently aliases DEFAULTS instead of copying it, so one call permanently changes the defaults seen by every later call, and nested dictionaries are shared. Fix settings.load_settings() so each call returns an independent deep copy and defaults.DEFAULTS is never modified. Do not change defaults.py.
