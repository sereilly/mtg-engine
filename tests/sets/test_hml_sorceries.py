"""Per-card tests for Homelands' sorceries.

See tests/sets/README.md for the convention: get cards through
``set_pool("HML")`` / ``set_cards("HML")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The waves that implement HML
split by grammar family rather than by printed type, so several groups land
tests in this one file. Each group appends a single delimited block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.

Do not edit the text above. The integrator compares every branch's copy of this
header against the merge base byte for byte; a branch that changed it is a
branch whose block cannot be appended mechanically.
"""

from __future__ import annotations


# --- W1G3: prevention, redirection and filtered damage ---

from engine import Game, PlayerState
from engine.models import Permanent


def _g3_cast(set_pool, spell, *battlefield, poison=0):
    """Cast *spell* from HML at seat 1, with *battlefield* on the opponent's
    board, and resolve it.

    ``(set_code, name)`` pairs for the creatures, because these two spells are
    both about which permanents a printed noun phrase names and the pool has to
    contain ones it does *not*.
    """
    perms = [Permanent(card=set_pool(code)[name]) for code, name in battlefield]
    p0 = PlayerState(name="P0", hand=[set_pool("HML")[spell]])
    p1 = PlayerState(name="P1", battlefield=perms)
    p1.poison_counters = poison
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game._settle()
    result = game.cast_from_hand(0, spell, target_player_index=1)
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()
    return game, result, p1, perms


def test_evaporate_burns_every_white_or_blue_creature_and_nothing_else(set_pool):
    """"Evaporate deals 1 damage to each white and/or blue creature."

    The printed conjunction is a **union** (CR 105.2 gives an object one or more
    colours), so a white creature and a blue one are both in the set and a green
    one is not. Read as an intersection the spell would hit nothing at all; read
    with the conjunction dropped it would hit the whole board.
    """
    game, result, _p1, (white, blue, green) = _g3_cast(
        set_pool, "Evaporate",
        ("LEA", "White Knight"),
        ("LEA", "Merfolk of the Pearl Trident"),
        ("LEA", "Grizzly Bears"),
    )

    assert result.supported, result.details
    assert white.damage_marked == 1
    assert not game.is_on_battlefield(blue), "a 1/1 took lethal damage"
    assert green.damage_marked == 0, "green is neither white nor blue"


def test_leeches_deals_the_number_of_counters_it_actually_removed(set_pool):
    """"Target player loses all poison counters. Leeches deals that much damage
    to that player."

    "That much" is the count the *first* sentence took off, read out of the
    resolution's scratchpad — by the time the damage runs the store holds zero,
    so a reading that asked the player again would deal nothing.
    """
    _game, result, victim, _perms = _g3_cast(set_pool, "Leeches", poison=3)

    assert result.supported, result.details
    assert victim.poison_counters == 0
    assert victim.life == 17


def test_leeches_deals_nothing_to_an_unpoisoned_player(set_pool):
    """The same back-reference from the other end: nothing was removed, so
    nothing is dealt. A "that much" that fell back to a printed number would
    make this spell a burn spell."""
    _game, result, victim, _perms = _g3_cast(set_pool, "Leeches", poison=0)

    assert result.supported, result.details
    assert victim.life == 20


# --- W1G2: counted amounts ---

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.models import CardDefinition, Permanent


def _w1g2_game(mine, hand, theirs=()):
    p1 = PlayerState(name="P1", battlefield=list(mine), hand=list(hand))
    p2 = PlayerState(name="P2", battlefield=list(theirs))
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._settle()
    return game, p1, p2


def _w1g2_creature(name, colors=("G",), toughness="4"):
    return Permanent(card=CardDefinition(
        name=name, mana_cost="{1}", cmc=1.0, type_line="Creature — Human",
        oracle_text="", colors=tuple(colors), color_identity=tuple(colors),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature — Human",
             "power": "1", "toughness": toughness},
    ))


def _w1g2_aura(name):
    return Permanent(card=CardDefinition(
        name=name, mana_cost="{1}", cmc=1.0, type_line="Enchantment — Aura",
        oracle_text="Enchant creature", colors=("U",), color_identity=("U",),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Enchantment — Aura"},
    ))


def test_an_havva_inn_gains_one_more_than_the_green_creatures_everywhere(set_pool):
    """"You gain **X plus 1** life, where X is the number of green creatures
    **on the battlefield**."

    Both halves of the arithmetic are printed and both have somewhere to go
    wrong: the count spans every seat (CR 403.1's shared zone), and the
    constant is added to it rather than being the whole amount."""
    pool = set_pool("HML")
    game, p1, p2 = _w1g2_game(
        [_w1g2_creature("Mine"), _w1g2_creature("Red", colors=("R",))],
        [pool["An-Havva Inn"]],
        theirs=[_w1g2_creature("Theirs")],
    )

    result = game.cast_from_hand(0, "An-Havva Inn")
    game._settle()

    assert result.supported, result.details
    # Two green creatures on the battlefield, plus 1.
    assert p1.life == 23


def test_an_havva_inn_gains_one_with_no_green_creature_at_all(set_pool):
    """The printed constant is paid whatever the count says. A reading that
    made the "plus 1" part of the *count* rather than part of the amount would
    be the same number here and a different one nowhere — which is exactly why
    it is worth pinning the floor."""
    pool = set_pool("HML")
    game, p1, p2 = _w1g2_game([], [pool["An-Havva Inn"]])

    game.cast_from_hand(0, "An-Havva Inn")
    game._settle()

    assert p1.life == 21


def test_bakis_curse_damages_each_creature_by_its_own_aura_count(set_pool):
    """"Baki's Curse deals 2 damage to each creature **for each Aura attached
    to that creature**."

    The multiplier is re-counted per recipient: "that creature" is whichever
    creature is being damaged, not one object the spell chose. Folded into the
    single X every other computed amount rides on, the count taken off the
    first creature would have been dealt to all of them."""
    pool = set_pool("HML")
    bare = _w1g2_creature("Bare", toughness="4")
    one = _w1g2_creature("One Aura", toughness="4")
    two = _w1g2_creature("Two Auras", toughness="9")
    auras = [_w1g2_aura("Aura A"), _w1g2_aura("Aura B"), _w1g2_aura("Aura C")]
    game, p1, p2 = _w1g2_game(
        [bare, one, two, *auras], [pool["Baki's Curse"]],
    )
    attach_aura(auras[0], one)
    attach_aura(auras[1], two)
    attach_aura(auras[2], two)

    result = game.cast_from_hand(0, "Baki's Curse")
    game._settle()

    assert result.supported, result.details
    assert (bare.damage_marked, one.damage_marked, two.damage_marked) == (0, 2, 4)


def test_bakis_curse_deals_nothing_to_an_unenchanted_creature(set_pool):
    """CR 120.8: a source that *would* deal 0 damage does not deal damage at
    all. A creature with no Aura on it is not dealt 0 by Baki's Curse, it is
    not dealt to — so nothing that triggers on damage triggers, and no shield
    is spent."""
    pool = set_pool("HML")
    bare = _w1g2_creature("Bare", toughness="4")
    game, p1, p2 = _w1g2_game([bare], [pool["Baki's Curse"]])

    game.cast_from_hand(0, "Baki's Curse")
    game._settle()

    assert bare.damage_marked == 0
    assert not bare.metadata.get("was_dealt_damage_this_turn")


def test_bakis_curse_counts_an_opponents_aura_on_your_creature(set_pool):
    """What is attached to a permanent is a record kept on that permanent, so
    the count is not a battlefield scan and inherits no controller scope — an
    opponent's Aura on your creature is attached to your creature."""
    pool = set_pool("HML")
    mine = _w1g2_creature("Mine", toughness="4")
    theirs = _w1g2_aura("Their Aura")
    game, p1, p2 = _w1g2_game([mine], [pool["Baki's Curse"]], theirs=[theirs])
    attach_aura(theirs, mine)

    game.cast_from_hand(0, "Baki's Curse")
    game._settle()

    assert mine.damage_marked == 2



# --- W2G2: library search, reveal and tuck ---

from engine import Game as _G2Game, PlayerState as _G2PlayerState
from engine.oracle import compile_card_oracle as _g2_compile
from engine.targeting import derive_cast_spec as _g2_cast_spec


def _g2_duel(*, interactive=(0,)):
    """A two-seat game with costs off. Seat 0 is interactive by default, so a
    prompt this group arms is *queued* rather than answered by its own default —
    ROADMAP idiom 39: a headless probe cannot tell "nobody was asked" from
    "nobody was there to ask"."""
    p0, p1 = _G2PlayerState(name="A"), _G2PlayerState(name="B")
    game = _G2Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, p0, p1


def test_merchant_scroll_offers_only_blue_instants(set_pool, catalog_by_name):
    """"Search your library for **a blue instant** card."

    Both halves of the phrase are tested by the picker, so the library holds one
    card that fails each half on its own. A colour the flow could not test would
    have left every instant offered — the card would still have reported
    supported, and the search would silently be Merchant Scroll's without its
    adjective.
    """
    game, p0, _p1 = _g2_duel()
    p0.library = [
        catalog_by_name["Lightning Bolt"],      # instant, wrong colour
        catalog_by_name["Ancestral Recall"],    # blue, and an instant
        catalog_by_name["Counterspell"],        # blue, and an instant
        catalog_by_name["Time Walk"],           # blue, wrong card type
    ]
    p0.hand = [set_pool("HML")["Merchant Scroll"]]

    game.cast_from_hand(0, "Merchant Scroll")
    game._settle()

    assert game.pending_search_library is not None
    assert not game.confirm_search_library(0, 0)   # Lightning Bolt: not blue
    assert not game.confirm_search_library(0, 3)   # Time Walk: not an instant
    assert game.confirm_search_library(0, 1)       # Ancestral Recall
    assert [card.name for card in p0.hand] == ["Ancestral Recall"]


def test_merchant_scroll_reveals_what_it_finds(set_pool, catalog_by_name):
    """"…**reveal that card**…" (CR 701.20a): the find is shown to every player,
    which is the printed word this production used to refuse outright — it read
    "reveal it" and "reveal them" and nothing else."""
    game, p0, _p1 = _g2_duel()
    p0.library = [catalog_by_name["Counterspell"]]
    p0.hand = [set_pool("HML")["Merchant Scroll"]]

    game.cast_from_hand(0, "Merchant Scroll")
    game._settle()
    game.confirm_search_library(0, 0)

    assert any(
        "Counterspell" in event["cards"] for event in game.reveal_events
    ), game.reveal_events


def test_prophecy_reads_the_opponents_library_and_not_its_own(set_pool, catalog_by_name):
    """"Reveal the top card of **target opponent's** library. If it's a land,
    you gain 1 life."

    The two decks are stacked to disagree: the caster's top card is a land and
    the opponent's is not. A reveal that opened the caster's own library — which
    is what the handler did before whose-library became payload — would gain the
    life, so the assertion that no life was gained is the one that can only pass
    for the right reason.
    """
    game, p0, p1 = _g2_duel()
    p0.library = [catalog_by_name["Forest"], catalog_by_name["Forest"]]
    p1.library = [catalog_by_name["Counterspell"], catalog_by_name["Forest"]]
    p0.hand = [set_pool("HML")["Prophecy"]]
    before = p0.life

    game.cast_from_hand(0, "Prophecy", target_player_index=1)
    game._settle()

    assert p0.life == before
    assert any(
        "Counterspell" in event["cards"] for event in game.reveal_events
    ), game.reveal_events


def test_prophecy_gains_a_life_for_a_land_on_top(set_pool, catalog_by_name):
    """The other branch of the same conditional, off the same record: the
    revealed card is read out of the resolution's scratchpad rather than off the
    library, which is what lets the shuffle behind it be a real shuffle."""
    game, p0, p1 = _g2_duel()
    p1.library = [catalog_by_name["Forest"], catalog_by_name["Island"]]
    p0.hand = [set_pool("HML")["Prophecy"]]
    before = p0.life

    game.cast_from_hand(0, "Prophecy", target_player_index=1)
    game._settle()

    assert p0.life == before + 1


def test_prophecy_leaves_the_revealed_card_in_the_library(set_pool, catalog_by_name):
    """CR 701.20a — revealing shows a card and **moves it nowhere**. The library
    keeps every card it had, and "Then that player shuffles" is the sentence
    that makes the reveal cost the opponent something rather than nothing."""
    game, p0, p1 = _g2_duel()
    p1.library = [catalog_by_name["Forest"], catalog_by_name["Island"]]
    p0.hand = [set_pool("HML")["Prophecy"]]

    game.cast_from_hand(0, "Prophecy", target_player_index=1)
    game._settle()

    assert sorted(card.name for card in p1.library) == ["Forest", "Island"]


def test_prophecy_shuffles_the_opponents_library_and_not_the_casters(set_pool, catalog_by_name):
    """"**Then that player shuffles.**" — the player the first sentence named,
    not the one resolving the spell.

    Which library was **not** touched is what a test can prove exactly: the
    caster's deck is left in a distinguishable order and has to still be in it.
    A shuffle is random, so the one that did happen is read off the log — the
    honest observable for an event whose whole content is that an order stopped
    being knowable.
    """
    game, p0, p1 = _g2_duel()
    p0.library = [
        catalog_by_name[name] for name in ("Forest", "Island", "Swamp", "Mountain")
    ]
    p1.library = [catalog_by_name["Island"], catalog_by_name["Forest"]]
    p0.hand = [set_pool("HML")["Prophecy"]]

    game.cast_from_hand(0, "Prophecy", target_player_index=1)
    game._settle()

    assert [card.name for card in p0.library] == [
        "Forest", "Island", "Swamp", "Mountain"
    ]
    assert sorted(card.name for card in p1.library) == ["Forest", "Island"]
    assert "B shuffled their library" in game.log
    assert "A shuffled their library" not in game.log


def test_prophecy_offers_an_opponent_to_target(set_pool):
    """The picker's half of the same fix. ``derive_cast_spec`` answered None
    while the first line did not parse — no instruction carried a target
    description — and None is what the client tests to decide whether to ask for
    a target at all, so the app could not aim the card it was happily
    reporting supported."""
    card = set_pool("HML")["Prophecy"]

    assert _g2_cast_spec(card, _g2_compile(card)) == {
        "kind": "player", "opponents_only": True
    }


def test_a_two_colour_search_phrase_means_either_colour(catalog_by_name):
    """Merchant Scroll names one colour, but the field it rides can hold two —
    and "a green **or** white creature" is what two mean everywhere else in this
    engine (``ObjectFilter.to_payload`` emits that case as ``any_colors``).

    Written against an invented sentence rather than a card, because the pool
    prints no two-colour search: the bug this pins is a *disagreement between
    readers*, and it would have shipped silently in the narrow direction — a
    "white or blue" tutor finding only gold cards, with nothing red and no card
    to notice it on.
    """
    from engine.grammar import compile_line as _g2_compile_line
    from engine.search_filters import search_matches as _g2_matches

    result = _g2_compile_line(
        "Search your library for a white or blue card, put that card into "
        "your hand, then shuffle.",
        card_name="Test",
    )
    assert result.usable, result.lowering_error
    data = result.instructions[0].payload

    assert _g2_matches(catalog_by_name["Swords to Plowshares"], data)  # white
    assert _g2_matches(catalog_by_name["Counterspell"], data)          # blue
    assert not _g2_matches(catalog_by_name["Lightning Bolt"], data)    # red
    assert not _g2_matches(catalog_by_name["Black Lotus"], data)       # colourless
