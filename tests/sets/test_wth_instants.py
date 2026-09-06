"""Weatherlight instants.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: cumulative upkeep beyond a mana cost ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("WTH")` / `set_cards("WTH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G1: the top of a graveyard as a cost ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


def _w1g1_card(name: str, type_line: str, colors: tuple = ()) -> CardDefinition:
    """A vanilla card to stack a graveyard with. The colour is what Spinning
    Darkness's cost scans for, so it is the one characteristic that varies."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=tuple(colors), color_identity=tuple(colors), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "2",
             "toughness": "2", "colors": list(colors)},
    )


def _w1g1_darkness(set_pool, graveyard):
    """Spinning Darkness in hand with *graveyard* behind it and a creature to
    aim at. The graveyard is bottom-first (CR 404.1: an arriving card goes on
    top, so the last element is the top card)."""
    victim = Permanent(card=_w1g1_card("Victim", "Creature — Bear"))
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("WTH")["Spinning Darkness"]],
                    graveyard=list(graveyard),
                    library=[_w1g1_card("Filler", "Artifact")] * 5),
        PlayerState(name="P2", battlefield=[victim],
                    library=[_w1g1_card("Filler", "Artifact")] * 5),
    ])
    game.start_turn(0)
    return game, victim


def test_spinning_darkness_is_cast_for_three_black_cards_and_no_mana(set_pool):
    """"You may exile the top three black cards of your graveyard rather than
    pay this spell's mana cost." (CR 118.9.)

    The mana is *never* paid — the game has no lands at all here — and the
    three cards come off the top of the pile, skipping the white card that
    happens to be above one of them. CR 118.9c leaves the printed {4}{B}{B}
    untouched; what is skipped is the payment.
    """
    game, victim = _w1g1_darkness(set_pool, [
        _w1g1_card("Black Deep", "Creature — Zombie", ("B",)),
        _w1g1_card("White Card", "Creature — Bear", ("W",)),
        _w1g1_card("Black Mid", "Creature — Zombie", ("B",)),
        _w1g1_card("Black Top", "Creature — Zombie", ("B",)),
    ])
    me = game.players[0]
    result = game.cast_from_hand(
        0, "Spinning Darkness", alternative_cost=True,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert sorted(card.name for card in me.exile) == [
        "Black Deep", "Black Mid", "Black Top"
    ]
    # The spell itself lands in the graveyard on resolution (CR 608.2m), so
    # the pile is read for what the *cost* left behind.
    assert [
        card.name for card in me.graveyard if card.name != "Spinning Darkness"
    ] == ["White Card"]
    if game.stack:
        game.resolve_top_of_stack()
    assert victim.damage_marked == 3
    assert me.life == 23


def test_spinning_darkness_refuses_a_pile_that_cannot_pay_in_full(set_pool):
    """CR 118.3: a cost is paid in full or not at all, and CR 601.2h then makes
    an unpayable alternative cost an *uncastable* spell — never one cast for
    nothing, which is what a partial charge would be once the mana payment has
    already been replaced."""
    game, _victim = _w1g1_darkness(set_pool, [
        _w1g1_card("Black One", "Creature — Zombie", ("B",)),
        _w1g1_card("Black Two", "Creature — Zombie", ("B",)),
    ])
    me = game.players[0]
    result = game.cast_from_hand(
        0, "Spinning Darkness", alternative_cost=True,
        target_player_index=1, target_permanent_index=0,
    )
    assert not result.supported
    assert len(me.graveyard) == 2, "the two black cards are still there"
    assert me.exile == []
    assert [card.name for card in me.hand] == ["Spinning Darkness"]


# --- W2G5: enforcement, entry replacement and the last statics ---

from engine import Game, PlayerState  # noqa: E402
from engine.models import Permanent  # noqa: E402
from engine.oracle import compile_card_oracle  # noqa: E402
from engine.targeting import derive_cast_spec  # noqa: E402
from tests.helpers import _mk_card, _nosick  # noqa: E402


def _w2g5_creature(name: str, type_line: str = "Creature - Bear"):
    return _nosick(Permanent(card=_mk_card(name, type_line)))


def test_boiling_blood_forces_the_chosen_creature_to_attack(set_pool):
    """"Target creature attacks this turn if able. Draw a card."

    The card compiled to its **second** line alone: the production that reads
    the requirement existed for Kookus' trailing "…and attacks this turn if
    able" and nothing had ever asked it at the head of a sentence, so the whole
    first line was dropped and Boiling Blood was a two-mana cantrip. CR 508.1a's
    requirement now rides the same ``must_attack_until_eot`` mark the declare
    step already reads.
    """
    blood = set_pool("WTH")["Boiling Blood"]
    lazy = _w2g5_creature("Lazy Bear")
    idle = _w2g5_creature("Idle Ogre", "Creature - Ogre")
    game = Game(players=[
        # A library, because the second line of this card draws: an empty one
        # makes its controller lose at the next state-based check and the
        # combat this test is about never happens.
        PlayerState(
            name="P0", hand=[blood], library=[_mk_card("Top", "Land")] * 3
        ),
        PlayerState(name="P1", battlefield=[lazy, idle]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    # Cast on the *defender's* turn, because "this turn" is the window the
    # requirement lives in: on any other turn the mark is swept before the
    # creature is ever asked to attack.
    game.start_turn(1)
    game._close_current_priority_step()

    result = game.cast_from_hand(
        0, "Boiling Blood", target_player_index=1,
        target_permanent_index=game.battlefield_index_of(lazy),
    )
    game.resolve_stack()

    assert result.supported, result.details
    assert lazy.metadata.get("must_attack_until_eot") is True, game.log
    assert idle.metadata.get("must_attack_until_eot") is None, game.log

    game.advance_combat_phase()
    game.advance_combat_phase()
    refused, why = game.declare_attackers(1, [])
    assert not refused, "the requirement was not enforced"
    assert "Lazy Bear" in why
    assert game.declare_attackers(1, [game.battlefield_index_of(lazy)])[0]


def test_boiling_blood_still_draws_its_card(set_pool):
    """The line that used to be the whole card, kept — a round that teaches a
    sentence to parse can just as easily take the sentence beside it away."""
    blood = set_pool("WTH")["Boiling Blood"]
    bear = _w2g5_creature("Lazy Bear")
    game = Game(players=[
        PlayerState(name="P0", hand=[blood], library=[_mk_card("Top", "Land")] * 3),
        PlayerState(name="P1", battlefield=[bear]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    game.cast_from_hand(
        0, "Boiling Blood", target_player_index=1,
        target_permanent_index=0,
    )
    game.resolve_stack()

    assert [c.name for c in game.players[0].hand] == ["Top"], game.log


def test_boiling_blood_offers_a_creature_picker(set_pool):
    """The Roots class: a supported card the client sends a *bare* cast for,
    because the derivation answered None. It answers now, and it answers
    "creature" — the printed noun — rather than "any target"."""
    blood = set_pool("WTH")["Boiling Blood"]

    spec = derive_cast_spec(blood, compile_card_oracle(blood))

    assert spec is not None and spec.get("kind") == "creature"


def test_urborg_justice_sacrifices_one_creature_per_creature_you_lost(set_pool):
    """"Target opponent sacrifices a creature of their choice **for each
    creature put into your graveyard from the battlefield this turn**."

    The multiplier counts the *caster's* graveyard (CR 400.3's owner), so it
    rides the shared count channel rather than the per-payer one beside it —
    read per payer the spell would size itself from the sacrificing opponent's
    own losses and ask for nothing whenever they had lost nothing.
    """
    justice = set_pool("WTH")["Urborg Justice"]
    mine = [_w2g5_creature(f"Mine{i}") for i in range(2)]
    theirs = [_w2g5_creature(f"Theirs{i}", "Creature - Ogre") for i in range(4)]
    me = PlayerState(name="P0", hand=[justice], battlefield=mine)
    them = PlayerState(name="P1", battlefield=theirs)
    game = Game(players=[me, them])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    for perm in list(mine):
        game.remove_from_battlefield(perm)
        game._permanent_to_graveyard(me, perm)

    game.cast_from_hand(0, "Urborg Justice", target_player_index=1)
    game.resolve_stack()
    game._settle()

    assert len(them.battlefield) == 2, game.log
    assert len(them.graveyard) == 2, game.log


def test_urborg_justice_asks_for_nothing_when_you_lost_nothing(set_pool):
    """Zero is a legal answer and no prompt: CR 608.2 does as much as possible,
    and a seat that owes none is not asked."""
    justice = set_pool("WTH")["Urborg Justice"]
    theirs = [_w2g5_creature(f"Theirs{i}", "Creature - Ogre") for i in range(4)]
    them = PlayerState(name="P1", battlefield=theirs)
    game = Game(players=[
        PlayerState(name="P0", hand=[justice]), them,
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    game.cast_from_hand(0, "Urborg Justice", target_player_index=1)
    game.resolve_stack()
    game._settle()

    assert len(them.battlefield) == 4, game.log
    assert them.graveyard == [], game.log

# --- end W2G5 ---
