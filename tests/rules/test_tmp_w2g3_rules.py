"""Tempest wave 2, group 3 — the rules behind the board-wide statics.

Four of this group's cards turned out to be a *rule* the engine implemented for
one printing and refused for another, so the tests that matter are about the
rule rather than about the card:

* **CR 106.7** — what mana a permanent "could produce". Reflecting Pool is the
  first land in this pool whose own production is derived, and the naive union
  over the board reads its ingested ``produced_mana`` (all five colours) and
  taps for anything. The rule's own worked example is this family, and Fellwar
  Stone — shipped since The Dark — was reading it the naive way.
* **CR 502.3** — the untap step's count limit, whose scope word may be
  "permanent" (CR 110.1) and not only a card type.
* **CR 614.1** — a damage multiplier, and the two printed words that vary.
* **CR 500.7** — an extra turn taken by a player the spell names.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.mana_could_produce import (
    could_produce_by_seat,
    derived_producer_board,
)
from engine.models import Permanent
from engine.damage_events import deal_damage
from engine.replacements import damage_multiplier_line
from tests.helpers import _mk_card
from engine.untap_restrictions import (
    ANY_PERMANENT_SCOPE,
    permanent_in_limited_scope,
    untap_restriction_for,
)


def _card(name, type_line, text="", produced=()):
    return _mk_card(
        name=name, type_line=type_line, oracle_text=text,
        produced_mana=tuple(produced),
    )


def _game(mine, theirs=()):
    p1 = PlayerState(name="P1", battlefield=[Permanent(card=c) for c in mine])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=c) for c in theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game


_DERIVED = "{T}: Add one mana of any color that a land an opponent controls could produce."
_DERIVED_OWN = "{T}: Add one mana of any type that a land you control could produce."


# ---------------------------------------------------------------------------
# CR 106.7 — "could produce"
# ---------------------------------------------------------------------------


@pytest.mark.cr("106.7")
def test_a_land_that_says_what_it_makes_could_produce_it():
    """The ordinary case: ``produced_mana`` is the answer."""
    game = _game([_card("Wood", "Land", produced=("G",))])

    assert could_produce_by_seat(game)[0] == frozenset({"G"})


@pytest.mark.cr("106.7")
def test_a_derived_producer_alone_defines_no_type():
    """"If that permanent wouldn't produce any mana under these conditions, or
    no type of mana can be defined this way, there's no type of mana it could
    produce."

    The trap is that the ingested data says otherwise: Scryfall records this
    family's ``produced_mana`` as every colour the card could ever make, which
    is what a plain union over the board would read.
    """
    orchard = _card("Orchard", "Land", _DERIVED_OWN, produced=("W", "U", "B", "R", "G"))
    game = _game([orchard])

    assert could_produce_by_seat(game)[0] == frozenset()


@pytest.mark.cr("106.7")
def test_two_derived_producers_reading_each_other_define_nothing():
    """The rule's own example, with the boards swapped for the two cards this
    pool has: "the same is true if you and your opponent each control no lands
    other than Exotic Orchards"."""
    orchard = _card("Orchard", "Land", _DERIVED, produced=("W", "U", "B", "R", "G"))
    game = _game([orchard], [_card("Theirs", "Land", _DERIVED, produced=("W", "U"))])

    assert could_produce_by_seat(game)[0] == frozenset()
    assert could_produce_by_seat(game)[1] == frozenset()


@pytest.mark.cr("106.7")
def test_the_fixpoint_carries_one_link(monkeypatch):
    """"However, if you control a Forest and an Exotic Orchard, and your
    opponent controls an Exotic Orchard, then each Exotic Orchard could produce
    {G}."

    Which is why this is a fixpoint and not a scan: the opponent's Orchard has
    to see the Forest *through* the Orchard beside it.
    """
    orchard = _card("Orchard", "Land", _DERIVED, produced=("W", "U", "B", "R", "G"))
    forest = _card("Wood", "Land", produced=("G",))
    game = _game([forest, orchard], [orchard])

    by_seat = could_produce_by_seat(game)
    assert by_seat[0] == frozenset({"G"})
    assert by_seat[1] == frozenset({"G"}), "read through the Orchard on seat 0"


@pytest.mark.cr("106.7")
def test_a_colourless_land_answers_type_and_not_colour():
    """CR 106.1b counts six types, the five colours and colourless — which is
    the whole reason "any **type** that a land you control could produce"
    (Reflecting Pool) and "any **color** …" (Fellwar Stone) cannot share a
    branch."""
    from engine.mana_could_produce import (
        colors_a_land_an_opponent_controls_could_produce,
        types_a_land_you_control_could_produce,
    )

    game = _game([_card("Waste", "Land", produced=("C",))],
                 [_card("Waste", "Land", produced=("C",))])

    assert types_a_land_you_control_could_produce(game, 0) == frozenset({"C"})
    assert colors_a_land_an_opponent_controls_could_produce(game, 0) == frozenset()


@pytest.mark.cr("106.7")
def test_which_board_a_derived_producer_reads_is_read_off_its_text():
    """The two printed phrases, and None for a land that simply says what it
    makes."""
    assert derived_producer_board(_card("A", "Land", _DERIVED_OWN)) == "controlled_lands"
    assert derived_producer_board(_card("B", "Land", _DERIVED)) == "opponent_lands"
    assert derived_producer_board(_card("C", "Land", "", produced=("G",))) is None


# ---------------------------------------------------------------------------
# CR 502.3 — the untap step's count limit
# ---------------------------------------------------------------------------


@pytest.mark.cr("502.3", "110.1")
def test_a_count_limit_may_name_permanents_rather_than_a_card_type():
    """"Players can't untap more than two **permanents** during their untap
    steps." (Static Orb.)

    CR 110.1 makes every object on the battlefield a permanent, so the word is
    not a card type and ``Permanent.has_type`` has nothing to answer with. The
    table reads it as a scope beside land / creature / artifact, and one shared
    predicate is what keeps the untap step and the web layer's selection split
    from disagreeing about which permanents the cap covers.
    """
    restriction = untap_restriction_for(
        "Players can't untap more than two permanents during their untap steps."
    )

    assert restriction.scope == ANY_PERMANENT_SCOPE
    assert restriction.limit == 2

    land = Permanent(card=_card("Wood", "Land"))
    assert permanent_in_limited_scope(land, ANY_PERMANENT_SCOPE)
    assert permanent_in_limited_scope(land, "land")
    assert not permanent_in_limited_scope(land, "creature")


@pytest.mark.cr("502.3")
def test_the_active_player_chooses_which_permanents_untap_under_a_cap():
    """"Normally, all of a player's permanents untap, but effects can keep one
    or more of a player's permanents from untapping." The choice is the
    controller's, so the candidate list has to be every tapped permanent rather
    than the tapped members of one card type."""
    orb = _card(
        "Orb", "Artifact",
        "Players can't untap more than two permanents during their untap steps.",
    )
    game = _game([orb, _card("Wood", "Land"), _card("Bear", "Creature — Bear"),
                  _card("Rock", "Artifact")])
    for permanent in list(game.players[0].battlefield)[1:]:
        permanent.tapped = True

    options = game.get_untap_land_selection_options(0)

    assert options["limits"] == {ANY_PERMANENT_SCOPE: 2}
    assert options["candidate_indices"] == [1, 2, 3]
    assert game.resolve_untap_step(0) == 2


# ---------------------------------------------------------------------------
# CR 614.1 / CR 616.1 — a damage multiplier
# ---------------------------------------------------------------------------


@pytest.mark.cr("614.1a")
def test_a_damage_multiplier_reads_its_factor_and_its_narrowing():
    """One sentence, two payload words. "A source **you control** … **triple**"
    (Fiery Emancipation) and "a source … **double**" (Furnace of Rath) differ in
    nothing else, and the second's missing narrowing is what makes it apply to
    its own controller's opponents."""
    assert damage_multiplier_line(
        "If a source would deal damage to a permanent or player, it deals "
        "double that damage to that permanent or player instead."
    ) == (2, False)
    assert damage_multiplier_line(
        "If a source you control would deal damage to a permanent or player, "
        "it deals triple that damage to that permanent or player instead."
    ) == (3, True)


@pytest.mark.cr("616.1e")
def test_multipliers_compose_rather_than_replacing_each_other():
    """CR 616.1 applies them one at a time and lets the affected player choose
    the order; multiplication does not care, so one interceptor taking the
    product is the same game. One that returned a single card's factor would
    drop the other, because an effect applies once per event."""
    furnace = _card(
        "Furnace", "Enchantment",
        "If a source would deal damage to a permanent or player, it deals "
        "double that damage to that permanent or player instead.",
    )
    emancipation = _card(
        "Emancipation", "Enchantment",
        "If a source you control would deal damage to a permanent or player, "
        "it deals triple that damage to that permanent or player instead.",
    )
    game = _game([furnace, emancipation])
    source = game.players[0].battlefield[0]

    outcome = deal_damage(
        game,
        {
            "recipient": game.players[1],
            "amount": 1,
            "source": source,
            "combat": False,
        },
    )

    assert outcome.dealt == 6, "doubled and tripled, in either order"
