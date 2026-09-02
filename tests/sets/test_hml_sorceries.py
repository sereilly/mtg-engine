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


# --- W2G1: sequenced spells ---

from engine import Game, PlayerState
from engine.models import Permanent


def _w2g1_game(*players: PlayerState, interactive=()) -> Game:
    game = Game(players=list(players))
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game._settle()
    return game


def _w2g1_resolve(game: Game) -> None:
    while game.stack:
        game.resolve_top_of_stack()
    game.auto_resolve_pending_choices()
    game._settle()


# --- Forget ----------------------------------------------------------------


def _w2g1_forget(set_pool, hand_size: int, library: int = 10):
    lea = set_pool("LEA")
    filler = [lea["Black Lotus"], lea["Mox Pearl"], lea["Mox Jet"], lea["Mox Ruby"]]
    caster = PlayerState(name="P0", hand=[set_pool("HML")["Forget"]])
    victim = PlayerState(
        name="P1", hand=filler[:hand_size], library=[lea["Plains"]] * library,
    )
    return _w2g1_game(caster, victim), caster, victim


def test_forget_replaces_the_two_cards_it_took(set_pool):
    """"Target player discards two cards, then draws as many cards as they
    discarded this way." Two out, two in, and the two in come off the library."""
    game, caster, victim = _w2g1_forget(set_pool, hand_size=4)

    result = game.cast_from_hand(0, "Forget", target_player_index=1)
    _w2g1_resolve(game)

    assert result.supported, result.details
    assert len(victim.hand) == 4
    assert len(victim.graveyard) == 2
    assert len(victim.library) == 8
    # The two that came back are the ones drawn, not the ones discarded.
    assert [c.name for c in victim.hand][-2:] == ["Plains", "Plains"]


def test_forget_draws_only_what_was_actually_discarded(set_pool):
    """The count is a back-reference, not the printed two. A player holding one
    card discards that one and draws one — reading the printed number would
    hand them a card they never paid for."""
    game, caster, victim = _w2g1_forget(set_pool, hand_size=1)

    game.cast_from_hand(0, "Forget", target_player_index=1)
    _w2g1_resolve(game)

    assert len(victim.hand) == 1
    assert len(victim.graveyard) == 1
    assert len(victim.library) == 9


def test_forget_over_an_empty_hand_draws_nothing(set_pool):
    """Nothing discarded is nothing drawn. A missing record reads as zero, which
    is what the sentence says when the step in front of it did nothing."""
    game, caster, victim = _w2g1_forget(set_pool, hand_size=0)

    game.cast_from_hand(0, "Forget", target_player_index=1)
    _w2g1_resolve(game)

    assert victim.hand == []
    assert victim.graveyard == []
    assert len(victim.library) == 10


def test_forget_waits_for_the_discard_before_it_draws(set_pool):
    """The discard is a prompt, so the draw is a later step of a suspended
    resolution: run eagerly it would draw against a hand the player has not
    emptied yet, and the count would be zero."""
    game, caster, victim = _w2g1_forget(set_pool, hand_size=4)
    game.interactive_seats = {1}

    game.cast_from_hand(0, "Forget", target_player_index=1)
    while game.stack:
        game.resolve_top_of_stack()

    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("discard", 1)]
    assert len(victim.library) == 10          # nothing drawn while the prompt stands

    assert game.confirm_discard(1, [0, 1])
    game._settle()

    assert len(victim.library) == 8
    # Removed in descending index order, so the graveyard reads back-to-front.
    assert sorted(c.name for c in victim.graveyard) == ["Black Lotus", "Mox Pearl"]


# --- Retribution -----------------------------------------------------------


def _w2g1_retribution(set_pool, interactive=()):
    lea = set_pool("LEA")
    big = Permanent(card=lea["Hill Giant"])          # 3/3
    small = Permanent(card=lea["Grizzly Bears"])     # 2/2
    caster = PlayerState(name="P0", hand=[set_pool("HML")["Retribution"]])
    victim = PlayerState(name="P1", battlefield=[big, small])
    game = _w2g1_game(caster, victim, interactive=interactive)
    return game, caster, victim, big, small


def test_retribution_lets_the_opponent_pick_which_of_the_two_dies(set_pool):
    """"That player chooses and sacrifices one of those creatures. Put a -1/-1
    counter on the other."

    The pick belongs to the opponent, not to the caster, and the counter lands
    on whichever creature they left.
    """
    game, caster, victim, big, small = _w2g1_retribution(set_pool, interactive=(1,))

    result = game.cast_from_hand(
        0, "Retribution",
        target_permanent_ids=[big.permanent_id, small.permanent_id],
    )
    while game.stack:
        game.resolve_top_of_stack()

    assert result.supported, result.details
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [
        ("permanent_choice", 1)
    ]

    assert game.confirm_permanent_choice(1, small.permanent_id)
    game._settle()

    assert [c.name for c in victim.graveyard] == ["Grizzly Bears"]
    assert [p.card.name for p in victim.battlefield] == ["Hill Giant"]
    assert (big.effective_power, big.effective_toughness) == (2, 2)


def test_retribution_offers_only_the_two_creatures_it_targeted(set_pool):
    """The sacrifice comes out of the set the first sentence chose, not off the
    opponent's board: a third creature they control is not an answer."""
    lea = set_pool("LEA")
    big = Permanent(card=lea["Hill Giant"])
    small = Permanent(card=lea["Grizzly Bears"])
    spare = Permanent(card=lea["Craw Wurm"])
    caster = PlayerState(name="P0", hand=[set_pool("HML")["Retribution"]])
    victim = PlayerState(name="P1", battlefield=[big, small, spare])
    game = _w2g1_game(caster, victim, interactive=(1,))

    game.cast_from_hand(
        0, "Retribution",
        target_permanent_ids=[big.permanent_id, small.permanent_id],
    )
    while game.stack:
        game.resolve_top_of_stack()

    choice = game.pending_choices[0]
    assert {p.permanent_id for p in game.live_permanent_choices(choice)} == {
        big.permanent_id, small.permanent_id,
    }
    assert game.confirm_permanent_choice(1, spare.permanent_id) is False


def test_retribution_headless_still_marks_the_creature_left_standing(set_pool):
    """A non-interactive opponent takes the stated default (the first live
    candidate) and the counter still lands on the *other* one — the record the
    pick leaves behind, not "whichever is still on the board"."""
    game, caster, victim, big, small = _w2g1_retribution(set_pool)

    game.cast_from_hand(
        0, "Retribution",
        target_permanent_ids=[big.permanent_id, small.permanent_id],
    )
    _w2g1_resolve(game)

    assert [c.name for c in victim.graveyard] == ["Hill Giant"]
    assert (small.effective_power, small.effective_toughness) == (1, 1)


# --- Winter Sky ------------------------------------------------------------
#
# A card that was already *supported* and already wrong. Its second half is the
# ordinary "each player draws a card", which the draw lowering had no reading
# for: every drawer that is not "you" became `draw_target_cards`, whose handler
# draws for one seat, so the caster never drew. Found while giving the draw
# family a per-seat record for Truce.


def test_winter_sky_draws_for_every_seat_not_just_the_opponent(set_pool):
    """"If you lose the flip, **each player** draws a card."

    Both seats, including the caster. One seat is not "each player" and is not
    half of the card either: the caster is the seat the printed text is most
    obviously about, and it was the one that never drew.
    """
    import random

    lea = set_pool("LEA")
    caster = PlayerState(
        name="P0", hand=[set_pool("HML")["Winter Sky"]],
        library=[lea["Plains"]] * 10,
    )
    other = PlayerState(name="P1", library=[lea["Plains"]] * 10)
    game = _w2g1_game(caster, other)

    # A seed on which the flip is lost, so the draw half is the one that runs.
    for seed in range(20):
        random.seed(seed)
        caster.hand = [set_pool("HML")["Winter Sky"]]
        caster.library = [lea["Plains"]] * 10
        other.library = [lea["Plains"]] * 10
        caster.life = other.life = 20
        game.cast_from_hand(0, "Winter Sky")
        _w2g1_resolve(game)
        if caster.life == 20:                    # the flip was lost
            break
    else:                                        # pragma: no cover - defensive
        raise AssertionError("no seed in range lost the flip")

    assert (len(caster.hand), len(other.hand)) == (1, 1)
    assert (len(caster.library), len(other.library)) == (9, 9)
