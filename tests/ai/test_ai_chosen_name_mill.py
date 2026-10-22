"""The name a seat nobody asks chooses for "Choose a card name, then target
player mills a card" (Predict, Foreshadow).

Predict draws two cards when the milled card has the chosen name and one
otherwise, and may be aimed at any player. The default named the commonest
card in the **opponent's graveyard** whoever was milled — so a seat that aimed
the spell at itself (which is where this policy aims it) milled its own
library looking for somebody else's card, and with that graveyard empty named
nothing at all. One card, every time: W1G4's measurement.

What a seat may know is the whole question (CR 400.2: a library is a hidden
zone; CR 401.2: nobody may look at or reorder one). A player built their own
deck, so *what* their own library still holds is theirs to work out, and only
which card is where is hidden — the reading Wood Sage's and Desperate
Research's defaults already make. An opponent's library is hidden outright,
and the public evidence of what it holds is that seat's graveyard. So: milled
from the chooser's own library, the commonest name left in it; milled from
another seat's, the commonest name in that seat's graveyard, as before.

The tests include the two that show the default does not peek.
"""
from __future__ import annotations

import pytest

from engine.ai_policy import choose_cast_action
from engine.ai_prompt_readers import (
    chosen_name_is_read_off_the_targets_library,
    chosen_name_own_zone,
)
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.game import Game
from engine.models import PlayerState
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack

ME, OPP = 0, 1


@pytest.fixture(scope="module")
def pool(set_pool, catalog_by_name):
    return {**catalog_by_name, **set_pool("ODY")}


def _duel(pool, spell: str, *, my_library, their_library=(), their_graveyard=()):
    def cards(names):
        return [pool[name] for name in names]

    me = PlayerState(name="AI", hand=[pool[spell]], library=cards(my_library))
    opp = PlayerState(
        name="Opp", library=cards(their_library) or [pool["Forest"]] * 5,
        graveyard=cards(their_graveyard),
    )
    game = Game(players=[me, opp])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = ME
    return game


def _cast(game, spell: str, target: int) -> None:
    assert game.cast_from_hand(ME, spell, target_player_index=target).supported
    game.auto_resolve_pending_choices()
    resolve_stack(game)


def _named(game) -> str:
    return next(line for line in game.log if line.startswith("AI named"))


def test_predict_aimed_at_its_caster_names_what_the_casters_library_holds(pool):
    """Nine Islands and three Grizzly Bears: "Island", and with one on top the
    spell draws its two cards."""
    game = _duel(pool, "Predict", my_library=["Island"] * 9 + ["Grizzly Bears"] * 3)
    assert choose_cast_action(game, ME).target_player_index == ME

    _cast(game, "Predict", ME)

    assert _named(game) == "AI named Island"
    assert len(game.players[ME].hand) == 2
    assert [card.name for card in game.players[ME].graveyard][0] == "Island"


def test_the_default_counts_the_library_and_does_not_look_at_its_top(pool):
    """The same library with a Grizzly Bears on top: still "Island" — the
    commonest name, not the card that is there — so the Bears are milled and
    one card is drawn. A default that peeked would never miss."""
    game = _duel(pool, "Predict", my_library=["Grizzly Bears"] + ["Island"] * 9)

    _cast(game, "Predict", ME)

    assert _named(game) == "AI named Island"
    assert len(game.players[ME].hand) == 1
    assert "Grizzly Bears" in [card.name for card in game.players[ME].graveyard]


def test_predict_aimed_at_another_seat_never_reads_that_seats_library(pool):
    """An opponent's library is a hidden zone (CR 400.2). Every card in it is a
    Hill Giant and the default names nothing, because that seat's graveyard —
    the only thing the caster may know — is empty; with two Mountains binned
    it names Mountain, and misses."""
    blind = _duel(
        pool, "Predict", my_library=["Island"] * 9, their_library=["Hill Giant"] * 6,
    )
    informed = _duel(
        pool, "Predict", my_library=["Island"] * 9, their_library=["Hill Giant"] * 6,
        their_graveyard=["Mountain", "Mountain", "Craw Wurm"],
    )

    _cast(blind, "Predict", OPP)
    _cast(informed, "Predict", OPP)

    assert _named(blind) == "AI named nothing"
    assert _named(informed) == "AI named Mountain"
    assert len(blind.players[ME].hand) == 1 and len(informed.players[ME].hand) == 1
    assert len(blind.players[OPP].library) == 5


def test_foreshadow_still_names_out_of_the_opponents_graveyard(pool):
    """"…then target **opponent** mills a card." The milled seat is never the
    chooser, so the answer is what it was."""
    game = _duel(
        pool, "Foreshadow", my_library=["Island"] * 9,
        their_library=["Hill Giant"] * 6,
        their_graveyard=["Mountain", "Mountain", "Craw Wurm"],
    )

    _cast(game, "Foreshadow", OPP)

    assert _named(game) == "AI named Mountain"


def test_every_card_that_chooses_a_card_name_has_a_place_to_look():
    """The census, with its floor: five cards print "choose a card name" as a
    step of their own, and each one's name is looked for somewhere this policy
    can name — the chooser's own zone, or the milled player's library."""
    readers: dict[str, str] = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        program = compile_card_oracle(card)
        if not program.supported:
            continue

        def walk(step):
            yield step
            for key in ("steps", "then", "else", "action", "otherwise"):
                for inner in (step.payload or {}).get(key) or ():
                    if hasattr(inner, "kind"):
                        yield from walk(inner)

        roots = [
            *program.instructions,
            *(ability.instruction for ability in program.activated_abilities),
            *(ability.instruction for ability in program.triggered_abilities),
        ]
        for root in roots:
            for step in walk(root) if root is not None else ():
                if step.kind != "choose_card_name":
                    continue
                if chosen_name_is_read_off_the_targets_library(card, step):
                    readers[card.name] = "the target's library"
                else:
                    readers[card.name] = chosen_name_own_zone(card, step) or "nowhere"

    assert len(readers) >= 5, readers
    assert readers["Predict"] == "the target's library"
    assert readers["Foreshadow"] == "the target's library"
    assert readers["Wood Sage"] == "library"
    assert readers["Cursed Scroll"] == "hand"
    assert "nowhere" not in readers.values(), readers
