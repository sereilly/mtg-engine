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
