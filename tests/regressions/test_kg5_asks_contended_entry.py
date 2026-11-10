"""Census: an entry two "would enter" replacements contend for is put to the
affected player (CR 616.1, 616.1e), and answering it finishes the entry and
the continuation of whatever made it.

Land Equilibrium's ruling (2009-10-01): "If a land that would enter has its
own 'If [this land] would enter' replacement effect, the player who will
control that land chooses which replacement effect to apply. After applying
one, if the other one would still be applicable, it's then applied." On the
base of round kg5 (59f133e63) the entry seam (``ZoneFunnelsMixin._begin_entry``)
raised its ``would_enter_battlefield`` event with no way to re-run it, so
every seat — a person included — took the default order: an Alliances land's
unpaid toll ahead of Land Equilibrium, Containment Priest's exile ahead of a
toll on a creature nobody cast.

One board per shape, each through a real entry point — a land play, Show and
Tell's one event, a put with a continuation — with seat 0 the affected
player. Each checks the seat nobody asks is not asked and is the reference;
the interactive seat is asked once with the permanent in no zone and the
continuation not yet run; the first answer reproduces the reference; the
second is honoured. Worms of the Earth is a CR 614.17 "can't" and is never one
of the options (614.17c).
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import resolve_stack, settle

_POOL = {card.name: card for card in load_catalog()}


def _game(interactive: bool) -> Game:
    game = Game(players=[
        PlayerState(f"P{index}", library=[_POOL["Island"]] * 8) for index in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.begin_turn_bookkeeping(0)
    game.resolve_untap_step(0)
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    return game


def _put(game: Game, seat: int, name: str) -> Permanent:
    permanent = Permanent(card=_POOL[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    resolve_stack(game)
    game.pending_choices.clear()
    game.pending_replacement_choices.clear()
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _where(game: Game, name: str) -> list[str]:
    found = []
    for seat, player in enumerate(game.players):
        for zone in ("hand", "graveyard", "exile", "library"):
            found += [f"P{seat}.{zone}"] * sum(
                1 for held in getattr(player, zone) if held.name == name
            )
    found += ["battlefield"] * sum(
        1 for permanent in game.all_permanents() if permanent.card.name == name
    )
    return sorted(found)


def _lands(game: Game, seat: int) -> int:
    return sum(1 for permanent in game.controlled_by(seat) if permanent.has_type("land"))


def _asked(game: Game) -> list:
    return [c for c in game.pending_choices if c.kind == "effect_order"]


def _answer(game: Game, option: int) -> None:
    choice = _asked(game)[0]
    assert game.resolve_pending_choice(
        "effect_order", choice.player_index, option_index=option,
    )


def _play(game: Game, name: str) -> None:
    game.players[0].hand.append(_POOL[name])
    result = game.queue_from_hand(0, name)
    assert result.supported, result.details


# ---------------------------------------------------------------------------
# One driver per board: (the contended card, where the second answer puts it,
# the run up to the question)
# ---------------------------------------------------------------------------


def _equilibrium_lake(game):
    """A land play: Lake of the Dead with no Swamp to pay for it, under an
    opponent's Land Equilibrium (two lands against one: "at least as many")."""
    _put(game, 0, "Forest")
    _put(game, 0, "Forest")
    _put(game, 1, "Land Equilibrium")
    _put(game, 1, "Forest")
    return "Lake of the Dead", ["P0.graveyard"], lambda: _play(game, "Lake of the Dead")


def _priest_lake_living_plane(game):
    """A land play under Living Plane ("All lands are 1/1 creatures"): a
    played land is not cast (CR 305.1), so Containment Priest's exile and the
    Lake's unpaid toll both reach it."""
    _put(game, 0, "Forest")
    _put(game, 1, "Living Plane")
    _put(game, 1, "Containment Priest")
    return "Lake of the Dead", ["P0.graveyard"], lambda: _play(game, "Lake of the Dead")


_CASES = [
    ("Land Equilibrium / Lake of the Dead", _equilibrium_lake),
    ("Containment Priest / Lake of the Dead under Living Plane", _priest_lake_living_plane),
]


def _run(driver, interactive: bool):
    game = _game(interactive)
    name, alternative, run = driver(game)
    run()
    return game, name, alternative


@pytest.mark.parametrize("label,driver", _CASES, ids=[c[0] for c in _CASES])
def test_a_contended_entry_is_asked_and_the_answer_finishes_it(label, driver):
    reference, name, alternative = _run(driver, interactive=False)
    assert not _asked(reference), f"{label}: a seat nobody asks was asked"
    settle(reference)
    expected = _where(reference, name)
    assert expected and "battlefield" not in expected, (label, expected)
    lands = _lands(reference, 0)

    game, *_ = _run(driver, interactive=True)
    asked = _asked(game)
    assert len(asked) == 1, f"{label}: {[(c.kind, c.data) for c in game.pending_choices]}"
    assert asked[0].player_index == 0
    assert asked[0].data["event_kind"] == "would_enter_battlefield"
    assert len(asked[0].data["options"]) == 2, asked[0].data["options"]
    # Nothing of the entry has happened: the land is in no zone.
    assert _where(game, name) == [], (label, _where(game, name))

    _answer(game, 0)
    settle(game)
    assert _where(game, name) == expected, (label, _where(game, name), expected)
    assert _lands(game, 0) == lands, label
    assert not game.resume_stack and not game.pending_choices and not game.stack, label
    assert not game.effect_order_answers, (label, game.effect_order_answers)

    other, *_ = _run(driver, interactive=True)
    _answer(other, 1)
    settle(other)
    assert _where(other, name) == alternative, (label, _where(other, name))
    assert not other.effect_order_answers, (label, other.effect_order_answers)


def test_land_equilibrium_applied_first_still_takes_its_land():
    """Land Equilibrium chosen ahead of the toll: its modified event — "puts
    that land onto the battlefield then sacrifices a land" — is what the toll
    then modifies, and only its entry (CR 614.6: "A modified event occurs
    instead"; 616.1f), so the Lake goes to the graveyard **and** a land is
    sacrificed. The order a seat nobody asks takes (the toll first) leaves no
    event for Land Equilibrium to modify."""
    game, name, _ = _run(_equilibrium_lake, interactive=True)
    assert "Land Equilibrium" in _asked(game)[0].data["options"][1]
    _answer(game, 1)
    settle(game)
    assert _where(game, name) == ["P0.graveyard"]
    assert _lands(game, 0) == 1
    assert sorted(card.name for card in game.players[0].graveyard) == [
        "Forest", "Lake of the Dead",
    ]


def _until_asked(game: Game):
    """Answer by default every prompt but CR 616.1e's question; return it
    (or None once the game is at rest)."""
    for _ in range(50):
        owed = settle(game, defaults=False)
        if owed is None or owed.kind == "effect_order":
            return owed
        game.take_choice_default(owed)
    raise AssertionError("never came to rest")


def _show_and_tell(interactive: bool, *, mine=(), theirs=(), held, given=None):
    game = _game(interactive)
    for name in mine:
        _put(game, 0, name)
    for name in theirs:
        _put(game, 1, name)
    game.players[0].hand[:] = [_POOL[held], _POOL["Show and Tell"]]
    game.players[1].hand[:] = [_POOL[given]] if given else []
    assert game.queue_from_hand(0, "Show and Tell").supported
    return game


def test_a_newcomer_whose_entry_asks_leaves_the_event_and_the_rest_enter():
    """Show and Tell's one event: seat 1's Grizzly Bears enters with the event
    (Soul Warden sees it), while seat 0's Lake — whose entry asks — leaves it
    and is finished alone at the answer. Show and Tell stays on the stack until
    then (CR 608.2: its resolution is not over)."""
    game = _show_and_tell(
        True, mine=("Forest", "Forest"),
        theirs=("Land Equilibrium", "Forest", "Soul Warden"),
        held="Lake of the Dead", given="Grizzly Bears",
    )
    life = game.players[1].life
    owed = _until_asked(game)
    assert owed is not None and owed.data["event_kind"] == "would_enter_battlefield"
    assert _where(game, "Grizzly Bears") == ["battlefield"]
    assert _where(game, "Lake of the Dead") == []
    # (Soul Warden's trigger for the Bears waits above it.)
    assert "Show and Tell" in [item.card.name for item in game.stack]

    _answer(game, 0)
    settle(game)
    assert _where(game, "Lake of the Dead") == ["P0.graveyard"]
    assert _where(game, "Show and Tell") == ["P0.graveyard"]
    assert game.players[1].life == life + 1
    assert not game.stack and not game.pending_choices


def test_a_cant_is_never_offered_as_a_contender():
    """Worms of the Earth beside Land Equilibrium and the Lake's unpaid toll:
    three effects apply, and nobody is asked — "Lands can't enter the
    battlefield" is not a replacement effect (CR 614.17) and an event that
    can't happen is replaced by nothing but a self-replacement effect
    (614.17c).

    (Where the land ends up is not asserted: Worms' ruling, 2004-10-04, keeps
    it "where it is", and the engine's can't leaves it in no zone once the
    road has taken it from the hand — a defect of the can't's own, on the
    base as well, recorded in round kg5 `asks`'s report.)"""
    game = _show_and_tell(
        True, mine=("Forest",), theirs=("Worms of the Earth", "Land Equilibrium"),
        held="Lake of the Dead",
    )
    assert _until_asked(game) is None
    assert "battlefield" not in _where(game, "Lake of the Dead")
    assert "P0.graveyard" not in _where(game, "Lake of the Dead")
    assert any("Lake of the Dead can't enter the battlefield" in line for line in game.log)
    assert not any("sacrifice" in line for line in game.log), game.log[-6:]


@pytest.mark.parametrize("interactive", [False, True])
def test_the_continuation_runs_once_after_the_entry_is_settled(interactive):
    """What a caller does once the permanent is there (``then``) runs exactly
    once: at once for a seat nobody asks, at the answer for a person — never
    for an entry still waiting on its question. And the identity a caller
    reads as the call returns ("if you do, sacrifice **it**") is the one the
    answer keeps (CR 400.7)."""
    game = _game(interactive)
    _put(game, 0, "Forest")
    _put(game, 1, "Living Plane")
    _put(game, 1, "Containment Priest")
    lake = Permanent(card=_POOL["Lake of the Dead"])
    built = lake.permanent_id
    ran: list[bool] = []
    game._put_permanent_onto_battlefield(
        0, lake, None, then=lambda: ran.append(game.is_on_battlefield(lake)),
    )
    if interactive:
        assert _asked(game) and ran == []
        recorded = lake.permanent_id
        assert recorded != built, "a new object's identity is stamped as the call returns"
        _answer(game, 1)
        assert lake.permanent_id == recorded
    settle(game)
    assert ran == [False]
    assert _where(game, "Lake of the Dead") == (
        ["P0.graveyard"] if interactive else ["P0.exile"]
    )


def test_a_toll_that_asks_again_after_the_answer_is_offered_in_turn():
    """Containment Priest beside Mox Diamond's optional toll, on a Mox under
    March of the Machines put onto the battlefield uncast. Mox Diamond's own
    effect applied first asks its own question (which land card to discard);
    paying it re-enters the Mox, which the Priest still exiles — its ruling,
    2021-03-19, reaches any creature that wasn't cast."""
    game = _game(True)
    game.players[0].hand[:] = [_POOL["Forest"]]
    _put(game, 1, "March of the Machines")
    _put(game, 1, "Containment Priest")
    mox = Permanent(card=_POOL["Mox Diamond"])
    game._put_permanent_onto_battlefield(0, mox, None)
    options = _asked(game)[0].data["options"]
    assert "Containment Priest" in options[0] and "Mox Diamond" in options[1]
    _answer(game, 1)
    assert [c.kind for c in game.pending_replacement_choices] == ["entry_discard_toll"]
    assert game.resolve_replacement_choice(0, 0, kind="entry_discard_toll")
    settle(game)
    assert _where(game, "Mox Diamond") == ["P0.exile"]
    assert _where(game, "Forest").count("P0.graveyard") == 1
