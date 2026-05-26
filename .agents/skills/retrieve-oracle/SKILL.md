# SKILL: Retrieve Oracle Text

Purpose
- Provide a concise, repeatable workflow to retrieve the oracle text for a given Magic: The Gathering card from this repository.

Scope
- Workspace-scoped skill for `c:\Users\qwv48_66yef5i\Desktop\Magic` projects that use the local `engine` card data.

Inputs
- `card_name` (string): user-supplied card name or partial name.
- Optional `match_mode`: one of `exact`, `case_insensitive`, `substring`, or `fuzzy`.

Outputs
- On success: returns the card's `oracle_text` string and the matching card metadata.
- On ambiguity: returns a short list of candidate card names and prompts for disambiguation.
- On not found: returns a helpful message and the top N closest matches.

Step-by-step Workflow
1. Normalize input
   - Trim whitespace; preserve punctuation used in official names (apostrophes, colons).
2. Load repository card data
   - Use the repository loader, e.g. `from engine import load_cards` or the appropriate loader in `engine.card_loader`.
   - `all_cards = load_cards()`
3. Exact match attempts (in this order)
   a. `exact` match against `card.name`
   b. case-insensitive exact
   c. substring match (card name contains input)
   d. optional fuzzy match (Levenshtein or difflib.get_close_matches)
4. Handle results
   - Single match: return `match.oracle_text` and `match` metadata.
   - Multiple matches: return candidate list (name, set, type) and ask user to choose.
   - No matches: return helpful failure and include top 5 close matches by similarity.
5. Error and edge cases
   - If input matches multiple printings (same name, different sets), prefer the most complete record or return all printings and ask user to pick.
   - For names with punctuation (e.g., `Nevinyrral's Disk`) prefer exact or case-insensitive exact to avoid false positives.

Decision Points and Branching Logic
- If `match_mode` is provided use it to force strategy; otherwise iterate modes from strict → loose.
- If fuzzy matching is enabled, ensure a similarity threshold (default 0.6). If below threshold, treat as not found.

Quality Criteria / Completion Checks
- Returned oracle text is non-empty and contains at least one sentence punctuated correctly.
- If ambiguous, user can select a numbered candidate and the skill returns that candidate's oracle text.
- Unit test: given input `Black Lotus` the skill returns the known oracle text and not an error.

Example Implementation Snippet
```python
from engine import load_cards
import difflib

def retrieve_oracle_text(card_name, match_mode=None, max_candidates=5):
    all_cards = load_cards()
    norm = card_name.strip()

    # 1. exact
    for c in all_cards:
        if c.name == norm:
            return c.oracle_text, c
    # 2. case-insensitive
    for c in all_cards:
        if c.name.lower() == norm.lower():
            return c.oracle_text, c
    # 3. substring
    candidates = [c for c in all_cards if norm.lower() in c.name.lower()]
    if len(candidates) == 1:
        return candidates[0].oracle_text, candidates[0]
    if candidates:
        return None, candidates
    # 4. fuzzy
    names = [c.name for c in all_cards]
    close = difflib.get_close_matches(norm, names, n=max_candidates, cutoff=0.6)
    return None, close
```

Testing Guidance
- Add a small pytest in `tests/` that calls `retrieve_oracle_text('Black Lotus')` and asserts the returned oracle text matches the known string from `lea_cards.json` or `load_cards()`.

Prompts & Usage Examples
- "Retrieve oracle text for Black Lotus"
- "Get oracle text for `Nevinyrral's Disk`"
- "Find oracle text for 'Lotus' (show candidates)"

Ambiguities to Clarify (questions for user)
- Should fuzzy matching be enabled by default, or opt-in?
- When multiple printings exist, prefer one printing or return all variants?
- Preferred format for returned text (raw string, JSON with metadata, or markdown-wrapped)?

Next Steps
- I can add a small helper function file (e.g., `.agents/skills/retrieve-oracle/retrieve.py`) and a pytest if you want.
- I can also wire a short CLI command or web endpoint in `web/` to expose this.

Examples of follow-up customizations
- Add language/localization support.
- Add a short-circuit cache for repeated lookups.
- Add fuzzy-match tuning settings in `pyproject.toml` or a small `settings.yaml`.

Created-by
- Skill author: agent-customization-guided template
- Date: 2026-05-25
