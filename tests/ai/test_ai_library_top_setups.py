"""What a cast that sets up the top of its caster's own library is worth.

"Search your library for a card, then shuffle and put that card on top"
(Vampiric Tutor, Mystical Tutor, Enlightened Tutor, Worldly Tutor; Insidious
Dreams' X cards; Scouting Trek's basic lands). The finds stay in the library,
so ``ai_rehearsal.rehearse`` — which prices a hand, a life total and a board
— read the cast as moving nothing it could price: Vampiric Tutor was its 2
life and never proposed, Mystical Tutor was a cast worth nothing, and
Insidious Dreams was its discards (Torment's W1G5 measured it and left it).

The reading, decided here and asked of the compiled program rather than of a
card (``ai_valuation.library_top_setups``): a card put on top of the caster's
own library is **a draw chosen**. For each of the next
``CHOSEN_DRAWS_COUNTED`` draws it decides, a ``CHOSEN_DRAW_SHARE`` of how much
better the find is than the library's average card — the draw a seat that
cast nothing would make — held to a card either way, since a standing counts
a card in hand as ``CARD_WORTH``. The finds are the ones the seat's own search
picks (``_score_tutor_choice``, the scorer the search asks), out of the cards
its library holds: its own deck, known though not in order.

So a chosen draw is worth at most half a card, and **Insidious Dreams, which
pays a card in hand for each chosen draw, is still not proposed for its own
sake** — now because it is priced, not because it is unseen. What would make
it worth casting is a discard the standing reads as cheaper than a card (a
madness card, a card that cannot be cast), which is the discard cost's
valuation and not this one.

Validated backwards on 053649ac: Vampiric Tutor not proposed, every tutor's
rehearsal reading 0 (or -2) where it reads a chosen draw now.
"""
from __future__ import annotations

import random

from engine import Game, PlayerState
from engine.ai_scoring import (
    CHOSEN_DRAW_SHARE,
    CHOSEN_DRAWS_COUNTED,
    _announcement,
    _rehearse_announcement,
)
from engine.ai_policy import choose_cast_action
from engine.ai_rehearsal import CARD_WORTH
from engine.ai_valuation import library_top_setups
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle

ME, OPP = 0, 1


def _pool() -> dict:
    cards: dict = {}
    for card in load_cards(manifest_set_paths(include_measured=True)):
        cards.setdefault(card.name, card)
    return cards


POOL = _pool()
#: A library with something worth finding for every tutor's restriction.
LIBRARY = (
    "Forest", "Shivan Dragon", "Lightning Bolt", "Sol Ring", "Grizzly Bears",
    "Island", "Ancestral Recall", "Serra Angel", "Swamp", "Counterspell",
    "Mountain", "Giant Growth", "Plains", "Wrath of God", "Llanowar Elves",
)
TUTORS = ("Vampiric Tutor", "Mystical Tutor", "Enlightened Tutor", "Worldly Tutor")


def _table(card, *, hand=(), lands=0) -> Game:
    game = Game(players=[
        PlayerState(
            name="AI", hand=[card, *(POOL[name] for name in hand)],
            library=[POOL[name] for name in LIBRARY],
        ),
        PlayerState(name="Opp", hand=[POOL["Forest"]], library=[POOL["Forest"]] * 10),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.current_turn_phase = "precombat_main"
    for _ in range(lands):
        land = Permanent(card=POOL["Forest"])
        game._put_permanent_onto_battlefield(ME, land, ME)
    game.players[ME].mana_pool.update({symbol: 8 for symbol in "WUBRGC"})
    return game


def _rehearsed(game, card, x_value=None):
    random.seed(1337)
    return _rehearse_announcement(
        game, ME, card,
        _announcement(card, target=OPP, caster=ME, x_value=x_value),
    )


def test_which_casts_set_up_the_top_is_the_program_s_answer():
    """Every instant and sorcery in the pool whose search puts its finds on
    top of its caster's library — and Doomsday, which exiles the rest of the
    library, is not a setup."""
    # Each half of a split card is a spell of its own (CR 709.3), so the
    # pool is read a compilation unit at a time.
    found = {
        unit.name for unit in compilation_units(POOL.values())
        if unit.primary_type in ("instant", "sorcery")
        and compile_card_oracle(unit).supported
        and library_top_setups(unit, x_value=1)
    }
    assert {*TUTORS, "Insidious Dreams", "Scouting Trek"} <= found, sorted(found)
    assert "Doomsday" not in found
    assert "Demonic Tutor" not in found  # to the hand: a standing sees it


def test_a_tutor_to_the_top_reads_a_chosen_draw():
    """Each tutor's rehearsal now reads the find on top (+half a card, the
    find being far better than the library's average) on top of what it
    costs: Vampiric Tutor's 2 life leaves it at nothing lost, and the rest
    gain."""
    for name in TUTORS:
        card = POOL[name]
        rehearsal = _rehearsed(_table(card), card)
        assert rehearsal is not None and rehearsal.accepted, name
        assert rehearsal.lasting > -0.5, (name, rehearsal)
    mystical = POOL["Mystical Tutor"]
    assert _rehearsed(_table(mystical), mystical).lasting == CHOSEN_DRAW_SHARE * CARD_WORTH


def test_vampiric_tutor_is_proposed_with_nothing_better_to_cast():
    """Before: its rehearsal read 2 life lost and nothing found, and a seat
    holding it and nothing else passed every turn."""
    card = POOL["Vampiric Tutor"]
    random.seed(1337)
    action = choose_cast_action(_table(card), ME)
    assert action is not None and action.card_name == "Vampiric Tutor", action


def test_insidious_dreams_pays_more_than_its_chosen_draws_are_worth():
    """The decision this reading makes: a chosen draw is worth at most half a
    card, so discarding X cards to choose X draws is a loss, and the cast is
    not proposed — priced, where it used to be unseen."""
    card = POOL["Insidious Dreams"]
    game = _table(card, hand=("Grizzly Bears", "Forest"))
    rehearsal = _rehearsed(game, card, x_value=2)
    assert rehearsal is not None and rehearsal.accepted
    assert rehearsal.lasting == -2 * CARD_WORTH + 2 * CHOSEN_DRAW_SHARE * CARD_WORTH
    random.seed(1337)
    action = choose_cast_action(game, ME)
    assert action is None or action.card_name != "Insidious Dreams", action
    assert CHOSEN_DRAWS_COUNTED == 2


def test_lands_on_top_are_worth_less_than_a_draw_with_lands_enough():
    """Signed: with five lands on the table, Scouting Trek's basic lands on
    top are worse draws than the library's average card, and the setup reads
    as a loss rather than as nothing."""
    card = POOL["Scouting Trek"]
    rehearsal = _rehearsed(_table(card, lands=5), card)
    assert rehearsal is not None and rehearsal.accepted
    assert rehearsal.lasting < 0, rehearsal
