"""Per-card tests for The Dark's lands.

See tests/sets/README.md for the convention.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import _mk_creature_card, _nosick
from engine.oracle import compile_card_oracle


# --- G1: damage family (The Dark) ---


def test_sorrows_path_burns_its_controller_and_their_creatures_when_tapped(set_pool):
    """"it deals 2 damage to **you and each creature you control**" — one
    printed clause, two kinds of recipient, and no sweep handler that batches
    exactly that set. Lowered as one instruction per recipient; refused
    outright before that, so the whole trigger did nothing."""
    lea = set_pool("LEA")
    path = Permanent(card=set_pool("DRK")["Sorrow's Path"])
    mine = Permanent(card=lea["Grizzly Bears"])
    theirs = Permanent(card=lea["Grizzly Bears"])
    players = [PlayerState(name="P1", life=20), PlayerState(name="P2", life=20)]
    players[0].battlefield = [path, mine]
    players[1].battlefield = [theirs]
    game = Game(players=players)
    game._sync_control()

    game.become_tapped(path)
    game._settle()

    assert players[0].life == 18, game.log
    assert mine.damage_marked == 2, game.log
    assert theirs.damage_marked == 0, game.log


def test_sorrows_paths_sweep_reaches_creatures_that_arrived_since(set_pool):
    """The recipients are the printed noun phrase asked at resolution, not a
    list built when the land entered — so a creature that arrived in between is
    damaged and one that left is not."""
    lea = set_pool("LEA")
    path = Permanent(card=set_pool("DRK")["Sorrow's Path"])
    players = [PlayerState(name="P1", life=20), PlayerState(name="P2", life=20)]
    players[0].battlefield = [path]
    game = Game(players=players)
    game._sync_control()

    latecomer = Permanent(card=lea["Hill Giant"])
    players[0].battlefield.append(latecomer)
    game._sync_control()
    game.become_tapped(path)
    game._settle()

    assert latecomer.damage_marked == 2, game.log

# --- G3: upkeep and land denial (The Dark) ---


def _run_upkeep(game: Game, seat: int) -> None:
    """One upkeep step for *seat*, with its triggers resolved off the stack."""
    game.active_player_index = seat
    game.resolve_upkeep(seat)
    while game.stack:
        game.resolve_top_of_stack()


def _safe_haven_holding_a_creature(set_pool):
    """Safe Haven on the battlefield with one creature exiled under it."""
    lea = set_pool("LEA")
    haven = Permanent(card=set_pool("DRK")["Safe Haven"])
    bears = Permanent(card=lea["Grizzly Bears"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[haven, bears]),
        PlayerState(name="P2"),
    ])
    game.players[0].mana_pool["C"] = 2
    result = game.activate_permanent_ability(
        0, "Safe Haven", target_player_index=0,
        target_permanent_ids=[bears.permanent_id],
    )
    assert result.supported, result.reason
    while game.stack:
        game.resolve_top_of_stack()
    return game, haven


def test_safe_haven_exiles_a_creature_with_its_activated_ability(set_pool):
    """"{2}, {T}: Exile target creature you control." The pile the upkeep
    trigger below returns from has to exist before it can be returned."""
    game, _haven = _safe_haven_holding_a_creature(set_pool)

    assert [c.name for c in game.players[0].exile] == ["Grizzly Bears"]
    assert not [p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears"]


def test_safe_haven_returns_its_exiled_cards_when_sacrificed(set_pool):
    """"At the beginning of your upkeep, you may sacrifice this land. If you do,
    return each card exiled with this land to the battlefield under its owner's
    control."

    This line compiled to **no instruction** — Safe Haven reported supported and
    exiled creatures forever. Knowledge Vault prints the same linked-pile
    sentence with the other verb ("put all cards exiled with…into"), so both
    spellings are one production now.
    """
    game, haven = _safe_haven_holding_a_creature(set_pool)

    _run_upkeep(game, 0)
    assert game.confirm_optional_pay(0, card_name="Safe Haven", accept=True)

    assert not game.is_on_battlefield(haven)
    assert not game.players[0].exile
    assert [p.card.name for p in game.controlled_by(0)] == ["Grizzly Bears"]


def test_safe_haven_declined_keeps_the_cards_in_exile(set_pool):
    """The offer is a "may": declining leaves the land and the pile alone."""
    game, haven = _safe_haven_holding_a_creature(set_pool)

    _run_upkeep(game, 0)
    assert game.confirm_optional_pay(0, card_name="Safe Haven", accept=False)

    assert game.is_on_battlefield(haven)
    assert [c.name for c in game.players[0].exile] == ["Grizzly Bears"]

# --- G5: zones and characteristics (The Dark) ---------------------------------


def _nosick(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _city(set_pool, extra=()):
    pool = set_pool("DRK")
    p1 = PlayerState(
        name="P1",
        battlefield=[
            _nosick(Permanent(card=pool["City of Shadows"])),
            *[_nosick(Permanent(card=pool[name])) for name in extra],
        ],
    )
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game, p1, p2, pool


def test_city_of_shadows_eats_a_creature_for_a_storage_counter(set_pool):
    """"{T}, **Exile a creature you control**: Put a storage counter on this
    land."

    The exile is a *cost* (CR 601.2b), so it is charged as the ability is
    activated and nothing about it is a target - protection and shroud have
    nothing to say about what may pay (idiom 10)."""
    from engine.named_counters import counters_on

    game, p1, p2, pool = _city(set_pool, extra=["Rag Man"])
    city = p1.battlefield[0]

    result = game.activate_permanent_ability(0, "City of Shadows", permanent_index=0)

    assert result.supported, result.details
    assert counters_on(city, "storage") == 1, game.log
    assert [perm.card.name for perm in p1.battlefield] == ["City of Shadows"]
    assert [card.name for card in p1.exile] == ["Rag Man"]


def test_city_of_shadows_cannot_be_activated_with_no_creature(set_pool):
    """The control: with nothing to pay the cost, the ability is not activated
    at all (CR 602.2b) — the land is not even tapped."""
    from engine.named_counters import counters_on

    game, p1, p2, pool = _city(set_pool)
    city = p1.battlefield[0]

    result = game.activate_permanent_ability(0, "City of Shadows", permanent_index=0)

    assert not result.supported
    assert counters_on(city, "storage") == 0
    assert city.tapped is False, game.log


def test_city_of_shadows_taps_for_one_mana_per_storage_counter(set_pool):
    """"{T}: Add {C} **for each storage counter on this land**." Counted off the
    source at resolution, which is what tells it from the batteries' "for each
    counter removed this way" — those are gone by then."""
    from engine.named_counters import add_counters

    game, p1, p2, pool = _city(set_pool)
    city = p1.battlefield[0]
    add_counters(city, "storage", 3)

    result = game.activate_permanent_ability(
        0, "City of Shadows", permanent_index=0, ability_index=1,
    )

    assert result.supported, result.details
    assert p1.mana_pool["C"] == 3, (dict(p1.mana_pool), game.log)


def test_city_of_shadows_with_no_counters_makes_no_mana(set_pool):
    """The control on the multiplier: nothing times a counter is nothing, not
    the flat {C} the pips alone would add."""
    game, p1, p2, pool = _city(set_pool)

    game.activate_permanent_ability(
        0, "City of Shadows", permanent_index=0, ability_index=1,
    )

    assert sum(p1.mana_pool.values()) == 0, (dict(p1.mana_pool), game.log)

# --- G4: combat, prevention, control (The Dark) ---


def test_maze_of_ith_shields_the_creature_it_untaps(set_pool):
    """"{T}: Untap target attacking creature. Prevent all combat damage that
    would be dealt to and dealt by that creature this turn."

    Ebony Horse prints the same second sentence, which is exactly what the
    card-hook registry's entry bar forbids — so the sentence is a grammar
    production and the Maze is two ordinary instructions.
    """
    maze = Permanent(card=set_pool("DRK")["Maze of Ith"])
    attacker = _nosick(Permanent(card=_mk_creature_card("Attacker", 3, 3)))
    blocker = Permanent(card=_mk_creature_card("Blocker", 2, 2))
    p1 = PlayerState(name="P1", battlefield=[attacker])
    p2 = PlayerState(name="P2", battlefield=[maze, blocker], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning of combat
    game.advance_combat_phase()  # declare attackers
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()  # declare blockers
    assert game.declare_blockers(1, {1: 0})[0]  # blocker is index 1; the Maze is 0

    result = game.activate_permanent_ability(
        1, "Maze of Ith", target_player_index=0, target_permanent_index=0
    )
    game._settle()

    assert result.supported
    assert attacker.tapped is False, "the attacker was untapped"

    game.advance_combat_phase()  # combat damage
    assert attacker.damage_marked == 0, "no combat damage was dealt to it"
    assert blocker.damage_marked == 0, "and none by it"


def test_maze_of_ith_is_supported(set_pool):
    program = compile_card_oracle(set_pool("DRK")["Maze of Ith"])
    assert program.supported
    kinds = [
        instruction.kind
        for ability in program.activated_abilities
        for instruction in (ability.instruction,)
        if instruction is not None
    ]
    # One ability, lowered as a sequence of the two printed sentences.
    assert kinds == ["sequence"]


# --- K3: Sorrow's Path (The Dark) ---


def _k3_creature(name, power, toughness, *, keywords=()):
    from engine.models import CardDefinition

    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line="Creature - Test",
        oracle_text="",
        colors=(),
        color_identity=(),
        keywords=keywords,
        produced_mana=(),
        raw={
            "name": name,
            "type_line": "Creature - Test",
            "power": str(power),
            "toughness": str(toughness),
        },
    )


def _sorrows_path_combat(set_pool, *, beta_flies=False):
    """A real combat with Sorrow's Path: two attackers, each blocked by a
    different creature the *defender* controls, and the Path untapped beside
    the attackers.

    Seat 0 controls Sorrow's Path and attacks with Alpha and Beta; seat 1
    blocks Alpha with Ex and Beta with Why. The Path is on the attacking side
    because the card names "two target blocking creatures controlled by the
    same **opponent**" — the blockers have to be on the other side of the table
    from the land.

    Returns ``(game, attacker_alpha, attacker_beta, blocker_ex, blocker_why)``.
    """
    # Tough enough to survive the Path's *own* second ability: tapping it to
    # activate the swap deals 2 damage to its controller and each creature they
    # control (the card is famous for it), and a 2/2 attacker dying mid-stack
    # would renumber the combat maps before the swap ever resolved.
    alpha = _nosick(Permanent(card=_k3_creature("Alpha", 2, 5)))
    beta = _nosick(
        Permanent(card=_k3_creature("Beta", 3, 5, keywords=("Flying",) if beta_flies else ()))
    )
    path = Permanent(card=set_pool("DRK")["Sorrow's Path"])
    ex = Permanent(card=_k3_creature("Ex", 1, 4))
    # Why can block the flier (CR 702.17b) so the declaration below is legal;
    # Ex cannot, which is what makes the swap illegal in the second test.
    why = Permanent(card=_k3_creature("Why", 1, 5, keywords=("Reach",) if beta_flies else ()))
    p1 = PlayerState(name="P1", battlefield=[alpha, beta, path])
    p2 = PlayerState(name="P2", battlefield=[ex, why], life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning of combat
    game.advance_combat_phase()  # declare attackers
    assert game.declare_attackers(0, [0, 1])[0], game.log
    game.advance_combat_phase()  # declare blockers
    # Ex blocks Alpha (attacker slot 0); Why blocks Beta (attacker slot 1).
    assert game.declare_blockers(1, {0: 0, 1: 1})[0], game.log
    assert game.combat_blockers[1] == {0: [0], 1: [1]}, game.log
    return game, alpha, beta, ex, why


def test_sorrows_path_swaps_two_blockers_in_a_real_combat(set_pool):
    """The board changes, not just the compile.

    Ex blocks Alpha and Why blocks Beta; after the ability resolves Ex blocks
    Beta and Why blocks Alpha, both attackers stay blocked the whole way
    through (CR 509.1h), and the combat damage lands on the swapped pairs.
    """
    game, alpha, beta, ex, why = _sorrows_path_combat(set_pool)

    result = game.activate_permanent_ability(
        0, "Sorrow's Path",
        target_permanent_ids=[ex.permanent_id, why.permanent_id],
    )
    game._settle()

    assert result.supported, game.log
    assert game.combat_blockers[1] == {0: [1], 1: [0]}, game.log
    assert ex.blocking_attacker_index == 1, "Ex now blocks Beta"
    assert why.blocking_attacker_index == 0, "Why now blocks Alpha"
    # CR 509.1h: a creature remains blocked even while its blockers are gone.
    assert alpha.blocked and beta.blocked, game.log

    game.advance_combat_phase()  # combat damage
    assert game.players[1].life == 20, "nothing got through the swap"
    assert ex.damage_marked == 3, "Ex took Beta's 3"
    assert why.damage_marked == 2, "Why took Alpha's 2"


def test_sorrows_path_does_nothing_when_one_creature_could_not_block(set_pool):
    """"If each of those creatures could block all creatures that the other is
    blocking" — Beta flies and Ex has neither flying nor reach, so the swap is
    refused whole: nothing is removed from combat and the declared blocks stand.
    """
    game, alpha, beta, ex, why = _sorrows_path_combat(set_pool, beta_flies=True)

    result = game.activate_permanent_ability(
        0, "Sorrow's Path",
        target_permanent_ids=[ex.permanent_id, why.permanent_id],
    )
    game._settle()

    assert result.supported, game.log
    assert game.combat_blockers[1] == {0: [0], 1: [1]}, "the blocks did not move"
    assert ex.blocking_attacker_index == 0 and why.blocking_attacker_index == 1


def test_sorrows_path_refuses_a_target_that_is_not_blocking(set_pool):
    """CR 602.2b, before any cost is paid: "two target **blocking** creatures".
    A creature that never blocked is not one the picker offers, so naming it
    refuses the activation rather than tapping the land for nothing."""
    game, alpha, beta, ex, why = _sorrows_path_combat(set_pool)
    bystander = Permanent(card=_k3_creature("Bystander", 1, 1))
    game.players[1].battlefield.append(bystander)
    game._sync_control()

    result = game.activate_permanent_ability(
        0, "Sorrow's Path",
        target_permanent_ids=[ex.permanent_id, bystander.permanent_id],
    )

    assert not result.supported, game.log
    assert game.combat_blockers[1] == {0: [0], 1: [1]}


def test_sorrows_path_activated_ability_is_no_longer_hollow(set_pool):
    """The hollow-line census's own question, asked of this card: a supported
    card whose ability compiles to no instruction reports success and does
    nothing."""
    program = compile_card_oracle(set_pool("DRK")["Sorrow's Path"])
    assert program.supported
    assert [a.instruction.kind for a in program.activated_abilities] == [
        "swap_block_assignments"
    ]
    assert all(a.supported for a in program.activated_abilities)
