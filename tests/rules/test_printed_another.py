"""CR 113.7 / CR 115.3 -- what the printed word "another" excludes.

Two different rules wear the same word, and a card may print it for either.

* With **no earlier choice in the sentence**, "another <object>" excludes the
  ability's own source. CR 113.7 is what says which object that is: "the source
  of a triggered ability ... is the object whose ability triggered". For a
  dies-trigger that object is a *card in a graveyard* (CR 109.2a), and CR 113.7a
  is why it can still be named at all -- the ability exists on the stack
  independently of its source, and the source's last known information is used.
* After a first "target", the word forbids the repeat CR 115.3 would otherwise
  allow: "if the spell or ability uses the word 'target' in multiple places, the
  same object or player can be chosen once for each instance of the word
  'target'" -- unless the card says otherwise.

Which of the two a sentence means is decided once, in
``engine/grammar/lowering/_targets.py``. What is tested here is that each
reading reaches the board.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.card_loader import load_catalog, load_cards, manifest_set_path
from engine.models import Permanent, PlayerState

_CATALOG = {card.name: card for card in load_catalog()}
_UDS = {
    card.name: card
    for card in load_cards(manifest_set_path("UDS", include_measured=True))
}


def _duel(**p1_kwargs) -> tuple[Game, PlayerState]:
    p1 = PlayerState(name="P1", **p1_kwargs)
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game, p1


def _kill(game: Game, permanent: Permanent) -> None:
    game._mark_damage_on_permanent(permanent, 99, source=None, combat=False)
    game.check_state_based_actions()
    game._settle()


@pytest.mark.cr("113.7", "109.2a", "603.3d")
def test_a_dies_triggers_another_excludes_the_card_that_died():
    """Junk Diver: "When this creature dies, return **another** target artifact
    card from your graveyard to your hand."

    CR 704.5g puts the card in the graveyard *before* CR 603.3 puts the trigger
    on the stack, so the source of the ability is one of the candidates the
    sentence is choosing between -- and it is the one candidate the printed word
    rules out. With nothing else in the pile the ability has nothing to return.
    """
    game, p1 = _duel()
    diver = Permanent(card=_UDS["Junk Diver"])
    p1.battlefield.append(diver)
    game._sync_control()

    _kill(game, diver)

    assert [card.name for card in p1.hand] == [], "it may not return itself"
    assert [card.name for card in p1.graveyard] == ["Junk Diver"]


@pytest.mark.cr("113.7", "109.2a")
def test_it_excludes_only_its_own_copy_and_not_the_card_name():
    """CR 113.7 names an **object**, not a name.

    ``load_cards`` dedupes by ``oracle_id``, so two copies of one card in one
    graveyard are the same ``CardDefinition`` object -- the residual
    :class:`engine.game_types.GraveyardTarget` states. Excluding by card rather
    than by slot would take both away, and the second copy is a card the
    sentence really does let its controller return.
    """
    game, p1 = _duel(graveyard=[_UDS["Junk Diver"]])
    diver = Permanent(card=_UDS["Junk Diver"])
    p1.battlefield.append(diver)
    game._sync_control()

    _kill(game, diver)

    assert [card.name for card in p1.hand] == ["Junk Diver"]
    assert [card.name for card in p1.graveyard] == ["Junk Diver"]


@pytest.mark.cr("113.7", "109.2a")
def test_another_still_admits_every_card_the_sentence_does_name():
    """The exclusion is one object wide. Everything else in the pile that
    answers the printed noun phrase is still a legal choice."""
    game, p1 = _duel(graveyard=[_CATALOG["Ornithopter"]])
    diver = Permanent(card=_UDS["Junk Diver"])
    p1.battlefield.append(diver)
    game._sync_control()

    _kill(game, diver)

    assert [card.name for card in p1.hand] == ["Ornithopter"]


@pytest.mark.cr("113.7a")
def test_a_source_that_has_left_the_graveyard_excludes_nothing():
    """Sylvan Hierophant: "When this creature dies, exile it, **then** return
    another target creature card from your graveyard to your hand."

    Its first step takes the source out of the pile, so by the second there is
    no slot for the word to exclude -- and the exclusion must not then reach for
    something else. The card in the pile comes back.
    """
    game, p1 = _duel(graveyard=[_CATALOG["Grizzly Bears"]])
    hierophant = Permanent(card=_CATALOG["Sylvan Hierophant"])
    p1.battlefield.append(hierophant)
    game._sync_control()

    _kill(game, hierophant)

    assert [card.name for card in p1.exile] == ["Sylvan Hierophant"]
    assert [card.name for card in p1.hand] == ["Grizzly Bears"]


@pytest.mark.cr("115.3", "601.2c")
def test_a_second_printed_target_narrowed_by_another_must_differ():
    """Kor Chant: "All damage that would be dealt this turn to target creature
    you control by a source of your choice is dealt to **another** target
    creature instead."

    Two instances of the word "target", which CR 115.3 would otherwise let name
    one creature twice. The word forbids it, and the payload says so -- the
    picker's distinctness had been an accident of the two slots' printed noun
    phrases differing, which is a property of this card rather than of the
    sentence.
    """
    program_targets = _CATALOG["Kor Chant"]
    from engine.oracle import compile_card_oracle

    instruction = compile_card_oracle(program_targets).instructions[0]
    assert instruction.payload["targets"]["distinct"] is True
