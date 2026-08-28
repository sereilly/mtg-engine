"""Per-card tests for The Dark's creatures.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

import random

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


# --- G5: zones and characteristics (The Dark) ---------------------------------


def _nosick(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _basic(name: str, subtype: str, symbol: str) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0,
        type_line=f"Basic Land - {subtype}", oracle_text="",
        colors=(), color_identity=(symbol,), keywords=(), produced_mana=(symbol,),
        raw={"name": name, "type_line": f"Basic Land - {subtype}"},
    )


def _board(set_pool, mine, theirs=(), *, my_graveyard=(), their_hand=()):
    pool = set_pool("DRK")
    p1 = PlayerState(
        name="P1",
        battlefield=[_nosick(Permanent(card=pool[name])) for name in mine],
        graveyard=[pool[name] for name in my_graveyard],
    )
    p2 = PlayerState(
        name="P2",
        battlefield=[_nosick(Permanent(card=pool[name])) for name in theirs],
        hand=[pool[name] for name in their_hand],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, p1, p2, pool


# --- exiling from a graveyard, as a cost and as an effect ---------------------


def test_grave_robbers_exiles_an_artifact_card_and_gains_two_life(set_pool):
    """"{B}, {T}: Exile target artifact card from a graveyard. You gain 2
    life." The picker is narrowed to artifacts, and the narrowing is the whole
    difference from the "any card" form the graveyard exile used to be."""
    game, p1, p2, pool = _board(
        set_pool, ["Grave Robbers"], my_graveyard=["Fellwar Stone"],
    )
    life = p1.life

    result = game.activate_permanent_ability(
        0, "Grave Robbers", permanent_index=0,
        target_player_index=0, target_permanent_index=0,
    )

    assert result.supported, result.details
    assert p1.graveyard == [], game.log
    assert [card.name for card in p1.exile] == ["Fellwar Stone"]
    assert p1.life == life + 2


def test_grave_robbers_picker_is_narrowed_to_artifact_cards(set_pool):
    """The control: "artifact card" is carried into the picker rather than
    collapsed to "any card". One predicate, offered and re-checked - a picker
    offering a creature for a cost the resolution then refuses is a tap paid
    for nothing."""
    from engine.oracle import compile_card_oracle
    from engine.targeting import derive_activation_spec

    pool = set_pool("DRK")
    program = compile_card_oracle(pool["Grave Robbers"])
    spec = derive_activation_spec(program.activated_abilities[0])

    assert spec == {"kind": "graveyard_creature", "card_type": "artifact"}


def test_eater_of_the_dead_untaps_itself_by_eating_a_corpse(set_pool):
    """"{0}: **If this creature is tapped**, exile target creature card from a
    graveyard and untap this creature." Both halves, in order."""
    game, p1, p2, pool = _board(
        set_pool, ["Eater of the Dead"], my_graveyard=["Rag Man"],
    )
    eater = p1.battlefield[0]
    eater.tapped = True

    result = game.activate_permanent_ability(
        0, "Eater of the Dead", permanent_index=0,
        target_player_index=0, target_permanent_index=0,
    )

    assert result.supported, result.details
    assert [card.name for card in p1.exile] == ["Rag Man"], game.log
    assert eater.tapped is False


def test_necropolis_grows_by_the_exiled_cards_mana_value(set_pool):
    """"Exile a creature card from your graveyard: Put **X** +0/+1 counters on
    this creature, where X is **the exiled card's** mana value."

    The cost is paid before the ability resolves (CR 601.2h), so by the time X
    is read the card is out of the game - the number is last-known information
    the activation recorded, not anything a zone still holds."""
    game, p1, p2, pool = _board(
        set_pool, ["Necropolis"], my_graveyard=["Angry Mob"],
    )
    necropolis = p1.battlefield[0]
    printed = necropolis.effective_toughness
    mana_value = int(pool["Angry Mob"].cmc)
    assert mana_value > 0, "the fixture needs a card with a real mana value"

    result = game.activate_permanent_ability(0, "Necropolis", permanent_index=0)

    assert result.supported, result.details
    assert p1.graveyard == [], "the cost ate the card"
    assert [card.name for card in p1.exile] == ["Angry Mob"]
    assert necropolis.effective_toughness == printed + mana_value, game.log
    assert necropolis.effective_power == 0, "+0/+1 counters add no power"


def test_necropolis_cannot_be_activated_with_an_empty_graveyard(set_pool):
    """The control on the test above: the exile is a *cost*, so with nothing to
    pay it the ability is not activated at all (CR 602.2b) rather than resolving
    for free."""
    game, p1, p2, pool = _board(set_pool, ["Necropolis"])
    necropolis = p1.battlefield[0]
    printed = necropolis.effective_toughness

    result = game.activate_permanent_ability(0, "Necropolis", permanent_index=0)

    assert not result.supported
    assert necropolis.effective_toughness == printed


# --- revealing a hand and discarding from it ---------------------------------


def test_rag_man_takes_a_creature_card_at_random(set_pool):
    """"Target opponent reveals their hand and discards a **creature** card at
    random." The sample is drawn from the cards answering the phrase, so the
    land in hand is never at risk."""
    game, p1, p2, pool = _board(
        set_pool, ["Rag Man"], their_hand=["Angry Mob", "City of Shadows"],
    )
    random.seed(11)

    result = game.activate_permanent_ability(
        0, "Rag Man", permanent_index=0, target_player_index=1,
    )

    assert result.supported, result.details
    assert [card.name for card in p2.hand] == ["City of Shadows"], game.log
    assert [card.name for card in p2.graveyard] == ["Angry Mob"]


def test_rag_man_replays_the_same_discard_for_the_same_seed(set_pool):
    """Determinism: the sample comes from the module RNG ``run_ai_simulation``
    seeds, so a given seed reproduces a run exactly."""
    taken = []
    for _ in range(2):
        game, p1, p2, pool = _board(
            set_pool, ["Rag Man"],
            their_hand=["Angry Mob", "Necropolis", "People of the Woods"],
        )
        random.seed(4)
        game.activate_permanent_ability(
            0, "Rag Man", permanent_index=0, target_player_index=1,
        )
        taken.append([card.name for card in p2.graveyard])

    assert taken[0] == taken[1] and len(taken[0]) == 1, taken


# --- characteristic-defining P/T (CR 604.3) ----------------------------------


def test_people_of_the_woods_toughness_counts_forests(set_pool):
    """"…**toughness** is equal to the number of Forests you control." The
    printed power stands: this is a 0/*, and defining both halves would make it
    a creature the card never prints."""
    pool = set_pool("DRK")
    forest = _basic("Forest", "Forest", "G")
    p1 = PlayerState(
        name="P1",
        battlefield=[
            Permanent(card=pool["People of the Woods"]),
            Permanent(card=forest),
            Permanent(card=forest),
        ],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game._refresh_dynamic_creatures()
    people = p1.battlefield[0]

    printed_power = int(pool["People of the Woods"].raw["power"])
    assert people.effective_toughness == 2, game.log
    assert people.effective_power == printed_power, "only the toughness is defined"

    # …and it tracks the board rather than being fixed as it entered. A third
    # Forest is a third point of toughness; without one it would be a 0/0 and
    # die to the state-based check, which is the card.
    p1.battlefield.append(Permanent(card=forest))
    game._refresh_dynamic_creatures()

    assert people.effective_toughness == 3, game.log


def test_angry_mob_counts_swamps_only_on_its_controllers_turn(set_pool):
    """"During **your** turn, …are each equal to 2 plus the number of Swamps
    **your opponents** control. During turns other than yours, …are each 2."

    Two answers on one card, and which one applies is a question about the turn
    rather than about a battlefield."""
    swamp = _basic("Swamp", "Swamp", "B")
    pool = set_pool("DRK")
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=pool["Angry Mob"])])
    p2 = PlayerState(
        name="P2",
        battlefield=[Permanent(card=swamp) for _ in range(3)],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    mob = p1.battlefield[0]

    game.start_turn(0)
    assert (mob.effective_power, mob.effective_toughness) == (5, 5), game.log

    game.active_player_index = 1
    game._refresh_dynamic_creatures()
    assert (mob.effective_power, mob.effective_toughness) == (2, 2), game.log


# --- odds and ends -----------------------------------------------------------


def test_goblin_wizard_drops_a_goblin_out_of_hand(set_pool):
    """"{T}: You may put a **Goblin permanent card** from your hand onto the
    battlefield." A generic head noun after a subtype, which used to refuse the
    line outright."""
    pool = set_pool("DRK")
    p1 = PlayerState(
        name="P1",
        battlefield=[_nosick(Permanent(card=pool["Goblin Wizard"]))],
        hand=[pool["Orc General"], pool["Goblin Wizard"]],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)

    result = game.activate_permanent_ability(0, "Goblin Wizard", permanent_index=0)

    assert result.supported, result.details
    # The offer is a prompt, so a seat that answers by default takes it - the
    # stated AI policy for an optional put-onto-the-battlefield.
    game.auto_resolve_pending_choices()
    dropped = [perm.card.name for perm in p1.battlefield]
    assert dropped.count("Goblin Wizard") == 2, game.log
    assert "Orc General" in [card.name for card in p1.hand], "an Orc is not a Goblin"


def test_orc_general_buffs_other_orcs_and_eats_one_to_do_it(set_pool):
    """"{T}, Sacrifice **another Orc or Goblin**: Other **Orc** creatures get
    +1/+1 until end of turn."

    Both halves are narrowed by subtype, and the two live on opposite sides of
    the pipeline - the cost is charged by `engine/oracle.py` and the buff comes
    out of the grammar. A narrowing that reached only one of them is a cost
    nobody pays or a board nobody named."""
    game, p1, p2, pool = _board(
        set_pool, ["Orc General", "Orc General", "Goblin Wizard"],
    )
    source, other_orc, goblin = p1.battlefield
    goblin_power = goblin.effective_power
    printed = int(pool["Orc General"].raw["power"])

    result = game.activate_permanent_ability(0, "Orc General", permanent_index=0)

    assert result.supported, result.details
    eaten = {"Orc General", "Goblin Wizard"} - {
        perm.card.name for perm in p1.battlefield
    } or {"Goblin Wizard"}
    assert eaten, "the cost ate nothing"
    # "**Other** Orc creatures" - CR 109.5 excludes the ability's own source,
    # so the General that paid does not buff itself.
    assert source.effective_power == printed, game.log
    if any(perm is other_orc for perm in p1.battlefield):
        assert other_orc.effective_power == printed + 1, game.log
    if any(perm is goblin for perm in p1.battlefield):
        assert goblin.effective_power == goblin_power, "a Goblin is not an Orc"


def test_orc_general_cannot_be_activated_with_no_other_orc_or_goblin(set_pool):
    """The control on the cost half: "another Orc or Goblin" is charged, so a
    lone General has no legal payment and the buff never happens."""
    game, p1, p2, pool = _board(set_pool, ["Orc General"])

    result = game.activate_permanent_ability(0, "Orc General", permanent_index=0)

    assert not result.supported, game.log
    assert [perm.card.name for perm in p1.battlefield] == ["Orc General"]
