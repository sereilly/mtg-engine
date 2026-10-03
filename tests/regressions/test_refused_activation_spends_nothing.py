"""Regression: an activation the engine refuses has spent nothing.

CR 602.2b routes an activation through CR 601.2b–h, and CR 601.2e/733.1 say
what happens when it turns out to be illegal: "the entire action is reversed
and any payments already made are canceled". This engine never reverses a
payment — it is arranged so that there is none to reverse: every check first,
then every cost. ``_activate_onto_stack`` kept to that for every cost but two.

- **The mana was paid above the {T} symbol's refusals** — CR 602.5a's
  summoning sickness and CR 107.5's already-tapped. Time Elemental, sick, went
  30 → 26 in its controller's pool and was refused. Measured before the move,
  over the whole pool on a board where every other cost is payable: 174
  abilities spent mana on a summoning-sick refusal (158 of them shipped) and
  361 on an already-tapped one (336 shipped).
- **A chosen exile cost was paid as it was chosen**, above five refusals still
  to come — the mana payment and the {T} checks among them. City of Shadows,
  already tapped, exiled a creature for nothing; Soul Shepherd, Balduvian Dead,
  Drudge Spell and Night Soil with an empty pool each ate their graveyard cards
  and were refused.

The browser does not hide all of it: ``app.js`` pre-checks sickness and
tappedness off the **first** ability's cost, so a {T} ability at a later index
(Cateran Overlord, Hakim, Subira) reached the server sick or tapped — and its
insufficient-mana auto-tap flow tapped the lands, resent, and lost the mana to
the refusal behind it. The AI skips tapped and sick permanents wholesale, so the
engine API, a test or a script was the other way in.

The sweep at the bottom asks the question of every shipped activated ability
rather than of the cards that surfaced it, and carries floors on how many
refusals it actually reached — run on the pre-fix engine it names Time
Elemental, Pradesh Gypsies, Boris Devilboon, City of Shadows and Soul Shepherd
among 493 shipped refusals that had paid something.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.named_counters import add_counters, counters_on
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from tests.helpers import _nosick, resolve_stack

_W2G3_CATALOG: dict = {}


def _w2g3_card(name):
    if not _W2G3_CATALOG:
        _W2G3_CATALOG.update({c.name: c for c in load_catalog()})
    return _W2G3_CATALOG[name]


def _w2g3_board(source_name, *, pool=None, mine=(), theirs=(), graveyard=()):
    """A two-seat board with costs enforced and the source first in its row.

    The source is placed *not* sick; a test makes it sick or taps it itself,
    so each test says exactly which refusal it engineers.
    """
    source = _nosick(Permanent(card=_w2g3_card(source_name)))
    p0 = PlayerState(
        name="P0",
        battlefield=[source, *(_nosick(Permanent(card=_w2g3_card(n))) for n in mine)],
        graveyard=[_w2g3_card(n) for n in graveyard],
        library=[_w2g3_card("Island")] * 5,
    )
    p1 = PlayerState(
        name="P1",
        battlefield=[_nosick(Permanent(card=_w2g3_card(n))) for n in theirs],
        library=[_w2g3_card("Island")] * 5,
    )
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = True
    game._settle()
    p0.mana_pool = {s: 0 for s in ("W", "U", "B", "R", "G", "C")}
    p0.mana_pool.update(pool or {})
    return game, source


def test_a_summoning_sick_time_elemental_keeps_its_mana():
    """"{2}{U}{U}, {T}: Return target permanent that isn't enchanted to its
    owner's hand." Refused for CR 602.5a with the pool exactly as it was."""
    game, elemental = _w2g3_board(
        "Time Elemental", pool={"U": 4, "C": 4}, theirs=("Grizzly Bears",),
    )
    elemental.metadata["summoning_sickness_turn"] = game.turn

    result = game.activate_permanent_ability(0, "Time Elemental")

    assert not result.supported
    assert "summoning sickness" in result.details
    assert game.players[0].mana_pool["U"] == 4 and game.players[0].mana_pool["C"] == 4
    assert not elemental.tapped
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]


def test_an_already_tapped_pradesh_gypsies_keeps_its_mana():
    """"{1}{G}, {T}: Target creature gets -2/-0 until end of turn." CR 107.5:
    a tapped permanent cannot pay {T}, so nothing else is paid either."""
    game, gypsies = _w2g3_board(
        "Pradesh Gypsies", pool={"G": 2}, theirs=("Grizzly Bears",),
    )
    gypsies.tapped = True

    result = game.activate_permanent_ability(0, "Pradesh Gypsies")

    assert not result.supported
    assert "already tapped" in result.details
    assert game.players[0].mana_pool["G"] == 2


def test_an_already_tapped_city_of_shadows_exiles_nothing():
    """"{T}, Exile a creature you control: Put a storage counter on this land."
    The exile was paid as it was chosen, above the {T} check — a creature gone
    for an activation that never happened."""
    game, city = _w2g3_board("City of Shadows", mine=("Grizzly Bears",))
    city.tapped = True

    result = game.activate_permanent_ability(0, "City of Shadows", ability_index=0)

    assert not result.supported
    assert "already tapped" in result.details
    assert [p.card.name for p in game.controlled_by(0)] == ["City of Shadows", "Grizzly Bears"]
    assert game.players[0].exile == []


def test_city_of_shadows_untapped_still_pays_and_resolves():
    """The positive half: moving the exile below the last refusal must not lose
    it. The creature leaves as the cost is paid and the counter arrives."""
    game, city = _w2g3_board("City of Shadows", mine=("Grizzly Bears",))

    result = game.activate_permanent_ability(0, "City of Shadows", ability_index=0)
    resolve_stack(game)

    assert result.supported, result.details
    assert city.tapped
    assert [p.card.name for p in game.controlled_by(0)] == ["City of Shadows"]
    assert [c.name for c in game.players[0].exile] == ["Grizzly Bears"]
    assert counters_on(city, "storage") == 1


def test_soul_shepherd_with_no_mana_keeps_its_graveyard():
    """"{W}, Exile a creature card from your graveyard: You gain 1 life." With
    an empty pool the mana is the refusal, and the card stays where it was."""
    game, _shepherd = _w2g3_board(
        "Soul Shepherd", graveyard=("Grizzly Bears", "Lightning Bolt"),
    )

    result = game.activate_permanent_ability(0, "Soul Shepherd")

    assert not result.supported
    assert "insufficient mana" in result.details
    assert [c.name for c in game.players[0].graveyard] == ["Grizzly Bears", "Lightning Bolt"]
    assert game.players[0].exile == []


def test_soul_shepherd_with_mana_exiles_the_creature_card_and_gains_life():
    game, _shepherd = _w2g3_board(
        "Soul Shepherd", pool={"W": 1}, graveyard=("Lightning Bolt", "Grizzly Bears"),
    )
    life = game.players[0].life

    result = game.activate_permanent_ability(0, "Soul Shepherd")
    resolve_stack(game)

    assert result.supported, result.details
    assert game.players[0].mana_pool["W"] == 0
    assert [c.name for c in game.players[0].graveyard] == ["Lightning Bolt"]
    assert [c.name for c in game.players[0].exile] == ["Grizzly Bears"]
    assert game.players[0].life == life + 1


# ---------------------------------------------------------------------------
# The sweep: every shipped activated ability, three refusals each.
# ---------------------------------------------------------------------------

_W2G3_MINE = (
    "Plains", "Island", "Swamp", "Mountain", "Forest", "Grizzly Bears",
    "Ornithopter", "Scathe Zombies",
)
_W2G3_THEIRS = ("Forest", "Grizzly Bears", "Serra Angel", "Mox Ruby", "Ornithopter")
_W2G3_HAND = ("Forest", "Grizzly Bears", "Lightning Bolt")
_W2G3_GRAVE = ("Grizzly Bears", "Ornithopter", "Scathe Zombies", "Forest")
_W2G3_FULL = {s: 10 for s in ("W", "U", "B", "R", "G", "C")}

_W2G3_INTENDED = {
    "sick": "summoning sickness",
    "tapped": "already tapped",
    "broke": "insufficient mana",
}


def _w2g3_sweep_state(game):
    """Everything a cost can move, per seat and per permanent."""
    seats = tuple(
        (
            p.life,
            tuple(sorted((k, v) for k, v in p.mana_pool.items() if v)),
            tuple(sorted(
                (k, tuple(sorted((s, n) for s, n in b.items() if n)))
                for k, b in (p.restricted_mana or {}).items() if any(b.values())
            )),
            tuple(c.name for c in p.hand),
            tuple(c.name for c in p.graveyard),
            tuple(c.name for c in p.library),
            tuple(c.name for c in p.exile),
        )
        for p in game.players
    )
    permanents = tuple(sorted(
        (
            seat, perm.permanent_id, perm.tapped,
            tuple(sorted(
                (k, v) for k, v in perm.metadata.items()
                if isinstance(v, (int, str, bool, float))
            )),
        )
        for seat, perm in game.permanents_with_controller()
    ))
    return seats, permanents


def _w2g3_sweep_run(card, ability_index, ability, scenario):
    source = _nosick(Permanent(card=card))
    p0 = PlayerState(
        name="P0",
        battlefield=[source, *(_nosick(Permanent(card=_w2g3_card(n))) for n in _W2G3_MINE)],
        hand=[_w2g3_card(n) for n in _W2G3_HAND],
        graveyard=[_w2g3_card(n) for n in _W2G3_GRAVE],
        library=[_w2g3_card("Island")] * 6,
    )
    their_board = [_nosick(Permanent(card=_w2g3_card(n))) for n in _W2G3_THEIRS]
    their_board[0].tapped = True
    p1 = PlayerState(name="P1", battlefield=their_board, library=[_w2g3_card("Island")] * 6)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = True
    game.turn = 3
    game._settle()
    if not any(perm is source for perm in game.controlled_by(0)):
        return None
    p0.mana_pool = dict(_W2G3_FULL) if scenario != "broke" else {s: 0 for s in _W2G3_FULL}
    if ability.cost.remove_counter:
        add_counters(source, str(ability.cost.remove_counter), 4)
    if scenario == "sick":
        source.metadata["summoning_sickness_turn"] = game.turn
    elif scenario == "tapped":
        source.tapped = True
    before = _w2g3_sweep_state(game)
    result = game.activate_permanent_ability(
        0, card.name, permanent_index=0, ability_index=ability_index, x_value=1,
    )
    if result.supported:
        return None
    return result.details or "", before != _w2g3_sweep_state(game)


def test_no_shipped_activation_refused_at_its_cost_has_paid_part_of_it():
    reached = {"sick": 0, "tapped": 0, "broke": 0}
    spent: list[str] = []
    for card in load_catalog():
        usable = usable_activated_abilities(compile_card_oracle(card))
        for index, ability in enumerate(usable):
            if ability.instruction is None or not ability.supported:
                continue
            cost = ability.cost
            scenarios = []
            if cost.requires_tap:
                if "creature" in (card.type_line or "").lower():
                    scenarios.append("sick")
                scenarios.append("tapped")
            if any(int(v) for v in (cost.mana or {}).values()):
                scenarios.append("broke")
            for scenario in scenarios:
                outcome = _w2g3_sweep_run(card, index, ability, scenario)
                if outcome is None:
                    continue
                details, moved = outcome
                if _W2G3_INTENDED[scenario] in details:
                    reached[scenario] += 1
                if moved:
                    spent.append(f"{card.name}[{index}] {scenario}: {details}")
    assert not spent, f"{len(spent)} refused activations paid something: {spent[:25]}"
    # The honesty floors. A sweep whose board stops reaching the refusal it
    # engineers passes on any engine; these are ~90% of what it reached when
    # written (sick 337, tapped 769, broke 802 on the shipped pool).
    assert reached["sick"] >= 300, reached
    assert reached["tapped"] >= 690, reached
    assert reached["broke"] >= 720, reached
