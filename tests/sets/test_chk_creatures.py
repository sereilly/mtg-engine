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


@_w1g2_pytest.mark.parametrize("interactive, pick_curtain", [
    ((), False), ((0,), False), ((0,), True),
])
def test_w1g2_pale_curtain_contends_with_firestorm_phoenix(set_pool, interactive, pick_curtain):
    """Two replacements for one death (CR 616.1): Firestorm Phoenix's "return
    it to its owner's hand instead" and the Samurai's exile. A seat nobody
    asks applies the Phoenix's first — the order its controller would choose,
    and after it nothing is going to a graveyard — and a person is asked
    (``effect_order``) and may name either."""
    game = _w1g2_table(set_pool, interactive=interactive,
                       hands=((), [set_pool("LEA")["Terror"]]))
    _w1g2_put(game, set_pool("CHK")["Samurai of the Pale Curtain"], 0)
    phoenix = _w1g2_put(game, set_pool("LEG")["Firestorm Phoenix"], 0)
    game.active_player_index = game.priority_player_index = 1
    assert game.cast_from_hand(
        1, "Terror", target_permanent_ids=[phoenix.permanent_id]
    ).supported
    if interactive:
        owed = _w1g2_settle(game, defaults=False)
        assert owed is not None and owed.kind == "effect_order", owed
        options = owed.data["options"]
        wanted = next(
            index for index, label in enumerate(options)
            if ("Exile this permanent" in label) == pick_curtain
        )
        assert game.resolve_pending_choice("effect_order", 0, option_index=wanted)
    _w1g2_settle(game)
    names = lambda zone: [c.name for c in zone]  # noqa: E731
    if pick_curtain:
        assert names(game.players[0].exile) == ["Firestorm Phoenix"]
    else:
        assert names(game.players[0].hand) == ["Firestorm Phoenix"]
        assert names(game.players[0].exile) == []
    assert "Firestorm Phoenix" not in names(game.players[0].graveyard)

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.
#
# "Whenever you cast a Spirit or Arcane spell, <effect>" — the cast trigger
# narrowed by a union of a creature type (Spirit, CR 205.3m) and a spell type
# (Arcane, CR 205.3k) — and every effect the set hangs on it; Kitsune
# Riftwalker's "Protection from Spirits and from Arcane". Thief of Hope's
# trigger is driven on an invented one-line card: its soulshift line is W1G3's.
import pytest as _w1g4_pytest

from engine import Game as _W1G4Game
from engine.models import CardDefinition as _W1G4Card
from engine.models import Permanent as _W1G4Permanent
from engine.models import PlayerState as _W1G4PlayerState
from tests.helpers import settle as _w1g4_settle


def _w1g4_put(game, seat, card):
    permanent = _W1G4Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g4_table(set_pool, *, hand=(), mine=(), theirs=(), opponent_hand=(),
                interactive=False):
    """A two-seat game on Alice's first main phase, Alice's permanents
    *mine*, Bob's *theirs*, mana costs off."""
    lea = set_pool("LEA")
    game = _W1G4Game(players=[
        _W1G4PlayerState(name="Alice", hand=list(hand), library=[lea["Island"]] * 10),
        _W1G4PlayerState(name="Bob", hand=list(opponent_hand),
                         library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    placed = (
        [_w1g4_put(game, 0, card) for card in mine],
        [_w1g4_put(game, 1, card) for card in theirs],
    )
    game.start_turn(0)
    _w1g4_settle(game)
    return game, placed[0], placed[1]


def _w1g4_cast(game, seat, name, **announced):
    assert game.queue_from_hand(seat, name, **announced).supported, game.log[-5:]


def _w1g4_target(permanent):
    """An answer to a ``trigger_target`` prompt naming *permanent*."""
    return lambda game, choice: game.confirm_trigger_target(
        choice.player_index, permanent_id=permanent.permanent_id,
    )


def _w1g4_may(accept):
    return lambda game, choice: game.confirm_optional_pay(choice.player_index, accept=accept)


def _w1g4_arcane(set_pool):
    """Reach Through Mists — {U} Instant — Arcane, "Draw a card."."""
    return set_pool("CHK")["Reach Through Mists"]


@_w1g4_pytest.mark.parametrize("spell, seat, grows", [
    (("CHK", "Reach Through Mists"), 0, True),     # an Arcane instant
    (("CHK", "Kami of the Hunt"), 0, True),        # a Spirit creature spell
    (("LGN", "Mistform Ultimus"), 0, True),        # every creature type (CR 604.3)
    (("LEA", "Grizzly Bears"), 0, False),          # a Bear spell is neither
    (("LEA", "Giant Growth"), 0, False),           # an instant that is not Arcane
    (("CHK", "Reach Through Mists"), 1, False),    # an opponent's Arcane: not "you cast"
])
def test_w1g4_kami_of_the_hunt_grows_on_your_spirit_or_arcane_spells(
    set_pool, spell, seat, grows,
):
    """"Whenever you cast a Spirit or Arcane spell, this creature gets +1/+1
    until end of turn." One union over two subtype lists: a spell answers
    when it has either subtype, and Mistform Ultimus's CDA works on the
    stack."""
    code, name = spell
    game, (kami,), _ = _w1g4_table(set_pool, mine=[set_pool("CHK")["Kami of the Hunt"]])
    game.players[seat].hand.append(set_pool(code)[name])
    announced = {}
    if name == "Giant Growth":
        announced["target_permanent_ids"] = [kami.permanent_id]
    _w1g4_cast(game, seat, name, **announced)
    _w1g4_settle(game)
    bonus = 3 if name == "Giant Growth" else 0
    expected = (3 + bonus, 3 + bonus) if grows else (2 + bonus, 2 + bonus)
    assert (kami.effective_power, kami.effective_toughness) == expected, game.log


def test_w1g4_the_trigger_resolves_before_the_spell_that_fired_it(set_pool):
    """CR 603.3: the trigger goes on the stack above the Arcane spell, so the
    pump has happened while Reach Through Mists is still a spell."""
    game, (kami,), _ = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)],
        mine=[set_pool("CHK")["Kami of the Hunt"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    assert [item.card.name for item in game.stack] == [
        "Reach Through Mists", "Kami of the Hunt",
    ]
    game.resolve_top_of_stack()
    assert kami.effective_power == 3
    assert [item.card.name for item in game.stack] == ["Reach Through Mists"]


def test_w1g4_earthshaker_hits_every_creature_without_flying(set_pool):
    """"…deals 2 damage to each creature without flying": the Bears on both
    sides die, Earthshaker (4/5, no flying) is dealt 2 itself, and the Serra
    Angel is spared."""
    lea = set_pool("LEA")
    game, (shaker, angel, _bears), (their_bears,) = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)],
        mine=[set_pool("CHK")["Earthshaker"], lea["Serra Angel"], lea["Grizzly Bears"]],
        theirs=[lea["Grizzly Bears"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Earthshaker", "Serra Angel"]
    assert not list(game.controlled_by(1)), game.log
    assert shaker.damage_marked == 2 and angel.damage_marked == 0


def test_w1g4_guardian_of_solitude_gives_its_target_flying_for_the_turn(set_pool):
    """"…target creature gains flying until end of turn", the target chosen by
    an interactive seat as the trigger goes on the stack."""
    lea = set_pool("LEA")
    game, (_guardian, bears), _ = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Guardian of Solitude"], lea["Grizzly Bears"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={"trigger_target": _w1g4_target(bears)})
    assert game._has_keyword(bears, "flying"), game.log
    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    assert not game._has_keyword(bears, "flying")


def test_w1g4_horizon_seed_regenerates_its_target(set_pool):
    """"…regenerate target creature": the shield replaces the Bears'
    destruction by a Lightning Bolt's lethal damage (CR 701.19) and taps it."""
    lea = set_pool("LEA")
    game, (_seed, bears), _ = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool), lea["Lightning Bolt"]], interactive=True,
        mine=[set_pool("CHK")["Horizon Seed"], lea["Grizzly Bears"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={"trigger_target": _w1g4_target(bears)})
    assert bears.regeneration_shield == 1, game.log
    _w1g4_cast(game, 0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id])
    _w1g4_settle(game)
    assert game.is_on_battlefield(bears) and bears.tapped, game.log


def test_w1g4_innocence_kami_untaps_itself(set_pool):
    """"…untap this creature" — the {W}, {T} tapper used again the same turn."""
    game, (kami,), _ = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], mine=[set_pool("CHK")["Innocence Kami"]],
    )
    kami.tapped = True
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game)
    assert not kami.tapped, game.log


def test_w1g4_kami_of_fires_roar_stops_its_target_blocking(set_pool):
    """"…target creature can't block this turn": Bob's Bears can no longer
    block the Kami."""
    lea = set_pool("LEA")
    game, (kami,), (bears,) = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Kami of Fire's Roar"]], theirs=[lea["Grizzly Bears"]],
    )
    assert game._can_block_attacker(bears, kami)
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={"trigger_target": _w1g4_target(bears)})
    assert not game._can_block_attacker(bears, kami), game.log


def test_w1g4_kami_of_the_painted_road_takes_protection_from_the_chosen_colour(set_pool):
    """"…gains protection from the color of your choice until end of turn":
    an interactive seat names red, and Lightning Bolt can no longer target it."""
    from engine.legality import cast_spec_of

    lea = set_pool("LEA")
    game, (kami,), _ = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Kami of the Painted Road"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={
        "color_choice": lambda g, c: g.confirm_color_choice(c.player_index, "R"),
    })
    assert ("color", "R") in game._protection_qualities(kami), game.log
    bolt = lea["Lightning Bolt"]
    offered = game._enumerate_targets(1, bolt, cast_spec_of(bolt), for_cast=True)
    assert kami.permanent_id not in {
        getattr(game.permanent_at(o.get("seat"), o.get("index")), "permanent_id", None)
        for o in offered if o.get("kind") == "permanent"
    }


def test_w1g4_kami_of_the_waning_moon_gives_its_target_fear(set_pool):
    """"…target creature gains fear until end of turn": a green Bears can't
    block it, a black creature still can (CR 702.36b)."""
    lea = set_pool("LEA")
    game, (_moon, bears), (their_bears, knight) = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Kami of the Waning Moon"], lea["Grizzly Bears"]],
        theirs=[lea["Grizzly Bears"], lea["Black Knight"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={"trigger_target": _w1g4_target(bears)})
    assert not game._can_block_attacker(their_bears, bears), game.log
    assert game._can_block_attacker(knight, bears)


def test_w1g4_orbweaver_kumo_gains_forestwalk(set_pool):
    """"…this creature gains forestwalk until end of turn": unblockable while
    Bob controls a Forest."""
    lea = set_pool("LEA")
    game, (kumo,), (bears, _forest) = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)],
        mine=[set_pool("CHK")["Orbweaver Kumo"]],
        theirs=[lea["Grizzly Bears"], lea["Forest"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game)
    assert game._has_keyword(kumo, "forestwalk"), game.log
    assert not game._can_block_attacker(bears, kumo)


@_w1g4_pytest.mark.parametrize("accept", [True, False])
def test_w1g4_ore_gorger_may_destroy_a_nonbasic_land(set_pool, accept):
    """"…you may destroy target nonbasic land": the Tundra is the only target
    offered (the basic Forest is not), and declining the "may" spares it."""
    lea = set_pool("LEA")
    game, _, (tundra, forest) = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Ore Gorger"]], theirs=[lea["Tundra"], lea["Forest"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    prompt = _w1g4_settle(game, defaults=False)
    assert prompt.kind == "trigger_target"
    assert [t["permanent_id"] for t in prompt.data["targets"]] == [tundra.permanent_id]
    _w1g4_settle(game, answers={
        "trigger_target": _w1g4_target(tundra), "optional_pay": _w1g4_may(accept),
    })
    assert game.is_on_battlefield(tundra) is (not accept), game.log
    assert game.is_on_battlefield(forest)


@_w1g4_pytest.mark.parametrize("accept", [True, False])
def test_w1g4_sire_of_the_storm_may_draw(set_pool, accept):
    """"…you may draw a card" — besides the card Reach Through Mists draws."""
    game, _, _ = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Sire of the Storm"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={"optional_pay": _w1g4_may(accept)})
    assert len(game.players[0].hand) == (2 if accept else 1), game.log


def test_w1g4_soilshaper_animates_a_land_that_stays_a_land(set_pool):
    """"…target land becomes a 3/3 creature until end of turn. It's still a
    land." — and it is a land again, and only a land, after cleanup."""
    lea = set_pool("LEA")
    game, (_shaper, forest), _ = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Soilshaper"], lea["Forest"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={"trigger_target": _w1g4_target(forest)})
    assert forest.is_creature and forest.has_type("land"), game.log
    assert (forest.effective_power, forest.effective_toughness) == (3, 3)
    game.resolve_end_step(0)
    game.resolve_cleanup_step(0)
    assert not forest.is_creature and forest.has_type("land")


def test_w1g4_soul_of_magma_deals_one_damage_to_its_target(set_pool):
    """"…this creature deals 1 damage to target creature" — the interactive
    seat's choice among every creature, the Kami's own included."""
    lea = set_pool("LEA")
    game, _, (bears,) = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Soul of Magma"]], theirs=[lea["Grizzly Bears"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={"trigger_target": _w1g4_target(bears)})
    assert bears.damage_marked == 1, game.log


@_w1g4_pytest.mark.parametrize("start_tapped", [False, True])
def test_w1g4_teller_of_tales_taps_or_untaps_its_target(set_pool, start_tapped):
    """"…you may tap or untap target creature": an untapped Bears is tapped
    and a tapped one untapped (the other answer would change nothing)."""
    lea = set_pool("LEA")
    game, _, (bears,) = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Teller of Tales"]], theirs=[lea["Grizzly Bears"]],
    )
    bears.tapped = start_tapped
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={
        "trigger_target": _w1g4_target(bears), "optional_pay": _w1g4_may(True),
    })
    assert bears.tapped is (not start_tapped), game.log


def test_w1g4_thief_of_hopes_trigger_drains_its_target_opponent(set_pool):
    """Thief of Hope's first line on an invented card (its soulshift line is
    W1G3's): "…target opponent loses 1 life and you gain 1 life"."""
    thief = _W1G4Card(
        name="Invented Thief", mana_cost="{2}{B}", cmc=3.0,
        type_line="Creature — Spirit",
        oracle_text=(
            "Whenever you cast a Spirit or Arcane spell, target opponent "
            "loses 1 life and you gain 1 life."
        ),
        colors=("B",), color_identity=("B",), keywords=(), produced_mana=(),
        raw={"name": "Invented Thief", "type_line": "Creature — Spirit",
             "power": "2", "toughness": "2"},
    )
    game, _, _ = _w1g4_table(set_pool, hand=[_w1g4_arcane(set_pool)], mine=[thief])
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game)
    assert [p.life for p in game.players] == [21, 19], game.log


def test_w1g4_hikari_leaves_before_the_spell_and_comes_back_at_the_end_step(set_pool):
    """"…you may exile Hikari. If you do, return it … at the beginning of the
    next end step." The 2004-12-01 ruling: "it leaves the battlefield before
    the spell that triggered it resolves its ability, so it will be unaffected
    by that spell" — a Kodama's Might aimed at it has no target left, and the
    Hikari that returns is a new object (CR 400.7), a plain 4/4."""
    chk = set_pool("CHK")
    game, (hikari,), _ = _w1g4_table(
        set_pool, hand=[chk["Kodama's Might"]],
        mine=[chk["Hikari, Twilight Guardian"]],
    )
    _w1g4_cast(game, 0, "Kodama's Might", target_permanent_ids=[hikari.permanent_id])
    _w1g4_settle(game)
    assert not list(game.controlled_by(0))
    assert [c.name for c in game.players[0].exile] == ["Hikari, Twilight Guardian"]
    game.resolve_end_step(0)
    _w1g4_settle(game)
    (back,) = list(game.controlled_by(0))
    assert back.card.name == "Hikari, Twilight Guardian" and back is not hikari
    assert (back.effective_power, back.effective_toughness) == (4, 4), game.log
    assert not game.players[0].exile


def test_w1g4_hikari_may_stay(set_pool):
    """The 2004-12-01 ruling: "You may choose not to exile Hikari."."""
    game, (hikari,), _ = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)], interactive=True,
        mine=[set_pool("CHK")["Hikari, Twilight Guardian"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game, answers={"optional_pay": _w1g4_may(False)})
    assert game.is_on_battlefield(hikari) and not game.players[0].exile, game.log


def test_w1g4_kodama_of_the_south_tree_pumps_each_other_creature_you_control(set_pool):
    """"…each other creature you control gets +1/+1 and gains trample until
    end of turn" — not the Kodama, not Bob's creatures."""
    lea = set_pool("LEA")
    game, (kodama, bears), (their_bears,) = _w1g4_table(
        set_pool, hand=[_w1g4_arcane(set_pool)],
        mine=[set_pool("CHK")["Kodama of the South Tree"], lea["Grizzly Bears"]],
        theirs=[lea["Grizzly Bears"]],
    )
    _w1g4_cast(game, 0, "Reach Through Mists")
    _w1g4_settle(game)
    assert (bears.effective_power, bears.effective_toughness) == (3, 3), game.log
    assert game._has_keyword(bears, "trample")
    assert (kodama.effective_power, kodama.effective_toughness) == (4, 4)
    assert not game._has_keyword(kodama, "trample")
    assert (their_bears.effective_power, their_bears.effective_toughness) == (2, 2)
    assert not game._has_keyword(their_bears, "trample")


def test_w1g4_kitsune_riftwalker_has_protection_from_spirits_and_arcane(set_pool):
    """"Protection from Spirits and from Arcane" (CR 702.16): Rend Flesh, an
    Arcane instant, can't target it (it can target the Bears beside it), and a
    Spirit can't block it (CR 702.16f) while the Bears can."""
    from engine.legality import cast_spec_of

    chk, lea = set_pool("CHK"), set_pool("LEA")
    game, (fox, bears), (kami, their_bears) = _w1g4_table(
        set_pool, mine=[chk["Kitsune Riftwalker"], lea["Grizzly Bears"]],
        theirs=[chk["Kami of the Hunt"], lea["Grizzly Bears"]],
    )
    rend = chk["Rend Flesh"]
    offered = {
        getattr(game.permanent_at(o.get("seat"), o.get("index")), "permanent_id", None)
        for o in game._enumerate_targets(1, rend, cast_spec_of(rend), for_cast=True)
        if o.get("kind") == "permanent"
    }
    assert fox.permanent_id not in offered
    assert bears.permanent_id in offered
    assert not game._can_block_attacker(kami, fox)
    assert game._can_block_attacker(their_bears, fox)

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================
