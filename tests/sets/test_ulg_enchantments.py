"""Urza's Legacy enchantments.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("ULG")` / `set_cards("ULG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G2: the animated body — "becomes a N/N <type> creature with …" ---
from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _g2_shipped_pool():
    """Every shipped card by name, for the spells an opponent casts at these.

    The Opal cycle's trigger is *somebody else's* spell, so a test of it needs a
    card `set_pool("ULG")` cannot give. Read through the manifest rather than a
    spelled-out filename, and memoized on the function so the whole block reads
    the JSON once.
    """
    cached = getattr(_g2_shipped_pool, "_g2_cache", None)
    if cached is None:
        cached = {}
        for path in manifest_set_paths():
            for card in load_cards(path):
                cached.setdefault(card.name, card)
        _g2_shipped_pool._g2_cache = cached
    return cached


def _g2_enchantment_board(set_pool, name):
    """*name* on Alice's battlefield in a two-seat game, Bob free to cast at it."""
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    permanent = Permanent(card=set_pool("ULG")[name])
    game._put_permanent_onto_battlefield(0, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return game, permanent


def _g2_opponent_casts(game, name):
    game.players[1].hand.append(_g2_shipped_pool()[name])
    game.cast_from_hand(1, name)
    resolve_stack(game)
    return game


def test_opal_champion_animates_with_first_strike(set_pool):
    """"When an opponent casts a creature spell, if this permanent is an
    enchantment, it becomes a 3/3 Knight creature **with first strike**."

    The whole card, and the keyword is the half that was missing: the same
    sentence with "flying" compiled, because the creature body read its keyword
    list one *token* at a time against a registry whose entries are ability
    names. "first" is not one, so the loop stopped there with nothing consumed
    and the line refused — Opal Gargoyle worked and its own cycle-mate did not.
    """
    game, champion = _g2_enchantment_board(set_pool, "Opal Champion")
    assert champion.has_type("enchantment") and not champion.is_creature

    _g2_opponent_casts(game, "Grizzly Bears")

    assert champion.is_creature
    assert champion.has_type("knight")
    assert (champion.effective_power, champion.effective_toughness) == (3, 3)
    assert champion.has_keyword("first strike")


def test_opal_champion_replaces_its_types(set_pool):
    """CR 205.1a: the sentence prints none of the retention clauses, so the
    enchantment stops being an enchantment — which is what makes its own
    intervening "if this permanent is an enchantment" false the second time an
    opponent casts a creature spell."""
    game, champion = _g2_enchantment_board(set_pool, "Opal Champion")

    _g2_opponent_casts(game, "Grizzly Bears")
    assert not champion.has_type("enchantment")

    _g2_opponent_casts(game, "Hill Giant")
    assert (champion.effective_power, champion.effective_toughness) == (3, 3)


def test_opal_champion_ignores_a_noncreature_spell(set_pool):
    """The narrowing on its own. A card that woke to any spell would pass the
    test above, so the printed word "creature" is asserted separately."""
    game, champion = _g2_enchantment_board(set_pool, "Opal Champion")

    _g2_opponent_casts(game, "Lightning Bolt")

    assert not champion.is_creature
    assert champion.has_type("enchantment")


def test_opal_avenger_wakes_when_its_controller_is_low(set_pool):
    """"**When you have 10 or less life**, if this permanent is an enchantment,
    it becomes a 3/5 Soldier creature."

    CR 603.8's state trigger read off a life total — a condition with no fire
    site, since life falls to damage, a cost, a loss effect or an opponent's
    drain. It is therefore swept for beside the counter, characteristic and
    hand states, in `mixins/game_ending.py`, and the threshold is payload.
    """
    game, avenger = _g2_enchantment_board(set_pool, "Opal Avenger")

    game.check_state_based_actions()
    resolve_stack(game)
    assert not avenger.is_creature, "20 life is not 10 or less"

    game.players[0].life = 11
    game.check_state_based_actions()
    resolve_stack(game)
    assert not avenger.is_creature, "11 is one more than the printed threshold"

    game.players[0].life = 10
    game.check_state_based_actions()
    resolve_stack(game)

    assert avenger.is_creature
    assert avenger.has_type("soldier")
    assert not avenger.has_type("enchantment")
    assert (avenger.effective_power, avenger.effective_toughness) == (3, 5)


def test_opal_avenger_reads_its_own_controllers_life(set_pool):
    """"**You**" is the source's controller and not every seat, which is the
    whole difference from Veiled Crocodile's "a player". An Avenger that woke to
    an opponent's life total would animate at exactly the wrong moment."""
    game, avenger = _g2_enchantment_board(set_pool, "Opal Avenger")

    game.players[1].life = 3
    game.check_state_based_actions()
    resolve_stack(game)

    assert not avenger.is_creature


def test_opal_avengers_threshold_is_payload(set_pool):
    """The number is delimited by the trigger table and read by the shared
    number reader, so a card printing another one needs no code. Asserted on the
    compiled condition rather than by inventing a card: what would break is the
    payload, and the payload is what the sweep tests."""
    program = compile_card_oracle(set_pool("ULG")["Opal Avenger"])

    (trigger,) = program.triggered_abilities

    assert trigger.condition.kind == "controller_life_at_most"
    assert trigger.condition.payload["life_count"] == 10
