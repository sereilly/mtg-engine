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
