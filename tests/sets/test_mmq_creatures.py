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


# --- W1G2: combat-event triggers and the defending player ---

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.named_counters import counters_on
from tests.helpers import _mk_creature_card, resolve_stack


def _g2_vanilla(name: str, power: int = 1, toughness: int = 1) -> CardDefinition:
    """A creature with no text at all, so the only thing under test is the
    trigger printed on the *other* creature in the combat."""
    return _mk_creature_card(name, power, toughness)


def _g2_blocked(
    set_pool, attacker_name, *, blockers=1, hand=(), seats=2, blocker_text="",
    libraries=0,
):
    """*attacker_name* attacking, and declared blocked by *blockers* vanillas.

    The becomes-blocked triggers this block is about are announced by the
    declare-blockers step (CR 509.1h/509.3c), so a compiled program alone proves
    nothing: which seat "defending player" names is a fact the fire site freezes
    and only a driven combat can show.
    """
    attacker = Permanent(card=set_pool("MMQ")[attacker_name])
    walls = [
        Permanent(card=_mk_creature_card(f"Blocker {i}", 0, 4, blocker_text))
        for i in range(blockers)
    ]
    p1 = PlayerState(
        name="P1", battlefield=[attacker], life=20,
        library=[_g2_vanilla(f"Mine {i}") for i in range(libraries)],
    )
    p2 = PlayerState(
        name="P2", battlefield=walls, life=20,
        hand=[_g2_vanilla(n) for n in hand],
        library=[_g2_vanilla(f"Theirs {i}") for i in range(libraries)],
    )
    players = [p1, p2]
    for extra in range(seats - 2):
        players.append(PlayerState(name=f"P{extra + 3}", life=20))
    game = Game(players=players)
    game._settle()
    attacker.metadata["summoning_sickness_turn"] = -99
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(1, {i: 0 for i in range(blockers)})[0]
    resolve_stack(game)
    return game, attacker


@pytest.mark.parametrize(
    "name, at_random",
    [("Alley Grifters", False), ("Corrupt Official", True)],
)
def test_the_becomes_blocked_discard_empties_the_defending_seat(
    set_pool, name, at_random
):
    """"Whenever this creature becomes blocked, defending player discards a
    card[ at random]."

    CR 506.2 defines "defending player" only inside a combat, and the phrase is
    resolved off the seat the declare-blockers announcement froze (CR 603.10) —
    not off the board, which by resolution may have no combat at all. The
    assertion that matters is the *negative* one: the attacker's controller,
    who is the seat a targetless resolution falls back to, keeps their hand.
    """
    game, _ = _g2_blocked(set_pool, name, hand=("A", "B"))

    if not at_random:
        # A chosen discard is a decision, so it is owed as a prompt rather than
        # taken — and *whose* prompt it is, is the whole of what this asserts.
        owed = [c for c in game.pending_choices if c.kind == "discard"]
        assert [c.player_index for c in owed] == [1]
        game.auto_resolve_pending_choices()
    assert len(game.players[1].hand) == 1, "the blocked-by seat discards"
    assert len(game.players[0].hand) == 0, "and it is not the attacker's hand"


def test_the_becomes_blocked_discard_names_nobody_outside_a_combat(set_pool):
    """The same trigger with nothing frozen discards from nobody.

    A resolution carrying no recorded seat must not fall back to the ability's
    own controller: that is the one player the card can never mean. Driven by
    pushing the compiled trigger with an empty context rather than by a combat,
    because a combat is exactly what this asks about the absence of.
    """
    from engine.game_types import StackItem
    from engine.oracle import compile_card_oracle

    grifters = Permanent(card=set_pool("MMQ")["Alley Grifters"])
    p1 = PlayerState(
        name="P1", battlefield=[grifters], life=20, hand=[_g2_vanilla("Held")]
    )
    p2 = PlayerState(name="P2", life=20, hand=[_g2_vanilla("Theirs")])
    game = Game(players=[p1, p2])
    game._settle()
    trig = compile_card_oracle(grifters.card).triggered_abilities[0]
    game._stack_push(
        StackItem(
            card=grifters.card, caster_index=0, target_player_index=0,
            target_permanent_index=None, x_value=None,
            ability_instruction=trig.instruction,
            ability_effect_kind=trig.effect_kind,
            source_permanent=grifters, ability_text=trig.source_line,
            trigger_context={},
        )
    )
    resolve_stack(game)

    assert len(game.players[0].hand) == 1
    assert len(game.players[1].hand) == 1


def test_port_inspector_shows_the_defending_players_hand(set_pool):
    """"…you may look at defending player's hand."

    The look is armed as a `hand_reveal` prompt for the *viewer*, and the seat
    it names is the one the combat froze. Without that key the handler read
    ``context.target`` — which for a trigger that chose nothing is whatever the
    resolution was carrying — so the assertion below is about `target_index`,
    not merely about a prompt existing.
    """
    game, _ = _g2_blocked(set_pool, "Port Inspector", hand=("X", "Y", "Z"))
    # "You may" is a decision owed to the attacker's controller, and only that
    # one is answered here: draining the whole queue would also answer the
    # `hand_reveal` this test is about, out from under the assertion.
    assert game.confirm_optional_pay(0, "Port Inspector", accept=True)
    game._settle()

    reveals = [c for c in game.pending_choices if c.kind == "hand_reveal"]
    assert len(reveals) == 1
    assert reveals[0].player_index == 0, "the attacker's controller looks"
    assert reveals[0].data["target_index"] == 1
    assert sorted(reveals[0].data["card_names"]) == ["X", "Y", "Z"]


def test_robber_fly_refills_the_defending_players_hand(set_pool):
    """"…defending player discards all the cards in their hand, then draws that
    many cards."

    Two steps, one seat. The draw used to carry no seat at all — the sentence's
    "that many" was read but "defending player" was not — so the hand emptied on
    one side of the table and the cards arrived on the other. Both halves are
    asserted, and the library is stocked so a draw can actually happen.
    """
    # Robber Fly flies, so the blocker has to be able to reach it — the card
    # under test is the trigger, not the evasion.
    game, _ = _g2_blocked(
        set_pool, "Robber Fly", hand=("A", "B", "C"), blocker_text="Reach",
        libraries=10,
    )

    assert len(game.players[1].hand) == 3, "discarded three, drew three"
    assert all(c.name.startswith("Theirs") for c in game.players[1].hand)
    assert len(game.players[0].hand) == 0, "the attacker's seat drew nothing"
    assert len(game.players[0].library) == 10, "and drew from nobody's library"
    assert len(game.players[1].graveyard) == 3


def test_quagmire_lamprey_shrinks_each_creature_that_blocked_it(set_pool):
    """"Whenever this creature becomes blocked **by a creature**, put a -1/-1
    counter on that creature."

    CR 509.3d: the narrowed wording fires once per creature that blocks, so two
    blockers means two firings and two counters — one each, never two on the
    first. The counter is a CR 122.1a P/T pair, so it goes through
    ``place_pt_counters`` rather than the named-counter store.
    """
    game, lamprey = _g2_blocked(set_pool, "Quagmire Lamprey", blockers=2)

    blockers = game.players[1].battlefield
    assert [counters_on(b, "-1/-1") for b in blockers] == [1, 1]
    assert [b.effective_toughness for b in blockers] == [3, 3]
    assert counters_on(lamprey, "-1/-1") == 0, "not on the attacker"


def _g2_trap_runner_board(set_pool):
    """Trap Runner on the defending seat, one unblocked attacker in front of it.

    The ability is the defender's answer to a creature nothing could block, so
    the board is the one it is printed for: the attack is declared and no block
    is, which is exactly the moment CR 509.1h makes the attacker unblocked.
    """
    runner = Permanent(card=set_pool("MMQ")["Trap Runner"])
    attacker = Permanent(card=_g2_vanilla("Sneak", 3, 3))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker], life=20),
        PlayerState(name="P2", battlefield=[runner], life=20),
    ])
    game._settle()
    for perm in (runner, attacker):
        perm.metadata["summoning_sickness_turn"] = -99
    game.active_player_index = 0
    return game, runner, attacker


def test_trap_runner_blocks_an_unblocked_attacker_after_the_declaration(set_pool):
    """"{T}: Target unblocked attacking creature becomes blocked."

    CR 509.1h: an effect may say an attacking creature becomes blocked, and the
    creature stays blocked for the rest of the combat. The attacker is left
    unblocked by the declaration, so its damage would go to the face; after the
    ability it is blocked by nobody and assigns its damage to nothing.
    """
    game, runner, attacker = _g2_trap_runner_board(set_pool)
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(1, {})[0]
    assert attacker.blocked is False

    assert game.activate_permanent_ability(
        1, "Trap Runner", target_permanent_ids=[attacker.permanent_id],
    ).supported
    resolve_stack(game)

    assert attacker.blocked is True
    assert runner.tapped is True


def test_trap_runner_cannot_be_activated_before_blockers_are_declared(set_pool):
    """"Activate only during combat after blockers are declared."

    A printed restriction is only done when something enforces it, and the
    failure it prevents is silent and in the player's favour: used in the
    declare-attackers step the ability would pre-empt the defender's own
    declaration, which is a card that works more often than it says. Asserted at
    both ends of the window — refused before the declaration and in a main
    phase, allowed once the blocks are locked in.
    """
    game, runner, attacker = _g2_trap_runner_board(set_pool)
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    refused = game.activate_permanent_ability(
        1, "Trap Runner", target_permanent_ids=[attacker.permanent_id],
    )
    # The *message*, not merely the refusal: in a main phase this ability is
    # already refused for want of an attacking creature, so a bare `not
    # supported` would pass with the clause unenforced. This asserts the clause
    # is what declined it, on a board where a legal target exists.
    assert not refused.supported
    assert refused.details.endswith(
        "only during combat after blockers are declared"
    )
    assert runner.tapped is False, "and nothing was paid for the refusal"

    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(1, {})[0]
    assert game.activate_permanent_ability(
        1, "Trap Runner", target_permanent_ids=[attacker.permanent_id],
    ).supported


def test_silent_assassin_destroys_the_blocker_at_end_of_combat(set_pool):
    """"{3}{B}: Destroy target blocking creature at end of combat."

    CR 603.7: the ability creates a *delayed* triggered ability, so nothing
    happens when it resolves — the blocker is still there through the combat
    damage step and deals its damage. CR 602.2b picks the target at activation,
    which is what the entry binds: by the end-of-combat step the creature may
    have stopped blocking, and a version that re-picked then would find nothing.
    """
    assassin = Permanent(card=set_pool("MMQ")["Silent Assassin"])
    attacker = Permanent(card=_g2_vanilla("Charger", 2, 2))
    blocker = Permanent(card=_g2_vanilla("Guard", 1, 4))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker], life=20),
        PlayerState(name="P2", battlefield=[blocker, assassin], life=20),
    ])
    game._settle()
    for perm in (assassin, attacker, blocker):
        perm.metadata["summoning_sickness_turn"] = -99
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(1, {0: 0})[0]
    resolve_stack(game)

    game.players[1].mana_pool.update({"B": 1, "C": 3})
    assert game.activate_permanent_ability(
        1, "Silent Assassin", target_permanent_ids=[blocker.permanent_id],
    ).supported
    resolve_stack(game)
    assert game.is_on_battlefield(blocker), "nothing happens until end of combat"

    game.end_combat()
    resolve_stack(game)

    assert not game.is_on_battlefield(blocker)
    assert [c.name for c in game.players[1].graveyard] == ["Guard"]


def test_silent_assassin_has_no_target_with_nobody_blocking(set_pool):
    """The same ability outside a block names nobody.

    CR 601.2c / 602.2b: an ability with a mandatory target it cannot fill is
    refused with nothing paid, rather than activated to arm an entry about
    nothing. The mana is asserted still in the pool, because "refused" and
    "resolved doing nothing" look identical from the board.
    """
    assassin = Permanent(card=set_pool("MMQ")["Silent Assassin"])
    bystander = Permanent(card=_g2_vanilla("Idler", 1, 1))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bystander], life=20),
        PlayerState(name="P2", battlefield=[assassin], life=20),
    ])
    game._settle()
    assassin.metadata["summoning_sickness_turn"] = -99
    game.players[1].mana_pool.update({"B": 1, "C": 3})

    assert not game.activate_permanent_ability(
        1, "Silent Assassin", target_permanent_ids=[bystander.permanent_id],
    ).supported
    assert game.players[1].mana_pool["B"] == 1, "nothing was paid"


def test_erithizon_lets_the_defending_player_pick_the_creature(set_pool):
    """"Whenever this creature attacks, put a +1/+1 counter on target creature
    of defending player's choice."

    CR 602.3: an ability may say one of its controller's opponents does what the
    controller normally would — here, choose the target. So the prompt is owed
    by the *defending* seat (CR 506.2, frozen by the declare-attackers
    announcement), and the assertion that matters is whose prompt it is: handed
    to the attacker's controller the card would be a free +1/+1 every attack
    instead of a gift.
    """
    erithizon = Permanent(card=set_pool("MMQ")["Erithizon"])
    theirs = Permanent(card=_g2_vanilla("Their Bear", 2, 2))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[erithizon], life=20),
        PlayerState(name="P2", battlefield=[theirs], life=20),
    ])
    game._settle()
    erithizon.metadata["summoning_sickness_turn"] = -99
    game.active_player_index = 0
    # Only the defending seat is interactive, so the prompt has to *queue* for
    # this test to see it: a non-interactive seat takes the default the instant
    # the choice is armed, and the two seats' defaults would be indistinguishable
    # here — the card narrows the creature not at all, so "any creature" is a
    # legal answer from either.
    game.interactive_seats = {1}
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]

    # The prompt is armed part-way through the trigger's resolution, so it is
    # read before the queue is drained.
    game.resolve_top_of_stack()
    owed = [c for c in game.pending_choices if c.kind == "permanent_choice"]
    assert [c.player_index for c in owed] == [1], "the defending seat picks"

    assert game.confirm_permanent_choice(1, theirs.permanent_id)
    game._settle()

    assert counters_on(theirs, "+1/+1") == 1
    assert counters_on(erithizon, "+1/+1") == 0
    assert theirs.effective_power == 3


# --- W1G4: upkeep, end-step and enters-the-battlefield triggers ---
#
# Five creatures whose abilities fire at a step boundary or on entry. The
# pattern worth stating: every one was refused by a *lowering* rather than by a
# parse, and in three cases the printed sentence was already a production one
# word order or one article away.

import pytest

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from tests.helpers import resolve_stack


def _g4_blank(name, type_line="Basic Land - Island"):
    """A filler card with no text, for hands, libraries and graveyards."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name},
    )


def _g4_creature(name, power="2", toughness="2"):
    """A vanilla bear, for a graveyard census or a sacrifice candidate."""
    return CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line="Creature - Bear",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": name},
        power=power, toughness=toughness,
    )


def _g4_duel(set_pool):
    """Two seats, cost enforcement off, and MMQ's pool keyed by name."""
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2, set_pool("MMQ")


def _g4_settle(game):
    """Drain the stack, then answer the offers a trigger left behind it."""
    game._settle()
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._settle()
    return game


def test_extravagant_spirits_toll_scales_with_the_hand(set_pool):
    """"...sacrifice this creature unless you pay {1} **for each card in your
    hand**." The multiplier is not a printed number, so it rides the payload as
    an ordinary count spec and is taken when the ability resolves (CR 608.2) -
    the hand as it stands then, not as it stood when the trigger fired.

    The card is asserted at the compiled program because a *headless* seat
    never taps a land for an optional cost (a stated policy, not the payability
    test), so no board this test could build would show the price being paid;
    Megatherium below pays the same toll out of a pool it already holds.
    """
    from engine.oracle import compile_card_oracle

    program = compile_card_oracle(set_pool("MMQ")["Extravagant Spirit"])
    offer = program.triggered_abilities[0].instruction
    assert offer.kind == "may"
    assert offer.payload["cost"] == {"generic": 1}
    assert offer.payload["cost_per"] == {
        "zone": "hand", "owner": "you", "filter": {},
    }


def test_extravagant_spirit_goes_when_the_toll_is_not_paid(set_pool):
    """The decline branch is the sacrifice, and it is the source that goes -
    not a permanent chosen out of the controller's board."""
    game, p1, _p2, by_name = _g4_duel(set_pool)
    p1.battlefield.append(Permanent(card=by_name["Extravagant Spirit"]))
    p1.battlefield.append(Permanent(card=_g4_creature("Bystander")))
    p1.hand = [_g4_blank("h0"), _g4_blank("h1")]
    game._sync_control()
    game.active_player_index = 0
    game.resolve_upkeep(0)
    _g4_settle(game)

    assert [perm.card.name for perm in p1.battlefield] == ["Bystander"]


def test_an_empty_hand_makes_extravagant_spirits_toll_free(set_pool):
    """Zero cards is a cost of {0}, which its payer can always cover - so the
    creature stays with no mana at all."""
    game, p1, _p2, by_name = _g4_duel(set_pool)
    p1.battlefield.append(Permanent(card=by_name["Extravagant Spirit"]))
    game._sync_control()
    game.active_player_index = 0
    game.resolve_upkeep(0)
    _g4_settle(game)

    assert [perm.card.name for perm in p1.battlefield] == ["Extravagant Spirit"]


def test_megatherium_charges_the_same_toll_on_entry(set_pool):
    """The identical printed sentence on an **enters** trigger. It used to
    lower to ``upkeep_pay_or_sacrifice_self``, which the upkeep registry
    dispatches and nothing else does - so the card would have compiled clean
    and never charged anybody."""
    game, p1, _p2, by_name = _g4_duel(set_pool)
    p1.hand = [_g4_blank("h0"), _g4_blank("h1")]
    p1.mana_pool["G"] = 5
    game._put_permanent_onto_battlefield(
        0, Permanent(card=by_name["Megatherium"]), None
    )
    _g4_settle(game)

    assert [perm.card.name for perm in p1.battlefield] == ["Megatherium"]
    assert p1.mana_pool["G"] == 3


def test_nether_spirit_returns_itself_when_it_is_alone(set_pool):
    """CR 113.6b: the intervening-if is where the card says a graveyard is
    where the ability functions at all, so the upkeep's graveyard scan is what
    fires it."""
    game, p1, _p2, by_name = _g4_duel(set_pool)
    p1.graveyard = [by_name["Nether Spirit"], _g4_blank("Ritual", "Sorcery")]
    game.active_player_index = 0
    game.resolve_upkeep(0)
    _g4_settle(game)

    assert [perm.card.name for perm in p1.battlefield] == ["Nether Spirit"]
    assert [card.name for card in p1.graveyard] == ["Ritual"]


@pytest.mark.parametrize("companions, comes_back", [((), True), (("Bear",), False)])
def test_nether_spirit_counts_every_creature_card_in_the_pile(
    set_pool, companions, comes_back,
):
    """"the **only** creature card" is a census, not a position: one other
    creature card anywhere in the graveyard turns the ability off."""
    game, p1, _p2, by_name = _g4_duel(set_pool)
    p1.graveyard = [by_name["Nether Spirit"]] + [
        _g4_creature(name) for name in companions
    ]
    game.active_player_index = 0
    game.resolve_upkeep(0)
    _g4_settle(game)

    on_board = [perm.card.name for perm in p1.battlefield]
    assert ("Nether Spirit" in on_board) is comes_back


def test_two_nether_spirits_are_two_creature_cards(set_pool):
    """The identity half of the test earns its keep here: a graveyard holding
    two copies has two creature cards in it, and neither is "the only" one.
    Two copies of a card in a deck are the same immutable object, so a count
    that stopped at "is this card in the pile" would return both."""
    game, p1, _p2, by_name = _g4_duel(set_pool)
    spirit = by_name["Nether Spirit"]
    p1.graveyard = [spirit, spirit]
    game.active_player_index = 0
    game.resolve_upkeep(0)
    _g4_settle(game)

    assert [perm.card.name for perm in p1.battlefield] == []
    assert len(p1.graveyard) == 2


def test_charmed_griffin_offers_each_opponent_a_permanent_from_hand(set_pool):
    """"...put an artifact or enchantment card onto the battlefield **from
    their hand**" - the source zone printed after the destination, which the
    noun parser reads perfectly well the other way round."""
    game, _p1, p2, by_name = _g4_duel(set_pool)
    p2.hand = [_g4_blank("Bauble", "Artifact"), _g4_blank("Ritual", "Sorcery")]
    game._put_permanent_onto_battlefield(
        0, Permanent(card=by_name["Charmed Griffin"]), None
    )
    _g4_settle(game)

    assert [perm.card.name for perm in p2.battlefield] == ["Bauble"]
    assert [card.name for card in p2.hand] == ["Ritual"]


def test_charmed_griffin_leaves_a_hand_with_nothing_it_names(set_pool):
    """The sorcery is neither an artifact nor an enchantment, and the *card*
    matcher now knows it: ``artifact_or_enchantment`` was a ``type_filter``
    value only the permanent matcher special-cased, so it matched every
    qualifying permanent and no card in any zone."""
    game, _p1, p2, by_name = _g4_duel(set_pool)
    p2.hand = [_g4_blank("Ritual", "Sorcery")]
    game._put_permanent_onto_battlefield(
        0, Permanent(card=by_name["Charmed Griffin"]), None
    )
    _g4_settle(game)

    assert [perm.card.name for perm in p2.battlefield] == []
    assert [card.name for card in p2.hand] == ["Ritual"]


def test_enslaved_horror_reanimates_out_of_every_other_graveyard(set_pool):
    """"each other player may return a creature card from **their** graveyard"
    - the offered seat's own pile, and never the controller's."""
    game, p1, p2, by_name = _g4_duel(set_pool)
    p1.graveyard = [_g4_creature("Mine")]
    p2.graveyard = [_g4_blank("Ritual", "Sorcery"), _g4_creature("Theirs")]
    game._put_permanent_onto_battlefield(
        0, Permanent(card=by_name["Enslaved Horror"]), None
    )
    _g4_settle(game)

    assert [perm.card.name for perm in p2.battlefield] == ["Theirs"]
    assert [perm.card.name for perm in p1.battlefield] == ["Enslaved Horror"]
    assert [card.name for card in p1.graveyard] == ["Mine"]
