# Per-set tests

The convention these files follow, written down because the pool is going from
5 sets to 137. `tests/engine/test_set_test_convention.py` enforces the parts
that can be checked mechanically.

## Where a test goes

**Is it about one card?** Then it belongs here, in
`test_<set>_<card type>.py` — `test_lea_creatures.py`,
`test_lea_instants.py`, and so on, by the **printed type of the card the test
names**. A set starts as a single `test_<set>_cards.py` and splits by type when
it outgrows one file; LEA reached 9,402 lines before it did, which is what this
convention exists to prevent happening again.

**When one printed type outgrows a file too.** The type axis has a floor, and
M21 reached it: 149 of the set's cards are creatures, so
`test_m21_creatures.py` hit the size guard three times in four rounds even after
`Legendary Creature` split off (`Legendary` is part of the printed type line,
CR 205.4a) and after every misfiled test had been moved out. Past that point the
next division is **a round boundary** — `test_m21_creatures_early_rounds.py`.
These files are written as a sequence of self-contained round sections, each one
written up in ROADMAP.md under the round that bought its cards, so cutting at a
section boundary keeps every section whole and keeps a test findable from the
round it belongs to. That is what the guard is protecting; the type is only the
first axis that delivers it.

Do this **only after** auditing the file for misfilings, which is what the guard
has actually surfaced every time so far: a Garruk's Uprising test among the
creatures, two artifact creatures, a per-turn record naming an Instant, four
grammar probes naming no card, and six Vito tests belonging with the other
legendary ones. Reach for a new axis when there is nothing left to move, not
before — and never raise the cap.

**Is it about the whole pool?** It is not a per-set test, whatever set it was
written against. Pool-wide sweeps and guards go in `tests/engine/` and
parametrize over `cards/manifest.json`. The catalog sweep lived in
`test_lea_cards.py` for a long time and read `cards/LEA_cards.json` directly —
which is exactly why Arabian Nights, a set the tracker called complete, was
never swept at all.

**Is it about something other than cards?** Then it goes in the folder for that
subject, not here: `tests/ai/`, `tests/ui/`, `tests/rules/` (with its CR
citation), `tests/engine/`, `tests/regressions/`.

## Getting the cards

```python
def test_serendib_efreet_damages_its_controller(set_pool):
    efreet = set_pool("ARN")["Serendib Efreet"]
```

`set_pool(code)` gives one set's cards by name and `set_cards(code)` gives them
in printing order; both resolve through `cards/manifest.json` and are loaded
once per session. An unknown code raises and names the codes that exist —
resolving it to an empty pool would make every test over that set pass without
testing anything.

Three rules follow from that, and the guard test checks all three:

- **Never add a per-set fixture to `conftest.py`.** It used to grow a path, a
  cards and a by-name fixture per set; at 137 sets that is several hundred
  lines whose entire content is a set code. `cards` / `all_cards` (LEA) and
  `arn_cards` / `arn_by_name` are grandfathered because they have thousands of
  call sites between them. Nothing else gets one.
- **Never spell out a `cards/*.json` path.** Ask the manifest —
  `manifest_set_path(code)`.
- **Keep the pools separate.** Beta is Alpha plus two cards and Unlimited is
  Beta reprinted, so a test that pulls from a merged pool can match a card it
  did not mean. `catalog` is the deliberately merged, deduped view, and is for
  pool-wide work only.

## Adding a set

1. `python scripts/ingest_set.py <CODE> --fetch`
2. Append one entry to `cards/manifest.json`.
3. Write `tests/sets/test_<set>_cards.py` using `set_pool("<CODE>")`.

Steps 1 and 2 are the whole registration: the web app, the coverage scripts,
the catalog sweeps and the fixtures all read the manifest, so nothing else has
a list to widen. The full lifecycle around these steps — measurement, backlog
rounds, promotion, retrospective — is `SET_PLAYBOOK.md` at the repo root.
