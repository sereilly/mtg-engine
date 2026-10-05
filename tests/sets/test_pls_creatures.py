"""Planeshift creatures.

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

Cards come from `set_pool("PLS")` / `set_cards("PLS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G8: damage and the odd ones ---
#
# Mirrorwood Treefolk: "{2}{R}{W}: The next time damage would be dealt to this
# creature this turn, that damage is dealt to any target instead." A CR 614.9
# redirect — the damage is still dealt, by the same source and in full — armed
# by an activated ability with its taker chosen on activation. Zhalfirin
# Crusader's sentence with CR 615.8's one instance where that prints a point
# pool, so it is that card's instruction with ``uses`` in place of ``amount``.

from engine import Game as _w1g8c_Game, PlayerState as _w1g8c_Player  # noqa: E402
from engine.card_loader import (load_cards as _w1g8c_load,  # noqa: E402
                                manifest_set_path as _w1g8c_path)
from engine.grammar import compile_line as _w1g8c_compile_line  # noqa: E402
from engine.models import (CardDefinition as _w1g8c_Card,  # noqa: E402
                           Permanent as _w1g8c_Permanent)
from engine.oracle import compile_card_oracle as _w1g8c_compile  # noqa: E402
from engine.targeting import (  # noqa: E402
    derive_activation_spec as _w1g8c_activation_spec,
)

from tests.helpers import (_damage_dealt as _w1g8c_dealt,  # noqa: E402
                           resolve_stack as _w1g8c_resolve_stack)


def _w1g8c_lea():
    return {card.name: card for card in _w1g8c_load(_w1g8c_path("LEA"))}


def _w1g8c_body(name, power, toughness, text="", keywords=(),
                type_line="Creature - Test", colors=()):
    """A bare creature for the other side of a fight."""
    return _w1g8c_Card(
        name=name, mana_cost="{3}", cmc=3.0, type_line=type_line,
        oracle_text=text, colors=tuple(colors), color_identity=tuple(colors),
        keywords=tuple(keywords), produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )  # W1G8 creatures: a test body


def _w1g8c_duel(mine, theirs, *, hand0=(), hand1=(), active=0, interactive=()):
    """Both boards placed and unsick, *active* in its precombat main phase."""
    board0 = [_w1g8c_Permanent(card=card) for card in mine]
    board1 = [_w1g8c_Permanent(card=card) for card in theirs]
    filler = _w1g8c_body("Filler", 0, 1)
    game = _w1g8c_Game(players=[
        _w1g8c_Player(name="P0", battlefield=board0, hand=list(hand0),
                      library=[filler] * 10),
        _w1g8c_Player(name="P1", battlefield=board1, hand=list(hand1),
                      library=[filler] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for permanent in board0 + board1:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(active)
    game._close_current_priority_step()
    return game, board0, board1  # W1G8 creatures: the duel


def _w1g8c_fight(game, attacker_slot, blocks=None, *, defender):
    """The active seat attacks with one creature; combat runs to main two."""
    game.advance_combat_phase()
    game.advance_combat_phase()
    declared = game.declare_attackers(game.active_player_index, [attacker_slot])
    assert declared[0], declared
    game.advance_combat_phase()
    blocked = game.declare_blockers(defender, dict(blocks or {}))
    assert blocked[0], blocked
    for _ in range(8):
        if game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
        _w1g8c_resolve_stack(game)
    assert game.current_step == "postcombat_main", game.current_step  # W1G8: fought


def _w1g8c_arm(game, **target):
    """Activate the Treefolk's ability at *target* and let it resolve."""
    used = game.activate_permanent_ability(
        0, "Mirrorwood Treefolk", ability_index=0, **target
    )
    assert used.supported, used.details
    _w1g8c_resolve_stack(game)  # W1G8 creatures: the redirect is armed


def test_w1g8_mirrorwood_treefolk_offers_any_target_and_one_use(set_pool):
    """The activation picker offers CR 115.4's "any target", and the payload
    carries the one instance — never a point pool."""
    program = _w1g8c_compile(set_pool("PLS")["Mirrorwood Treefolk"])

    assert program.supported
    (ability,) = program.activated_abilities
    assert ability.instruction.kind == "redirect_next_damage_from_source_until_eot"
    assert ability.instruction.payload == {
        "targets": {"kind": "any", "quantifier": "any_target"}, "uses": 1,
    }
    assert ability.cost.mana == {
        "B": 0, "C": 0, "G": 0, "R": 1, "U": 0, "W": 1, "generic": 2,
    }
    assert _w1g8c_activation_spec(ability) == {"kind": "any"}


def test_w1g8_mirrorwood_treefolk_moves_the_next_burn_spell_to_a_player(set_pool):
    """The whole of the next event moves — three damage to the Treefolk is
    three to the chosen player — and then the effect is spent: the second
    Bolt lands where it was aimed."""
    lea = _w1g8c_lea()
    treefolk_card = set_pool("PLS")["Mirrorwood Treefolk"]
    game, mine, _ = _w1g8c_duel(
        [treefolk_card], [], hand1=[lea["Lightning Bolt"]] * 2, active=1,
    )
    treefolk = mine[0]
    _w1g8c_arm(game, target_player_index=1)

    game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[treefolk.permanent_id]
    )
    _w1g8c_resolve_stack(game)
    assert treefolk.damage_marked == 0
    assert [player.life for player in game.players] == [20, 17]

    game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[treefolk.permanent_id]
    )
    _w1g8c_resolve_stack(game)
    assert treefolk.damage_marked == 3, '"the next time" is one instance'
    assert [player.life for player in game.players] == [20, 17]


def test_w1g8_mirrorwood_treefolk_moves_combat_damage_onto_a_creature(set_pool):
    """Combat damage is damage: blocking a 3/3 with the redirect aimed back at
    it, the attacker takes its own three and the Treefolk's two, and dies."""
    lea = _w1g8c_lea()
    treefolk_card = set_pool("PLS")["Mirrorwood Treefolk"]
    game, mine, theirs = _w1g8c_duel(
        [treefolk_card], [lea["Hill Giant"]], active=1,
    )
    treefolk, giant = mine[0], theirs[0]
    _w1g8c_arm(game, target_permanent_ids=[giant.permanent_id])

    _w1g8c_fight(game, 0, {0: 0}, defender=0)

    assert treefolk.damage_marked == 0
    assert game.is_on_battlefield(treefolk)
    assert not game.is_on_battlefield(giant)


def test_w1g8_mirrorwood_redirect_is_still_dealt_by_its_source(set_pool):
    """CR 614.9 moves the damage; it does not prevent it and deal other damage.
    A lifelink attacker's redirected damage is still that attacker's, so its
    controller gains the life (CR 120.3f) while the Treefolk's controller,
    who took it instead, loses it."""
    treefolk_card = set_pool("PLS")["Mirrorwood Treefolk"]
    lifelinker = _w1g8c_body("Lifelinker", 2, 2, "Lifelink", ("Lifelink",))
    game, mine, _ = _w1g8c_duel([treefolk_card], [lifelinker], active=1)
    _w1g8c_arm(game, target_player_index=0)

    _w1g8c_fight(game, 0, {0: 0}, defender=0)

    assert mine[0].damage_marked == 0
    assert [player.life for player in game.players] == [18, 22]


def test_w1g8_mirrorwood_redirect_does_nothing_once_its_taker_is_gone(set_pool):
    """CR 614.9: if the new recipient is no longer there when the damage would
    be dealt, the effect does nothing — the damage lands on the Treefolk as
    though the ability had never been activated."""
    lea = _w1g8c_lea()
    treefolk_card = set_pool("PLS")["Mirrorwood Treefolk"]
    game, mine, theirs = _w1g8c_duel(
        [treefolk_card], [lea["Grizzly Bears"]],
        hand1=[lea["Lightning Bolt"]], active=1,
    )
    treefolk, bears = mine[0], theirs[0]
    _w1g8c_arm(game, target_permanent_ids=[bears.permanent_id])
    game.remove_from_battlefield(bears)

    game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[treefolk.permanent_id]
    )
    _w1g8c_resolve_stack(game)

    assert treefolk.damage_marked == 3


def test_w1g8_mirrorwood_redirects_stack_and_end_with_the_turn(set_pool):
    """Two activations are two instances, each spent by one event; and an
    unspent one is gone at cleanup ("this turn")."""
    treefolk_card = set_pool("PLS")["Mirrorwood Treefolk"]
    game, mine, _ = _w1g8c_duel([treefolk_card], [])
    treefolk = mine[0]
    _w1g8c_arm(game, target_player_index=1)
    _w1g8c_arm(game, target_player_index=1)

    # the helper runs the event's first half only and spends what applies
    assert _w1g8c_dealt(game, treefolk, 2) == 0
    assert _w1g8c_dealt(game, treefolk, 2) == 0
    assert _w1g8c_dealt(game, treefolk, 2) == 2

    _w1g8c_arm(game, target_player_index=1)
    game.resolve_cleanup_step(0)
    assert _w1g8c_dealt(game, treefolk, 2) == 2


def test_w1g8_an_unsourced_instance_redirect_reads_its_whole_sentence():
    """The lowering's refusals. A narrowed taker is carried and re-checked; a
    blanket over the ability's own source, a taker nobody chose and a missing
    duration are each a wider card and refuse."""
    narrowed = _w1g8c_compile_line(
        "{1}: The next time damage would be dealt to this creature this turn, "
        "that damage is dealt to target creature you control instead.",
        card_name="Probe",
    )
    (instruction,) = narrowed.instructions
    assert instruction.kind == "redirect_next_damage_from_source_until_eot"
    assert instruction.payload["uses"] == 1
    assert instruction.payload["targets"]["filter"]["controller"] == "you"

    for text in (
        # no chosen taker: "you" is not a target this instruction resolves
        "{1}: The next time damage would be dealt to this creature this turn, "
        "that damage is dealt to you instead.",
        # no duration: a record the cleanup sweep would end a turn early
        "{1}: The next time damage would be dealt to this creature, that "
        "damage is dealt to any target instead.",
    ):
        refused = _w1g8c_compile_line(text, card_name="Probe")
        assert refused.parse_error or refused.lowering_error, text
        assert not refused.instructions, text
