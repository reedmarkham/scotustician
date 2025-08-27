# Claude Code Preferences

## Code Style
- Do not use emojis in logging or documentation
- Collapse imports onto one line whenever possible
- Group imports by: standard libraries, local imports, external libraries
- Avoid docstrings for functions where the docstring would more or less repeat the function name, to keep the overall file length light
- Always provide typing to functions' input(s) and/or output(s), and when writing a docstring (if need be, per above guidance) add in those input(s) and/or output(s) types in reference to their variables as well

## Python Services Structure
- Prioritize creating `helpers.py` files to collect utility functions
- Keep main logic in `main.py` or `app.py` files clean by extracting helpers
- Move reusable functions to `helpers.py` rather than cluttering main files