"""Over seeded games, an AI seat commits no blocker an attacker does not need
killing with: a census of every block declaration the simulator makes.

LGN Phase 5, smoke game 1: the AI triple-blocked a 1/1 and lost Daru Mender,
and triple-blocked a provoked 4/1 Crested Craghorn the provoked creature alone
would have killed, and lost Skinthinner. CR 510.1c (the September 25, 2026
edition, which has no damage assignment order): "If two or more creatures are
blocking it, it assigns its combat damage to those creatures divided as its
controller chooses among them" — so each blocker beyond what the kill needs is
one more creature the attacker may choose to destroy.

For each attacker an AI declaration blocks with two or more creatures, read on
the board as declared, with ``ai_declarations``' own estimate of a fight
(``_gang_kills``: first strike, deathtouch, a shield):

* **beyond the minimum** — when the blockers together kill the attacker, how
  many more of them there are than the fewest of them that do;
* **beside a compelled blocker that wins alone** — the blockers added to an
  attacker one creature was already required to block (CR 509.1c: provoke's
  mark, ``Game.block_requirements``) and kills alone.

``test_the_old_declaration_committed_blockers_it_did_not_need`` runs it
backwards (the two loops as on a501c6c5) and must find both. Measured on that
tree over these runs: 79 declarations, 12 blockers beyond the minimum and 4
beside a compelled blocker that won alone (backwards on this one: 81, 12 and
2); after it, 87 declarations, 17 gangs, none of either.
"""
from __future__ import annotations

import collections
from contextlib import ExitStack
from itertools import combinations
from unittest import mock

import pytest

from engine import ai_declarations, ai_rehearsal, ai_simulator
from engine.ai_declarations import _gang_kills
from engine.card_loader import manifest_set_path
from engine.game import Game

#: (set, seed, games, pinned). Legions with its provoke creatures (and the
#: 1/1s and 4/1 of Phase 5's board), and two older sets of plain creatures.
RUNS = (
    ("LGN", 7, 4, ("Crested Craghorn", "Goblin Grappler", "Deftblade Elite")),
    ("LGN", 11, 4, ("Crested Craghorn", "Warbreak Trumpeter", "Daru Mender")),
    ("LEA", 7, 3, ()),
    ("M21", 7, 3, ()),
)


def _fewest_that_kill(game, attacker, members) -> int | None:
    for size in range(1, len(members) + 1):
        if any(_gang_kills(game, attacker, list(gang)) for gang in combinations(members, size)):
            return size
    return None


def _read(game: Game, defender: int, blocks: dict) -> dict:
    """What one declaration commits beyond what its kills need."""
    attacker_seat = game.active_player_index
    blockers_of: dict[int, list[int]] = collections.defaultdict(list)
    for blocker_idx, assigned in blocks.items():
        for attacker_idx in assigned if isinstance(assigned, list) else [assigned]:
            blockers_of[attacker_idx].append(blocker_idx)
    compelled = {
        requirement.blocker: requirement.attacker
        for requirement in game.block_requirements(defender)
        if requirement.blocker is not None and requirement.attacker is not None
    }
    read = {"gangs": 0, "beyond": 0, "beside_compelled": 0, "rows": []}
    for attacker_idx, slots in blockers_of.items():
        if len(slots) < 2:
            continue
        attacker = game.permanent_at(attacker_seat, attacker_idx)
        members = [game.permanent_at(defender, slot) for slot in slots]
        if attacker is None or any(member is None for member in members):
            continue
        read["gangs"] += 1
        fewest = _fewest_that_kill(game, attacker, members)
        if fewest is not None and fewest < len(members):
            read["beyond"] += len(members) - fewest
            read["rows"].append(("beyond", attacker.card.name, [m.card.name for m in members]))
        alone = [
            slot for slot in slots
            if compelled.get(slot) == attacker_idx
            and _gang_kills(game, attacker, [game.permanent_at(defender, slot)])
        ]
        if alone:
            read["beside_compelled"] += len(slots) - 1
            read["rows"].append(("beside compelled", attacker.card.name,
                                 [m.card.name for m in members]))
    return read


def _census() -> dict:
    found = {"declarations": 0, "gangs": 0, "beyond": 0, "beside_compelled": 0,
             "compelled_seen": 0, "rows": []}
    original = Game.declare_blockers

    def spy(self, defender, blocks, *args, **kwargs):
        if not ai_rehearsal.rehearsing() and blocks:
            found["declarations"] += 1
            found["compelled_seen"] += sum(
                1 for requirement in self.block_requirements(defender)
                if requirement.blocker is not None and requirement.attacker is not None
            )
            read = _read(self, defender, dict(blocks))
            for key in ("gangs", "beyond", "beside_compelled"):
                found[key] += read[key]
            found["rows"].extend(read["rows"])
        return original(self, defender, blocks, *args, **kwargs)

    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(Game, "declare_blockers", spy))
        for code, seed, games, pinned in RUNS:
            report = ai_simulator.run_ai_simulation(
                manifest_set_path(code), games=games, seed=seed, max_turns=14,
                required_cards=pinned,
            )
            assert report.games_completed == games, code
    return found


def _summary(found: dict) -> dict:
    return {key: value for key, value in found.items() if key != "rows"}


@pytest.mark.full
def test_no_blocker_is_committed_beyond_what_its_kill_needs():
    found = _census()
    assert found["beyond"] == 0, (_summary(found), found["rows"])
    assert found["beside_compelled"] == 0, (_summary(found), found["rows"])
    assert found["declarations"] >= 40, _summary(found)
    assert found["compelled_seen"] >= 1, _summary(found)


@pytest.mark.full
def test_the_old_declaration_committed_blockers_it_did_not_need():
    """Backwards: every blocker given its best pair whatever the blocks on it
    already kill, and no compelled block counted first — the over-commitment
    of a501c6c5's two loops."""
    with mock.patch.object(ai_declarations, "compelled_blocks", lambda game, seat: {}),             mock.patch.object(ai_declarations, "_blocks_already_kill", lambda *args: False):
        found = _census()
    assert found["beyond"] >= 5, _summary(found)
    assert found["beside_compelled"] >= 1, _summary(found)
