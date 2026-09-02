"""Per-card tests for Homelands' instants.

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


# --- W2G2: library search, reveal and tuck ---

from engine import Game as _G2Game, PlayerState as _G2PlayerState
from engine.models import Permanent as _G2Permanent
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


def test_memory_lapse_puts_the_countered_spell_on_top_of_its_library(
    set_pool, catalog_by_name
):
    """"Counter target spell. If that spell is countered this way, put it on
    top of its owner's library **instead of** into that player's graveyard."

    Both halves are asserted, because the failure this replaces is silent: a
    counter whose destination clause was dropped bins the card, which is
    exactly what an ordinary Counterspell does and reads as nothing going wrong.
    """
    game, p0, p1 = _g2_duel()
    p0.hand = [set_pool("HML")["Memory Lapse"]]
    p1.hand = [catalog_by_name["Lightning Bolt"]]
    p1.library = [catalog_by_name["Forest"]]

    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    assert game.cast_from_hand(0, "Memory Lapse", target_stack_index=0).supported
    game.resolve_stack()

    assert [card.name for card in p1.library] == ["Lightning Bolt", "Forest"]
    assert [card.name for card in p1.graveyard] == []


def test_memory_lapse_stops_the_spell_resolving(set_pool, catalog_by_name):
    """CR 701.5a is still a counter — the redirect changes where the card goes
    and not whether the spell did anything. Asserted on a life total, because a
    Bolt that resolved *and* got tucked would pass the destination test above."""
    game, p0, p1 = _g2_duel()
    p0.hand = [set_pool("HML")["Memory Lapse"]]
    p1.hand = [catalog_by_name["Lightning Bolt"]]
    before = p0.life

    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    assert game.cast_from_hand(0, "Memory Lapse", target_stack_index=0).supported
    game.resolve_stack()

    assert p0.life == before


def test_jinx_asks_for_the_land_type_before_changing_anything(
    set_pool, catalog_by_name
):
    """"Target land becomes **the basic land type of your choice** until end of
    turn." CR 609.3 puts the choice inside the resolution, so nothing is
    recorded until the seat answers — the same contract Phantasmal Terrain's
    prompt already had, reached from a spell that has no permanent."""
    game, p0, p1 = _g2_duel()
    forest = _G2Permanent(card=catalog_by_name["Forest"])
    p1.battlefield.append(forest)
    p0.hand = [set_pool("HML")["Jinx"]]

    game.cast_from_hand(0, "Jinx", target_player_index=1, target_permanent_index=0)
    game._settle()

    assert forest.changed_land_types == ()
    assert game.pending_land_type_choice is not None
    assert game.pending_land_type_choice["player_index"] == 0

    assert game.confirm_land_type(0, "island") is True
    assert forest.changed_land_types == ("island",)
    assert forest.basic_land_types == ("island",)


def test_jinx_replaces_the_lands_types_rather_than_adding_one(
    set_pool, catalog_by_name
):
    """CR 305.7: a land that becomes a basic land type **loses** its old ones,
    which is what makes this a type change and not a grant. A Forest that was
    still a Forest would tap for two colours."""
    game, p0, p1 = _g2_duel()
    forest = _G2Permanent(card=catalog_by_name["Forest"])
    p1.battlefield.append(forest)
    p0.hand = [set_pool("HML")["Jinx"]]

    game.cast_from_hand(0, "Jinx", target_player_index=1, target_permanent_index=0)
    game._settle()
    game.confirm_land_type(0, "swamp")

    assert forest.basic_land_types == ("swamp",)


def test_jinx_wears_off_in_the_cleanup_step(set_pool, catalog_by_name):
    """"…**until end of turn**." The lowering admits that duration only because
    this sweep exists; without it the land would be a Swamp for the rest of the
    game, which is the direction a dropped duration always fails in.

    The record is keyed by a label rather than by a permanent, because Jinx is
    an instant and has none — so what the cleanup step drops is the label's
    prefix, and the reversion is that contribution leaving (CR 611.3b).
    """
    game, p0, p1 = _g2_duel()
    forest = _G2Permanent(card=catalog_by_name["Forest"])
    p1.battlefield.append(forest)
    p0.hand = [set_pool("HML")["Jinx"]]

    game.cast_from_hand(0, "Jinx", target_player_index=1, target_permanent_index=0)
    game._settle()
    game.confirm_land_type(0, "swamp")
    assert forest.basic_land_types == ("swamp",)

    game.resolve_cleanup_step(0)

    assert forest.changed_land_types == ()
    assert forest.basic_land_types == ("forest",)


def test_two_jinxes_do_not_overwrite_each_other(set_pool, catalog_by_name):
    """The reason the contribution is keyed by a per-resolution label. Both
    copies are one instant with no permanent behind it, so keying on the source
    would give them the same key — and the second would replace the first's
    contribution on a *different* land, reverting it."""
    game, p0, p1 = _g2_duel()
    pool = set_pool("HML")
    one = _G2Permanent(card=catalog_by_name["Forest"])
    two = _G2Permanent(card=catalog_by_name["Mountain"])
    p1.battlefield.extend([one, two])
    p0.hand = [pool["Jinx"], pool["Jinx"]]

    game.cast_from_hand(0, "Jinx", target_player_index=1, target_permanent_index=0)
    game._settle()
    game.confirm_land_type(0, "swamp")
    game.cast_from_hand(0, "Jinx", target_player_index=1, target_permanent_index=1)
    game._settle()
    game.confirm_land_type(0, "island")

    assert one.basic_land_types == ("swamp",)
    assert two.basic_land_types == ("island",)


def test_jinx_offers_a_land_to_target(set_pool):
    """The picker's half. ``derive_cast_spec`` answered None while the first
    line did not parse, and None is what the client tests to decide whether to
    ask for a target — so the app could not aim a card it reported supported."""
    card = set_pool("HML")["Jinx"]

    assert _g2_cast_spec(card, _g2_compile(card)) == {"kind": "land"}


# --- W2G1: sequenced spells ---

from engine import Game, PlayerState
from engine.models import Permanent
from engine.pt import add_pt_modifier


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


def _w2g1_visage(set_pool, attacker: Permanent, pump=None):
    """Seat 0 holds Broken Visage; seat 1 is attacking with *attacker*."""
    caster = PlayerState(
        name="P0", hand=[set_pool("HML")["Broken Visage"]],
        library=[set_pool("LEA")["Plains"]] * 5,
    )
    victim = PlayerState(
        name="P1", battlefield=[attacker],
        library=[set_pool("LEA")["Plains"]] * 5,
    )
    game = _w2g1_game(caster, victim)
    game.active_player_index = 1
    attacker.attacking = True
    game.combat_attackers = {0: 0}
    if pump is not None:
        add_pt_modifier(attacker, *pump)
    game._settle()
    return game, caster, victim


# --- Truce -----------------------------------------------------------------


def test_truce_lets_each_seat_take_its_own_number_of_cards(set_pool):
    """"Each player may draw up to two cards. For each card less than two a
    player draws this way, that player gains 2 life."

    The shortfall is per seat: the caster takes both cards and gains nothing,
    the other seat declines both and gains 4. One number for the whole
    resolution would have handed the same answer to both.
    """
    pool = set_pool("HML")
    lea = set_pool("LEA")
    caster = PlayerState(name="P0", hand=[pool["Truce"]], library=[lea["Plains"]] * 10)
    other = PlayerState(name="P1", library=[lea["Plains"]] * 10)
    game = _w2g1_game(caster, other, interactive=(0, 1))

    result = game.cast_from_hand(0, "Truce")
    while game.stack:
        game.resolve_top_of_stack()

    assert result.supported, result.details
    assert {(c.kind, c.player_index) for c in game.pending_choices} == {
        ("draw_up_to", 0), ("draw_up_to", 1),
    }
    # No life is gained until the last seat has answered: the sentence behind
    # the prompt is sized from every seat's number.
    assert (caster.life, other.life) == (20, 20)

    assert game.confirm_draw_up_to(0, 2)
    assert game.confirm_draw_up_to(1, 0)
    game._settle()

    assert (len(caster.hand), len(other.hand)) == (2, 0)
    assert (caster.life, other.life) == (20, 24)


def test_truce_pays_two_life_for_each_card_a_seat_leaves(set_pool):
    """One card short of two is 2 life, not 4 and not nothing -- the rate is per
    card and the base is the printed two."""
    pool = set_pool("HML")
    lea = set_pool("LEA")
    caster = PlayerState(name="P0", hand=[pool["Truce"]], library=[lea["Plains"]] * 10)
    other = PlayerState(name="P1", library=[lea["Plains"]] * 10)
    game = _w2g1_game(caster, other, interactive=(0, 1))

    game.cast_from_hand(0, "Truce")
    while game.stack:
        game.resolve_top_of_stack()
    assert game.confirm_draw_up_to(0, 1)
    assert game.confirm_draw_up_to(1, 1)
    game._settle()

    assert (len(caster.hand), len(other.hand)) == (1, 1)
    assert (caster.life, other.life) == (22, 22)


def test_truce_refuses_a_number_above_the_printed_ceiling(set_pool):
    """Out of range is a rejection, not a clamp: the prompt names the ceiling
    the card prints, and repairing an answer silently would let a client draw
    three cards off a card that offers two and be told it worked."""
    pool = set_pool("HML")
    lea = set_pool("LEA")
    caster = PlayerState(name="P0", hand=[pool["Truce"]], library=[lea["Plains"]] * 10)
    other = PlayerState(name="P1", library=[lea["Plains"]] * 10)
    game = _w2g1_game(caster, other, interactive=(0, 1))

    game.cast_from_hand(0, "Truce")
    while game.stack:
        game.resolve_top_of_stack()

    assert game.confirm_draw_up_to(0, 3) is False
    assert len(caster.hand) == 0
    assert len(game.pending_choices) == 2


def test_truce_headless_seats_take_the_maximum_their_library_allows(set_pool):
    """The stated policy for an "up to N" is the maximum -- a free draw is a gift
    -- capped by the library, because a default never picks the answer that
    loses the game (CR 704.5b). The short seat draws its one card and is paid
    for the one it could not take."""
    pool = set_pool("HML")
    lea = set_pool("LEA")
    caster = PlayerState(name="P0", hand=[pool["Truce"]], library=[lea["Plains"]] * 10)
    other = PlayerState(name="P1", library=[lea["Plains"]])
    game = _w2g1_game(caster, other)

    game.cast_from_hand(0, "Truce")
    _w2g1_resolve(game)

    assert (len(caster.hand), len(other.hand)) == (2, 1)
    assert (caster.life, other.life) == (20, 22)
    assert other.library == []


# --- Broken Visage ---------------------------------------------------------


def test_broken_visage_makes_a_token_the_size_of_the_creature_it_destroyed(set_pool):
    """"Create a black Spirit creature token. Its power is equal to that
    creature's power and its toughness is equal to that creature's toughness."

    The creature is already in a graveyard when the token is built, so the
    numbers are the ones the destroy froze (CR 608.2h).
    """
    attacker = Permanent(card=set_pool("LEA")["Hill Giant"])
    game, caster, victim = _w2g1_visage(set_pool, attacker)

    result = game.cast_from_hand(
        0, "Broken Visage", target_permanent_ids=[attacker.permanent_id],
    )
    _w2g1_resolve(game)

    assert result.supported, result.details
    assert [c.name for c in victim.graveyard] == ["Hill Giant"]
    token = caster.battlefield[0]
    assert token.card.name == "Spirit Token"
    assert (token.effective_power, token.effective_toughness) == (3, 3)
    assert set(token.effective_colors) == {"B"}


def test_broken_visage_copies_the_size_the_creature_had_not_the_printed_one(set_pool):
    """A pumped 5/7 Hill Giant makes a 5/7 Spirit. The frozen numbers are the
    *effective* ones, which is the whole reason they cannot be read off the
    card after the destroy."""
    attacker = Permanent(card=set_pool("LEA")["Hill Giant"])
    game, caster, victim = _w2g1_visage(set_pool, attacker, pump=(2, 4))

    game.cast_from_hand(
        0, "Broken Visage", target_permanent_ids=[attacker.permanent_id],
    )
    _w2g1_resolve(game)

    token = caster.battlefield[0]
    assert (token.effective_power, token.effective_toughness) == (5, 7)


def test_broken_visage_sacrifices_its_token_at_the_next_end_step(set_pool):
    """"Sacrifice the token at the beginning of the next end step."

    "The token" is the one this resolution made, not the creature the spell
    targeted -- which by then is a card in a graveyard, so a delay bound to the
    target would arm nothing and the sentence would silently do nothing.
    """
    attacker = Permanent(card=set_pool("LEA")["Hill Giant"])
    game, caster, victim = _w2g1_visage(set_pool, attacker)

    game.cast_from_hand(
        0, "Broken Visage", target_permanent_ids=[attacker.permanent_id],
    )
    _w2g1_resolve(game)
    assert [p.card.name for p in caster.battlefield] == ["Spirit Token"]

    game.resolve_end_step(1)
    _w2g1_resolve(game)

    # CR 111.7: a token that has left the battlefield ceases to exist, so the
    # graveyard holds the spell and nothing else.
    assert caster.battlefield == []
    assert [c.name for c in caster.graveyard] == ["Broken Visage"]

