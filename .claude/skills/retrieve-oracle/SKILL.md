---
name: retrieve-oracle
description: 'Retrieve oracle text for a Magic: The Gathering card from the local engine card data. Use for lookups by exact name, case-insensitive name, substring, or fuzzy match.'
argument-hint: 'Provide the card name or partial name to look up.'
user-invocable: true
---

# Retrieve Oracle Text

## Outcome
Return the `oracle_text` and metadata for a named Magic: The Gathering card from
this repository's card data.

## Procedure

Run the script. It is the implementation — do not re-derive the matching logic
inline, or the skill and the script drift into disagreeing about what the pool
contains.

```powershell
.\.venv\Scripts\python.exe scripts/retrieve_oracle.py "Black Lotus"
.\.venv\Scripts\python.exe scripts/retrieve_oracle.py "lotus" --mode substring
.\.venv\Scripts\python.exe scripts/retrieve_oracle.py "Erhnam Djinn" --set ARN
```

### The pool

The default is **every set in `cards/manifest.json`**. That matters: the script
read Alpha's file and nothing else until this was fixed, so `Library of
Alexandria` — an Arabian Nights card the engine ships — fuzzy-matched to
`Library of Leng` and returned the wrong card's text, silently. For a lookup
whose whole job is confirming exact wording before a ruling, that is the worst
available failure.

Narrow it only when the question is about one set: `--set <CODE>` (`LEA`, `LEB`,
`2ED`, `ARN`, `3ED` — `--set` with an unknown code exits naming the codes that
ship). `--all` is the explicit form of the default. `--cards <path>` / `--file
<path>` still take a JSON by path.

### Arguments

- positional `name` — the card name or partial name.
- `--mode {exact,ci,substring,fuzzy}` — force one matching strategy. Omit it to
  try all four strict→loose, stopping at the first hit.
- `--max-candidates N` — how many candidates to list for a non-unique match.

### Exit codes

| Code | Meaning | What to do |
| --- | --- | --- |
| 0 | one match; the card is printed | report the oracle text |
| 1 | no match at all | say so; do not guess a card |
| 2 | bad arguments (unknown `--set`, missing file) | fix the invocation |
| 3 | several candidates; they are listed | ask the user which, or re-run with `--mode exact` |

## Decision Points
- For names with punctuation (e.g. `Nevinyrral's Disk`), pass `--mode exact` or
  `--mode ci` — substring and fuzzy invite false positives, and a plausible
  wrong card is worse than a reported miss.
- Reprints dedupe to one card, and the output's `Printings:` line names every
  set it appears in. Prefer that line over re-running per set.
- If the card is not in the pool, say the engine does not ship it. Do not fill
  the gap from memory — `MagicCompRules.txt` and the card files are the
  authorities here, and the point of the lookup is to not be recalling.

## Quality Checks
- `"Black Lotus"` returns `{T}, Sacrifice this artifact: Add three mana of any
  one color.` with `Printings: LEA, LEB, 2ED`.
- `"Library of Alexandria"` returns the Arabian Nights land, not Library of Leng.
- `--set ZZZ` exits 2 naming the codes that exist, rather than reporting no
  match against an empty pool.
