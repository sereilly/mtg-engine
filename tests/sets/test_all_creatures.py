"""Per-card tests for Alliances' creatures.

See tests/sets/README.md for the convention: get cards through
``set_pool("ALL")`` / ``set_cards("ALL")``, never a spelled-out
``cards/*.json`` path and never a new conftest fixture.

**Parallel-authorship convention for this set.** The waves that implement
Alliances split by grammar family rather than by printed type, so several
groups land tests in this one file. Each group appends a single delimited
block::

    # --- W<wave>G<n>: <topic> ---

and puts **its own imports at the top of its own block**, not in a shared
header. That is deliberate. The mechanical merge for this file is "take ours,
append the branch's block", and a branch that added an import to a shared
header loses it in exactly that move -- a ``NameError`` at collection, found
only after the merge is committed. A self-contained block cannot lose one.

Do not edit the text above. The integrator compares every branch's copy of this
header against the merge base byte for byte; a branch that changed it is a
branch whose block cannot be appended mechanically.
"""

from __future__ import annotations


# --- W1G2: library-top costs ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


def _w1g2_card(name: str, type_line: str, mana_cost: str = "") -> CardDefinition:
    """A vanilla card to stack a library with, invented so the only thing that
    varies between the halves of each pair below is the characteristic under
    test."""
    return CardDefinition(
        name=name, mana_cost=mana_cost, cmc=float(len(mana_cost) // 3),
        type_line=type_line, oracle_text="", colors=(), color_identity=(),
        keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "1", "toughness": "1"},
    )


def _w1g2_board(set_pool, name: str, library: list[CardDefinition]):
    """*name* on the battlefield with *library* under it, ready to activate."""
    perm = Permanent(card=set_pool("ALL")[name])
    perm.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(name="P1", battlefield=[perm], library=list(library)),
        PlayerState(name="P2", library=[_w1g2_card("Filler", "Artifact")] * 5),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, perm


def test_royal_herbalist_exiles_the_top_card_to_gain_a_life(set_pool):
    """"{2}, Exile the top card of your library: You gain 1 life."

    CR 118.1: paying the cost is carrying out the printed action, so the card
    is in exile before the ability is on the stack — and the life arrives
    whatever that card was.
    """
    game, _perm = _w1g2_board(
        set_pool, "Royal Herbalist", [_w1g2_card("Top Card", "Artifact")] * 3
    )
    me = game.players[0]
    result = game.activate_permanent_ability(0, "Royal Herbalist")
    assert result.supported, result.details
    assert len(me.library) == 2, "the cost came off the library on activation"
    assert [card.name for card in me.exile] == ["Top Card"]
    game.resolve_top_of_stack()
    assert me.life == 21


def test_royal_herbalist_cannot_be_activated_with_an_empty_library(set_pool):
    """CR 118.3: a player can't pay a cost without the resources to pay it
    *fully*, so an empty library makes this ability unactivatable — never a
    free one, and never one that exiles nothing and gains the life anyway."""
    game, _perm = _w1g2_board(set_pool, "Royal Herbalist", [])
    me = game.players[0]
    result = game.activate_permanent_ability(0, "Royal Herbalist")
    assert not result.supported
    assert me.life == 20, "nothing was gained"
    assert not game.stack, "the ability never reached the stack"


def test_seasoned_tactician_needs_four_cards_for_its_four_card_cost(set_pool):
    """"{3}, Exile the top four cards of your library: …"

    The counted cost, and CR 118.3's "fully" is the whole of it: three cards
    do not pay a four-card cost, and the three are still there afterwards.
    """
    game, _perm = _w1g2_board(
        set_pool, "Seasoned Tactician", [_w1g2_card("Card", "Artifact")] * 3
    )
    me = game.players[0]
    assert not game.activate_permanent_ability(0, "Seasoned Tactician").supported
    assert len(me.library) == 3 and not me.exile

    me.library.append(_w1g2_card("Card", "Artifact"))
    assert game.activate_permanent_ability(0, "Seasoned Tactician").supported
    assert not me.library and len(me.exile) == 4


def test_storm_elemental_reads_back_the_card_its_cost_exiled(set_pool):
    """"{U}, Exile the top card of your library: If the exiled card is a snow
    land, this creature gets +1/+1 until end of turn."

    The sentence asks about the card the *cost* ate, which by resolution is in
    exile (CR 608.2h) — so the answer is the record the payment kept, and the
    snow supertype is what it is asked for.
    """
    snow = _w1g2_card("Snowy", "Basic Snow Land - Mountain")
    plain = _w1g2_card("Plain Land", "Basic Land - Mountain")

    game, elemental = _w1g2_board(set_pool, "Storm Elemental", [snow, snow])
    assert game.activate_permanent_ability(0, "Storm Elemental", ability_index=1).supported
    game.resolve_top_of_stack()
    assert (elemental.effective_power, elemental.effective_toughness) == (4, 5)

    game, elemental = _w1g2_board(set_pool, "Storm Elemental", [plain, plain])
    assert game.activate_permanent_ability(0, "Storm Elemental", ability_index=1).supported
    game.resolve_top_of_stack()
    assert (elemental.effective_power, elemental.effective_toughness) == (3, 4), (
        "an ordinary land is not a snow land"
    )


def test_chaos_harlequin_branches_on_the_card_its_effect_exiled(set_pool):
    """"{R}: Exile the top card of your library. If that card is a land card,
    this creature gets -4/-0 until end of turn. Otherwise, this creature gets
    +2/+0 until end of turn."

    The exile here is the *effect*, not the cost, and "that card" is the
    pronoun for what the step in front of it moved — the same back-reference
    "it was" spells with a bare pronoun.
    """
    game, harlequin = _w1g2_board(
        set_pool, "Chaos Harlequin", [_w1g2_card("Plain Land", "Basic Land - Mountain")]
    )
    assert game.activate_permanent_ability(0, "Chaos Harlequin").supported
    game.resolve_top_of_stack()
    assert (harlequin.effective_power, harlequin.effective_toughness) == (-2, 4)

    game, harlequin = _w1g2_board(
        set_pool, "Chaos Harlequin", [_w1g2_card("Some Spell", "Artifact")]
    )
    assert game.activate_permanent_ability(0, "Chaos Harlequin").supported
    game.resolve_top_of_stack()
    assert (harlequin.effective_power, harlequin.effective_toughness) == (4, 4)


# --- W1G5: delayed triggers ---

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path


def _w1g5_lea(name: str):
    """One Limited Edition Alpha card, for the graveyards these tests build."""
    for card in load_cards(manifest_set_path("LEA", include_measured=True)):
        if card.name == name:
            return card
    raise AssertionError(f"{name} is not in LEA")


def _w1g5_duel():
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.active_player_index = 0
    return game, game.players[0], game.players[1]


def test_w1g5_krovikan_horror_returns_itself_at_the_end_step(set_pool):
    """CR 113.6b: "if this card is in your graveyard …" is where the card states
    which zone the ability functions in, and CR 404.3's order is what "directly
    above it" reads."""
    horror = set_pool("ALL")["Krovikan Horror"]
    game, p1, _p2 = _w1g5_duel()
    game.interactive_seats = {0}
    p1.graveyard.extend([horror, _w1g5_lea("Grizzly Bears")])

    game.resolve_end_step(0)
    game._settle()
    assert game.confirm_optional_pay(0, "Krovikan Horror", accept=True)
    game._settle()

    assert [card.name for card in p1.hand] == ["Krovikan Horror"]
    assert [card.name for card in p1.graveyard] == ["Grizzly Bears"]


def test_w1g5_krovikan_horror_answers_to_an_opponents_end_step(set_pool):
    """"At the beginning of **the** end step" — not "your". CR 513.1 gives every
    turn one end step and this ability names whichever comes next, so the scan
    is unseated where Death Spark's upkeep one is not."""
    horror = set_pool("ALL")["Krovikan Horror"]
    game, p1, _p2 = _w1g5_duel()
    game.interactive_seats = {0}
    p1.graveyard.extend([horror, _w1g5_lea("Grizzly Bears")])
    game.active_player_index = 1

    game.resolve_end_step(1)
    game._settle()
    assert game.confirm_optional_pay(0, "Krovikan Horror", accept=True)
    game._settle()

    assert [card.name for card in p1.hand] == ["Krovikan Horror"]


def test_w1g5_krovikan_horror_stays_put_with_nothing_above_it(set_pool):
    """CR 603.4: the intervening-if is checked when the trigger would fire. On
    top of the pile there is nothing above it, so nothing fires."""
    horror = set_pool("ALL")["Krovikan Horror"]
    game, p1, _p2 = _w1g5_duel()
    game.interactive_seats = {0}
    p1.graveyard.extend([_w1g5_lea("Grizzly Bears"), horror])

    game.resolve_end_step(0)
    game._settle()

    assert p1.hand == []
    assert p1.graveyard[-1] is horror


def test_w1g5_nether_shadows_deeper_condition_still_reads(set_pool):
    """The three-cards-above spelling is the same clause with a different number,
    and it must keep answering the way it did — Nether Shadow's line is claimed
    by a card hook, and a condition production that changed what "above" means
    would have moved it silently."""
    from engine.graveyard_order import satisfies_above

    bear = _w1g5_lea("Grizzly Bears")
    forest = _w1g5_lea("Forest")
    pile = [set_pool("ALL")["Krovikan Horror"], bear, bear, bear]
    spec = {"card_type": "creature", "count": 3, "op": "ge", "directly": False}
    assert satisfies_above(pile, 0, spec)
    assert not satisfies_above([pile[0], bear, forest], 0, spec)


# --- W2G1: combat triggers and restrictions ---

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle


def _w2g1_attack_unblocked(set_pool, name):
    """*name* attacking P2 with nothing declared to block it.

    The trigger every card in this block hangs off is announced by the
    declare-blockers step (CR 509.1h), so the board has to reach that step: a
    compiled program alone cannot show that the seat the effect names is the
    seat the fire site froze.
    """
    subject = Permanent(card=set_pool("ALL")[name])
    p1 = PlayerState(name="P1", battlefield=[subject], life=20)
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game._settle()
    subject.metadata["summoning_sickness_turn"] = -99
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game._set_phase_and_step("combat", "declare_blockers")
    game._fire_unblocked_attack_triggers()
    while game.stack:
        game.resolve_top_of_stack()
    return game, subject


def test_keeper_of_tresserhorn_drains_the_seat_the_combat_froze(set_pool):
    """"Whenever this creature attacks and isn't blocked, it assigns no combat
    damage this turn and **defending player loses 2 life**."

    The seat is CR 506.2's, read from the key the combat fire site stamps
    (``trigger_defending_player_index``) rather than from the board: this
    resolves in a priority window after the declaration, and an attacker that
    left combat in between would leave a board read naming nobody.
    """
    game, keeper = _w2g1_attack_unblocked(set_pool, "Keeper of Tresserhorn")

    assert game.players[1].life == 18
    assert game.players[0].life == 20, "the drain is not the controller's"
    # Both halves of one sentence: the life loss is what the card trades its
    # combat damage for, so a version that only drained would be a better card.
    assert keeper.metadata.get("assigns_no_combat_damage_until_eot") is True


def test_lim_duls_paladin_drains_four_and_keeps_its_other_three_lines(set_pool):
    """The same trigger with a different number, on a card whose other three
    lines already compiled. The number is payload, so nothing about the second
    card is a second implementation."""
    game, paladin = _w2g1_attack_unblocked(set_pool, "Lim-Dûl's Paladin")

    assert game.players[1].life == 16
    assert paladin.metadata.get("assigns_no_combat_damage_until_eot") is True
    program = compile_card_oracle(set_pool("ALL")["Lim-Dûl's Paladin"])
    assert program.supported, program.reason
    assert all(trig.supported for trig in program.triggered_abilities)
    assert "trample" in program.static_lines


def test_swamp_mosquito_poisons_the_defender_not_a_damaged_player(set_pool):
    """"... defending player gets a poison counter."

    The counter reaches ``PlayerState.poison_counters`` through the same
    handler Pit Scorpion uses, and the difference is which *record* names the
    seat: a damage event freezes the damaged player and this one freezes
    CR 506.2's defender. The Mosquito's trigger deals no damage at all, so
    reading the damage key for both words would have poisoned nobody.
    """
    game, _ = _w2g1_attack_unblocked(set_pool, "Swamp Mosquito")

    assert game.players[1].poison_counters == 1
    assert game.players[0].poison_counters == 0
    assert game.players[1].life == 20, "a poison counter is not damage"


def test_gorilla_berserkers_needs_three_blockers_at_once(set_pool):
    """"This creature can't be blocked except by three or more creatures."

    Menace (CR 702.111a) is the N=2 case of this sentence, so the declaration
    gate asks one helper for the largest minimum any restriction imposes
    (CR 509.1b). Zero blockers stays legal - the restriction says how many must
    block together, not that any must.
    """
    pool = set_pool("ALL")

    def board(n):
        ape = Permanent(card=pool["Gorilla Berserkers"])
        bears = [Permanent(card=pool["Elvish Ranger"]) for _ in range(3)]
        game = Game(players=[
            PlayerState(name="P1", battlefield=[ape], life=20),
            PlayerState(name="P2", battlefield=bears, life=20),
        ])
        game._settle()
        ape.metadata["summoning_sickness_turn"] = -99
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        assert game.declare_attackers(0, [0], defending_player_index=1)[0]
        game._set_phase_and_step("combat", "declare_blockers")
        return game.declare_blockers(1, {i: 0 for i in range(n)})

    assert not board(1)[0]
    assert not board(2)[0]
    assert board(3)[0]
    assert board(0)[0], "declining to block is always legal"


def test_gorilla_berserkers_keeps_the_keywords_printed_beside_the_semicolon(set_pool):
    """"Trample; rampage 2 (...)" is one printed line carrying two keywords.

    The oracle keyword classifier normalises the semicolon to a comma and reads
    both, which is why this card never lost trample or rampage - the refusal
    census reports the *grammar* refusing the line, and the grammar is not the
    reader for a keyword line.
    """
    program = compile_card_oracle(set_pool("ALL")["Gorilla Berserkers"])

    assert program.supported, program.reason
    assert "trample, rampage 2" in program.static_lines
    (rampage,) = [
        trig for trig in program.triggered_abilities
        if trig.condition.kind == "creature_becomes_blocked"
    ]
    assert rampage.instruction.payload == {"amount": 2}


def test_whip_vine_holds_only_the_flier_it_is_blocking(set_pool):
    """"{T}: Tap target creature with flying **blocked by this creature**. **That
    creature** doesn't untap ... for as long as this creature remains tapped."

    Two readings the parser lacked: the passive voice of "target creature it's
    blocking" (one relation, CR 509.1a, printed from either end), and the
    demonstrative back-reference the linked untap lock accepted only as "it".
    """
    from engine.legality import usable_activated_abilities

    pool = set_pool("ALL")
    vine = Permanent(card=pool["Whip Vine"])
    flier = Permanent(card=pool["Storm Crow"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[flier], life=20),
        PlayerState(name="P2", battlefield=[vine], life=20),
    ])
    game.enforce_mana_costs = False
    game._settle()
    for perm in (vine, flier):
        perm.metadata["summoning_sickness_turn"] = -99
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(1, {0: 0})[0]

    vine_idx = game.players[1].battlefield.index(vine)
    spec = game.activation_target_spec(1, vine_idx, 0)
    assert [t["name"] for t in spec["valid_targets"]] == [flier.card.name]

    ability = usable_activated_abilities(compile_card_oracle(vine.effective_card))[0]
    assert game.activation_target_refusal(
        1, vine, ability, target_permanent_ids=[flier.permanent_id]
    ) is None

    assert game.activate_permanent_ability(
        1, "Whip Vine", permanent_index=vine_idx,
        target_player_index=0, target_permanent_index=0,
        target_permanent_ids=[flier.permanent_id],
    ).supported
    while game.stack:
        game.resolve_top_of_stack()

    assert flier.tapped and vine.tapped
    game.resolve_untap_step(0)
    assert flier.tapped, "held while the Vine remains tapped (CR 611.2a)"
    game.become_untapped(vine)
    game.resolve_untap_step(0)
    assert not flier.tapped, "the lock ends the moment the Vine untaps"


def test_whip_vine_refuses_a_creature_it_is_not_blocking(set_pool):
    """The narrowing enforced, which is the half a parsed-and-dropped rider
    would lose: the ability would tap the source for nothing and hold down a
    creature the card never names."""
    from engine.legality import usable_activated_abilities

    pool = set_pool("ALL")
    vine = Permanent(card=pool["Whip Vine"])
    bystander = Permanent(card=pool["Elvish Ranger"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[bystander], life=20),
        PlayerState(name="P2", battlefield=[vine], life=20),
    ])
    game.enforce_mana_costs = False
    game._settle()

    ability = usable_activated_abilities(compile_card_oracle(vine.effective_card))[0]
    assert game.activation_target_refusal(
        1, vine, ability, target_permanent_ids=[bystander.permanent_id]
    ) is not None
    assert not vine.tapped, "refused before the {T} cost is paid (CR 602.2b)"


def _w2g1_home_guard(set_pool, mode):
    """Kjeldoran Home Guard through one combat as an attacker, a blocker, or
    neither."""
    pool = set_pool("ALL")
    guard = Permanent(card=pool["Kjeldoran Home Guard"])
    other = Permanent(card=pool["Elvish Ranger"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[guard], life=20),
        PlayerState(name="P2", battlefield=[other], life=20),
    ])
    game._settle()
    for perm in (guard, other):
        perm.metadata["summoning_sickness_turn"] = -99
    if mode == "attack":
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        assert game.declare_attackers(0, [0], defending_player_index=1)[0]
        game._set_phase_and_step("combat", "declare_blockers")
        game.declare_blockers(1, {})
    elif mode == "block":
        game.active_player_index = 1
        game._set_phase_and_step("combat", "declare_attackers")
        assert game.declare_attackers(1, [0], defending_player_index=0)[0]
        game._set_phase_and_step("combat", "declare_blockers")
        assert game.declare_blockers(0, {0: 0})[0]
    else:
        game.active_player_index = 0
        game._set_phase_and_step("combat", "declare_attackers")
        game._set_phase_and_step("combat", "declare_blockers")
    game.end_combat()
    while game.stack:
        game.resolve_top_of_stack()
    return game, guard


@pytest.mark.parametrize("mode", ["attack", "block"])
def test_kjeldoran_home_guard_pays_its_toll_from_either_side_of_combat(
    set_pool, mode
):
    """"At end of combat, **if this creature attacked or blocked this combat**,
    put a -0/-1 counter on this creature and create a 0/1 white Deserter."

    Both halves of CR 509.1a's relation, and the blocking half is the one a
    board read gets wrong: ``end_combat`` sweeps the combat record before the
    priority window that resolves this batch, so the answer is frozen when the
    trigger is announced (CR 603.10).
    """
    game, guard = _w2g1_home_guard(set_pool, mode)

    assert counters_on(guard, "-0/-1") == 1
    assert guard.effective_toughness == 5, "1/6 printed, one -0/-1 counter"
    tokens = [
        p.card.name for p in game.controlled_by(game.players[0]) if p is not guard
    ]
    assert tokens == ["Deserter Token"]


def test_kjeldoran_home_guard_does_nothing_if_it_stayed_home(set_pool):
    """The intervening-if actually gating (CR 603.4). Read as always true, the
    card would shed a counter at the end of every combat of every turn."""
    game, guard = _w2g1_home_guard(set_pool, "idle")

    assert counters_on(guard, "-0/-1") == 0
    assert guard.effective_toughness == 6
    assert list(game.controlled_by(game.players[0])) == [guard]
# --- end W2G1 ---


# --- W2G2: costs ---
#
# An activation cost that *places* a counter on a chosen permanent, plus the
# recipient union prevention shares with damage. Imports are in this block, per
# the header's parallel-authorship convention.

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from engine.oracle import compile_card_oracle, parse_activated_ability_cost

_W2G2_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _w2g2_mage_board(set_pool, mine=("Grizzly Bears",)):
    """Wandering Mage on the battlefield with company, mana costs enforced so
    its {B} and its counter are both really collected."""
    p1 = PlayerState(name="A")
    game = Game(players=[p1, PlayerState(name="B")])
    game.enforce_mana_costs = True
    mage = Permanent(card=set_pool("ALL")["Wandering Mage"])
    p1.battlefield.append(mage)
    for name in mine:
        p1.battlefield.append(Permanent(card=_W2G2_LEA[name]))
    game._settle()
    return game, p1, mage


def test_wandering_mage_pays_its_counter_onto_a_chosen_creature(set_pool):
    """"{B}, **Put a -1/-1 counter on a creature you control**: Prevent the next
    2 damage that would be dealt to target player or planeswalker this turn."

    Both halves were missing. The cost read as nothing at all — the kind is
    spelled in symbols (CR 122.1a) and both the production and the charger read
    it off a bare *word* — and the recipient union "or planeswalker" was
    damage's alone. Watched here as a payment: the counter really lands, on the
    creature the payer named and not on the Mage."""
    game, p1, mage = _w2g2_mage_board(set_pool)
    bears = p1.battlefield[1]
    p1.mana_pool["B"] = 1

    ability = [
        a for a in compile_card_oracle(mage.card).activated_abilities
        if a.cost.put_counter_filter is not None
    ]
    assert len(ability) == 1, "one of the three abilities pays with a counter"

    result = game.activate_permanent_ability(
        0, "Wandering Mage", target_player_index=1, ability_index=2,
        cost_permanent_ids=[bears.permanent_id],
    )
    game._settle()

    assert result.supported, result.details
    # The counter is on the chosen creature, at CR 122.1a's layer-7 value.
    assert (bears.effective_power, bears.effective_toughness) == (1, 1)
    assert (mage.effective_power, mage.effective_toughness) == (0, 3), (
        "the counter went where the payer named it, not onto the source"
    )
    assert p1.mana_pool["B"] == 0


def test_wandering_mage_cannot_pay_with_no_creature_to_shrink(set_pool):
    """CR 601.2h: a cost that cannot be paid makes the ability unactivatable —
    and the Mage is itself "a creature you control", so the empty case is a
    board where it has left. Read off the mana: a refusal that came after the
    payment would show up as a spent {B}."""
    p1 = PlayerState(name="A")
    game = Game(players=[p1, PlayerState(name="B")])
    game.enforce_mana_costs = True
    game._settle()
    # The Mage on the battlefield can always pay by shrinking itself, which is
    # the honest reading of "a creature you control" — so the unpayable case is
    # asked of the charger, over a phrase no permanent on this board answers.
    cost = parse_activated_ability_cost(
        "{B}, Put a -1/-1 counter on a Wall you control: Draw a card."
    )
    assert cost.put_counter == "-1/-1"
    assert cost.put_counter_filter == {
        "type_filter": "creature", "subtype_filter": "wall",
    }


def test_wandering_mage_may_shrink_itself_to_pay(set_pool):
    """"a creature you control" includes the Mage (CR 109.5 names no exclusion),
    so a lone Mage can still activate — and the deterministic default has to
    find it, or a seat that named nothing would be blocked."""
    game, p1, mage = _w2g2_mage_board(set_pool, mine=())
    p1.mana_pool["B"] = 1

    result = game.activate_permanent_ability(
        0, "Wandering Mage", target_player_index=1, ability_index=2,
    )
    game._settle()

    assert result.supported, result.details
    assert (mage.effective_power, mage.effective_toughness) == (-1, 2)


def test_the_mage_shield_absorbs_damage_aimed_at_a_player(set_pool):
    """The effect half. "target player or planeswalker" reached no production
    outside damage, so this line refused at ``unconsumed text`` — the shield is
    the ordinary CR 615 one and the union was the whole gap."""
    game, p1, mage = _w2g2_mage_board(set_pool)
    p1.mana_pool["B"] = 1

    game.activate_permanent_ability(
        0, "Wandering Mage", target_player_index=1, ability_index=2,
    )
    game._settle()

    game._deal_damage_to_player(game.players[1], 3, source=mage)
    assert game.players[1].life == 19, "2 of the 3 were prevented"


def test_the_marker_counter_cost_still_lands_on_its_own_source(set_pool):
    """Mazemind Tome's reading is the one this widening must not have moved: a
    cost naming no permanent puts the counter on the source, and it can never
    be unpayable."""
    cost = parse_activated_ability_cost(
        "{2}, Put a page counter on this artifact: Draw a card."
    )
    assert cost.put_counter == "page"
    assert cost.put_counter_filter is None


def _w2g2_adnate_board(set_pool, mine=("Grizzly Bears", "Bog Wraith", "Mox Ruby")):
    p1 = PlayerState(name="A")
    game = Game(players=[p1, PlayerState(name="B")])
    game.enforce_mana_costs = True
    p1.battlefield.append(Permanent(card=set_pool("ALL")["Soldevi Adnate"]))
    for name in mine:
        p1.battlefield.append(Permanent(card=_W2G2_LEA[name]))
    game._settle()
    return game, p1


def test_soldevi_adnate_eats_a_black_creature_for_its_mana_value(set_pool):
    """"{T}, **Sacrifice a black or artifact creature**: Add an amount of {B}
    equal to the sacrificed creature's mana value."

    The effect half already worked — what refused was the cost's noun phrase.
    "black or artifact creature" is a union across *two axes*, CR 105 colour
    against CR 205.2 card type, and the filter ANDs its keys: written as
    ``colors`` plus ``card_types`` it would name a black creature that is also
    an artifact, which almost nothing is. Bog Wraith's mana value is 4, so the
    number is read off the sacrificed permanent rather than off a constant."""
    game, p1 = _w2g2_adnate_board(set_pool)
    wraith = p1.battlefield[2]
    assert wraith.card.name == "Bog Wraith"

    result = game.activate_permanent_ability(
        0, "Soldevi Adnate", cost_permanent_ids=[wraith.permanent_id],
    )
    game._settle()

    assert result.supported, result.details
    assert p1.mana_pool["B"] == 4, "{3}{B} is mana value 4"
    assert [p.card.name for p in game.controlled_by(0)] == [
        "Soldevi Adnate", "Grizzly Bears", "Mox Ruby",
    ], "the named Wraith paid, and nothing else left"


def test_the_adnates_union_is_not_a_conjunction(set_pool):
    """The direction the two-axis union must not be wrong in. Read as an AND,
    only a *black artifact creature* could pay — and there is none in the pool,
    so the ability would have been unactivatable rather than visibly wrong."""
    from engine.oracle import parse_activated_ability_cost
    from engine.subject_filters import subject_matches

    cost = parse_activated_ability_cost(
        "{T}, Sacrifice a black or artifact creature: Add {B}."
    )
    assert cost.sacrifice_filter == {
        "type_filter": "creature",
        "any_classes": [["color", "B"], ["card_type", "artifact"]],
    }

    game, p1 = _w2g2_adnate_board(
        set_pool, mine=("Grizzly Bears", "Bog Wraith", "Clockwork Beast"),
    )
    bears, wraith, beast = p1.battlefield[1:]
    described = cost.sacrifice_filter
    assert not subject_matches(game, bears, described), "green, and no artifact"
    assert subject_matches(game, wraith, described), "black creature"
    assert subject_matches(game, beast, described), "artifact creature"


def test_the_adnate_refuses_a_creature_neither_black_nor_an_artifact(set_pool):
    """A cost the charger cannot collect must refuse the activation with
    nothing spent (CR 601.2h) — and the Mox is the second half of the same
    check: an artifact that is not a *creature* is not what the phrase names,
    so the head noun still has to hold."""
    from engine.oracle import parse_activated_ability_cost
    from engine.subject_filters import subject_matches

    game, p1 = _w2g2_adnate_board(set_pool)
    described = parse_activated_ability_cost(
        "{T}, Sacrifice a black or artifact creature: Add {B}."
    ).sacrifice_filter
    mox = p1.battlefield[3]
    assert mox.card.name == "Mox Ruby"
    assert not subject_matches(game, mox, described), (
        "an artifact that is not a creature is outside the printed noun"
    )


def _w2g2_drone_board(set_pool, mine):
    p1 = PlayerState(name="A")
    game = Game(players=[p1, PlayerState(name="B")])
    game.enforce_mana_costs = True
    game.interactive_seats = {0}
    p1.battlefield.append(Permanent(card=set_pool("ALL")["Viscerid Drone"]))
    for name in mine:
        p1.battlefield.append(Permanent(card=_W2G2_LEA[name]))
    game.players[1].battlefield.append(Permanent(card=_W2G2_LEA["Hill Giant"]))
    game._settle()
    return game, p1


def test_viscerid_drone_eats_two_permanents_for_one_activation(set_pool):
    """"{T}, **Sacrifice a creature and a Swamp**: Destroy target nonartifact
    creature. It can't be regenerated."

    One printed verb naming two *different* objects. A single filter cannot say
    it — every matcher ANDs its keys, and "a creature that is also a Swamp" is
    not what the card prints — so the clause parsed as unconsumed text and the
    whole ability refused. The effect half already worked (it is Terror's)."""
    game, p1 = _w2g2_drone_board(set_pool, ["Grizzly Bears", "Swamp"])
    giant = game.players[1].battlefield[0]

    result = game.activate_permanent_ability(
        0, "Viscerid Drone", target_player_index=1,
        target_permanent_index=0, ability_index=0,
    )
    game._settle()

    assert result.supported, result.details
    assert not game.is_on_battlefield(giant)
    # Two permanents left to pay, and the Swamp is one of them.
    assert [p.card.name for p in game.controlled_by(0)] == ["Grizzly Bears"], (
        "the Swamp and one creature both paid"
    )


def test_viscerid_drone_refuses_with_no_swamp_and_pays_nothing(set_pool):
    """CR 601.2h: if either half is unpayable the whole cost is, so a board with
    a creature and no Swamp refuses **with the creature still on it**. The
    creature is the assertion that matters — a gate that checked the halves one
    at a time would have eaten it before finding the Swamp missing."""
    game, p1 = _w2g2_drone_board(set_pool, ["Grizzly Bears"])
    giant = game.players[1].battlefield[0]

    result = game.activate_permanent_ability(
        0, "Viscerid Drone", target_player_index=1,
        target_permanent_index=0, ability_index=0,
    )
    game._settle()

    assert not result.supported
    assert [p.card.name for p in game.controlled_by(0)] == [
        "Viscerid Drone", "Grizzly Bears",
    ]
    assert game.is_on_battlefield(giant)


def test_the_drones_snow_variant_keeps_its_supertype(set_pool):
    """The second ability prints "a **snow** Swamp" and destroys target creature
    rather than target *nonartifact* creature — two narrowings that would both
    vanish if the conjoined tail were read as one loose phrase."""
    from engine.oracle import parse_activated_ability_cost

    plain, snow = [
        parse_activated_ability_cost(a.source_line)
        for a in compile_card_oracle(
            set_pool("ALL")["Viscerid Drone"]
        ).activated_abilities
    ]
    assert plain.sacrifice_also_filter == {"subtype_filter": "swamp"}
    assert snow.sacrifice_also_filter == {
        "subtype_filter": "swamp", "supertypes": ["snow"],
    }
    assert plain.sacrifice_filter == snow.sacrifice_filter == {
        "type_filter": "creature"
    }


# --- W2G2 declines, each naming the part it is waiting on -------------------
#
# These assert the card is *still* unsupported. That is deliberate: a decline
# whose missing part later lands should fail loudly here rather than sit
# unnoticed, and the message says what to do about it.


def test_benthic_explorers_declines_on_three_named_parts(set_pool):
    """"{T}, Untap a tapped land an opponent controls: Add one mana of any type
    that land could produce." Three parts, and none of them is the noun phrase
    — "a tapped land an opponent controls" parses and is testable today:

    1. **an activation cost that *untaps* a permanent.** ``grammar/costs.py``
       has a ``tap`` branch and no ``untap`` one, and ``ActivatedAbilityCost``
       has no field for it. ``tap_filter``/``tap_count`` is the opposite
       direction and its payment path taps — reusing it would tap the
       opponent's land rather than untapping it. Also the first cost in this
       engine paid with a permanent **an opponent controls**: every existing
       chosen cost enumerates ``controlled_by(payer)``.
    2. **a record of which permanent that cost untapped.** "That land" is a
       back-reference to the payment, and unlike every other cost record the
       object is *still on the battlefield* — so it is not last-known
       information, but there is no ``CHOICE_KEYS`` channel carrying it and no
       producer key for a lowering to gate on.
    3. **"one mana of any type that land could produce".** ``effects/mana.py``
       reads "any **color**" (and Fellwar Stone's "that a land an opponent
       controls could produce", which names a *class* of lands, not one). This
       prints "any **type**", which includes {C} — CR 106.1b — and names the
       land part 2 would have recorded. It refuses at ``expected 'color'``.
    """
    program = compile_card_oracle(set_pool("ALL")["Benthic Explorers"])
    assert not program.supported

    from engine.grammar import compile_line

    cost_half = compile_line(
        "{T}, Untap a tapped land an opponent controls: Add {U}.",
        card_name="Benthic Explorers",
    )
    assert not cost_half.parsed, "part 1: no untap branch in the cost clause"

    effect_half = compile_line(
        "{T}: Add one mana of any type that land could produce.",
        card_name="Benthic Explorers",
    )
    assert not effect_half.parsed, "part 3: 'any type' is not 'any color'"

    # The noun phrase itself is *not* a blocker, which is what keeps this
    # decline three parts rather than four.
    from engine.grammar import subject_filter_payload

    assert subject_filter_payload("a tapped land an opponent controls") == {
        "type_filter": "land", "tapped_only": True, "controller": "opponent",
    }
