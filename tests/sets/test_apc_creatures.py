"""Apocalypse creatures.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("APC")` / `set_cards("APC")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ============================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ========================================================


# ==== W1G2 ============================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

import pytest as _w1g3_pytest

from engine import Game as _w1g3_Game, PlayerState as _w1g3_Player
from engine.game_types import CardDefinition as _w1g3_CardDefinition
from engine.models import Permanent as _w1g3_Permanent
from tests.helpers import resolve_stack as _w1g3_resolve_stack


def _w1g3_card(name, type_line, power="2", toughness="2"):
    """A card that is nothing but a printed type line, which is the whole of
    what a recruiter reads off the cards it turns over."""
    return _w1g3_CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": power, "toughness": toughness},
    )  # W1G3 creatures: a typed card


def _w1g3_duel(hand=(), library=(), *, mine=(), theirs=(), interactive=(), mana=False):
    """Seat 0 with *hand* over *library*; both boards placed and unsick."""
    board0 = [_w1g3_Permanent(card=card) for card in mine]
    board1 = [_w1g3_Permanent(card=card) for card in theirs]
    for permanent in board0 + board1:
        permanent.metadata["summoning_sickness_turn"] = -99
    game = _w1g3_Game(players=[
        _w1g3_Player(name="P0", hand=list(hand), library=list(library), battlefield=board0),
        _w1g3_Player(name="P1", battlefield=board1),
    ])
    game.enforce_mana_costs = bool(mana)
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    return game, board0, board1  # W1G3 creatures: the duel


def _w1g3_names(cards):
    return [card.name for card in cards]  # W1G3 creatures: names


_W1G3_RECRUITERS = (
    ("Enlistment Officer", "Soldier"),
    ("Goblin Ringleader", "Goblin"),
    ("Grave Defiler", "Zombie"),
    ("Kavu Howler", "Kavu"),
    ("Sylvan Messenger", "Elf"),
    ("Tidal Courier", "Merfolk"),
)


@_w1g3_pytest.mark.parametrize(("recruiter", "tribe"), _W1G3_RECRUITERS)
def test_w1g3_a_recruiter_takes_its_tribe_from_the_top_four_and_bottoms_the_rest(
    set_pool, recruiter, tribe,
):
    """"When this creature enters, reveal the top four cards of your library.
    Put all <Tribe> cards revealed this way into your hand and the rest on the
    bottom of your library in any order."

    One sentence on six cards with the subtype changed. Played through the
    stack, because the trigger is an object on it (CR 603.3): the creature is
    on the battlefield and nothing has been turned over until the trigger
    resolves. A second subtype on the card (a Human Soldier is a Soldier) and
    a second card type (an artifact creature) change nothing; the fifth card
    is of the tribe and is never seen.
    """
    first = _w1g3_card(f"{tribe} One", f"Creature — {tribe}")
    land = _w1g3_card("A Land", "Land")
    stranger = _w1g3_card("An Ox", "Creature — Ox")
    second = _w1g3_card(f"{tribe} Two", f"Artifact Creature — Human {tribe}")
    fifth = _w1g3_card(f"{tribe} Unseen", f"Creature — {tribe}")
    game, _, _ = _w1g3_duel(
        [set_pool("APC")[recruiter]], [first, land, stranger, second, fifth],
    )
    me = game.players[0]

    assert game.queue_from_hand(0, recruiter).supported
    assert game.resolve_top_of_stack()

    assert [p.card.name for p in game.controlled_by(0)] == [recruiter]
    assert [item.card.name for item in game.stack] == [recruiter], game.log
    assert me.hand == [] and len(me.library) == 5 and not game.reveal_events

    _w1g3_resolve_stack(game)

    assert _w1g3_names(me.hand) == [f"{tribe} One", f"{tribe} Two"], game.log
    assert _w1g3_names(me.library) == [f"{tribe} Unseen", "A Land", "An Ox"]
    assert game.reveal_events[-1]["seat"] == 0
    assert game.reveal_events[-1]["cards"] == [
        f"{tribe} One", "A Land", "An Ox", f"{tribe} Two",
    ]
    assert f"P0 revealed {tribe} One, A Land, An Ox, {tribe} Two" in game.log
    assert (
        f"P0 put {tribe} One, {tribe} Two into their hand and 2 card(s) on the "
        "bottom of their library"
    ) in game.log
    assert game.stack == [] and game.pending_choices == []


def test_w1g3_goblin_ringleader_reads_the_type_line_and_not_the_name(set_pool):
    """A "Goblin card" is a card with the subtype (CR 205.3): a card that only
    has the word in its name stays, and with nothing of the tribe in the four
    the whole pile goes under the library in the order it was revealed — the
    card that was fifth is now the next draw."""
    library = [
        _w1g3_card("Goblin Shrine", "Enchantment"),
        _w1g3_card("Goblin Mountaineer's Wall", "Creature — Wall"),
        _w1g3_card("A Land", "Land"),
        _w1g3_card("An Ox", "Creature — Ox"),
        _w1g3_card("Fifth", "Creature — Goblin"),
    ]
    game, _, _ = _w1g3_duel([set_pool("APC")["Goblin Ringleader"]], library)
    me = game.players[0]

    assert game.cast_from_hand(0, "Goblin Ringleader").supported

    assert me.hand == []
    assert _w1g3_names(me.library) == [
        "Fifth", "Goblin Shrine", "Goblin Mountaineer's Wall", "A Land", "An Ox",
    ]
    assert "P0 put no card into their hand and 4 card(s) on the bottom of their library" in game.log


def test_w1g3_a_recruiter_finds_the_real_cards_of_its_tribe(set_pool):
    """The same trigger over printed cards rather than built ones: a Kavu
    Howler turns up another Howler (Creature — Kavu) beside three cards that
    are not Kavu, and takes it."""
    apc = set_pool("APC")
    game, _, _ = _w1g3_duel(
        [apc["Kavu Howler"]],
        [apc["Goblin Ringleader"], apc["Kavu Howler"], apc["Helionaut"], apc["Index"]],
    )
    me = game.players[0]

    assert game.cast_from_hand(0, "Kavu Howler").supported

    assert _w1g3_names(me.hand) == ["Kavu Howler"]
    assert _w1g3_names(me.library) == ["Goblin Ringleader", "Helionaut", "Index"]


def test_w1g3_a_recruiter_over_a_short_library_reveals_what_is_there(set_pool):
    """CR 701.20a shows the cards the library holds. Two cards is an ordinary
    board, and an empty library is one too: nothing is revealed and nobody has
    drawn from it, so nobody loses (CR 704.5b is about a draw)."""
    game, _, _ = _w1g3_duel(
        [set_pool("APC")["Sylvan Messenger"]],
        [_w1g3_card("An Elf", "Creature — Elf Druid"), _w1g3_card("A Land", "Land")],
    )
    me = game.players[0]
    assert game.cast_from_hand(0, "Sylvan Messenger").supported
    assert _w1g3_names(me.hand) == ["An Elf"]
    assert _w1g3_names(me.library) == ["A Land"]

    game, _, _ = _w1g3_duel([set_pool("APC")["Sylvan Messenger"]], [])
    me = game.players[0]
    assert game.cast_from_hand(0, "Sylvan Messenger").supported
    assert me.hand == [] and me.library == [] and not game.reveal_events
    assert "P0 has no cards to reveal" in game.log
    assert not me.lost


def test_w1g3_the_order_of_the_rest_is_asked_of_the_player_who_owns_them(set_pool):
    """"…and the rest on the bottom of your library **in any order**."

    CR 401.4: cards put in one position in a library at one time are arranged
    by their owner. An interactive seat is asked — the trigger stays on the
    stack and the game waits (CR 608.2) — and is shown exactly the cards that
    went down. A wrong permutation and another seat's answer are refused;
    the answer reorders those cards and nothing above them."""
    library = [
        _w1g3_card("First Down", "Land"),
        _w1g3_card("A Merfolk", "Creature — Merfolk"),
        _w1g3_card("Second Down", "Creature — Ox"),
        _w1g3_card("Third Down", "Enchantment"),
        _w1g3_card("Untouched", "Land"),
    ]
    game, _, _ = _w1g3_duel(
        [set_pool("APC")["Tidal Courier"]], library, interactive={0},
    )
    me = game.players[0]

    assert game.cast_from_hand(0, "Tidal Courier").supported

    assert _w1g3_names(me.hand) == ["A Merfolk"]
    assert [item.card.name for item in game.stack] == ["Tidal Courier"], game.log
    waiting = game.waiting_prompt()
    assert waiting is not None and waiting.kind == "reorder_library"
    assert waiting.player_index == 0 and waiting.data["position"] == "bottom"
    assert _w1g3_names(game.reorder_library_pile(waiting)) == [
        "First Down", "Second Down", "Third Down",
    ]

    assert not game.confirm_reorder_library(0, [0, 1])
    assert not game.confirm_reorder_library(0, [0, 0, 1])
    assert not game.confirm_reorder_library(1, [2, 1, 0])
    assert _w1g3_names(me.library) == [
        "Untouched", "First Down", "Second Down", "Third Down",
    ]

    assert game.confirm_reorder_library(0, [2, 0, 1])
    game._settle()

    assert _w1g3_names(me.library) == [
        "Untouched", "Third Down", "First Down", "Second Down",
    ]
    assert game.stack == [] and game.pending_choices == []
    assert "P0 put 3 cards on the bottom of their library in an order they chose" in game.log


def test_w1g3_a_seat_that_is_not_asked_lays_the_rest_down_as_revealed(set_pool):
    """The default order is the one the cards were turned over in, and a seat
    nobody is asking takes it without a prompt being queued — so a headless
    game and an AI seat never stall on a question about the bottom of a deck.
    One card left over has no order to ask about even of a human."""
    cards = [
        _w1g3_card("Down One", "Land"), _w1g3_card("Down Two", "Land"),
        _w1g3_card("Down Three", "Land"), _w1g3_card("Down Four", "Land"),
    ]
    game, _, _ = _w1g3_duel([set_pool("APC")["Grave Defiler"]], cards)
    assert game.cast_from_hand(0, "Grave Defiler").supported
    assert game.pending_choices == [] and game.stack == []
    assert _w1g3_names(game.players[0].library) == [
        "Down One", "Down Two", "Down Three", "Down Four",
    ]

    one_left = [
        _w1g3_card("Zombie A", "Creature — Zombie"),
        _w1g3_card("Zombie B", "Creature — Zombie"),
        _w1g3_card("Zombie C", "Creature — Zombie"),
        _w1g3_card("Down One", "Land"),
    ]
    game, _, _ = _w1g3_duel(
        [set_pool("APC")["Grave Defiler"]], one_left, interactive={0},
    )
    assert game.cast_from_hand(0, "Grave Defiler").supported
    assert game.pending_choices == [] and game.stack == []
    assert _w1g3_names(game.players[0].hand) == ["Zombie A", "Zombie B", "Zombie C"]
    assert _w1g3_names(game.players[0].library) == ["Down One"]


def test_w1g3_the_recruiters_keep_their_other_printed_lines(set_pool):
    """The reveal is one line of each card. The others still work: Enlistment
    Officer has first strike, Goblin Ringleader haste, Sylvan Messenger
    trample, Grave Defiler regenerates for {1}{B} and Tidal Courier flies for
    {3}{U} until end of turn."""
    apc = set_pool("APC")
    game, mine, _ = _w1g3_duel(mine=[
        apc["Enlistment Officer"], apc["Goblin Ringleader"],
        apc["Sylvan Messenger"], apc["Grave Defiler"], apc["Tidal Courier"],
    ], mana=True)
    officer, ringleader, messenger, defiler, courier = mine
    me = game.players[0]

    assert game._has_keyword(officer, "first strike")
    assert game._has_keyword(ringleader, "haste")
    assert game._has_keyword(messenger, "trample")

    assert not game.activate_permanent_ability(0, "Grave Defiler").supported
    assert defiler.regeneration_shield == 0
    me.mana_pool["B"] = 2
    assert game.activate_permanent_ability(0, "Grave Defiler").supported
    assert defiler.regeneration_shield == 1 and me.mana_pool["B"] == 0

    assert not game._has_keyword(courier, "flying")
    me.mana_pool["U"] = 4
    assert game.activate_permanent_ability(0, "Tidal Courier").supported
    assert game._has_keyword(courier, "flying") and me.mana_pool["U"] == 0


@_w1g3_pytest.mark.slow
def test_w1g3_the_ai_plays_recruiters_through_whole_games():
    """Three recruiters pinned into both decks of four simulated games: they
    are cast, each reveal is followed by its sort, and the sort accounts for
    every card it turned over — what went to the hand plus what went under the
    library is what was revealed. No prompt is left owing: an AI seat is never
    asked for the order of the rest.

    (The pool is a measured set, so other cards' unsupported casts are in the
    report; only the recruiters' lines are read. The floor is well under what
    the seed gives today — nine casts — so another card becoming castable does
    not move it.)"""
    from engine.ai_simulator import run_ai_simulation
    from engine.card_loader import manifest_set_path

    names = ["Goblin Ringleader", "Kavu Howler", "Sylvan Messenger"]
    report = run_ai_simulation(
        [manifest_set_path("APC", include_measured=True)],
        games=4, seed=1337, max_turns=16, required_cards=names,
    )
    assert report.games_completed == 4
    lines = [line.strip() for line in report.log_lines]
    casts = [
        line for line in lines
        if any(f" cast {name} -> resolved" in line for name in names)
    ]
    assert len(casts) >= 4, casts
    sorts = 0
    for position, line in enumerate(lines):
        if " put " not in line or "on the bottom of their library" not in line:
            continue
        reveal = lines[position - 1]
        seat = line.split(" put ")[0]
        assert reveal.startswith(f"{seat} revealed "), (reveal, line)
        # No Apocalypse card (and no basic land) has a comma in its name, so
        # the log's own separator splits the names.
        revealed = reveal.split(" revealed ", 1)[1].split(", ")
        kept_text = line.split(" put ", 1)[1].split(" into their hand and ")[0]
        kept = [] if kept_text == "no card" else kept_text.split(", ")
        bottomed = int(line.split(" into their hand and ")[1].split(" ")[0])
        assert len(kept) + bottomed == len(revealed) <= 4, (reveal, line)
        assert all(name in revealed for name in kept), (reveal, line)
        sorts += 1
    assert sorts >= len(casts) >= 4, (sorts, casts)
    assert [key for key in report.refused_casts if key.split(":")[0] in names] == []
    assert [
        i.message for i in report.issues if any(name in i.message for name in names)
    ] == []
    w1g3_recruiters_left_nothing_owing = not report.steps_left_owing
    assert w1g3_recruiters_left_nothing_owing, report.steps_left_owing


# --- The drive list: compiled on arrival, played here ------------------------


@_w1g3_pytest.mark.parametrize(("name", "drawn", "life"), [
    ("Jungle Barrier", 1, 20),
    ("Phyrexian Rager", 1, 19),
    ("Phyrexian Gargantua", 2, 18),
])
def test_w1g3_an_entry_draw_is_a_stack_object_and_then_draws(set_pool, name, drawn, life):
    """"When this creature enters, draw a card." / "…you draw a card and you
    lose 1 life." / "…you draw two cards and you lose 2 life."

    The creature is on the battlefield with its trigger above it before a
    card moves (CR 603.3); resolving it draws off the top and takes the life
    in the same resolution."""
    library = [_w1g3_card(f"Card {n}", "Land") for n in range(1, 5)]
    game, _, _ = _w1g3_duel([set_pool("APC")[name]], library)
    me = game.players[0]

    assert game.queue_from_hand(0, name).supported
    assert game.resolve_top_of_stack()
    assert [p.card.name for p in game.controlled_by(0)] == [name]
    assert [item.card.name for item in game.stack] == [name]
    assert me.hand == [] and me.life == 20

    _w1g3_resolve_stack(game)

    assert _w1g3_names(me.hand) == [f"Card {n}" for n in range(1, drawn + 1)]
    assert len(me.library) == 4 - drawn
    assert me.life == life, game.log
    assert game.players[1].life == 20 and game.players[1].hand == []


def test_w1g3_phyrexian_gargantua_over_one_card_draws_it_and_loses_the_game(set_pool):
    """Two draws off a one-card library: the card is drawn, the life is lost,
    and the second draw is the one from an empty library that CR 704.5b
    answers the next time state-based actions are checked."""
    game, _, _ = _w1g3_duel(
        [set_pool("APC")["Phyrexian Gargantua"]], [_w1g3_card("Last Card", "Land")],
    )
    me = game.players[0]

    assert game.cast_from_hand(0, "Phyrexian Gargantua").supported

    assert _w1g3_names(me.hand) == ["Last Card"] and me.life == 18
    assert me.lost
    assert "P0 lost the game (704.5b: drew from empty library)" in game.log


def test_w1g3_jungle_barrier_is_a_wall_that_cannot_attack(set_pool):
    """"Defender (This creature can't attack.)" A 2/6 that the declare
    attackers step refuses, with the turn actually in that step."""
    game, mine, _ = _w1g3_duel(mine=[set_pool("APC")["Jungle Barrier"]])
    barrier, = mine
    game.players[0].library = [_w1g3_card("Filler", "Land")] * 5
    game.players[1].library = [_w1g3_card("Filler", "Land")] * 5
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers", game.current_step

    assert (barrier.effective_power, barrier.effective_toughness) == (2, 6)
    assert game._has_keyword(barrier, "defender")
    assert not game.can_attack(barrier, 1)
    declared = game.declare_attackers(0, [0])
    assert not declared[0], declared
    assert not barrier.tapped


def test_w1g3_coastal_drake_returns_a_kavu_and_only_a_kavu(set_pool):
    """"{1}{U}, {T}: Return target Kavu to its owner's hand."

    The picker offers the Kavu on both boards and nothing else; a creature
    that is not one is refused before anything is paid; the Kavu named goes to
    its **owner's** hand and the Drake is tapped for it."""
    apc = set_pool("APC")
    game, mine, theirs = _w1g3_duel(
        mine=[apc["Coastal Drake"], apc["Kavu Howler"]],
        theirs=[apc["Kavu Howler"], apc["Helionaut"]],
        mana=True,
    )
    drake, my_kavu = mine
    their_kavu, helionaut = theirs
    me = game.players[0]
    me.mana_pool["U"] = 4

    assert game._has_keyword(drake, "flying")
    spec = game.activation_target_spec(0, 0, 0)
    assert spec["requires_target"]
    assert sorted((t["seat"], t["name"]) for t in spec["valid_targets"]) == [
        (0, "Kavu Howler"), (1, "Kavu Howler"),
    ]

    refused = game.activate_permanent_ability(
        0, "Coastal Drake", target_permanent_ids=[helionaut.permanent_id],
    )
    assert not refused.supported and not drake.tapped and me.mana_pool["U"] == 4

    bounced = game.activate_permanent_ability(
        0, "Coastal Drake", target_permanent_ids=[their_kavu.permanent_id],
    )
    assert bounced.supported, bounced.details
    assert drake.tapped and me.mana_pool["U"] == 2
    assert _w1g3_names(game.players[1].hand) == ["Kavu Howler"]
    assert [p.card.name for p in game.controlled_by(1)] == ["Helionaut"]
    assert game.is_on_battlefield(my_kavu) and me.hand == []

    again = game.activate_permanent_ability(
        0, "Coastal Drake", target_permanent_ids=[my_kavu.permanent_id],
    )
    assert not again.supported and game.is_on_battlefield(my_kavu)
    assert me.mana_pool["U"] == 2


def test_w1g3_coastal_drake_needs_a_kavu_to_exist_and_to_still_be_there(set_pool):
    """With no Kavu on the battlefield the ability cannot be activated at all
    (CR 602.2b), nothing paid. And a Kavu that leaves in response is not
    replaced by the one beside it: the ability does nothing (CR 608.2b)."""
    apc = set_pool("APC")
    game, mine, _ = _w1g3_duel(mine=[apc["Coastal Drake"]], theirs=[apc["Helionaut"]])
    drake, = mine
    nothing = game.activate_permanent_ability(0, "Coastal Drake")
    assert not nothing.supported and not drake.tapped

    game, mine, theirs = _w1g3_duel(
        mine=[apc["Coastal Drake"]], theirs=[apc["Kavu Howler"], apc["Kavu Howler"]],
    )
    named, bystander = theirs
    queued = game.queue_permanent_ability(
        0, "Coastal Drake", target_permanent_ids=[named.permanent_id],
    )
    assert queued.supported, queued.details
    game.remove_from_battlefield(named)
    _w1g3_resolve_stack(game)

    assert game.is_on_battlefield(bystander)
    assert game.players[1].hand == []


def test_w1g3_living_airship_regenerates_from_lethal_damage(set_pool):
    """"{2}{G}: Regenerate this creature." A blue flier whose shield is green
    mana: paid, the next destruction this turn taps it, clears its damage and
    leaves it on the battlefield (CR 701.19a) — and the shield is spent, so
    the second bolt kills it."""
    game, mine, _ = _w1g3_duel(
        [set_pool("LEA")["Lightning Bolt"], set_pool("LEA")["Lightning Bolt"]],
        mine=[set_pool("APC")["Living Airship"]], mana=True,
    )
    airship, = mine
    me = game.players[0]

    assert game._has_keyword(airship, "flying")
    assert not game.activate_permanent_ability(0, "Living Airship").supported
    assert airship.regeneration_shield == 0

    me.mana_pool["G"] = 1
    me.mana_pool["U"] = 2
    assert game.activate_permanent_ability(0, "Living Airship").supported
    assert airship.regeneration_shield == 1
    assert me.mana_pool["G"] == 0 and me.mana_pool["U"] == 0

    game.enforce_mana_costs = False
    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[airship.permanent_id],
    ).supported
    assert game.is_on_battlefield(airship), game.log
    assert airship.tapped and airship.damage_marked == 0 and airship.regeneration_shield == 0

    assert game.cast_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[airship.permanent_id],
    ).supported
    assert not game.is_on_battlefield(airship)
    assert "Living Airship" in _w1g3_names(me.graveyard)


def test_w1g3_helionaut_filters_one_mana_into_any_colour(set_pool):
    """"{1}, {T}: Add one mana of any color." A mana ability (CR 605.1a): it
    never uses the stack, it costs a mana to make one, and the colour is the
    one named. Without the {1} it is refused untapped; summoning sick it
    cannot be tapped for it (CR 302.6)."""
    game, mine, _ = _w1g3_duel(mine=[set_pool("APC")["Helionaut"]], mana=True)
    helionaut, = mine
    me = game.players[0]

    assert game._has_keyword(helionaut, "flying")
    broke = game.activate_permanent_ability(0, "Helionaut", mana_color="R")
    assert not broke.supported and not helionaut.tapped

    me.mana_pool["G"] = 1
    made = game.activate_permanent_ability(0, "Helionaut", mana_color="R")
    assert made.supported, made.details
    assert helionaut.tapped and game.stack == []
    assert {c: n for c, n in me.mana_pool.items() if n} == {"R": 1}

    game, mine, _ = _w1g3_duel(mine=[set_pool("APC")["Helionaut"]], mana=True)
    fresh, = mine
    fresh.metadata["summoning_sickness_turn"] = game.turn
    game.players[0].mana_pool["G"] = 1
    sick = game.activate_permanent_ability(0, "Helionaut", mana_color="W")
    assert not sick.supported and not fresh.tapped
    assert game.players[0].mana_pool["G"] == 1

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================
