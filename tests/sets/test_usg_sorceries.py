"""Urza's Saga sorceries.

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

Cards come from `set_pool("USG")` / `set_cards("USG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: cycling (CR 702.29) ---
import pytest

from engine import Game, PlayerState
from engine.activation_zones import HAND
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from tests.helpers import resolve_stack

#: The three sorceries with cycling. All three reported supported before the
#: rewrite, with the keyword unclaimed — see the instants file for why that is
#: the interesting half.
_G1_CYCLING_SORCERIES = ("Lay Waste", "Hush", "Rejuvenate")


def _g1_sorcery_game(card, *, library=4):
    """Seat 0 holds *card* over a library of copies of it. Named for this block."""
    player = PlayerState(name="G1-S", hand=[card], library=[card] * library)
    return Game(players=[player, PlayerState(name="G1-T")]), player


@pytest.mark.parametrize("name", _G1_CYCLING_SORCERIES)
def test_w1g1_a_cycling_sorcery_is_discarded_for_a_card(set_pool, name):
    """Rejuvenate is the one to read: cycled, it gains no life. A rewrite that
    let the spell's own line resolve would be invisible on the other two."""
    card = set_pool("USG")[name]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    assert [a.source_line for a in usable_activated_abilities(program, zone=HAND)] == [
        "{2}, Discard this card: Draw a card."
    ]

    game, player = _g1_sorcery_game(card)
    game.enforce_mana_costs = False
    life_before = player.life

    assert game.activate_from_hand(0, name).supported
    resolve_stack(game)

    assert [c.name for c in player.graveyard] == [name]
    assert len(player.library) == 3
    assert player.life == life_before


# --- W2G4: ownership, and a whole board held down for one step ---
import pytest

from engine import Game, PlayerState
from engine.control import change_control
from engine.models import Permanent

from tests.helpers import resolve_stack as _g4e_resolve


def _g4e_board(*, mine=(), theirs=(), hand0=(), life=20):
    """Two seats, mana costs off, seat 0 active. Returns ``(game, s0, s1)`` and
    ends on that tuple so no union can splice another helper onto it."""
    g4e_seat0 = PlayerState(
        name="G4-S1", battlefield=[Permanent(card=c) for c in mine],
        hand=list(hand0), life=life,
    )
    g4e_seat1 = PlayerState(
        name="G4-S2", battlefield=[Permanent(card=c) for c in theirs], life=life,
    )
    g4e_game = Game(players=[g4e_seat0, g4e_seat1])
    g4e_game.enforce_mana_costs = False
    g4e_game.active_player_index = 0
    g4e_game._sync_control()
    return g4e_game, g4e_seat0, g4e_seat1


def _g4e_creature(name, power=2, toughness=2):
    from tests.helpers import _mk_creature_card

    return _mk_creature_card(name, power, toughness)


def test_w2g4_path_of_peace_heals_the_owner_not_the_controller(set_pool):
    """CR 108.3 and CR 109.5 are two questions, and they differ for every
    permanent anybody has ever stolen. Read out of the controller record this
    card heals the thief — which is who destroyed it."""
    pool = set_pool("USG")
    game, mine, theirs = _g4e_board(
        theirs=[_g4e_creature("G4E Stolen")], hand0=[pool["Path of Peace"]],
    )
    stolen = theirs.battlefield[0]
    # Seat 0 steals it, then destroys its own stolen creature.
    change_control(stolen, 0, source="G4E theft")
    game._sync_control()
    assert game.controller_index_of(stolen) == 0
    assert game.owner_index_of(stolen) == 1

    assert game.cast_from_hand(
        0, "Path of Peace", target_player_index=0,
        target_permanent_index=0, target_permanent_ids=[stolen.permanent_id],
    ).supported
    _g4e_resolve(game)

    assert not game.is_on_battlefield(stolen)
    assert (mine.life, theirs.life) == (20, 24)


def test_w2g4_its_owner_refuses_with_no_step_that_chose_an_object(set_pool):
    """The possessive names the object an earlier step of the same effect acted
    on. With no such step it names nobody, and defaulting to "target" would heal
    whichever seat a targetless resolution happens to carry."""
    from engine.grammar import compile_line

    assert compile_line("Destroy target creature. Its owner gains 4 life.").usable
    assert not compile_line("Its owner gains 4 life.").usable
    # The possessive is still read as a *zone* owner everywhere it was.
    assert compile_line("Return target creature to its owner's hand.").usable


def test_w2g4_exhaustion_holds_both_types_on_one_seat_only(set_pool):
    """"Creatures and lands **target opponent** controls" is a seat the spell
    chose (CR 115.4), which no read of a permanent can supply. Refused rather
    than supplied the sweep matched nothing and the spell resolved having held
    nothing down; dropped, it would hold the caster's board too."""
    pool = set_pool("USG")
    game, mine, theirs = _g4e_board(
        mine=[_g4e_creature("G4E Mine")],
        theirs=[_g4e_creature("G4E Theirs"), set_pool("USG")["Forest"]],
        hand0=[pool["Exhaustion"]],
    )
    for permanent in (*mine.battlefield, *theirs.battlefield):
        permanent.tapped = True

    assert game.cast_from_hand(0, "Exhaustion", target_player_index=1).supported
    _g4e_resolve(game)

    assert theirs.battlefield[0].metadata.get("skip_next_untap") == 1
    assert theirs.battlefield[1].metadata.get("skip_next_untap") == 1
    assert mine.battlefield[0].metadata.get("skip_next_untap") is None

    game.active_player_index = 1
    game.resolve_untap_step(1)
    assert all(perm.tapped for perm in theirs.battlefield)
    game.resolve_untap_step(1)
    assert not any(perm.tapped for perm in theirs.battlefield)


def test_w2g4_the_elided_possessive_names_the_same_untap_step(set_pool):
    """"During **their next** untap step" and "during **their controller's**
    next untap step" are one window: an untap step belongs to a player (CR 502),
    and the only player "their" can name for a set of permanents is the one who
    controls them. It is not read as "your", which picks a different step the
    moment a permanent changes hands."""
    from engine.grammar import compile_line

    elided = compile_line(
        "Creatures and lands target opponent controls don't untap during their "
        "next untap step."
    )
    spelled = compile_line(
        "Creatures and lands target opponent controls don't untap during their "
        "controller's next untap step."
    )
    assert elided.usable and spelled.usable
    assert [(i.kind, i.payload) for i in elided.instructions] == [
        (i.kind, i.payload) for i in spelled.instructions
    ]
    seated = compile_line(
        "This creature doesn't untap during your next untap step."
    )
    assert seated.usable
    assert seated.instructions[0].payload.get("whose_untap_step") == "controller"
