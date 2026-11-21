"""Champions of Kamigawa creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("CHK")` / `set_cards("CHK")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g1 ==========================================================
# w1g1's tests go between this line and the "end w1g1" line.

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.
#
# Bushido (CR 702.45) on every printing, and the Samurai lines beside it:
# Konda's Hatamoto, Nagao, Takeno, Sensei Golden-Tail, Brothers Yamazaki and
# Samurai of the Pale Curtain. The keyword's rules (both halves, CR 702.45b's
# instances, the response window) are tests/rules/test_chk_w1g2_bushido.py.

import pytest as _w1g2_pytest

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.models import Permanent as _W1G2Permanent
from engine.oracle import compile_card_oracle as _w1g2_compile
from engine.targeting import derive_activation_spec as _w1g2_activation_spec
from tests.helpers import drive_combat as _w1g2_drive_combat
from tests.helpers import settle as _w1g2_settle


def _w1g2_table(set_pool, *, interactive=(), hands=((), ())):
    forest = set_pool("LEA")["Forest"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(
            name=f"P{seat}", library=[forest] * 20, hand=list(hands[seat]),
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    return game


def _w1g2_put(game, card, seat, *, sick=False):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    if not sick:
        permanent.metadata["summoning_sickness_turn"] = -99
    _w1g2_settle(game)
    return permanent


def _w1g2_pt(permanent):
    return (permanent.effective_power, permanent.effective_toughness)


def _w1g2_attack(game, seat, attackers, blocks=()):
    """*seat* attacks with *attackers* (permanents); the other seat declares
    *blocks*, ``(blocker, attacker)`` permanent pairs. Leaves the game in
    the declare blockers step with the block triggers on the stack."""
    defender = 1 - seat
    game.active_player_index = seat
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(
        seat, [game.battlefield_index_of(a) for a in attackers],
        defending_player_index=defender,
    )
    assert ok, why
    _w1g2_settle(game)
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers", game.current_step
    pairs = {
        game.battlefield_index_of(blocker): game.battlefield_index_of(attacker)
        for blocker, attacker in blocks
    }
    ok, why = game.declare_blockers(defender, pairs)
    assert ok, why


def _w1g2_bushido_lines(card):
    return [
        t for t in _w1g2_compile(card).triggered_abilities
        if t.source_line.startswith("bushido ")
    ]


@_w1g2_pytest.mark.parametrize("name, amount", [
    ("Devoted Retainer", 1), ("Kitsune Blademaster", 1),
    ("Samurai of the Pale Curtain", 1), ("Battle-Mad Ronin", 2),
    ("Cursed Ronin", 1), ("Konda's Hatamoto", 1), ("Mothrider Samurai", 1),
    ("Numai Outcast", 2), ("Ronin Houndmaster", 1), ("Samurai Enforcers", 2),
    ("Nezumi Ronin", 1), ("Brothers Yamazaki", 1),
    ("Konda, Lord of Eiganjo", 5), ("Nagao, Bound by Honor", 1),
    ("Takeno, Samurai General", 2), ("Sensei Golden-Tail", 1),
])
def test_w1g2_every_bushido_printing_blocks_bigger_by_its_n(set_pool, name, amount):
    """Each of the sixteen blocks an attacker that would otherwise be too
    big for it, and its bushido makes it +N/+N as the block's trigger
    resolves (CR 702.45a) — read off the board, not off the program."""
    card = set_pool("CHK")[name]
    assert _w1g2_compile(card).supported
    assert len(_w1g2_bushido_lines(card)) == 1
    game = _w1g2_table(set_pool)
    attacker = _w1g2_put(game, set_pool("LEA")["Craw Wurm"], 0)
    samurai = _w1g2_put(game, card, 1)
    before = _w1g2_pt(samurai)
    _w1g2_attack(game, 0, [attacker], [(samurai, attacker)])
    assert [item.ability_text for item in game.stack] == [f"bushido {amount}"]
    _w1g2_settle(game)
    assert _w1g2_pt(samurai) == (before[0] + amount, before[1] + amount)
    assert f"{name} gets +{amount}/+{amount} until end of turn" in game.log


def test_w1g2_devoted_retainer_trades_with_a_bear_it_blocks(set_pool):
    """A 1/1 that blocks a Grizzly Bears is a 2/2 by damage, so both die."""
    game = _w1g2_table(set_pool)
    bears = _w1g2_put(game, set_pool("LEA")["Grizzly Bears"], 0)
    retainer = _w1g2_put(game, set_pool("CHK")["Devoted Retainer"], 1)
    _w1g2_attack(game, 0, [bears], [(retainer, bears)])
    _w1g2_drive_combat(game)
    assert "Grizzly Bears" in [c.name for c in game.players[0].graveyard]
    assert "Devoted Retainer" in [c.name for c in game.players[1].graveyard]


def test_w1g2_samurai_enforcers_bushido_fires_when_it_becomes_blocked(set_pool):
    """The other half of CR 702.45a: the attacker is the one blocked, and a
    4/4 blocked by a Shivan Dragon is a 6/6 by damage — it survives and the
    5/5 dies."""
    game = _w1g2_table(set_pool)
    enforcers = _w1g2_put(game, set_pool("CHK")["Samurai Enforcers"], 0)
    dragon = _w1g2_put(game, set_pool("LEA")["Shivan Dragon"], 1)
    _w1g2_attack(game, 0, [enforcers], [(dragon, enforcers)])
    assert "Samurai Enforcers triggered on becoming blocked (added to stack)" in game.log
    _w1g2_settle(game)
    assert _w1g2_pt(enforcers) == (6, 6)
    _w1g2_drive_combat(game)
    assert game.is_on_battlefield(enforcers)
    assert "Shivan Dragon" in [c.name for c in game.players[1].graveyard]


def test_w1g2_an_unblocked_samurai_gets_no_bushido(set_pool):
    """Neither half happens: nothing blocks, nothing triggers, and the
    Nezumi Ronin deals its printed 3."""
    game = _w1g2_table(set_pool)
    ronin = _w1g2_put(game, set_pool("CHK")["Nezumi Ronin"], 0)
    _w1g2_attack(game, 0, [ronin], [])
    assert not game.stack
    _w1g2_drive_combat(game)
    assert game.players[1].life == 17


def test_w1g2_kitsune_blademaster_strikes_first_with_its_bushido(set_pool):
    """First strike and bushido 1: the trigger resolves in the declare
    blockers step, before any damage, so the 3/3 first striker kills a Hill
    Giant before it can deal damage back."""
    game = _w1g2_table(set_pool)
    giant = _w1g2_put(game, set_pool("LEA")["Hill Giant"], 0)
    blademaster = _w1g2_put(game, set_pool("CHK")["Kitsune Blademaster"], 1)
    _w1g2_attack(game, 0, [giant], [(blademaster, giant)])
    _w1g2_drive_combat(game)
    assert game.is_on_battlefield(blademaster)
    assert blademaster.metadata.get("damage", 0) == 0
    assert "Hill Giant" in [c.name for c in game.players[0].graveyard]


def test_w1g2_battle_mad_ronin_must_attack_and_trades_up(set_pool):
    """"This creature attacks each combat if able": a declaration leaving it
    home is refused. Blocked by a Hill Giant it is a 3/3, and they trade."""
    game = _w1g2_table(set_pool)
    ronin = _w1g2_put(game, set_pool("CHK")["Battle-Mad Ronin"], 0)
    giant = _w1g2_put(game, set_pool("LEA")["Hill Giant"], 1)
    game._set_phase_and_step("combat", "declare_attackers")
    ok, _why = game.declare_attackers(0, [], defending_player_index=1)
    assert not ok
    ok, why = game.declare_attackers(
        0, [game.battlefield_index_of(ronin)], defending_player_index=1
    )
    assert ok, why
    game.advance_combat_phase()
    assert game.declare_blockers(
        1, {game.battlefield_index_of(giant): game.battlefield_index_of(ronin)}
    )[0]
    _w1g2_drive_combat(game)
    assert "Battle-Mad Ronin" in [c.name for c in game.players[0].graveyard]
    assert "Hill Giant" in [c.name for c in game.players[1].graveyard]


def test_w1g2_cursed_ronin_pumps_on_top_of_its_bushido(set_pool):
    """"{B}: This creature gets +1/+1 until end of turn" stacks with the
    bushido trigger: two activations and a block make a 1/1 a 4/4."""
    game = _w1g2_table(set_pool)
    giant = _w1g2_put(game, set_pool("LEA")["Hill Giant"], 0)
    ronin = _w1g2_put(game, set_pool("CHK")["Cursed Ronin"], 1)
    _w1g2_attack(game, 0, [giant], [(ronin, giant)])
    _w1g2_settle(game)
    for _ in range(2):
        result = game.activate_permanent_ability(
            1, "Cursed Ronin", permanent_index=game.battlefield_index_of(ronin)
        )
        assert result.supported, result
        _w1g2_settle(game)
    assert _w1g2_pt(ronin) == (4, 4)
    _w1g2_drive_combat(game)
    assert game.is_on_battlefield(ronin)
    assert "Hill Giant" in [c.name for c in game.players[0].graveyard]


def test_w1g2_numai_outcast_regenerates_for_five_life(set_pool):
    """"{B}, Pay 5 life: Regenerate this creature." The shield is paid for
    in life, and a Craw Wurm's 6 damage to the 3/3 bushido Outcast is
    regenerated away: tapped, removed from combat, alive, 15 life."""
    game = _w1g2_table(set_pool)
    wurm = _w1g2_put(game, set_pool("LEA")["Craw Wurm"], 0)
    outcast = _w1g2_put(game, set_pool("CHK")["Numai Outcast"], 1)
    _w1g2_attack(game, 0, [wurm], [(outcast, wurm)])
    _w1g2_settle(game)
    assert _w1g2_pt(outcast) == (3, 3)
    result = game.activate_permanent_ability(
        1, "Numai Outcast", permanent_index=game.battlefield_index_of(outcast)
    )
    assert result.supported, result
    _w1g2_settle(game)
    assert game.players[1].life == 15
    _w1g2_drive_combat(game)
    assert game.is_on_battlefield(outcast)
    assert outcast.tapped


def test_w1g2_ronin_houndmaster_attacks_the_turn_it_arrives(set_pool):
    """Haste: a summoning-sick Houndmaster may still be declared."""
    game = _w1g2_table(set_pool)
    hound = _w1g2_put(game, set_pool("CHK")["Ronin Houndmaster"], 0, sick=True)
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(
        0, [game.battlefield_index_of(hound)], defending_player_index=1
    )
    assert ok, why


def test_w1g2_mothrider_samurai_flies_over_a_ground_blocker(set_pool):
    """Flying beside bushido: a Grizzly Bears cannot block it."""
    game = _w1g2_table(set_pool)
    moth = _w1g2_put(game, set_pool("CHK")["Mothrider Samurai"], 0)
    bears = _w1g2_put(game, set_pool("LEA")["Grizzly Bears"], 1)
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(
        0, [game.battlefield_index_of(moth)], defending_player_index=1
    )[0]
    game.advance_combat_phase()
    ok, _why = game.declare_blockers(
        1, {game.battlefield_index_of(bears): game.battlefield_index_of(moth)}
    )
    assert not ok


def test_w1g2_konda_lord_of_eiganjo_is_indestructible_and_huge_blocking(set_pool):
    """Vigilance, indestructible, bushido 5: a blocked Konda is an 8/8 that
    no damage destroys, and it attacks without tapping."""
    game = _w1g2_table(set_pool)
    konda = _w1g2_put(game, set_pool("CHK")["Konda, Lord of Eiganjo"], 0)
    wurm = _w1g2_put(game, set_pool("LEA")["Craw Wurm"], 1)
    _w1g2_attack(game, 0, [konda], [(wurm, konda)])
    assert not konda.tapped
    _w1g2_settle(game)
    assert _w1g2_pt(konda) == (8, 8)
    _w1g2_drive_combat(game)
    assert game.is_on_battlefield(konda)
    assert "Craw Wurm" in [c.name for c in game.players[1].graveyard]


def test_w1g2_kondas_hatamoto_needs_a_legendary_samurai_of_its_own(set_pool):
    """"As long as you control a legendary Samurai, this creature gets +1/+2
    and has vigilance." Alone it is a 1/2; an opponent's Nagao changes
    nothing; a Nagao of its own makes it a 2/4 with vigilance; a nonlegendary
    Samurai (Devoted Retainer) is not enough."""
    pool = set_pool("CHK")
    game = _w1g2_table(set_pool)
    hatamoto = _w1g2_put(game, pool["Konda's Hatamoto"], 0)
    assert _w1g2_pt(hatamoto) == (1, 2) and not hatamoto.has_keyword("vigilance")
    _w1g2_put(game, pool["Devoted Retainer"], 0)
    _w1g2_put(game, pool["Nagao, Bound by Honor"], 1)
    assert _w1g2_pt(hatamoto) == (1, 2) and not hatamoto.has_keyword("vigilance")
    nagao = _w1g2_put(game, pool["Nagao, Bound by Honor"], 0)
    assert _w1g2_pt(hatamoto) == (2, 4) and hatamoto.has_keyword("vigilance")
    game.remove_from_battlefield(nagao)
    game._permanent_to_graveyard(game.players[0], nagao)
    _w1g2_settle(game)
    assert _w1g2_pt(hatamoto) == (1, 2)


def test_w1g2_nagao_pumps_its_controllers_samurai_when_it_attacks(set_pool):
    """"Whenever Nagao attacks, Samurai creatures you control get +1/+1 until
    end of turn." Its own Samurai (itself and a Devoted Retainer at home) get
    it; a Grizzly Bears beside them and the opponent's Nezumi Ronin do not;
    it is gone after the turn."""
    pool = set_pool("CHK")
    game = _w1g2_table(set_pool)
    nagao = _w1g2_put(game, pool["Nagao, Bound by Honor"], 0)
    retainer = _w1g2_put(game, pool["Devoted Retainer"], 0)
    bears = _w1g2_put(game, set_pool("LEA")["Grizzly Bears"], 0)
    theirs = _w1g2_put(game, pool["Nezumi Ronin"], 1)
    _w1g2_attack(game, 0, [nagao], [])
    _w1g2_settle(game)
    assert _w1g2_pt(nagao) == (4, 4)
    assert _w1g2_pt(retainer) == (2, 2)
    assert _w1g2_pt(bears) == (2, 2)
    assert _w1g2_pt(theirs) == (3, 1)
    _w1g2_drive_combat(game)
    assert game.resolve_cleanup_step(0)
    assert _w1g2_pt(nagao) == (3, 3) and _w1g2_pt(retainer) == (1, 1)


def test_w1g2_takeno_counts_each_other_samurais_bushido(set_pool):
    """"Each other Samurai creature you control gets +1/+1 for each point of
    bushido it has." Samurai Enforcers (bushido 2) +2/+2, Devoted Retainer
    (bushido 1) +1/+1; Takeno itself, a non-Samurai, and an opponent's
    Samurai get nothing. Takeno leaving takes it all back."""
    pool = set_pool("CHK")
    game = _w1g2_table(set_pool)
    takeno = _w1g2_put(game, pool["Takeno, Samurai General"], 0)
    enforcers = _w1g2_put(game, pool["Samurai Enforcers"], 0)
    retainer = _w1g2_put(game, pool["Devoted Retainer"], 0)
    bears = _w1g2_put(game, set_pool("LEA")["Grizzly Bears"], 0)
    theirs = _w1g2_put(game, pool["Nezumi Ronin"], 1)
    assert _w1g2_pt(takeno) == (3, 3)
    assert _w1g2_pt(enforcers) == (6, 6)
    assert _w1g2_pt(retainer) == (2, 2)
    assert _w1g2_pt(bears) == (2, 2)
    assert _w1g2_pt(theirs) == (3, 1)
    game.remove_from_battlefield(takeno)
    game._permanent_to_graveyard(game.players[0], takeno)
    _w1g2_settle(game)
    assert _w1g2_pt(enforcers) == (4, 4) and _w1g2_pt(retainer) == (1, 1)


def test_w1g2_sensei_golden_tail_trains_a_creature_for_good(set_pool):
    """"Put a training counter on target creature. That creature gains
    bushido 1 and becomes a Samurai in addition to its other creature types.
    Activate only as a sorcery." The picker offers a creature; the Bears gets
    the counter, the keyword (it triggers when it blocks) and the Samurai
    type while staying a Bear — and keeps all of it turns later, because the
    grant has no duration."""
    pool = set_pool("CHK")
    game = _w1g2_table(set_pool)
    sensei = _w1g2_put(game, pool["Sensei Golden-Tail"], 0)
    bears = _w1g2_put(game, set_pool("LEA")["Grizzly Bears"], 0)
    ability = _w1g2_compile(sensei.effective_card).activated_abilities[0]
    assert _w1g2_activation_spec(ability) == {"kind": "creature"}
    result = game.activate_permanent_ability(
        0, "Sensei Golden-Tail", target_permanent_ids=[bears.permanent_id]
    )
    assert result.supported, result
    _w1g2_settle(game)
    assert bears.metadata.get("training_counters") == 1
    assert bears.has_keyword("bushido")
    assert bears.has_type("samurai") and bears.has_type("bear")
    for seat in (1, 0, 1):
        game.start_turn(seat)
        _w1g2_settle(game)
    assert bears.has_keyword("bushido") and bears.has_type("samurai")
    giant = _w1g2_put(game, set_pool("LEA")["Hill Giant"], 1)
    _w1g2_attack(game, 1, [giant], [(bears, giant)])
    assert [item.ability_text for item in game.stack] == ["bushido 1"]
    _w1g2_settle(game)
    assert _w1g2_pt(bears) == (3, 3)


def test_w1g2_sensei_golden_tail_activates_only_as_a_sorcery(set_pool):
    """In combat the activation is refused and nothing is trained."""
    pool = set_pool("CHK")
    game = _w1g2_table(set_pool)
    _w1g2_put(game, pool["Sensei Golden-Tail"], 0)
    bears = _w1g2_put(game, set_pool("LEA")["Grizzly Bears"], 0)
    game._set_phase_and_step("combat", "declare_attackers")
    result = game.activate_permanent_ability(
        0, "Sensei Golden-Tail", target_permanent_ids=[bears.permanent_id]
    )
    assert not result.supported
    _w1g2_settle(game)
    assert not bears.has_keyword("bushido")


def test_w1g2_sensei_training_a_samurai_stacks_a_second_bushido(set_pool):
    """Trained, a Devoted Retainer has two instances of bushido 1: Takeno
    counts both (+2/+2), and its block puts two triggers on the stack
    (CR 702.45b), a 3/3 becoming a 5/5."""
    pool = set_pool("CHK")
    game = _w1g2_table(set_pool)
    _w1g2_put(game, pool["Sensei Golden-Tail"], 0)
    retainer = _w1g2_put(game, pool["Devoted Retainer"], 0)
    _w1g2_put(game, pool["Takeno, Samurai General"], 0)
    game.activate_permanent_ability(
        0, "Sensei Golden-Tail", target_permanent_ids=[retainer.permanent_id]
    )
    _w1g2_settle(game)
    assert _w1g2_pt(retainer) == (3, 3)
    game.start_turn(1)
    _w1g2_settle(game)
    giant = _w1g2_put(game, set_pool("LEA")["Hill Giant"], 1)
    _w1g2_attack(game, 1, [giant], [(retainer, giant)])
    assert [item.ability_text for item in game.stack] == ["bushido 1", "bushido 1"]
    _w1g2_settle(game)
    assert _w1g2_pt(retainer) == (5, 5)


def test_w1g2_brothers_yamazaki_two_survive_and_pump_each_other(set_pool):
    """Exactly two on the battlefield: the legend rule does not apply, and
    each is the other's "other creature named Brothers Yamazaki" — 4/3 with
    haste. A third brings the rule back, and its controller keeps one (the
    card's 2013-07-01 ruling); the one left is a bare 2/1."""
    brothers = set_pool("CHK")["Brothers Yamazaki"]
    game = _w1g2_table(set_pool)
    first = _w1g2_put(game, brothers, 0, sick=True)
    second = _w1g2_put(game, brothers, 0, sick=True)
    game.check_state_based_actions()
    _w1g2_settle(game)
    assert game.is_on_battlefield(first) and game.is_on_battlefield(second)
    assert _w1g2_pt(first) == (4, 3) and first.has_keyword("haste")
    assert _w1g2_pt(second) == (4, 3) and second.has_keyword("haste")
    _w1g2_put(game, brothers, 0)
    game.check_state_based_actions()
    _w1g2_settle(game)
    left = list(game.controlled_by(0))
    assert len(left) == 1
    assert _w1g2_pt(left[0]) == (2, 1) and not left[0].has_keyword("haste")
    assert [c.name for c in game.players[0].graveyard].count("Brothers Yamazaki") == 2


def test_w1g2_brothers_yamazaki_under_two_controllers_pump_each_other(set_pool):
    """"The two Brothers could be controlled by different players" (the
    card's 2004-12-01 ruling): the static counts the whole battlefield, and
    each buffs the other across the table."""
    brothers = set_pool("CHK")["Brothers Yamazaki"]
    game = _w1g2_table(set_pool)
    mine = _w1g2_put(game, brothers, 0)
    theirs = _w1g2_put(game, brothers, 1)
    assert _w1g2_pt(mine) == (4, 3) and _w1g2_pt(theirs) == (4, 3)


def test_w1g2_a_third_brothers_asks_its_controller_which_to_keep(set_pool):
    """At a table a person sits at, the third Brothers arms CR 704.5j's
    prompt over all three; the answer keeps the one named."""
    brothers = set_pool("CHK")["Brothers Yamazaki"]
    game = _w1g2_table(set_pool, interactive=(0,))
    _w1g2_put(game, brothers, 0)
    _w1g2_put(game, brothers, 0)
    game.check_state_based_actions()
    assert not game.pending_choices_of("legend_rule", 0)
    # Put down without settling: a settle would answer the prompt by default.
    third = _W1G2Permanent(card=brothers)
    game._put_permanent_onto_battlefield(0, third, None)
    game.check_state_based_actions()
    (choice,) = game.pending_choices_of("legend_rule", 0)
    assert len(choice.data["candidates"]) == 3
    assert game.resolve_pending_choice("legend_rule", 0, permanent_id=third.permanent_id)
    _w1g2_settle(game)
    assert list(game.controlled_by(0)) == [third]


def test_w1g2_two_brothers_do_not_exempt_another_legend(set_pool):
    """The exemption is the Brothers' name alone: two Nagaos beside two
    Brothers are still put down to one."""
    pool = set_pool("CHK")
    game = _w1g2_table(set_pool)
    for name in ("Brothers Yamazaki", "Brothers Yamazaki", "Nagao, Bound by Honor",
                 "Nagao, Bound by Honor"):
        _w1g2_put(game, pool[name], 0)
    game.check_state_based_actions()
    _w1g2_settle(game)
    names = sorted(p.card.name for p in game.controlled_by(0))
    assert names == ["Brothers Yamazaki", "Brothers Yamazaki", "Nagao, Bound by Honor"]


def test_w1g2_pale_curtain_exiles_a_destroyed_creature_with_no_dies_trigger(set_pool):
    """"If a permanent would be put into a graveyard, exile it instead."
    Onulet ("When Onulet dies, you gain 2 life") shattered with the Samurai
    out: exiled, so it never died and its controller gains nothing. The
    Shatter itself — a spell, not a permanent — goes to the graveyard."""
    game = _w1g2_table(set_pool, hands=([set_pool("2ED")["Shatter"]], ()))
    _w1g2_put(game, set_pool("CHK")["Samurai of the Pale Curtain"], 0)
    onulet = _w1g2_put(game, set_pool("ATQ")["Onulet"], 1)
    result = game.cast_from_hand(0, "Shatter", target_permanent_ids=[onulet.permanent_id])
    assert result.supported, result
    _w1g2_settle(game)
    assert [c.name for c in game.players[1].exile] == ["Onulet"]
    assert game.players[1].graveyard == []
    assert game.players[1].life == 20
    assert [c.name for c in game.players[0].graveyard] == ["Shatter"]


def test_w1g2_pale_curtain_exiles_itself_and_a_whole_wrath(set_pool):
    """The Samurai is a permanent too, and a Wrath of God's creatures leave
    together: every one, the Samurai included, is exiled."""
    game = _w1g2_table(set_pool, hands=([set_pool("LEA")["Wrath of God"]], ()))
    _w1g2_put(game, set_pool("LEA")["Grizzly Bears"], 0)
    _w1g2_put(game, set_pool("CHK")["Samurai of the Pale Curtain"], 0)
    _w1g2_put(game, set_pool("LEA")["Hill Giant"], 1)
    assert game.cast_from_hand(0, "Wrath of God").supported
    _w1g2_settle(game)
    assert sorted(c.name for c in game.players[0].exile) == [
        "Grizzly Bears", "Samurai of the Pale Curtain"]
    assert [c.name for c in game.players[1].exile] == ["Hill Giant"]
    assert [c.name for c in game.players[0].graveyard] == ["Wrath of God"]
    assert game.players[1].graveyard == []


def test_w1g2_pale_curtain_exiles_its_own_targeted_destruction(set_pool):
    """Terror on the Samurai itself: it is taken off the battlefield before
    the move, and its own replacement still sends it to exile."""
    game = _w1g2_table(set_pool, hands=((), [set_pool("LEA")["Terror"]]))
    samurai = _w1g2_put(game, set_pool("CHK")["Samurai of the Pale Curtain"], 0)
    game.active_player_index = game.priority_player_index = 1
    assert game.cast_from_hand(1, "Terror", target_permanent_ids=[samurai.permanent_id]).supported
    _w1g2_settle(game)
    assert [c.name for c in game.players[0].exile] == ["Samurai of the Pale Curtain"]
    assert game.players[0].graveyard == []


def test_w1g2_pale_curtain_reaches_lands_artifacts_and_tokens_not_discards(set_pool):
    """Every kind of permanent: a Stone Rained land and a Snake token killed
    in combat are exiled (the token never dies — no card for anyone's pile),
    while a discarded card is no permanent and is binned as usual."""
    lea = set_pool("LEA")
    game = _w1g2_table(set_pool, hands=([lea["Stone Rain"], lea["Grizzly Bears"]], ()))
    _w1g2_put(game, set_pool("CHK")["Samurai of the Pale Curtain"], 0)
    forest = _w1g2_put(game, lea["Forest"], 1)
    assert game.cast_from_hand(0, "Stone Rain", target_permanent_ids=[forest.permanent_id]).supported
    _w1g2_settle(game)
    assert [c.name for c in game.players[1].exile] == ["Forest"]
    _w1g2_put(game, set_pool("LEG")["Serpent Generator"], 0)
    assert game.activate_permanent_ability(0, "Serpent Generator").supported
    _w1g2_settle(game)
    (snake,) = [p for p in game.controlled_by(0) if p.metadata.get("is_token")]
    giant = _w1g2_put(game, lea["Hill Giant"], 1)
    _w1g2_attack(game, 1, [giant], [(snake, giant)])
    _w1g2_drive_combat(game)
    assert not game.is_on_battlefield(snake)
    assert "Snake Token was exiled instead of being put into a graveyard" in " ".join(game.log)
    game._discard_card(game.players[0], next(
        c for c in game.players[0].hand if c.name == "Grizzly Bears"))
    assert "Grizzly Bears" in [c.name for c in game.players[0].graveyard]

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================
