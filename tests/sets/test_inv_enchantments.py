"""Invasion enchantments.

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

Cards come from `set_pool("INV")` / `set_cards("INV")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G6: colour choices ---
# Teferi's Moat and Harsh Judgment arrived supported on "As this enchantment
# enters, choose a color." alone, with the sentence that *spends* the colour
# implemented by nothing. Traveler's Cloak chooses a land type the same way;
# Pulse of Llanowar's colour is the tapper's, named per production.
from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile


def _w1g6_ench_table(set_pool, mine=(), theirs=()):
    """Seat 0 holds *mine*, seat 1 *theirs* (INV names first, else LEA); mana
    off, nothing summoning sick, seat 0's turn."""
    inv, lea = set_pool("INV"), set_pool("LEA")
    w1g6_game = _W1G6Game(players=[
        _W1G6PlayerState(name="A", life=20), _W1G6PlayerState(name="B", life=20),
    ])
    w1g6_game.enforce_mana_costs = False
    w1g6_game.active_player_index = 0
    w1g6_sides = []
    for seat, names in ((0, mine), (1, theirs)):
        side = []
        for name in names:
            perm = _W1G6Permanent(card=inv[name] if name in inv else lea[name])
            w1g6_game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
            side.append(perm)
        w1g6_sides.append(side)
    w1g6_game.auto_resolve_pending_choices()
    return w1g6_game, w1g6_sides[0], w1g6_sides[1]  # _w1g6_ench_table


def _w1g6_enter_naming(game, seat, name, **answer):
    """Cast *name* from *seat*'s hand and answer its entry choice."""
    game.interactive_seats = {seat}
    assert game.queue_from_hand(seat, name).supported
    game.resolve_top_of_stack()
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("enter_choice", seat)]
    assert game.confirm_enter_choice(seat, **answer)
    return next(p for p in game.controlled_by(seat) if p.card.name == name)  # _w1g6_enter_naming


# -- Teferi's Moat ------------------------------------------------------------


def test_w1g6_teferis_moat_grounds_the_chosen_colour_and_nothing_else(set_pool):
    """"Creatures of the chosen color without flying can't attack you." Green
    is named: the green Bears cannot attack the Moat's controller, the red
    Giant can, and the green Birds can because they fly (CR 613 layer 6)."""
    program = _w1g6_compile(set_pool("INV")["Teferi's Moat"])
    assert "creatures_cant_attack_you" in {i.kind for i in program.instructions}

    game, mine, _theirs = _w1g6_ench_table(
        set_pool, ["Grizzly Bears", "Hill Giant", "Birds of Paradise"],
    )
    game.players[1].hand.append(set_pool("INV")["Teferi's Moat"])
    _w1g6_enter_naming(game, 1, "Teferi's Moat", mana_color="G")
    bears, giant, birds = mine

    assert [game.can_attack(perm, 1) for perm in (bears, giant, birds)] == [False, True, True]
    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    refused, why = game.declare_attackers(0, [0])
    assert not refused and "Grizzly Bears" in why
    assert game.declare_attackers(0, [1, 2])[0]


def test_w1g6_teferis_moat_reads_the_creatures_colour_as_it_is_now(set_pool):
    """The colour is a computed characteristic (CR 613 layer 5): Bears laced
    blue are no longer green and may attack; a Giant turned green may not."""
    game, mine, _theirs = _w1g6_ench_table(set_pool, ["Grizzly Bears", "Hill Giant"])
    game.players[1].hand.append(set_pool("INV")["Teferi's Moat"])
    _w1g6_enter_naming(game, 1, "Teferi's Moat", mana_color="G")
    bears, giant = mine

    bears.metadata["color_override"] = "U"
    giant.metadata["color_override"] = "G"
    game._recompute_continuous_effects()

    assert [game.can_attack(perm, 1) for perm in (bears, giant)] == [True, False]


def test_w1g6_teferis_moat_protects_only_its_controller(set_pool):
    """"…can't attack **you**": the Moat's controller's own green creature is
    free to attack the opponent."""
    game, mine, _theirs = _w1g6_ench_table(set_pool, ["Grizzly Bears"])
    game.players[0].hand.append(set_pool("INV")["Teferi's Moat"])
    _w1g6_enter_naming(game, 0, "Teferi's Moat", mana_color="G")

    assert game.can_attack(mine[0], 1)


# -- Harsh Judgment -----------------------------------------------------------


def _w1g6_judgment(set_pool, colour, hand):
    """Seat 1 controls a Harsh Judgment naming *colour*; seat 0 holds *hand*."""
    game, mine, theirs = _w1g6_ench_table(
        set_pool, ["Prodigal Sorcerer"], ["Grizzly Bears"],
    )
    game.players[1].hand.append(set_pool("INV")["Harsh Judgment"])
    _w1g6_enter_naming(game, 1, "Harsh Judgment", mana_color=colour)
    game.interactive_seats = set()
    lea = set_pool("LEA")
    game.players[0].hand.extend(lea[name] for name in hand)
    return game, mine, theirs  # _w1g6_judgment


def test_w1g6_harsh_judgment_sends_a_spell_of_the_chosen_colour_back(set_pool):
    """"If an instant or sorcery spell of the chosen color would deal damage to
    you, it deals that damage to its controller instead." Red is named: a
    Lightning Bolt at the Judgment's controller is dealt to its caster."""
    from tests.helpers import resolve_stack

    game, _mine, _theirs = _w1g6_judgment(set_pool, "R", ["Lightning Bolt"])
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    resolve_stack(game)

    assert (game.players[0].life, game.players[1].life) == (17, 20)
    assert "3 damage to B is dealt to A instead (Harsh Judgment)" in game.log


def test_w1g6_harsh_judgment_ignores_other_colours_abilities_and_other_recipients(set_pool):
    """Every printed word of the source class and the recipient is enforced. A
    black sorcery is not of the chosen colour; a red permanent's *ability* is
    not a spell; and red damage to the controller's creature is not damage to
    "you"."""
    from tests.helpers import resolve_stack

    game, mine, theirs = _w1g6_judgment(
        set_pool, "R", ["Drain Life", "Lightning Bolt"],
    )
    assert game.queue_from_hand(0, "Drain Life", target_player_index=1, x_value=2).supported
    resolve_stack(game)
    assert (game.players[0].life, game.players[1].life) == (22, 18)

    sorcerer = mine[0]
    sorcerer.metadata["color_override"] = "R"
    game._recompute_continuous_effects()
    assert game.queue_permanent_ability(
        0, "Prodigal Sorcerer", ability_index=0, target_player_index=1,
    ).supported
    resolve_stack(game)
    assert (game.players[0].life, game.players[1].life) == (22, 17)

    bears = theirs[0]
    assert game.queue_from_hand(
        0, "Lightning Bolt", target_player_index=1,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    resolve_stack(game)
    game.check_state_based_actions()
    assert (game.players[0].life, game.players[1].life) == (22, 17)
    assert not game.is_on_battlefield(bears)


def test_w1g6_harsh_judgment_naming_another_colour_lets_the_bolt_land(set_pool):
    """Blue is named, so the red Bolt is dealt where it was aimed."""
    from tests.helpers import resolve_stack

    game, _mine, _theirs = _w1g6_judgment(set_pool, "U", ["Lightning Bolt"])
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    resolve_stack(game)

    assert (game.players[0].life, game.players[1].life) == (20, 17)


# -- Traveler's Cloak ---------------------------------------------------------


def test_w1g6_travelers_cloak_grants_landwalk_of_the_type_it_chose(set_pool):
    """"As this Aura enters, choose a land type. / When this Aura enters, draw
    a card. / Enchanted creature has landwalk of the chosen type." Swamp is
    named: the Bears have swampwalk and nothing else, the defender's Giant
    cannot block them while its controller has a Swamp, and the card is
    drawn."""
    game, mine, theirs = _w1g6_ench_table(
        set_pool, ["Grizzly Bears", "Island"], ["Hill Giant", "Swamp", "Mountain"],
    )
    lea = set_pool("LEA")
    game.interactive_seats = {0}
    game.players[0].hand.append(set_pool("INV")["Traveler's Cloak"])
    game.players[0].library.extend([lea["Forest"]] * 2)
    bears = mine[0]

    assert game.queue_from_hand(
        0, "Traveler's Cloak", target_player_index=0, target_permanent_index=0,
    ).supported
    for _ in range(6):
        if game.pending_choices:
            assert game.pending_choices[0].data.get("needs_land_type")
            assert game.confirm_enter_choice(0, land_type="swamp")
        elif game.stack:
            game.resolve_top_of_stack()

    assert game._has_keyword(bears, "swampwalk")
    assert not game._has_keyword(bears, "islandwalk")
    assert not game._has_keyword(bears, "mountainwalk")
    assert [card.name for card in game.players[0].hand] == ["Forest"]

    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    blocked, why = game.declare_blockers(1, {0: 0})
    assert not blocked and "cannot block" in why


def test_w1g6_travelers_cloaks_walk_ends_with_the_aura_and_needs_the_land(set_pool):
    """The grant is derived while the Aura is attached: an opponent with no
    land of the chosen type may block, and once the Cloak is gone so is the
    ability."""
    game, mine, theirs = _w1g6_ench_table(
        set_pool, ["Grizzly Bears"], ["Hill Giant", "Mountain"],
    )
    game.interactive_seats = {0}
    game.players[0].hand.append(set_pool("INV")["Traveler's Cloak"])
    game.players[0].library.append(set_pool("LEA")["Forest"])
    bears = mine[0]
    assert game.queue_from_hand(
        0, "Traveler's Cloak", target_player_index=0, target_permanent_index=0,
    ).supported
    for _ in range(6):
        if game.pending_choices:
            assert game.confirm_enter_choice(0, land_type="swamp")
        elif game.stack:
            game.resolve_top_of_stack()
    assert game._has_keyword(bears, "swampwalk")

    game.current_turn_phase, game.current_step = "combat", "declare_attackers"
    assert game.declare_attackers(0, [0])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0], "no Swamp, so the walk is idle"

    cloak = next(p for p in game.controlled_by(0) if p.card.name == "Traveler's Cloak")
    game.remove_from_battlefield(cloak)
    game.check_state_based_actions()
    game._recompute_continuous_effects()
    assert not game._has_keyword(bears, "swampwalk")


# -- Pulse of Llanowar --------------------------------------------------------


def test_w1g6_pulse_of_llanowar_lets_its_controllers_basics_make_any_colour(set_pool):
    """"If a basic land you control is tapped for mana, it produces mana of a
    color of your choice instead of any other type." The tapper names the
    colour for each production: a Forest for red, a Swamp for blue. A nonbasic
    land and an opponent's basic are outside the phrase and make what they
    print."""
    assert _w1g6_compile(set_pool("INV")["Pulse of Llanowar"]).supported
    game, mine, theirs = _w1g6_ench_table(
        set_pool, ["Pulse of Llanowar", "Forest", "Swamp", "Bayou"], ["Forest"],
    )
    game.enforce_mana_costs = True
    _pulse, forest, swamp, bayou = mine

    assert set(game._land_payment_colors(forest)) == {"W", "U", "B", "R", "G"}
    assert tuple(game._land_payment_colors(theirs[0])) == ("G",)
    assert set(game._land_payment_colors(bayou)) == {"B", "G"}, "a Swamp Forest, not basic"

    assert game.tap_land_for_mana(0, "Forest", "R", permanent_id=forest.permanent_id)
    assert game.tap_land_for_mana(0, "Swamp", "U", permanent_id=swamp.permanent_id)
    assert game.tap_land_for_mana(0, "Bayou", "B", permanent_id=bayou.permanent_id)
    assert game.tap_land_for_mana(1, "Forest", "R", permanent_id=theirs[0].permanent_id)

    assert {k: v for k, v in game.players[0].mana_pool.items() if v} == {"R": 1, "U": 1, "B": 1}
    assert {k: v for k, v in game.players[1].mana_pool.items() if v} == {"G": 1}


def test_w1g6_pulse_of_llanowar_stops_when_it_leaves(set_pool):
    """A static, derived off the board: with the Pulse gone the Forest makes
    green whatever is asked of it."""
    game, mine, _theirs = _w1g6_ench_table(set_pool, ["Pulse of Llanowar", "Forest"])
    game.enforce_mana_costs = True
    pulse, forest = mine

    game.remove_from_battlefield(pulse)
    assert tuple(game._land_payment_colors(forest)) == ("G",)
    assert game.tap_land_for_mana(0, "Forest", "R", permanent_id=forest.permanent_id)
    assert {k: v for k, v in game.players[0].mana_pool.items() if v} == {"G": 1}


# --- W1G4: colour census ---
from engine import Game as _W1G4AuraGame
from engine import PlayerState as _W1G4AuraSeat
from engine.models import Permanent as _W1G4AuraPermanent
from tests.helpers import resolve_stack as _w1g4_aura_resolve

_W1G4_LEAK_LINE = (
    "at the beginning of your upkeep, sacrifice this permanent unless you pay "
    "its mana cost."
)


def _w1g4_leak_table():
    """Two seats, mana costs off until a test turns them on to charge the toll."""
    w1g4_leak_game = _W1G4AuraGame(players=[
        _W1G4AuraSeat(name="W1G4-leaker"), _W1G4AuraSeat(name="W1G4-host"),
    ])
    w1g4_leak_game.enforce_mana_costs = False
    w1g4_leak_game.active_player_index = 0
    return w1g4_leak_game


def _w1g4_host(game, seat, card):
    """*card* onto *seat*'s battlefield through the real entry seam."""
    w1g4_host_permanent = _W1G4AuraPermanent(card=card)
    game._put_permanent_onto_battlefield(seat, w1g4_host_permanent, None)
    game.check_state_based_actions()
    return w1g4_host_permanent


def _w1g4_leak_onto(game, aura_card, host):
    """Seat 0 casts *aura_card* on *host* through the real cast; the Aura."""
    game.players[0].hand.append(aura_card)
    w1g4_leak_cast = game.cast_from_hand(
        0, aura_card.name,
        target_player_index=game.controller_index_of(host),
        target_permanent_index=game.battlefield_index_of(host),
    )
    assert w1g4_leak_cast.supported, w1g4_leak_cast.details
    _w1g4_aura_resolve(game)
    game.check_state_based_actions()
    return next(
        permanent for permanent in game.all_permanents()
        if permanent.card.name == aura_card.name
    )


def test_w1g4_essence_leak_charges_a_green_hosts_controller_its_mana_cost(set_pool):
    """'As long as enchanted permanent is red or green, it has "At the beginning
    of your upkeep, sacrifice this permanent unless you pay its mana cost."'

    The ability is the *host's*, so "your upkeep" is its controller's — not the
    Aura's — and the price is the host's own mana cost: Grizzly Bears' {1}{G}
    taps two of three Forests. Nothing happens on the Aura controller's upkeep.
    """
    inv, lea = set_pool("INV"), set_pool("LEA")
    game = _w1g4_leak_table()
    bear = _w1g4_host(game, 1, lea["Grizzly Bears"])
    forests = [_w1g4_host(game, 1, lea["Forest"]) for _ in range(3)]
    _w1g4_leak_onto(game, inv["Essence Leak"], bear)
    assert bear.effective_card.oracle_text == _W1G4_LEAK_LINE
    game.enforce_mana_costs = True

    game.resolve_upkeep(0)
    _w1g4_aura_resolve(game)
    assert game.is_on_battlefield(bear) and not any(f.tapped for f in forests)

    quoted = [
        prompt for prompt in game.get_upkeep_pay_triggers(1)
        if prompt["permanent_id"] == bear.permanent_id
    ]
    assert len(quoted) == 1 and quoted[0]["cost"]["mana"] == {"G": 1, "generic": 1}

    game.resolve_upkeep(1)
    _w1g4_aura_resolve(game)
    assert game.is_on_battlefield(bear)
    assert sum(forest.tapped for forest in forests) == 2
    assert "W1G4-host paid upkeep for Grizzly Bears" in game.log


def test_w1g4_essence_leak_takes_the_host_when_its_cost_is_not_paid(set_pool):
    """Declined, or simply unaffordable, the host is sacrificed by its own
    controller — and the Aura follows it as a state-based action (CR 704.5m).
    """
    inv, lea = set_pool("INV"), set_pool("LEA")
    for declined in (True, False):
        game = _w1g4_leak_table()
        giant = _w1g4_host(game, 1, lea["Hill Giant"])        # red, {3}{R}
        lands = (
            [_w1g4_host(game, 1, lea["Mountain"]) for _ in range(4)]
            if declined else []
        )
        _w1g4_leak_onto(game, inv["Essence Leak"], giant)
        game.enforce_mana_costs = True
        answers = {giant.permanent_id: False} if declined else None
        game.resolve_upkeep(1, human_choices=answers)
        _w1g4_aura_resolve(game)
        game.check_state_based_actions()

        assert not game.is_on_battlefield(giant)
        assert not any(land.tapped for land in lands), "nothing was paid"
        assert [card.name for card in game.players[1].graveyard] == ["Hill Giant"]
        assert [card.name for card in game.players[0].graveyard] == ["Essence Leak"]


def test_w1g4_essence_leak_follows_the_hosts_colour_through_the_layers(set_pool):
    """The criterion is CR 613 layer 5's answer, asked on every recompute: a
    white host has no such ability and survives its upkeep with no lands; a
    Chaoslace makes it red and the ability appears; a Purelace takes it away
    again with nothing to undo (CR 611.3a).
    """
    inv, lea = set_pool("INV"), set_pool("LEA")
    game = _w1g4_leak_table()
    lions = _w1g4_host(game, 1, lea["Savannah Lions"])
    _w1g4_leak_onto(game, inv["Essence Leak"], lions)
    assert lions.effective_card.oracle_text == ""
    game.resolve_upkeep(1)
    _w1g4_aura_resolve(game)
    assert game.is_on_battlefield(lions)

    for lace, expected in (("Chaoslace", _W1G4_LEAK_LINE), ("Purelace", "")):
        game.players[0].hand.append(lea[lace])
        assert game.cast_from_hand(
            0, lace, target_player_index=1,
            target_permanent_ids=[lions.permanent_id],
        ).supported
        _w1g4_aura_resolve(game)
        game.check_state_based_actions()
        assert lions.effective_card.oracle_text == expected, lace


def test_w1g4_a_host_with_no_mana_cost_cannot_pay_it(set_pool):
    """CR 118.6 / CR 202.1b: a land has no mana cost, so a cost based on it is
    unpayable — it may not even be attempted. A Forest turned green by a
    Lifelace is sacrificed however many lands its controller could tap, and the
    prompt quotes nothing for it.
    """
    inv, lea = set_pool("INV"), set_pool("LEA")
    game = _w1g4_leak_table()
    forest = _w1g4_host(game, 1, lea["Forest"])
    spare = [_w1g4_host(game, 1, lea["Forest"]) for _ in range(3)]
    _w1g4_leak_onto(game, inv["Essence Leak"], forest)
    assert _W1G4_LEAK_LINE not in forest.effective_card.oracle_text, (
        "a Forest is colourless, whatever mana it makes"
    )

    game.players[0].hand.append(lea["Lifelace"])
    assert game.cast_from_hand(
        0, "Lifelace", target_player_index=1,
        target_permanent_ids=[forest.permanent_id],
    ).supported
    _w1g4_aura_resolve(game)
    game.check_state_based_actions()
    assert _W1G4_LEAK_LINE in forest.effective_card.oracle_text
    game.enforce_mana_costs = True
    assert not [
        prompt for prompt in game.get_upkeep_pay_triggers(1)
        if prompt["permanent_id"] == forest.permanent_id
    ]

    game.resolve_upkeep(1)
    _w1g4_aura_resolve(game)
    assert not game.is_on_battlefield(forest)
    assert not any(land.tapped for land in spare)


def test_w1g4_a_conditional_grant_the_engine_cannot_read_is_not_claimed():
    """The gate asks the same function the grant is derived from, so a quote
    the compiler refuses, or a criterion the matcher cannot test, leaves the
    line unclaimed and the card unsupported — never admitted and inert.
    """
    from engine.auras import aura_conditional_ability_grants, aura_continuous_claim

    printed = (
        'As long as enchanted permanent is red or green, it has "At the '
        'beginning of your upkeep, sacrifice this permanent unless you pay its '
        'mana cost."'
    )
    (criterion, line), = aura_conditional_ability_grants(printed)
    assert dict(criterion)["any_colors"] == ("R", "G")
    assert line == _W1G4_LEAK_LINE
    assert aura_continuous_claim(printed)

    unreadable = (
        'As long as enchanted permanent is red or green, it has "Whenever a '
        'moon rises, win the game."'
    )
    assert aura_conditional_ability_grants(unreadable) == ()
    assert aura_continuous_claim(unreadable) is None
    vacuous = (
        'As long as enchanted permanent is splendid, it has "{T}: Draw a card."'
    )
    assert aura_conditional_ability_grants(vacuous) == ()


# --- W1G5: colour relations ---
from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState
from engine.models import CardDefinition as _W1G5Card, Permanent as _W1G5Permanent
from engine.oracle import compile_card_oracle as _w1g5_compile
from tests.helpers import _damage_dealt as _w1g5_damage_dealt
from tests.helpers import resolve_stack as _w1g5_resolve_stack


def _w1g5_creature(name, power, toughness, colors=(), text="", type_line="Creature - Test"):
    """A bare creature of the given colours — the only thing these cards ask
    of the objects around them."""
    cost = "".join("{%s}" % symbol for symbol in colors) or "{2}"
    return _W1G5Card(
        name=name, mana_cost=cost, cmc=float(max(1, len(colors))),
        type_line=type_line, oracle_text=text, colors=tuple(colors),
        color_identity=tuple(colors), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )  # W1G5 enchantments: a coloured test creature


def _w1g5_table(mine, theirs, *, hand0=(), hand1=()):
    """Seat 0 active in its precombat main phase; both boards placed, nothing
    summoning sick. Returns the game and the two boards' permanents."""
    board0 = [_W1G5Permanent(card=card) for card in mine]
    board1 = [_W1G5Permanent(card=card) for card in theirs]
    island = _W1G5Card(
        name="Island", mana_cost="", cmc=0.0, type_line="Basic Land - Island",
        oracle_text="({T}: Add {U}.)", colors=(), color_identity=("U",),
        keywords=(), produced_mana=("U",),
        raw={"name": "Island", "type_line": "Basic Land - Island"},
    )
    game = _W1G5Game(players=[
        _W1G5PlayerState(name="P0", battlefield=board0, hand=list(hand0),
                         library=[island] * 10),
        _W1G5PlayerState(name="P1", battlefield=board1, hand=list(hand1),
                         library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for permanent in board0 + board1:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._close_current_priority_step()
    return game, board0, board1  # W1G5 enchantments: the table


def _w1g5_fight(game, attacker_slot, blocker_slot=None):
    """Seat 0 attacks with *attacker_slot*; seat 1 blocks it with
    *blocker_slot* (or not at all); combat runs to the second main phase."""
    game.advance_combat_phase()
    game.advance_combat_phase()
    declared = game.declare_attackers(0, [attacker_slot])
    assert declared[0], declared
    game.advance_combat_phase()
    blocks = {} if blocker_slot is None else {blocker_slot: attacker_slot}
    blocked = game.declare_blockers(1, blocks)
    assert blocked[0], blocked
    for _ in range(6):
        if game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
        _w1g5_resolve_stack(game)
    assert game.current_step == "postcombat_main", game.current_step  # W1G5: combat over


# --- Well-Laid Plans -------------------------------------------------------
# "Prevent all damage that would be dealt to a creature by another creature if
# they share a color." A static blanket whose narrowing is a relation between
# the two ends of the damage event, held to each printed word in turn.


def test_w1g5_well_laid_plans_stops_two_white_creatures_trading(set_pool):
    """A real combat: white attacker, white blocker, both 2/2. Each would kill
    the other; under the Plans neither is touched (CR 615.1), in both
    directions of the one fight."""
    plans = set_pool("INV")["Well-Laid Plans"]
    assert _w1g5_compile(plans).supported
    game, (_plans, attacker), (blocker,) = _w1g5_table(
        [plans, _w1g5_creature("Knight", 2, 2, ("W",))],
        [_w1g5_creature("Squire", 2, 2, ("W",))],
    )
    _w1g5_fight(game, attacker_slot=1, blocker_slot=0)

    assert game.is_on_battlefield(attacker) and game.is_on_battlefield(blocker)
    assert attacker.damage_marked == 0 and blocker.damage_marked == 0
    assert any("they share a color (Well-Laid Plans)" in line for line in game.log)


def test_w1g5_well_laid_plans_lets_differently_coloured_creatures_fight(set_pool):
    """The condition is the card: a white attacker and a red blocker share
    nothing, so the same combat kills both."""
    game, (_plans, attacker), (blocker,) = _w1g5_table(
        [set_pool("INV")["Well-Laid Plans"], _w1g5_creature("Knight", 2, 2, ("W",))],
        [_w1g5_creature("Raider", 2, 2, ("R",))],
    )
    _w1g5_fight(game, attacker_slot=1, blocker_slot=0)

    assert not game.is_on_battlefield(attacker)
    assert not game.is_on_battlefield(blocker)


def test_w1g5_well_laid_plans_reads_each_printed_word(set_pool):
    """One event per narrowing. A multicoloured creature shares with either of
    its colours (CR 105.2b); a colourless one shares with nothing, another
    colourless one included (CR 105.2c); a player is not a creature; a spell
    is not "another creature"; and the Plans' controller is nobody special —
    an opponent's creatures are covered too."""
    game, (_plans, white, gold, golem), (blue, rock) = _w1g5_table(
        [
            set_pool("INV")["Well-Laid Plans"],
            _w1g5_creature("Knight", 2, 2, ("W",)),
            _w1g5_creature("Envoy", 2, 2, ("W", "U")),
            _w1g5_creature("Golem", 2, 2, (), type_line="Artifact Creature - Golem"),
        ],
        [
            _w1g5_creature("Drake", 2, 2, ("U",)),
            _w1g5_creature("Rock", 2, 2, (), type_line="Artifact Creature - Golem"),
        ],
    )
    # gold shares white with the Knight and blue with the Drake
    assert _w1g5_damage_dealt(game, white, 3, source=gold) == 0
    assert _w1g5_damage_dealt(game, blue, 3, source=gold) == 0
    assert _w1g5_damage_dealt(game, gold, 3, source=blue) == 0
    # white and blue share nothing
    assert _w1g5_damage_dealt(game, blue, 3, source=white) == 3
    # colourless shares with nothing, another colourless creature included
    assert _w1g5_damage_dealt(game, rock, 3, source=golem) == 3
    assert _w1g5_damage_dealt(game, white, 3, source=golem) == 3
    # "to a creature": the face still takes it
    assert _w1g5_damage_dealt(game, game.players[1], 3, source=white) == 3
    # "by another creature": a white spell is not a creature
    bolt = _W1G5Card(
        name="Smite", mana_cost="{W}", cmc=1.0, type_line="Instant",
        oracle_text="", colors=("W",), color_identity=("W",), keywords=(),
        produced_mana=(), raw={"name": "Smite", "type_line": "Instant"},
    )
    assert _w1g5_damage_dealt(game, white, 3, source=bolt) == 3
    # …and the same creature is not "another" one
    assert _w1g5_damage_dealt(game, white, 3, source=white) == 3


def test_w1g5_well_laid_plans_ends_with_the_enchantment(set_pool):
    game, (plans, white, other), _ = _w1g5_table(
        [set_pool("INV")["Well-Laid Plans"],
         _w1g5_creature("Knight", 2, 2, ("W",)),
         _w1g5_creature("Squire", 2, 2, ("W",))],
        [],
    )
    assert _w1g5_damage_dealt(game, white, 2, source=other) == 0
    game.remove_from_battlefield(plans)
    assert _w1g5_damage_dealt(game, white, 2, source=other) == 2


# --- Spirit of Resistance --------------------------------------------------
# "As long as you control a permanent of each color, prevent all damage that
# would be dealt to you." Glacial Chasm's blanket behind CR 611.2's condition.


def _w1g5_rainbow(*, without=()):
    return [
        _w1g5_creature(f"{symbol}-mage", 1, 1, (symbol,))
        for symbol in ("W", "U", "B", "R", "G") if symbol not in without
    ]  # W1G5: one permanent per colour


def test_w1g5_spirit_of_resistance_shields_only_behind_all_five_colours(set_pool):
    """Four colours is no shield at all; the fifth arriving arms it; one of
    them leaving disarms it again — rechecked per event, never latched."""
    spirit = set_pool("INV")["Spirit of Resistance"]
    assert _w1g5_compile(spirit).supported
    # The Spirit itself is white, so the board needs the other four.
    game, board, (raider,) = _w1g5_table(
        [spirit] + _w1g5_rainbow(without=("W", "G")),
        [_w1g5_creature("Raider", 3, 3, ("R",))],
    )
    me = game.players[0]
    assert _w1g5_damage_dealt(game, me, 5, source=raider) == 5

    green = _W1G5Permanent(card=_w1g5_creature("G-mage", 1, 1, ("G",)))
    game._put_permanent_onto_battlefield(0, green, None)
    assert _w1g5_damage_dealt(game, me, 5, source=raider) == 0
    assert _w1g5_damage_dealt(game, me, 5, source=raider, combat=True) == 0
    # "to you": the opponent, and my own creatures, are not shielded
    assert _w1g5_damage_dealt(game, game.players[1], 5, source=raider) == 5
    assert _w1g5_damage_dealt(game, green, 1, source=raider) == 1

    game.remove_from_battlefield(green)
    assert _w1g5_damage_dealt(game, me, 5, source=raider) == 5


def test_w1g5_spirit_of_resistance_counts_a_gold_permanent_for_each_colour(set_pool):
    """CR 105.2b: one multicoloured permanent is each of its colours, so a
    black-red-green creature and a blue one complete the white Spirit's set —
    and an opponent's permanents never count toward "you control"."""
    game, _mine, _theirs = _w1g5_table(
        [set_pool("INV")["Spirit of Resistance"],
         _w1g5_creature("Hydra", 4, 4, ("B", "R", "G"))],
        _w1g5_rainbow(),
    )
    me = game.players[0]
    assert _w1g5_damage_dealt(game, me, 4) == 4  # no blue of my own
    game._put_permanent_onto_battlefield(
        0, _W1G5Permanent(card=_w1g5_creature("Drake", 1, 1, ("U",))), None
    )
    assert _w1g5_damage_dealt(game, me, 4) == 0


def test_w1g5_spirit_of_resistance_holds_through_a_real_attack(set_pool):
    """Through the combat damage step rather than a bare event: a 3/3 attacks
    the rainbow's controller unblocked and no life is lost."""
    game, _theirs, _mine = _w1g5_table(
        [_w1g5_creature("Raider", 3, 3, ("R",))],
        [set_pool("INV")["Spirit of Resistance"]] + _w1g5_rainbow(without=("W",)),
    )
    _w1g5_fight(game, attacker_slot=0)
    assert game.players[1].life == 20


def test_w1g5_of_each_color_is_a_condition_any_noun_can_carry():
    """The relation is read behind the noun, so "a **creature** of each color"
    (Coalition Victory's half) is the same clause with a narrower set — and a
    wording nothing evaluates refuses rather than lowering to presence."""
    from engine.grammar import condition_payload_for

    permanent = condition_payload_for("you control a permanent of each color")
    creature = condition_payload_for("you control a creature of each color")
    assert permanent["of_each_color"] is True and creature["of_each_color"] is True
    assert creature["filter"] != permanent["filter"]
    assert condition_payload_for("an opponent controls a permanent of each color") is None
    assert condition_payload_for("you control no permanent of each color") is None


# --- Divine Presence -------------------------------------------------------
# "If a source would deal 4 or more damage to a permanent or player, that
# source deals 3 damage to that permanent or player instead." Forethought
# Amulet's cap with both narrowings taken off — a CR 614 replacement.


def test_w1g5_divine_presence_caps_every_large_event_at_three(set_pool):
    """Players and permanents, both seats', any source — and three or less is
    not this card's business."""
    presence = set_pool("INV")["Divine Presence"]
    assert _w1g5_compile(presence).supported
    game, (_presence, mine), (theirs,) = _w1g5_table(
        [presence, _w1g5_creature("Wall", 0, 7, ("W",))],
        [_w1g5_creature("Giant", 7, 7, ("R",))],
    )
    assert _w1g5_damage_dealt(game, game.players[0], 9, source=theirs) == 3
    assert _w1g5_damage_dealt(game, game.players[1], 9, source=mine) == 3
    assert _w1g5_damage_dealt(game, mine, 4, source=theirs) == 3
    assert _w1g5_damage_dealt(game, theirs, 20) == 3
    assert _w1g5_damage_dealt(game, game.players[0], 3, source=theirs) == 3
    assert _w1g5_damage_dealt(game, theirs, 2, source=mine) == 2


def test_w1g5_divine_presence_caps_a_real_attack_and_a_real_block(set_pool):
    """Through combat: a 7/7 hits the face for 3, and blocked by a 0/4 Wall it
    marks 3 on the Wall rather than killing it."""
    board = [_w1g5_creature("Giant", 7, 7, ("R",))]
    defence = [set_pool("INV")["Divine Presence"], _w1g5_creature("Wall", 0, 4, ("W",))]
    game, _mine, _theirs = _w1g5_table(board, defence)
    _w1g5_fight(game, attacker_slot=0)
    assert game.players[1].life == 17

    game, _mine, (_presence, wall) = _w1g5_table(board, defence)
    _w1g5_fight(game, attacker_slot=0, blocker_slot=1)
    assert game.is_on_battlefield(wall) and wall.damage_marked == 3


def test_w1g5_divine_presence_is_a_replacement_not_a_prevention(set_pool):
    """CR 614.1a, and the difference is rules-visible: damage that "can't be
    prevented" (the lock Whippoorwill arms) is capped all the same, where a
    shield would be switched off."""
    from engine.damage_events import DAMAGE_LOCK

    game, (_presence, wall), (giant,) = _w1g5_table(
        [set_pool("INV")["Divine Presence"], _w1g5_creature("Wall", 0, 7, ("W",))],
        [_w1g5_creature("Giant", 7, 7, ("R",))],
    )
    wall.metadata[DAMAGE_LOCK] = True
    assert _w1g5_damage_dealt(game, wall, 7, source=giant) == 3


# --- Spreading Plague ------------------------------------------------------
# "Whenever a creature enters, destroy all other creatures that share a color
# with it. They can't be regenerated." A sweep narrowed by a relation to the
# object the firing event was about.


def _w1g5_cast_creature(game, seat, card):
    game.players[seat].hand.append(card)
    result = game.cast_from_hand(seat, card.name)
    assert result.supported, result.details
    _w1g5_resolve_stack(game)  # W1G5: the creature has entered and the Plague resolved


def test_w1g5_spreading_plague_kills_what_shares_a_colour_with_the_arrival(set_pool):
    """A white creature enters: every other white creature dies on both sides,
    a white-black one included (CR 105.2b); blue and red ones live; the
    arrival itself is "other" than nothing and lives; and a regeneration
    shield does not save its creature."""
    plague = set_pool("INV")["Spreading Plague"]
    assert _w1g5_compile(plague).supported
    game, (_plague, white, blue, gold, troll), (their_white, red) = _w1g5_table(
        [
            plague,
            _w1g5_creature("Knight", 2, 2, ("W",)),
            _w1g5_creature("Drake", 2, 2, ("U",)),
            _w1g5_creature("Envoy", 2, 2, ("W", "B")),
            _w1g5_creature("Troll", 2, 2, ("W",), text="{W}: Regenerate this creature."),
        ],
        [_w1g5_creature("Squire", 2, 2, ("W",)), _w1g5_creature("Raider", 2, 2, ("R",))],
    )
    shielded = game.activate_permanent_ability(
        0, "Troll", permanent_index=game.battlefield_index_of(troll)
    )
    assert shielded.supported, shielded.details
    _w1g5_resolve_stack(game)

    _w1g5_cast_creature(game, 0, _w1g5_creature("Arrival", 2, 2, ("W",)))

    alive = {perm.card.name for perm in game.all_permanents()}
    assert alive == {"Spreading Plague", "Drake", "Raider", "Arrival"}, alive
    for dead in (white, gold, troll, their_white):
        assert not game.is_on_battlefield(dead), dead.card.name
    assert game.is_on_battlefield(blue) and game.is_on_battlefield(red)


def test_w1g5_spreading_plague_spares_everything_from_a_colourless_arrival(set_pool):
    """CR 105.2c: a colourless creature shares a colour with nothing, another
    colourless creature included — so an artifact creature entering under the
    Plague kills no one."""
    game, board, _ = _w1g5_table(
        [
            set_pool("INV")["Spreading Plague"],
            _w1g5_creature("Knight", 2, 2, ("W",)),
            _w1g5_creature("Golem", 2, 2, (), type_line="Artifact Creature - Golem"),
        ],
        [],
    )
    _w1g5_cast_creature(
        game, 0, _w1g5_creature("Rock", 2, 2, (), type_line="Artifact Creature - Golem")
    )
    assert len(list(game.all_permanents())) == 4
    assert any("is colorless and shares a color with nothing" in line for line in game.log)


def test_w1g5_spreading_plague_fires_for_either_players_creature(set_pool):
    """"A creature" names no controller: the opponent's black arrival kills the
    Plague's controller's black creature, and a noncreature permanent entering
    fires nothing at all."""
    game, (_plague, mine), _ = _w1g5_table(
        [set_pool("INV")["Spreading Plague"], _w1g5_creature("Ghoul", 2, 2, ("B",))],
        [],
    )
    game._put_permanent_onto_battlefield(
        0, _W1G5Permanent(card=set_pool("INV")["Well-Laid Plans"]), None
    )
    _w1g5_resolve_stack(game)
    assert game.is_on_battlefield(mine)

    game._put_permanent_onto_battlefield(
        1, _W1G5Permanent(card=_w1g5_creature("Shade", 1, 1, ("B",))), None
    )
    _w1g5_resolve_stack(game)
    assert not game.is_on_battlefield(mine)
    assert {perm.card.name for perm in game.controlled_by(1)} == {"Shade"}


def test_w1g5_only_a_sweep_under_an_event_reads_shares_a_color_with_it():
    """The key is resolved by the one handler that holds the trigger's context,
    so every other position the phrase could be printed in refuses the line
    rather than carrying a narrowing nothing tests."""
    from engine.grammar import compile_line

    plague = compile_line(
        "Whenever a creature enters, destroy all other creatures that share a "
        "color with it. They can't be regenerated."
    )
    assert plague.usable
    assert plague.instructions[0].payload == {
        "type_filter": "creature", "shares_color_with_event_subject": True,
        "other_than_event_subject": True, "bypass_regeneration": True,
    }
    for refused in (
        "Destroy all creatures that share a color with it.",
        "When this creature enters, destroy all other creatures that share a color with it.",
        "Whenever a creature enters, destroy target creature that shares a color with it.",
        "Whenever a creature enters, exile all other creatures that share a color with it.",
        "Whenever a creature enters, tap all creatures that share a color with it.",
    ):
        assert not compile_line(refused).usable, refused


# --- Mana Maze -------------------------------------------------------------
# "Players can't cast spells that share a color with the spell most recently
# cast this turn." A CR 601.3a prohibition comparing two spells.


def _w1g5_spell(name, colors, type_line="Creature - Test"):
    return _w1g5_creature(name, 1, 1, colors, type_line=type_line)  # W1G5: a castable


def test_w1g5_mana_maze_refuses_a_spell_sharing_the_last_spells_colour(set_pool):
    """One turn, cast by cast. The first spell of the turn is free; the second
    white one is refused with nothing spent and the card still in hand; a gold
    spell is stopped by either of its colours (CR 105.2b) and passes when it
    shares neither; and a colourless spell both passes and clears the way,
    because it shares a colour with nothing (CR 105.2c)."""
    maze = set_pool("INV")["Mana Maze"]
    assert _w1g5_compile(maze).supported
    hand = [
        _w1g5_spell("White One", ("W",)), _w1g5_spell("White Two", ("W",)),
        _w1g5_spell("White-Blue", ("W", "U")), _w1g5_spell("Black-Red", ("B", "R")),
        _w1g5_spell("Black One", ("B",)),
        _w1g5_spell("Bauble", (), type_line="Artifact"),
    ]
    game, _board, _ = _w1g5_table([maze], [], hand0=hand)
    me = game.players[0]

    def cast(name):
        result = game.cast_from_hand(0, name)
        _w1g5_resolve_stack(game)
        return result

    assert cast("White One").supported
    refused = cast("White Two")
    assert not refused.supported and "Mana Maze" in refused.details
    assert any(card.name == "White Two" for card in me.hand)
    assert not cast("White-Blue").supported          # shares white
    assert cast("Black-Red").supported               # shares nothing with white
    assert not cast("Black One").supported           # shares black
    assert cast("Bauble").supported                  # colourless shares nothing…
    assert cast("Black One").supported               # …and is now the last spell
    assert cast("White Two").supported


def test_w1g5_mana_maze_binds_every_player_and_forgets_at_the_turn(set_pool):
    """"Players": the opponent's spell is compared against the Maze's
    controller's, in either direction. And "this turn": the first spell of the
    next turn is compared against nothing."""
    game, _board, _ = _w1g5_table(
        [set_pool("INV")["Mana Maze"]], [],
        hand0=[_w1g5_spell("Green One", ("G",)), _w1g5_spell("Green Two", ("G",))],
        hand1=[_w1g5_spell("Green Three", ("G",), type_line="Instant"),
               _w1g5_spell("Green Four", ("G",))],
    )
    assert game.cast_from_hand(0, "Green One").supported
    _w1g5_resolve_stack(game)
    refused = game.cast_from_hand(1, "Green Three")
    assert not refused.supported and "Mana Maze" in refused.details

    game.start_turn(1)
    game._close_current_priority_step()
    assert game.cast_from_hand(1, "Green Four").supported


def test_w1g5_mana_maze_does_not_stop_a_land_and_the_ai_stops_proposing(set_pool):
    """A land is played, not cast (CR 305.1), so the Maze never reaches it. And
    a restriction is enforced in two places: the cast path refuses, and the
    AI's proposal filter asks the same predicate — otherwise a seat re-proposes
    its second green spell all turn and does nothing."""
    from engine.ai_policy import _can_cast_with_targets
    from engine.cast_restrictions import last_cast_color_ban

    second = _w1g5_spell("Green Two", ("G",))
    game, _board, _ = _w1g5_table(
        [set_pool("INV")["Mana Maze"]], [],
        hand0=[_w1g5_spell("Green One", ("G",)), second, set_pool("LEA")["Forest"]],
    )
    assert _can_cast_with_targets(game, 0, second)
    assert game.cast_from_hand(0, "Green One").supported
    _w1g5_resolve_stack(game)
    assert last_cast_color_ban(game, 0, second) == "Mana Maze"
    assert not _can_cast_with_targets(game, 0, second)
    assert last_cast_color_ban(game, 0, set_pool("LEA")["Forest"]) is None
    assert game.cast_from_hand(0, "Forest").supported


# --- Rewards of Diversity --------------------------------------------------
# "Whenever an opponent casts a multicolored spell, you gain 4 life."


def test_w1g5_rewards_of_diversity_pays_for_an_opponents_gold_spell_only(set_pool):
    """Three casts: an opponent's monocoloured spell (nothing), an opponent's
    gold spell (4 life), and the enchantment's own controller's gold spell
    (nothing — the trigger says "an opponent")."""
    rewards = set_pool("INV")["Rewards of Diversity"]
    assert _w1g5_compile(rewards).supported
    gold = set_pool("INV")["Shivan Zombie"]
    game, _board, _ = _w1g5_table(
        [rewards], [], hand0=[gold],
        hand1=[gold, set_pool("LEA")["Grizzly Bears"]],
    )
    me = game.players[0]
    game.start_turn(1)
    game._close_current_priority_step()

    assert game.cast_from_hand(1, "Grizzly Bears").supported
    _w1g5_resolve_stack(game)
    assert me.life == 20
    assert game.cast_from_hand(1, "Shivan Zombie").supported
    _w1g5_resolve_stack(game)
    assert me.life == 24

    game.start_turn(0)
    game._close_current_priority_step()
    assert game.cast_from_hand(0, "Shivan Zombie").supported
    _w1g5_resolve_stack(game)
    assert me.life == 24


def test_w1g5_multicolored_is_a_cast_narrowing_on_every_scope():
    """The marker rides all three cast kinds, read by one helper — and the
    "you cast" row has to come before the subtype row, which would otherwise
    read "multicolored" as a creature type and compile a trigger that never
    fires."""
    from engine.oracle import trigger_condition_of_line

    for line, kind in (
        ("Whenever an opponent casts a multicolored spell, you gain 4 life.",
         "opponent_casts_spell"),
        ("Whenever a player casts a multicolored spell, you gain 1 life.", "spell_cast"),
        ("Whenever you cast a multicolored spell, you gain 1 life.", "you_cast_spell"),
    ):
        condition, _ = trigger_condition_of_line(line)
        assert condition is not None and condition.kind == kind, line
        assert "cast_multicolored" in condition.payload, line
        assert "cast_subtype" not in condition.payload, line


# --- Pledge of Loyalty -----------------------------------------------------
# "Enchanted creature has protection from each color among permanents you
# control. This effect doesn't remove this Aura."


def _w1g5_pledge_table(set_pool, mine, theirs=(), *, hand1=()):
    """Pledge of Loyalty cast onto seat 0's first permanent."""
    game, board0, board1 = _w1g5_table(
        mine, theirs, hand0=[set_pool("INV")["Pledge of Loyalty"]], hand1=hand1
    )
    result = game.cast_from_hand(
        0, "Pledge of Loyalty", target_player_index=0, target_permanent_index=0
    )
    assert result.supported, result.details
    _w1g5_resolve_stack(game)
    # The battlefield list is the live one, so the Aura is now in it: hand back
    # the permanents the caller placed.
    return game, board0[:len(mine)], board1  # W1G5: the Pledge is attached


def test_w1g5_pledge_of_loyalty_protects_from_the_colours_its_controller_shows(set_pool):
    """A green creature beside a red one, under the white Pledge: protection
    from green, red and white and from nothing else — and the wire spells it
    out. The set follows the board: a black permanent arriving adds black, and
    the red one leaving takes red away (CR 611.3a)."""
    from web.serialization import _effective_keywords

    pledge = set_pool("INV")["Pledge of Loyalty"]
    assert _w1g5_compile(pledge).supported
    game, (host, red), _ = _w1g5_pledge_table(
        set_pool,
        [_w1g5_creature("Host", 2, 2, ("G",)), _w1g5_creature("Goblin", 1, 1, ("R",))],
    )
    assert game._protection_colors(host) == {"G", "R", "W"}
    assert _effective_keywords(host, game) == ["Protection from green and red and white"]

    shade = _W1G5Permanent(card=_w1g5_creature("Shade", 1, 1, ("B",)))
    game._put_permanent_onto_battlefield(0, shade, None)
    assert game._protection_colors(host) == {"B", "G", "R", "W"}
    game.remove_from_battlefield(red)
    assert game._protection_colors(host) == {"B", "G", "W"}
    # the other creature beside it is not enchanted and has nothing
    assert game._protection_colors(shade) == set()


def test_w1g5_pledge_of_loyalty_counts_only_its_own_controllers_permanents(set_pool):
    """"You" is the Aura's controller (CR 109.5): the opponent's blue creature
    adds no blue, so their blue creature still deals its damage and a red one
    of theirs is stopped — red is among *my* permanents."""
    game, (host, _red), (drake, raider) = _w1g5_pledge_table(
        set_pool,
        [_w1g5_creature("Host", 2, 2, ("G",)), _w1g5_creature("Goblin", 1, 1, ("R",))],
        [_w1g5_creature("Drake", 2, 2, ("U",)), _w1g5_creature("Raider", 2, 2, ("R",))],
    )
    assert "U" not in game._protection_colors(host)
    assert _w1g5_damage_dealt(game, host, 2, source=drake) == 2
    assert _w1g5_damage_dealt(game, host, 2, source=raider) == 0


def test_w1g5_pledge_of_loyalty_stops_spells_and_stays_on(set_pool):
    """Through real casts. The Pledge is white and gives protection from white,
    and "this effect doesn't remove this Aura" (CR 702.16n) is what keeps it
    attached — a second white Aura on the same creature is put into the
    graveyard by the state-based sweep (CR 702.16c). A red spell cannot target
    the creature (CR 702.16b); a black one, with no black permanent on the
    Pledge's side, can."""
    pool = set_pool("LEA")
    game, (host, _red), _ = _w1g5_table(
        [_w1g5_creature("Host", 2, 2, ("G",)), _w1g5_creature("Goblin", 1, 1, ("R",))],
        [],
        hand0=[pool["Holy Strength"], set_pool("INV")["Pledge of Loyalty"]],
        hand1=[pool["Lightning Bolt"], pool["Terror"]],
    )
    for aura in ("Holy Strength", "Pledge of Loyalty"):
        cast = game.cast_from_hand(0, aura, target_player_index=0, target_permanent_index=0)
        assert cast.supported, cast.details
        _w1g5_resolve_stack(game)
    names = {perm.card.name for perm in game.controlled_by(0)}
    assert "Pledge of Loyalty" in names and "Holy Strength" not in names
    assert any(card.name == "Holy Strength" for card in game.players[0].graveyard)

    bolt = game.cast_from_hand(1, "Lightning Bolt", target_player_index=0, target_permanent_index=0)
    assert not bolt.supported, bolt.details
    terror = game.cast_from_hand(1, "Terror", target_player_index=0, target_permanent_index=0)
    assert terror.supported, terror.details
    _w1g5_resolve_stack(game)
    assert not game.is_on_battlefield(host)


# --- Protective Sphere -----------------------------------------------------
# "{1}, Pay 1 life: Prevent all damage that would be dealt to you this turn by
# a source of your choice that shares a color with the mana spent on this
# activation cost. (Colorless mana prevents no damage.)"


def _w1g5_sphere_table(set_pool, paid_with):
    """Protective Sphere on seat 0 with costs enforced and one mana of
    *paid_with* floating; a red 3/3 and a green 2/2 across the table."""
    game, (sphere,), (giant, bears) = _w1g5_table(
        [set_pool("INV")["Protective Sphere"]],
        [_w1g5_creature("Giant", 3, 3, ("R",)), _w1g5_creature("Bears", 2, 2, ("G",))],
    )
    game.enforce_mana_costs = True
    game.players[0].mana_pool[paid_with] = 1
    return game, sphere, giant, bears  # W1G5: the Sphere's table


def _w1g5_activate_sphere(game, source):
    result = game.activate_permanent_ability(
        0, "Protective Sphere", permanent_index=0,
        target_player_index=game.controller_index_of(source),
        target_permanent_ids=[source.permanent_id],
    )
    assert result.supported, result.details
    _w1g5_resolve_stack(game)  # W1G5: the Sphere's ability has resolved


def test_w1g5_protective_sphere_paid_in_red_stops_the_red_source_all_turn(set_pool):
    """Red mana, the red Giant named: every instance it would deal this turn is
    prevented — "all", not "the next" — while the green creature's damage and
    damage to anything but the Sphere's controller go through. The life is
    paid, and the cleanup step ends the shield."""
    sphere_card = set_pool("INV")["Protective Sphere"]
    assert _w1g5_compile(sphere_card).supported
    from engine.targeting import derive_activation_spec

    spec = derive_activation_spec(_w1g5_compile(sphere_card).activated_abilities[0])
    assert spec["source_of_choice"] is True

    game, _sphere, giant, bears = _w1g5_sphere_table(set_pool, "R")
    me = game.players[0]
    _w1g5_activate_sphere(game, giant)
    assert me.life == 19 and me.mana_pool["R"] == 0

    assert _w1g5_damage_dealt(game, me, 3, source=giant) == 0
    assert _w1g5_damage_dealt(game, me, 3, source=giant, combat=True) == 0
    assert _w1g5_damage_dealt(game, me, 2, source=bears) == 2
    assert _w1g5_damage_dealt(game, game.players[1], 3, source=giant) == 3

    game.resolve_cleanup_step(0)
    assert _w1g5_damage_dealt(game, me, 3, source=giant) == 3


def test_w1g5_protective_sphere_needs_the_source_to_share_the_mana_colour(set_pool):
    """The same activation paid in green prevents nothing from the red Giant —
    the property is rechecked when the damage would be dealt (CR 609.7b) — and
    starts preventing the moment the Giant is made green."""
    game, _sphere, giant, _bears = _w1g5_sphere_table(set_pool, "G")
    me = game.players[0]
    _w1g5_activate_sphere(game, giant)
    assert _w1g5_damage_dealt(game, me, 3, source=giant) == 3

    # Lifelace: "Target spell or permanent becomes green." A real layer-5
    # change (CR 105.3), cast for free so the test is about the shield.
    game.enforce_mana_costs = False
    me.hand.append(set_pool("LEA")["Lifelace"])
    laced = game.cast_from_hand(
        0, "Lifelace", target_player_index=1,
        target_permanent_index=game.battlefield_index_of(giant),
    )
    assert laced.supported, laced.details
    _w1g5_resolve_stack(game)
    assert game._effective_colors(giant) == {"G"}
    assert _w1g5_damage_dealt(game, me, 3, source=giant) == 0


def test_w1g5_protective_sphere_paid_with_colorless_mana_prevents_nothing(set_pool):
    """"(Colorless mana prevents no damage.)" The cost is paid — the life too —
    and no shield is armed at all, rather than one that answers every source."""
    game, _sphere, giant, bears = _w1g5_sphere_table(set_pool, "C")
    me = game.players[0]
    _w1g5_activate_sphere(game, giant)
    assert me.life == 19
    assert _w1g5_damage_dealt(game, me, 3, source=giant) == 3
    assert _w1g5_damage_dealt(game, me, 2, source=bears) == 2
    assert any("no colored mana was spent" in line for line in game.log)


def test_w1g5_protective_sphere_with_no_source_named_never_arms_a_blanket(set_pool):
    """A seat that names no source takes the stated default — the opponent's
    biggest creature *that shares a colour with the mana spent* — and never a
    shield against every source, which is a different and far larger card."""
    game, _sphere, giant, bears = _w1g5_sphere_table(set_pool, "G")
    me = game.players[0]
    result = game.activate_permanent_ability(0, "Protective Sphere", permanent_index=0)
    assert result.supported, result.details
    _w1g5_resolve_stack(game)
    assert _w1g5_damage_dealt(game, me, 2, source=bears) == 0   # green, chosen
    assert _w1g5_damage_dealt(game, me, 3, source=giant) == 3   # red, not chosen
    assert _w1g5_damage_dealt(game, me, 4) == 4                 # no source at all
