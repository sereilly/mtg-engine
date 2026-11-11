"""A return out of a graveyard names the card worth most back that can arrive
(``engine/ai_graveyard_returns.py``).

kg5's ``kindred`` measured that the AI's reanimation never asked whether its
card could enter the battlefield: with a Kindred instant ("Kindred Instant —
Zombie", a legal "Zombie card" target that stays in the graveyard, CR 400.4a)
first in the pile, the cast's rehearsal saw nothing change and dropped it, and
the Zombie creature beside it was never returned. Re-measured, the cast named
**no** card at all: the handler's fallback took the first card the phrase
admits in pile order, so a Resurrection over a Grizzly Bears and a Shivan
Dragon returned the Bears — on every shipped one-card return (Raise Dead,
Regrowth, Zombify, Breath of Life, …), a much wider defect than the Kindred
case, which no shipped card reaches (the pool's one Kindred card is an
artifact). A trigger's default took the first card in a pile (Gravedigger),
an activation the card of greatest mana value, a several-card return the
pile's first N.

Every road ranks by one reading now: a card that can be put where the return
puts it first (``permanent_cards.is_permanent_card``, CR 110.4a), then the
dearest (``battlefield_worth`` / ``held_worth``). The censuses cast every
shipped one-card return spell, and put every shipped creature whose entry
trigger returns a card, over a pile with its dearest legal card last; on the
base each returned the pile's first.
"""

from __future__ import annotations

from functools import lru_cache

import pytest

from engine import Game, PlayerState, faces
from engine.ai_graveyard_returns import (best_graveyard_return, cast_graveyard_return,
                                         graveyard_return_destination)
from engine.ai_policy import cast_chosen_instant, choose_cast_action
from engine.card_loader import load_catalog
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.pending_choices import spec_for
from tests.helpers import _nosick, settle

#: The pile, cheapest first and the dearest last, so a pick by pile order is
#: the worst one: creatures, artifacts, an enchantment, spells and a land.
_PILE = (
    "Grizzly Bears", "Ornithopter", "Lightning Bolt", "Giant Growth", "Mountain",
    "Pacifism", "Juggernaut", "Serra Angel", "Shivan Dragon",
)


@lru_cache(maxsize=None)
def _catalog() -> dict:
    return {card.name: card for card in load_catalog()}


def _card(name: str, type_line: str, oracle_text: str = "", mana_cost: str = "{B}",
          power: "int | None" = None) -> CardDefinition:
    cmc = float(sum(int(ch) if ch.isdigit() else 1
                    for ch in mana_cost.replace("{", " ").replace("}", " ").split()))
    raw = {"name": name, "type_line": type_line}
    if power is not None:
        raw.update(power=str(power), toughness=str(power))
    return CardDefinition(
        name=name, mana_cost=mana_cost, cmc=cmc, type_line=type_line,
        oracle_text=oracle_text, colors=("B",), color_identity=("B",),
        keywords=(), produced_mana=(), raw=raw,
    )


#: A Kindred sorcery with a creature type: a legal "Zombie card" target that
#: cannot enter the battlefield (CR 308.1, CR 400.4a), dearer than the Zombie.
_ZOMBIE_RITE = _card("Test Zombie Rite", "Kindred Sorcery — Zombie", "You gain 1 life.", "{4}{B}{B}")
_RAISE = _card("Test Zombie Raising", "Sorcery",
               "Return target Zombie card from your graveyard to the battlefield.", "{1}{B}")
_NECROMANCER = _card("Test Zombie Caller", "Creature — Human Wizard",
                     "{T}: Return target Zombie card from your graveyard to the battlefield.", "{2}{B}",
                     power=1)


def _seat(hand=(), *, graveyard=(), mine=(), interactive=()) -> Game:
    cards = _catalog()

    def named(items):
        return [cards[item] if isinstance(item, str) else item for item in items]

    game = Game(players=[
        PlayerState(name="A", hand=named(hand), graveyard=named(graveyard),
                    library=[cards["Swamp"]] * 10),
        PlayerState(name="B", library=[cards["Swamp"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    hill_giant = Permanent(card=cards["Hill Giant"])
    game._put_permanent_onto_battlefield(1, hill_giant, None)
    for item in mine:
        permanent = Permanent(card=named([item])[0])
        game._put_permanent_onto_battlefield(0, permanent, None)
        _nosick(permanent)
    game.start_turn(0)
    game._settle()
    return game


def _returns(program) -> "tuple[str, set] | None":
    """Where the program's one-card graveyard return puts its card, from a
    spell's own instructions, or None."""
    return graveyard_return_destination(program.instructions)


def _left(game, before) -> list[str]:
    after = [card.name for card in game.players[0].graveyard]
    gone = list(before)
    for name in after:
        if name in gone:
            gone.remove(name)
    return gone


def _one_card_return_spells() -> list:
    found = []
    for unit in faces.compilation_units(sorted(_catalog().values(), key=lambda c: c.name)):
        if unit.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(unit)
        if program.supported and _returns(program) is not None:
            found.append(unit)
    return found


def test_every_one_card_return_spell_names_the_card_worth_most_back():
    """Every shipped instant or sorcery returning a target card out of its
    caster's graveyard, cast by the AI over a pile whose dearest legal card is
    last: the cast names a card, the engine returns that card, and it is the
    one the reading ranks first — never, where they differ, the pile's
    first legal card (the base's pick)."""
    spells = _one_card_return_spells()
    assert len(spells) >= 30, len(spells)
    cast, distinguishing = 0, 0
    for spell in spells:
        if spell.name not in _catalog():
            continue  # a split card's half: its whole card is cast by the half's name
        game = _seat([spell.name], graveyard=_PILE)
        named = cast_graveyard_return(game, 0, spell)
        if named is None:
            continue
        legal = [
            entry for entry in game.cast_target_spec(0, spell).get("valid_targets") or []
            if entry.get("kind") == "graveyard"
        ]
        destination = _returns(compile_card_oracle(spell))
        best = best_graveyard_return(game, 0, legal, destination)
        first = legal[0]
        action = choose_cast_action(game, 0)
        if action is None or action.card_name != spell.name:
            continue
        assert (action.target_player_index, action.target_graveyard_indices) == (
            best["seat"], [best["index"]],
        ), (spell.name, action)
        before = [card.name for card in game.players[0].graveyard]
        cast_chosen_instant(game, 0, action)
        settle(game)
        gone = _left(game, before)
        assert best["name"] in gone, (spell.name, best["name"], gone, game.log[-6:])
        cast += 1
        distinguishing += first["name"] != best["name"]
    assert cast >= 15, cast
    assert distinguishing >= 10, distinguishing


def _entry_return_creatures() -> list:
    found = []
    for unit in faces.compilation_units(sorted(_catalog().values(), key=lambda c: c.name)):
        if "Creature" not in (unit.type_line or ""):
            continue
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        if any(
            trigger.condition.kind == "enters_battlefield"
            and trigger.instruction is not None
            and graveyard_return_destination((trigger.instruction,)) is not None
            for trigger in program.triggered_abilities
        ):
            found.append(unit)
    return found


def test_every_entry_trigger_return_takes_the_card_worth_most_back():
    """Every shipped creature whose entry trigger returns a target card out of
    a graveyard (Gravedigger, Karmic Guide, …), over the same pile: the
    trigger's own default (``choices/triggers._default_trigger_target``,
    what a seat nobody asks answers) names the card the reading ranks first
    among the cards the trigger offers, and the engine returns it — not the
    first offered, which on the base it was."""
    creatures = _entry_return_creatures()
    assert len(creatures) >= 8, [card.name for card in creatures]
    returned, distinguishing = 0, 0
    for creature in creatures:
        game = _seat([creature.name], graveyard=_PILE, interactive=(0,))
        if not game.cast_from_hand(0, creature.name).supported:
            continue
        owed = settle(game, defaults=False)
        for _ in range(4):
            if owed is None or owed.kind == "trigger_target":
                break
            spec_for(owed.kind).default(game, owed)
            owed = settle(game, defaults=False)
        if owed is None:
            continue
        offered = [t for t in owed.data.get("targets") or () if t.get("kind") == "graveyard"]
        item = owed.data.get("_trigger_item")
        destination = graveyard_return_destination((getattr(item, "ability_instruction", None),))
        best = best_graveyard_return(game, 0, offered, destination) if destination else None
        if best is None:
            continue
        before = [card.name for card in game.players[0].graveyard]
        game._default_trigger_target(owed)
        settle(game)
        gone = _left(game, before)
        if not gone:
            continue  # a "may" the default declined
        returned += 1
        assert gone == [best["name"]], (creature.name, best["name"], gone, game.log[-6:])
        distinguishing += offered[0]["name"] != best["name"]
    assert returned >= 5, returned
    assert distinguishing >= 3, distinguishing


@pytest.mark.parametrize("pile", [(_ZOMBIE_RITE, "Scathe Zombies"), ("Scathe Zombies", _ZOMBIE_RITE)])
def test_a_reanimation_returns_the_zombie_the_battlefield_can_take(pile):
    """kindred's board: "Return target Zombie card from your graveyard to the
    battlefield" over a Kindred sorcery (dearer, and first or second in the
    pile) and Scathe Zombies. The AI casts it at the Zombie creature — on the
    base, with the sorcery first, the rehearsal saw nothing change and the
    spell stayed in hand."""
    game = _seat([_RAISE], graveyard=list(pile))
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == _RAISE.name, action
    cast_chosen_instant(game, 0, action)
    settle(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Scathe Zombies"], game.log[-6:]
    assert [card.name for card in game.players[0].graveyard if card.name != _RAISE.name] == [
        _ZOMBIE_RITE.name,
    ]


def test_an_activated_return_takes_the_card_that_can_enter():
    """"{T}: Return target Zombie card from your graveyard to the
    battlefield": the activation's pick was the card of greatest mana value —
    the Kindred sorcery, which stays where it is, so the rehearsal turned the
    activation down and the Zombie stayed in the graveyard."""
    from engine.ai_abilities import choose_activation_action
    from engine.ai_actions import activation_announcement

    game = _seat(graveyard=[_ZOMBIE_RITE, "Scathe Zombies"], mine=[_NECROMANCER])
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == _NECROMANCER.name, action
    result = game.activate_permanent_ability(
        0, action.permanent_name, **activation_announcement(action),
    )
    assert result.supported, result
    settle(game)
    assert sorted(p.card.name for p in game.controlled_by(0)) == [
        "Scathe Zombies", _NECROMANCER.name,
    ], game.log[-6:]


def test_a_two_card_return_takes_the_two_worth_most():
    """"Return two target creature cards from your graveyard to your hand"
    (Death's Duet): the two dearest, where the pile's first two were taken."""
    game = _seat(["Death's Duet"], graveyard=["Grizzly Bears", "Llanowar Elves", "Shivan Dragon", "Craw Wurm"])
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Death's Duet", action
    cast_chosen_instant(game, 0, action)
    settle(game)
    assert sorted(card.name for card in game.players[0].hand) == ["Craw Wurm", "Shivan Dragon"]


def test_the_reading_ranks_what_can_arrive_first():
    """The reading itself: for the battlefield, a card that can be put there
    before a dearer one that cannot; for a hand, any card by its worth."""
    game = _seat(graveyard=[_ZOMBIE_RITE, "Scathe Zombies"])
    options = [{"seat": 0, "index": 0}, {"seat": 0, "index": 1}]
    assert best_graveyard_return(game, 0, options, "battlefield")["index"] == 1
    assert best_graveyard_return(game, 0, options[:1], "battlefield") is None
    assert best_graveyard_return(game, 0, options[:1], "hand")["index"] == 0
