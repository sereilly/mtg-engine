"""Urza's Saga creatures.

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

Cards come from `set_pool("USG")` / `set_cards("USG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G2: echo (CR 702.30) ---
import pytest

from engine import Game
from engine.echo import echo_cost
from engine.models import CardDefinition, Permanent, PlayerState
from engine.oracle import compile_card_oracle, simple_card_keywords

from tests.helpers import resolve_stack

#: Every Urza's Saga card that prints echo, with the cost it prints.
#: Spelled out rather than derived from ``mana_cost``: CR 702.30b makes the two
#: equal *for this block*, and a test that derived one from the other would pass
#: on a card whose echo cost the engine never read. Twelve distinct costs over
#: fourteen cards, so nothing here can be special-cased on one.
_G2_ECHO_CARDS = (
    ("Acridian", "{1}{G}"),
    ("Albino Troll", "{1}{G}"),
    ("Citanul Centaurs", "{3}{G}"),
    ("Cradle Guard", "{1}{G}{G}"),
    ("Crater Hellion", "{4}{R}{R}"),
    ("Goblin Patrol", "{R}"),
    ("Goblin War Buggy", "{1}{R}"),
    ("Herald of Serra", "{2}{W}{W}"),
    ("Lightning Dragon", "{2}{R}{R}"),
    ("Pouncing Jaguar", "{G}"),
    ("Shivan Raptor", "{2}{R}"),
    ("Viashino Outrider", "{2}{R}"),
    ("Vug Lizard", "{1}{R}{R}"),
    ("Winding Wurm", "{4}{G}"),
)


def _g2_echo_trigger(card):
    """The one gated upkeep trigger echo compiles to on *card*."""
    program = compile_card_oracle(card)
    return next(
        trig for trig in program.triggered_abilities
        if trig.instruction is not None
        and "intervening_if" in (trig.instruction.payload or {})
    )


def _g2_prism(index: int) -> CardDefinition:
    """A land that taps for one mana of any colour.

    One fixture for fourteen cards whose echo costs run over four colours;
    an upkeep cost is paid by tapping lands during the step, so the observable
    is how many were tapped and the colour they made is nobody's subject here.
    """
    name = f"G2 Prism {index}"
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Land",
        oracle_text="{T}: Add one mana of any color.",
        colors=(), color_identity=(), keywords=(),
        produced_mana=("W", "U", "B", "R", "G"),
        raw={"name": name, "type_line": "Land"},
    )


def _g2_rig(lands: int):
    p1 = PlayerState(
        name="P1", life=20,
        battlefield=[Permanent(card=_g2_prism(i)) for i in range(lands)],
    )
    p2 = PlayerState(name="P2", life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.begin_turn_bookkeeping(0)
    return game, p1, p2


def _g2_next_turn(game, seat: int) -> None:
    game.turn += 1
    game.begin_turn_bookkeeping(seat)


def _g2_play_to_the_echo_upkeep(card, lands: int):
    """Put *card* onto the battlefield on P1's turn, then run the turns up to
    the upkeep at which CR 702.30a says its echo is due.

    Through ``_put_permanent_onto_battlefield`` — the one entry path there is —
    so the permanent has an id, a base controller and its layer contributions,
    the same way it would in a real game. See ``tests/rules/test_echo.py`` for
    the window's own tests, including the two that drive the drivers that do
    this differently.
    """
    game, p1, _p2 = _g2_rig(lands)
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(0, permanent, None)
    _g2_next_turn(game, 1)
    _g2_next_turn(game, 0)
    return game, p1, permanent


def _g2_tapped_land_count(player) -> int:
    return sum(
        1 for perm in player.battlefield
        if perm.card.primary_type == "land" and perm.tapped
    )


def _g2_untap_lands(player) -> None:
    for perm in player.battlefield:
        perm.tapped = False


@pytest.mark.parametrize("name,cost", _G2_ECHO_CARDS)
def test_w1g2_every_usg_echo_card_compiles_with_its_printed_cost(set_pool, name, cost):
    """All fourteen, with the cost read off the printed line.

    ``echo_cost`` is asked of the card's own text rather than of a fixture, so
    this fails if an ingest ever changes the reminder text's shape — which is
    the one thing that could stop the reader finding a cost while every card
    still reported supported on some other line.
    """
    card = set_pool("USG")[name]
    program = compile_card_oracle(card)

    assert program.supported, program.reason
    printed = next(
        line for line in card.oracle_text.splitlines() if line.startswith("Echo")
    )
    assert echo_cost(printed) == cost
    trigger = _g2_echo_trigger(card)
    assert trigger.condition.kind == "upkeep_self"
    assert trigger.instruction.kind == "upkeep_pay_or_sacrifice_self"
    assert trigger.instruction.payload["intervening_if"] == {
        "kind": "came_under_your_control_since_your_last_upkeep"
    }
    assert trigger.source_line.endswith("pay " + cost + ".")


@pytest.mark.parametrize("name,cost", _G2_ECHO_CARDS)
def test_w1g2_the_urza_block_errata_gives_each_one_its_mana_cost(set_pool, name, cost):
    """CR 702.30b, asserted about the *data* rather than about the engine.

    The ingested text already carries the errata, which is why nothing in
    ``engine/echo.py`` derives a cost from ``mana_cost`` — and this is what says
    the two really are equal here, so declining to derive is a decision rather
    than an accident nobody could have noticed.
    """
    assert set_pool("USG")[name].mana_cost == cost


def test_w1g2_pouncing_jaguar_pays_its_echo_once_and_then_never_again(set_pool):
    """A real board, a real upkeep, and the second cycle charging nothing."""
    game, p1, jaguar = _g2_play_to_the_echo_upkeep(set_pool("USG")["Pouncing Jaguar"], 3)

    assert [c["card_name"] for c in game.get_upkeep_pay_triggers(0)] == ["Pouncing Jaguar"]
    game.resolve_upkeep(0)
    assert jaguar in p1.battlefield
    assert _g2_tapped_land_count(p1) == 1, "{G} is one land"

    _g2_untap_lands(p1)
    _g2_next_turn(game, 1)
    _g2_next_turn(game, 0)
    assert game.get_upkeep_pay_triggers(0) == []
    game.resolve_upkeep(0)
    assert jaguar in p1.battlefield
    assert _g2_tapped_land_count(p1) == 0


def test_w1g2_winding_wurm_is_sacrificed_when_its_echo_goes_unpaid(set_pool):
    """{4}{G} on a board of four lands: the whole cost or nothing (CR 118.3),
    and nothing is what gets spent."""
    game, p1, wurm = _g2_play_to_the_echo_upkeep(set_pool("USG")["Winding Wurm"], 4)

    game.resolve_upkeep(0)

    assert wurm not in p1.battlefield
    assert [c.name for c in p1.graveyard] == ["Winding Wurm"]
    assert _g2_tapped_land_count(p1) == 0


def test_w1g2_crater_hellion_keeps_its_entry_trigger_beside_its_echo(set_pool):
    """The rewrite replaces one line, not the card — and the two triggers are
    told apart by their conditions rather than by their order."""
    program = compile_card_oracle(set_pool("USG")["Crater Hellion"])

    assert program.supported
    assert sorted(trig.condition.kind for trig in program.triggered_abilities) == [
        "enters_battlefield", "upkeep_self",
    ]
    entry = next(
        trig for trig in program.triggered_abilities
        if trig.condition.kind == "enters_battlefield"
    )
    assert entry.instruction.kind == "deal_damage_each_matching"
    assert entry.instruction.payload["amount"] == 4


def test_w1g2_crater_hellion_still_sweeps_the_board_as_it_enters(set_pool):
    """…and does it, rather than merely compiling to it."""
    pool = set_pool("USG")
    game, p1, p2 = _g2_rig(0)
    bystander = Permanent(card=pool["Acridian"])   # a 2/2
    game._put_permanent_onto_battlefield(1, bystander, None)

    hellion = Permanent(card=pool["Crater Hellion"])
    game._put_permanent_onto_battlefield(0, hellion, None)
    resolve_stack(game)
    game.check_state_based_actions()

    assert bystander not in p2.battlefield, "4 damage kills a 2/2"
    assert hellion in p1.battlefield, "'each other creature' spares the Hellion"


@pytest.mark.parametrize("name,keyword", [
    ("Herald of Serra", "flying"),
    ("Herald of Serra", "vigilance"),
    ("Shivan Raptor", "first strike"),
    ("Shivan Raptor", "haste"),
    ("Goblin War Buggy", "haste"),
    ("Cradle Guard", "trample"),
    ("Citanul Centaurs", "shroud"),
    ("Vug Lizard", "mountainwalk"),
])
def test_w1g2_an_echo_creatures_other_keywords_survive_the_rewrite(set_pool, name, keyword):
    """Eight keyword lines across six of the fourteen. The rewrite is per-line,
    so a keyword line beside the echo line must be untouched — and Vug Lizard's
    carries reminder text of its own, which is the case a whole-text rewrite
    would have eaten."""
    program = compile_card_oracle(set_pool("USG")[name])

    assert program.supported
    assert any(keyword in line.lower() for line in program.static_lines), (
        name + " lost " + keyword + " to the echo rewrite: " + repr(program.static_lines)
    )


def test_w1g2_albino_trolls_regeneration_still_compiles_beside_its_echo(set_pool):
    program = compile_card_oracle(set_pool("USG")["Albino Troll"])

    assert program.supported
    assert [ab.instruction.kind for ab in program.activated_abilities] == [
        "grant_regeneration_to_self"
    ]


def test_w1g2_lightning_dragons_pump_still_compiles_beside_its_echo(set_pool):
    program = compile_card_oracle(set_pool("USG")["Lightning Dragon"])

    assert program.supported
    assert len(program.activated_abilities) == 1
    assert program.activated_abilities[0].cost.mana["R"] == 1


def test_w1g2_goblin_war_buggy_is_an_artifact_creature_that_still_echoes(set_pool):
    """The one echo card in the set whose body is an artifact. Echo is a
    keyword of *permanents*, so nothing about the rewrite may be keyed to the
    creature front end."""
    game, p1, _p2 = _g2_play_to_the_echo_upkeep(set_pool("USG")["Goblin War Buggy"], 2)

    assert [c["card_name"] for c in game.get_upkeep_pay_triggers(0)] == ["Goblin War Buggy"]
    game.resolve_upkeep(0)
    assert p1.battlefield[-1].card.name == "Goblin War Buggy"
    assert _g2_tapped_land_count(p1) == 2


def test_w1g2_an_echo_creature_is_not_auto_passed_by_the_verification_tracker(set_pool):
    """A card whose printed text is keyword lines only is auto-passed as having
    no card-specific path to exercise. An echo card looks like one and is not:
    the rewrite gives it a triggered ability, so the tracker has to ask for a
    real check."""
    assert simple_card_keywords(set_pool("USG")["Acridian"]) is None
    assert simple_card_keywords(set_pool("USG")["Goblin Patrol"]) is None

# --- W1G1: cycling (CR 702.29) ---
import pytest

from engine import Game, PlayerState
from engine.activation_zones import HAND
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from tests.helpers import resolve_stack

#: The eight creatures printing cycling. Seven of them were reported
#: "creature text too complex" on the keyword line before the CR 702.29a
#: rewrite; Wild Dogs was refused for its upkeep trigger instead and still is
#: (that line belongs to another group), which is why it is not here.
_G1_CYCLING_CREATURES = (
    "Disciple of Grace",
    "Disciple of Law",
    "Shimmering Barrier",
    "Drifting Djinn",
    "Pendrell Drake",
    "Sandbar Merfolk",
    "Sandbar Serpent",
)


def _g1_creature_game(card, *, library=4):
    """Seat 0 holds *card* and has a library worth drawing from."""
    filler = card
    player = PlayerState(name="G1-A", hand=[card], library=[filler] * library)
    game = Game(players=[player, PlayerState(name="G1-B")])
    game.enforce_mana_costs = False
    return game, player


@pytest.mark.parametrize("name", _G1_CYCLING_CREATURES)
def test_w1g1_a_cycling_creature_cycles_from_hand_and_not_from_play(set_pool, name):
    """A creature with cycling is two different cards depending on the zone.

    In hand it is "{2}: draw a card"; on the battlefield it is a creature with
    no activated ability at all (CR 702.29b — the ability exists there, and
    CR 113.6j says it does not *function* there). Getting the second half wrong
    is not a missing feature: it is a free repeatable draw, on eight cards.
    """
    card = set_pool("USG")[name]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    assert [a.source_line for a in usable_activated_abilities(program)] == []
    assert [a.source_line for a in usable_activated_abilities(program, zone=HAND)] == [
        "{2}, Discard this card: Draw a card."
    ]

    game, player = _g1_creature_game(card)
    assert game.activate_from_hand(0, name).supported
    resolve_stack(game)
    assert [c.name for c in player.graveyard] == [name]
    assert len(player.hand) == 1

    game, player = _g1_creature_game(card)
    player.hand.clear()
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    player.battlefield.append(perm)
    library_before = len(player.library)
    refusal = game.activate_permanent_ability(0, name)
    assert refusal.supported is False
    assert "113.6" in refusal.details, refusal.details
    assert len(player.library) == library_before
    assert player.graveyard == []


def test_w1g1_the_keyword_creatures_keep_the_keywords_beside_it(set_pool):
    """Cycling is printed *under* a keyword line on four of them, so the rewrite
    has to leave the other lines alone. Disciple of Grace's protection from
    black and Shimmering Barrier's defender + first strike are what a rewrite
    that consumed too much would take away."""
    pool = set_pool("USG")
    assert compile_card_oracle(pool["Disciple of Grace"]).static_lines == (
        "protection from black",
    )
    assert compile_card_oracle(pool["Disciple of Law"]).static_lines == (
        "protection from red",
    )
    barrier = compile_card_oracle(pool["Shimmering Barrier"])
    assert set(barrier.static_lines) == {"defender", "first strike"}

# --- W1G5: Carrion Beetles, the picker-sweep finding that is not a hollow card ---
from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import _mk_creature_card, resolve_stack


def _g5c_game():
    """Two seats with no mana enforcement, ending on its own three-tuple.

    The ``_g5c_`` prefix and the distinct ending are SET_PLAYBOOK.md's rule
    about a mechanical union splicing one helper's body onto another's
    signature.
    """
    p1, p2 = PlayerState(name="G5A"), PlayerState(name="G5B")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2


def test_w1g5_carrion_beetles_exiles_three_cards_from_one_graveyard(set_pool):
    """{2}{B}, {T}: Exile up to three target cards from a single graveyard.

    Carrion Beetles is in ``picker_sweep`` and in **neither** of the other two
    instruments, which is the whole reading of it: the ability is implemented
    and works. What the sweep names is that its cards are chosen at *resolution*
    rather than announced (CR 601.2c) — ROADMAP.md's recorded decline for a
    graveyard target, not a card doing nothing.

    So this test is the evidence for that reading rather than a fix: the cards
    leave the pile, and they all leave the same one.
    """
    game, _p1, p2 = _g5c_game()
    beetles = Permanent(card=set_pool("USG")["Carrion Beetles"])
    game._put_permanent_onto_battlefield(0, beetles, None)
    game._sync_control()
    # CR 302.6: the {T} half of the cost needs a creature that has been under
    # its controller's control since their turn began, and the entry path is
    # what stamps the turn this reads.
    beetles.metadata.pop("summoning_sickness_turn", None)
    for i in range(4):
        p2.graveyard.append(_mk_creature_card("G5 Corpse%d" % i, 1, 1))

    assert game.activate_permanent_ability(0, "Carrion Beetles").supported
    resolve_stack(game)

    assert len(p2.exile) == 3
    assert len(p2.graveyard) == 1
    assert not game.pending_choices, "one pile with legal cards is not a decision"
