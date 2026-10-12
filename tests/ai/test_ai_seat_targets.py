"""Census: the seat an AI names for an ability that targets a player — or
"any target" — is its own when the effect is a gift.

``ai_policy._choose_target_for_instruction`` decides the seat, and it decided
with a list of instruction kinds: ``draw_target_cards``, ``gain_life`` and
``prevent_damage`` went to the activator and everything else to an opponent.
Two of the three are names no handler has — the grammar lowers those effects
to ``target_gains_life`` and ``grant_prevention_shield`` — so a kind list that
was a claim about the pool had expired: "{W}, {T}: Target player gains 1 life"
(Mournful Zombie) gave its life to the opponent, and so did every "prevent the
next 1 damage that would be dealt to any target" in the pool, Samite Healer
first among nineteen.

Which effects are gifts is ``ai_valuation.ability_seat_side`` now, read off the
compiled program step by step. This census asks it of every activated ability
in both manifest roles whose target can be a player's face, in three ways:

* the policy names the seat the derivation says (the weight has one reader);
* a gift is really one — activated at its controller's own seat through the
  engine, that seat ends up with more life, more cards, or a shield;
* and a seat the card prints as an opponent's is never read as a gift.

Before the derivation, of the abilities the AI proposes on the census board,
17 gifts were announced at the opponent: Mournful Zombie's life, fifteen
shields (Alabaster Wall, Amulet of Kroog, Clergy en-Vec, Combat Medic, Elvish
Healer, Femeref Healer, Master Healer, Orim, Samite Healer, Raka Disciple,
Samite Archer, Samite Healer, Sanctum Custodian, Sanctum Guardian, Serra
Paladin, Treefolk Healer) and Rakalite's — and one was announced at the
activator, Xira Arien's draw, the only kind on the old list that exists.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_policy import _choose_target_for_instruction, choose_activation_action
from engine.ai_valuation import ability_seat_side
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.shields import shields_on
from engine.targeting import derive_activation_spec, usable_activated_abilities
from tests.helpers import _mk_card, _nosick, resolve_stack

#: The spec kinds whose candidates include a player's face — the picker's own
#: set (``ai_valuation._SEAT_SPEC_KINDS``), spelled here so the census does not
#: borrow its population from the code it is checking.
_SEAT_KINDS = ("player", "player_or_planeswalker", "any")


def _pool() -> list:
    return list(compilation_units(load_cards(manifest_set_paths(include_measured=True))))


@pytest.fixture(scope="module")
def pool():
    return _pool()


@pytest.fixture(scope="module")
def by_name(pool):
    names: dict = {}
    for card in pool:
        names.setdefault(card.name, card)
    return names


def seat_abilities(pool) -> list[tuple]:
    """``(card, ability index, ability)`` for every usable activated ability of
    a supported permanent whose target may be a player."""
    found = []
    for card in pool:
        program = compile_card_oracle(card)
        if not program.supported or card.primary_type in ("instant", "sorcery"):
            continue
        for index, ability in enumerate(usable_activated_abilities(program)):
            if ability.instruction is None:
                continue
            spec = derive_activation_spec(ability) or {}
            if spec.get("kind") in _SEAT_KINDS:
                found.append((card, index, ability))
    return found


def _table(by_name, card) -> tuple:
    """Seat 0 controls *card* at its main phase; each seat has a vanilla
    creature, a hand, a library and a graveyard, and is at 12 life."""
    def bait(name):
        return _nosick(Permanent(card=_mk_card(
            name=name, type_line="Creature - Human", power=2, toughness=2,
        )))

    source = _nosick(Permanent(card=card))
    game = Game(players=[
        PlayerState(
            name=name, battlefield=board, life=12,
            hand=[by_name["Forest"]] * 3, library=[by_name["Forest"]] * 10,
            graveyard=[by_name["Grizzly Bears"]],
        )
        for name, board in (("A", [source, bait("Mine")]), ("B", [bait("Theirs")]))
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    return game, source


def _better_off(game, before) -> bool:
    """Whether seat 0 has more life or more cards than *before*, or holds a
    shield it did not."""
    player = game.players[0]
    return (
        player.life > before[0]
        or len(player.hand) > before[1]
        or len(shields_on(player)) > before[2]
    )


def test_the_policy_names_the_seat_the_program_says(pool, by_name):
    """Every seat ability: a gift names the activator, anything else an
    opponent, and a printed "target opponent" is never a gift."""
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    abilities = seat_abilities(pool)
    gifts = []
    for card, index, ability in abilities:
        side = ability_seat_side(ability.instruction)
        named = _choose_target_for_instruction(ability.instruction, 0, game)
        assert named == (0 if side == "you" else 1), (card.name, index, side, named)
        if side == "you":
            gifts.append(f"{card.name}#{index}")
            spec = derive_activation_spec(ability) or {}
            assert not spec.get("opponents_only"), (card.name, index)

    assert len(abilities) >= 180, len(abilities)
    assert len(gifts) >= 25, gifts
    for name in ("Mournful Zombie#0", "Tonic Peddler#0", "Samite Healer#0", "Xira Arien#0"):
        assert name in gifts, (name, gifts)


def test_what_the_program_calls_a_gift_leaves_its_own_seat_better_off(pool, by_name):
    """The derivation, held to the game: each ability it calls a gift is
    activated at its controller's own seat through the engine, and that seat
    then has more life, more cards or a shield. A kind added to the gift table
    that is no gift fails here on the card that prints it."""
    examined, unreached = 0, []
    for card, index, ability in seat_abilities(pool):
        if ability_seat_side(ability.instruction) != "you":
            continue
        game, _source = _table(by_name, card)
        player = game.players[0]
        before = (player.life, len(player.hand), len(shields_on(player)))
        # "{X}{X}, {T}: Prevent the next X damage…" (Panacea): an X of zero is
        # a shield of nothing, so an ability that announces one announces 2.
        announces_x = "{x}" in (ability.source_line or "").lower().split(":", 1)[0]
        if not game.is_on_battlefield(_source):
            # A permanent that does not outlive its first upkeep with nothing
            # paid for it (fading with no counters: Defender en-Vec).
            unreached.append(f"{card.name}#{index}: left the battlefield")
            continue
        result = game.activate_permanent_ability(
            0, card.name, ability_index=index, target_player_index=0,
            **({"x_value": 2} if announces_x else {}),
        )
        if not result.supported:
            unreached.append(f"{card.name}#{index}: {result.details[:60]}")
            continue
        resolve_stack(game)
        game.auto_resolve_pending_choices()
        examined += 1
        assert _better_off(game, before), (card.name, index, game.log[-4:])

    assert examined >= 20, (examined, unreached)


def test_the_ai_proposes_its_gifts_at_itself(pool, by_name):
    """The proposal, which is what a game sees: for every permanent whose
    first usable ability is a gift to a seat, the action the AI proposes names
    its own seat or is not proposed at all — never an opponent."""
    proposed = 0
    for card, index, ability in seat_abilities(pool):
        if index != 0 or ability_seat_side(ability.instruction) != "you":
            continue
        game, _source = _table(by_name, card)
        action = choose_activation_action(game, 0)
        if action is None or action.permanent_name != card.name:
            continue
        proposed += 1
        assert action.target_player_index == 0, (card.name, action)

    assert proposed >= 17, proposed
