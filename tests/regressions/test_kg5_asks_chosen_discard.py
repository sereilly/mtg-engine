"""Census: a card the player **chose** to discard goes where CR 616.1's one
process sends it — the forced discard's own (``Game.discarded_card_destination``).

"If two or more replacement and/or prevention effects are attempting to
modify the way an event affects an object or player, the affected object's
controller (or its owner if it has no controller) or the affected player
chooses one to apply" (CR 616.1, 616.1e). Since round kg4 `asks` a card taken
from the player (Hymn to Tourach, Mind Twist) asks; the chosen discard's seam
(``handlers/discards._resolve_one_discard``) ran Dodecapod, then madness, then
the graveyard seam in a fixed order, so on the base of round kg5 (59f133e63)
none of these boards asked anybody:

* Dodecapod beside Forbidden Crypt, on a discard an opponent's Mind Rot made;
* madness beside Forbidden Crypt, and beside Yawgmoth's Will's turn;
* and Library of Leng on a discard no prompt offered the library top on — the
  caster's pick out of a revealed hand (Coercion) — which its ruling reaches
  ("The ability applies any time a spell or ability has you discard as part of
  its effect. It does not matter if you or your opponent control the spell or
  ability", 2004-10-04): the base put the card into the graveyard unasked.

One board per contention, through the real entry points (cast, resolve, the
discard prompt's answer). Each checks the seat nobody asks is not asked and is
the reference; the interactive seat is asked once with the card in no zone;
the first answer reproduces the reference and the second is honoured.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import resolve_stack, settle

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
    game.players[seat].hand.append(_POOL[name])
    result = game.queue_from_hand(seat, name, **announced)
    assert result.supported, result.details
    game.resolve_top_of_stack()


def _discard_what_is_asked(game: Game) -> None:
    """Seat 0 answers its discard prompt with the cards it holds — the one
    card each board gives it, so the reference's pick is the same card."""
    choice = game.pending_choice_of("discard", 0)
    assert choice is not None, [c.kind for c in game.pending_choices]
    assert game.confirm_discard(0, list(range(int(choice.data["count"]))))


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


# ---------------------------------------------------------------------------
# One driver per board: (the contended card, where the second option puts it,
# the run up to the seat's discard answer)
# ---------------------------------------------------------------------------


def _crypt_dodecapod(game):
    """Dodecapod's battlefield against Forbidden Crypt's exile, on a card the
    player chose for an opponent's Mind Rot (its 2022-12-08 ruling: "causes
    you to choose a card to discard and you discard Dodecapod")."""
    _put(game, 0, "Forbidden Crypt")
    game.players[0].hand[:] = [_POOL["Dodecapod"]]
    return "Dodecapod", ["P0.exile"], lambda: _cast(
        game, 1, "Mind Rot", target_player_index=0,
    )


def _crypt_madness(game):
    """Madness's exile (and its cast) against Forbidden Crypt's plain exile."""
    _put(game, 0, "Forbidden Crypt")
    game.players[0].hand[:] = [_POOL["Arrogant Wurm"]]
    return "Arrogant Wurm", ["P0.exile"], lambda: _cast(
        game, 1, "Mind Rot", target_player_index=0,
    )


def _will_madness(game):
    """Yawgmoth's Will's turn against madness, on the caster's own Mind Rot."""
    game.players[0].hand[:] = [_POOL["Arrogant Wurm"]]

    def run():
        _cast(game, 0, "Yawgmoth's Will")
        settle(game)
        _cast(game, 0, "Mind Rot", target_player_index=0)

    return "Arrogant Wurm", ["P0.exile"], run


_CASES = [
    ("Forbidden Crypt / Dodecapod", _crypt_dodecapod, 1),
    ("Forbidden Crypt / madness", _crypt_madness, 1),
    ("Yawgmoth's Will / madness", _will_madness, 0),
]


def _run(driver, active: int, interactive: bool):
    game = _game(interactive, active)
    name, alternative, run = driver(game)
    run()
    _discard_what_is_asked(game)
    return game, name, alternative


def _answer(game: Game, option: int) -> None:
    choice = game.pending_choice_of("effect_order")
    assert game.resolve_pending_choice(
        "effect_order", choice.player_index, option_index=option,
    )


@pytest.mark.parametrize("label,driver,active", _CASES, ids=[c[0] for c in _CASES])
def test_a_chosen_discard_meeting_two_effects_is_asked(label, driver, active):
    reference, name, alternative = _run(driver, active, interactive=False)
    assert not [c for c in reference.pending_choices if c.kind == "effect_order"], (
        f"{label}: a seat nobody asks was asked"
    )
    settle(reference)
    expected = _where(reference, name)
    assert expected, f"{label}: the reference run lost the card"

    game, *_ = _run(driver, active, interactive=True)
    asked = [c for c in game.pending_choices if c.kind == "effect_order"]
    assert len(asked) == 1, (
        f"{label}: {[(c.kind, c.data) for c in game.pending_choices]}"
    )
    assert asked[0].player_index == 0 and asked[0].data["event_kind"] == "discard"
    assert len(asked[0].data["options"]) == 2, asked[0].data["options"]
    # The card has been discarded and is in no zone while its player chooses.
    assert _where(game, name) == [], (label, _where(game, name))

    _answer(game, 0)
    settle(game)
    assert _where(game, name) == expected, (label, _where(game, name), expected)
    assert not game.resume_stack and not game.pending_choices and not game.stack, label
    assert not game.effect_order_answers, (label, game.effect_order_answers)

    other, *_ = _run(driver, active, interactive=True)
    _answer(other, 1)
    settle(other)
    assert _where(other, name) == alternative, (label, _where(other, name))
    assert not other.effect_order_answers, (label, other.effect_order_answers)
    # The graveyard's exile is not madness's: nothing is offered for a cast.
    assert not any("into exile (madness)" in line for line in other.log), other.log[-8:]


def test_the_reference_answers_are_the_effects_the_event_names_first():
    """A seat nobody asks takes the ``discard`` event's own effects ahead of
    the graveyard's — the order the chosen discard has always applied them in,
    so nothing moved for an AI or headless seat."""
    reference, name, _ = _run(_crypt_dodecapod, 1, interactive=False)
    settle(reference)
    assert _where(reference, name) == ["battlefield"]
    pod = next(p for p in reference.all_permanents() if p.card.name == name)
    assert int(pod.metadata.get("plus_counters", 0) or 0) == 2


def test_a_card_only_the_graveyard_effect_takes_is_still_named_discarded():
    """"P0 discarded Grizzly Bears" stays in the log for a chosen card Forbidden Crypt
    exiles — it was discarded (CR 701.9a) and none of the discard's own effects
    names it — while a card one of those effects took is named by that
    effect's line alone."""
    game = _game(True, 1)
    _put(game, 0, "Forbidden Crypt")
    game.players[0].hand[:] = [_POOL["Grizzly Bears"]]
    _cast(game, 1, "Mind Rot", target_player_index=0)
    _discard_what_is_asked(game)
    settle(game)
    assert _where(game, "Grizzly Bears") == ["P0.exile"]
    assert "P0 discarded Grizzly Bears" in game.log, game.log[-6:]

    pod_game, *_ = _run(_crypt_dodecapod, 1, interactive=True)
    _answer(pod_game, 0)
    settle(pod_game)
    assert "P0 discarded Dodecapod" not in pod_game.log
    assert any(
        "discarded Dodecapod, which was put onto the battlefield" in line
        for line in pod_game.log
    ), pod_game.log[-8:]


def _coerced(interactive: bool) -> Game:
    """Seat 0 controls Library of Leng; seat 1's Coercion takes its Grizzly Bears."""
    game = _game(interactive, 1)
    _put(game, 0, "Library of Leng")
    game.players[0].hand[:] = [_POOL["Grizzly Bears"]]
    _cast(game, 1, "Coercion", target_player_index=0)
    pick = game.pending_choice_of("revealed_hand_pick", 1)
    assert pick is not None, [c.kind for c in game.pending_choices]
    assert game.confirm_revealed_hand_pick(1, 0)
    return game


def test_library_of_leng_reaches_the_card_a_caster_picked_out_of_the_hand():
    """Library of Leng, 2004-10-04: "The ability applies any time a spell or
    ability has you discard as part of its effect. It does not matter if you or
    your opponent control the spell or ability." Coercion's pick arms no
    ``discard`` prompt, so nothing offered the library top; the destination's
    process offers it now — taken at a seat nobody asks (the Library's own
    default), asked of a person."""
    reference = _coerced(interactive=False)
    settle(reference)
    assert _where(reference, "Grizzly Bears") == ["P0.library"], reference.log[-6:]
    assert reference.players[0].library[0].name == "Grizzly Bears"

    for to_library, zone in ((True, ["P0.library"]), (False, ["P0.graveyard"])):
        game = _coerced(interactive=True)
        offered = [c for c in game.pending_replacement_choices if c.kind == "leng_discard"]
        assert len(offered) == 1 and offered[0].player_index == 0, (
            [(c.kind, c.player_index) for c in game.pending_replacement_choices]
        )
        assert _where(game, "Grizzly Bears") == []
        assert game.confirm_leng_discard(0, to_library=to_library)
        settle(game)
        assert _where(game, "Grizzly Bears") == zone, (to_library, game.log[-6:])
        assert not game.pending_replacement_choices and not game.stack


def test_a_prompt_that_offered_the_library_top_is_not_offered_it_twice():
    """A seat whose own discard prompt offered Library of Leng's top and who
    declined it has had the Library's one opportunity (CR 614.5): the card goes
    to the graveyard, nobody asked again."""
    game = _game(True, 1)
    _put(game, 0, "Library of Leng")
    game.players[0].hand[:] = [_POOL["Grizzly Bears"]]
    _cast(game, 1, "Mind Rot", target_player_index=0)
    choice = game.pending_choice_of("discard", 0)
    assert choice.data.get("allow_top_of_library")
    assert game.confirm_discard(0, [0], to_library=False)
    assert not game.pending_replacement_choices
    settle(game)
    assert _where(game, "Grizzly Bears") == ["P0.graveyard"]
