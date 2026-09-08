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


# --- W2G3: whole-hand and whole-library effects ---
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle

from tests.helpers import _mk_card, _mk_creature_card, resolve_stack


def _g3w2s_table(*, interactive=()):
    """Two seats, mana enforcement off, and whichever of them answers prompts.

    ``_g3w2s_`` prefixed and ending on ``return game, game.players[0],
    game.players[1]`` — SET_PLAYBOOK.md's note about a union splicing one
    helper's body onto another's signature.
    """
    game = Game(players=[PlayerState(name="W2G3S-A"), PlayerState(name="W2G3S-B")])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, game.players[0], game.players[1]


def _g3w2s_land(name):
    return _mk_card(name, "Basic Land - Forest", "")


def _g3w2s_cast(game, seat, card, **kwargs):
    """Cast *card* from *seat*'s hand and drain what it puts on the stack."""
    game.players[seat].hand.append(card)
    result = game.cast_from_hand(seat, card.name, **kwargs)
    resolve_stack(game)
    return result


def test_w2g3_windfall_draws_the_greatest_number_anyone_discarded(set_pool):
    """"Each player discards their hand, then draws cards equal to the greatest
    number of cards a player discarded this way."

    The number is a maximum **across seats**, measured inside this resolution —
    not the caster's own discard and not the last seat's. The two hands are
    deliberately different sizes, which is the only arrangement that tells the
    three readings apart.
    """
    card = set_pool("USG")["Windfall"]
    assert compile_card_oracle(card).supported

    game, alice, bob = _g3w2s_table()
    alice.hand = [_g3w2s_land("A1")]
    bob.hand = [_g3w2s_land("B1"), _g3w2s_land("B2"), _g3w2s_land("B3")]
    alice.library = [_g3w2s_land(f"AL{i}") for i in range(8)]
    bob.library = [_g3w2s_land(f"BL{i}") for i in range(8)]

    _g3w2s_cast(game, 0, card)

    assert len(alice.hand) == 3, "the greatest number any player discarded"
    assert len(bob.hand) == 3
    assert len(alice.graveyard) == 2, "her one card, and the Windfall itself"
    assert len(bob.graveyard) == 3


def test_w2g3_windfall_discards_through_the_discard_seam(set_pool):
    """CR 701.9a: emptying a hand this way *is* a discard, so anything watching
    discards sees it.

    The name-keyed hook this production took over put the cards into the
    graveyard directly and announced nothing, so a Megrim on the table watched
    the biggest discard in the format go past — a card that plays, compiles and
    is wrong. The watcher here is the assertion.
    """
    game, alice, bob = _g3w2s_table()
    watcher = Permanent(card=_mk_card(
        name="W2G3 Watcher", mana_cost="{2}{B}", type_line="Enchantment",
        oracle_text=(
            "Whenever an opponent discards a card, this enchantment deals 2 "
            "damage to that player."
        ),
    ))
    game._put_permanent_onto_battlefield(0, watcher, None)
    game._sync_control()
    bob.hand = [_g3w2s_land("B1"), _g3w2s_land("B2")]
    alice.library = [_g3w2s_land(f"AL{i}") for i in range(8)]
    bob.library = [_g3w2s_land(f"BL{i}") for i in range(8)]

    _g3w2s_cast(game, 0, set_pool("USG")["Windfall"])

    assert bob.life == 16, "two discards, 2 damage each"


def test_w2g3_time_spiral_shuffles_everything_in_and_draws_seven(set_pool):
    """"Exile Time Spiral. Each player shuffles their hand and graveyard into
    their library, then draws seven cards. You untap up to six lands."

    Three sentences and three assertions. The draw is a **printed** seven rather
    than "that many": a player whose hand and graveyard were both empty still
    draws a full grip, which is what tells this apart from Winds of Change.
    """
    card = set_pool("USG")["Time Spiral"]
    assert compile_card_oracle(card).supported

    game, alice, bob = _g3w2s_table()
    alice.hand = [_g3w2s_land("A1")]
    alice.graveyard = [_g3w2s_land("AG1")]
    alice.library = [_g3w2s_land(f"AL{i}") for i in range(10)]
    bob.library = [_g3w2s_land(f"BL{i}") for i in range(10)]
    lands = [
        Permanent(card=_g3w2s_land(f"tapped{i}")) for i in range(6)
    ]
    for land in lands:
        game._put_permanent_onto_battlefield(0, land, None)
        land.tapped = True
    game._sync_control()

    _g3w2s_cast(game, 0, card)
    # "You untap **up to** six lands" is a ceiling the caster answers under, so
    # it is a prompt owed with an empty stack — which `resolve_stack` leaves
    # alone on purpose.
    game.auto_resolve_pending_choices()

    assert len(alice.hand) == 7, "seven, whatever went in"
    assert len(bob.hand) == 7, "and every player, not only the caster"
    assert alice.graveyard == [], "the graveyard went into the library"
    assert not any(land.tapped for land in lands), "up to six lands untapped"
    assert any(c.name == "Time Spiral" for c in alice.exile), "and it exiled itself"


def test_w2g3_time_spiral_draws_seven_from_an_empty_hand_and_graveyard(set_pool):
    """The half a "that many" reading would lose: nothing moved, and seven cards
    are still drawn."""
    game, alice, bob = _g3w2s_table()
    alice.library = [_g3w2s_land(f"AL{i}") for i in range(10)]
    bob.library = [_g3w2s_land(f"BL{i}") for i in range(10)]

    _g3w2s_cast(game, 0, set_pool("USG")["Time Spiral"])

    assert len(alice.hand) == 7


def test_w2g3_persecute_discards_only_the_chosen_colour(set_pool):
    """"Choose a color. Target player reveals their hand and discards all cards
    of that color."

    The colour is chosen as the spell resolves (CR 608.2d) by the sentence in
    front, and read back by the sentence behind it. A narrowing dropped on the
    way would empty the whole hand, which is a strictly larger effect than the
    card prints — so the hand deliberately holds two colours.
    """
    card = set_pool("USG")["Persecute"]
    assert compile_card_oracle(card).supported

    game, alice, bob = _g3w2s_table()
    black = _mk_card(name="W2G3 Fear", mana_cost="{B}", type_line="Instant",
                     oracle_text="", colors=("B",))
    white = _mk_card(name="W2G3 Ward", mana_cost="{W}", type_line="Instant",
                     oracle_text="", colors=("W",))
    bob.hand = [black, white, _g3w2s_land("B-Land")]

    _g3w2s_cast(game, 0, card, target_player_index=1, new_color="B")

    assert [c.name for c in bob.hand] == ["W2G3 Ward", "B-Land"]
    assert [c.name for c in bob.graveyard] == ["W2G3 Fear"]


def test_w2g3_persecute_with_no_colour_named_discards_nothing(set_pool):
    """An unanswered CR 608.2d choice is not "no narrowing": read that way the
    spell would empty the hand. Doing nothing is the honest failure, and it is
    what the missing record is checked for."""
    game, alice, bob = _g3w2s_table()
    black = _mk_card(name="W2G3 Fear", mana_cost="{B}", type_line="Instant",
                     oracle_text="", colors=("B",))
    bob.hand = [black]

    _g3w2s_cast(game, 0, set_pool("USG")["Persecute"], target_player_index=1)

    assert [c.name for c in bob.hand] == ["W2G3 Fear"]


def test_w2g3_reprocess_draws_one_card_per_permanent_sacrificed(set_pool):
    """"Sacrifice any number of artifacts, creatures, and/or lands. Draw a card
    for each permanent sacrificed this way."

    "Any number" prints no count, so the number the draw reads exists nowhere
    until the seat has answered — and by then the permanents are cards in a
    graveyard. The count therefore comes off what the sacrifice recorded.
    """
    card = set_pool("USG")["Reprocess"]
    assert compile_card_oracle(card).supported

    game, alice, bob = _g3w2s_table(interactive=(0,))
    for i in range(3):
        game._put_permanent_onto_battlefield(
            0, Permanent(card=_mk_creature_card(f"W2G3 Ox{i}", 1, 1)), None
        )
    game._sync_control()
    alice.library = [_g3w2s_land(f"AL{i}") for i in range(6)]

    alice.hand.append(card)
    game.cast_from_hand(0, card.name)
    offer = game.pending_sacrifice_state()
    assert offer["up_to"] is True and offer["count"] == 3, (
        '"any number" is a ceiling the whole board answers, not an amount'
    )
    assert game.confirm_sacrifice(0, [0, 1, 2])
    resolve_stack(game)

    assert list(game.controlled_by(0)) == [], "all three went"
    assert len(alice.hand) == 3, "one card per permanent sacrificed this way"


def test_w2g3_reprocess_declined_by_a_headless_seat_draws_nothing(set_pool):
    """The stated ``up_to`` policy: a seat merely *offered* the chance to give
    permanents up gives up none, so the count behind it is zero.

    Wood Elemental already documents that policy; this is the same word on the
    same prompt, and the assertion is that the draw follows the sacrifice rather
    than a printed number the card never names.
    """
    game, alice, bob = _g3w2s_table()
    game._put_permanent_onto_battlefield(
        0, Permanent(card=_mk_creature_card("W2G3 Ox", 1, 1)), None
    )
    game._sync_control()
    alice.library = [_g3w2s_land(f"AL{i}") for i in range(6)]

    _g3w2s_cast(game, 0, set_pool("USG")["Reprocess"])

    assert len(list(game.controlled_by(0))) == 1, "nothing was given up"
    assert alice.hand == [], "and nothing was drawn"


def test_w2g3_reprocess_over_an_empty_board_draws_nothing(set_pool):
    """"Any number" includes none, and a count off a record nothing wrote is
    zero rather than a printed number the card never names."""
    game, alice, bob = _g3w2s_table(interactive=(0,))
    alice.library = [_g3w2s_land(f"AL{i}") for i in range(6)]

    _g3w2s_cast(game, 0, set_pool("USG")["Reprocess"])

    assert game.pending_sacrifice_state() is None, "nothing to offer, nothing asked"
    assert alice.hand == []


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
