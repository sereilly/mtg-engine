"""Betrayers of Kamigawa creatures (legendary ones too) — the later groups' sections.

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


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

from engine import Game as _w1g8_Game, PlayerState as _w1g8_PlayerState
from engine.models import Permanent as _w1g8_Permanent
from tests.helpers import (declare_attack as _w1g8_declare_attack,
                           drive_combat as _w1g8_drive_combat,
                           settle as _w1g8_settle,
                           stock_libraries as _w1g8_stock_libraries)

_W1G8_KEPT = "kept_until_end_of_turn"


def _w1g8_table(*boards):
    """A two-seat game, libraries stocked, mana costs enforced; *boards* is a
    list of cards per seat, each put onto the battlefield untouched by
    summoning sickness."""
    game = _w1g8_Game(players=[
        _w1g8_PlayerState(name="P0"), _w1g8_PlayerState(name="P1"),
    ])
    _w1g8_stock_libraries(game)
    game.enforce_mana_costs = True
    placed = []
    for seat, cards in enumerate(boards):
        for each in cards:
            permanent = _w1g8_Permanent(card=each)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed.append(permanent)
    game._sync_control()
    game.active_player_index = 0
    return game, placed


def _w1g8_kept(game, seat):
    return dict(game.players[seat].restricted_mana.get(_W1G8_KEPT, {}))


def _w1g8_to_main(game, seat):
    """Run *seat*'s beginning phase — untap, upkeep, draw — and enter its
    precombat main phase."""
    game.active_player_index = seat
    game.begin_turn_bookkeeping(seat)
    game.resolve_untap_step(seat)
    game.resolve_upkeep(seat)
    _w1g8_settle(game)
    game.resolve_draw_step(seat)
    _w1g8_settle(game)
    game.enter_next_turn_phase("beginning")


def test_w1g8_springcaller_mana_stays_through_the_turn_and_is_spent_last(set_pool):
    """"At the beginning of your upkeep, add {G}. Until end of turn, you don't
    lose this mana as steps and phases end." Made in the upkeep, kept through
    the draw step's end (CR 500.5's emptying excepted for this unit), still
    there in the main phase; a Forest's {G} beside it is the one a {G} spell
    spends (CR 601.2h: the payer keeps the mana that stays), and the kept {G}
    survives the main phase's end, the combat and the end step, and empties
    as the cleanup step ends (CR 514.2 ended the effect as it began)."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game, (_, forest) = _w1g8_table([bok["Sakura-Tribe Springcaller"], lea["Forest"]], [])
    game.players[0].hand.append(lea["Llanowar Elves"])
    _w1g8_to_main(game, 0)
    assert game.current_step == "precombat_main"
    assert _w1g8_kept(game, 0) == {"G": 1}
    assert game.players[0].mana_pool["G"] == 0
    assert "Sakura-Tribe Springcaller produced {G} (kept until end of turn)" in game.log

    game.tap_land_for_mana(0, "Forest", "G", permanent_id=forest.permanent_id)
    cast = game.cast_from_hand(0, "Llanowar Elves")
    _w1g8_settle(game)
    assert cast.supported, cast.details
    assert any(p.card.name == "Llanowar Elves" for p in game.players[0].battlefield)
    assert game.players[0].mana_pool["G"] == 0
    assert _w1g8_kept(game, 0) == {"G": 1}, "the Forest's {G} paid; the kept one stays"

    game.enter_next_turn_phase("precombat_main")
    game.enter_next_turn_phase("combat")
    game.enter_next_turn_phase("postcombat_main")
    assert _w1g8_kept(game, 0) == {"G": 1}
    game.resolve_end_step(0)
    _w1g8_settle(game)
    assert _w1g8_kept(game, 0) == {"G": 1}
    game.resolve_cleanup_step(0)
    assert not any(_w1g8_kept(game, 0).values())


def test_w1g8_kept_mana_pays_an_activation_and_an_effects_tax(set_pool):
    """Kept mana is plain mana that stays: it pays an activated ability (a
    payment with a purpose) and an effect-collected "unless … pays" (a payment
    with none, CR 605.3a's road) — Springcaller's {G} into a later step."""
    from engine.restricted_mana import mana_bucket, take_from_pool

    game, _ = _w1g8_table([], [])
    player = game.players[0]
    mana_bucket(player, _W1G8_KEPT)["G"] = 2
    player.mana_pool["G"] = 1
    # The payer's order: the open pool before the kept bucket.
    assert take_from_pool(player, None, "G", 2) == 0
    assert player.mana_pool["G"] == 0 and _w1g8_kept(game, 0) == {"G": 1}
    plan = game.effect_payment_plan(player, {"generic": 1})
    assert plan is not None and not plan.tapped
    assert game._pay_planned_cost(player, lambda: game.effect_payment_plan(player, {"generic": 1}))
    assert not any(_w1g8_kept(game, 0).values())


def test_w1g8_shizuko_feeds_each_player_in_their_own_upkeep(set_pool):
    """"At the beginning of each player's upkeep, that player adds {G}{G}{G}.
    Until end of turn, they don't lose this mana as steps and phases end."
    The mana goes to the player whose upkeep it is — the opponent included —
    and stays into that player's main phase."""
    bok = set_pool("BOK")
    game, _ = _w1g8_table([bok["Shizuko, Caller of Autumn"]], [])
    _w1g8_to_main(game, 1)
    assert _w1g8_kept(game, 1) == {"G": 3}
    assert not any(_w1g8_kept(game, 0).values())
    assert "Shizuko, Caller of Autumn: P1 added 3 mana (kept until end of turn)" in game.log


def test_w1g8_sakiko_adds_that_much_green_per_creature_dealing_combat_damage(set_pool):
    """"Whenever a creature you control deals combat damage to a player, add
    that much {G}." One trigger per creature, each sized by the damage that
    creature dealt (the event's own number, CR 120.4b); the mana stays into
    the postcombat main phase."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game, (sakiko, _, _) = _w1g8_table(
        [bok["Sakiko, Mother of Summer"], lea["Grizzly Bears"], lea["Hill Giant"]], [],
    )
    game.enforce_mana_costs = False
    sakiko.tapped = True   # stays home: two attackers, 2 and 3 damage
    _w1g8_declare_attack(game, 0)
    _w1g8_drive_combat(game)
    assert game.players[1].life == 15
    assert _w1g8_kept(game, 0) == {"G": 5}
    assert "Sakiko, Mother of Summer produced {G}{G}{G} (kept until end of turn)" in game.log
    assert "Sakiko, Mother of Summer produced {G}{G} (kept until end of turn)" in game.log
    assert game.current_step == "postcombat_main"


def _w1g8_accept(game, choice):
    game.confirm_optional_pay(choice.player_index, accept=True)


def _w1g8_decline(game, choice):
    game.confirm_optional_pay(choice.player_index, accept=False)


def test_w1g8_blademane_baku_gets_two_power_per_counter_its_cost_removed(set_pool):
    """"{1}, Remove X ki counters from this creature: For each counter
    removed, this creature gets +2/+0 until end of turn." Two Spirit casts,
    the person at seat 0 taking the first ki counter and declining nothing
    the second time; X=2 is paid and the Baku is 5/1 (1 + 2×2), the counters
    gone; X=1 on a fresh counter is +2 more, and the pump ends at cleanup."""
    from engine.named_counters import counters_on

    bok = set_pool("BOK")
    game, (blade,) = _w1g8_table([bok["Blademane Baku"]], [])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}
    game._set_phase_and_step("precombat_main", "precombat_main")
    for answer in (_w1g8_accept, _w1g8_accept, _w1g8_decline):
        game.players[0].hand.append(bok["Petalmane Baku"])
        assert game.cast_from_hand(0, "Petalmane Baku").supported
        _w1g8_settle(game, answers={"optional_pay": answer})
    assert counters_on(blade, "ki") == 2, "two taken, one declined"

    pumped = game.activate_permanent_ability(0, "Blademane Baku", x_value=2)
    _w1g8_settle(game)
    assert pumped.supported, pumped.details
    assert counters_on(blade, "ki") == 0
    assert (blade.effective_power, blade.effective_toughness) == (5, 1)
    assert "Blademane Baku gets +4/+0 until end of turn" in game.log
    # No counter left: X=1 is unpayable and refused with nothing paid.
    refused = game.activate_permanent_ability(0, "Blademane Baku", x_value=1)
    assert not refused.supported
    assert blade.effective_power == 5
    game.resolve_end_step(0)
    _w1g8_settle(game)
    game.resolve_cleanup_step(0)
    assert blade.effective_power == 1


def test_w1g8_the_wire_bounds_a_removal_x_by_the_counters_held(set_pool):
    """A person's X prompt for "{1}, Remove X ki counters from this
    creature: …" is sized by the server (``web/offers.ability_x_payable``):
    the counters the Baku holds bound it whatever the mana says, and
    ``counter_bound`` names the store; with {1} unpayable nothing is."""
    from engine.named_counters import add_counters
    from engine.oracle import compile_card_oracle
    from engine.targeting import usable_activated_abilities
    from web.offers import ability_x_payable

    bok = set_pool("BOK")
    game, (blade,) = _w1g8_table([bok["Blademane Baku"]], [])
    add_counters(blade, "ki", 2)
    (ability,) = usable_activated_abilities(compile_card_oracle(blade.card))
    game.players[0].mana_pool["C"] = 5
    payable = ability_x_payable(game, 0, blade, ability)
    assert payable["pool"] == 2 and payable["board"] == 2
    assert payable["counter_bound"] == {"kind": "ki", "count": 2}
    game.players[0].mana_pool["C"] = 0
    payable = ability_x_payable(game, 0, blade, ability)
    assert payable["pool"] == 0 and payable["board"] == 0


def test_w1g8_for_each_counter_removed_needs_a_removal_cost():
    """The leading "For each counter removed," counts the ability's own
    removal cost; on an ability whose cost removes nothing the words name
    nothing, and the line refuses rather than pumping by zero."""
    from engine.grammar import compile_line

    line = "For each counter removed, this creature gets +2/+0 until end of turn."
    assert compile_line("{1}, Remove X ki counters from this creature: " + line).instructions
    assert not compile_line("{1}: " + line).instructions


def test_w1g8_the_ai_announces_a_removal_x_and_never_one_it_cannot_pay(set_pool):
    """The ki Baku's "Remove X ki counters" is an X the activator announces
    (CR 107.3a via 602.2b). Skullmane Baku with two counters is proposed at
    X=2 on the 2/2 it kills; Waxmane Baku, whose X sizes its target list, is
    declined rather than proposed for an X of 0 and refused (the base's
    activation-cost census red)."""
    from engine.ai_abilities import choose_activation_action
    from engine.named_counters import add_counters

    bok, lea = set_pool("BOK"), set_pool("LEA")
    for name, expected in (("Skullmane Baku", 2), ("Waxmane Baku", None)):
        game, (baku, *_rest) = _w1g8_table(
            [bok[name]] + [lea["Forest"]] * 3, [lea["Grizzly Bears"]],
        )
        game.interactive_seats = set()
        game._set_phase_and_step("precombat_main", "precombat_main")
        add_counters(baku, "ki", 2)
        action = choose_activation_action(game, 0)
        if expected is None:
            assert action is None or action.permanent_name != name
            continue
        assert action is not None and action.permanent_name == name
        assert action.x_value == expected
        bears = game.players[1].battlefield[0]
        assert action.target_permanent_ids == [bears.permanent_id]


def _w1g8_upkeep(game, seat=0):
    game.active_player_index = seat
    game.begin_turn_bookkeeping(seat)
    game.resolve_untap_step(seat)
    game.resolve_upkeep(seat)


def test_w1g8_chisei_is_sacrificed_unless_a_counter_comes_off_your_permanent(set_pool):
    """"At the beginning of your upkeep, sacrifice Chisei unless you remove a
    counter from a permanent you control." With no counter on anything its
    controller controls the price cannot be paid and Chisei goes (the
    opponent's ki counters are no resource of theirs); with one, the counter
    comes off and Chisei stays."""
    from engine.named_counters import add_counters, counters_on

    bok = set_pool("BOK")
    game, (chisei, theirs) = _w1g8_table(
        [bok["Chisei, Heart of Oceans"]], [bok["Petalmane Baku"]],
    )
    add_counters(theirs, "ki", 2)
    _w1g8_upkeep(game)
    _w1g8_settle(game)
    assert not any(p is chisei for p in game.players[0].battlefield)
    assert chisei.card in game.players[0].graveyard
    assert counters_on(theirs, "ki") == 2

    game, (chisei, baku, theirs) = _w1g8_table(
        [bok["Chisei, Heart of Oceans"], bok["Petalmane Baku"]], [bok["Petalmane Baku"]],
    )
    add_counters(baku, "ki", 2)
    add_counters(theirs, "ki", 2)
    _w1g8_upkeep(game)
    _w1g8_settle(game)
    assert any(p is chisei for p in game.players[0].battlefield)
    assert (counters_on(baku, "ki"), counters_on(theirs, "ki")) == (1, 2)
    assert "Chisei, Heart of Oceans removed a ki counter from Petalmane Baku" in game.log


def test_w1g8_chisei_asks_a_person_whether_and_from_which_permanent(set_pool):
    """The interactive seat is offered the price (``optional_pay``) and, taking
    it, picks the permanent (``permanent_choice``) among its own that hold a
    counter — here the Baku Altar, not the Baku. Declining sacrifices Chisei."""
    from engine.named_counters import add_counters, counters_on

    bok = set_pool("BOK")
    for take in (True, False):
        game, (chisei, baku, altar, bare) = _w1g8_table([
            bok["Chisei, Heart of Oceans"], bok["Petalmane Baku"],
            bok["Baku Altar"], bok["Skullmane Baku"],
        ], [])
        add_counters(baku, "ki", 2)
        add_counters(altar, "ki", 1)
        game.interactive_seats = {0}
        _w1g8_upkeep(game)
        owed = _w1g8_settle(game, defaults=False)
        assert owed is not None and owed.kind == "optional_pay"
        game.confirm_optional_pay(0, accept=take)
        if not take:
            _w1g8_settle(game)
            assert not any(p is chisei for p in game.players[0].battlefield)
            continue
        owed = _w1g8_settle(game, defaults=False)
        assert owed is not None and owed.kind == "permanent_choice"
        offered = {p.permanent_id for p in game.live_permanent_choices(owed)}
        assert offered == {baku.permanent_id, altar.permanent_id}, "only what holds a counter"
        assert game.confirm_permanent_choice(0, altar.permanent_id)
        _w1g8_settle(game)
        assert any(p is chisei for p in game.players[0].battlefield)
        assert (counters_on(baku, "ki"), counters_on(altar, "ki")) == (2, 0)


def _w1g8_flipped(bok, name):
    """*name* on seat 0's battlefield, two Spirit casts taking a ki counter
    each, then the end step's "you may flip it" accepted (CR 710)."""
    from engine.named_counters import counters_on

    game, (flip,) = _w1g8_table([bok[name]], [])
    game.enforce_mana_costs = False
    game._set_phase_and_step("precombat_main", "precombat_main")
    for _ in range(2):
        game.players[0].hand.append(bok["Petalmane Baku"])
        assert game.cast_from_hand(0, "Petalmane Baku").supported
        _w1g8_settle(game, answers={"optional_pay": _w1g8_accept})
    assert counters_on(flip, "ki") == 2
    game.resolve_end_step(0)
    _w1g8_settle(game, answers={"optional_pay": _w1g8_accept})
    game.resolve_cleanup_step(0)
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game, flip


def test_w1g8_the_ki_flip_cards_flip_and_their_bottom_halves_work(set_pool):
    """The five ki flip cards: two Spirit casts, two ki counters, flipped at
    the end step, and each bottom half's ki ability spends a counter and does
    what it prints — Kaiso's prevention (a Lightning Bolt into the shielded
    creature), Scarmaker's fear, Azamuki's control until end of turn, Ichiga's
    +2/+2 (and trample)."""
    from engine.named_counters import counters_on

    bok, lea = set_pool("BOK"), set_pool("LEA")

    game, kaiso = _w1g8_flipped(bok, "Faithful Squire")
    assert kaiso.card.name == "Kaiso, Memory of Loyalty" and kaiso.has_keyword("flying")
    bears = _w1g8_Permanent(card=lea["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, bears, None)
    assert game.activate_permanent_ability(
        0, kaiso.card.name, target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g8_settle(game)
    game.players[0].hand.append(lea["Lightning Bolt"])
    game.cast_from_hand(0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id])
    _w1g8_settle(game)
    assert game.is_on_battlefield(bears) and counters_on(kaiso, "ki") == 1

    game, scarmaker = _w1g8_flipped(bok, "Hired Muscle")
    assert scarmaker.card.name == "Scarmaker"
    assert game.activate_permanent_ability(
        0, "Scarmaker", target_permanent_ids=[scarmaker.permanent_id],
    ).supported
    _w1g8_settle(game)
    assert scarmaker.has_keyword("fear")

    game, azamuki = _w1g8_flipped(bok, "Cunning Bandit")
    assert azamuki.card.name == "Azamuki, Treachery Incarnate"
    ogre = _w1g8_Permanent(card=lea["Gray Ogre"])
    game._put_permanent_onto_battlefield(1, ogre, None)
    game._sync_control()
    assert game.activate_permanent_ability(
        0, azamuki.card.name, target_permanent_ids=[ogre.permanent_id],
    ).supported
    _w1g8_settle(game)
    assert game.controller_index_of(ogre) == 0
    game.resolve_end_step(0)
    _w1g8_settle(game)
    game.resolve_cleanup_step(0)
    assert game.controller_index_of(ogre) == 1

    game, ichiga = _w1g8_flipped(bok, "Budoka Pupil")
    assert ichiga.card.name == "Ichiga, Who Topples Oaks" and ichiga.has_keyword("trample")
    assert game.activate_permanent_ability(
        0, ichiga.card.name, target_permanent_ids=[ichiga.permanent_id],
    ).supported
    _w1g8_settle(game)
    assert (ichiga.effective_power, ichiga.effective_toughness) == (6, 5)


def test_w1g8_jaraku_counters_a_spell_unless_its_controller_pays_two(set_pool):
    """Callow Jushi flipped: "Remove a ki counter from Jaraku: Counter target
    spell unless its controller pays {2}." A caster with no mana left loses
    the spell; one with two untapped Forests pays and keeps it."""
    lea = set_pool("LEA")
    bok = set_pool("BOK")
    for forests, countered in ((0, True), (2, False)):
        game, jaraku = _w1g8_flipped(bok, "Callow Jushi")
        assert jaraku.card.name == "Jaraku the Interloper"
        game.enforce_mana_costs = True
        for _ in range(forests):
            land = _w1g8_Permanent(card=lea["Forest"])
            game._put_permanent_onto_battlefield(1, land, None)
        game._sync_control()
        game.players[1].hand.append(lea["Grizzly Bears"])
        game.players[1].mana_pool["G"] = 2
        game.active_player_index = 1
        assert game.queue_from_hand(1, "Grizzly Bears").supported
        assert game.activate_permanent_ability(
            0, "Jaraku the Interloper", target_stack_index=0,
        ).supported
        _w1g8_settle(game)
        bears_out = any(p.card.name == "Grizzly Bears" for p in game.controlled_by(1))
        assert bears_out is not countered
        assert ("Grizzly Bears" in [c.name for c in game.players[1].graveyard]) is countered


def test_w1g8_the_ki_baku_spend_x_counters_on_x(set_pool):
    """Petalmane, Skullmane and Waxmane Baku with three ki counters each, X=2:
    {G}{G} added; a 3/3 at 1/1; two creatures tapped — one counter left on
    each."""
    from engine.named_counters import add_counters, counters_on

    bok, lea = set_pool("BOK"), set_pool("LEA")
    game, (petal, skull, wax, giant, bears, ogre) = _w1g8_table(
        [bok["Petalmane Baku"], bok["Skullmane Baku"], bok["Waxmane Baku"]],
        [lea["Hill Giant"], lea["Grizzly Bears"], lea["Gray Ogre"]],
    )
    game.enforce_mana_costs = False
    game._set_phase_and_step("precombat_main", "precombat_main")
    for baku in (petal, skull, wax):
        add_counters(baku, "ki", 3)
    assert game.activate_permanent_ability(
        0, "Petalmane Baku", x_value=2, mana_color="G",
    ).supported
    _w1g8_settle(game)
    assert game.players[0].mana_pool["G"] == 2
    assert game.activate_permanent_ability(
        0, "Skullmane Baku", x_value=2, target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g8_settle(game)
    assert (giant.effective_power, giant.effective_toughness) == (1, 1)
    assert game.activate_permanent_ability(
        0, "Waxmane Baku", x_value=2,
        target_permanent_ids=[bears.permanent_id, ogre.permanent_id],
    ).supported
    _w1g8_settle(game)
    assert bears.tapped and ogre.tapped and not giant.tapped
    assert [counters_on(b, "ki") for b in (petal, skull, wax)] == [1, 1, 1]


def test_w1g8_the_kept_sentence_names_the_pool_it_keeps():
    """"…**you** don't lose this mana" after "that player adds", or "**they**"
    after a bare "Add", names a pool the mana did not go into: refused, never
    kept in the wrong pool."""
    from engine.grammar import compile_line

    kept = "Until end of turn, {} don't lose this mana as steps and phases end."
    good = compile_line(
        "At the beginning of each player's upkeep, that player adds {G}{G}{G}. "
        + kept.format("they")
    )
    assert good.instructions[0].payload["spend_only"] == _W1G8_KEPT
    for line in (
        "At the beginning of each player's upkeep, that player adds {G}{G}{G}. "
        + kept.format("you"),
        "At the beginning of your upkeep, add {G}. " + kept.format("they"),
    ):
        assert not compile_line(line).instructions, line

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================


# ==== w1g10 ==========================================================
# w1g10's tests go between this line and the "end w1g10" line.

# ==== end w1g10 ======================================================
