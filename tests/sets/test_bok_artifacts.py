"""Betrayers of Kamigawa artifacts.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("BOK")` / `set_cards("BOK")` — never a new
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


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.
#
# That Which Was Taken's counter-keyed static grant: "Each permanent with a
# divinity counter on it has indestructible" (``LordBuffFilter``'s
# ``with_named_counter``, asked of the named-counter store at every read).
from engine import Game as _W1G6Game, PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.named_counters import counters_on as _w1g6_counters_on
from tests.helpers import settle as _w1g6_settle


def _w1g6_put(game, seat, card):
    permanent = _W1G6Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return permanent


def _w1g6_table(set_pool, *, hand=(), mine=(), theirs=()):
    lea = set_pool("LEA")
    game = _W1G6Game(players=[
        _W1G6PlayerState(name="Alice", hand=list(hand), library=[lea["Island"]] * 10),
        _W1G6PlayerState(name="Bob", library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    placed = [_w1g6_put(game, 0, card) for card in mine]
    placed += [_w1g6_put(game, 1, card) for card in theirs]
    game.start_turn(0)
    _w1g6_settle(game)
    return game, placed


def test_w1g6_that_which_was_taken_shields_what_holds_a_divinity_counter(set_pool):
    """"{4}, {T}: Put a divinity counter on target permanent other than That
    Which Was Taken." then "Each permanent with a divinity counter on it has
    indestructible": an opponent's Hill Giant given a counter survives Terror;
    the Artifact itself is not a legal target; once That Which Was Taken is
    destroyed the counter stays but shields nothing (2013-07-01 ruling: "only
    while That Which Was Taken is on the battlefield"), and Terror kills."""
    lea = set_pool("LEA")
    bok = set_pool("BOK")
    game, (taken, giant) = _w1g6_table(
        set_pool, hand=[lea["Terror"], lea["Terror"], lea["Shatter"]],
        mine=[bok["That Which Was Taken"]], theirs=[lea["Hill Giant"]],
    )
    refused = game.activate_permanent_ability(
        0, "That Which Was Taken", target_permanent_ids=[taken.permanent_id],
    )
    assert not refused.supported
    assert game.activate_permanent_ability(
        0, "That Which Was Taken", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert _w1g6_counters_on(giant, "divinity") == 1 and taken.tapped
    assert giant.has_keyword("indestructible")
    assert not taken.has_keyword("indestructible")

    assert game.cast_from_hand(
        0, "Terror", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert giant in game.controlled_by(1), game.log

    assert game.cast_from_hand(
        0, "Shatter", target_permanent_ids=[taken.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert taken not in game.controlled_by(0)
    assert _w1g6_counters_on(giant, "divinity") == 1
    assert not giant.has_keyword("indestructible")
    assert game.cast_from_hand(
        0, "Terror", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert giant not in game.controlled_by(1), game.log


def test_w1g6_that_which_was_taken_loses_the_shield_with_the_counter(set_pool):
    """The set is re-derived from the board (CR 611.3a): a permanent whose
    divinity counter Spinal Parasite removes ("Remove a counter from target
    permanent") stops being indestructible."""
    lea = set_pool("LEA")
    bok = set_pool("BOK")
    game, (taken, bears) = _w1g6_table(
        set_pool, mine=[bok["That Which Was Taken"], lea["Grizzly Bears"]],
    )
    # A 0/0 with sunburst: placed with the two counters it removes.
    parasite = _W1G6Permanent(card=set_pool("5DN")["Spinal Parasite"])
    game._put_permanent_onto_battlefield(0, parasite, None)
    from engine.named_counters import add_counters as _w1g6_add_counters

    _w1g6_add_counters(parasite, "+1/+1", 2)
    parasite.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    assert game.activate_permanent_ability(
        0, "That Which Was Taken", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert bears.has_keyword("indestructible")
    assert game.activate_permanent_ability(
        0, "Spinal Parasite", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g6_settle(game)
    assert _w1g6_counters_on(bears, "divinity") == 0, game.log
    assert not bears.has_keyword("indestructible")

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

from engine import Game as _W1G7Game
from engine import PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import settle as _w1g7_settle


def _w1g7_table(set_pool, *, hand=(), opponent_hand=(), interactive=(), library=20):
    """Two seats on seat 0's first main phase, costs not enforced."""
    lea = set_pool("LEA")
    game = _W1G7Game(players=[
        _W1G7PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * library,
            hand=list(hand) if seat == 0 else list(opponent_hand),
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g7_settle(game)
    return game


def _w1g7_put(game, card, seat=0):
    permanent = _W1G7Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g7_named(game, name):
    return [perm for perm in game.all_permanents() if perm.card.name == name]


def test_w1g7_orb_of_dreams_taps_every_entering_permanent_but_itself(set_pool):
    """Permanents enter tapped. CR 614.12: the replacement comes from the Orb
    only for what is already on the battlefield — its example is Orb of
    Dreams entering untapped. Then a played land, a creature spell, the
    tokens a spell creates and an opponent's creature all enter tapped, and so
    does a second Orb (the first one's effect reaches it)."""
    bok, lea, chk = set_pool("BOK"), set_pool("LEA"), set_pool("CHK")
    game = _w1g7_table(
        set_pool,
        hand=[bok["Orb of Dreams"], lea["Forest"], lea["Grizzly Bears"], bok["Orb of Dreams"]],
    )
    assert game.cast_from_hand(0, "Orb of Dreams").supported
    _w1g7_settle(game)
    (orb,) = _w1g7_named(game, "Orb of Dreams")
    assert not orb.tapped
    assert game.cast_from_hand(0, "Forest").supported
    assert game.cast_from_hand(0, "Grizzly Bears").supported
    _w1g7_settle(game)
    assert _w1g7_named(game, "Forest")[0].tapped
    assert _w1g7_named(game, "Grizzly Bears")[0].tapped
    # A token is a permanent too, and so is the opponent's creature.
    _w1g7_put(game, chk["Kami of the Hunt"], seat=1)
    assert _w1g7_named(game, "Kami of the Hunt")[0].tapped
    assert game.cast_from_hand(0, "Orb of Dreams").supported
    _w1g7_settle(game)
    assert sorted(perm.tapped for perm in _w1g7_named(game, "Orb of Dreams")) == [False, True]


def test_w1g7_orb_of_dreams_taps_tokens(set_pool):
    """A token a spell creates enters tapped under the Orb (every road onto
    the battlefield passes the one entry seam)."""
    bok, mrd = set_pool("BOK"), set_pool("MRD")
    game = _w1g7_table(set_pool, hand=[mrd["Raise the Alarm"]])
    _w1g7_put(game, bok["Orb of Dreams"])
    assert game.cast_from_hand(0, "Raise the Alarm").supported
    _w1g7_settle(game)
    soldiers = _w1g7_named(game, "Soldier Token")
    assert len(soldiers) == 2 and all(perm.tapped for perm in soldiers)


def test_w1g7_mirror_gallery_switches_the_legend_rule_off_while_it_stays(set_pool):
    """The "legend rule" doesn't apply. Two Ishi-Ishi under one controller stay
    while the Gallery is on the battlefield, with nothing asked; the first
    state-based check after it leaves applies the rule again (its 2005-02-01
    ruling), and a seat nobody asks keeps one."""
    bok = set_pool("BOK")
    game = _w1g7_table(set_pool)
    gallery = _w1g7_put(game, bok["Mirror Gallery"])
    first = _w1g7_put(game, bok["Ishi-Ishi, Akki Crackshot"])
    second = _w1g7_put(game, bok["Ishi-Ishi, Akki Crackshot"])
    game.check_state_based_actions()
    _w1g7_settle(game)
    assert game.is_on_battlefield(first) and game.is_on_battlefield(second)
    assert not any("704.5j" in line for line in game.log)
    game.remove_from_battlefield(gallery)
    game._permanent_to_graveyard(game.players[0], gallery)
    game.check_state_based_actions()
    _w1g7_settle(game)
    assert len(_w1g7_named(game, "Ishi-Ishi, Akki Crackshot")) == 1
    assert "Ishi-Ishi, Akki Crackshot put into graveyard (704.5j: legend rule)" in game.log


def test_w1g7_mirror_gallery_withdraws_and_restores_a_persons_legend_rule_prompt(set_pool):
    """At a seat a person sits at the rule asks which to keep (CR 704.5j). A
    Gallery arriving while that prompt is owed drops it — the group is no
    group while the rule doesn't apply — and nothing leaves; when the Gallery
    goes the prompt is armed again and the answer is what stays."""
    bok = set_pool("BOK")
    game = _w1g7_table(set_pool, interactive=(0,))
    first = _w1g7_put(game, bok["Ishi-Ishi, Akki Crackshot"])
    second = _w1g7_put(game, bok["Ishi-Ishi, Akki Crackshot"])
    game.check_state_based_actions()
    owed = [c for c in game.pending_choices if c.kind == "legend_rule"]
    assert len(owed) == 1
    assert owed[0].data["candidates"] == [first.permanent_id, second.permanent_id]
    gallery = _w1g7_put(game, bok["Mirror Gallery"])
    game.check_state_based_actions()
    assert not [c for c in game.pending_choices if c.kind == "legend_rule"]
    assert game.is_on_battlefield(first) and game.is_on_battlefield(second)
    game.remove_from_battlefield(gallery)
    game._permanent_to_graveyard(game.players[0], gallery)
    game.check_state_based_actions()
    assert [c.kind for c in game.pending_choices] == ["legend_rule"]
    assert game.resolve_pending_choice("legend_rule", 0, permanent_id=second.permanent_id)
    assert game.is_on_battlefield(second) and not game.is_on_battlefield(first)


def test_w1g7_two_hokori_under_mirror_gallery_untap_two_lands(set_pool):
    """Hokori, Dust Drinker's 2005-02-01 ruling: "If there are two Hokori on
    the battlefield (for example, if Mirror Gallery is on the battlefield),
    each player untaps two lands they control at the beginning of their
    upkeep." Both legends stay under the Gallery, no land untaps in the untap
    step, and each Hokori's upkeep trigger untaps one."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g7_table(set_pool)
    _w1g7_put(game, bok["Mirror Gallery"])
    _w1g7_put(game, bok["Hokori, Dust Drinker"])
    _w1g7_put(game, bok["Hokori, Dust Drinker"])
    forests = [_w1g7_put(game, lea["Forest"]) for _ in range(3)]
    game.check_state_based_actions()
    _w1g7_settle(game)
    assert len(_w1g7_named(game, "Hokori, Dust Drinker")) == 2
    for forest in forests:
        forest.tapped = True
    game.resolve_cleanup_step(0)
    game.start_turn(1)
    _w1g7_settle(game)
    game.resolve_cleanup_step(1)
    game.start_turn(0)
    _w1g7_settle(game)
    assert sorted(forest.tapped for forest in forests) == [False, False, True]

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

from engine import Game as _w1g8_Game, PlayerState as _w1g8_PlayerState
from engine.models import Permanent as _w1g8_Permanent
from tests.helpers import (settle as _w1g8_settle,
                           stock_libraries as _w1g8_stock_libraries)


def _w1g8_artifact_table(*mine):
    game = _w1g8_Game(players=[
        _w1g8_PlayerState(name="P0"), _w1g8_PlayerState(name="P1"),
    ])
    _w1g8_stock_libraries(game)
    game.enforce_mana_costs = True
    placed = []
    for each in mine:
        permanent = _w1g8_Permanent(card=each)
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    game._sync_control()
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game, placed


def test_w1g8_baku_altar_trades_a_ki_counter_for_a_spirit_token(set_pool):
    """"Whenever you cast a Spirit or Arcane spell, you may put a ki counter on
    this artifact. / {2}, {T}, Remove a ki counter from this artifact: Create a
    1/1 colorless Spirit creature token." A Spirit cast, the counter taken;
    {2} paid, the counter gone, a 1/1 colourless Spirit; with no counter the
    ability is refused with nothing paid."""
    from engine.named_counters import counters_on

    bok = set_pool("BOK")
    game, (altar,) = _w1g8_artifact_table(bok["Baku Altar"])
    game.players[0].hand.append(bok["Petalmane Baku"])
    game.players[0].mana_pool["G"] = 2
    assert game.cast_from_hand(0, "Petalmane Baku").supported
    _w1g8_settle(game, answers={
        "optional_pay": lambda g, c: g.confirm_optional_pay(c.player_index, accept=True),
    })
    assert counters_on(altar, "ki") == 1
    game.players[0].mana_pool["C"] = 2
    made = game.activate_permanent_ability(0, "Baku Altar")
    _w1g8_settle(game)
    assert made.supported, made.details
    assert counters_on(altar, "ki") == 0 and altar.tapped
    (token,) = [p for p in game.controlled_by(0) if p.card.name == "Spirit Token"]
    assert (token.effective_power, token.effective_toughness) == (1, 1)
    assert token.has_type("creature") and not token.card.colors
    altar.tapped = False
    game.players[0].mana_pool["C"] = 2
    assert not game.activate_permanent_ability(0, "Baku Altar").supported
    assert game.players[0].mana_pool["C"] == 2


def test_w1g8_slumbering_tora_becomes_a_cat_the_size_of_the_discard(set_pool):
    """"{2}, Discard a Spirit or Arcane card: This artifact becomes an X/X Cat
    artifact creature until end of turn, where X is the discarded card's mana
    value." Skullmane Baku (mana value 5) discarded — never the Grizzly Bears
    beside it — makes a 5/5 Cat artifact creature, an artifact again at
    cleanup."""
    from engine.object_creature_types import creature_types

    bok, lea = set_pool("BOK"), set_pool("LEA")
    game, (tora,) = _w1g8_artifact_table(bok["Slumbering Tora"])
    game.players[0].hand.extend([bok["Skullmane Baku"], lea["Grizzly Bears"]])
    game.players[0].mana_pool["C"] = 2
    woke = game.activate_permanent_ability(0, "Slumbering Tora")
    _w1g8_settle(game)
    assert woke.supported, woke.details
    assert [c.name for c in game.players[0].hand] == ["Grizzly Bears"]
    assert [c.name for c in game.players[0].graveyard] == ["Skullmane Baku"]
    assert tora.is_creature and tora.has_type("artifact")
    assert (tora.effective_power, tora.effective_toughness) == (5, 5)
    assert creature_types(game, tora) == frozenset({"cat"})
    game.resolve_end_step(0)
    _w1g8_settle(game)
    game.resolve_cleanup_step(0)
    assert not tora.is_creature and tora.has_type("artifact")

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

from engine import Game as _W1G9Game, PlayerState as _W1G9PlayerState
from engine.models import Permanent as _W1G9Permanent
from engine.named_counters import add_counters as _w1g9_add_counters
from engine.named_counters import counters_on as _w1g9_counters_on
from tests.helpers import declare_attack as _w1g9_declare_attack
from tests.helpers import drive_combat as _w1g9_drive_combat
from tests.helpers import settle as _w1g9_settle


def _w1g9_card(set_pool, name):
    for code in ("BOK", "LEA", "LGN", "CHK", "5DN", "MRD"):
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(name)


def _w1g9_table(set_pool, *, hand=(), mine=(), theirs=(), their_hand=(), interactive=()):
    """Two seats on seat 0's first main phase, costs not enforced; *mine* /
    *theirs* placed and not summoning sick."""
    card = lambda name: _w1g9_card(set_pool, name)  # noqa: E731
    game = _W1G9Game(players=[
        _W1G9PlayerState(name="Alice", hand=[card(n) for n in hand],
                         library=[card("Forest")] * 12),
        _W1G9PlayerState(name="Bob", hand=[card(n) for n in their_hand],
                         library=[card("Forest")] * 12),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _W1G9Permanent(card=card(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed[seat].append(permanent)
    game._sync_control()
    game.start_turn(0)
    _w1g9_settle(game)
    return game, placed[0], placed[1]


def _w1g9_slot(game, permanent):
    seat = game.controller_index_of(permanent)
    return [p.permanent_id for p in game.players[seat].battlefield].index(
        permanent.permanent_id
    )


def _w1g9_activate(game, permanent, **announce):
    seat = game.controller_index_of(permanent)
    result = game.activate_permanent_ability(
        seat, permanent.card.name, permanent_index=_w1g9_slot(game, permanent),
        **announce,
    )
    _w1g9_settle(game)
    return result


def _w1g9_equip_index(permanent):
    """The equip ability's index among the Equipment's activated abilities —
    the CR 702.6a rewrite sits after every ability printed above it."""
    from engine.oracle import compile_card_oracle

    abilities = compile_card_oracle(permanent.card).activated_abilities
    return next(
        index for index, ability in enumerate(abilities)
        if ability.instruction is not None
        and ability.instruction.kind == "attach_source_to_target"
    )


def _w1g9_equip(game, equipment, creature):
    return _w1g9_activate(
        game, equipment, ability_index=_w1g9_equip_index(equipment),
        target_permanent_ids=[creature.permanent_id],
    )


# Umezawa's Jitte: "Whenever equipped creature deals combat damage, put two
# charge counters on Umezawa's Jitte." / "Remove a charge counter from
# Umezawa's Jitte: Choose one — • Equipped creature gets +2/+2 until end of
# turn. • Target creature gets -1/-1 until end of turn. • You gain 2 life."
# The modal head names the card in full in its cost; it is rewritten into one
# activated ability per bullet (ability indexes 0, 1, 2), the equip rewrite
# after them.


def test_w1g9_jitte_charges_once_per_combat_damage_step(set_pool):
    """Blocked by two Grizzly Bears, the Craw Wurm deals combat damage to both
    at once — one event, one trigger, two charge counters (CR 510.2). The
    Jitte charges even though the Wurm dies in the same damage step: the
    creature was equipped when it dealt the damage."""
    game, mine, theirs = _w1g9_table(
        set_pool, mine=["Umezawa's Jitte", "Craw Wurm"],
        theirs=["Grizzly Bears", "Grizzly Bears"],
    )
    jitte, wurm = mine
    assert _w1g9_equip(game, jitte, wurm).supported
    assert jitte.metadata.get("attached_to") is wurm
    _w1g9_declare_attack(game, 0, blocks={
        _w1g9_slot(game, blocker): _w1g9_slot(game, wurm) for blocker in theirs
    })
    _w1g9_drive_combat(game)
    assert _w1g9_counters_on(jitte, "charge") == 2
    assert [c.name for c in game.players[1].graveyard] == ["Grizzly Bears"] * 2


def test_w1g9_jitte_charges_in_each_damage_step_of_a_double_striker(set_pool):
    """Double strike deals combat damage in two steps (CR 702.4b): two
    triggers, four counters."""
    game, mine, _ = _w1g9_table(set_pool, mine=["Umezawa's Jitte", "Ridgetop Raptor"])
    jitte, raptor = mine
    assert _w1g9_equip(game, jitte, raptor).supported
    _w1g9_declare_attack(game, 0)
    _w1g9_drive_combat(game)
    assert game.players[1].life == 16
    assert _w1g9_counters_on(jitte, "charge") == 4


def test_w1g9_jitte_does_not_charge_without_combat_damage(set_pool):
    """No combat damage dealt, no counters, and every mode is refused with
    nothing to remove (CR 602.2b, 601.2h)."""
    game, mine, theirs = _w1g9_table(
        set_pool, mine=["Umezawa's Jitte", "Grizzly Bears"], theirs=["Grizzly Bears"],
    )
    jitte, bears = mine
    assert _w1g9_equip(game, jitte, bears).supported
    assert _w1g9_counters_on(jitte, "charge") == 0
    assert not _w1g9_activate(game, jitte, ability_index=2).supported
    assert not _w1g9_activate(game, jitte, ability_index=0).supported
    assert game.players[0].life == 20
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)


def test_w1g9_jitte_modes_each_remove_one_counter(set_pool):
    """Unblocked, the Bears charge the Jitte with two counters; a third is put
    on by hand. Each mode is its own activation removing one: -1/-1 on Bob's
    Hill Giant, two life, +2/+2 on the equipped Bears — and nothing left for a
    fourth."""
    game, mine, theirs = _w1g9_table(
        set_pool, mine=["Umezawa's Jitte", "Grizzly Bears"],
        theirs=["Grizzly Bears", "Hill Giant"],
    )
    jitte, bears = mine
    their_bears, giant = theirs
    assert _w1g9_equip(game, jitte, bears).supported
    _w1g9_declare_attack(game, 0)
    _w1g9_drive_combat(game)
    assert game.players[1].life == 18
    assert _w1g9_counters_on(jitte, "charge") == 2
    _w1g9_add_counters(jitte, "charge", 1)

    assert _w1g9_activate(
        game, jitte, ability_index=1, target_permanent_ids=[giant.permanent_id],
    ).supported
    assert (giant.effective_power, giant.effective_toughness) == (2, 2)
    assert _w1g9_counters_on(jitte, "charge") == 2
    assert _w1g9_activate(game, jitte, ability_index=2).supported
    assert game.players[0].life == 22
    assert _w1g9_counters_on(jitte, "charge") == 1
    assert _w1g9_activate(game, jitte, ability_index=0).supported
    assert (bears.effective_power, bears.effective_toughness) == (4, 4)
    assert (their_bears.effective_power, their_bears.effective_toughness) == (2, 2)
    assert _w1g9_counters_on(jitte, "charge") == 0
    assert not _w1g9_activate(
        game, jitte, ability_index=1, target_permanent_ids=[their_bears.permanent_id],
    ).supported
    assert (their_bears.effective_power, their_bears.effective_toughness) == (2, 2)


def test_w1g9_jitte_pump_reaches_the_last_equipped_creature_after_it_leaves(set_pool):
    """2005-02-01 ruling: "If the Jitte leaves the battlefield after the
    '+2/+2' mode is announced but before it resolves, the bonus is given to
    the creature that was most recently equipped." Shattered in response,
    the Jitte's pump still reaches the Bears (CR 608.2h)."""
    game, mine, _ = _w1g9_table(
        set_pool, hand=["Shatter"], mine=["Umezawa's Jitte", "Grizzly Bears"],
    )
    jitte, bears = mine
    assert _w1g9_equip(game, jitte, bears).supported
    _w1g9_add_counters(jitte, "charge", 1)
    assert game.queue_permanent_ability(
        0, jitte.card.name, permanent_index=_w1g9_slot(game, jitte), ability_index=0,
    ).supported
    assert _w1g9_counters_on(jitte, "charge") == 0
    assert game.queue_from_hand(
        0, "Shatter", target_permanent_ids=[jitte.permanent_id],
    ).supported
    _w1g9_settle(game)
    assert not game.is_on_battlefield(jitte)
    assert (bears.effective_power, bears.effective_toughness) == (4, 4)


def test_w1g9_unattached_jitte_pump_does_nothing(set_pool):
    """2005-02-01 ruling: "Choosing the 'Equipped creature gets +2/+2 until
    end of turn' mode does nothing if the Jitte isn't equipped to a creature
    when the ability resolves." The counter is still spent (it is the cost)."""
    game, mine, _ = _w1g9_table(set_pool, mine=["Umezawa's Jitte", "Grizzly Bears"])
    jitte, bears = mine
    _w1g9_add_counters(jitte, "charge", 1)
    _w1g9_activate(game, jitte, ability_index=0)
    assert _w1g9_counters_on(jitte, "charge") == 0
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)

# Ronin Warclub: "Equipped creature gets +2/+1." / "Whenever a creature you
# control enters, attach this Equipment to that creature." The host is the
# object the entry seam froze (``host_from: "event_subject"``).


def test_w1g9_ronin_warclub_moves_onto_each_creature_that_enters_under_you(set_pool):
    """The Warclub is on Alice's Llanowar Elves; Grizzly Bears enters and
    the trigger moves it (CR 701.3a: the Elves are 1/1 again, the Bears
    4/3). Bob's Bears entering does not trigger it ("you control")."""
    game, mine, _ = _w1g9_table(
        set_pool, hand=["Grizzly Bears"], their_hand=["Grizzly Bears"],
        mine=["Ronin Warclub", "Llanowar Elves"],
    )
    club, elves = mine
    # The Elves entered after the Warclub, so the trigger attached it already.
    assert club.metadata.get("attached_to") is elves
    assert (elves.effective_power, elves.effective_toughness) == (3, 2)
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    _w1g9_settle(game)
    bears = next(p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears")
    assert club.metadata.get("attached_to") is bears
    assert (bears.effective_power, bears.effective_toughness) == (4, 3)
    assert (elves.effective_power, elves.effective_toughness) == (1, 1)

    game.active_player_index = 1
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    _w1g9_settle(game)
    theirs = next(p for p in game.controlled_by(1) if p.card.name == "Grizzly Bears")
    assert club.metadata.get("attached_to") is bears
    assert (theirs.effective_power, theirs.effective_toughness) == (2, 2)


def test_w1g9_ronin_warclub_leaves_a_creature_that_cant_be_equipped_bare(set_pool):
    """2005-02-01 ruling: "The triggered ability won't attach Ronin Warclub
    to a creature that can't be equipped (such as Goblin Brawler)." It stays
    where it was."""
    game, mine, _ = _w1g9_table(
        set_pool, hand=["Goblin Brawler"], mine=["Ronin Warclub", "Grizzly Bears"],
    )
    club, bears = mine
    assert club.metadata.get("attached_to") is bears
    assert game.queue_from_hand(0, "Goblin Brawler").supported
    _w1g9_settle(game)
    brawler = next(p for p in game.controlled_by(0) if p.card.name == "Goblin Brawler")
    assert club.metadata.get("attached_to") is bears
    assert (brawler.effective_power, brawler.effective_toughness) == (2, 2)
    assert any("can't be equipped" in line for line in game.log)


def test_w1g9_ronin_warclub_attaches_nothing_when_the_creature_left_in_response(set_pool):
    """The trigger names the creature that entered, by id (CR 400.7). Killed
    in response — Lightning Bolt on the Elves with the trigger on the stack —
    there is nothing to attach to, and the Warclub stays unattached."""
    game, mine, _ = _w1g9_table(
        set_pool, hand=["Llanowar Elves", "Lightning Bolt"], mine=["Ronin Warclub"],
    )
    club = mine[0]
    assert club.metadata.get("attached_to") is None
    assert game.queue_from_hand(0, "Llanowar Elves").supported
    assert game.resolve_next_object(pause_for_choices=False)
    assert [item.ability_kind for item in game.stack] == ["triggered"]
    elves = next(p for p in game.controlled_by(0) if p.card.name == "Llanowar Elves")
    assert game.queue_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[elves.permanent_id],
    ).supported
    _w1g9_settle(game)
    assert not game.is_on_battlefield(elves)
    assert club.metadata.get("attached_to") is None
    assert game.is_on_battlefield(club)

# Neko-Te: "Whenever equipped creature deals damage to a creature, tap that
# creature. That creature doesn't untap during its controller's untap step for
# as long as this Equipment remains on the battlefield." / "Whenever equipped
# creature deals damage to a player, that player loses 1 life."


def test_w1g9_neko_te_taps_and_holds_the_creature_its_wearer_damaged(set_pool):
    """Blocked by Bob's Hill Giant, the equipped Craw Wurm deals it combat
    damage: the Giant survives (6 damage would kill it, so a War Mammoth is
    used — 3 damage to a 3/3 kills, so the Giant blocks a Grizzly Bears), is
    tapped, and stays tapped through Bob's untap step while Neko-Te remains.
    Shattered, Neko-Te releases it at the next untap step (CR 611.2a)."""
    game, mine, theirs = _w1g9_table(
        set_pool, hand=["Shatter"], mine=["Neko-Te", "Grizzly Bears"],
        theirs=["Hill Giant"],
    )
    neko, bears = mine
    giant = theirs[0]
    assert _w1g9_equip(game, neko, bears).supported
    _w1g9_declare_attack(game, 0, blocks={_w1g9_slot(game, giant): _w1g9_slot(game, bears)})
    _w1g9_drive_combat(game)
    assert game.is_on_battlefield(giant)
    assert giant.tapped
    assert "Hill Giant won't untap while Neko-Te remains on the battlefield" in game.log

    game.start_next_turn()
    _w1g9_settle(game)
    assert game.active_player_index == 1 and giant.tapped

    game.start_next_turn()
    _w1g9_settle(game)
    assert game.queue_from_hand(0, "Shatter", target_permanent_ids=[neko.permanent_id]).supported
    _w1g9_settle(game)
    assert not game.is_on_battlefield(neko)
    game.start_next_turn()
    _w1g9_settle(game)
    assert game.active_player_index == 1 and not giant.tapped


def test_w1g9_neko_te_holds_every_creature_it_has_locked(set_pool):
    """Each trigger's lock is its own continuous effect (CR 611.2a), and all
    of them last as long as Neko-Te remains: the equipped Prodigal Sorcerer
    pings the Hill Giant and then the Grizzly Bears, and both stay tapped
    through Bob's untap step — the second lock does not release the first."""
    game, mine, theirs = _w1g9_table(
        set_pool, mine=["Neko-Te", "Prodigal Sorcerer"],
        theirs=["Hill Giant", "Grizzly Bears"],
    )
    neko, tim = mine
    giant, bears = theirs
    assert _w1g9_equip(game, neko, tim).supported
    assert _w1g9_activate(game, tim, target_permanent_ids=[giant.permanent_id]).supported
    tim.tapped = False
    assert _w1g9_activate(game, tim, target_permanent_ids=[bears.permanent_id]).supported
    assert giant.tapped and bears.tapped
    game.start_next_turn()
    _w1g9_settle(game)
    assert game.active_player_index == 1
    assert giant.tapped and bears.tapped


def test_w1g9_neko_te_drains_the_player_its_wearer_damaged(set_pool):
    """"That player" is the damaged player, not the Equipment's controller:
    the unblocked equipped Bears deal Bob 2 and Neko-Te makes him lose 1 more;
    Alice's life does not move."""
    game, mine, _ = _w1g9_table(set_pool, mine=["Neko-Te", "Grizzly Bears"])
    neko, bears = mine
    assert _w1g9_equip(game, neko, bears).supported
    _w1g9_declare_attack(game, 0)
    _w1g9_drive_combat(game)
    assert game.players[1].life == 17
    assert game.players[0].life == 20


def test_w1g9_neko_te_does_nothing_for_an_unequipped_damager(set_pool):
    """Unattached, Neko-Te watches nobody: the Prodigal Sorcerer's ping on the
    Giant taps nothing and drains nobody."""
    game, mine, theirs = _w1g9_table(
        set_pool, mine=["Neko-Te", "Prodigal Sorcerer"], theirs=["Hill Giant"],
    )
    _neko, tim = mine
    giant = theirs[0]
    assert _w1g9_activate(game, tim, target_permanent_ids=[giant.permanent_id]).supported
    assert not giant.tapped
    tim.tapped = False
    assert _w1g9_activate(game, tim, target_player_index=1).supported
    assert game.players[1].life == 19

# Shuriken: 'Equipped creature has "{T}, Unattach Shuriken: Shuriken deals 2
# damage to target creature. That creature's controller gains control of
# Shuriken unless it was unattached from a Ninja."' The quote is folded onto
# the creature with the Equipment's name bound to its id (CR 201.5a): the
# Equipment is the dealer (``biter: "granter"``), the hand-over moves the
# Equipment (``give_control_of_granter_to_player``), and the condition reads
# what the unattach cost took it off (``unattached_from_for_cost``).


def _w1g9_throw(game, bearer, target):
    """Activate the creature's granted Shuriken ability at *target*."""
    from engine.oracle import compile_card_oracle

    abilities = compile_card_oracle(bearer.effective_card).activated_abilities
    index = next(
        i for i, ability in enumerate(abilities)
        if "unattach" in (ability.source_line or "").lower()
    )
    return _w1g9_activate(
        game, bearer, ability_index=index, target_permanent_ids=[target.permanent_id],
    )


def _w1g9_test_ninja(game, seat=0):
    """A vanilla 'Creature — Human Ninja' for seat 0: every printed Ninja on
    this base carries ninjutsu, which another group implements."""
    from tests.helpers import _mk_card

    ninja = _W1G9Permanent(card=_mk_card("W1G9 Ninja", "Creature — Human Ninja"))
    game._put_permanent_onto_battlefield(seat, ninja, None)
    ninja.metadata["summoning_sickness_turn"] = -99
    game._sync_control()
    return ninja


def test_w1g9_shuriken_thrown_from_a_non_ninja_changes_hands(set_pool):
    """The equipped Grizzly Bears taps and unattaches Shuriken (CR 701.3d);
    *Shuriken* deals the 2 damage (the log names it, CR 608.2h), and Bob, the
    damaged Hill Giant's controller, gains control of it (CR 611.2a: untimed)."""
    game, mine, theirs = _w1g9_table(
        set_pool, mine=["Shuriken", "Grizzly Bears"], theirs=["Hill Giant"],
    )
    shuriken, bears = mine
    giant = theirs[0]
    assert _w1g9_equip(game, shuriken, bears).supported
    assert _w1g9_throw(game, bears, giant).supported
    assert "Shuriken dealt 2 damage to Hill Giant" in game.log
    assert giant.damage_marked == 2
    assert bears.tapped
    assert shuriken.metadata.get("attached_to") is None
    assert game.controller_index_of(shuriken) == 1
    assert "Bob gains control of Shuriken" in game.log


def test_w1g9_shuriken_thrown_from_a_ninja_stays(set_pool):
    """Unattached from a Ninja, Shuriken deals its damage and stays with its
    controller."""
    game, mine, theirs = _w1g9_table(set_pool, mine=["Shuriken"], theirs=["Hill Giant"])
    shuriken = mine[0]
    giant = theirs[0]
    ninja = _w1g9_test_ninja(game)
    assert _w1g9_equip(game, shuriken, ninja).supported
    assert _w1g9_throw(game, ninja, giant).supported
    assert giant.damage_marked == 2
    assert game.controller_index_of(shuriken) == 0
    assert shuriken.metadata.get("attached_to") is None


def test_w1g9_shuriken_deals_the_damage_as_the_equipment(set_pool):
    """The dealer is the Equipment (CR 120.7), not the creature: Tel-Jilad
    Chosen's protection from artifacts prevents the damage (CR 702.16e). The
    target was legal — the ability's source is the Bears, a green creature —
    and the hand-over still happens, as it is not conditioned on damage."""
    game, mine, theirs = _w1g9_table(
        set_pool, mine=["Shuriken", "Grizzly Bears"], theirs=["Tel-Jilad Chosen"],
    )
    shuriken, bears = mine
    chosen = theirs[0]
    assert _w1g9_equip(game, shuriken, bears).supported
    assert _w1g9_throw(game, bears, chosen).supported
    assert chosen.damage_marked == 0
    assert game.controller_index_of(shuriken) == 1


def test_w1g9_shuriken_destroyed_in_response_still_deals_its_damage(set_pool):
    """CR 608.2h: the object the ability says deals the damage deals it as it
    last existed — Shuriken, Shattered with the ability on the stack, still
    deals 2; there is no Shuriken left for Bob to gain control of."""
    game, mine, theirs = _w1g9_table(
        set_pool, hand=["Shatter"], mine=["Shuriken", "Grizzly Bears"],
        theirs=["Hill Giant"],
    )
    shuriken, bears = mine
    giant = theirs[0]
    assert _w1g9_equip(game, shuriken, bears).supported
    from engine.oracle import compile_card_oracle

    abilities = compile_card_oracle(bears.effective_card).activated_abilities
    index = next(
        i for i, ability in enumerate(abilities)
        if "unattach" in (ability.source_line or "").lower()
    )
    assert game.queue_permanent_ability(
        0, "Grizzly Bears", permanent_index=_w1g9_slot(game, bears),
        ability_index=index, target_permanent_ids=[giant.permanent_id],
    ).supported
    assert shuriken.metadata.get("attached_to") is None
    assert game.queue_from_hand(
        0, "Shatter", target_permanent_ids=[shuriken.permanent_id],
    ).supported
    _w1g9_settle(game)
    assert not game.is_on_battlefield(shuriken)
    assert giant.damage_marked == 2
    assert "Shuriken dealt 2 damage to Hill Giant" in game.log

# ==== end w1g9 ======================================================


# ==== w1g10 ==========================================================
# w1g10's tests go between this line and the "end w1g10" line.

from engine import Game as _W1G10Game
from engine.cast_permissions import playable_from_zones as _w1g10_playable
from engine.models import Permanent as _W1G10Permanent
from engine.models import PlayerState as _W1G10PlayerState
from tests.helpers import settle as _w1g10_settle


def _w1g10_kanzashi_table(set_pool, opponent_library):
    """Alice controls an untapped Ornate Kanzashi; Bob's library is as given."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    kanzashi = _W1G10Permanent(card=bok["Ornate Kanzashi"])
    game = _W1G10Game(players=[
        _W1G10PlayerState(name="Alice", battlefield=[kanzashi],
                          library=[lea["Island"]] * 10),
        _W1G10PlayerState(name="Bob", library=[lea[name] for name in opponent_library]),
    ])
    game.enforce_mana_costs = False
    game._sync_control()
    game.start_turn(0)
    _w1g10_settle(game)
    return game


def test_w1g10_ornate_kanzashi_exiles_the_opponents_top_card_to_play(set_pool):
    """Ornate Kanzashi: "{2}, {T}: Target opponent exiles the top card of their
    library. You may play that card this turn." Bob's Grizzly Bears goes to
    Bob's exile (CR 406.3, its owner's) face up (2005-02-01 ruling); Alice may
    cast it and it enters under her control; Bob may not."""
    game = _w1g10_kanzashi_table(set_pool, ["Grizzly Bears", "Island"])
    alice, bob = game.players
    assert game.activate_permanent_ability(0, "Ornate Kanzashi", target_player_index=1).supported
    _w1g10_settle(game)
    assert [card.name for card in bob.exile] == ["Grizzly Bears"]
    assert any("Bob exiled Grizzly Bears from the top of their library" in line
               for line in game.log)
    assert [(e["zone"], e["name"]) for e in _w1g10_playable(game, 0)] == [
        ("exile", "Grizzly Bears"),
    ]
    assert _w1g10_playable(game, 1) == []
    cast = game.cast_from_hand(0, "Grizzly Bears", from_zone="exile")
    assert cast.supported, cast.details
    _w1g10_settle(game)
    assert "Grizzly Bears" in [perm.card.name for perm in game.controlled_by(0)]
    assert bob.exile == []


def test_w1g10_ornate_kanzashi_plays_a_land_and_the_grant_ends_this_turn(set_pool):
    """"Play" includes a land (CR 305.1, with the land drop); and "You can't play
    cards you exiled with Ornate Kanzashi on previous turns" (2005-02-01): a
    card not played stays exiled and is closed once the turn ends."""
    game = _w1g10_kanzashi_table(set_pool, ["Forest", "Lightning Bolt", "Island"])
    alice, bob = game.players
    assert game.activate_permanent_ability(0, "Ornate Kanzashi", target_player_index=1).supported
    _w1g10_settle(game)
    played = game.cast_from_hand(0, "Forest", from_zone="exile")
    assert played.supported, played.details
    assert "Forest" in [perm.card.name for perm in game.controlled_by(0)]
    game.players[0].battlefield[0].tapped = False
    assert game.activate_permanent_ability(0, "Ornate Kanzashi", target_player_index=1).supported
    _w1g10_settle(game)
    assert [card.name for card in bob.exile] == ["Lightning Bolt"]
    assert [e["name"] for e in _w1g10_playable(game, 0)] == ["Lightning Bolt"]
    game.resolve_cleanup_step(0)
    game.start_next_turn()
    _w1g10_settle(game)
    game.resolve_cleanup_step(1)
    game.start_next_turn()
    _w1g10_settle(game)
    assert _w1g10_playable(game, 0) == []
    assert [card.name for card in bob.exile] == ["Lightning Bolt"]

# ==== end w1g10 ======================================================
