---
name: retrieve-oracle
description: 'Retrieve oracle text for a Magic: The Gathering card from the local engine card data. Use for lookups by exact name, case-insensitive name, substring, or fuzzy match.'
argument-hint: 'Provide the card name or partial name to look up.'
user-invocable: true
---

# Retrieve Oracle Text

## Outcome
Return the `oracle_text` and metadata for a named Magic: The Gathering card using the local repository card data (`engine.card_loader`).

## Inputs
- `card_name` (string): user-supplied card name or partial name.
- Optional `match_mode`: one of `exact`, `case_insensitive`, `substring`, or `fuzzy`.

## When To Use
- User asks for the oracle text, rules text, or card text of a specific card.
- User wants to look up card metadata (type, cost, power/toughness) from the local data set.
- A rules question requires confirming exact card wording before issuing a ruling.

## Procedure
1. **Normalize input** — trim whitespace; preserve punctuation used in official names (apostrophes, colons).
2. **Load card data** — `from engine.card_loader import load_cards; all_cards = load_cards()`.
3. **Match in priority order** (stop at first hit):
   a. Exact match against `card.name`.
   b. Case-insensitive exact match.
   c. Substring match (card name contains input).
   d. Fuzzy match via `difflib.get_close_matches` (threshold 0.6) — only if `match_mode` is `fuzzy` or no earlier match found.
4. **Handle results**:
   - Single match → return `match.oracle_text` and `match` metadata.
   - Multiple matches → return candidate list (name, set, type) and ask user to choose.
   - No match → return a helpful failure message and the top 5 closest names by similarity.
5. **Multiple-printing edge case** — if the same name appears in multiple sets, prefer the most complete record or return all printings and ask the user to pick.

## Decision Points
- If `match_mode` is provided, use it to force the matching strategy; otherwise iterate modes from strict → loose.
- For names with punctuation (e.g., `Nevinyrral's Disk`), prefer exact or case-insensitive exact to avoid false positives from substring/fuzzy.
- If fuzzy similarity is below 0.6, treat the result as not found.

## Quality Checks
- Returned oracle text is non-empty and punctuated correctly.
- If ambiguous, the user can select a numbered candidate and the skill returns that card's oracle text.
- Given input `Black Lotus`, the skill returns the known oracle text without error.

## Example Implementation

```python
from engine.card_loader import load_cards
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

## Usage Examples
- "Retrieve oracle text for Black Lotus"
- "Get oracle text for `Nevinyrral's Disk`"
- "Find oracle text for 'Lotus' (show candidates)"
