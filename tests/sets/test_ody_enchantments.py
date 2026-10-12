"""Odyssey enchantments.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ODY")` / `set_cards("ODY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.
from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.models import Permanent as _W1G1Permanent
from engine.oracle import compile_card_oracle as _w1g1_compile
from tests.helpers import resolve_stack as _w1g1_resolve_stack


def _w1g1_table(set_pool, hand=(), mana=None):
    """A two-seat game with mana costs enforced; *hand* names Odyssey cards
    (or Alpha ones) in seat 0's hand."""
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _W1G1Game(players=[
        _W1G1PlayerState(
            "Caster", library=[lea["Forest"]] * 10,
            hand=[ody[name] if name in ody else lea[name] for name in hand],
        ),
        _W1G1PlayerState("Opponent", library=[lea["Forest"]] * 10),
    ])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(mana or {})
    return game  # _w1g1_table (enchantments)


def _w1g1_put(game, set_pool, seat, name):
    """*name* (Odyssey first, then Alpha) onto *seat*'s battlefield, able to
    act this turn."""
    ody = set_pool("ODY")
    card = ody[name] if name in ody else set_pool("LEA")[name]
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g1_put (enchantments)


def _w1g1_graveyard(game, set_pool, seat, count):
    """Give *seat* exactly *count* cards in its graveyard, then let the
    state-based sweep recompute (CR 611.3a)."""
    game.players[seat].graveyard[:] = [set_pool("LEA")["Forest"]] * count
    game.check_state_based_actions()  # _w1g1_graveyard (enchantments)


def _w1g1_pt(permanent):
    return (permanent.effective_power, permanent.effective_toughness)


def _w1g1_enchant(game, name, host):
    """Cast the Aura *name* from seat 0's hand onto *host* and resolve it."""
    result = game.cast_from_hand(0, name, target_permanent_ids=[host.permanent_id])
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    game.check_state_based_actions()
    (aura,) = [p for p in game.all_permanents() if p.card.name == name]
    assert aura.metadata.get("attached_to") is host
    return aura  # _w1g1_enchant (enchantments)


def test_w1g1_kamahls_desire_counts_the_graveyard_of_whoever_controls_the_aura(
    set_pool,
):
    """"Enchanted creature has first strike. Threshold — Enchanted creature
    gets +3/+0 as long as there are seven or more cards in your graveyard."
    Cast on an *opponent's* creature: first strike at once, and the +3/+0
    follows the Aura's controller's graveyard (CR 109.5) — seven cards in the
    creature's controller's graveyard do nothing."""
    assert _w1g1_compile(set_pool("ODY")["Kamahl's Desire"]).supported
    game = _w1g1_table(set_pool, ["Kamahl's Desire"], {"R": 2})
    theirs = _w1g1_put(game, set_pool, 1, "Grizzly Bears")
    _w1g1_enchant(game, "Kamahl's Desire", theirs)
    assert game._has_keyword(theirs, "first strike") and _w1g1_pt(theirs) == (2, 2)

    _w1g1_graveyard(game, set_pool, 1, 7)
    assert _w1g1_pt(theirs) == (2, 2)

    _w1g1_graveyard(game, set_pool, 1, 0)
    _w1g1_graveyard(game, set_pool, 0, 7)
    assert _w1g1_pt(theirs) == (5, 2)

    _w1g1_graveyard(game, set_pool, 0, 6)
    assert _w1g1_pt(theirs) == (2, 2) and game._has_keyword(theirs, "first strike")


def test_w1g1_aboshans_desire_adds_shroud_to_flying_only_with_threshold(set_pool):
    """"Enchanted creature has flying. Threshold — Enchanted creature has
    shroud as long as there are seven or more cards in your graveyard." Flying
    is unconditional; shroud comes and goes with the count, and while it is
    there a spell aimed at the creature is refused with nothing paid."""
    assert _w1g1_compile(set_pool("ODY")["Aboshan's Desire"]).supported
    game = _w1g1_table(
        set_pool, ["Aboshan's Desire", "Lightning Bolt"], {"U": 1, "R": 1},
    )
    bears = _w1g1_put(game, set_pool, 0, "Grizzly Bears")
    _w1g1_enchant(game, "Aboshan's Desire", bears)
    assert game._has_keyword(bears, "flying") and not game._has_keyword(bears, "shroud")

    _w1g1_graveyard(game, set_pool, 0, 7)
    assert game._has_keyword(bears, "flying") and game._has_keyword(bears, "shroud")
    refused = game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    )
    assert not refused.supported
    assert game.players[0].mana_pool["R"] == 1, "nothing was paid for the refused cast"

    _w1g1_graveyard(game, set_pool, 0, 6)
    assert game._has_keyword(bears, "flying") and not game._has_keyword(bears, "shroud")
    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported


# --- the rest of the Desires, and the two enchantments that dropped a line ---


def _w1g1_slot(game, seat, permanent):
    return list(game.controlled_by(seat)).index(permanent)  # _w1g1_slot (enchantments)


def _w1g1_to_declare_attackers(game, seat=0, graveyards=None):
    """*seat*'s turn at the declare-attackers step, nobody summoning sick.
    *graveyards* is set before the turn starts, so the turn's own recompute is
    what reads it."""
    for index, count in (graveyards or {}).items():
        filler = game.players[index].library[0]
        game.players[index].graveyard[:] = [filler] * count
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(seat)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers", game.current_step  # _w1g1_to_declare_attackers (enchantments)


def _w1g1_finish_combat(game):
    for _ in range(8):
        if game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
        _w1g1_resolve_stack(game)
    assert game.current_step == "postcombat_main", game.current_step  # _w1g1_finish_combat (enchantments)


def _w1g1_abilities(permanent):
    program = _w1g1_compile(permanent.effective_card)
    return (
        [trigger.source_line for trigger in program.triggered_abilities],
        [ability.source_line for ability in program.activated_abilities],
    )  # _w1g1_abilities (enchantments)


def _w1g1_granted_index(permanent, words):
    """The index of the activated ability on *permanent* whose line carries
    *words* — an Aura's quoted grant, found as the game finds it."""
    lines = _w1g1_abilities(permanent)[1]
    (index,) = [i for i, line in enumerate(lines) if words in line.lower()]
    return index  # _w1g1_granted_index (enchantments)


def test_w1g1_kirtars_desire_stops_attacks_always_and_blocks_with_threshold(set_pool):
    """Kirtar's Desire: the enchanted creature can't attack, and with
    threshold it can't block either. The attack ban is there from the moment
    the Aura attaches; the block ban follows the *Aura's* controller's
    graveyard (CR 109.5), driven through the declare-blockers step."""
    assert _w1g1_compile(set_pool("ODY")["Kirtar's Desire"]).supported
    blocks = []
    for count in (6, 7):
        game = _w1g1_table(set_pool, ["Kirtar's Desire"], {"W": 1})
        theirs = _w1g1_put(game, set_pool, 1, "Grizzly Bears")
        mine = _w1g1_put(game, set_pool, 0, "Hill Giant")
        _w1g1_enchant(game, "Kirtar's Desire", theirs)
        assert not game.can_attack(theirs, 0)
        _w1g1_to_declare_attackers(game, graveyards={0: count})
        slot = _w1g1_slot(game, 0, mine)
        assert game.declare_attackers(0, [slot])[0]
        game.advance_combat_phase()
        blocks.append(
            game.declare_blockers(1, {_w1g1_slot(game, 1, theirs): slot})[0]
        )

    assert blocks == [True, False]


def test_w1g1_kirtars_desire_ignores_the_enchanted_creatures_controllers_graveyard(
    set_pool,
):
    """Seven cards in the *creature's* controller's graveyard are not the
    Aura's controller's: the enchanted Bears still blocks."""
    game = _w1g1_table(set_pool, ["Kirtar's Desire"], {"W": 1})
    theirs = _w1g1_put(game, set_pool, 1, "Grizzly Bears")
    mine = _w1g1_put(game, set_pool, 0, "Hill Giant")
    _w1g1_enchant(game, "Kirtar's Desire", theirs)
    _w1g1_to_declare_attackers(game, graveyards={1: 9})
    slot = _w1g1_slot(game, 0, mine)
    assert game.declare_attackers(0, [slot])[0]
    game.advance_combat_phase()

    assert game.declare_blockers(1, {_w1g1_slot(game, 1, theirs): slot})[0]


def test_w1g1_setons_desire_is_a_lure_with_threshold(set_pool):
    """Seton's Desire: +2/+2 always, and with threshold all creatures able to
    block the enchanted creature do so. Below threshold the defender may
    decline to block the 4/4 Bears; at seven cards declining is refused and
    both creatures must block it."""
    assert _w1g1_compile(set_pool("ODY")["Seton's Desire"]).supported
    outcomes = []
    for count in (6, 7):
        game = _w1g1_table(set_pool, ["Seton's Desire"], {"G": 3})
        mine = _w1g1_put(game, set_pool, 0, "Grizzly Bears")
        giant = _w1g1_put(game, set_pool, 1, "Hill Giant")
        zombies = _w1g1_put(game, set_pool, 1, "Scathe Zombies")
        _w1g1_enchant(game, "Seton's Desire", mine)
        _w1g1_to_declare_attackers(game, graveyards={0: count})
        assert _w1g1_pt(mine) == (4, 4)
        slot = _w1g1_slot(game, 0, mine)
        assert game.declare_attackers(0, [slot])[0]
        game.advance_combat_phase()
        declined = game.declare_blockers(1, {})[0]
        both = declined or game.declare_blockers(1, {
            _w1g1_slot(game, 1, giant): slot, _w1g1_slot(game, 1, zombies): slot,
        })[0]
        outcomes.append((declined, both))

    assert outcomes == [(True, True), (False, True)]


def test_w1g1_patriarchs_desire_doubles_with_threshold_and_can_kill_its_host(set_pool):
    """Patriarch's Desire: +2/-2, and with threshold an additional +2/-2. A
    3/3 Hill Giant under it is a 5/1; the seventh card in the Aura's
    controller's graveyard makes it 7/-1, the Giant dies as a state-based
    action (CR 704.5f) and the Aura follows it (CR 704.5m)."""
    assert _w1g1_compile(set_pool("ODY")["Patriarch's Desire"]).supported
    game = _w1g1_table(set_pool, ["Patriarch's Desire"], {"B": 4})
    giant = _w1g1_put(game, set_pool, 1, "Hill Giant")
    _w1g1_enchant(game, "Patriarch's Desire", giant)
    assert _w1g1_pt(giant) == (5, 1) and game.is_on_battlefield(giant)

    _w1g1_graveyard(game, set_pool, 0, 7)

    assert not game.is_on_battlefield(giant)
    assert [card.name for card in game.players[1].graveyard] == ["Hill Giant"]
    assert game.players[0].graveyard[-1].name == "Patriarch's Desire"


def test_w1g1_patriarchs_desire_on_a_bigger_creature_shows_both_deltas(set_pool):
    """On a 0/8 Wall of Stone the two contributions are visible side by side
    and neither is lethal: 2/6 without threshold, 4/4 with it, 2/6 again when
    a card leaves."""
    game = _w1g1_table(set_pool, ["Patriarch's Desire"], {"B": 4})
    wall = _w1g1_put(game, set_pool, 0, "Wall of Stone")
    _w1g1_enchant(game, "Patriarch's Desire", wall)

    seen = []
    for count in (6, 7, 6):
        _w1g1_graveyard(game, set_pool, 0, count)
        seen.append(_w1g1_pt(wall))

    assert seen == [(2, 6), (4, 4), (2, 6)]


def test_w1g1_divine_sacrament_gives_white_creatures_a_second_bonus_with_threshold(
    set_pool,
):
    """Divine Sacrament: white creatures get +1/+1, and with threshold an
    additional +1/+1. *Every* white creature, an opponent's too; a green one
    gets neither; and the second bonus follows the Sacrament's controller's
    graveyard. The sentence compiled "supported" on the first line alone
    before this."""
    game = _w1g1_table(set_pool)
    _w1g1_put(game, set_pool, 0, "Divine Sacrament")
    mine = _w1g1_put(game, set_pool, 0, "White Knight")
    theirs = _w1g1_put(game, set_pool, 1, "White Knight")
    bears = _w1g1_put(game, set_pool, 0, "Grizzly Bears")

    seen = []
    for count in (6, 7, 6):
        _w1g1_graveyard(game, set_pool, 0, count)
        seen.append((_w1g1_pt(mine), _w1g1_pt(theirs), _w1g1_pt(bears)))

    assert seen == [
        ((3, 3), (3, 3), (2, 2)), ((4, 4), (4, 4), (2, 2)), ((3, 3), (3, 3), (2, 2)),
    ]
    _w1g1_graveyard(game, set_pool, 1, 7)
    assert _w1g1_pt(theirs) == (3, 3), "the opponent's graveyard is not the Sacrament's"


def test_w1g1_a_white_creature_dies_when_divine_sacrament_loses_threshold(set_pool):
    """The card's ruling of 2022-12-08: nonlethal damage marked on a white
    creature becomes lethal when the count falls below seven. A 4/4 White
    Knight carrying 3 damage dies as the eighth card leaves."""
    game = _w1g1_table(set_pool)
    _w1g1_put(game, set_pool, 0, "Divine Sacrament")
    knight = _w1g1_put(game, set_pool, 0, "White Knight")
    _w1g1_graveyard(game, set_pool, 0, 7)
    game._mark_damage_on_permanent(knight, 3, source=None)
    game.check_state_based_actions()
    assert game.is_on_battlefield(knight)

    game.players[0].graveyard.pop()
    game.check_state_based_actions()

    assert not game.is_on_battlefield(knight)


def test_w1g1_decaying_soil_exiles_a_card_from_its_controllers_graveyard_each_upkeep(
    set_pool,
):
    """Decaying Soil's upkeep trigger exiles a card from its controller's
    graveyard — one card, their own pile, and nothing where the pile is
    empty."""
    game = _w1g1_table(set_pool)
    _w1g1_put(game, set_pool, 0, "Decaying Soil")
    _w1g1_graveyard(game, set_pool, 0, 3)
    _w1g1_graveyard(game, set_pool, 1, 3)
    game.active_player_index = 0

    game.resolve_upkeep(0)
    _w1g1_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert len(game.players[0].graveyard) == 2 and len(game.players[0].exile) == 1
    assert len(game.players[1].graveyard) == 3


def test_w1g1_decaying_soil_returns_a_dead_creature_for_one_mana_with_threshold(
    set_pool,
):
    """Threshold: Decaying Soil has a trigger that lets its controller pay
    {1} to return a nontoken creature put into their graveyard from the
    battlefield. With threshold and the mana, a Grizzly Bears that dies (to a
    Lightning Bolt, paid for with the red) comes back to its owner's hand and
    the {1} is spent; with threshold and no mana the offer cannot be taken and
    the Bears stays in the graveyard. Both sentences of the quote were
    unclaimed before this."""
    assert _w1g1_compile(set_pool("ODY")["Decaying Soil"]).supported
    outcomes = []
    for spare in (1, 0):
        game = _w1g1_table(set_pool, ["Lightning Bolt"], {"R": 1, "C": spare})
        soil = _w1g1_put(game, set_pool, 0, "Decaying Soil")
        bears = _w1g1_put(game, set_pool, 0, "Grizzly Bears")
        _w1g1_graveyard(game, set_pool, 0, 8)
        assert len(_w1g1_abilities(soil)[0]) == 2
        assert game.cast_from_hand(
            0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
        ).supported
        _w1g1_resolve_stack(game)
        game.check_state_based_actions()
        _w1g1_resolve_stack(game)
        game.auto_resolve_pending_choices()
        _w1g1_resolve_stack(game)
        outcomes.append((
            [card.name for card in game.players[0].hand],
            "Grizzly Bears" in [card.name for card in game.players[0].graveyard],
            game.players[0].mana_pool["C"],
        ))

    assert outcomes == [(["Grizzly Bears"], False, 0), ([], True, 0)]


def test_w1g1_decaying_soil_has_no_second_ability_below_threshold(set_pool):
    """Below seven cards the Soil has only its upkeep trigger, and a creature
    that dies is not offered back however much mana is floating."""
    game = _w1g1_table(set_pool, ["Lightning Bolt"], {"R": 1, "C": 3})
    soil = _w1g1_put(game, set_pool, 0, "Decaying Soil")
    bears = _w1g1_put(game, set_pool, 0, "Grizzly Bears")
    _w1g1_graveyard(game, set_pool, 0, 4)
    assert len(_w1g1_abilities(soil)[0]) == 1

    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g1_resolve_stack(game)
    game.check_state_based_actions()
    _w1g1_resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert game.players[0].hand == []
    assert game.players[0].mana_pool["C"] == 3


def test_w1g1_the_creature_that_reaches_threshold_does_not_trigger_decaying_soil(
    set_pool,
):
    """The card's ruling of 2004-10-04: "The ability in Threshold will trigger
    only if Threshold was met before the creature goes to the graveyard. So
    the one that causes Threshold to be met will not trigger the ability."
    With six cards, the dying Bears is the seventh — and stays there."""
    game = _w1g1_table(set_pool, ["Terror"], {"B": 1, "C": 2})
    _w1g1_put(game, set_pool, 0, "Decaying Soil")
    bears = _w1g1_put(game, set_pool, 0, "Grizzly Bears")
    _w1g1_graveyard(game, set_pool, 0, 6)

    assert game.cast_from_hand(
        0, "Terror", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g1_resolve_stack(game)
    game.auto_resolve_pending_choices()
    _w1g1_resolve_stack(game)

    assert game.players[0].hand == []
    assert "Grizzly Bears" in [card.name for card in game.players[0].graveyard]
    assert game.players[0].mana_pool["C"] == 1


# --- the Auras that compiled on arrival, each given a game ------------------


def test_w1g1_primal_frenzy_gives_trample_for_as_long_as_it_is_attached(set_pool):
    game = _w1g1_table(set_pool, ["Primal Frenzy"], {"G": 1})
    bears = _w1g1_put(game, set_pool, 0, "Grizzly Bears")
    aura = _w1g1_enchant(game, "Primal Frenzy", bears)
    assert game._has_keyword(bears, "trample")

    game.remove_from_battlefield(aura)
    game.check_state_based_actions()

    assert not game._has_keyword(bears, "trample")


def test_w1g1_persuasion_takes_a_creature_for_as_long_as_it_is_attached(set_pool):
    """Persuasion: you control enchanted creature. Its picker offers the
    opponent's creature, the Hill Giant changes sides as the Aura resolves,
    and goes home when the Aura leaves."""
    game = _w1g1_table(set_pool, ["Persuasion"], {"U": 5})
    giant = _w1g1_put(game, set_pool, 1, "Hill Giant")
    spec = game.cast_target_spec(0, set_pool("ODY")["Persuasion"])
    assert [(t["seat"], t["name"]) for t in spec["valid_targets"]] == [(1, "Hill Giant")]

    aura = _w1g1_enchant(game, "Persuasion", giant)
    assert game.controller_index_of(giant) == 0

    game.remove_from_battlefield(aura)
    game.check_state_based_actions()
    assert game.controller_index_of(giant) == 1


def test_w1g1_psionic_gift_makes_its_creature_a_pinger(set_pool):
    """Psionic Gift: the enchanted creature can tap to deal 1 damage to any
    target. The ability is the creature's: it taps the Bears, it kills a Birds
    of Paradise, and aimed at a player it takes one life."""
    game = _w1g1_table(set_pool, ["Psionic Gift"], {"U": 2})
    bears = _w1g1_put(game, set_pool, 0, "Grizzly Bears")
    birds = _w1g1_put(game, set_pool, 1, "Birds of Paradise")
    _w1g1_enchant(game, "Psionic Gift", bears)
    assert len(_w1g1_abilities(bears)[1]) == 1

    result = game.activate_permanent_ability(
        0, "Grizzly Bears", ability_index=0, target_permanent_ids=[birds.permanent_id],
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    game.check_state_based_actions()
    assert bears.tapped and not game.is_on_battlefield(birds)

    bears.tapped = False
    assert game.activate_permanent_ability(
        0, "Grizzly Bears", ability_index=0, target_player_index=1,
    ).supported
    _w1g1_resolve_stack(game)
    assert game.players[1].life == 19


def test_w1g1_immobilizing_ink_keeps_a_creature_tapped_until_its_controller_pays(
    set_pool,
):
    """Immobilizing Ink: the enchanted creature doesn't untap during its
    controller's untap step, and has an ability — {1} and a discard — that
    untaps it. The ability is the *creature's*, so the creature's controller
    is who may pay, not the player who cast the Ink."""
    game = _w1g1_table(set_pool, ["Immobilizing Ink"], {"U": 2})
    giant = _w1g1_put(game, set_pool, 1, "Hill Giant")
    _w1g1_enchant(game, "Immobilizing Ink", giant)
    assert len(_w1g1_abilities(giant)[1]) == 1
    giant.tapped = True
    game.active_player_index = 1

    game.resolve_untap_step(1)
    assert giant.tapped

    game.players[1].hand.append(set_pool("LEA")["Forest"])
    game.players[1].mana_pool["C"] = 1
    result = game.activate_permanent_ability(1, "Hill Giant", ability_index=0)
    assert result.supported, result.details
    _w1g1_resolve_stack(game)

    assert not giant.tapped
    assert game.players[1].hand == [] and game.players[1].mana_pool["C"] == 0


def test_w1g1_druids_call_makes_a_squirrel_for_each_damage_its_creature_takes(
    set_pool,
):
    """Druid's Call: whenever the enchanted creature is dealt damage, its
    controller creates that many 1/1 green Squirrel tokens. A Lightning Bolt
    at an opponent's enchanted Craw Wurm makes three Squirrels **for the
    Wurm's controller** — not for the player who cast the Aura.

    This card arrived compiling supported and making none: "that many" read a
    scratchpad key no damage event writes."""
    game = _w1g1_table(set_pool, ["Druid's Call", "Lightning Bolt"], {"G": 2})
    wurm = _w1g1_put(game, set_pool, 1, "Craw Wurm")
    _w1g1_enchant(game, "Druid's Call", wurm)
    game.players[0].mana_pool["R"] = 1

    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[wurm.permanent_id],
    ).supported
    _w1g1_resolve_stack(game)
    game.check_state_based_actions()
    _w1g1_resolve_stack(game)

    squirrels = [p for p in game.controlled_by(1) if p.has_type("squirrel")]
    assert len(squirrels) == 3
    assert all(_w1g1_pt(s) == (1, 1) and s.effective_colors == {"G"} for s in squirrels)
    assert not [p for p in game.controlled_by(0) if p.has_type("squirrel")]


def test_w1g1_druids_call_counts_combat_damage_too(set_pool):
    """Blocked by a Grizzly Bears, the enchanted Hill Giant is dealt 2 and its
    controller gets two Squirrels."""
    game = _w1g1_table(set_pool, ["Druid's Call"], {"G": 2})
    giant = _w1g1_put(game, set_pool, 0, "Hill Giant")
    bears = _w1g1_put(game, set_pool, 1, "Grizzly Bears")
    _w1g1_enchant(game, "Druid's Call", giant)
    _w1g1_to_declare_attackers(game, seat=1)
    slot = _w1g1_slot(game, 1, bears)
    assert game.declare_attackers(1, [slot])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(0, {_w1g1_slot(game, 0, giant): slot})[0]
    _w1g1_finish_combat(game)

    assert len([p for p in game.controlled_by(0) if p.has_type("squirrel")]) == 2


def test_w1g1_squirrel_nest_enchants_a_land_and_lets_it_make_squirrels(set_pool):
    """Squirrel Nest: enchant land; the land can tap to create a 1/1 green
    Squirrel. A creature is not a legal host; the land's new ability taps it
    and makes the token, cannot be used again while tapped, and leaves with
    the Aura."""
    game = _w1g1_table(set_pool, ["Squirrel Nest"], {"G": 3})
    forest = _w1g1_put(game, set_pool, 0, "Forest")
    bears = _w1g1_put(game, set_pool, 0, "Grizzly Bears")
    assert not game.cast_from_hand(
        0, "Squirrel Nest", target_permanent_ids=[bears.permanent_id],
    ).supported
    nest = _w1g1_enchant(game, "Squirrel Nest", forest)
    index = _w1g1_granted_index(forest, "squirrel")

    assert game.activate_permanent_ability(0, "Forest", ability_index=index).supported
    _w1g1_resolve_stack(game)
    assert forest.tapped
    assert len([p for p in game.controlled_by(0) if p.has_type("squirrel")]) == 1
    assert not game.activate_permanent_ability(0, "Forest", ability_index=index).supported

    game.remove_from_battlefield(nest)
    game.check_state_based_actions()
    assert _w1g1_abilities(forest)[1] == []


def test_w1g1_caustic_tar_lets_its_land_drain_three_life(set_pool):
    """Caustic Tar: the enchanted land can tap to make target player lose 3
    life — either player."""
    game = _w1g1_table(set_pool, ["Caustic Tar"], {"B": 6})
    swamp = _w1g1_put(game, set_pool, 0, "Swamp")
    _w1g1_enchant(game, "Caustic Tar", swamp)
    index = _w1g1_granted_index(swamp, "loses 3 life")

    assert game.activate_permanent_ability(
        0, "Swamp", ability_index=index, target_player_index=1,
    ).supported
    _w1g1_resolve_stack(game)
    swamp.tapped = False
    assert game.activate_permanent_ability(
        0, "Swamp", ability_index=index, target_player_index=0,
    ).supported
    _w1g1_resolve_stack(game)

    assert [player.life for player in game.players] == [17, 17]


def test_w1g1_animal_boneyard_trades_a_creature_for_its_toughness_in_life(set_pool):
    """Animal Boneyard: the enchanted land can tap, with a creature
    sacrificed, to gain life equal to that creature's toughness. The *named*
    creature is the one sacrificed (a 3/3 Hill Giant, for 3), and with no
    creature to sacrifice the ability is refused with the land untapped."""
    game = _w1g1_table(set_pool, ["Animal Boneyard"], {"W": 3})
    plains = _w1g1_put(game, set_pool, 0, "Plains")
    giant = _w1g1_put(game, set_pool, 0, "Hill Giant")
    bears = _w1g1_put(game, set_pool, 0, "Grizzly Bears")
    _w1g1_enchant(game, "Animal Boneyard", plains)
    index = _w1g1_granted_index(plains, "sacrifice a creature")

    result = game.activate_permanent_ability(
        0, "Plains", ability_index=index, cost_permanent_ids=[giant.permanent_id],
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    assert game.players[0].life == 23
    assert game.is_on_battlefield(bears) and not game.is_on_battlefield(giant)

    plains.tapped = False
    game.remove_from_battlefield(bears)
    refused = game.activate_permanent_ability(0, "Plains", ability_index=index)
    assert not refused.supported and not plains.tapped


def test_w1g1_chamber_of_manipulation_borrows_a_creature_for_a_turn(set_pool):
    """Chamber of Manipulation: the enchanted land can tap, with a discard, to
    gain control of target creature until end of turn. The card is discarded,
    the Hill Giant changes sides without haste (the card's ruling of
    2004-10-04: it can't attack the turn it is taken), and goes home at
    cleanup; with no card to discard the ability is refused, land untapped."""
    game = _w1g1_table(set_pool, ["Chamber of Manipulation", "Forest"], {"U": 4})
    island = _w1g1_put(game, set_pool, 0, "Island")
    giant = _w1g1_put(game, set_pool, 1, "Hill Giant")
    _w1g1_enchant(game, "Chamber of Manipulation", island)
    index = _w1g1_granted_index(island, "gain control")
    giant.metadata.pop("summoning_sickness_turn", None)

    result = game.activate_permanent_ability(
        0, "Island", ability_index=index, target_permanent_ids=[giant.permanent_id],
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    game.check_state_based_actions()
    assert game.controller_index_of(giant) == 0
    assert [card.name for card in game.players[0].graveyard] == ["Forest"]
    assert not game.can_attack(giant, 1)

    game.resolve_cleanup_step(0)
    game.check_state_based_actions()
    assert game.controller_index_of(giant) == 1

    island.tapped = False
    refused = game.activate_permanent_ability(
        0, "Island", ability_index=index, target_permanent_ids=[giant.permanent_id],
    )
    assert not refused.supported and not island.tapped

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

import pytest as _w1g4_pytest

from engine import Game as _w1g4_Game, PlayerState as _w1g4_PlayerState
from engine.models import Permanent as _w1g4_Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from tests.helpers import _mk_card as _w1g4_mk_card
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_duel(set_pool, *, hand0=(), hand1=(), gy0=(), gy1=(), lib0=(),
               lib1=(), bf0=(), bf1=()):
    """A two-seat game with costs off, built from card names.

    Odyssey over Apocalypse over Alpha: the Shrines count a spell's name, the
    spells are furniture, and one of them is a split card.
    """
    pool = {**set_pool("LEA"), **set_pool("APC"), **set_pool("ODY")}
    seats = [
        _w1g4_PlayerState(
            name=f"P{seat}", life=20,
            hand=[pool[n] for n in hand], graveyard=[pool[n] for n in gy],
            library=[pool[n] for n in lib],
        )
        for seat, (hand, gy, lib) in enumerate(
            ((hand0, gy0, lib0), (hand1, gy1, lib1))
        )
    ]
    game = _w1g4_Game(players=seats)
    game.enforce_mana_costs = False
    for seat, names in enumerate((bf0, bf1)):
        for name in names:
            game._put_permanent_onto_battlefield(
                seat, _w1g4_Permanent(card=pool[name]), None
            )
    return game


def _w1g4_names(cards):
    return [card.name for card in cards]


def _w1g4_cast_bears_under(set_pool, shrine, **zones):
    """P1 casts Grizzly Bears while P0 controls *shrine*; the whole stack is
    resolved and every prompt it left is answered by its default."""
    hand1 = ["Grizzly Bears", *zones.pop("hand1", ())]
    game = _w1g4_duel(set_pool, hand1=hand1, bf0=[shrine], **zones)
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    assert [item.card.name for item in game.stack] == ["Grizzly Bears", shrine]
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    return game


# --- The Shrines: "…cards in all graveyards with the same name as that spell" -

def test_aven_shrine_gains_the_caster_a_life_per_same_named_card(set_pool):
    """Both graveyards are read, a card of another name is not, and it is the
    *caster* who gains — here the Shrine's controller's opponent."""
    game = _w1g4_cast_bears_under(
        set_pool, "Aven Shrine",
        gy0=["Grizzly Bears"], gy1=["Grizzly Bears", "Forest"],
    )
    assert (game.players[0].life, game.players[1].life) == (20, 22)
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]


def test_aven_shrine_with_no_such_card_gains_nothing(set_pool):
    game = _w1g4_cast_bears_under(set_pool, "Aven Shrine", gy0=["Forest"])
    assert game.players[1].life == 20


def test_cabal_shrine_makes_the_caster_choose_that_many_discards(set_pool):
    game = _w1g4_duel(
        set_pool, hand1=["Grizzly Bears", "Island", "Swamp", "Mountain"],
        gy0=["Grizzly Bears"], gy1=["Grizzly Bears"], bf0=["Cabal Shrine"],
    )
    game.interactive_seats.add(1)
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    game.resolve_top_of_stack()
    prompt = next(c for c in game.pending_choices if c.kind == "discard")
    assert prompt.player_index == 1 and prompt.data["count"] == 2
    game.auto_resolve_pending_choices()
    assert len(game.players[1].hand) == 1
    assert game.players[0].hand == []


def test_dwarven_shrine_deals_twice_the_count_to_the_caster(set_pool):
    game = _w1g4_cast_bears_under(
        set_pool, "Dwarven Shrine",
        gy0=["Grizzly Bears"], gy1=["Grizzly Bears", "Forest"],
    )
    assert (game.players[0].life, game.players[1].life) == (20, 16)


def test_nantuko_shrine_gives_the_caster_that_many_squirrels(set_pool):
    game = _w1g4_cast_bears_under(
        set_pool, "Nantuko Shrine", gy0=["Grizzly Bears"], gy1=["Grizzly Bears"],
    )
    theirs = sorted(p.card.name for p in game.controlled_by(1))
    assert theirs == ["Grizzly Bears", "Squirrel Token", "Squirrel Token"]
    squirrel = next(
        p for p in game.controlled_by(1) if p.card.name == "Squirrel Token"
    )
    assert (squirrel.effective_power, squirrel.effective_toughness) == (1, 1)
    assert [p.card.name for p in game.controlled_by(0)] == ["Nantuko Shrine"]


def test_cephalid_shrine_counters_a_spell_whose_price_goes_unpaid(set_pool):
    """Mana is enforced and the caster has nothing left to tap: {2} is owed for
    two Bears in graveyards, and the spell is countered."""
    game = _w1g4_duel(
        set_pool, hand1=["Grizzly Bears"], gy0=["Grizzly Bears"],
        gy1=["Grizzly Bears"], bf0=["Cephalid Shrine"], bf1=["Forest", "Forest"],
    )
    game.enforce_mana_costs = True
    game.active_player_index = 1
    for forest in list(game.controlled_by(1)):
        assert game.tap_land_for_mana(
            1, "Forest", "G", permanent_id=forest.permanent_id
        )
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert _w1g4_names(game.players[1].graveyard) == ["Grizzly Bears"] * 2
    assert [p.card.name for p in game.controlled_by(1)] == ["Forest", "Forest"]


def test_cephalid_shrine_lets_a_spell_through_once_x_is_paid(set_pool):
    """One Bears in a graveyard is {1}: a third Forest pays it (CR 605.3b — the
    payment has no priority window, so the lands are tapped inside it)."""
    game = _w1g4_duel(
        set_pool, hand1=["Grizzly Bears"], gy0=["Grizzly Bears"],
        bf0=["Cephalid Shrine"], bf1=["Forest", "Forest", "Forest"],
    )
    game.enforce_mana_costs = True
    game.active_player_index = 1
    forests = list(game.controlled_by(1))
    for forest in forests[:2]:
        assert game.tap_land_for_mana(
            1, "Forest", "G", permanent_id=forest.permanent_id
        )
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert "Grizzly Bears" in [p.card.name for p in game.controlled_by(1)]
    assert forests[2].tapped


def test_cephalid_shrine_asks_nothing_when_x_is_zero(set_pool):
    game = _w1g4_cast_bears_under(set_pool, "Cephalid Shrine")
    assert "Grizzly Bears" in [p.card.name for p in game.controlled_by(1)]
    assert any("pays {0}" in line for line in game.log)


def test_a_shrine_counts_the_spell_itself_once_it_is_a_card_in_a_graveyard(set_pool):
    """CR 608.2h: the spell left the stack in response (countered), so its name
    is last known information — and the card is now in a graveyard with it."""
    game = _w1g4_duel(set_pool, hand1=["Grizzly Bears"], bf0=["Aven Shrine"])
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    spell = next(item for item in game.stack if item.card.name == "Grizzly Bears")
    game.counter_stack_object(spell)
    game.players[1].graveyard.append(spell.card)
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 21


def test_a_shrine_reads_the_cast_half_of_a_split_card(set_pool):
    """CR 709.3b gives the spell the cast half's name and CR 709.4a gives the
    card in the graveyard both halves' — so a Fire // Ice there shares a name
    with a Fire on the stack (CR 201.2a), and Grizzly Bears does not."""
    game = _w1g4_duel(
        set_pool, hand1=["Fire // Ice"], gy0=["Fire // Ice", "Grizzly Bears"],
        bf0=["Aven Shrine"],
    )
    assert game.queue_from_hand(1, "Fire", target_player_index=0).supported
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 21


def test_each_shrine_triggers_for_its_own_controllers_spell_too(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Grizzly Bears"], gy1=["Grizzly Bears"],
        bf0=["Aven Shrine", "Aven Shrine"],
    )
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    _w1g4_resolve_stack(game)
    assert (game.players[0].life, game.players[1].life) == (22, 20)


@_w1g4_pytest.mark.parametrize("line", [
    # No cast event froze a spell for the words to name.
    "At the beginning of your upkeep, you gain X life, where X is the number "
    "of cards in all graveyards with the same name as that spell.",
    # A permanent's name is computed; the count has no key for the relation.
    "Whenever a player casts a spell, that player gains X life, where X is "
    "the number of permanents with the same name as that spell.",
])
def test_the_same_name_count_refuses_where_nothing_could_answer_it(line):
    shrine = _w1g4_mk_card("Odd Shrine", "{W}", "Enchantment", line)
    assert not _w1g4_compile(shrine).supported


def test_an_opponent_scoped_cast_trigger_reads_the_same_name_count(set_pool):
    """An invented card: the relation is the event's, not the five names'."""
    shrine = _w1g4_mk_card(
        "Rival Shrine", "{W}", "Enchantment",
        "Whenever an opponent casts a spell, you gain X life, where X is the "
        "number of cards in all graveyards with the same name as that spell.",
    )
    assert _w1g4_compile(shrine).supported
    game = _w1g4_duel(
        set_pool, hand0=["Grizzly Bears"], hand1=["Grizzly Bears"],
        gy0=["Grizzly Bears", "Grizzly Bears", "Forest"],
    )
    game._put_permanent_onto_battlefield(0, _w1g4_Permanent(card=shrine), None)
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    _w1g4_resolve_stack(game)
    assert game.players[0].life == 22
    assert game.queue_from_hand(0, "Grizzly Bears").supported
    _w1g4_resolve_stack(game)
    assert game.players[0].life == 22, "its own controller is no opponent"


# --- Verdant Succession -------------------------------------------------------

def _w1g4_bolt(game, set_pool, seat, victim):
    """*seat* casts Lightning Bolt at *victim*; the Bolt resolves and
    state-based actions are checked, leaving any dies-trigger on the stack."""
    game.players[seat].hand.append(set_pool("LEA")["Lightning Bolt"])
    assert game.queue_from_hand(
        seat, "Lightning Bolt", target_permanent_ids=[victim.permanent_id]
    ).supported
    game.resolve_top_of_stack()
    game.check_state_based_actions()


def test_verdant_succession_replaces_a_dead_green_creature_from_its_controllers_library(set_pool):
    """The dead creature's **controller** searches — here the opponent of the
    Succession's controller — and the copy enters under that player."""
    game = _w1g4_duel(
        set_pool, bf0=["Verdant Succession"], bf1=["Grizzly Bears"],
        lib0=["Grizzly Bears"],
        lib1=["Forest", "Grizzly Bears", "Grizzly Bears", "Island"],
    )
    _w1g4_bolt(game, set_pool, 0, next(iter(game.controlled_by(1))))
    assert [item.card.name for item in game.stack] == ["Verdant Succession"]
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
    assert len(game.players[1].library) == 3
    assert _w1g4_names(game.players[0].library) == ["Grizzly Bears"]
    assert _w1g4_names(game.players[1].graveyard) == ["Grizzly Bears"]


def test_verdant_succession_with_no_copy_left_finds_nothing(set_pool):
    game = _w1g4_duel(
        set_pool, bf0=["Verdant Succession"], bf1=["Grizzly Bears"],
        lib0=["Grizzly Bears"], lib1=["Forest", "Island"],
    )
    _w1g4_bolt(game, set_pool, 0, next(iter(game.controlled_by(1))))
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert list(game.controlled_by(1)) == []
    assert len(game.players[1].library) == 2


def test_verdant_succession_ignores_a_nongreen_creature_and_a_token(set_pool):
    from engine.tokens import make_token_card

    game = _w1g4_duel(
        set_pool, bf0=["Verdant Succession"], bf1=["Scathe Zombies"],
        lib1=["Scathe Zombies", "Grizzly Bears"],
    )
    _w1g4_bolt(game, set_pool, 0, next(iter(game.controlled_by(1))))
    assert game.stack == []

    squirrel = _w1g4_Permanent(card=make_token_card(
        name="Squirrel Token", power=1, toughness=1,
        type_line="Creature — Squirrel", colors=("G",),
    ))
    squirrel.metadata["is_token"] = True
    game._put_permanent_onto_battlefield(1, squirrel, None)
    _w1g4_bolt(game, set_pool, 0, squirrel)
    assert game.stack == []


def test_verdant_succession_asks_the_dead_creatures_controller(set_pool):
    """"That creature's controller **may**": the offer is on the seat that
    controlled the creature, not on the enchantment's controller."""
    game = _w1g4_duel(
        set_pool, bf0=["Verdant Succession"], bf1=["Grizzly Bears"],
        lib1=["Forest", "Grizzly Bears"],
    )
    game.interactive_seats.update({0, 1})
    _w1g4_bolt(game, set_pool, 0, next(iter(game.controlled_by(1))))
    game.resolve_top_of_stack()
    assert [c.player_index for c in game.pending_choices] == [1]
    assert game.players[1].library and list(game.controlled_by(1)) == []


def test_verdant_succession_reads_the_controller_of_a_stolen_creature(set_pool):
    """A creature P0 took from P1 dies: P0 controlled it, so P0's library is
    searched — and the card itself goes to its owner's graveyard."""
    from engine.control import change_control

    game = _w1g4_duel(
        set_pool, bf0=["Verdant Succession"], bf1=["Grizzly Bears"],
        lib0=["Grizzly Bears"], lib1=["Grizzly Bears", "Grizzly Bears"],
    )
    bears = next(iter(game.controlled_by(1)))
    change_control(bears, 0, source="w1g4")
    game._sync_control()
    assert game.controller_index_of(bears) == 0
    _w1g4_bolt(game, set_pool, 1, bears)
    _w1g4_resolve_stack(game)
    game.auto_resolve_pending_choices()
    assert "Grizzly Bears" in [p.card.name for p in game.controlled_by(0)]
    assert game.players[0].library == [] and len(game.players[1].library) == 2
    assert "Grizzly Bears" in _w1g4_names(game.players[1].graveyard)

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
