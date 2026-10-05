"""Planeshift creatures.

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

Cards come from `set_pool("PLS")` / `set_cards("PLS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G7: triggers and cast rules ---
from engine import Game as _W1G7Game
from engine import PlayerState as _W1G7PlayerState
from engine.counter_conditions import cant_be_countered as _w1g7_cant_be_countered
from engine.counter_conditions import (
    uncounterable_class_line as _w1g7_uncounterable_class_line,
)
from engine.models import CardDefinition as _W1G7Card
from engine.models import Permanent as _W1G7Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_card(name, type_line, text="", *, cost="{1}", colors=(), pt=None):
    """A fixture card with exactly the printed text a creature test needs."""
    raw = {"name": name, "type_line": type_line}
    if pt is not None:
        raw["power"], raw["toughness"] = str(pt[0]), str(pt[1])
    built = _W1G7Card(
        name=name, mana_cost=cost, cmc=float(cost.count("{")),
        type_line=type_line, oracle_text=text, colors=tuple(colors),
        color_identity=tuple(colors), keywords=(), produced_mana=(), raw=raw,
    )
    return built


def _w1g7_table(mine=(), theirs=(), *, hands=((), ()), interactive=()):
    """Two seats with costs off; the creature under test on seat 0 unless the
    test puts it elsewhere."""
    filler = _w1g7_card("W1G7 Filler", "Creature - Test", pt=(1, 1))
    duel = _W1G7Game(players=[
        _W1G7PlayerState(
            name="P1", battlefield=list(mine), hand=list(hands[0]),
            library=[filler] * 8,
        ),
        _W1G7PlayerState(
            name="P2", battlefield=list(theirs), hand=list(hands[1]),
            library=[filler] * 8,
        ),
    ])
    duel.enforce_mana_costs = False
    duel.interactive_seats = set(interactive)
    return duel


# Gaea's Herald — "Creature spells can't be countered." The board half of
# Scragnoth's immunity: a permanent's static about every spell of a type,
# asked by the one counter path at CR 608.2 beside the spell's own line.


def _w1g7_counter_a_spell(set_pool, spell, *, counter="Counterspell",
                          herald_seat=0, **cast):
    """Seat 0 casts *spell*, seat 1 answers with *counter*; the stack drains."""
    herald = _W1G7Permanent(card=set_pool("PLS")["Gaea's Herald"])
    sides = [[], []]
    if herald_seat is not None:
        sides[herald_seat].append(herald)
    answer = next(
        set_pool(code)[counter]
        for code in ("LEA", "ICE", "MIR", "INV")
        if counter in set_pool(code)
    )
    duel = _w1g7_table(sides[0], sides[1], hands=((spell,), (answer,)))
    assert duel.queue_from_hand(0, spell.name).supported
    # CR 115.1: the counter is a legal cast — "target spell" is not "target
    # spell that can be countered".
    assert duel.queue_from_hand(1, counter, target_player_index=0, **cast).supported
    _w1g7_resolve_stack(duel)
    duel.auto_resolve_pending_choices()
    return duel


def test_w1g7_gaeas_herald_is_supported_through_the_counter_path(set_pool):
    herald = set_pool("PLS")["Gaea's Herald"]
    program = _w1g7_compile(herald)
    assert program.supported, program.reason
    assert _w1g7_uncounterable_class_line(herald.oracle_text) == "creature"
    # The narrower sentence is a different card and must refuse, not widen.
    assert _w1g7_uncounterable_class_line(
        "Creature spells you control can't be countered."
    ) is None


def test_w1g7_gaeas_herald_keeps_a_creature_spell_from_being_countered(set_pool):
    bears = set_pool("LEA")["Grizzly Bears"]
    duel = _w1g7_counter_a_spell(set_pool, bears)

    assert "Grizzly Bears" in [p.card.name for p in duel.players[0].battlefield]
    assert duel.players[0].graveyard == []
    assert [c.name for c in duel.players[1].graveyard] == ["Counterspell"]
    assert any("can't be countered (Gaea's Herald)" in line for line in duel.log)


def test_w1g7_gaeas_herald_protects_every_players_creature_spells(set_pool):
    """The sentence names nobody: an opponent's Herald protects my creature
    spell from that same opponent's Counterspell."""
    bears = set_pool("LEA")["Grizzly Bears"]
    duel = _w1g7_counter_a_spell(set_pool, bears, herald_seat=1)

    assert [p.card.name for p in duel.players[0].battlefield] == ["Grizzly Bears"]


def test_w1g7_gaeas_herald_reads_every_type_an_artifact_creature_has(set_pool):
    """CR 205.2: an artifact creature spell is a creature spell."""
    golem = _w1g7_card(
        "W1G7 Golem", "Artifact Creature - Golem", cost="{3}", pt=(3, 3)
    )
    duel = _w1g7_counter_a_spell(set_pool, golem)

    assert "W1G7 Golem" in [p.card.name for p in duel.players[0].battlefield]


def test_w1g7_gaeas_herald_says_nothing_about_a_noncreature_spell(set_pool):
    """The narrowing is the card: dropped, the Herald would make every spell
    in the game uncounterable."""
    rock = _w1g7_card("W1G7 Rock", "Artifact", cost="{2}")
    duel = _w1g7_counter_a_spell(set_pool, rock)

    assert [c.name for c in duel.players[0].graveyard] == ["W1G7 Rock"]
    assert "W1G7 Rock" not in [p.card.name for p in duel.players[0].battlefield]


def test_w1g7_gaeas_herald_arms_no_payment_for_a_spell_nothing_can_counter(set_pool):
    """Asked before Power Sink's "unless its controller pays" — a player asked
    to pay to prevent something that cannot happen would pay."""
    bears = set_pool("LEA")["Grizzly Bears"]
    duel = _w1g7_counter_a_spell(set_pool, bears, counter="Power Sink", x_value=3)

    assert duel.pending_choices == []
    assert "Grizzly Bears" in [p.card.name for p in duel.players[0].battlefield]


def test_w1g7_gaeas_herald_does_not_protect_itself_on_the_stack(set_pool):
    """A static of a *permanent* (CR 113.6): the Herald on the stack is not on
    the battlefield, so nothing is yet saying its sentence."""
    herald = set_pool("PLS")["Gaea's Herald"]
    duel = _w1g7_counter_a_spell(set_pool, herald, herald_seat=None)

    assert [c.name for c in duel.players[0].graveyard] == ["Gaea's Herald"]
    assert duel.players[0].battlefield == []


def test_w1g7_gaeas_herald_stops_protecting_once_it_has_left(set_pool):
    herald = _W1G7Permanent(card=set_pool("PLS")["Gaea's Herald"])
    bears = set_pool("LEA")["Grizzly Bears"]
    duel = _w1g7_table([herald], [])
    assert _w1g7_cant_be_countered(duel, bears) is not None

    duel.remove_from_battlefield(herald)

    assert _w1g7_cant_be_countered(duel, bears) is None


# Meddling Mage — "As this creature enters, choose a nonland card name." /
# "Spells with the chosen name can't be cast." Null Chamber's machinery with one
# chooser, CR 201.4a's "nonland" bound and no land half: the entry choice is
# Runed Halo's prompt read as a pattern, and the ban is a second row of the
# chosen-name table read by the same cast gate.


def _w1g7_mage_table(set_pool, *, mine=(), theirs=(), interactive=(0,)):
    """Seat 0 holds a Meddling Mage and casts it; the entry prompt is owed."""
    mage = set_pool("PLS")["Meddling Mage"]
    duel = _w1g7_table(
        [], [], hands=((mage, *mine), tuple(theirs)), interactive=interactive
    )
    assert duel.cast_from_hand(0, "Meddling Mage").supported
    duel.resolve_stack(pause_for_choices=True)
    entered = next(
        p for p in duel.players[0].battlefield if p.card.name == "Meddling Mage"
    )
    return duel, entered


def _w1g7_split_card(set_pool):
    from engine.faces import face_cards

    whole = set_pool("INV")["Stand // Deliver"]
    first, second = face_cards(whole)
    return whole, first.name, second.name


def test_w1g7_meddling_mage_is_supported_by_both_of_its_lines(set_pool):
    from engine.cast_restrictions import chosen_name_ban_row
    from engine.enter_effects import chooses_card_name_on_enter, enter_effect_line

    mage = set_pool("PLS")["Meddling Mage"]
    program = _w1g7_compile(mage)
    assert program.supported, program.reason

    entry, ban = mage.oracle_text.split("\n")
    assert enter_effect_line(entry) == "chooses a card name as it enters"
    assert chooses_card_name_on_enter(entry.lower()) == {
        "excluded_card_type": "land"
    }
    # Spells only: the row says so, and the gate reads it.
    assert chosen_name_ban_row(ban) == ("chosen_card_name", False)
    # A longer bound is a different card and refuses rather than being read as
    # the unbounded choice with its exclusion dropped.
    assert chooses_card_name_on_enter(
        "as this creature enters, choose a card name other than a basic land "
        "card name."
    ) is None


def test_w1g7_meddling_mage_asks_its_controller_for_one_nonland_name(set_pool):
    bolt = set_pool("LEA")["Lightning Bolt"]
    forest = set_pool("LEA")["Forest"]
    duel, entered = _w1g7_mage_table(set_pool, theirs=(bolt,))
    duel.players[1].graveyard.extend([forest, bolt])

    (asked,) = duel.pending_choices
    assert (asked.kind, asked.player_index) == ("enter_choice", 0)
    assert asked.data["needs_card_name"]
    assert asked.data["excluded_card_type"] == "land"

    # CR 201.4a: a land's name is not a nonland card name. Refused, not
    # repaired — the prompt stays owed.
    assert not duel.confirm_enter_choice(0, card_name="Forest")
    assert [c.kind for c in duel.pending_choices] == ["enter_choice"]

    assert duel.confirm_enter_choice(0, card_name="Lightning Bolt")
    assert entered.metadata["chosen_card_name"] == "Lightning Bolt"
    assert duel.pending_choices == []


def test_w1g7_meddling_mage_stops_every_player_casting_the_named_spell(set_pool):
    """CR 601.3: the sentence names nobody, so it binds the Mage's own
    controller as surely as the opponent."""
    bolt = set_pool("LEA")["Lightning Bolt"]
    bears = set_pool("LEA")["Grizzly Bears"]
    duel, _entered = _w1g7_mage_table(
        set_pool, mine=(bolt,), theirs=(bolt, bears)
    )
    assert duel.confirm_enter_choice(0, card_name="Lightning Bolt")

    theirs = duel.cast_from_hand(1, "Lightning Bolt", target_player_index=0)
    assert not theirs.supported and "Meddling Mage" in theirs.details
    mine = duel.cast_from_hand(0, "Lightning Bolt", target_player_index=1)
    assert not mine.supported and "Meddling Mage" in mine.details
    assert [seat.life for seat in duel.players] == [20, 20]
    assert len(duel.players[1].hand) == 2, "a refused cast spends nothing"

    # The control: a card nobody named is unaffected.
    assert duel.cast_from_hand(1, "Grizzly Bears").supported


def test_w1g7_meddling_mage_stops_one_half_of_a_split_card_and_not_the_other(
    set_pool,
):
    """CR 201.4b names a split card by one half; CR 709.3a evaluates only the
    half being cast. Naming the first half leaves the second castable, and the
    joined spelling is the name of no spell and is refused as an answer."""
    from engine.cast_restrictions import chosen_name_ban
    from engine.faces import face_cards

    whole, first, second = _w1g7_split_card(set_pool)
    duel, entered = _w1g7_mage_table(set_pool, theirs=(whole, whole))

    assert not duel.confirm_enter_choice(0, card_name=whole.name)
    assert duel.confirm_enter_choice(0, card_name=first)
    assert entered.metadata["chosen_card_name"] == first

    stopped = duel.cast_from_hand(1, first)
    assert not stopped.supported and "Meddling Mage" in stopped.details
    halves = {face.name: face for face in face_cards(whole)}
    assert chosen_name_ban(duel, halves[first]) == "Meddling Mage"
    assert chosen_name_ban(duel, halves[second]) is None


def test_w1g7_meddling_mage_lifts_its_ban_when_it_leaves(set_pool):
    bolt = set_pool("LEA")["Lightning Bolt"]
    duel, entered = _w1g7_mage_table(set_pool, theirs=(bolt,))
    assert duel.confirm_enter_choice(0, card_name="Lightning Bolt")
    refused = duel.cast_from_hand(1, "Lightning Bolt", target_player_index=0)
    assert not refused.supported

    duel.remove_from_battlefield(entered)

    assert duel.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert duel.players[0].life == 17


def test_w1g7_meddling_mage_says_nothing_about_a_land_drop(set_pool):
    """"**Spells** … can't be cast": a land is played, never cast (CR 305.1).
    The name is forced onto the record here because the prompt would refuse it
    — the row, not the prompt, is what this test holds."""
    forest = set_pool("LEA")["Forest"]
    mage = _W1G7Permanent(card=set_pool("PLS")["Meddling Mage"])
    mage.metadata["chosen_card_name"] = "Forest"
    duel = _w1g7_table([mage], [], hands=((forest,), ()))
    duel.start_turn(0)

    assert duel.cast_from_hand(0, "Forest").supported


def test_w1g7_meddling_mage_names_something_for_a_seat_nobody_asks(set_pool):
    """A headless seat names the nonland card it last saw an opponent use —
    never a land, and never nothing while there is something to see."""
    bolt = set_pool("LEA")["Lightning Bolt"]
    forest = set_pool("LEA")["Forest"]
    mage = set_pool("PLS")["Meddling Mage"]
    duel = _w1g7_table([], [], hands=((mage,), (bolt,)))
    duel.players[1].graveyard.extend([bolt, forest])

    assert duel.cast_from_hand(0, "Meddling Mage").supported
    _w1g7_resolve_stack(duel)
    duel.auto_resolve_pending_choices()

    entered = next(
        p for p in duel.players[0].battlefield if p.card.name == "Meddling Mage"
    )
    assert entered.metadata["chosen_card_name"] == "Lightning Bolt"
    refused = duel.cast_from_hand(1, "Lightning Bolt", target_player_index=0)
    assert not refused.supported


def test_w1g7_meddling_mage_takes_the_named_card_off_the_ais_proposals(set_pool):
    """A refused cast spends nothing, so a seat that kept proposing the named
    card would do nothing else for as long as the Mage stood."""
    from engine.ai_policy import _can_cast_with_targets

    bears = set_pool("LEA")["Grizzly Bears"]
    wolves = set_pool("LEA")["Timber Wolves"]
    mage = _W1G7Permanent(card=set_pool("PLS")["Meddling Mage"])
    mage.metadata["chosen_card_name"] = "Grizzly Bears"
    duel = _w1g7_table([mage], [], hands=((), (bears, wolves)))

    assert not _can_cast_with_targets(duel, 1, bears)
    assert _can_cast_with_targets(duel, 1, wolves)
