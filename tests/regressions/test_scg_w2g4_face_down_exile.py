"""A card exiled face down stays hidden, in the log and on the board, until an
instruction shows it (CR 406.3) — and it does nothing from exile (CR 113.6).

Three defects the hidden-card census (``tests/engine/
test_hidden_cards_stay_out_of_the_log.py``) and its drive found on SCG W2G4's
base, each one reproduced here on the card that showed it:

* **The exiler leaving turned its pile face up.** ``face_down_exiled_cards``
  read the record off the exiling permanent on the battlefield, so once
  Necropotence was destroyed with its card still waiting for the end step —
  or Kyren Archive was sacrificed to its own cost, or Mangara's Tome phased
  out — every one of its face-down cards was face up to every viewer, and the
  log named them as they went to a hand ("Serra Angel go to their owner's
  hand"). ``linked_exile.keep_face_down_after_departure`` hands them to the
  game's register as the permanent leaves.
* **A face-down card's own upkeep trigger fired from exile.** Three Wishes
  exiling three Juzám Djinn dealt its caster 3 damage at the next upkeep and
  logged "Juzám Djinn dealt 1 damage to A" three times: the upkeep scan over
  exiled records fired every ``upkeep_self`` trigger of the card.
  ``exiled_records.functions_in_exile`` admits only the ability that says it
  works there (All Hallow's Eve's "if this card is exiled", CR 113.6k).
* **The permissions named what they covered**: Three Wishes' "may look at"
  and "may play", Gustha's Scepter's exile and its look.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.linked_exile import face_down_exiled_cards
from engine.models import Permanent
from tests.helpers import _nosick, resolve_stack

_SECRET = "Serra Angel"


def _card(code: str, name: str):
    return next(
        c for c in load_cards(manifest_set_path(code, include_measured=True))
        if c.name == name
    )


def _game(*, mine=(), hand=(), library=()) -> Game:
    me = PlayerState(
        name="A", battlefield=[_nosick(Permanent(card=c)) for c in mine],
        hand=list(hand), library=list(library),
    )
    game = Game(players=[me, PlayerState(name="B", library=[_card("2ED", "Island")] * 8)])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def _settle(game) -> None:
    for _ in range(8):
        resolve_stack(game)
        if not game.pending_choices:
            return
        game.auto_resolve_pending_choices()


def _named(game, name: str) -> list[str]:
    return [line for line in game.log if name in line]


def test_necropotence_leaving_keeps_its_card_face_down_to_the_end_step():
    necropotence = _card("5ED", "Necropotence")
    library = [_card("2ED", _SECRET)] * 3
    game = _game(mine=[necropotence], library=library)
    assert game.activate_permanent_ability(0, "Necropotence").supported
    resolve_stack(game)
    secret = game.players[0].exile[0]
    assert any(held is secret for held in face_down_exiled_cards(game, 0))

    source = next(p for p in game.controlled_by(0) if p.card is necropotence)
    game.remove_from_battlefield(source)
    game.players[0].graveyard.append(necropotence)

    # Still face down to every viewer: nothing turned it up (CR 406.3).
    assert any(held is secret for held in face_down_exiled_cards(game, 0))
    assert any(held is secret for held in face_down_exiled_cards(game, 0, 1))
    # The delayed ability is independent of its source (CR 603.7c), and puts
    # the card into its controller's hand without telling the table which.
    game.resolve_end_step(0)
    _settle(game)
    assert [c.name for c in game.players[0].hand] == [_SECRET]
    assert _named(game, _SECRET) == [], _named(game, _SECRET)
    assert any("1 face-down card(s)" in line for line in game.log), game.log[-6:]
    # It left exile, so nothing still speaks for it as face down.
    assert face_down_exiled_cards(game, 0) == []


def test_kyren_archive_sacrificed_hands_over_its_pile_without_naming_it():
    archive = _card("MMQ", "Kyren Archive")
    game = _game(mine=[archive], library=[_card("2ED", _SECRET)] * 4)
    # Its upkeep exile ran as the turn began; once more for a pile of two.
    game.start_next_turn()
    _settle(game)
    game.start_next_turn()
    _settle(game)
    assert len(game.players[0].exile) == 2
    # Onto the stack and no further: the pile waits while the ability does.
    result = game.queue_permanent_ability(0, "Kyren Archive", ability_index=0)
    assert result.supported, result.details
    assert game.stack and not any(
        p.card is archive for p in game.controlled_by(0)
    ), "sacrificed as it was activated"
    # Sacrificed as a cost: while the ability waits on the stack, the pile it
    # left behind is still face down.
    assert len(face_down_exiled_cards(game, 0)) == 2
    _settle(game)
    assert [c.name for c in game.players[0].hand].count(_SECRET) == 2
    assert _named(game, _SECRET) == [], _named(game, _SECRET)
    assert any(
        "a face-down card, a face-down card go to their owner's hand" in line
        for line in game.log
    ), game.log[-6:]


def test_a_phased_out_tome_keeps_its_pile_face_down():
    tome = _card("MIR", "Mangara's Tome")
    game = _game(hand=[tome], library=[_card("2ED", _SECRET)] * 9)
    assert game.queue_from_hand(0, "Mangara's Tome").supported
    _settle(game)
    assert len(face_down_exiled_cards(game, 0)) == 5
    source = next(p for p in game.controlled_by(0) if p.card is tome)
    assert game.phase_out_permanent(source)
    # CR 702.26d: phasing out is no zone change, and a face-down pile has no
    # ending in it either.
    assert len(face_down_exiled_cards(game, 0)) == 5


def test_three_wishes_names_nothing_and_its_cards_do_nothing_from_exile():
    djinn = _card("ARN", "Juzám Djinn")
    wishes = _card("VIS", "Three Wishes")
    game = _game(hand=[wishes], library=[djinn] * 3 + [_card("2ED", "Island")] * 5)
    assert game.queue_from_hand(0, "Three Wishes").supported
    _settle(game)
    assert len(face_down_exiled_cards(game, 0)) == 3
    assert _named(game, "Juzám Djinn") == []
    assert any(
        "may look at 3 face-down card(s) for as long as it remains exiled" in line
        for line in game.log
    ), game.log[-6:]
    assert any("may play 3 face-down card(s) from exile" in line for line in game.log)

    life = game.players[0].life
    game.start_next_turn()
    _settle(game)
    game.start_next_turn()
    _settle(game)
    # CR 113.6: Juzám Djinn's upkeep damage works from the battlefield only.
    assert game.players[0].life == life
    assert not any("dealt 1 damage" in line for line in game.log)
    # Three Wishes' own delayed ability still puts them into the graveyard.
    assert [c.name for c in game.players[0].graveyard].count("Juzám Djinn") == 3


def test_all_hallows_eve_still_counts_down_from_exile():
    """The other side of ``functions_in_exile``: an ability that says it works
    in exile ("if this card is exiled with a scream counter on it", CR 113.6k)
    still fires there."""
    eve = _card("LEG", "All Hallow's Eve")
    game = _game(hand=[eve], library=[_card("2ED", "Island")] * 8)
    assert game.queue_from_hand(0, "All Hallow's Eve").supported
    _settle(game)
    assert any(c is eve for c in game.players[0].exile)
    game.start_next_turn()
    _settle(game)
    game.start_next_turn()
    _settle(game)
    assert any("scream counter" in line for line in game.log[-12:]), game.log[-12:]


def test_gusthas_scepter_exiles_a_card_face_down_without_naming_it():
    scepter = _card("ALL", "Gustha's Scepter")
    game = _game(mine=[scepter], hand=[_card("2ED", _SECRET)])
    result = game.activate_permanent_ability(0, "Gustha's Scepter", ability_index=0)
    assert result.supported, result.details
    _settle(game)
    assert [c.name for c in game.players[0].exile] == [_SECRET]
    # Face down to the table, readable by the seat the look was granted.
    assert len(face_down_exiled_cards(game, 0, 1)) == 1
    assert face_down_exiled_cards(game, 0, 0) == []
    assert _named(game, _SECRET) == [], _named(game, _SECRET)
    assert any("exiled a card face down from their hand" in line for line in game.log)
