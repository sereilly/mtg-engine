"""Mercadian Masques creatures.

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

Cards come from `set_pool("MMQ")` / `set_cards("MMQ")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: alternative and additional casting costs ---
# CR 118.9's *second* printed spelling, which the rule names beside the first:
# "You may cast this spell without paying its mana cost." Mercadian Masques
# prints it five times, once per colour, each behind a two-land condition
# checked at CR 601.2b — so what is asserted here is the board and the mana
# pool, never that a sentence parsed.
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle

#: (Legate, the land **you** must control, the land an **opponent** must).
#: Printed as a cycle, so the table is the cycle: a reader that admitted one
#: seat's land for the other's would pass on any single card and fail on all
#: five, which is what the swapped-board test below asks.
_G1_LEGATES = (
    ("Cho-Arrim Legate", "Plains", "Swamp"),
    ("Deepwood Legate", "Swamp", "Forest"),
    ("Kyren Legate", "Mountain", "Plains"),
    ("Rushwood Legate", "Forest", "Island"),
    ("Saprazzan Legate", "Island", "Mountain"),
)


def _g1_duel(set_pool, hand, mine=(), theirs=()):
    """A two-seat board with mana-cost enforcement **on**.

    On, deliberately and unlike the house rig: every card in this block is about
    not paying a mana cost, and a game that charges none cannot tell a free cast
    from an ordinary one.
    """
    pool = set_pool("MMQ")
    caster, other = PlayerState("Caster"), PlayerState("Opponent")
    caster.hand = [pool[name] for name in hand]
    game = Game(players=[caster, other])
    game.enforce_mana_costs = True
    for name in mine:
        caster.battlefield.append(Permanent(card=pool[name]))
    for name in theirs:
        other.battlefield.append(Permanent(card=pool[name]))
    game._sync_control()
    return game, caster, other


def _g1_offers(game, seat, card, hand_index=0):
    """The alternative-cost offers the picker would show, with payability."""
    return [
        (offer["label"], offer["payable"])
        for offer in game.cast_cost_offers(
            seat, card, spell_hand_index=hand_index
        )
        if offer["kind"] == "alternative"
    ]


_G1_FREE = ("cast it without paying its mana cost", True)


@pytest.mark.parametrize("name,mine,theirs", _G1_LEGATES)
def test_g1_legate_is_free_when_both_lands_are_there(set_pool, name, mine, theirs):
    """CR 118.9: the printed alternative cost is a price of nothing.

    Every one of the five compiled ``supported`` before this round — on its
    *other* line, a keyword or an activated ability — while the sentence the
    card is named for was claimed by nobody at all. So it was castable only at
    its printed mana cost, and the whole point of the cycle did not exist.
    "The sentence parses" is exactly the evidence that was wrong, so the board
    is what is asserted: nothing tapped, nothing in the pool, the creature in
    play.
    """
    card = set_pool("MMQ")[name]
    game, caster, _ = _g1_duel(set_pool, [name], mine=(mine,), theirs=(theirs,))

    assert compile_card_oracle(card).supported
    assert _g1_offers(game, 0, card) == [_G1_FREE]

    result = game.cast_from_hand(0, name, alternative_cost=True)

    assert result.supported, result.details
    assert [perm.card.name for perm in caster.battlefield] == [mine, name]
    # CR 118.9c: the alternative replaces the payment, never the mana cost.
    assert not any(caster.mana_pool.values())
    assert not any(perm.tapped for perm in caster.battlefield)
    assert card.mana_cost


@pytest.mark.parametrize("name,mine,theirs", _G1_LEGATES)
def test_g1_legate_offers_nothing_on_an_empty_board(set_pool, name, mine, theirs):
    """CR 601.2b: a condition that does not hold is not an offer.

    Not "an offer that cannot be paid" — those are different answers and the
    difference is what a picker shows. An unmet condition means there is no
    alternative cost to announce, so the caster is refused by CR 118.9 rather
    than by CR 601.2h, and nothing is spent either way.
    """
    card = set_pool("MMQ")[name]
    game, caster, _ = _g1_duel(set_pool, [name])

    assert _g1_offers(game, 0, card) == []

    result = game.cast_from_hand(0, name, alternative_cost=True)

    assert not result.supported
    assert "CR 118.9" in result.details
    assert [held.name for held in caster.hand] == [name]


@pytest.mark.parametrize("name,mine,theirs", _G1_LEGATES)
def test_g1_legate_reads_which_seat_controls_which_land(set_pool, name, mine, theirs):
    """The two land types are not interchangeable, and neither are the seats.

    "If an opponent controls a Swamp and **you** control a Plains" is two
    clauses about two different battlefields. A reader that scanned one board
    for both, or that folded the pair into "these two lands are somewhere",
    passes every other test in this block: both lands are on the table here,
    only on the wrong sides.
    """
    card = set_pool("MMQ")[name]
    game, caster, _ = _g1_duel(set_pool, [name], mine=(theirs,), theirs=(mine,))

    assert _g1_offers(game, 0, card) == []
    assert not game.cast_from_hand(0, name, alternative_cost=True).supported
    assert [held.name for held in caster.hand] == [name]


@pytest.mark.parametrize("name,mine,theirs", _G1_LEGATES)
def test_g1_legate_needs_both_halves_of_its_condition(set_pool, name, mine, theirs):
    """Each clause alone is not the condition (CR 601.2b).

    An "and" read as an "or" is an offer standing on strictly more boards than
    the card names — the direction a cost must never drift in, and invisible to
    every test that sets up the board the card asks for.
    """
    card = set_pool("MMQ")[name]

    game, _, _ = _g1_duel(set_pool, [name], mine=(mine,))
    assert _g1_offers(game, 0, card) == []

    game, _, _ = _g1_duel(set_pool, [name], theirs=(theirs,))
    assert _g1_offers(game, 0, card) == []


def test_g1_legate_condition_is_re_asked_at_every_cast(set_pool):
    """CR 601.2b checks the condition **as the spell is cast**, not once.

    The offer is derived from the board at the moment of the announcement, so a
    Legate that was free while both lands were there is not free after one
    leaves. A condition resolved at compile time — the tempting place, since the
    printed sentence never changes — would be a permanently free creature.
    """
    card = set_pool("MMQ")["Kyren Legate"]
    game, _, other = _g1_duel(
        set_pool, ["Kyren Legate"], mine=("Mountain",), theirs=("Plains",),
    )

    assert _g1_offers(game, 0, card) == [_G1_FREE]

    game.remove_from_battlefield(other.battlefield[0])

    assert _g1_offers(game, 0, card) == []


def test_g1_legate_still_costs_its_mana_when_the_offer_is_declined(set_pool):
    """CR 118.9b: the alternative cost is optional, and declining is a real cast.

    The caster who says nothing pays the printed price — which is what the five
    Legates did on every board before this round, and what they must go on doing
    on a board that does not meet the condition.
    """
    game, caster, _ = _g1_duel(
        set_pool, ["Kyren Legate"], mine=("Mountain", "Mountain"),
    )
    caster.mana_pool["R"] = 1
    caster.mana_pool["C"] = 1

    result = game.cast_from_hand(0, "Kyren Legate")

    assert result.supported, result.details
    assert not any(caster.mana_pool.values())
    assert [perm.card.name for perm in caster.battlefield].count("Kyren Legate") == 1


# --- W1G3: prevention shields and damage redirection ---
from engine import Game as _G3cGame
from engine import PlayerState as _G3cPlayerState
from engine.models import CardDefinition as _G3cCard
from engine.models import Permanent as _G3cPermanent
from engine.shields import shields_on as _g3c_shields_on
from tests.helpers import _damage_dealt as _g3c_dealt
from tests.helpers import resolve_stack as _g3c_resolve


def _g3c_creature(name, power=2, toughness=2):
    """A vanilla creature to shield, to shield against, or to block with."""
    line = "Creature - Test"
    return _G3cCard(
        name=name, mana_cost="", cmc=0.0, type_line=line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": line,
             "power": str(power), "toughness": str(toughness)},
    )


def _g3c_board(seat0=(), seat1=()):
    """A two-seat game with the permanents already on the battlefield."""
    made = _G3cGame(players=[
        _G3cPlayerState(name="P0", battlefield=list(seat0)),
        _G3cPlayerState(name="P1", battlefield=list(seat1)),
    ])
    made.enforce_mana_costs = False
    made.interactive_seats = set()
    return made


def test_cho_manno_shields_itself_by_its_own_printed_name(set_pool):
    """"Prevent all damage that would be dealt to Cho-Manno."

    CR 201.5: text naming the object it is on means *that* object. Pre-modern
    templating writes the name where modern templating writes "this creature",
    and the static-shield pattern is anchored on the modern wording — so the
    self-reference has to be collapsed before the line is matched, or the card
    reports "text too complex" for a shield the engine already implements.

    The bystander and the look-alike are both here because the rule is about
    *this object*: a reader that matched the printed name against the board
    rather than against the card it is on would shield a second creature
    sharing it, and CR 201.5's last clause says it must not.
    """
    cho = _G3cPermanent(card=set_pool("MMQ")["Cho-Manno, Revolutionary"])
    bystander = _G3cPermanent(card=_g3c_creature("Bystander"))
    victim = _G3cPermanent(card=_g3c_creature("Victim", 5, 5))
    game = _g3c_board((cho, bystander), (victim,))

    assert _g3c_dealt(game, cho, 3, source=victim, combat=True) == 0
    assert _g3c_dealt(game, cho, 3, source=victim) == 0, "damage of every kind"
    assert _g3c_dealt(game, bystander, 3, source=victim) == 3, "only Cho-Manno"
    assert _g3c_dealt(game, victim, 3, source=cho, combat=True) == 3, (
        "'dealt to' is one end of the event"
    )


def test_ignoble_soldier_silences_itself_and_not_the_creature_blocking_it(
    set_pool,
):
    """"Whenever this creature becomes blocked, prevent all combat damage that
    would be dealt by it this turn."

    "It" is the ability's own source, and reading it any other way is invisible
    from the compiled program: a triggered ability's stack item carries a
    bookkeeping target, and under `creature_becomes_blocked` that target is the
    **blocker**. The first run of this card logged "all combat damage Blocker
    would deal this turn is prevented (Ignoble Soldier)" — the wrong creature,
    with the card reporting supported and the trigger reporting resolved.

    So the block is declared for real rather than the shield being armed by
    hand, and the decoy is here to catch the other failure the same clause has:
    a fallback scan over the battlefields would silence whichever creature it
    reached first.
    """
    soldier = _G3cPermanent(card=set_pool("MMQ")["Ignoble Soldier"])
    decoy = _G3cPermanent(card=_g3c_creature("Decoy", 7, 7))
    blocker = _G3cPermanent(card=_g3c_creature("Blocker", 1, 6))
    game = _g3c_board((soldier, decoy), (blocker,))
    for permanent in (soldier, decoy, blocker):
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()   # declare blockers
    assert game.declare_blockers(1, {0: 0})[0]
    _g3c_resolve(game)

    assert _g3c_dealt(game, blocker, 2, source=soldier, combat=True) == 0
    assert _g3c_dealt(game, blocker, 2, source=soldier) == 2, (
        "the printed 'combat' is read"
    )
    assert _g3c_dealt(game, blocker, 7, source=decoy, combat=True) == 7, (
        "no other creature was silenced"
    )
    assert _g3c_dealt(game, soldier, 2, source=blocker, combat=True) == 2, (
        "'dealt by' leaves the soldier perfectly able to be dealt damage"
    )


def test_charm_peddler_shields_a_chosen_creature_from_a_chosen_source(set_pool):
    """"{W}, {T}, Discard a card: The next time a source of your choice would
    deal damage to target creature this turn, prevent that damage."

    CR 615.8's whole-instance shield with **two** announcements in one
    activation: the protected creature is a target (CR 601.2c) and the source is
    CR 609.7's choice, which is not a target at all. Both are checked, because
    each has its own way of going quietly wrong — a shield armed on the
    activating player instead of on the target, and a shield answering to every
    source instead of the one named.

    The last assertion is CR 615.8's closing sentence: once an instance from
    that source has been prevented, the next is dealt normally.
    """
    peddler = _G3cPermanent(card=set_pool("MMQ")["Charm Peddler"])
    protectee = _G3cPermanent(card=_g3c_creature("Protectee", 2, 6))
    named = _G3cPermanent(card=_g3c_creature("Named Source", 3, 3))
    other = _G3cPermanent(card=_g3c_creature("Other Source", 3, 3))
    game = _g3c_board((peddler, protectee), (named, other))
    game.players[0].hand = [_g3c_creature("Discardable")]
    game.start_turn(0)
    game._close_current_priority_step()
    peddler.metadata["summoning_sickness_turn"] = -99
    game.players[0].mana_pool.update({"W": 1})

    result = game.activate_permanent_ability(
        0, "Charm Peddler",
        target_player_index=0,
        target_permanent_ids=[protectee.permanent_id],
        source_seat=1, source_permanent_index=0,
    )
    assert result.supported, result
    _g3c_resolve(game)

    assert [s.kind for s in _g3c_shields_on(protectee)] == ["prevent_whole"]
    assert _g3c_shields_on(game.players[0]) == [], (
        "the shield goes round the announced creature, not round its controller"
    )
    assert _g3c_dealt(game, protectee, 3, source=other) == 3, "an unnamed source"
    assert _g3c_dealt(game, protectee, 3, source=named) == 0, "the named one"
    assert _g3c_dealt(game, protectee, 3, source=named) == 3, (
        "CR 615.8: the shield is spent by the instance it prevented"
    )
# --- end W1G3 ---
