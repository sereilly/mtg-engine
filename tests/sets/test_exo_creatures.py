"""Exodus creatures.

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

Cards come from `set_pool("EXO")` / `set_cards("EXO")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G4: counters, computed characteristics and the Licids ----------------

from engine import Game as _G4Game, PlayerState as _G4Player
from engine.models import Permanent as _G4Perm
from engine.named_counters import counters_on as _g4_counters_on
from engine.named_counters import remove_counters as _g4_remove_counters
from engine.oracle import compile_card_oracle as _g4_compile

from tests.helpers import resolve_stack as _g4_resolve


def _g4_perm(card, *, tapped=False):
    """A permanent already on the battlefield, past its summoning sickness."""
    permanent = _G4Perm(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    permanent.tapped = tapped
    return permanent


def _g4_duel(mine=(), theirs=(), hand=(), pool=None):
    """A two-seat board with P0 to act, costs off, layers already computed."""
    p0 = _G4Player(name="G4-P0", battlefield=list(mine), life=20,
                   hand=list(hand), mana_pool=dict(pool or {}))
    p1 = _G4Player(name="G4-P1", battlefield=list(theirs), life=20)
    game = _G4Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.priority_player_index = 0
    game._sync_control()
    game._refresh_dynamic_creatures()
    # A closing line no other group's helper writes, so a mechanical union
    # cannot splice this body onto another signature (W1G4).
    return game, p0, p1


def test_w1g4_spike_cannibal_eats_every_creatures_plus_one_counters(set_pool):
    """"When this creature enters, move all +1/+1 counters from all creatures
    onto it."

    The counter move read from the far end: the *destination* is the ability's
    own source and the sources are a described set. CR 122.5 makes it one
    action, which is why it is one instruction rather than a counter sweep
    composed with a placement -- the number placed is exactly the number the
    board gave up, and an empty board places nothing.

    Every creature, not only the caster's: the printed phrase names no
    controller, so an opponent's counters travel too.
    """
    exo, lea = set_pool("EXO"), set_pool("LEA")
    mine, theirs = _g4_perm(lea["Grizzly Bears"]), _g4_perm(lea["Grizzly Bears"])
    game, _p0, _p1 = _g4_duel(mine=[mine], theirs=[theirs],
                              hand=[exo["Spike Cannibal"]])
    game.place_pt_counters(mine, "+1/+1", 2)
    game.place_pt_counters(theirs, "+1/+1", 3)
    game._refresh_dynamic_creatures()

    assert game.cast_from_hand(0, "Spike Cannibal").supported
    _g4_resolve(game)
    game.check_state_based_actions()

    cannibal = next(p for p in game.controlled_by(0)
                    if p.card.name == "Spike Cannibal")
    # One counter from its own entry line plus the five it took.
    assert _g4_counters_on(cannibal, "+1/+1") == 6
    assert (cannibal.effective_power, cannibal.effective_toughness) == (6, 6)
    assert _g4_counters_on(mine, "+1/+1") == 0
    assert _g4_counters_on(theirs, "+1/+1") == 0


def test_w1g4_spike_cannibal_on_an_empty_board_keeps_its_own_counter(set_pool):
    """A permanent is skipped as a source of its own move (CR 122.5 -- moving a
    counter onto the object it came off does nothing).

    Taking the Spike's entry counter off and putting the same number back would
    read the same on the board and would write the "a counter was removed"
    record along the way, which nothing about this card asks for.
    """
    exo = set_pool("EXO")
    game, _p0, _p1 = _g4_duel(hand=[exo["Spike Cannibal"]])

    assert game.cast_from_hand(0, "Spike Cannibal").supported
    _g4_resolve(game)
    game.check_state_based_actions()

    cannibal = next(p for p in game.controlled_by(0)
                    if p.card.name == "Spike Cannibal")
    assert _g4_counters_on(cannibal, "+1/+1") == 1
    assert any("no +1/+1 counters to move" in line for line in game.log)


def test_w1g4_spike_rogue_pays_a_counter_off_another_creature(set_pool):
    """"{2}, Remove a +1/+1 counter from **a creature you control**: Put a
    +1/+1 counter on this creature."

    The counter-removal cost aimed somewhere other than the source -- the
    mirror of Wandering Mage's placing cost, on the same `cost_permanent_ids`
    channel. The named creature pays; the Spike grows.
    """
    exo, lea = set_pool("EXO"), set_pool("LEA")
    bear = _g4_perm(lea["Grizzly Bears"])
    game, _p0, _p1 = _g4_duel(mine=[bear], hand=[exo["Spike Rogue"]],
                              pool={"generic": 9, "G": 4})
    game.place_pt_counters(bear, "+1/+1", 2)
    game._refresh_dynamic_creatures()
    assert game.cast_from_hand(0, "Spike Rogue").supported
    _g4_resolve(game)
    game.check_state_based_actions()
    rogue = next(p for p in game.controlled_by(0) if p.card.name == "Spike Rogue")
    assert _g4_counters_on(rogue, "+1/+1") == 2

    result = game.activate_permanent_ability(
        0, "Spike Rogue", ability_index=1,
        cost_permanent_ids=[bear.permanent_id],
    )
    assert result.supported, result.details
    _g4_resolve(game)

    assert _g4_counters_on(bear, "+1/+1") == 1
    assert _g4_counters_on(rogue, "+1/+1") == 3


def test_w1g4_spike_rogue_refuses_when_nothing_holds_a_counter(set_pool):
    """CR 601.2h: an activation whose cost cannot be paid is no activation.

    The candidate list is not "a creature you control" but "a creature you
    control **with a +1/+1 counter on it**" -- a list that ignored the counters
    would take the mana and then find nothing to remove.
    """
    exo = set_pool("EXO")
    game, _p0, _p1 = _g4_duel(hand=[exo["Spike Rogue"]],
                              pool={"generic": 9, "G": 4})
    assert game.cast_from_hand(0, "Spike Rogue").supported
    _g4_resolve(game)
    game.check_state_based_actions()
    rogue = next(p for p in game.controlled_by(0) if p.card.name == "Spike Rogue")
    _g4_remove_counters(rogue, "+1/+1", _g4_counters_on(rogue, "+1/+1"))
    game._refresh_dynamic_creatures()

    result = game.activate_permanent_ability(0, "Spike Rogue", ability_index=1)

    assert not result.supported
    assert "+1/+1 counter to remove" in result.details


def test_w1g4_spike_rogues_own_counter_cost_stays_a_self_cost(set_pool):
    """The first ability still reads its own source.

    The chosen-subject reading is tried **before** the plain one in
    ``engine/oracle.py``, because the plain regex's "from " matches anything at
    all. This is the other side of that order: "from this creature" opens with
    no article, so the chosen reader cannot claim it and Scavenging Ghoul's
    shape is untouched.
    """
    rogue = set_pool("EXO")["Spike Rogue"]
    program = _g4_compile(rogue)

    self_cost, chosen_cost = (a.cost for a in program.activated_abilities)
    assert self_cost.remove_counter == "+1/+1"
    assert self_cost.remove_counter_filter is None
    assert chosen_cost.remove_counter_filter == {"type_filter": "creature"}


def test_w1g4_skyshroud_war_beast_counts_the_chosen_players_nonbasics(set_pool):
    """"...power and toughness are each equal to the number of **nonbasic**
    lands the chosen player controls." (CR 604.3.)

    Pallimud's row with a fifth capture: a supertype the counted object must
    *not* have (CR 205.4a). Asked through ``has_supertype``, so it is CR 613
    layer 4 rather than the printed line -- a land made basic stops counting.
    """
    exo, lea = set_pool("EXO"), set_pool("LEA")
    theirs = [_g4_perm(lea["Badlands"]), _g4_perm(lea["Tundra"]),
              _g4_perm(lea["Forest"])]
    game, _p0, _p1 = _g4_duel(theirs=theirs, hand=[exo["Skyshroud War Beast"]])

    assert game.cast_from_hand(
        0, "Skyshroud War Beast", target_player_index=1
    ).supported
    _g4_resolve(game)
    game.check_state_based_actions()

    beast = next(p for p in game.controlled_by(0)
                 if p.card.name == "Skyshroud War Beast")
    assert beast.metadata.get("chosen_player_index") == 1
    # Two nonbasics; the Forest is a basic land and is not counted.
    assert (beast.effective_power, beast.effective_toughness) == (2, 2)
