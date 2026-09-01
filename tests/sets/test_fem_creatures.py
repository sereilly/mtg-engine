"""Per-card tests for Fallen Empires' creatures.

See tests/sets/README.md for the convention: get cards through
``set_pool("FEM")`` / ``set_cards("FEM")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The wave that implemented FEM
split by grammar family rather than by printed type, so several groups land
tests in this one file. Each group appends a single delimited block:

    # --- G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.
"""

from __future__ import annotations


# --- G2: self-clocks, delayed self-sacrifice and card-flow order ---

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent


def _g2_game(*battlefield, library=None):
    """One seat with *battlefield* in play, costs off, everything able to act."""
    for permanent in battlefield:
        permanent.metadata["summoning_sickness_turn"] = -99
    player = PlayerState(
        name="P1", battlefield=list(battlefield), library=list(library or [])
    )
    game = Game(players=[player, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game._settle()
    return game, player


def _g2_settle(game):
    while game.stack:
        game.resolve_top_of_stack()
    game._settle()


def _g2_basic(name):
    """A basic land card, for a library a mill can eat."""
    return next(
        card for card in load_cards(manifest_set_path("LEA")) if card.name == name
    )


def _g2_activate(game, name, permanent):
    result = game.activate_permanent_ability(
        0, name, permanent_index=game.battlefield_index_of(permanent)
    )
    _g2_settle(game)
    return result


def _g2_tap_for_mana(game, name, permanent, times):
    for _ in range(times):
        result = _g2_activate(game, name, permanent)
        assert result.supported, result.details


def test_farrelite_priest_adds_white_and_clocks_itself_on_the_fourth_use(set_pool):
    """"{1}: Add {W}. If this ability has been activated four or more times this
    turn, sacrifice this creature at the beginning of the next end step."

    The tally is the ability's own activation count, kept by
    ``engine/activation_restrictions.py`` -- the same ledger CR 602.5's printed
    caps are refused against. The fourth use crosses the threshold and creates
    the delayed sacrifice (CR 603.7); the end step carries it out.
    """
    priest = Permanent(card=set_pool("FEM")["Farrelite Priest"])
    game, player = _g2_game(priest)

    _g2_tap_for_mana(game, "Farrelite Priest", priest, 4)

    assert player.mana_pool["W"] == 4
    assert priest.metadata.get("sacrifice_at_next_end_step") is True

    game.resolve_end_step(0)
    assert [p.card.name for p in player.battlefield] == []
    assert [c.name for c in player.graveyard] == ["Farrelite Priest"]


def test_farrelite_priest_survives_three_uses(set_pool):
    """Three is not four. The threshold is read off the printed number, so a
    tally compared with the wrong operator would kill the creature a use early
    -- the direction a drawback must never err in."""
    priest = Permanent(card=set_pool("FEM")["Farrelite Priest"])
    game, player = _g2_game(priest)

    _g2_tap_for_mana(game, "Farrelite Priest", priest, 3)

    assert priest.metadata.get("sacrifice_at_next_end_step") is None
    game.resolve_end_step(0)
    assert [p.card.name for p in player.battlefield] == ["Farrelite Priest"]


def test_the_priests_clock_counts_this_turn_and_not_a_running_total(set_pool):
    """"...**this turn**." Three uses on one turn and one on the next is four
    activations and no sacrifice: the ledger is stamped with the turn it
    belongs to, and a running total would clock the creature on a turn it was
    barely used."""
    priest = Permanent(card=set_pool("FEM")["Farrelite Priest"])
    game, player = _g2_game(priest)

    _g2_tap_for_mana(game, "Farrelite Priest", priest, 3)
    game.turn += 1
    _g2_tap_for_mana(game, "Farrelite Priest", priest, 1)

    assert priest.metadata.get("sacrifice_at_next_end_step") is None
    game.resolve_end_step(0)
    assert [p.card.name for p in player.battlefield] == ["Farrelite Priest"]


def test_initiates_of_the_ebon_hand_is_the_same_sentence_in_black(set_pool):
    """The Priest's line with one mana symbol changed. One production reads
    both, so this is the test that the production is a production and not a
    card: same tally, same threshold, same delayed sacrifice, {B} for {W}."""
    initiates = Permanent(card=set_pool("FEM")["Initiates of the Ebon Hand"])
    game, player = _g2_game(initiates)

    _g2_tap_for_mana(game, "Initiates of the Ebon Hand", initiates, 4)

    assert player.mana_pool["B"] == 4
    assert player.mana_pool["W"] == 0
    game.resolve_end_step(0)
    assert [c.name for c in player.graveyard] == ["Initiates of the Ebon Hand"]


def test_homarid_warrior_hides_taps_itself_and_stays_down_a_turn(set_pool):
    """"{U}: This creature gains shroud until end of turn and doesn't untap
    during your next untap step. Tap it."

    All three halves of one sentence. "Tap it" names the creature the sentence
    opened with, so the Warrior taps *itself* rather than choosing anything.
    """
    warrior = Permanent(card=set_pool("FEM")["Homarid Warrior"])
    game, _player = _g2_game(warrior)

    result = _g2_activate(game, "Homarid Warrior", warrior)

    assert result.supported, result.details
    assert warrior.has_keyword("shroud")
    assert warrior.tapped is True

    game.resolve_untap_step(0)
    assert warrior.tapped is True
    game.resolve_untap_step(0)
    assert warrior.tapped is False


def test_the_warriors_skipped_untap_is_your_step_and_not_the_next_one(set_pool):
    """"...during **your** next untap step" (CR 701.43a's exert wording: the
    next untap step of the player who did it), not "its controller's next untap
    step".

    The two readings pick out different steps, and an opponent's untap step is
    what tells them apart: it must not spend the restriction, because it is not
    the step the card named.
    """
    warrior = Permanent(card=set_pool("FEM")["Homarid Warrior"])
    game, _player = _g2_game(warrior)

    _g2_activate(game, "Homarid Warrior", warrior)

    game.resolve_untap_step(1)
    assert warrior.tapped is True
    assert warrior.metadata.get("skip_next_untap") == 1

    game.resolve_untap_step(0)
    assert warrior.metadata.get("skip_next_untap") is None


def test_deep_spawn_prints_the_warriors_sentence_with_the_noun_written_out(set_pool):
    """"...Tap **this creature**." against the Warrior's "Tap **it**." -- the
    same sentence, so the same production and the same three effects."""
    spawn = Permanent(card=set_pool("FEM")["Deep Spawn"])
    game, _player = _g2_game(spawn)

    result = _g2_activate(game, "Deep Spawn", spawn)

    assert result.supported, result.details
    assert spawn.has_keyword("shroud")
    assert spawn.has_keyword("trample")
    assert spawn.tapped is True
    game.resolve_untap_step(0)
    assert spawn.tapped is True


def test_deep_spawn_mills_two_to_survive_its_upkeep(set_pool):
    """"At the beginning of your upkeep, sacrifice this creature unless you mill
    two cards." An offer with a penalty, priced in cards off the library
    (CR 701.13a) rather than in mana -- so taking it costs two cards and keeps
    the creature."""
    spawn = Permanent(card=set_pool("FEM")["Deep Spawn"])
    game, player = _g2_game(spawn, library=[_g2_basic("Mountain")] * 5)

    game.resolve_upkeep(0)
    assert [c.kind for c in game.pending_choices] == ["optional_pay"]
    assert game.confirm_optional_pay(0, accept=True) is True
    game._settle()

    assert len(player.library) == 3
    assert [c.name for c in player.graveyard] == ["Mountain", "Mountain"]
    assert [p.card.name for p in player.battlefield] == ["Deep Spawn"]


def test_deep_spawn_declining_the_mill_sacrifices_it(set_pool):
    """The other arm of the same offer. A price nobody is charged is the effect
    happening for free, so the decline has to land."""
    spawn = Permanent(card=set_pool("FEM")["Deep Spawn"])
    game, player = _g2_game(spawn, library=[_g2_basic("Mountain")] * 5)

    game.resolve_upkeep(0)
    assert game.confirm_optional_pay(0, accept=False) is True
    game._settle()

    assert len(player.library) == 5
    assert [p.card.name for p in player.battlefield] == []
    assert [c.name for c in player.graveyard] == ["Deep Spawn"]
# --- G1: counters as named state ---
#
# The unifying machinery of this group is a **named counter as readable
# state**: putting them on, taking them off, counting them, and conditioning a
# static effect or a trigger on how many there are. The enchantment half of the
# same round (Tidal Influence, Tourach's Gate, Merseine) is in
# ``test_fem_enchantments.py``.

from engine import Game
from engine.models import Permanent, PlayerState
from engine.named_counters import counters_on
from tests.helpers import _nosick as _g1_nosick


def _g1_board(set_pool, *names, life=20, hand=(), opponents=()):
    """A two-seat game with *names* on seat 0's battlefield, in order.

    FEM cards by default; a ``(code, name)`` pair reaches another set's pool,
    which is how the fodder and the targets below are basics and vanilla bears
    rather than more of this set.
    """
    def _card(entry):
        return set_pool(entry[0])[entry[1]] if isinstance(entry, tuple) else set_pool("FEM")[entry]

    p0 = PlayerState(name="P0", life=life, hand=[_card(entry) for entry in hand])
    p1 = PlayerState(name="P1", life=life)
    game = Game(players=[p0, p1])
    game.enforce_mana_costs = False
    made = []
    for entry in names:
        perm = Permanent(card=_card(entry))
        game._put_permanent_onto_battlefield(0, perm, None)
        made.append(perm)
    for entry in opponents:
        perm = Permanent(card=_card(entry))
        game._put_permanent_onto_battlefield(1, perm, None)
        made.append(perm)
    game._settle()
    game.active_player_index = 0
    return (game, p0, p1, *made)


def _g1_upkeep(game, seat=0):
    game.active_player_index = seat
    game.resolve_upkeep(seat)
    game._settle()


# -- Homarid ---------------------------------------------------------------


def test_homarid_rides_its_tide_counters_up_and_back_to_zero(set_pool):
    """The whole printed cycle in one game, because the card *is* the cycle.

    It enters with one tide counter and gets -1/-1 while there is exactly one;
    a second counter is neither one nor three, so it is a plain 2/2; the third
    turns the penalty into a bonus; the fourth trips the CR 603.8 state trigger
    that empties it, and the tide starts again.
    """
    game, _p0, _p1, homarid = _g1_board(set_pool, "Homarid")

    assert counters_on(homarid, "tide") == 1, "it enters with one"
    assert (homarid.effective_power, homarid.effective_toughness) == (1, 1)

    _g1_upkeep(game)
    assert counters_on(homarid, "tide") == 2
    assert (homarid.effective_power, homarid.effective_toughness) == (2, 2), (
        "two is neither exactly one nor exactly three"
    )

    _g1_upkeep(game)
    assert counters_on(homarid, "tide") == 3
    assert (homarid.effective_power, homarid.effective_toughness) == (3, 3)

    _g1_upkeep(game)
    assert counters_on(homarid, "tide") == 0, "four or more empties it (CR 603.8)"
    assert (homarid.effective_power, homarid.effective_toughness) == (2, 2)

    _g1_upkeep(game)
    assert counters_on(homarid, "tide") == 1, "and the tide comes back in"
    assert (homarid.effective_power, homarid.effective_toughness) == (1, 1)


# -- Icatian Moneychanger --------------------------------------------------


def test_icatian_moneychanger_charges_three_life_on_arrival(set_pool):
    """"When this creature enters, it deals 3 damage to you" — and it enters
    with three credit counters, which is the loan it is charging for."""
    _game, p0, _p1, changer = _g1_board(set_pool, "Icatian Moneychanger")

    assert p0.life == 17
    assert counters_on(changer, "credit") == 3


def test_the_moneychanger_pays_back_one_life_per_credit_counter(set_pool):
    """"Sacrifice this creature: You gain 1 life for each credit counter on
    this creature."

    The counter count is read back off the permanent the *cost* has already
    eaten (CR 608.2h), so the life gained is the number that was there at
    activation and not zero.
    """
    game, p0, _p1, changer = _g1_board(set_pool, "Icatian Moneychanger")
    _g1_upkeep(game)
    assert counters_on(changer, "credit") == 4, "the upkeep adds one"

    before = p0.life
    result = game.activate_permanent_ability(0, "Icatian Moneychanger", ability_index=0)
    game._settle()

    assert result.supported, result.details
    assert p0.life == before + 4, "one life per credit counter, not one life"
    assert not game.is_on_battlefield(changer), "the cost sacrificed it"


def test_the_moneychanger_cannot_cash_out_outside_your_upkeep(set_pool):
    """"Activate only during your upkeep." An unenforced restriction is not a
    dead ability — it is one that works more often than the card allows."""
    game, p0, _p1, _changer = _g1_board(set_pool, "Icatian Moneychanger")
    game.current_turn_phase, game.current_step = "precombat_main", "main"

    result = game.activate_permanent_ability(0, "Icatian Moneychanger", ability_index=0)

    assert not result.supported
    assert "only during your upkeep" in result.details
    assert p0.life == 17, "nothing was gained and nothing was paid"


# -- Ebon Praetor ----------------------------------------------------------


def test_ebon_praetor_shrinks_itself_every_upkeep(set_pool):
    """"At the beginning of your upkeep, put a -2/-2 counter on this creature.\""""
    game, _p0, _p1, praetor = _g1_board(set_pool, "Ebon Praetor")
    assert (praetor.effective_power, praetor.effective_toughness) == (5, 5)

    _g1_upkeep(game)

    assert counters_on(praetor, "-2/-2") == 1
    assert (praetor.effective_power, praetor.effective_toughness) == (3, 3)


def test_feeding_the_praetor_a_thrull_also_grows_it(set_pool):
    """"If the sacrificed creature was a Thrull, put a +1/+0 counter on this
    creature."

    The effect reads back an object the *cost* consumed: by resolution the
    Thrull is a card in a graveyard, so the answer is the record the payment
    path wrote (CR 608.2h) rather than any read of the board.
    """
    game, _p0, _p1, praetor, thrull = _g1_board(
        set_pool, "Ebon Praetor", "Basal Thrull",
    )
    _g1_upkeep(game)

    result = game.activate_permanent_ability(
        0, "Ebon Praetor", ability_index=0,
        cost_permanent_ids=[game.permanent_id_of(thrull)],
    )
    game._settle()

    assert result.supported, result.details
    assert counters_on(praetor, "-2/-2") == 0, "the removal happened"
    assert counters_on(praetor, "+1/+0") == 1, "and the Thrull clause fired"
    assert (praetor.effective_power, praetor.effective_toughness) == (6, 5)


def test_feeding_the_praetor_anything_else_only_removes(set_pool):
    """The same activation with a non-Thrull: the removal still happens and the
    conditional half does not. A condition that answered True either way would
    be a card strictly better than the one printed."""
    game, _p0, _p1, praetor, bear = _g1_board(
        set_pool, "Ebon Praetor", ("LEA", "Grizzly Bears"),
    )
    _g1_upkeep(game)

    result = game.activate_permanent_ability(
        0, "Ebon Praetor", ability_index=0,
        cost_permanent_ids=[game.permanent_id_of(bear)],
    )
    game._settle()

    assert result.supported, result.details
    assert counters_on(praetor, "-2/-2") == 0
    assert counters_on(praetor, "+1/+0") == 0, "Grizzly Bears is not a Thrull"
    assert (praetor.effective_power, praetor.effective_toughness) == (5, 5)


def test_the_praetor_may_only_be_fed_once_each_turn(set_pool):
    """"Activate only during your upkeep **and only once each turn**." Two
    restrictions in one printed sentence, and both have to hold."""
    game, _p0, _p1, praetor, thrull, other = _g1_board(
        set_pool, "Ebon Praetor", "Basal Thrull", "Basal Thrull",
    )
    _g1_upkeep(game)
    game.activate_permanent_ability(
        0, "Ebon Praetor", ability_index=0,
        cost_permanent_ids=[game.permanent_id_of(thrull)],
    )
    game._settle()

    again = game.activate_permanent_ability(
        0, "Ebon Praetor", ability_index=0,
        cost_permanent_ids=[game.permanent_id_of(other)],
    )

    assert not again.supported
    assert "only once each turn" in again.details
    assert game.is_on_battlefield(other), "the second Thrull was not eaten"
    assert counters_on(praetor, "+1/+0") == 1


# -- Dwarven Armorer -------------------------------------------------------


def _g1_armorer_board(set_pool, interactive=()):
    game, _p0, _p1, smith, bear = _g1_board(
        set_pool, "Dwarven Armorer", ("LEA", "Grizzly Bears"),
        hand=[("LEA", "Mountain"), ("LEA", "Mountain")],
    )
    game.interactive_seats = set(interactive)
    _g1_nosick(smith)
    return game, smith, bear


def test_the_armorer_defaults_to_the_first_printed_counter(set_pool):
    """"Put a +0/+1 counter **or** a +1/+0 counter on target creature."

    A choice between two kinds is one placement, not two, and a seat that
    answers nothing takes the first printed alternative — the stated policy for
    every mode in this engine.
    """
    game, _smith, bear = _g1_armorer_board(set_pool)

    result = game.activate_permanent_ability(
        0, "Dwarven Armorer", ability_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    game._settle()

    assert result.supported, result.details
    assert counters_on(bear, "+0/+1") == 1
    assert counters_on(bear, "+1/+0") == 0, "one of the two, never both"
    assert (bear.effective_power, bear.effective_toughness) == (2, 3)


def test_the_armorer_offers_the_other_counter_to_a_player(set_pool):
    """An interactive seat is asked, and its answer decides which kind lands —
    on the creature the *activation* named, not on whichever the prompt's own
    default picker would have found first."""
    game, smith, bear = _g1_armorer_board(set_pool, interactive={0})

    game.activate_permanent_ability(
        0, "Dwarven Armorer", ability_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    (choice,) = game.pending_choices
    assert choice.kind == "mode_choice"
    assert choice.data["labels"] == ["a +0/+1 counter", "a +1/+0 counter"]

    assert game.resolve_pending_choice("mode_choice", 0, mode_index=1)
    game._settle()

    assert counters_on(bear, "+1/+0") == 1
    assert (bear.effective_power, bear.effective_toughness) == (3, 2)
    assert counters_on(smith, "+1/+0") == 0, "the counter went to the target"


def test_the_armorer_charges_its_discard(set_pool):
    """{R}, {T}, **Discard a card** — the cost is collected, and the source
    taps. A cost nobody charges is an ability that works for free."""
    game, smith, _bear = _g1_armorer_board(set_pool)
    hand_before = len(game.players[0].hand)

    game.activate_permanent_ability(
        0, "Dwarven Armorer", ability_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    game._settle()

    assert len(game.players[0].hand) == hand_before - 1
    assert smith.tapped


# --- G4: costs from the board and the graveyard ---

from engine import Game, PlayerState
from engine.models import Permanent


def _g4_nosick(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _g4_game(battlefield, *, hand=(), their_battlefield=(), enforce=False):
    p1 = PlayerState(name="P1", battlefield=list(battlefield), hand=list(hand))
    p2 = PlayerState(name="P2", battlefield=list(their_battlefield))
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = enforce
    game.start_turn(0)
    return game, p1, p2


# Derelor — a cost tax printed as a coloured pip


def test_derelor_taxes_your_black_spells_a_black_pip(set_pool):
    """"Black spells you cast cost {B} more to cast."

    The tax is a **coloured** pip, not a generic one, which is the whole
    difference: {B} may not be paid with a Forest. So a caster holding exactly
    the printed cost cannot cast, and one holding a second black mana can.
    """
    pool = set_pool("FEM")
    lea = set_pool("LEA")
    ritual = lea["Dark Ritual"]

    def cast_with(**mana):
        game, p1, _p2 = _g4_game(
            [Permanent(card=pool["Derelor"])], hand=[ritual], enforce=True
        )
        p1.mana_pool.update(mana)
        return game.cast_from_hand(0, "Dark Ritual")

    assert not cast_with(B=1).supported, "one {B} no longer pays {B} plus {B}"
    assert not cast_with(B=1, G=1).supported, "a Forest cannot pay a {B} tax"
    assert cast_with(B=2).supported


def test_derelor_taxes_only_its_own_controllers_black_spells(set_pool):
    """"…**you cast**" is CR 109.5's seat: the opponent's black spell is
    untaxed, and so is a nonblack spell of the controller's own.
    """
    pool = set_pool("FEM")
    lea = set_pool("LEA")

    game, p1, _p2 = _g4_game(
        [], their_battlefield=[Permanent(card=pool["Derelor"])], enforce=True
    )
    p1.hand = [lea["Dark Ritual"]]
    p1.mana_pool["B"] = 1
    assert game.cast_from_hand(0, "Dark Ritual").supported, (
        "the taxing permanent is the opponent's, and it taxes only its own "
        "controller's spells"
    )

    game, p1, _p2 = _g4_game(
        [Permanent(card=pool["Derelor"])], hand=[lea["Giant Growth"]], enforce=True
    )
    p1.mana_pool["G"] = 1
    assert game.cast_from_hand(0, "Giant Growth").supported, "green is not black"


# Thelonite Druid — an activated, one-turn land animation scoped to "you control"


def _g4_druid_board(set_pool):
    pool = set_pool("FEM")
    lea = set_pool("LEA")
    druid = _g4_nosick(Permanent(card=pool["Thelonite Druid"]))
    forest = Permanent(card=lea["Forest"])
    mountain = Permanent(card=lea["Mountain"])
    fodder = _g4_nosick(Permanent(card=lea["Grizzly Bears"]))
    theirs = Permanent(card=lea["Forest"])
    game, p1, p2 = _g4_game(
        [druid, forest, mountain, fodder], their_battlefield=[theirs]
    )
    return game, p1, p2, druid, forest, mountain, theirs, fodder


def test_thelonite_druid_animates_only_the_forests_you_control(set_pool):
    """"{1}{G}, {T}, Sacrifice a creature: **Forests you control** become 2/3
    creatures until end of turn. They're still lands."

    Three narrowings in one sentence and each one is load-bearing: the Mountain
    is not a Forest, the opponent's Forest is not one *you control*, and the
    animated lands are still lands (CR 613 layer 4 adds a type, it does not
    replace one).
    """
    (game, p1, _p2, druid, forest, mountain, theirs, fodder) = _g4_druid_board(
        set_pool
    )

    result = game.activate_permanent_ability(
        0, "Thelonite Druid", permanent_index=0,
        cost_permanent_ids=[fodder.permanent_id],
    )
    game._settle()

    assert result.supported, result.details
    assert (
        forest.is_creature, forest.effective_power, forest.effective_toughness
    ) == (True, 2, 3)
    assert forest.has_type("land"), "they are still lands"
    assert not mountain.is_creature
    assert not theirs.is_creature
    assert druid.tapped
    assert [card.name for card in p1.graveyard] == ["Grizzly Bears"]


def test_thelonite_druids_forests_stop_being_creatures_at_cleanup(set_pool):
    """"…**until end of turn**". The record is what makes them creatures, and
    the cleanup sweep is what ends it — a duration nothing lifts is a permanent
    animation.
    """
    (game, _p1, _p2, _druid, forest, _mtn, _theirs, fodder) = _g4_druid_board(
        set_pool
    )
    game.activate_permanent_ability(
        0, "Thelonite Druid", permanent_index=0,
        cost_permanent_ids=[fodder.permanent_id],
    )
    game._settle()
    assert forest.is_creature

    game.resolve_cleanup_step(0)

    assert not forest.is_creature
    assert (forest.effective_power, forest.effective_toughness) == (0, 0)


def test_thelonite_druid_pays_with_itself_when_it_is_the_only_creature(set_pool):
    """The sacrifice is a real cost, and "a creature" includes the source
    (CR 601.2b names no exclusion) — so a lone Druid eats itself, and the
    ability still resolves from the graveyard (CR 603.6).

    That is also the cheapest proof the cost is charged at all: something leaves
    the battlefield every time this is activated.
    """
    pool = set_pool("FEM")
    lea = set_pool("LEA")
    druid = _g4_nosick(Permanent(card=pool["Thelonite Druid"]))
    forest = Permanent(card=lea["Forest"])
    game, p1, _p2 = _g4_game([druid, forest])

    result = game.activate_permanent_ability(0, "Thelonite Druid", permanent_index=0)
    game._settle()

    assert result.supported, result.details
    assert [card.name for card in p1.graveyard] == ["Thelonite Druid"]
    assert [perm.card.name for perm in p1.battlefield] == ["Forest"]
    assert forest.is_creature


def test_thelonite_druid_spends_nothing_when_it_cannot_pay_the_tap(set_pool):
    """"{1}{G}, **{T}**, Sacrifice a creature: …". CR 302.6 makes a
    summoning-sick creature unable to pay a tap symbol, and CR 601.2h then makes
    the whole cost unpayable — so the ability is not activated and the creature
    that would have paid the sacrifice is still there.

    The order matters as much as the refusal: a cost half-charged is a creature
    eaten for nothing.
    """
    pool = set_pool("FEM")
    lea = set_pool("LEA")
    druid = Permanent(card=pool["Thelonite Druid"])
    fodder = _g4_nosick(Permanent(card=lea["Grizzly Bears"]))
    forest = Permanent(card=lea["Forest"])
    game, p1, _p2 = _g4_game([druid, fodder, forest])
    druid.metadata["summoning_sickness_turn"] = game.turn  # it arrived this turn

    result = game.activate_permanent_ability(
        0, "Thelonite Druid", permanent_index=0,
        cost_permanent_ids=[fodder.permanent_id],
    )
    game._settle()

    assert not result.supported
    assert p1.graveyard == []
    assert not druid.tapped
    assert not forest.is_creature


# Vodalian War Machine — a record of what was tapped to pay for its abilities


def _g4_war_machine(set_pool, merfolk=2, extra=()):
    pool = set_pool("FEM")
    machine = _g4_nosick(Permanent(card=pool["Vodalian War Machine"]))
    school = [
        _g4_nosick(Permanent(card=pool["River Merfolk"])) for _ in range(merfolk)
    ]
    others = [_g4_nosick(Permanent(card=pool[name])) for name in extra]
    game, p1, p2 = _g4_game([machine, *school, *others])
    return game, p1, p2, machine, school, others


def test_vodalian_war_machine_taps_a_merfolk_to_pump(set_pool):
    """"**Tap an untapped Merfolk you control**: This creature gets +2/+1 until
    end of turn."

    The cost taps *another* permanent, and it was charged as nothing at all: the
    count reader knew "a" and not "an", so the ability pumped for free and could
    be pumped forever.
    """
    game, _p1, _p2, machine, school, _others = _g4_war_machine(set_pool)

    result = game.activate_permanent_ability(
        0, "Vodalian War Machine", permanent_index=0, ability_index=1,
        cost_permanent_ids=[school[0].permanent_id],
    )
    game._settle()

    assert result.supported, result.details
    assert (machine.effective_power, machine.effective_toughness) == (2, 5)
    assert school[0].tapped
    assert not school[1].tapped


def test_vodalian_war_machine_cannot_pump_with_no_untapped_merfolk(set_pool):
    """The control on the cost: an ability whose payment does not exist is
    refused (CR 602.2b), not activated for nothing.
    """
    game, _p1, _p2, machine, school, _others = _g4_war_machine(set_pool, merfolk=1)
    game.become_tapped(school[0])

    result = game.activate_permanent_ability(
        0, "Vodalian War Machine", permanent_index=0, ability_index=1,
    )

    assert not result.supported
    assert (machine.effective_power, machine.effective_toughness) == (0, 4)


def test_vodalian_war_machine_may_attack_after_tapping_a_merfolk(set_pool):
    """Defender, and the ability that lifts it for a turn — checked from both
    sides, because an unenforced defender would make the second half prove
    nothing.
    """
    game, _p1, _p2, _machine, school, _others = _g4_war_machine(set_pool, merfolk=1)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    allowed, _why = game.declare_attackers(0, [0])
    assert not allowed, "Defender: it cannot attack on its own"

    game, _p1, _p2, _machine, school, _others = _g4_war_machine(set_pool, merfolk=1)
    assert game.activate_permanent_ability(
        0, "Vodalian War Machine", permanent_index=0, ability_index=0,
        cost_permanent_ids=[school[0].permanent_id],
    ).supported
    game._settle()
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()

    assert game.declare_attackers(0, [0])[0]


def test_vodalian_war_machine_destroys_only_the_merfolk_that_paid(set_pool):
    """"When this creature dies, destroy all Merfolk **tapped this turn to pay
    for its abilities**."

    Narrower than "tapped this turn", and nothing about a tapped permanent says
    which it is — so the payment path writes the record and the sweep reads it.
    A Merfolk tapped for anything else survives.
    """
    game, p1, _p2, machine, school, others = _g4_war_machine(
        set_pool, merfolk=2, extra=["Vodalian Soldiers"],
    )
    bystander = others[0]

    game.activate_permanent_ability(
        0, "Vodalian War Machine", permanent_index=0, ability_index=1,
        cost_permanent_ids=[school[0].permanent_id],
    )
    game._settle()
    game.become_tapped(bystander)  # tapped, but not to pay for anything

    game.sacrifice_permanent(machine)
    game._settle()

    assert [perm.card.name for perm in p1.battlefield] == [
        "River Merfolk", "Vodalian Soldiers",
    ], "the untapped Merfolk and the bystander both survive"
    assert [card.name for card in p1.graveyard] == [
        "Vodalian War Machine", "River Merfolk",
    ]


def test_vodalian_war_machines_record_does_not_outlive_the_turn(set_pool):
    """"…tapped **this turn**". The record is swept at cleanup, so a Merfolk
    that paid on an earlier turn is not destroyed — without the sweep the phrase
    would mean "ever".
    """
    game, p1, _p2, machine, school, _others = _g4_war_machine(set_pool, merfolk=1)

    game.activate_permanent_ability(
        0, "Vodalian War Machine", permanent_index=0, ability_index=1,
        cost_permanent_ids=[school[0].permanent_id],
    )
    game._settle()
    game.resolve_cleanup_step(0)

    game.sacrifice_permanent(machine)
    game._settle()

    assert [perm.card.name for perm in p1.battlefield] == ["River Merfolk"]
