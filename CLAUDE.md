# Claude Code Preferences

## Code Style
- Do not use emojis in logging or documentation
- Collapse imports onto one line whenever possible
- Group imports by: standard libraries, local imports, external libraries

## Python Services Structure
- Prioritize creating `helpers.py` files to collect utility functions
- Keep main logic in `main.py` or `app.py` files clean by extracting helpers
- Move reusable functions to `helpers.py` rather than cluttering main files