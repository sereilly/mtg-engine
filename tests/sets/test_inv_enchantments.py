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
