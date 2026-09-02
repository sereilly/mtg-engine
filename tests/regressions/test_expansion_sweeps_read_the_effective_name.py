"""Regressions: an expansion sweep asks the permanent's *name*, not its face.

CR 206.3 states each of the three cards that name a set as a **list of names**
— "One card (Golgothian Sylex) refers to permanents with a name originally
printed in the Antiquities expansion. Those names are Amulet of Kroog, …". So
what a sweep asks of a permanent is whether *its* name is one of them, and a
copy's name is the name it copied (CR 707.2, layer 1).

All three readers asked ``perm.card.original_printing`` instead — where the
physical card was first published, which is a different question with the same
answer for every permanent that is not a copy. Measured on the shipped pool
before the fix:

* **Golgothian Sylex** left a Copy Artifact copying Su-Chi standing. The
  permanent's name was Su-Chi, which CR 206.3b lists by hand.
* **City in a Bottle** left a Copy Artifact copying Ebony Horse on the
  battlefield, for the same reason and through a different code path (the
  continuous state check in ``mixins/game_ending.py``).
* **Apocalypse Chime**, whose noun phrase became a shared ``ObjectFilter``
  rider the same round, would have shipped with the defect already in it.

The read is ``perm.effective_card.original_printing`` in all three. Nothing
ratchets ``card.name``, so no guard in the repo could have found this: the
three sites are spelled as a set-code comparison, not as a name comparison, and
``tests/engine/test_layer_reads.py`` does not cover the field they reach it
through.
"""

from __future__ import annotations

from engine import Game
from engine.card_loader import load_cards, manifest_set_paths
from engine.copies import become_copy
from engine.models import Permanent, PlayerState

# Both manifest roles, because Apocalypse Chime's set is still `measured` — the
# card is real card data whether or not a player may deck it, which is the same
# reasoning ``set_code_for_expansion_name`` states.
_POOL: dict = {}
for _path in manifest_set_paths(include_measured=True):
    for _card in load_cards(_path):
        _POOL.setdefault(_card.name, _card)


def _board(*names: str):
    perms = [Permanent(card=_POOL[name]) for name in names]
    p1 = PlayerState(name="P1", battlefield=perms)
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    return game, perms


def test_golgothian_sylex_takes_a_copy_wearing_an_antiquities_name():
    """CR 206.3b lists Su-Chi, and the Copy Artifact's name *is* Su-Chi."""
    game, (sylex, suchi, copier, bear) = _board(
        "Golgothian Sylex", "Su-Chi", "Copy Artifact", "Grizzly Bears"
    )
    become_copy(copier, suchi)
    assert copier.card.name == "Copy Artifact", "the printed face is unchanged"
    assert copier.effective_card.name == "Su-Chi", "the copiable name is not"

    game.activate_permanent_ability(0, "Golgothian Sylex")
    game._settle()

    assert [perm.effective_card.name for perm in game.all_permanents()] == [
        "Grizzly Bears"
    ]


def test_golgothian_sylex_still_spares_an_uncopied_permanent():
    """The control: the fix must not widen the sweep to everything, and the
    printed Antiquities cards must still go."""
    game, (sylex, thopter, bear) = _board(
        "Golgothian Sylex", "Ornithopter", "Grizzly Bears"
    )

    game.activate_permanent_ability(0, "Golgothian Sylex")
    game._settle()

    assert [perm.card.name for perm in game.all_permanents()] == ["Grizzly Bears"]


def test_city_in_a_bottle_takes_a_copy_wearing_an_arabian_nights_name():
    """The same rule through the other code path — a continuous state check
    rather than an activated sweep, so the two could have drifted."""
    bottle = Permanent(card=_POOL["City in a Bottle"])
    copier = Permanent(card=_POOL["Copy Artifact"])
    horse = Permanent(card=_POOL["Ebony Horse"])
    p1 = PlayerState(name="P1", battlefield=[bottle, copier])
    p2 = PlayerState(name="P2", battlefield=[horse])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    become_copy(copier, horse)

    game.check_state_based_actions()
    game._settle()

    assert [perm.card.name for perm in p1.battlefield] == ["City in a Bottle"]
    assert p2.battlefield == [], "the printed Arabian Nights card goes too"


def test_apocalypse_chime_takes_a_clone_wearing_a_homelands_name():
    """The third reader, and the one that arrived with the defect already in
    it: the Chime reads the phrase as an ``ObjectFilter`` rider, so its answer
    comes from ``permanent_matches_filter`` rather than from either sweep above.
    """
    game, (chime, troll, clone, bear) = _board(
        "Apocalypse Chime", "Sea Troll", "Clone", "Grizzly Bears"
    )
    become_copy(clone, troll)

    game.activate_permanent_ability(0, "Apocalypse Chime")
    game._settle()

    assert [perm.effective_card.name for perm in game.all_permanents()] == [
        "Grizzly Bears"
    ]
