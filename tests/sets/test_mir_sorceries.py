"""Per-card tests for Mirage's sorceries.

See tests/sets/README.md for the convention: get cards through
``set_pool("MIR")`` / ``set_cards("MIR")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

Organised as a sequence of self-contained round sections, each headed
``# --- Round N: <topic> ---`` and written up in ROADMAP.md under the round
that bought its cards.

**Parallel-authorship convention for this set.** Wave 1 splits by grammar
family rather than by printed type, so several groups land tests in this one
file. Each group appends a single delimited block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared header
loses it in exactly that move — a ``NameError`` at collection, found only after
the merge is committed. A self-contained block cannot lose one.

Do not edit the text above this paragraph, and do not edit an earlier group's
block. The integrator compares every branch's copy of this header against the
merge base byte for byte; a branch that changed it is a branch whose block
cannot be appended mechanically.
"""

from __future__ import annotations


# --- Round 6: narrowings the sweep and the tuck were dropping ---

from engine import Game, PlayerState
from engine.models import Permanent


def _r6_cast(set_pool, spell: str, own=(), theirs=()):
    pool = set_pool("MIR")
    mine = [Permanent(card=pool[name]) for name in own]
    yours = [Permanent(card=pool[name]) for name in theirs]
    game = Game(players=[
        PlayerState(name="P1", battlefield=mine, hand=[pool[spell]],
                    library=[pool["Island"]] * 5),
        PlayerState(name="P2", battlefield=yours, library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    result = game.cast_from_hand(0, spell)
    assert result.supported, result.details
    game.resolve_stack()
    return game, mine, yours


def test_blinding_light_taps_only_the_nonwhite(set_pool):
    """"Tap all **nonwhite** creatures."

    The sweep already resolves through ``subject_matches``, which tests
    ``exclude_colors`` like any other key — the whitelist in the lowering was
    the only thing refusing the word. Dropping it instead would have tapped the
    caster's own white team, which is the direction a dropped narrowing on a
    sweep always goes.
    """
    game, mine, yours = _r6_cast(
        set_pool, "Blinding Light",
        own=["Femeref Knight"],            # white
        theirs=["Cadaverous Knight"],      # black
    )

    assert not mine[0].tapped
    assert yours[0].tapped


def test_fallow_earth_tucks_a_land(set_pool):
    """"Put target land on top of its owner's library." The other card the
    creature-pinned tuck refused."""
    pool = set_pool("MIR")
    land = Permanent(card=pool["Island"])
    game = Game(players=[
        PlayerState(name="P1", hand=[pool["Fallow Earth"]], library=[pool["Island"]] * 5),
        PlayerState(name="P2", battlefield=[land], library=[pool["Island"]] * 5),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    result = game.cast_from_hand(
        0, "Fallow Earth", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert not game.is_on_battlefield(land)
    assert game.players[1].library[0].name == "Island"


# --- W1G4: the zones / cards / library family ---

from engine import Game as _W1G4Game, PlayerState as _W1G4PlayerState
from engine.models import Permanent as _W1G4Permanent


def test_polymorph_reanimates_off_the_victims_own_library(set_pool):
    """"Destroy target creature. It can't be regenerated. **Its controller**
    reveals cards from the top of their library until they reveal a creature
    card. The player puts that card onto the battlefield, then shuffles all
    other cards revealed this way into their library."

    Transmogrify's procedure behind a destroy instead of an exile, and three
    words apart from it: "its controller" for "that creature's controller",
    "the player" for "that player", and "all other cards revealed this way" for
    "the rest". None of the three changes what the card does, so they are
    alternatives inside the one rider rather than a second production.

    The creature arrives on the *victim's* battlefield, out of the *victim's*
    library -- the seat the destroy recorded, not the caster.
    """
    pool = set_pool("MIR")
    game = _W1G4Game(players=[
        _W1G4PlayerState(name="P1", hand=[pool["Polymorph"]],
                         library=[pool["Island"]] * 5),
        _W1G4PlayerState(
            name="P2", battlefield=[_W1G4Permanent(card=pool["Femeref Scouts"])],
            library=[pool["Island"], pool["Mountain"], pool["Viashino Warrior"],
                     pool["Plains"]],
        ),
    ])
    game.interactive_seats = set()
    game.enforce_mana_costs = False
    game.start_turn(0)

    result = game.cast_from_hand(
        0, "Polymorph", target_player_index=1, target_permanent_index=0
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert [c.name for c in game.players[1].graveyard] == ["Femeref Scouts"]
    assert [p.card.name for p in game.players[1].battlefield] == ["Viashino Warrior"]
    assert game.players[0].battlefield == [], "the caster reanimates nothing"
    assert sorted(c.name for c in game.players[1].library) == [
        "Island", "Mountain", "Plains",
    ], "the cards revealed on the way are shuffled back, not milled"
    assert game.players[1].graveyard == [
        card for card in game.players[1].graveyard if card.name == "Femeref Scouts"
    ], "nothing revealed reached a graveyard"


def _w1g4_look_board(set_pool, spell, *, library, seat1_hand=(), interactive=(0,)):
    pool = set_pool("MIR")
    game = _W1G4Game(players=[
        _W1G4PlayerState(name="P1", hand=[pool[spell]],
                         library=[pool[n] for n in library]),
        _W1G4PlayerState(name="P2", hand=[pool[n] for n in seat1_hand],
                         library=[pool["Mountain"]] * 4),
    ])
    game.interactive_seats = set(interactive)
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, pool


_W1G4_SEVEN = (
    "Femeref Scouts", "Viashino Warrior", "Mana Prism", "Fire Diamond",
    "Island", "Mountain", "Plains", "Swamp", "Forest",
)


def test_ancestral_memories_takes_two_and_bins_the_other_five(set_pool):
    """"Look at the top seven cards of your library. Put **two** of them into
    your hand and the rest into your graveyard."

    Two firsts for this template: a pick count other than one -- the word "one"
    was a literal in the production, so the only card in the pool that takes two
    refused on the number it printed -- and "the rest **into your graveyard**"
    as a destination for the whole remainder, where Waker of Waves prints that
    fate for a single named card.

    The two picks are a *chain* of one-card prompts, because taking a card
    renumbers the pile behind it. The assertions are about counts as much as
    names: seven leave the library, two reach the hand, five reach the
    graveyard, and the spell itself resolves only once the last prompt is
    answered (CR 608.2).
    """
    game, _ = _w1g4_look_board(set_pool, "Ancestral Memories", library=_W1G4_SEVEN)

    assert game.cast_from_hand(0, "Ancestral Memories").supported
    assert game.waiting_prompt() is not None, "the resolution waits (CR 117.3b)"

    assert game.confirm_look_top_pick(0, 2), "Mana Prism"
    assert [c.name for c in game.players[0].hand] == ["Mana Prism"]
    assert game.waiting_prompt() is not None, "one pick still owed"

    assert game.confirm_look_top_pick(0, 0), "Femeref Scouts, after the renumber"

    assert [c.name for c in game.players[0].hand] == ["Mana Prism", "Femeref Scouts"]
    assert [c.name for c in game.players[0].graveyard] == [
        "Viashino Warrior", "Fire Diamond", "Island", "Mountain", "Plains",
        "Ancestral Memories",
    ], "five looked-at cards, then the spell itself"
    assert [c.name for c in game.players[0].library] == ["Swamp", "Forest"]
    assert game.pending_choices == []


def test_ancestral_memories_drains_both_picks_for_a_non_interactive_seat(set_pool):
    """The AI path takes the same two cards through the same chain -- a default
    that answered once would leave the second prompt queued and the spell
    resolving forever."""
    game, _ = _w1g4_look_board(
        set_pool, "Ancestral Memories", library=_W1G4_SEVEN, interactive=()
    )

    game.cast_from_hand(0, "Ancestral Memories")
    game.auto_resolve_pending_choices()

    assert len(game.players[0].hand) == 2
    assert len(game.players[0].library) == 2
    assert game.pending_choices == []


def test_painful_memories_tucks_the_chosen_card_and_takes_only_one_copy(set_pool):
    """"Look at target opponent's hand and choose a card from it. Put that card
    on top of that player's library."

    Mind Warp's template with the other printed ending, so ``fate`` grows a
    third value rather than the family a second node. The count assertion is
    the one that matters here: a hand repeats the *same* ``CardDefinition``
    object for every copy, so a removal spelled as an identity filter takes all
    of them -- the tuck goes through ``take_card_from_hand`` and moves exactly
    one.
    """
    game, pool = _w1g4_look_board(
        set_pool, "Painful Memories", library=("Island",) * 5,
        seat1_hand=("Island", "Mana Prism", "Island"),
    )

    assert game.cast_from_hand(0, "Painful Memories", target_player_index=1).supported
    assert game.resolve_pending_choice("revealed_hand_pick", 0, hand_index=0)

    assert [c.name for c in game.players[1].hand] == ["Mana Prism", "Island"], (
        "one Island moved, not both"
    )
    assert game.players[1].library[0].name == "Island"
    assert len(game.players[1].library) == 5
    assert game.players[1].graveyard == [], "a tuck is not a discard"
