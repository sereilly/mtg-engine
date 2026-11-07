"""Census: seeded games' logs carry none of Phase 5's wording classes.

Phase 5 read whole games and found the log printing the engine's record in
place of the game. ``test_kg3_logs_wording.py`` drives one board of each
class; this plays seeded AI games — with the cards that wrote each class
pinned into the decks — and reads every line they wrote:

* a token's name said twice ("Bird Token token", CR 111.4);
* a colour said as its mana symbol ("chose U", "became G", "1 R mana") and a
  type in lower case ("chose wizard");
* a shrink called a buff ("buffed matching creatures");
* a line that names no card and no player ("Reanimated creature to
  battlefield", "Returned creature to hand", "Changed target color") — the
  turn's own structure lines excepted;
* a damage line naming one end only ("Goblin Dynamo dealt 1 damage",
  "AI-B took 3 damage");
* "died" said of a creature a replacement exiled (CR 700.4);
* a declaration step said to be complete before its window has drained
  (CR 500.2) — read by a spy, since a log alone cannot say when a window ran.

Measured on the base (``9d5c7b25``): every class but the colour words fires
over these four runs — the step line in every game.
"""
from __future__ import annotations

import re
from collections import Counter

import pytest

from engine import ai_rehearsal
from engine.ai_simulator import run_ai_simulation
from engine.card_loader import load_catalog, manifest_set_path
from engine.face_down import face_down_card
from engine.game import Game
from engine.grammar.vocabulary import CREATURE_TYPES, LAND_TYPES

#: (set, seed, games, pinned cards) — each pinned card wrote a class Phase 5
#: or this round's census found.
_RUNS = (
    ("LGN", 7, 2, ("Goblin Dynamo", "Toxin Sliver", "Bane of the Living")),
    ("ARN", 7, 2, ("Rukh Egg", "City of Brass")),
    ("LEG", 7, 2, ("Hell Swarm",)),
    ("LEA", 7, 2, ("Disintegrate", "Resurrection")),
)

_CLASSES = {
    "a token's name said twice": re.compile(r"\btoken tokens?\b", re.I),
    "a colour said as its symbol": re.compile(
        r"\b(?:chose|became|is not) [WUBRG](?:/[WUBRG])*(?![\w'])"
    ),
    "mana said as a letter": re.compile(r"\b\d+ [WUBRGC] mana\b"),
    "a shrink called a buff": re.compile(r"\bbuffed\b"),
    "a damage line naming no recipient": re.compile(r"\bdealt \d+ damage$"),
    "a damage line naming no source": re.compile(r"^\S+ took \d+ damage$"),
}

#: Lines about the turn itself, which name no card because none did it.
_STRUCTURE = re.compile(
    r"^(?:Resolved (?:first strike )?combat damage"
    r"|Declare (?:attackers|blockers) step complete: .*"
    r"|No attackers; declare blockers and combat damage steps skipped \(508\.8\))$"
)

#: A token's CR 111.4 name ("Insect Token"), which no card in the pool carries.
_TOKEN_NAME = re.compile(r"\b[A-Z][\w'-]*(?: [A-Z][\w'-]*)* Token\b")

_DECLARATION_STEPS = {
    "declare_attackers": "Declare attackers step complete",
    "declare_blockers": "Declare blockers step complete",
}


def _named(pattern_names):
    return re.compile(
        r"(?<![\w])(?:" + "|".join(re.escape(name) for name in pattern_names) + r")(?![\w])"
    )


@pytest.fixture
def step_spy(monkeypatch):
    """Where each declaration step began in each real game's log, and every
    window opened in one: at that moment its "complete" line must not yet
    have been written."""
    entered: dict[int, tuple] = {}
    record = {"windows": 0, "early": []}
    enter, window = Game._enter_combat_step, Game._resolve_priority_window

    def spied_enter(self, step):
        result = enter(self, step)
        if not ai_rehearsal.rehearsing():
            # The game itself is held, so its id is never reused while kept.
            entered[id(self)] = (self, self.current_step, len(self.log))
        return result

    def spied_window(self):
        kept = entered.get(id(self))
        if (
            kept is not None and not ai_rehearsal.rehearsing()
            and kept[1] == self.current_step in _DECLARATION_STEPS
        ):
            record["windows"] += 1
            said = _DECLARATION_STEPS[self.current_step]
            if any(line.startswith(said) for line in self.log[kept[2]:]):
                record["early"].append((self.turn, self.current_step))
        return window(self)

    monkeypatch.setattr(Game, "_enter_combat_step", spied_enter)
    monkeypatch.setattr(Game, "_resolve_priority_window", spied_window)
    return record


@pytest.mark.full
def test_seeded_logs_carry_none_of_the_wording_classes(step_spy):
    catalog = load_catalog()
    names = {card.name for card in catalog}
    names |= {part for name in list(names) for part in name.split(" // ")}
    # A face-down object is named as what it is (CR 708.2a), never as its card.
    names.add(face_down_card(catalog[0]).name)
    card_or_player = _named(sorted(names, key=len, reverse=True))
    subtype = re.compile(r"\bchose ([a-z][\w'\- ]*)$")
    found: Counter = Counter()
    examples: dict[str, str] = {}
    read = 0

    for code, seed, games, pinned in _RUNS:
        report = run_ai_simulation(
            manifest_set_path(code), games=games, seed=seed, required_cards=pinned,
        )
        assert report.games_completed == games, code
        players = _named(sorted({
            match for line in report.log_lines
            for match in re.findall(r"AI-[AB]-\d+", line)
        }))
        lines = [line.strip() for line in report.log_lines if line.startswith("  ")]
        read += len(lines)
        for index, line in enumerate(lines):
            hits = [label for label, pattern in _CLASSES.items() if pattern.search(line)]
            chosen = subtype.search(line)
            if chosen and (chosen.group(1) in CREATURE_TYPES or chosen.group(1) in LAND_TYPES):
                hits.append("a type said in lower case")
            if line.startswith("Reanimated ") or not (
                _STRUCTURE.match(line) or card_or_player.search(line)
                or players.search(line) or _TOKEN_NAME.search(line)
            ):
                hits.append("a line naming no card and no player")
            gone = re.match(
                r"(.+?) was (?:destroyed \(.*\) and )?exiled instead of dying$", line
            )
            if gone and any(
                later.startswith(f"{gone.group(1)} died") for later in lines[index + 1:index + 4]
            ):
                hits.append("died, said of a creature exiled instead")
            for label in hits:
                found[f"{code}: {label}"] += 1
                examples.setdefault(f"{code}: {label}", line)

    assert read >= 2000, read
    assert step_spy["windows"] >= 8, step_spy["windows"]
    assert not found, {label: (count, examples[label]) for label, count in found.items()}
    assert not step_spy["early"], step_spy["early"][:6]
