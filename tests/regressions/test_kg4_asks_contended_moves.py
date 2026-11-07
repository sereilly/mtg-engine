"""Census: a card's move that two CR 614 effects contend for is put to the
affected player (CR 616.1, 616.1e), and answering it finishes the move.

"If two or more replacement and/or prevention effects are attempting to
modify the way an event affects an object or player, the affected object's
controller (or its owner if it has no controller) or the affected player
chooses one to apply" (CR 616.1). On the base of round kg4 `asks` (7e120654)
none of these boards asked anybody: a dying permanent, a card on its way to a
graveyard and a discarded card each ran their effects in a fixed order, even
for an interactive seat — and a death ran its three spellings (``would_die``,
``would_leave_battlefield``, ``put_into_graveyard``) as three contention sets,
so the would-die effect won even the pair CR 616.1f's own example is about
(Forbidden Crypt beside Gravebane Zombie: "its controller decides which
replacement to apply first").

One board per shape, each through a real entry point — a spell's damage and
the state-based death behind it, a destroy spell, a countered spell, a
discard at random, a discard of the player's own — with seat 0, the affected
player, holding the contended card. Each checks:

* the seat nobody asks is not asked, and its run is the reference;
* the interactive seat **is** asked, once, about this event, with the card
  in no zone while it chooses;
* answering with the first option — the default — puts the card where the
  reference put it, with nothing left owed;
* answering with the second option is honoured.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.replacements.zone_changes import EXILE_ON_LEAVING_BATTLEFIELD
from tests.helpers import resolve_stack

_POOL = {card.name: card for card in load_catalog()}


def _game(interactive: bool, active: int) -> Game:
    game = Game(players=[
        PlayerState(f"P{index}", library=[_POOL["Island"]] * 8) for index in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.begin_turn_bookkeeping(active)
    game.resolve_untap_step(active)
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


def _cast(game: Game, seat: int, name: str, **announced) -> None:
    """Cast *name* from *seat*'s hand, resolve it once and make the state
    check — one resolution, not ``resolve_stack``, which answers what holds
    the stack, and a question held there is what is being looked for."""
    game.players[seat].hand.append(_POOL[name])
    result = game.queue_from_hand(seat, name, **announced)
    assert result.supported, result.details
    game.resolve_top_of_stack()
    # The death a spell's damage leaves behind (CR 704.5g).
    game.check_state_based_actions()


def _where(game: Game, name: str) -> list[str]:
    """Every zone holding a card called *name*, a permanent included."""
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


# ---------------------------------------------------------------------------
# One driver per board: (the contended card's name, the event asked about,
# where the second option puts it, the run)
# ---------------------------------------------------------------------------


def _disintegrate_gravebane(game):
    """Two would-die effects: Disintegrate's exile and Gravebane Zombie's own
    "put it on top of its owner's library instead"."""
    zombie = _put(game, 0, "Gravebane Zombie")
    return "Gravebane Zombie", "would_die", ["P0.library"], lambda: _cast(
        game, 1, "Disintegrate", target_player_index=0,
        target_permanent_ids=[zombie.permanent_id], x_value=3,
    )


def _crypt_gravebane(game):
    """CR 616.1f's example: a would-die effect against a graveyard one."""
    _put(game, 0, "Forbidden Crypt")
    zombie = _put(game, 0, "Gravebane Zombie")
    return "Gravebane Zombie", "would_die", ["P0.exile"], lambda: _cast(
        game, 1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[zombie.permanent_id],
    )


def _crypt_phoenix(game):
    """Firestorm Phoenix's return to hand against Forbidden Crypt's exile."""
    _put(game, 0, "Forbidden Crypt")
    phoenix = _put(game, 0, "Firestorm Phoenix")
    return "Firestorm Phoenix", "would_die", ["P0.exile"], lambda: _cast(
        game, 1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[phoenix.permanent_id],
    )


def _dreams_gravebane(game):
    """A would-die effect against a would-leave-the-battlefield one. Either
    order exiles it: Gravebane's library is still a way off the battlefield,
    which Dreams of the Dead's exile then replaces (CR 616.1f) — so the
    choice is put, and both answers end in exile."""
    zombie = _put(game, 0, "Gravebane Zombie")
    zombie.metadata[EXILE_ON_LEAVING_BATTLEFIELD] = "Dreams of the Dead"
    return "Gravebane Zombie", "would_die", ["P0.exile"], lambda: _cast(
        game, 1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[zombie.permanent_id],
    )


def _crypt_legacy_weapon_destroyed(game):
    """ROADMAP's "Legacy Weapon under Forbidden Crypt": a destroy spell."""
    _put(game, 0, "Forbidden Crypt")
    weapon = _put(game, 0, "Legacy Weapon")
    return "Legacy Weapon", "would_die", ["P0.library"], lambda: _cast(
        game, 1, "Disenchant", target_player_index=0,
        target_permanent_ids=[weapon.permanent_id],
    )


def _crypt_legacy_weapon_countered(game):
    """The graveyard seam alone: a countered Legacy Weapon spell."""
    _put(game, 0, "Forbidden Crypt")

    def run():
        game.players[0].hand.append(_POOL["Legacy Weapon"])
        assert game.queue_from_hand(0, "Legacy Weapon").supported
        _cast(game, 1, "Counterspell", target_stack_index=0)

    return "Legacy Weapon", "put_into_graveyard", ["P0.library"], run


def _will_legacy_weapon_discarded(game):
    """ROADMAP's "… or Yawgmoth's Will": the turn's exile against Legacy
    Weapon's shuffle, on a discard (Mind Twist at its own caster)."""

    def run():
        _cast(game, 0, "Yawgmoth's Will")
        game.players[0].hand[:] = [_POOL["Legacy Weapon"]]
        _cast(game, 0, "Mind Twist", target_player_index=0, x_value=1)

    return "Legacy Weapon", "discard", ["P0.library"], run


def _leng_madness(game):
    """ROADMAP's "Library of Leng and madness on a forced discard": a card
    taken at random (Hymn to Tourach)."""
    _put(game, 0, "Library of Leng")

    def run():
        game.players[0].hand[:] = [_POOL["Arrogant Wurm"]]
        _cast(game, 1, "Hymn to Tourach", target_player_index=0)

    # The Library first offers its "you may", whose default is the top.
    return "Arrogant Wurm", "discard", ["P0.library"], run


def _leng_dodecapod(game):
    """Dodecapod's battlefield against Library of Leng's library top, on a
    discard an opponent's spell caused."""
    _put(game, 0, "Library of Leng")

    def run():
        game.players[0].hand[:] = [_POOL["Dodecapod"]]
        _cast(game, 1, "Hymn to Tourach", target_player_index=0)

    return "Dodecapod", "discard", ["P0.library"], run


_CASES = [
    ("Disintegrate / Gravebane Zombie", _disintegrate_gravebane, 1),
    ("Forbidden Crypt / Gravebane Zombie", _crypt_gravebane, 1),
    ("Forbidden Crypt / Firestorm Phoenix", _crypt_phoenix, 1),
    ("Dreams of the Dead / Gravebane Zombie", _dreams_gravebane, 1),
    ("Forbidden Crypt / Legacy Weapon destroyed", _crypt_legacy_weapon_destroyed, 1),
    ("Forbidden Crypt / Legacy Weapon countered", _crypt_legacy_weapon_countered, 0),
    ("Yawgmoth's Will / Legacy Weapon discarded", _will_legacy_weapon_discarded, 0),
    ("Library of Leng / madness", _leng_madness, 1),
    ("Library of Leng / Dodecapod", _leng_dodecapod, 1),
]


def _run(driver, active: int, interactive: bool):
    game = _game(interactive, active)
    name, kind, alternative, run = driver(game)
    run()
    return game, name, kind, alternative


def _answer(game: Game, option: int) -> None:
    choice = game.pending_choice_of("effect_order")
    assert game.resolve_pending_choice(
        "effect_order", choice.player_index, option_index=option,
    )


def _settle(game: Game) -> None:
    """Every later decision at its default — a madness cast, the Library's
    own "you may" — and whatever is left on the stack."""
    for _ in range(10):
        resolve_stack(game)
        game.auto_resolve_pending_choices()
        game.auto_resolve_pending_replacement_choices()
        if not (game.pending_choices or game.pending_replacement_choices or game.stack):
            return


@pytest.mark.parametrize("label,driver,active", _CASES, ids=[c[0] for c in _CASES])
def test_a_contended_move_is_asked_and_the_answer_finishes_it(label, driver, active):
    reference, name, kind, alternative = _run(driver, active, interactive=False)
    assert not [c for c in reference.pending_choices if c.kind == "effect_order"], (
        f"{label}: a seat nobody asks was asked"
    )
    _settle(reference)
    expected = _where(reference, name)
    assert expected, f"{label}: the reference run lost the card"

    game, *_ = _run(driver, active, interactive=True)
    asked = [c for c in game.pending_choices if c.kind == "effect_order"]
    assert len(asked) == 1, f"{label}: {[(c.kind, c.data) for c in game.pending_choices]}"
    assert asked[0].player_index == 0 and asked[0].data["event_kind"] == kind, (
        label, asked[0].player_index, asked[0].data["event_kind"],
    )
    assert len(asked[0].data["options"]) == 2, asked[0].data["options"]
    # The move waits for the answer: the card is in no zone (CR 614.6 — no
    # effect in the set leaves it where it was going, and none has applied).
    assert _where(game, name) == [], (label, _where(game, name))

    _answer(game, 0)
    _settle(game)
    assert _where(game, name) == expected, (label, _where(game, name), expected)
    assert not game.resume_stack and not game.pending_choices and not game.stack, label
    assert not game.effect_order_answers, (label, game.effect_order_answers)

    other, *_ = _run(driver, active, interactive=True)
    _answer(other, 1)
    _settle(other)
    assert _where(other, name) == alternative, (label, _where(other, name))
    assert not other.effect_order_answers, (label, other.effect_order_answers)


@pytest.mark.cr("616.1f")
def test_a_declined_library_of_leng_re_asks_dodecapod():
    """Library of Leng applied first and its "you may" declined: the event is
    still a discard into the graveyard, and CR 616.1f re-asks what is still
    applicable — Dodecapod, whose battlefield the decline used to skip (the
    Library's answer re-asked madness alone)."""
    game = _game(True, 1)
    _put(game, 0, "Library of Leng")
    game.players[0].hand[:] = [_POOL["Dodecapod"]]
    _cast(game, 1, "Hymn to Tourach", target_player_index=0)
    _answer(game, 1)  # Library of Leng first
    assert game.confirm_leng_discard(0, to_library=False)
    _settle(game)
    assert _where(game, "Dodecapod") == ["battlefield"], game.log[-6:]
    pod = next(p for p in game.all_permanents() if p.card.name == "Dodecapod")
    assert int(pod.metadata.get("plus_counters", 0) or 0) == 2


def test_two_deaths_in_one_sweep_are_each_asked_about_their_own_card():
    """Two Gravebane Zombies under Forbidden Crypt die to one Pyroclasm: two
    questions for one seat, each answered for its own Zombie — the first
    exiled (the Crypt), the second on top of the library (its own)."""
    game = _game(True, 1)
    _put(game, 0, "Forbidden Crypt")
    _put(game, 0, "Gravebane Zombie")
    _put(game, 0, "Gravebane Zombie")
    _cast(game, 1, "Pyroclasm")
    asked = [c for c in game.pending_choices if c.kind == "effect_order"]
    assert len(asked) == 2, [c.kind for c in game.pending_choices]
    _answer(game, 1)
    _answer(game, 0)
    _settle(game)
    assert _where(game, "Gravebane Zombie") == ["P0.exile", "P0.library"]
    assert not game.effect_order_answers
