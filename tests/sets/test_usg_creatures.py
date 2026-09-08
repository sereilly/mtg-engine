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


# --- W2G3: an Aura put onto the battlefield attached as it arrives ---
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle

from tests.helpers import _mk_card, resolve_stack


def _g3w2c_table(*, interactive=()):
    """Two seats, mana enforcement off, and whichever of them answers prompts.

    ``_g3w2c_`` prefixed and ending on ``return game, game.players[0],
    game.players[1]`` — SET_PLAYBOOK.md's note about a union splicing one
    helper's body onto another's signature.
    """
    game = Game(players=[PlayerState(name="W2G3C-A"), PlayerState(name="W2G3C-B")])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, game.players[0], game.players[1]


def _g3w2c_aura(name, enchant="creature", effect="Enchanted creature gets +1/+1."):
    return _mk_card(
        name=name, mana_cost="{W}", type_line="Enchantment - Aura",
        oracle_text=f"Enchant {enchant}\n{effect}",
    )


def test_w2g3_academy_researchers_arrives_wearing_the_aura(set_pool):
    """"When this creature enters, you may put an Aura card from your hand onto
    the battlefield attached to this creature."

    CR 303.4f attaches the Aura as it enters, so the two halves are one event:
    an Aura that existed for even one state-based check attached to nothing
    would be in a graveyard by now (CR 704.5m).
    """
    card = set_pool("USG")["Academy Researchers"]
    assert compile_card_oracle(card).supported

    game, alice, bob = _g3w2c_table()
    alice.hand = [_g3w2c_aura("W2G3 Blessing")]
    researcher = Permanent(card=card)
    game._put_permanent_onto_battlefield(0, researcher, None)
    game._sync_control()
    resolve_stack(game)
    game.auto_resolve_pending_choices()

    aura = next(
        perm for perm in game.controlled_by(0)
        if perm.card.name == "W2G3 Blessing"
    )
    assert aura.metadata.get("attached_to") is researcher
    assert alice.graveyard == [], "it did not fall off for want of a host"
    assert researcher.effective_power == 3, "and its grant applies (2/2 base, +1/+1)"


def test_w2g3_academy_researchers_never_offers_an_illegal_aura(set_pool):
    """CR 303.4a: an Aura may be put onto the battlefield only attached to
    something its own enchant ability can enchant. An Aura the Researchers
    cannot carry is not among the answers — offered and taken it would leave
    the card out of the hand and the Aura in a graveyard.
    """
    game, alice, bob = _g3w2c_table()
    land_aura = _g3w2c_aura(
        "W2G3 Overgrowth", enchant="land", effect="Enchanted land gets +0/+0."
    )
    alice.hand = [land_aura]
    researcher = Permanent(card=set_pool("USG")["Academy Researchers"])
    game._put_permanent_onto_battlefield(0, researcher, None)
    game._sync_control()
    resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert [c.name for c in alice.hand] == ["W2G3 Overgrowth"], "it stayed in hand"
    assert alice.graveyard == []


# --- W2G4: what a permanent may not do, and the durations that end it ---
import pytest

from engine import Game, PlayerState
from engine.combat_restrictions import combat_restriction_for
from engine.models import Permanent
from engine.oracle import compile_card_oracle, normalize_creature_line

from tests.helpers import resolve_stack as _g4b_resolve


def _g4b_board(*, mine=(), theirs=(), hand0=(), life=20):
    """A two-seat game with mana costs off and control synced, seat 0 active.

    Returns ``(game, seat0, seat1)`` and ends on that tuple, so no mechanical
    union can splice another group's helper body onto this signature.
    """
    g4b_seat0 = PlayerState(
        name="G4-A", battlefield=[Permanent(card=c) for c in mine],
        hand=list(hand0), life=life,
    )
    g4b_seat1 = PlayerState(
        name="G4-B", battlefield=[Permanent(card=c) for c in theirs], life=life,
    )
    g4b_game = Game(players=[g4b_seat0, g4b_seat1])
    g4b_game.enforce_mana_costs = False
    g4b_game.active_player_index = 0
    g4b_game._sync_control()
    return g4b_game, g4b_seat0, g4b_seat1


def _g4b_creature(name, power=2, toughness=2):
    from tests.helpers import _mk_creature_card

    return _mk_creature_card(name, power, toughness)


def test_w2g4_okk_needs_a_bigger_attacker_beside_it(set_pool):
    """CR 508.1c asks its restrictions of the **declaration**, which is why no
    per-creature predicate can answer this one: what makes Okk's attack legal is
    a fact about who else was declared."""
    pool = set_pool("USG")
    game, mine, _ = _g4b_board(
        mine=[pool["Okk"], _g4b_creature("G4B Small", 2, 2),
              _g4b_creature("G4B Big", 6, 6)],
    )
    okk, small, big = mine.battlefield
    assert okk.effective_power == 4

    def refusal(declared):
        found = game.attack_declaration_refusal(declared)
        return None if found is None else found[1]

    assert refusal([okk]) is not None
    assert refusal([okk, small]) is not None, "2/2 is not greater power than 4"
    assert refusal([okk, big]) is None
    # …and the companion alone is unrestricted.
    assert refusal([small]) is None


def test_w2g4_okk_reads_power_live_rather_than_off_the_printed_number(set_pool):
    """CR 613 computes power, so a companion pumped in response qualifies and a
    pumped Okk needs a bigger one. Reading the printed 4 would make both wrong
    in the direction of letting the attack through."""
    from engine.pt import add_pt_modifier

    pool = set_pool("USG")
    game, mine, _ = _g4b_board(
        mine=[pool["Okk"], _g4b_creature("G4B Peer", 4, 4)],
    )
    okk, peer = mine.battlefield

    assert game.attack_declaration_refusal([okk, peer]) is not None
    add_pt_modifier(peer, 1, 0)
    assert game.attack_declaration_refusal([okk, peer]) is None


def test_w2g4_okk_needs_a_bigger_blocker_beside_it(set_pool):
    """CR 509.1b's side of the same rule, asked where the block declaration is
    assembled."""
    pool = set_pool("USG")
    game, mine, theirs = _g4b_board(
        mine=[_g4b_creature("G4B Attacker", 1, 1)],
        theirs=[pool["Okk"], _g4b_creature("G4B Wall", 0, 6),
                _g4b_creature("G4B Ogre", 6, 6)],
    )
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    assert game.declare_attackers(0, {0: 1})[0]
    game.current_step = "declare_blockers"

    alone, why = game.declare_blockers(1, {0: 0})
    assert not alone and "greater power" in why
    game.combat_blockers = {}
    assert game.declare_blockers(1, {0: 0, 2: 0})[0]


def test_w2g4_wirecat_fights_on_an_empty_board_and_not_otherwise(set_pool):
    """The qualifier is the whole card. Read as an unconditional restriction the
    Cat is a 2/2 for {4} that never attacks and never blocks; the clause dropped
    the other way, it is a 2/2 for {4} with no drawback at all."""
    pool = set_pool("USG")
    game, mine, theirs = _g4b_board(
        mine=[pool["Wirecat"]], theirs=[_g4b_creature("G4B Bear")],
    )
    cat = mine.battlefield[0]
    attacker = theirs.battlefield[0]

    assert game.can_attack(cat, 1)
    assert game._can_block_attacker(cat, attacker)

    # CR 403.1 makes the battlefield a shared zone, so an *opponent's*
    # enchantment grounds the Cat too.
    theirs.battlefield.append(Permanent(card=pool["Bedlam"]))
    game._sync_control()
    assert not game.can_attack(cat, 1)
    assert not game._can_block_attacker(cat, attacker)


def test_w2g4_wirecats_clause_reaches_both_halves_of_its_sentence(set_pool):
    """One sentence, two prohibitions, one condition — the ``also_kinds`` shape.
    A row that produced only the attack half would leave the Cat blocking with
    an enchantment out, which is half a card."""
    read = combat_restriction_for(
        normalize_creature_line(set_pool("USG")["Wirecat"].oracle_text)
    )
    assert read is not None
    assert (read.kind, read.also_kinds) == ("cant_attack", ("cant_block",))
    assert read.payload["condition"] == {
        "who": "anyone", "subject": {"type_filter": "enchantment"},
    }


def test_w2g4_a_qualified_restriction_still_refuses_where_nothing_asks(set_pool):
    """The gate the row above passes is per **kind**, not per sentence: a clause
    attached to a kind whose enforcement site never looks at one would be a
    restriction applied unconditionally, which is the silent direction."""
    assert combat_restriction_for(
        "this creature attacks each combat if able if an enchantment is on the "
        "battlefield"
    ) is None
    assert combat_restriction_for(
        "this creature attacks each combat if able"
    ) is not None


def test_w2g4_somnophore_holds_its_creature_only_while_it_is_there(set_pool):
    """"For as long as this creature remains on the battlefield" is not a step
    boundary and not "while tapped": the Somnophore attacks (and taps) with the
    lock still on, and the lock ends the moment it leaves."""
    pool = set_pool("USG")
    game, mine, theirs = _g4b_board(
        mine=[pool["Somnophore"]], theirs=[_g4b_creature("G4B Victim")],
    )
    somno = mine.battlefield[0]
    victim = theirs.battlefield[0]
    victim.tapped = True

    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"
    assert game.declare_attackers(0, {0: 1})[0]
    game.current_step = "declare_blockers"
    game.declare_blockers(1, {})
    game.current_step = "combat_damage"
    game.resolve_all_combat_damage(0)
    for item in game.stack:
        item.target = theirs
        item.target_permanent_index = 0
        item.target_permanent_id = victim.permanent_id
    _g4b_resolve(game)

    assert victim.tapped, "the trigger taps what it names"
    assert somno.metadata["untap_lock_while_present"] == victim.permanent_id

    game.active_player_index = 1
    game.resolve_untap_step(1)
    assert victim.tapped, "the Somnophore is still there, tapped or not"

    game.remove_from_battlefield(somno)
    game.resolve_untap_step(1)
    assert not victim.tapped, "the lock ends with its holder"


def test_w2g4_the_tap_picker_narrows_to_the_seat_the_trigger_froze(set_pool):
    """Somnophore's target is "target creature **that player** controls", and
    the seat is one only the firing event knows (CR 603.10). Refused rather than
    supplied, the picker offered nothing and CR 603.3c took the whole ability off
    the stack — which is what it did until this seat was handed down."""
    pool = set_pool("USG")
    game, mine, theirs = _g4b_board(
        mine=[pool["Somnophore"], _g4b_creature("G4B Mine")],
        theirs=[_g4b_creature("G4B Theirs")],
    )
    program = compile_card_oracle(pool["Somnophore"])
    spec = {"kind": "creature", "that_player_only": True, "that_player_index": 1}
    offered = game._enumerate_targets(
        0, pool["Somnophore"], spec, for_cast=False,
        ability_instruction=program.triggered_abilities[0].instruction,
        source_permanent=mine.battlefield[0],
        ability_source=mine.battlefield[0],
        triggered=True,
    )
    assert [entry["name"] for entry in offered] == ["G4B Theirs"]


# --- W2G1: the damage path — dealing it, preventing it, replacing it ---
from engine import Game, PlayerState  # noqa: E402
from engine.damage_events import deal_damage as _g1_deal  # noqa: E402
from engine.models import Permanent as _G1Permanent  # noqa: E402

from tests.helpers import resolve_stack as _g1_resolve  # noqa: E402


def _g1_board(pool, mine=(), theirs=(), life=(20, 20)):
    """Two seats, control synced, nothing enforced. Ends on the sync so no
    other block's helper tail matches this one."""
    game = Game(players=[
        PlayerState(name="G1A", battlefield=list(mine), life=life[0],
                    library=[pool["Remote Isle"]] * 8),
        PlayerState(name="G1B", battlefield=list(theirs), life=life[1],
                    library=[pool["Remote Isle"]] * 8),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game._sync_control()
    return game


def test_w2g1_fog_bank_shields_both_ends_of_combat_damage(set_pool):
    """"Prevent all combat damage that would be dealt to and dealt by this
    creature."

    The static form of the two-way shield ten other cards *resolve* onto a
    creature, printed about the creature itself. Both directions and the printed
    word "combat" are separate claims and each is tested: a shield answering only
    one end would make Fog Bank either unkillable or harmless rather than both,
    and one that ignored "combat" would stop a burn spell the card says nothing
    about.
    """
    pool = set_pool("USG")
    fog = _G1Permanent(card=pool["Fog Bank"])
    other = _G1Permanent(card=pool["Coral Merfolk"])
    game = _g1_board(pool, mine=[fog], theirs=[other])

    to_it = _g1_deal(game, {"recipient": fog, "amount": 2, "source": other, "combat": True})
    by_it = _g1_deal(game, {"recipient": other, "amount": 2, "source": fog, "combat": True})
    burn = _g1_deal(game, {"recipient": fog, "amount": 2, "source": other, "combat": False})

    assert to_it.dealt == 0, "combat damage dealt to it is prevented"
    assert by_it.dealt == 0, "combat damage dealt by it is prevented"
    assert burn.dealt == 2, "the printed word is 'combat'; a burn spell still lands"


def test_w2g1_flesh_reaver_bites_its_own_controller(set_pool):
    """"Whenever this creature deals damage to a creature or opponent, this
    creature deals that much damage to you."

    The recipient union printed the other way round from Mangara's Equity, with
    the article on the noun and the seat word bare. Both halves are tested, and
    so is the seat the union does **not** name: damage to the Reaver's own
    controller is neither a creature nor one of their opponents, so it must not
    fire — a trigger that did would double every point.
    """
    pool = set_pool("USG")
    reaver = _G1Permanent(card=pool["Flesh Reaver"])
    game = _g1_board(pool, mine=[reaver])
    _g1_deal(game, {"recipient": game.players[1], "amount": 4, "source": reaver})
    _g1_resolve(game)
    assert game.players[0].life == 16, "4 to an opponent is 4 back to you"

    reaver = _G1Permanent(card=pool["Flesh Reaver"])
    victim = _G1Permanent(card=pool["Coral Merfolk"])
    game = _g1_board(pool, mine=[reaver], theirs=[victim])
    _g1_deal(game, {"recipient": victim, "amount": 2, "source": reaver})
    _g1_resolve(game)
    assert game.players[0].life == 18, "a creature is the other half of the union"

    reaver = _G1Permanent(card=pool["Flesh Reaver"])
    game = _g1_board(pool, mine=[reaver])
    _g1_deal(game, {"recipient": game.players[0], "amount": 3, "source": reaver})
    _g1_resolve(game)
    assert game.players[0].life == 20, (
        "its own controller is neither a creature nor one of their opponents"
    )


def test_w2g1_electryte_bites_the_blockers_with_its_power(set_pool):
    """"Whenever this creature deals combat damage to defending player, it deals
    damage equal to its power to each blocking creature."

    Three claims, three assertions. The amount is a *read* of the dealer at
    resolution (CR 613's computed power); the set is the printed noun phrase and
    not every creature; and the condition names combat damage, so a ping from the
    same creature to the same seat fires nothing.
    """
    pool = set_pool("USG")
    electryte = _G1Permanent(card=pool["Electryte"])
    blocker = _G1Permanent(card=pool["Blanchwood Treefolk"])
    idle = _G1Permanent(card=pool["Blanchwood Treefolk"])
    game = _g1_board(pool, mine=[electryte], theirs=[blocker, idle])
    game.combat_defending_player_index = 1
    blocker.blocking_attacker_index = 0

    _g1_deal(game, {"recipient": game.players[1], "amount": 3,
                    "source": electryte, "combat": True})
    _g1_resolve(game)

    assert electryte.effective_power == 3
    assert blocker.damage_marked == 3, "the amount is the dealer's power"
    assert idle.damage_marked == 0, "the phrase says 'blocking', and it is tested"

    quiet = _G1Permanent(card=pool["Electryte"])
    bystander = _G1Permanent(card=pool["Blanchwood Treefolk"])
    game = _g1_board(pool, mine=[quiet], theirs=[bystander])
    game.combat_defending_player_index = 1
    bystander.blocking_attacker_index = 0
    _g1_deal(game, {"recipient": game.players[1], "amount": 3,
                    "source": quiet, "combat": False})
    _g1_resolve(game)
    assert bystander.damage_marked == 0, "the condition says combat damage"


def test_w2g1_retromancer_burns_whoever_pointed_at_it(set_pool):
    """"Whenever this creature becomes the target of a spell or ability, this
    creature deals 3 damage to that spell or ability's controller."

    The referent is the seat that announced the targeting object (CR 109.5),
    frozen by the fire site — not the Retromancer's controller and not whoever
    happens to be resolving. Heat Ray still resolves, which is what makes the
    seat readable at all: by then the spell has left the stack (CR 603.10) and
    only the frozen record answers.
    """
    pool = set_pool("USG")
    retro = _G1Permanent(card=pool["Retromancer"])
    game = _g1_board(pool, mine=[retro])
    game.players[1].hand.append(pool["Heat Ray"])

    assert game.cast_from_hand(
        1, "Heat Ray", target_permanent_ids=[retro.permanent_id], x_value=1
    ).supported
    _g1_resolve(game)

    assert game.players[1].life == 17, "the spell's controller takes the 3"
    assert game.players[0].life == 20, "and the Retromancer's does not"


# --- W2G5: the activation-cost cluster (Barrin, Faith Healer) ---
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _g5_slot(game, seat, permanent):
    """*permanent*'s slot in *seat*'s battlefield, for ``cost_permanent_index``.

    The wire's own address, which is what that parameter takes; located by
    identity so two copies of one card cannot answer for each other.
    """
    for index, found in enumerate(game.controlled_by(seat)):
        if found is permanent:
            return index
    raise AssertionError("permanent is not on that battlefield")


def _g5_cost_board(set_pool, *names, seat=0):
    """A game with *names* on *seat*'s battlefield, none summoning sick."""
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    pool = set_pool("USG")
    made = []
    for name in names:
        perm = Permanent(card=pool[name])
        game._put_permanent_onto_battlefield(seat, perm, None)
        perm.metadata["summoning_sickness_turn"] = -99
        made.append(perm)
    return game, made


def test_barrin_eats_a_land_to_bounce_a_creature(set_pool, catalog_by_name):
    """"{2}, Sacrifice a permanent: Return target creature to its owner's hand."

    The cost's noun phrase is the widest one printed — "a permanent" — and the
    census reason said "no cost path charges a narrowed sacrifice". The charger
    could always collect it; what refused was ``cost_object_is_named``, which
    asked that the reduced filter carry *something* so an unnamed cost could
    not eat a land. Here a land is exactly what the card says may pay, so the
    land is the assertion: it goes to the graveyard and the bounce happens.
    """
    game, (barrin,) = _g5_cost_board(set_pool, "Barrin, Master Wizard")
    forest = Permanent(card=catalog_by_name["Forest"])
    game._put_permanent_onto_battlefield(0, forest, None)
    victim = Permanent(card=catalog_by_name["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, victim, None)

    game.activate_permanent_ability(
        0, "Barrin, Master Wizard",
        target_player_index=1,
        target_permanent_ids=[victim.permanent_id],
        cost_permanent_index=_g5_slot(game, 0, forest),
    )
    resolve_stack(game)

    assert [c.name for c in game.players[0].graveyard] == ["Forest"]
    assert not any(p is forest for p in game.controlled_by(0))
    assert [c.name for c in game.players[1].hand] == ["Grizzly Bears"]


def test_barrin_pays_with_himself_when_he_is_the_only_permanent(set_pool, catalog_by_name):
    """"A permanent" includes the source, so a lone Barrin can still activate.

    The counterpart of a refusal test, and the more useful one here: the shape
    that would fail is a charger reading "a permanent" as "another permanent",
    which is the printed cost with a word added.
    """
    game, (barrin,) = _g5_cost_board(set_pool, "Barrin, Master Wizard")
    victim = Permanent(card=catalog_by_name["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, victim, None)

    game.activate_permanent_ability(
        0, "Barrin, Master Wizard",
        target_player_index=1,
        target_permanent_ids=[victim.permanent_id],
    )
    resolve_stack(game)

    assert [c.name for c in game.players[0].graveyard] == ["Barrin, Master Wizard"]
    assert [c.name for c in game.players[1].hand] == ["Grizzly Bears"]


def test_faith_healer_gains_the_sacrificed_enchantments_mana_value(set_pool):
    """"Sacrifice an enchantment: You gain life equal to the sacrificed
    enchantment's mana value."

    The number is a characteristic of what the *cost* ate (CR 601.2h), read
    back as last-known information (CR 608.2h). Two different enchantments are
    sacrificed in one game, because a reading that resolved to zero or to a
    constant would look right at whichever card the test happened to pick.
    """
    game, (healer, lurking, greater) = _g5_cost_board(
        set_pool, "Faith Healer", "Lurking Evil", "Greater Good"
    )
    game.players[0].life = 20

    game.activate_permanent_ability(
        0, "Faith Healer",
        cost_permanent_index=_g5_slot(game, 0, lurking),
    )
    resolve_stack(game)
    assert game.players[0].life == 23, "Lurking Evil is {B}{B}{B}"

    game.activate_permanent_ability(
        0, "Faith Healer",
        cost_permanent_index=_g5_slot(game, 0, greater),
    )
    resolve_stack(game)
    assert game.players[0].life == 27, "Greater Good is {2}{G}{G}"


def test_diamond_valleys_toughness_reading_survives_the_shared_channel(catalog_by_name):
    """One of the two cards the life family's private cost-sacrifice key was
    written for.

    Its lowering now emits the ``x_from_count`` channel every other family
    reads that record on, so this is the differential the change owes: the
    toughness is still what is gained, and it is the *effective* toughness the
    permanent last had rather than the printed one.
    """
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    valley = Permanent(card=catalog_by_name["Diamond Valley"])
    game._put_permanent_onto_battlefield(0, valley, None)
    valley.metadata["summoning_sickness_turn"] = -99
    bears = Permanent(card=catalog_by_name["Grizzly Bears"])
    game._put_permanent_onto_battlefield(0, bears, None)
    alice.life = 20

    game.activate_permanent_ability(
        0, "Diamond Valley", cost_permanent_index=_g5_slot(game, 0, bears),
    )
    resolve_stack(game)

    assert alice.life == 22, "Grizzly Bears is 2/2"


# --- W2G5: Priest of Titania — a count over every battlefield ---
from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _g5m_elf_board(set_pool, mine, theirs):
    """A Priest of Titania on seat 0, plus *mine* / *theirs* extra Elves."""
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    priest = Permanent(card=set_pool("USG")["Priest of Titania"])
    game._put_permanent_onto_battlefield(0, priest, None)
    priest.metadata["summoning_sickness_turn"] = -99
    for seat, count in ((0, mine), (1, theirs)):
        for _ in range(count):
            game._put_permanent_onto_battlefield(
                seat, Permanent(card=set_pool("USG")["Priest of Titania"]), None
            )
    return game


def test_priest_of_titania_counts_elves_on_every_battlefield(set_pool):
    """"{T}: Add {G} for each Elf on the battlefield."

    CR 403.1 makes the battlefield one zone shared by every player, so the
    phrase scopes to nobody — the whole of it. The lowering refused with "the
    mana multiplier counts the producer's own board", which is the reading that
    would have made this "for each Elf you control": a Priest opposite two
    opposing Elves would have added one mana where the card adds three.

    Both sides are populated unevenly, because a count that read only one
    battlefield would still look right on a symmetric board.
    """
    game = _g5m_elf_board(set_pool, mine=1, theirs=2)

    game.activate_permanent_ability(0, "Priest of Titania")
    resolve_stack(game)

    assert game.players[0].mana_pool.get("G") == 4, "2 mine + 2 theirs"


def test_priest_of_titania_counts_only_elves(set_pool, catalog_by_name):
    """The narrowing survives the widened scope: an opponent's non-Elf is on
    the same battlefield and is not counted.
    """
    game = _g5m_elf_board(set_pool, mine=0, theirs=0)
    game._put_permanent_onto_battlefield(
        1, Permanent(card=catalog_by_name["Grizzly Bears"]), None
    )

    game.activate_permanent_ability(0, "Priest of Titania")
    resolve_stack(game)

    assert game.players[0].mana_pool.get("G") == 1, "the Priest itself"


# --- W2G5: Wild Dogs — the life leader takes the creature ---
def _g5d_run(set_pool, life_a, life_b):
    """One upkeep with Wild Dogs on seat 0 and the given life totals."""
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    dogs = Permanent(card=set_pool("USG")["Wild Dogs"])
    game._put_permanent_onto_battlefield(0, dogs, None)
    alice.life, bob.life = life_a, life_b
    game.active_player_index = 0
    game.resolve_upkeep(0)
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    return game.controller_index_of(dogs)


def test_wild_dogs_walk_to_whoever_is_ahead(set_pool):
    """"At the beginning of your upkeep, if a player has more life than each
    other player, the player with the most life gains control of this
    creature."

    The trigger is on **your** upkeep and the seat it names is nobody the
    trigger froze — it is read off the life totals — so a reading that took the
    frozen seat would leave the Dogs where they are for ever.
    """
    assert _g5d_run(set_pool, 20, 25) == 1, "the opponent is ahead"
    assert _g5d_run(set_pool, 25, 20) == 0, "and stay put when you are"


def test_wild_dogs_stay_put_on_a_tie(set_pool):
    """A tie names nobody: "more life than each other player" is strict and
    CR 104.3b's superlative has no answer when two seats are level. The gate
    and the hand-over ask the *same* reader, so they cannot disagree about it.
    """
    assert _g5d_run(set_pool, 20, 20) == 0


def test_ghazban_ogre_keeps_working_with_its_hook_retired(catalog_by_name):
    """The production took a name-keyed hook over.

    Ghazban Ogre printed Wild Dogs' sentence exactly and was implemented as a
    ``CARD_LINE_INSTRUCTIONS`` entry plus an upkeep-registry handler; both are
    gone. This is the card the retirement owes a behaviour check — the guard in
    ``tests/engine/test_card_lines.py`` only proves the entry was dead.
    """
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    ogre = Permanent(card=catalog_by_name["Ghazb\u00e1n Ogre"])
    game._put_permanent_onto_battlefield(0, ogre, None)
    alice.life, bob.life = 18, 22

    game.active_player_index = 0
    game.resolve_upkeep(0)
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)

    assert game.controller_index_of(ogre) == 1


# --- W2G2: Serra Avatar — a life-total body and a graveyard trigger ---
import pytest

from engine import Game, PlayerState
from engine.control import change_control
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _g2c_game(set_pool):
    """Two seats, no mana costs. W2G2's own creature-block helper."""
    alice, bob = PlayerState(name="G2C-A"), PlayerState(name="G2C-B")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    return game, alice, bob


def test_w2g2_serra_avatar_is_the_size_of_its_controller_s_life(set_pool):
    """"Serra Avatar's power and toughness are each equal to your life total."

    CR 604.3 recomputes continuously, so the assertion is made twice at two
    different life totals — a P/T frozen at the entry number would pass the
    first read and only the first.
    """
    game, alice, _ = _g2c_game(set_pool)
    alice.life = 20
    avatar = Permanent(card=set_pool("USG")["Serra Avatar"])
    game._put_permanent_onto_battlefield(0, avatar, None)

    assert (avatar.effective_power, avatar.effective_toughness) == (20, 20)

    alice.life = 7
    game._refresh_dynamic_creatures()

    assert (avatar.effective_power, avatar.effective_toughness) == (7, 7)


def test_w2g2_serra_avatar_reads_the_controller_s_life_not_the_owner_s(set_pool):
    """The same sentence under a control change. "Your" is CR 109.5's ability
    controller, and the two seats are given different life totals so a read of
    the wrong one is a different number rather than the same one twice.
    """
    game, alice, bob = _g2c_game(set_pool)
    alice.life, bob.life = 20, 4
    avatar = Permanent(card=set_pool("USG")["Serra Avatar"])
    game._put_permanent_onto_battlefield(0, avatar, None)
    change_control(avatar, 1, source="test")
    game._sync_control()
    game._refresh_dynamic_creatures()

    assert (avatar.effective_power, avatar.effective_toughness) == (4, 4)


def test_w2g2_serra_avatar_shuffles_itself_back_after_dying(set_pool):
    """"When Serra Avatar is put into a graveyard from anywhere, shuffle it
    into its owner's library."
    """
    game, alice, _ = _g2c_game(set_pool)
    alice.library = []
    avatar = Permanent(card=set_pool("USG")["Serra Avatar"])
    game._put_permanent_onto_battlefield(0, avatar, None)

    # The order ``_destroy_swept_permanents`` uses: the card is filed while the
    # permanent is still on the battlefield — which is what announces the death
    # triggers — and the object leaves afterwards.
    game._permanent_to_graveyard(alice, avatar)
    game.remove_from_battlefield(avatar)
    resolve_stack(game)

    assert [c.name for c in alice.library] == ["Serra Avatar"]
    assert not alice.graveyard


def test_w2g2_serra_avatar_shuffles_back_from_a_mill_too(set_pool):
    """The half "from anywhere" buys and a death reading would lose: a milled
    Avatar never touched a battlefield, so CR 700.4 says it did not die — and
    the trigger still fires.
    """
    game, alice, _ = _g2c_game(set_pool)
    avatar_card = set_pool("USG")["Serra Avatar"]
    filler = set_pool("USG")["Sanctum Custodian"]
    alice.library = [avatar_card, filler, filler]

    game.put_card_into_graveyard(alice, alice.library.pop(0), from_zone="library")
    resolve_stack(game)

    assert [c.name for c in alice.library].count("Serra Avatar") == 1
    assert not alice.graveyard


# --- W3G2: Gilded Drake, an exchange whose first side is the source itself ---
#
# Four printed parts and every one of them given a game: the exchange, the
# "up to one" that may name nobody, the sacrifice that fires on the exchange
# *not* having happened, and CR 608.2b's printed exception. "It reports
# supported" is what the hollow-lines and parse-coverage instruments exist to
# catch.
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _g2d_duel(set_pool, theirs=(), mine=()):
    """A two-seat game with the Drake in hand and *theirs* on seat 1's board.

    Returns ``(game, alice, bob)`` — never a bare game, so no mechanical union
    can splice a different group's helper body onto this signature.
    """
    pool = set_pool("USG")
    g2d_alice = PlayerState(name="G2D-A", hand=[pool["Gilded Drake"]])
    g2d_bob = PlayerState(name="G2D-B")
    g2d_game = Game(players=[g2d_alice, g2d_bob])
    g2d_game.enforce_mana_costs = False
    for card in mine:
        g2d_game._put_permanent_onto_battlefield(0, Permanent(card=card), None)
    for card in theirs:
        g2d_game._put_permanent_onto_battlefield(1, Permanent(card=card), None)
    return g2d_game, g2d_alice, g2d_bob


def test_w3g2_gilded_drake_exchanges_itself_for_the_targeted_creature(set_pool, catalog_by_name):
    """CR 701.12b, with the source on the first side.

    The whole point of the card: what the opponent gets is the Drake, and what
    its controller gets is the creature they named.
    """
    bears = catalog_by_name["Grizzly Bears"]
    game, _alice, bob = _g2d_duel(set_pool, theirs=[bears])
    victim = next(iter(game.controlled_by(1)))

    game.cast_from_hand(
        0, "Gilded Drake",
        target_player_index=1, target_permanent_ids=[victim.permanent_id],
    )
    resolve_stack(game)

    assert sorted(p.card.name for p in game.controlled_by(0)) == ["Grizzly Bears"]
    assert sorted(p.card.name for p in game.controlled_by(1)) == ["Gilded Drake"]
    assert not bob.graveyard


def test_w3g2_gilded_drake_is_sacrificed_when_no_exchange_happens(set_pool):
    """"If you don't or can't make an exchange, sacrifice this creature."

    The printed "up to one" lets the trigger name nobody (CR 601.2c), and an
    opponent with no creature is exactly that board. The condition is the
    *absence* of the exchange record, so this is the sentence firing rather
    than the exchange half-happening.
    """
    game, alice, _bob = _g2d_duel(set_pool)

    game.cast_from_hand(0, "Gilded Drake")
    resolve_stack(game)

    assert not list(game.controlled_by(0))
    assert [c.name for c in alice.graveyard] == ["Gilded Drake"]


def test_w3g2_gilded_drake_still_resolves_when_its_target_has_left(set_pool, catalog_by_name):
    """"This ability still resolves if its target becomes illegal."

    CR 608.2b would take the object off the stack unresolved when every target
    is illegal, and this sentence says not to. Reproduced by handing the
    trigger the id of a creature that has left: the exchange cannot happen and
    the *sacrifice* must, which is the whole reason the card prints the
    sentence — a fizzle would leave its controller a 3/3 flier for {1}{U}.
    """
    from engine.game_types import OracleExecutionContext

    bears = catalog_by_name["Grizzly Bears"]
    game, alice, _bob = _g2d_duel(set_pool, theirs=[bears])
    departed = next(iter(game.controlled_by(1)))
    game.remove_from_battlefield(departed)

    drake = Permanent(card=set_pool("USG")["Gilded Drake"])
    game._put_permanent_onto_battlefield(0, drake, None)
    program = compile_card_oracle(drake.card)
    trigger = next(t for t in program.triggered_abilities)
    game._execute_oracle_instruction(
        trigger.instruction,
        OracleExecutionContext(
            caster=alice, target=game.players[1], card=drake.card,
            source_permanent=drake, target_permanent_id=departed.permanent_id,
        ),
    )

    assert not list(game.controlled_by(0)), "the ability resolved rather than fizzling"
    assert [c.name for c in alice.graveyard] == ["Gilded Drake"]


def test_w3g2_gilded_drake_offers_only_an_opponents_creature(set_pool):
    """CR 601.2c's announcement, off the compiled program.

    "target creature **an opponent controls**" is a seat question, and the
    picker is what has to ask it — a spec that offered every creature would let
    the caster name their own and exchange a permanent with themselves.
    """
    from engine.targeting import derive_cast_spec

    card = set_pool("USG")["Gilded Drake"]
    spec = derive_cast_spec(card, compile_card_oracle(card))

    assert spec == {"kind": "creature", "opponent_only": True}


@pytest.mark.parametrize(
    "sentence,expected",
    [
        ("This ability still resolves if its target becomes illegal", True),
        ("This spell still resolves if its target becomes illegal", True),
        ("This ability still resolves", False),
        ("This ability still resolves if its controller becomes illegal", False),
    ],
)
def test_w3g2_the_resolution_override_is_matched_whole(sentence, expected):
    """A substring match is how a whitelist comes to claim text it does not
    implement, so the table anchors the sentence — the rule
    `special_actions.special_action_line` states one module over."""
    from engine.resolution_overrides import resolution_override_sentence

    assert (resolution_override_sentence(sentence) is not None) is expected


def test_w3g2_the_restated_rider_refuses_when_it_names_another_action(set_pool):
    """The refusal, which is the half a positive test cannot show.

    "If you don't or can't **make an exchange**" is folded onto the step in
    front of it only when the restatement names *that* step. A sentence naming
    something else must put its words back and let the line refuse as
    unconsumed text, rather than folding a branch onto an action it is not
    about — which would sacrifice the creature on the wrong condition and
    compile clean.
    """
    from engine.grammar import parse_line
    from engine.grammar.errors import GrammarError

    with pytest.raises(GrammarError):
        parse_line(
            "exchange control of this creature and up to one target creature "
            "an opponent controls. If you don't or can't sacrifice a Forest, "
            "sacrifice this creature."
        )


def test_w3g2_an_exchange_with_neither_side_chosen_still_refuses(set_pool):
    """The lowering admits the source on the **first** side and nothing wider.

    An exchange naming no chosen permanent at all has nothing for the picker to
    offer and nothing for the handler to re-check at resolution (CR 608.2b), so
    it must go on refusing rather than resolving against whatever the context
    happened to carry.
    """
    from engine.grammar import parse_line
    from engine.grammar.errors import LoweringError
    from engine.grammar.lower import lower_ability

    node = parse_line("exchange control of this creature and this creature")
    with pytest.raises(LoweringError, match="chosen permanent"):
        lower_ability(node)
