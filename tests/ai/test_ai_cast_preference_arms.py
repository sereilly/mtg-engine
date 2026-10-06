"""The preference arms in ``ai_policy._can_cast_with_targets`` ask the engine.

Found by the mode chooser's census and true of spells with no mode at all.
Two of the three arms answered "is there something worth pointing this at"
with a matcher of their own:

* the **destroy** arm compared a permanent's printed, collapsed type word with
  the instruction's ``type_filter`` — so an artifact creature (whose word is
  "creature") was no artifact, and a filter naming several types, which is a
  list, matched nothing: Pillage, Creeping Mold, Fissure, Eliminate and
  Finishing Blow were never cast by an AI seat;
* the **pump** arm asked for a creature on the caster's own board, for a kind
  that also prints "-4/-4".

And the burn weights in the scorer reached every spell with a damage step, so
damage that can only be dealt to a creature scored as game-winning burn.

``test_ai_one_target_cast_census.py`` is the pool-wide sweep.
"""
from __future__ import annotations

from engine.ai_policy import cast_announcement, choose_cast_action
from engine.game import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, _mk_creature_card, _nosick, resolve_stack


def _duel(hand=(), mine=(), theirs=()):
    ai = PlayerState(
        name="AI", hand=list(hand),
        battlefield=[_nosick(Permanent(card=c)) for c in mine],
    )
    opp = PlayerState(
        name="Opp", battlefield=[_nosick(Permanent(card=c)) for c in theirs],
    )
    game = Game(players=[ai, opp])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._sync_control()
    return game


def _cast(game, action):
    result = game.cast_from_hand(0, action.card_name, **cast_announcement(action))
    assert result.supported, result.details
    resolve_stack(game)


def _names(cards):
    return sorted(card.name for card in cards)


GOLEM = _mk_card(
    name="Their Golem", type_line="Artifact Creature - Golem", power=3, toughness=3,
)


# --- The destroy arm ---------------------------------------------------------------


def test_a_destroy_naming_several_types_is_cast(catalog_by_name):
    """"Destroy target artifact or land": the filter is a list, and a list
    equals no type word."""
    land = _mk_card(name="Their Tower", type_line="Land")
    game = _duel(hand=[catalog_by_name["Pillage"]], theirs=[land])

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Pillage"
    _cast(game, action)
    assert _names(game.players[1].graveyard) == ["Their Tower"]


def test_finishing_blow_is_cast_at_a_creature(catalog_by_name):
    """"Destroy target creature or planeswalker" — the same list."""
    bear = _mk_creature_card("Their Bear", 2, 2)
    game = _duel(hand=[catalog_by_name["Finishing Blow"]], theirs=[bear])

    action = choose_cast_action(game, 0)

    assert action is not None
    _cast(game, action)
    assert _names(game.players[1].graveyard) == ["Their Bear"]


def test_shatter_is_cast_at_an_artifact_creature(catalog_by_name):
    """An artifact creature's printed type collapses to "creature"; the engine
    asks ``has_type``, and the arm asks the engine."""
    game = _duel(hand=[catalog_by_name["Shatter"]], theirs=[GOLEM])

    action = choose_cast_action(game, 0)

    assert action is not None
    assert game.permanent_by_id(action.target_permanent_ids[0]).card is GOLEM
    _cast(game, action)
    assert _names(game.players[1].graveyard) == ["Their Golem"]


def test_a_filtered_destroy_still_wants_the_opponents_board(catalog_by_name):
    """The preference the arm was written for is unchanged: with the only
    artifact on the caster's own side, Shatter stays in hand."""
    game = _duel(hand=[catalog_by_name["Shatter"]], mine=[GOLEM])

    assert choose_cast_action(game, 0) is None


# --- The pump arm --------------------------------------------------------------------


def test_a_shrinking_pump_needs_no_creature_of_its_casters(catalog_by_name):
    """Grasp of Darkness is ``pump_target_creature_until_eot`` with -4/-4, and
    the arm held it until the caster controlled a creature."""
    bear = _mk_creature_card("Their Bear", 2, 2)
    game = _duel(hand=[catalog_by_name["Grasp of Darkness"]], theirs=[bear])

    action = choose_cast_action(game, 0)

    assert action is not None and action.target_player_index == 1
    _cast(game, action)
    assert _names(game.players[1].graveyard) == ["Their Bear"]


def test_the_sign_decides_the_board_for_an_invented_card():
    """Name-free: the same template under another name, both signs."""
    shrink = _mk_card(
        name="Wither Probe", mana_cost="{B}", type_line="Instant",
        oracle_text="Target creature gets -3/-3 until end of turn.",
    )
    grow = _mk_card(
        name="Swell Probe", mana_cost="{G}", type_line="Instant",
        oracle_text="Target creature gets +3/+3 until end of turn.",
    )
    assert compile_card_oracle(shrink).supported and compile_card_oracle(grow).supported
    mine = _mk_creature_card("Own Bear", 2, 2)
    theirs = _mk_creature_card("Their Bear", 2, 2)

    # The gift wants the caster's own creature, and is held without one.
    assert choose_cast_action(_duel(hand=[grow], theirs=[theirs]), 0) is None
    game = _duel(hand=[grow], mine=[mine], theirs=[theirs])
    action = choose_cast_action(game, 0)
    assert action is not None
    assert game.permanent_by_id(action.target_permanent_ids[0]).card is mine

    # The penalty wants the opponent's, and is held with only the caster's own.
    assert choose_cast_action(_duel(hand=[shrink], mine=[mine]), 0) is None
    game = _duel(hand=[shrink], theirs=[theirs])
    action = choose_cast_action(game, 0)
    assert action is not None
    assert game.permanent_by_id(action.target_permanent_ids[0]).card is theirs
    _cast(game, action)
    assert _names(game.players[1].graveyard) == ["Their Bear"]


# --- Which spells the burn weights reach -----------------------------------------------


def test_damage_that_cannot_reach_a_face_is_not_lethal_burn():
    """Five damage to a *creature* with the opponent at five life scored the
    ten and twelve points "burn that closes the game" is worth, and tied the
    spell that really does close it — the tie going to hand order."""
    sear = _mk_card(
        name="Sear Probe", mana_cost="{R}", type_line="Instant",
        oracle_text="Sear Probe deals 5 damage to target creature.",
    )
    axe = _mk_card(
        name="Axe Probe", mana_cost="{R}", type_line="Sorcery",
        oracle_text="Axe Probe deals 5 damage to target player.",
    )
    assert compile_card_oracle(sear).supported and compile_card_oracle(axe).supported
    game = _duel(hand=[sear, axe], theirs=[_mk_creature_card("Their Bear", 2, 2)])
    game.players[1].life = 5

    action = choose_cast_action(game, 0)

    assert action is not None and action.card_name == "Axe Probe"
    _cast(game, action)
    assert game.players[1].life == 0


def test_creature_only_burn_is_still_cast_at_a_creature():
    sear = _mk_card(
        name="Sear Probe", mana_cost="{R}", type_line="Instant",
        oracle_text="Sear Probe deals 5 damage to target creature.",
    )
    game = _duel(hand=[sear], theirs=[_mk_creature_card("Their Bear", 2, 2)])

    action = choose_cast_action(game, 0)

    assert action is not None and action.target_player_index == 1
    _cast(game, action)
    assert _names(game.players[1].graveyard) == ["Their Bear"]
    assert game.players[1].life == 20


# --- An effect guarded by a condition on its own target --------------------------------


def test_a_blast_is_not_spent_on_a_permanent_of_the_wrong_colour(catalog_by_name):
    """"Destroy target permanent **if it's blue**" (Pyroblast) may legally
    name any permanent — that is the difference between it and Red Elemental
    Blast — and does nothing to one that is not blue. With the mode chooser a
    seat holding it weighed that bullet in every main phase, and across ten
    seeded Ice Age games cast it ten times at the wrong colour."""
    elf = _mk_card(
        name="Their Elf", type_line="Creature - Elf", colors=("G",), power=1, toughness=1,
    )
    merfolk = _mk_card(
        name="Their Merfolk", type_line="Creature - Merfolk", colors=("U",),
        power=1, toughness=1,
    )
    card = catalog_by_name["Pyroblast"]
    wasted = _duel(hand=[card], theirs=[elf])
    assert 1 in wasted.announceable_modes(0, card), "a legal announcement all the same"
    assert choose_cast_action(wasted, 0) is None

    game = _duel(hand=[card], theirs=[elf, merfolk])
    action = choose_cast_action(game, 0)
    assert action is not None and action.mode_index == 1
    assert game.permanent_by_id(action.target_permanent_ids[0]).card is merfolk
    _cast(game, action)
    assert _names(game.players[1].graveyard) == ["Their Merfolk"]
    assert _names(p.card for p in game.players[1].battlefield) == ["Their Elf"]


def test_a_guarded_kill_names_the_creature_it_would_kill(catalog_by_name):
    """Soul Rend prints no mode and was aimed the same way: "Destroy target
    creature if it's white" at the first creature across the table. It also
    draws a card, so with no white creature it is still a cast — and with
    one, that is the creature named."""
    elf = _mk_card(
        name="Their Elf", type_line="Creature - Elf", colors=("G",), power=1, toughness=1,
    )
    knight = _mk_card(
        name="Their Knight", type_line="Creature - Knight", colors=("W",),
        power=2, toughness=2,
    )
    card = catalog_by_name["Soul Rend"]
    game = _duel(hand=[card], theirs=[elf, knight])

    action = choose_cast_action(game, 0)

    assert action is not None
    assert game.permanent_by_id(action.target_permanent_ids[0]).card is knight
    _cast(game, action)
    assert _names(game.players[1].graveyard) == ["Their Knight"]

    cantrip = _duel(hand=[card], theirs=[elf])
    assert choose_cast_action(cantrip, 0) is not None, "the card it draws is not nothing"


def test_a_guard_that_holds_for_nothing_keeps_the_spell_in_hand(catalog_by_name):
    """Barrin's Unmaking returns its target "if that permanent shares a color
    with the most common color among all permanents" and does nothing else:
    at a colourless artifact it is a card thrown away."""
    relic = _mk_card(name="Their Relic", type_line="Artifact")
    merfolk = _mk_card(
        name="Their Merfolk", type_line="Creature - Merfolk", colors=("U",),
        power=1, toughness=1,
    )
    elf = _mk_card(
        name="Their Elf", type_line="Creature - Elf", colors=("G",), power=1, toughness=1,
    )
    card = catalog_by_name["Barrin's Unmaking"]

    assert choose_cast_action(_duel(hand=[card], theirs=[relic]), 0) is None

    game = _duel(hand=[card], theirs=[elf, merfolk, merfolk])
    action = choose_cast_action(game, 0)
    assert action is not None
    named = game.permanent_by_id(action.target_permanent_ids[0])
    assert named.card is merfolk, "blue is the most common colour; the Elf is spared"
    _cast(game, action)
    assert _names(game.players[1].hand) == ["Their Merfolk"]
