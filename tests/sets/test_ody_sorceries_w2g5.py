"""Odyssey sorceries, wave 2 group 5: Cultural Exchange.

"Choose any number of creatures target player controls. Choose the same number
of creatures another target player controls. Those players exchange control of
those creatures. (This effect lasts indefinitely.)"

One card and its own file, because the type files beside this one are at the
size cap. Scryfall lists **no rulings** for it (``rulings_uri`` returned an
empty list, 2026-10-12), so everything asserted here rests on the printed
words and the Comprehensive Rules, cited where they decide something:

* CR 115.1a / 115.3 — only the two players are targets, and "another" is what
  makes them two different players;
* CR 608.2d — the creatures are chosen as the spell resolves, by its
  controller, and a choice that cannot be done cannot be made;
* CR 701.12a-b — an exchange that cannot be completed does nothing at all,
  and each player gains control of what the other controlled, at once;
* CR 608.2b — one illegal target and the spell still resolves, doing what it
  can; every target illegal and it does not resolve.

Cards come from ``set_pool("ODY")`` (``tests/sets/README.md``).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.control import BASE_CONTROLLER, control_changes
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.stack_targets import chosen_targets
from engine.targeting import derive_cast_spec
from engine.target_roles import ROLE_SEATS
from tests.helpers import _mk_card, _mk_creature_card

NAME = "Cultural Exchange"


def _table(card, creatures=(2, 3), *, interactive=(0,), caster=0) -> Game:
    """A table with ``creatures[seat]`` vanilla creatures per seat, costs off,
    *card* in *caster*'s hand. A seat in *interactive* is asked its decisions."""
    game = Game(players=[PlayerState(name=f"P{seat}") for seat in range(len(creatures))])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for seat, count in enumerate(creatures):
        for number in range(count):
            game._put_permanent_onto_battlefield(
                seat,
                Permanent(card=_mk_creature_card(f"Seat {seat} Bear {number}", 2, 2)),
                None,
            )
    game.players[caster].hand.append(card)
    return game


def _cast(game, refs, *, caster=0, name=NAME):
    return game.queue_from_hand(caster, name, target_role_refs=refs)


def _names(game, seat) -> list[str]:
    return sorted(permanent.card.name for permanent in game.controlled_by(seat))


def _owed(game):
    """The one pick the game is waiting on, as ``(seat, ceiling, floor,
    candidate names)``, or None."""
    choice = game.waiting_prompt()
    if choice is None:
        return None
    return (
        choice.player_index, choice.data["up_to"], choice.data["at_least"],
        sorted(permanent.card.name for permanent in choice.data["_candidates"]),
    )


def _ids(game, seat, count) -> list[int]:
    return [permanent.permanent_id for permanent in game.controlled_by(seat)][:count]


# --------------------------------------------------------------------------
# What it compiles to, and what it announces
# --------------------------------------------------------------------------


def test_cultural_exchange_is_two_picks_and_an_exchange(set_pool):
    card = set_pool("ODY")[NAME]
    program = compile_card_oracle(card)

    assert program.supported
    (sequence,) = program.instructions
    first, second, exchange = sequence.payload["steps"]
    assert [step.kind for step in (first, second, exchange)] == [
        "choose_permanents", "choose_permanents", "exchange_control_of_chosen_sets",
    ]
    assert first.payload["unbounded"] and first.payload["filter"] == {"type_filter": "creature"}
    assert second.payload["same_number_as"] == first.payload["result_key"]
    # Each pick spends its own role of one shared announcement.
    assert first.payload["targets"]["role"] == "player"
    assert second.payload["targets"]["role"] == "another player"
    assert first.payload["targets"]["roles"] == second.payload["targets"]["roles"]
    assert second.payload["targets"]["roles"][1]["distinct"] is True


def test_cultural_exchange_targets_two_players_and_nothing_else(set_pool):
    """CR 115.1a: the spell targets where it says "target" — twice, a player
    each time. The creatures are not in the announcement at all."""
    card = set_pool("ODY")[NAME]

    spec = derive_cast_spec(card, compile_card_oracle(card))

    assert spec["kind"] == "roles"
    assert [role["kind"] for role in spec["roles"]] == ["player", "player"]


def test_cultural_exchange_picker_never_offers_one_player_twice(set_pool):
    """CR 115.3 with the printed "another": the second role's list is every
    other player."""
    card = set_pool("ODY")[NAME]
    game = _table(card, creatures=(1, 1, 1))

    offered = game.cast_target_spec(0, card)["valid_targets"]

    assert [entry["seat"] for entry in offered] == [0, 1, 2]
    for entry in offered:
        assert entry["kind"] == "player"
        assert [step["seat"] for step in entry["next"]] == [
            seat for seat in (0, 1, 2) if seat != entry["seat"]
        ]


@pytest.mark.parametrize(
    "announcement, reason",
    [
        ({"target_role_refs": [{"seat": 1}, {"seat": 1}]}, "no valid target"),
        ({"target_role_refs": [{"seat": 0}, {"seat": 0}]}, "no valid target"),
        ({"target_role_refs": [{"seat": 1}]}, "requires 2 targets"),
        ({"target_role_refs": [{"seat": 1}, {"seat": 7}]}, "no valid target"),
        # One seat field cannot name two players, whichever player it names.
        ({"target_player_index": 1}, "requires 2 targets"),
        ({}, "requires 2 targets"),
    ],
)
def test_cultural_exchange_refuses_an_announcement_that_is_not_two_players(
    set_pool, announcement, reason,
):
    card = set_pool("ODY")[NAME]
    game = _table(card)
    game.enforce_mana_costs = True
    game.players[0].mana_pool["U"] = 6

    result = game.queue_from_hand(0, NAME, **announcement)

    assert not result.supported
    assert reason in result.details
    # CR 601.2c comes before CR 601.2h: nothing was spent.
    assert game.players[0].mana_pool["U"] == 6
    assert game.players[0].hand == [card]
    assert not game.stack


def test_cultural_exchange_cannot_name_a_player_who_cannot_be_targeted(set_pool):
    """"You have shroud." (Ivory Mask, CR 702.18a.) And a player who has left
    the game is nobody's target (CR 800.4a)."""
    card = set_pool("ODY")[NAME]
    mask = set_pool("MMQ")["Ivory Mask"]

    shrouded = _table(card, creatures=(1, 1, 1))
    shrouded._put_permanent_onto_battlefield(2, Permanent(card=mask), None)
    assert not _cast(shrouded, [{"seat": 1}, {"seat": 2}]).supported
    assert _cast(shrouded, [{"seat": 1}, {"seat": 0}]).supported

    departed = _table(card, creatures=(1, 1, 1))
    departed.players[2].lost = True
    assert not _cast(departed, [{"seat": 2}, {"seat": 1}]).supported
    assert departed.players[0].hand == [card]


def test_cultural_exchange_records_both_players_on_the_stack(set_pool):
    card = set_pool("ODY")[NAME]
    game = _table(card, creatures=(1, 1, 1))

    assert _cast(game, [{"seat": 2}, {"seat": 1}]).supported

    (item,) = game.stack
    assert item.choices[ROLE_SEATS] == [2, 1]
    # The scalar still names a player the spell really targets: the first.
    assert item.target_player_index == 2
    assert [(target.position, target.kind, target.seat) for target in chosen_targets(game, item)] == [
        (0, "player", 2), (1, "player", 1),
    ]


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------


def test_cultural_exchange_caster_picks_a_set_then_matches_it(set_pool):
    """The caster makes both picks (CR 608.2d), the first bounded by what the
    second can match and the second exactly as many."""
    card = set_pool("ODY")[NAME]
    game = _table(card, creatures=(2, 3))
    assert _cast(game, [{"seat": 1}, {"seat": 0}]).supported

    game.resolve_top_of_stack()

    # Seat 0 is asked, about seat 1's three creatures — and may take two,
    # because seat 0 has two to give back.
    assert _owed(game) == (
        0, 2, 0, ["Seat 1 Bear 0", "Seat 1 Bear 1", "Seat 1 Bear 2"],
    )
    assert not game.confirm_permanent_set_choice(0, _ids(game, 1, 3))
    taken = _ids(game, 1, 2)
    assert game.confirm_permanent_set_choice(0, taken)

    # …then exactly two of its own, no fewer.
    assert _owed(game) == (0, 2, 2, ["Seat 0 Bear 0", "Seat 0 Bear 1"])
    assert not game.confirm_permanent_set_choice(0, _ids(game, 0, 1))
    given = _ids(game, 0, 2)
    assert game.confirm_permanent_set_choice(0, given)

    assert game.waiting_prompt() is None
    assert _names(game, 0) == ["Seat 1 Bear 0", "Seat 1 Bear 1"]
    assert _names(game, 1) == ["Seat 0 Bear 0", "Seat 0 Bear 1", "Seat 1 Bear 2"]
    assert [entry.name for entry in game.players[0].graveyard] == [NAME]


def test_cultural_exchange_lasts_past_the_turn_and_the_creatures_are_new_arrivals(set_pool):
    """"This effect lasts indefinitely": two plain layer-2 contributions with
    no duration, so cleanup ends nothing. CR 302.6: each creature came under
    its new controller's control this turn."""
    card = set_pool("ODY")[NAME]
    game = _table(card, creatures=(1, 1))
    (mine,) = game.controlled_by(0)
    (theirs,) = game.controlled_by(1)
    for permanent in (mine, theirs):
        permanent.metadata["summoning_sickness_turn"] = -99
    assert _cast(game, [{"seat": 0}, {"seat": 1}]).supported
    game.resolve_top_of_stack()
    assert game.confirm_permanent_set_choice(0, [mine.permanent_id])
    assert game.confirm_permanent_set_choice(0, [theirs.permanent_id])

    assert game.controller_index_of(mine) == 1
    assert game.controller_index_of(theirs) == 0
    assert game._is_summoning_sick(mine) and game._is_summoning_sick(theirs)
    for permanent in (mine, theirs):
        assert [entry["until_eot"] for entry in control_changes(permanent)] == [False]
    # Neither creature changed owner (CR 108.3).
    assert mine.metadata[BASE_CONTROLLER] == 0
    assert theirs.metadata[BASE_CONTROLLER] == 1

    game.resolve_cleanup_step(0)

    assert game.controller_index_of(mine) == 1
    assert game.controller_index_of(theirs) == 0


def test_cultural_exchange_holds_the_stack_until_both_picks_are_made(set_pool):
    """One resolution (CR 608.2): on the path a table plays through, the spell
    stays on the stack, held, until its last decision is answered — and the
    second pick is armed by answering the first."""
    card = set_pool("ODY")[NAME]
    game = _table(card, creatures=(1, 1), interactive=(0, 1))
    assert _cast(game, [{"seat": 1}, {"seat": 0}]).supported

    game.resolve_top_of_stack(pause_for_choices=True)

    (item,) = game.stack
    assert item.resolution_held
    # Its instructions have run as far as the first question; asked again, it
    # is mid-resolution and does not move.
    assert not game.resolve_top_of_stack(pause_for_choices=True)
    assert game.waiting_prompt().kind == "permanent_set_choice"
    assert game.players[0].graveyard == []
    assert game.confirm_permanent_set_choice(0, _ids(game, 1, 1))
    assert game.stack and game.waiting_prompt().data["at_least"] == 1
    assert game.confirm_permanent_set_choice(0, _ids(game, 0, 1))

    assert not game.stack
    assert [entry.name for entry in game.players[0].graveyard] == [NAME]


def test_cultural_exchange_may_choose_nothing(set_pool):
    """"Any number" includes none (CR 107.1c reads the phrase for a count):
    then there is no second pick and nothing changes hands."""
    card = set_pool("ODY")[NAME]
    game = _table(card)
    before = (_names(game, 0), _names(game, 1))
    assert _cast(game, [{"seat": 1}, {"seat": 0}]).supported
    game.resolve_top_of_stack()

    assert game.confirm_permanent_set_choice(0, [])

    assert game.waiting_prompt() is None
    assert (_names(game, 0), _names(game, 1)) == before
    assert [entry.name for entry in game.players[0].graveyard] == [NAME]


def test_cultural_exchange_first_pick_is_bounded_by_the_second_board(set_pool):
    """CR 701.12a: an exchange that cannot be completed does nothing, so a
    first pick the second player cannot match is the pick of none — and
    CR 608.2d does not offer a choice that cannot be done."""
    card = set_pool("ODY")[NAME]

    short = _table(card, creatures=(3, 1))
    assert _cast(short, [{"seat": 0}, {"seat": 1}]).supported
    short.resolve_top_of_stack()
    assert _owed(short)[:3] == (0, 1, 0)
    assert not short.confirm_permanent_set_choice(0, _ids(short, 0, 2))

    empty = _table(card, creatures=(3, 0))
    assert _cast(empty, [{"seat": 0}, {"seat": 1}]).supported
    empty.resolve_top_of_stack()
    # Nothing to match with, so nothing is asked at all.
    assert empty.waiting_prompt() is None
    assert len(_names(empty, 0)) == 3
    assert [entry.name for entry in empty.players[0].graveyard] == [NAME]


def test_cultural_exchange_between_two_other_players(set_pool):
    """Four seats, and the caster is neither target: it still makes both
    picks, and its own board is untouched."""
    card = set_pool("ODY")[NAME]
    game = _table(card, creatures=(1, 2, 2, 1))
    assert _cast(game, [{"seat": 1}, {"seat": 2}]).supported
    game.resolve_top_of_stack()

    assert _owed(game)[0] == 0
    assert game.confirm_permanent_set_choice(0, _ids(game, 1, 2))
    assert _owed(game)[:3] == (0, 2, 2)
    assert game.confirm_permanent_set_choice(0, _ids(game, 2, 2))

    assert _names(game, 0) == ["Seat 0 Bear 0"]
    assert _names(game, 1) == ["Seat 2 Bear 0", "Seat 2 Bear 1"]
    assert _names(game, 2) == ["Seat 1 Bear 0", "Seat 1 Bear 1"]
    assert _names(game, 3) == ["Seat 3 Bear 0"]


def test_cultural_exchange_chooses_creatures_it_could_not_target(set_pool):
    """CR 115.10a: a creature is *chosen*, not targeted, so shroud and
    protection from blue stop nothing."""
    card = set_pool("ODY")[NAME]
    game = _table(card, creatures=(1, 0))
    warded = Permanent(card=_mk_card(
        "Warded Bear", "{1}{G}", "Creature — Bear", "Shroud\nProtection from blue",
    ))
    game._put_permanent_onto_battlefield(1, warded, None)
    assert _cast(game, [{"seat": 1}, {"seat": 0}]).supported
    game.resolve_top_of_stack()

    assert _owed(game)[3] == ["Warded Bear"]
    assert game.confirm_permanent_set_choice(0, [warded.permanent_id])
    assert game.confirm_permanent_set_choice(0, _ids(game, 0, 1))

    assert game.controller_index_of(warded) == 0


def test_cultural_exchange_only_exchanges_creatures(set_pool):
    card = set_pool("ODY")[NAME]
    game = _table(card, creatures=(1, 1))
    game._put_permanent_onto_battlefield(
        1, Permanent(card=_mk_card("Trinket", "{1}", "Artifact", "")), None,
    )
    assert _cast(game, [{"seat": 1}, {"seat": 0}]).supported
    game.resolve_top_of_stack()

    assert _owed(game)[3] == ["Seat 1 Bear 0"]


# --------------------------------------------------------------------------
# CR 608.2b
# --------------------------------------------------------------------------


@pytest.mark.parametrize("shrouded", [1, 2])
def test_cultural_exchange_does_nothing_when_one_player_became_illegal(set_pool, shrouded):
    """One target illegal: the spell still resolves, the step about that
    player does not happen, and the exchange cannot be completed — so the
    caster is not asked to choose creatures that will not move."""
    card = set_pool("ODY")[NAME]
    mask = set_pool("MMQ")["Ivory Mask"]
    game = _table(card, creatures=(1, 2, 2))
    assert _cast(game, [{"seat": 1}, {"seat": 2}]).supported
    before = [_names(game, seat) for seat in range(3)]

    game._put_permanent_onto_battlefield(shrouded, Permanent(card=mask), None)
    assert game.illegal_targets_refusal(game.stack[-1]) is None
    game.resolve_top_of_stack()

    assert game.waiting_prompt() is None
    assert [
        [name for name in _names(game, seat) if name != "Ivory Mask"]
        for seat in range(3)
    ] == before
    assert any("resolved and moved to graveyard" in line for line in game.log)


def test_cultural_exchange_does_not_resolve_when_both_players_became_illegal(set_pool):
    card = set_pool("ODY")[NAME]
    mask = set_pool("MMQ")["Ivory Mask"]
    game = _table(card, creatures=(1, 2, 2))
    assert _cast(game, [{"seat": 1}, {"seat": 2}]).supported

    for seat in (1, 2):
        game._put_permanent_onto_battlefield(seat, Permanent(card=mask), None)
    game.resolve_top_of_stack()

    assert game.waiting_prompt() is None
    assert any("every target is illegal (608.2b)" in line for line in game.log)
    assert [entry.name for entry in game.players[0].graveyard] == [NAME]


def test_cultural_exchange_does_nothing_when_a_named_player_has_left(set_pool):
    card = set_pool("ODY")[NAME]
    game = _table(card, creatures=(1, 2, 2))
    assert _cast(game, [{"seat": 1}, {"seat": 2}]).supported

    game.players[1].lost = True
    game.resolve_top_of_stack()

    assert game.waiting_prompt() is None
    assert _names(game, 2) == ["Seat 2 Bear 0", "Seat 2 Bear 1"]


# --------------------------------------------------------------------------
# A seat nobody is asking, a copy, and the same words on another card
# --------------------------------------------------------------------------


@pytest.mark.parametrize("refs", [[{"seat": 0}, {"seat": 1}], [{"seat": 1}, {"seat": 0}]])
def test_cultural_exchange_default_gives_nothing_away(set_pool, refs):
    """A seat with nobody to ask takes "any number" as none, whichever player
    it named first — the prompt's standing default would have handed over the
    caster's own creatures in board order."""
    card = set_pool("ODY")[NAME]
    game = _table(card, interactive=())
    before = (_names(game, 0), _names(game, 1))

    assert game.cast_from_hand(0, NAME, target_role_refs=refs).supported

    assert (_names(game, 0), _names(game, 1)) == before
    assert [entry.name for entry in game.players[0].graveyard] == [NAME]


def test_a_copy_of_cultural_exchange_keeps_both_players(set_pool):
    """CR 707.10: a copy has the same targets. Both of them."""
    card = set_pool("ODY")[NAME]
    game = _table(card, creatures=(1, 1, 1))
    game.players[0].hand.append(set_pool("LEA")["Fork"])
    assert _cast(game, [{"seat": 2}, {"seat": 1}]).supported
    assert game.queue_from_hand(0, "Fork", target_stack_index=0).supported

    game.resolve_top_of_stack()

    original, copy = game.stack
    assert copy.is_copy
    assert [(target.kind, target.seat) for target in chosen_targets(game, copy)] == [
        ("player", 2), ("player", 1),
    ]
    # The copy resolves against its own two players.
    game.resolve_top_of_stack()
    assert _owed(game)[3] == ["Seat 2 Bear 0"]
    assert game.confirm_permanent_set_choice(0, _ids(game, 2, 1))
    assert game.confirm_permanent_set_choice(0, _ids(game, 1, 1))
    assert _names(game, 1) == ["Seat 2 Bear 0"]
    assert _names(game, 2) == ["Seat 1 Bear 0"]


def test_the_same_paragraph_with_other_nouns_is_the_same_effect():
    """No name is read anywhere: a card printing the paragraph over artifacts
    and lands, and against an opponent, compiles to the same three steps and
    plays the same way."""
    barter = _mk_card(
        "Barter Test", "{2}{U}", "Sorcery",
        "Choose any number of artifacts target opponent controls. Choose the "
        "same number of lands another target player controls. Those players "
        "exchange control of those permanents.",
    )
    program = compile_card_oracle(barter)
    assert program.supported
    first, second, _exchange = program.instructions[0].payload["steps"]
    assert first.payload["filter"] == {"type_filter": "artifact"}
    assert second.payload["filter"] == {"type_filter": "land"}
    assert first.payload["targets"]["roles"][0].get("opponents_only") is True

    game = _table(barter, creatures=(0, 0))
    relic = Permanent(card=_mk_card("Relic", "{1}", "Artifact", ""))
    field = Permanent(card=_mk_card("Field", "", "Land", ""))
    game._put_permanent_onto_battlefield(1, relic, None)
    game._put_permanent_onto_battlefield(0, field, None)
    # "Target opponent": the caster cannot name itself for the first role.
    assert not _cast(game, [{"seat": 0}, {"seat": 1}], name="Barter Test").supported
    assert _cast(game, [{"seat": 1}, {"seat": 0}], name="Barter Test").supported
    game.resolve_top_of_stack()
    assert game.confirm_permanent_set_choice(0, [relic.permanent_id])
    assert game.confirm_permanent_set_choice(0, [field.permanent_id])

    assert game.controller_index_of(relic) == 0
    assert game.controller_index_of(field) == 1


def test_a_closing_noun_that_names_neither_set_is_not_this_paragraph():
    """"Those players exchange control of those **enchantments**" after two
    sets of creatures is a sentence about objects nobody chose; the production
    refuses rather than exchanging the creatures."""
    wrong = _mk_card(
        "Wrong Noun Test", "{2}{U}", "Sorcery",
        "Choose any number of creatures target player controls. Choose the "
        "same number of creatures another target player controls. Those "
        "players exchange control of those enchantments.",
    )

    assert not compile_card_oracle(wrong).supported


# --------------------------------------------------------------------------
# The sweep the other way: the resolution with the announcement gate off
# --------------------------------------------------------------------------


def test_cultural_exchange_resolution_does_not_lean_on_the_gate(set_pool, monkeypatch):
    """The resolution now trusts a per-role seat list, so it is asked what it
    does with one no gate checked. One player named for both roles: the picks
    are made off one board and CR 701.12b exchanges nothing. A seat that does
    not exist: its step is skipped, the other side has nothing to match, and
    nobody is asked anything."""
    card = set_pool("ODY")[NAME]
    monkeypatch.setattr(
        Game, "_validate_cast_targets", lambda self, *args, **kwargs: (True, "valid"),
    )

    game = _table(card, creatures=(2, 2))
    before = (_names(game, 0), _names(game, 1))
    assert _cast(game, [{"seat": 1}, {"seat": 1}]).supported
    game.resolve_top_of_stack()
    first, second = _ids(game, 1, 2)
    assert game.confirm_permanent_set_choice(0, [first])
    assert game.confirm_permanent_set_choice(0, [second])
    assert (_names(game, 0), _names(game, 1)) == before
    assert any("could not be completed" in line for line in game.log)

    game = _table(card, creatures=(2, 2))
    assert _cast(game, [{"seat": 1}, {"seat": 9}]).supported
    game.resolve_top_of_stack()
    assert game.waiting_prompt() is None
    assert (_names(game, 0), _names(game, 1)) == before
