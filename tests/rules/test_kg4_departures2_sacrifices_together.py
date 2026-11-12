"""A loop whose repetitions each sacrifice at an answer makes every sacrifice
at once, by its last step (CR 101.4, 603.10a, 701.21a).

"For each creature, its controller sacrifices a permanent of their choice
unless they pay {1}." (Fade Away.) Its ruling (2004-10-04): "each player
counts up the number of creatures they control, then they make the required
number of payments and/or sacrifices. The active player announces their
choices first followed by the other players, but all the sacrifices are done
at the same time. Because of this, you can't sacrifice one creature in order to
pay for another and thereby avoid payment for the first." Read the Runes ("You
draw the cards, then sacrifice any permanents you want to sacrifice, then
discard"), Oath of Lim-Dûl ("for each 1 life you lost, sacrifice a permanent …
unless you discard a card") and Tariff ("Each player sacrifices the creature
they control with the greatest mana value unless they pay that creature's mana
cost"; its ruling, 2008-04-01: "All creatures sacrificed this way are
sacrificed at the same time") are the same shape, and so is an offer to each
opponent whose decline is a sacrifice (Rishadan Cutpurse: "each opponent
sacrifices a permanent of their choice unless they pay {1}"; CR 101.4: "Then
the actions happen simultaneously").

Each repetition used to sacrifice at its own answer, outside any event, so on
614442be: an observer the first repetition took — Moonlit Wake ("Whenever a
creature dies, you gain 1 life"), Havoc Jester ("Whenever you sacrifice a
permanent", which "triggers when you sacrifice it. If you sacrifice other
permanents at the same time, it triggers for them as well"), Massacre Wurm —
saw none of the rest go; and a creature sacrificed for another's repetition was
gone before its own was asked, so it was never paid for. Now the loop's
sacrifices are held and made together (``sacrificing_together_through``), a held
permanent is no candidate for another, and Fade Away's repetitions are asked in
APNAP order.

The census at the bottom finds every loop in the pool whose body sacrifices at
an answer, and holds the set to the boards driven here.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, load_catalog, manifest_set_paths
from engine.models import Permanent
from engine.oracle import compiled_units
from tests.helpers import settle

_CARDS = {card.name: card for card in load_catalog()}


def _table(interactive=()) -> Game:
    game = Game(players=[
        PlayerState(name=f"P{i}", library=[_CARDS["Plains"]] * 10) for i in range(2)
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    game.interactive_seats = set(interactive)
    return game


def _set_down(game: Game, seat: int, name: str) -> Permanent:
    permanent = Permanent(card=_CARDS[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    game._sync_control()
    return permanent


def _cast(game: Game, seat: int, name: str, **kwargs) -> None:
    game.players[seat].hand.append(_CARDS[name])
    result = game.cast_from_hand(seat, name, **kwargs)
    assert result.supported, result


def _answer(game: Game, sacrifices: list[str], *, take_offers: bool) -> None:
    """Answer every prompt the table owes as a person would: each offer taken
    or declined, each sacrifice the next name of *sacrifices*, each trigger
    aimed at P1."""
    for _ in range(60):
        owed = game.waiting_prompt()
        if owed is None:
            if game.stack:
                game.resolve_top_of_stack(pause_for_choices=True)
                continue
            return
        if owed.kind == "optional_pay":
            assert game.confirm_optional_pay(owed.player_index, accept=take_offers)
        elif owed.kind == "sacrifice":
            name = sacrifices.pop(0)
            perm = next(
                p for p in game.controlled_by(owed.player_index) if p.card.name == name
            )
            assert game.confirm_sacrifice(
                owed.player_index, permanent_ids=[perm.permanent_id]
            ), (name, game.log[-4:])
        elif owed.kind == "trigger_target":
            assert game.confirm_trigger_target(owed.player_index, seat=1)
        else:
            raise AssertionError(owed.kind)
    raise AssertionError(game.log[-8:])


def _resolved(game: Game, name: str) -> int:
    return sum(1 for line in game.log if line == f"{name} ability resolved")


def _names(game: Game, seat: int) -> list[str]:
    return sorted(p.card.name for p in game.controlled_by(seat))


# --- Fade Away ---------------------------------------------------------------

@pytest.mark.cr("603.10a", "101.4")
def test_fade_away_headless_an_observer_given_up_first_sees_the_rest_die():
    """No one can pay {1}; the default gives up the Moonlit Wake (power 0)
    first. It sees both Bears die with it: one event."""
    game = _table()
    _set_down(game, 0, "Moonlit Wake")
    _set_down(game, 0, "Grizzly Bears")
    _set_down(game, 0, "Hill Giant")
    _set_down(game, 1, "Grizzly Bears")
    _cast(game, 0, "Fade Away")
    game.enforce_mana_costs = True
    settle(game)
    assert _names(game, 0) == ["Hill Giant"] and _names(game, 1) == []
    assert game.players[0].life == 22, game.log[-10:]


@pytest.mark.cr("603.10a", "701.21a")
def test_fade_away_havoc_jester_given_up_first_hears_the_second_sacrifice():
    game = _table(interactive={0})
    _set_down(game, 0, "Havoc Jester")
    _set_down(game, 0, "Grizzly Bears")
    _cast(game, 0, "Fade Away")
    game.enforce_mana_costs = True
    game.resolve_top_of_stack(pause_for_choices=True)
    _answer(game, ["Havoc Jester", "Grizzly Bears"], take_offers=False)
    assert _names(game, 0) == []
    assert _resolved(game, "Havoc Jester") == 2, game.log[-10:]
    assert game.players[1].life == 18


@pytest.mark.cr("101.4")
def test_fade_away_a_creature_given_up_for_another_is_still_paid_for():
    """"You can't sacrifice one creature in order to pay for another and
    thereby avoid payment for the first": two creatures, two sacrifices."""
    game = _table(interactive={0})
    _set_down(game, 0, "Grizzly Bears")
    _set_down(game, 0, "Hill Giant")
    _set_down(game, 0, "Plains")
    _cast(game, 0, "Fade Away")
    game.enforce_mana_costs = True
    game.resolve_top_of_stack(pause_for_choices=True)
    _answer(game, ["Hill Giant", "Plains"], take_offers=False)
    assert _names(game, 0) == ["Grizzly Bears"]


@pytest.mark.cr("101.4", "101.4b")
def test_fade_away_asks_the_active_player_first():
    """"The active player announces their choices first followed by the other
    players" — with seat 1 active, its creature's repetition is asked first."""
    game = _table(interactive={0, 1})
    _set_down(game, 0, "Grizzly Bears")
    _set_down(game, 1, "Hill Giant")
    game.active_player_index = 1
    _cast(game, 1, "Fade Away")
    game.enforce_mana_costs = True
    game.resolve_top_of_stack(pause_for_choices=True)
    _answer(game, ["Hill Giant", "Grizzly Bears"], take_offers=False)
    chose = [line for line in game.log if " to sacrifice (Fade Away)" in line]
    assert chose == [
        "P1 chose Hill Giant to sacrifice (Fade Away)",
        "P0 chose Grizzly Bears to sacrifice (Fade Away)",
    ], chose


# --- Read the Runes, Oath of Lim-Dûl, Tariff ---------------------------------

@pytest.mark.cr("603.10a", "701.21a")
def test_read_the_runes_sacrifices_paid_for_two_discards_are_one_event():
    game = _table(interactive={0})
    _set_down(game, 0, "Havoc Jester")
    _set_down(game, 0, "Grizzly Bears")
    _cast(game, 0, "Read the Runes", x_value=2)
    game.resolve_top_of_stack(pause_for_choices=True)
    _answer(game, ["Havoc Jester", "Grizzly Bears"], take_offers=True)
    assert _names(game, 0) == []
    assert len(game.players[0].hand) == 2, "both discards were bought off"
    assert _resolved(game, "Havoc Jester") == 2, game.log[-10:]


@pytest.mark.cr("603.10a", "701.21a")
def test_read_the_runes_a_held_permanent_is_no_price_for_another_discard():
    """One permanent, three cards drawn: the second and third tolls cannot be
    paid with the permanent the first already gave up — they are discards."""
    game = _table(interactive={0})
    _set_down(game, 0, "Grizzly Bears")
    _cast(game, 0, "Read the Runes", x_value=3)
    game.resolve_top_of_stack(pause_for_choices=True)
    offers = []
    for _ in range(40):
        owed = game.waiting_prompt()
        if owed is None:
            break
        if owed.kind == "optional_pay":
            offers.append(owed)
            assert game.confirm_optional_pay(0, accept=True), game.log[-4:]
        elif owed.kind == "sacrifice":
            bears = next(p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears")
            assert game.confirm_sacrifice(0, permanent_ids=[bears.permanent_id])
        elif owed.kind == "discard":
            assert game.confirm_discard(0, [0])
        else:
            raise AssertionError(owed.kind)
    assert len(offers) == 1, "the held Bears is no price for the next toll"
    assert _names(game, 0) == []
    assert sum(1 for line in game.log if "sacrificed Grizzly Bears" in line) == 1
    assert len(game.players[0].hand) == 1, game.log[-10:]


@pytest.mark.cr("603.10a")
def test_oath_of_lim_dul_sacrifices_for_each_life_lost_together():
    """Three damage with an empty hand: three sacrifices, the Moonlit Wake
    (taken first) seeing the two creatures die with it."""
    game = _table()
    _set_down(game, 0, "Oath of Lim-Dûl")
    _set_down(game, 0, "Moonlit Wake")
    _set_down(game, 0, "Grizzly Bears")
    _set_down(game, 0, "Hill Giant")
    game.check_state_based_actions()
    _cast(game, 1, "Lightning Bolt", target_player_index=0)
    settle(game)
    assert _names(game, 0) == ["Oath of Lim-Dûl"]
    assert game.players[0].life == 17 + 2, game.log[-10:]


@pytest.mark.cr("603.10a", "101.4")
@pytest.mark.parametrize("interactive", [(), (0, 1)])
def test_tariff_the_seats_sacrifices_are_one_event(interactive):
    """The active player's Massacre Wurm, given up first, sees the other
    seat's creature die: "Whenever a creature an opponent controls dies, that
    creature's controller loses 2 life"."""
    game = _table(interactive)
    _set_down(game, 0, "Massacre Wurm")
    _set_down(game, 1, "Grizzly Bears")
    _cast(game, 0, "Tariff")
    game.enforce_mana_costs = True
    if interactive:
        game.resolve_top_of_stack(pause_for_choices=True)
        _answer(game, [], take_offers=False)
    settle(game)
    assert _names(game, 0) == [] and _names(game, 1) == []
    assert game.players[1].life == 18, game.log[-10:]


# --- An offer to several seats ------------------------------------------------

@pytest.mark.cr("603.10a", "101.4")
def test_each_opponents_sacrifice_unless_they_pay_is_one_event():
    """Rishadan Cutpurse: "When this creature enters, each opponent
    sacrifices a permanent of their choice unless they pay {1}." Two
    opponents, neither able to pay: the first gives up its Moonlit Wake and
    sees the second's Grizzly Bears die with it."""
    game = Game(players=[
        PlayerState(name=f"P{i}", library=[_CARDS["Plains"]] * 10) for i in range(3)
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    _set_down(game, 1, "Moonlit Wake")
    _set_down(game, 2, "Grizzly Bears")
    _cast(game, 0, "Rishadan Cutpurse")
    game.enforce_mana_costs = True
    settle(game)
    assert _names(game, 1) == [] and _names(game, 2) == []
    assert game.players[1].life == 21, game.log[-10:]


@pytest.mark.cr("603.10a", "101.4")
def test_possessed_portal_each_players_sacrifice_unless_they_discard_is_one_event(
    set_pool,
):
    """Possessed Portal (5DN): "At the beginning of each end step, each player
    sacrifices a permanent of their choice unless they discard a card." The
    offer is each player's in turn, the active player's first (CR 101.4), and
    with empty hands (the Portal's own "skips that draw" sees to that) each
    sacrifices: the active player gives up its Moonlit Wake and the other its
    Grizzly Bears, and the two sacrifices are one event — the Wake, given up
    first, sees the Bears die with it."""
    game = _table((0, 1))
    portal = Permanent(card=set_pool("5DN")["Possessed Portal"])
    portal.metadata["summoning_sickness_turn"] = -99
    game.players[0].battlefield.append(portal)
    game._sync_control()
    _set_down(game, 0, "Moonlit Wake")
    _set_down(game, 1, "Grizzly Bears")
    asked: list[int] = []
    confirm = game.confirm_sacrifice

    def sacrifice(seat, *args, **kwargs):
        asked.append(seat)
        return confirm(seat, *args, **kwargs)

    game.confirm_sacrifice = sacrifice
    game.resolve_end_step(0)
    _answer(game, ["Moonlit Wake", "Grizzly Bears"], take_offers=False)
    settle(game)
    assert asked == [0, 1]
    assert _names(game, 0) == ["Possessed Portal"] and _names(game, 1) == []
    assert game.players[0].life == 21, game.log[-10:]


# --- The census ----------------------------------------------------------------

#: Every loop in the pool whose body sacrifices at an answer, and the board
#: above that drives it. A handler that loops over seats itself, with a
#: sacrifice in its own steps, names its kind here (the compiled program shows
#: one instruction and no loop).
_DRIVEN = {
    "Fade Away": "test_fade_away_*",
    # The offer to each opponent: one board drives the shape for the three.
    "Rishadan Brigand": "test_each_opponents_sacrifice_unless_they_pay_is_one_event",
    "Rishadan Cutpurse": "test_each_opponents_sacrifice_unless_they_pay_is_one_event",
    "Rishadan Footpad": "test_each_opponents_sacrifice_unless_they_pay_is_one_event",
    # The same offer to every player with a discard for the price (Fifth Dawn,
    # measured: in this census's population under MTG_PROMOTE=5DN).
    "Possessed Portal": "test_possessed_portal_each_players_sacrifice_unless_they_discard_is_one_event",
    "Read the Runes": "test_read_the_runes_*",
    "Oath of Lim-Dûl": "test_oath_of_lim_dul_*",
    "Tariff": "test_tariff_*",
}
#: An offer to several seats whose sacrifice is the **price** a taker pays,
#: with a consequence behind it: one seat's act after another, not held.
_SEQUENTIAL = {
    "Argothian Wurm": (
        "any player may sacrifice a land; if a player does, the Wurm goes on "
        "top of its library - \"but then all remaining players still get the "
        "option\" (2007-02-01): each taker's act and its consequence in turn"
    ),
    "Prowling Pangolin": (
        "Argothian Wurm's shape (\"any player may sacrifice two creatures … "
        "If a player does, sacrifice this creature\")"
    ),
    "Longhorn Firebeast": (
        "any opponent may take 5 damage; the sacrifice is the source's own, "
        "the consequence of a taker's act"
    ),
}
_LOOPING_HANDLERS = {
    "each_player_pays_or_sacrifices_greatest": (
        "Tariff: per seat a tie-break choice and an offer whose decline is "
        "``sacrifice_recorded_permanent``, run as one resumable loop"
    ),
}


def _steps_of(instruction):
    for value in (instruction.payload or {}).values():
        if hasattr(value, "kind"):
            yield value
        elif isinstance(value, (list, tuple)):
            yield from (item for item in value if hasattr(item, "kind"))


def _walk(instruction):
    yield instruction
    for step in _steps_of(instruction):
        yield from _walk(step)


def _roots(program):
    yield from program.instructions
    for ability in program.triggered_abilities:
        if ability.instruction is not None:
            yield ability.instruction
    for ability in program.activated_abilities:
        if getattr(ability, "instruction", None) is not None:
            yield ability.instruction


#: The offers made to several seats, one after another.
_SEVERAL_SEATS = frozenset({"each_player", "each_opponent"})


@pytest.mark.cr("603.10a")
def test_every_loop_whose_body_sacrifices_is_driven():
    """By shape, over every compiled unit: a ``for_each`` with any sacrifice
    kind anywhere in its body, an offer to several seats with one in a
    branch, or a looping handler from the table above.

    Over **both manifest roles**, so a measured set's loop is found the day
    its card compiles rather than at its promotion rehearsal (Possessed
    Portal was found only under ``MTG_PROMOTE=5DN``), and the table above
    names the same cards whether or not the set is promoted."""
    examined = 0
    found: dict[str, set[str]] = {}
    pool = load_cards(manifest_set_paths(include_measured=True))
    for card, program in compiled_units(pool):
        if not program.supported:
            continue
        for root in _roots(program):
            for node in _walk(root):
                if node.kind in _LOOPING_HANDLERS:
                    found.setdefault(card.name, set()).add(node.kind)
                several = (
                    node.kind == "may"
                    and (node.payload or {}).get("actor") in _SEVERAL_SEATS
                )
                if node.kind != "for_each" and not several:
                    continue
                examined += 1
                kinds = {
                    inner.kind for step in _steps_of(node) for inner in _walk(step)
                    if "sacrifice" in inner.kind
                }
                if kinds:
                    found.setdefault(card.name, set()).update(kinds)
    assert examined >= 40, examined
    assert set(found) == set(_DRIVEN) | set(_SEQUENTIAL), sorted(
        set(found) ^ (set(_DRIVEN) | set(_SEQUENTIAL))
    )
    for name in _SEQUENTIAL:
        del found[name]
    # Every sacrifice those loops make is one the hold takes.
    from engine.handlers.control_flow import HELD_SACRIFICE_KINDS

    loose = {
        name: kinds - HELD_SACRIFICE_KINDS - set(_LOOPING_HANDLERS)
        for name, kinds in found.items()
    }
    assert not any(loose.values()), loose
