"""CR 614.12 — a replacement effect that modifies how a permanent enters.

The Alliances lands are the pool's first "pay to enter": *if this land would
enter, sacrifice something instead*. Two rules decide almost everything about
how it has to be built.

CR 614.12a puts the **choice before the entry**, so a board that cannot pay is
answered by a consuming replacement — the permanent never enters, nothing that
watches an entry sees it, and the card goes to the zone the sentence names.
CR 614.13a says the entering permanent can never be one of the objects the
effect moves, which is why the toll excludes it rather than merely happening
not to match.

These are written against invented cards as well as printed ones wherever the
rule is about the *rule*: a test that only ever names Balduvian Trading Post
passes against an implementation keyed to that name.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.enter_effects import entry_sacrifice_requirement
from engine.models import CardDefinition, Permanent


@pytest.fixture(scope="module")
def pool():
    return {c.name: c for c in load_cards(manifest_set_paths(include_measured=True))}


def _land(name: str, text: str) -> CardDefinition:
    """An invented land printing *text* — the toll must be read off the words."""
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Land",
        oracle_text=text,
        colors=(),
        color_identity=(),
        keywords=(),
        produced_mana=("C",),
        raw={"name": name, "type_line": "Land", "oracle_text": text},
    )


def _game(pool, *battlefield):
    p1 = PlayerState(
        name="P1", battlefield=[Permanent(card=pool[n]) for n in battlefield]
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, p1


_TOLL = (
    "If this land would enter, sacrifice an untapped Mountain instead. If you "
    "do, put this land onto the battlefield. If you don't, put it into its "
    "owner's graveyard."
)


@pytest.mark.cr("614.1a", "614.12")
def test_the_toll_is_read_off_the_printed_words_not_off_a_name(pool):
    """An invented land with the same sentence pays the same toll.

    The point of the whole arrangement: five printed cards differ by one noun
    phrase, so the phrase is payload and a sixth printing needs no code.
    """
    invented = _land("Nobody's Trading Post", _TOLL)

    assert entry_sacrifice_requirement(invented) == {
        "filter": {"subtype_filter": "mountain", "untapped_only": True},
        "count": 1,
        "unpaid": "graveyard",
    }


@pytest.mark.cr("614.12a", "701.21a")
def test_the_toll_is_charged_as_the_permanent_enters(pool):
    game, p1 = _game(pool, "Mountain")

    game._put_permanent_onto_battlefield(
        0, Permanent(card=_land("Nobody's Trading Post", _TOLL)), None
    )

    assert [p.card.name for p in p1.battlefield] == ["Nobody's Trading Post"]
    assert [c.name for c in p1.graveyard] == ["Mountain"]


@pytest.mark.cr("614.12", "614.6")
def test_a_board_that_cannot_pay_stops_the_entry_entirely(pool):
    """A **consuming** replacement (CR 614.6: the original event never happens).

    The permanent must not appear on the battlefield even for an instant: an
    entry that happened and was then undone would have stamped a permanent id,
    made a layer contribution and announced every enters-the-battlefield
    trigger on the board.
    """
    game, p1 = _game(pool, "Forest")
    entering = Permanent(card=_land("Nobody's Trading Post", _TOLL))

    game._put_permanent_onto_battlefield(0, entering, None)

    assert [p.card.name for p in p1.battlefield] == ["Forest"]
    assert [c.name for c in p1.graveyard] == ["Nobody's Trading Post"]
    assert game.permanent_by_id(entering.permanent_id) is None


@pytest.mark.cr("614.13a")
def test_the_entering_permanent_cannot_pay_for_its_own_entry(pool):
    """"You can't choose the object that will become that permanent."

    Asked of a land whose toll its own printed type would answer: a Mountain
    that says "sacrifice an untapped Mountain instead". It is on the battlefield
    by the time the toll is charged, so it matches its own noun phrase -- and
    without the exclusion it would pay for itself, arriving and dying in one
    step while the Mountain it was supposed to cost stayed put.
    """
    self_paying = _land("Self-Paying Post", _TOLL)
    self_paying = CardDefinition(
        **{
            **{k: getattr(self_paying, k) for k in (
                "name", "mana_cost", "cmc", "oracle_text", "colors",
                "color_identity", "keywords", "produced_mana", "raw",
            )},
            "type_line": "Land — Mountain",
        }
    )
    game, p1 = _game(pool, "Mountain", "Mountain")
    game.interactive_seats = {0}
    entering = Permanent(card=self_paying)

    game._put_permanent_onto_battlefield(0, entering, None)
    offered = game.pending_sacrifice_state()

    # Three untapped Mountains are on the battlefield and the prompt offers two:
    # the exclusion is what the third one is missing for. Asserted against what
    # the *engine* queued rather than by re-deriving the candidate list, so a
    # version that forgot the exclusion fails here rather than agreeing with
    # itself.
    assert len(p1.battlefield) == 3
    assert offered is not None and len(offered["valid_indices"]) == 2
    assert p1.battlefield.index(entering) not in offered["valid_indices"]


@pytest.mark.cr("611.2a")
def test_an_animation_with_no_printed_duration_lasts_until_the_game_ends(pool):
    """"If no duration is stated, it lasts until the end of the game."

    Mishra's Groundbreaker's reminder text says so out loud; the rule is what
    makes the *absence* of "until end of turn" mean it, which is why the two
    spellings lower to two instruction kinds rather than one with a flag.
    """
    game, p1 = _game(pool, "Mishra's Groundbreaker", "Forest")
    for perm in p1.battlefield:
        perm.metadata["summoning_sickness_turn"] = -99
    forest = p1.battlefield[1]

    game.activate_permanent_ability(
        0, "Mishra's Groundbreaker", permanent_index=0,
        target_permanent_index=1, target_player_index=0,
    )
    game._settle()
    game.resolve_cleanup_step(0)
    game.resolve_untap_step(1)
    game.resolve_cleanup_step(1)

    assert forest.is_creature
    assert (forest.effective_power, forest.effective_toughness) == (3, 3)


@pytest.mark.cr("305.2")
def test_an_extra_land_play_can_be_granted_to_every_player(pool):
    """"Each player may play an additional land during each of their turns."

    CR 305.2's "continuous effects may increase this number" says nothing about
    whose effect it is, and the sentence names the seat. Reading Storm
    Cauldron's as Fastbond's would be a card that only ever helped its own
    controller.
    """
    game, _p1 = _game(pool, "Storm Cauldron")

    game.lands_played_this_turn[1] = 1

    assert game._may_play_another_land(1)
