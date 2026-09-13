"""Mercadian Masques artifacts.

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

Cards come from `set_pool("MMQ")` / `set_cards("MMQ")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G3: prevention shields and damage redirection ---
from engine import Game as _G3aGame
from engine import PlayerState as _G3aPlayerState
from engine.damage_redirects import redirects_on as _g3a_redirects_on
from engine.models import CardDefinition as _G3aCard
from engine.models import Permanent as _G3aPermanent
from tests.helpers import _damage_dealt as _g3a_dealt
from tests.helpers import resolve_stack as _g3a_resolve


def _g3a_creature(name, power=2, toughness=2):
    """A vanilla creature to take redirected damage, or to deal it."""
    line = "Creature - Test"
    return _G3aCard(
        name=name, mana_cost="", cmc=0.0, type_line=line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": line,
             "power": str(power), "toughness": str(toughness)},
    )


def _g3a_board(seat0=(), seat1=()):
    """A two-seat game with the permanents already on the battlefield."""
    made = _G3aGame(players=[
        _G3aPlayerState(name="P0", battlefield=list(seat0)),
        _G3aPlayerState(name="P1", battlefield=list(seat1)),
    ])
    made.enforce_mana_costs = False
    made.interactive_seats = set()
    return made


def test_generals_regalia_moves_a_chosen_sources_damage_onto_a_named_creature(
    set_pool,
):
    """"{3}: The next time a source of your choice would deal damage to you this
    turn, that damage is dealt to target creature you control instead."

    CR 614.9's redirection, not a shield: the damage is still dealt, in full, by
    the same source, and only its recipient changes. Two announcements again —
    CR 609.7's chosen source and CR 601.2c's target — so an unnamed source is
    checked as well as the named one, because a record that answered to every
    source would move a whole turn's damage onto one creature.
    """
    regalia = _G3aPermanent(card=set_pool("MMQ")["General's Regalia"])
    taker = _G3aPermanent(card=_g3a_creature("Taker", 1, 9))
    named = _G3aPermanent(card=_g3a_creature("Named Source", 3, 3))
    other = _G3aPermanent(card=_g3a_creature("Other Source", 3, 3))
    game = _g3a_board((regalia, taker), (named, other))
    game.start_turn(0)
    game._close_current_priority_step()
    game.players[0].mana_pool.update({"generic": 3})

    result = game.activate_permanent_ability(
        0, "General's Regalia",
        target_player_index=0,
        target_permanent_ids=[taker.permanent_id],
        source_seat=1, source_permanent_index=0,
    )
    assert result.supported, result
    _g3a_resolve(game)
    assert [r.uses for r in _g3a_redirects_on(game.players[0])] == [1]

    before = game.players[0].life
    game._deal_damage_to_player(game.players[0], 2, source=other)
    assert game.players[0].life == before - 2, "an unnamed source is untouched"
    assert taker.damage_marked == 0

    game._deal_damage_to_player(game.players[0], 3, source=named)
    assert game.players[0].life == before - 2, "the named source's damage moved"
    assert taker.damage_marked == 3, "and was dealt in full to the creature"


def test_generals_regalia_will_not_move_its_damage_onto_an_opponents_creature(
    set_pool,
):
    """The printed "you control" is re-checked at resolution (CR 608.2b).

    Dropped, the ability would hand an opponent's creature the damage its
    controller was about to take, which is a strictly better card — and the
    activation, the log and the board all look the same at the moment it is
    announced.
    """
    regalia = _G3aPermanent(card=set_pool("MMQ")["General's Regalia"])
    mine = _G3aPermanent(card=_g3a_creature("Mine", 1, 9))
    theirs = _G3aPermanent(card=_g3a_creature("Theirs", 1, 9))
    game = _g3a_board((regalia, mine), (theirs,))
    game.start_turn(0)
    game._close_current_priority_step()
    game.players[0].mana_pool.update({"generic": 3})

    game.activate_permanent_ability(
        0, "General's Regalia",
        target_player_index=1,
        target_permanent_ids=[theirs.permanent_id],
        source_seat=1, source_permanent_index=0,
    )
    _g3a_resolve(game)

    assert _g3a_redirects_on(game.players[0]) == []


def test_crumbling_sanctuary_exiles_a_library_instead_of_dealing_damage(
    set_pool,
):
    """"If damage would be dealt to a player, that player exiles that many cards
    from the top of their library instead."

    CR 614's substitution: the damage never happens, so no life is lost and
    nothing that watches damage to a player fires. The sentence narrows neither
    end, so it is symmetric — both seats pay — which is the half a reader keyed
    to the artifact's controller would drop while the card still looked right
    from one side of the table.
    """
    sanctuary = _G3aPermanent(card=set_pool("MMQ")["Crumbling Sanctuary"])
    bear = _G3aPermanent(card=_g3a_creature("Bear"))
    game = _g3a_board((sanctuary,), (bear,))
    for seat in game.players:
        seat.library = [_g3a_creature(f"Card{n}") for n in range(10)]

    assert _g3a_dealt(game, game.players[0], 4, source=bear) == 0
    assert len(game.players[0].library) == 6
    assert len(game.players[0].exile) == 4

    assert _g3a_dealt(game, game.players[1], 3, source=bear) == 0, "symmetric"
    assert len(game.players[1].exile) == 3

    assert _g3a_dealt(game, bear, 4, source=bear) == 4, (
        "the sentence names a player, not a permanent"
    )


def test_crumbling_sanctuary_exiles_what_is_there_and_replaces_the_rest(
    set_pool,
):
    """CR 609.3: an effect that cannot do all of something does as much as it
    can — and "as much as it can" is a statement about the *cards*.

    A library shorter than the damage exiles its whole self and the player still
    takes nothing, which is what makes this artifact a way to lose by decking
    rather than a way to survive one more turn. Running out is not a loss until
    a draw is attempted (CR 104.3c), and this is not a draw.
    """
    sanctuary = _G3aPermanent(card=set_pool("MMQ")["Crumbling Sanctuary"])
    bear = _G3aPermanent(card=_g3a_creature("Bear"))
    game = _g3a_board((sanctuary,), (bear,))
    game.players[0].library = [_g3a_creature("Last")]

    before = game.players[0].life
    assert _g3a_dealt(game, game.players[0], 6, source=bear) == 0
    assert game.players[0].life == before, "the whole event was replaced"
    assert game.players[0].library == []
    assert len(game.players[0].exile) == 1
# --- end W1G3 ---


# --- W1G4: upkeep and end-step triggers ---
#
# Two artifacts, both of which parsed cleanly on `main` and were refused one
# layer down: the mill on a phrase the *draw* one family over already read, and
# the Atlas on a CR 603.4 condition nothing had a node for.

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from tests.helpers import resolve_stack


def _g4a_card(name, type_line="Basic Land - Forest"):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name},
    )


def _g4a_duel(set_pool):
    p1 = PlayerState(name="P1")
    p2 = PlayerState(name="P2")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2, set_pool("MMQ")


def _g4a_run(game):
    game._settle()
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._settle()


def test_worry_beads_mills_the_seat_whose_upkeep_it_is(set_pool):
    """"At the beginning of each player's upkeep, **that player** mills a
    card." The seat is the one the upkeep announcement froze - the same record
    the damage recipient and the draw's own reader already take of the same two
    words, and the reading the mill's comment claimed it took and did not."""
    game, p1, p2, by_name = _g4a_duel(set_pool)
    p1.battlefield.append(Permanent(card=by_name["Worry Beads"]))
    p1.library = [_g4a_card("a0"), _g4a_card("a1")]
    p2.library = [_g4a_card("b0"), _g4a_card("b1")]
    game._sync_control()

    game.active_player_index = 0
    game.resolve_upkeep(0)
    _g4a_run(game)
    assert [card.name for card in p1.graveyard] == ["a0"]
    assert p2.graveyard == []

    game.active_player_index = 1
    game.resolve_upkeep(1)
    _g4a_run(game)
    assert [card.name for card in p1.graveyard] == ["a0"]
    assert [card.name for card in p2.graveyard] == ["b0"]


def test_mercadian_atlas_draws_only_on_a_landless_turn(set_pool):
    """"At the beginning of your end step, **if you didn't play a land this
    turn**, you may draw a card." CR 603.4 checks the condition when the
    trigger would fire, so a turn with a land drop puts nothing on the stack at
    all."""
    game, p1, _p2, by_name = _g4a_duel(set_pool)
    p1.battlefield.append(Permanent(card=by_name["Mercadian Atlas"]))
    p1.library = [_g4a_card("top"), _g4a_card("next")]
    game._sync_control()
    game.active_player_index = 0
    game.lands_played_this_turn[0] = 0
    game.resolve_end_step(0)
    _g4a_run(game)

    assert [card.name for card in p1.hand] == ["top"]


def test_a_land_drop_silences_mercadian_atlas(set_pool):
    """The other half of the same gate, read off the per-seat per-turn tally
    the land-play path writes - never off the board, because by the end step a
    land played this turn is an ordinary permanent."""
    game, p1, _p2, by_name = _g4a_duel(set_pool)
    p1.battlefield.append(Permanent(card=by_name["Mercadian Atlas"]))
    p1.library = [_g4a_card("top"), _g4a_card("next")]
    game._sync_control()
    game.active_player_index = 0
    game.lands_played_this_turn[0] = 1
    game.resolve_end_step(0)
    _g4a_run(game)

    assert p1.hand == []
    assert [card.name for card in p1.library] == ["top", "next"]


# --- W2G2: libraries and graveyards ---
# Assembly Hall: a reveal out of your own hand, and a search whose name comes
# from what that reveal turned face up.
from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path
from engine.models import Permanent
from tests.helpers import resolve_stack

_W2G2_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _w2g2_hall(card):
    """A two-seat game with *card* on seat 0's battlefield, ready to tap."""
    game = Game(players=[PlayerState(name="Alice"), PlayerState(name="Bob")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    game._put_permanent_onto_battlefield(0, perm, None)
    return game, perm, game.players[0]
    # end of _w2g2_hall


def test_w2g2_assembly_hall_searches_for_the_revealed_cards_name(set_pool):
    """"{4}, {T}: Reveal a creature card in your hand. Search your library for a
    card **with the same name as that card**, reveal it, put it into your hand,
    then shuffle."

    "That card" is a third referent for CR 201.2's name comparison: not the
    board ("another permanent") and not the firing event's object ("that
    creature"), but a card an earlier step of *this same effect* turned face up.
    Its own field and its own record key for that reason -- a single field would
    make the search read whichever of them happened to be there.

    The library holds two cards the reveal did **not** name, and that is the
    assertion: a dropped name comparison makes this a Demonic Tutor.
    """
    pool = set_pool("MMQ")
    game, _perm, caster = _w2g2_hall(pool["Assembly Hall"])
    caster.hand.extend([_W2G2_LEA["Grizzly Bears"], _W2G2_LEA["Lightning Bolt"]])
    caster.library.extend([
        _W2G2_LEA["Serra Angel"],
        _W2G2_LEA["Grizzly Bears"],
        _W2G2_LEA["Forest"],
    ])

    result = game.activate_permanent_ability(0, "Assembly Hall")
    resolve_stack(game)
    assert result.supported, result.details

    owed = [c for c in game.pending_choices if c.kind == "search_library"]
    assert owed, "the search should be owed once the reveal is answered"
    restrictions = owed[0].data["restrictions"]
    assert restrictions["named_from_record"] == "revealed_hand_cards"
    assert restrictions["named"] == "Grizzly Bears"

    from engine.search_filters import search_matches

    offered = [
        card.name for card in caster.library
        if search_matches(card, owed[0].data, game=game, owner=0)
    ]
    assert offered == ["Grizzly Bears"]

    assert game.resolve_pending_choice(
        "search_library", 0, zone="library", library_index=1,
    )
    resolve_stack(game)
    assert [c.name for c in caster.hand].count("Grizzly Bears") == 2
    assert sorted(c.name for c in caster.library) == ["Forest", "Serra Angel"]
    # end of test_w2g2_assembly_hall_searches_for_the_revealed_cards_name


def test_w2g2_assembly_hall_reveals_only_a_creature_card(set_pool):
    """"Reveal **a** creature card in your hand."

    A printed count where every earlier printing of this sentence said "any
    number of", and a printed noun phrase the prompt is built from rather than
    checked against -- a prompt listing a wider set than the card names is a card
    that reports supported and cheats. With no creature card in hand there is
    nothing to reveal, so the search behind it has no name and finds nothing
    rather than everything.
    """
    pool = set_pool("MMQ")
    game, _perm, caster = _w2g2_hall(pool["Assembly Hall"])
    caster.hand.append(_W2G2_LEA["Lightning Bolt"])
    caster.library.extend([_W2G2_LEA["Serra Angel"], _W2G2_LEA["Forest"]])

    result = game.activate_permanent_ability(0, "Assembly Hall")
    resolve_stack(game)

    assert result.supported, result.details
    assert sorted(c.name for c in caster.library) == ["Forest", "Serra Angel"]
    assert [c.name for c in caster.hand] == ["Lightning Bolt"]
    # end of test_w2g2_assembly_hall_reveals_only_a_creature_card


# --- W2G3: artifact activated abilities ---
import random as _w2g3_random

import pytest as _w2g3_pytest

from engine import Game as _W2G3Game
from engine import PlayerState as _W2G3PlayerState
from engine.control import change_control as _w2g3_change_control
from engine.cost_x_definitions import cost_x_value as _w2g3_cost_x_value
from engine.models import CardDefinition as _W2G3Card
from engine.models import Permanent as _W2G3Permanent
from tests.helpers import _damage_dealt as _w2g3_dealt
from tests.helpers import resolve_stack as _w2g3_resolve


def _w2g3_card(name, type_line="Creature - Test", colors=()):
    """A plain card to stand in the board this group's artifacts act on."""
    raw = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw["power"], raw["toughness"] = "2", "2"
    return _W2G3Card(
        name=name, mana_cost="", cmc=0.0, type_line=type_line,
        oracle_text="", colors=tuple(colors),
        color_identity=tuple(colors), keywords=(), produced_mana=(), raw=raw,
    )
    # W2G3's plain-card helper ends here.


def _w2g3_duel(*seat0, seat1=()):
    """A two-seat game with *seat0* already on the first battlefield.

    Non-interactive by default, which is what makes every pending choice this
    group arms take its registered default at once.
    """
    made = _W2G3Game(players=[
        _W2G3PlayerState(name="P0", battlefield=list(seat0)),
        _W2G3PlayerState(name="P1", battlefield=list(seat1)),
    ])
    made.enforce_mana_costs = False
    made.interactive_seats = set()
    made._sync_control()
    return made, made.players[0], made.players[1]
    # W2G3's two-seat board helper ends here.


# -- Barbed Wire: CR 615.7's pool with CR 615.8's absent recipient -----------


def _w2g3_wired(set_pool):
    """A Barbed Wire on seat 0's battlefield, ready to be activated."""
    wire = _W2G3Permanent(card=set_pool("MMQ")["Barbed Wire"])
    game, p0, p1 = _w2g3_duel(wire)
    return game, p0, p1, wire
    # W2G3's Barbed Wire board helper ends here.


@_w2g3_pytest.mark.cr("615.7", "615.8")
def test_barbed_wire_shields_the_player_its_own_damage_is_aimed_at(set_pool):
    """"{2}: Prevent the next 1 damage that would be dealt by this artifact
    this turn."

    The sentence names **no recipient** — CR 615.8's shield is defined by its
    source alone — so the point it absorbs is the next one Barbed Wire deals to
    anybody, which on this card is usually the opponent: the upkeep trigger
    fires on each player's turn and the activator is only ever one of them.
    """
    game, _p0, p1, _wire = _w2g3_wired(set_pool)
    result = game.activate_permanent_ability(0, "Barbed Wire")
    _w2g3_resolve(game)
    assert result.supported

    game.active_player_index = 1
    game.resolve_upkeep(1)
    _w2g3_resolve(game)

    assert p1.life == 20, "the shield never reached a recipient it did not name"


@_w2g3_pytest.mark.cr("615.7")
def test_barbed_wire_without_the_shield_still_bites(set_pool):
    """The other half, so the test above cannot pass on an upkeep that dealt no
    damage at all."""
    game, _p0, p1, _wire = _w2g3_wired(set_pool)

    game.active_player_index = 1
    game.resolve_upkeep(1)
    _w2g3_resolve(game)

    assert p1.life == 19


@_w2g3_pytest.mark.cr("615.7")
def test_barbed_wires_pool_is_spent_by_the_first_point_it_absorbs(set_pool):
    """CR 615.7 counts the *amount*, not the events: one activation is one
    point, so a second upkeep in the same turn is dealt in full."""
    game, p0, p1, _wire = _w2g3_wired(set_pool)
    game.activate_permanent_ability(0, "Barbed Wire")
    _w2g3_resolve(game)

    game.active_player_index = 0
    game.resolve_upkeep(0)
    _w2g3_resolve(game)
    game.active_player_index = 1
    game.resolve_upkeep(1)
    _w2g3_resolve(game)

    assert (p0.life, p1.life) == (20, 19)


@_w2g3_pytest.mark.cr("615.9", "615.8")
def test_barbed_wires_shield_answers_only_to_the_source_that_armed_it(set_pool):
    """CR 615.9 rechecks the property the shield recorded, and what this one
    recorded is the permanent itself — so damage from anything else is none of
    its business. A recipientless shield reaches every recipient in the game
    (``prevention._table_shields``), which is exactly why it has to be narrow at
    the other end: without the source it would absorb the next point of damage
    dealt to anybody by anything."""
    game, _p0, p1, _wire = _w2g3_wired(set_pool)
    stranger = _W2G3Permanent(card=_w2g3_card("Rod", "Artifact"))
    game.players[0].battlefield.append(stranger)
    game._sync_control()
    game.activate_permanent_ability(0, "Barbed Wire")
    _w2g3_resolve(game)

    assert _w2g3_dealt(game, p1, 1, source=stranger) == 1


# -- Jeweled Torque: CR 614.1c's record read by a cast trigger ---------------


@_w2g3_pytest.mark.cr("614.1c", "603.2")
def test_jeweled_torque_offers_its_toll_only_for_the_chosen_colour(set_pool):
    """"Whenever a player casts a spell of the chosen color, you may pay {2}.
    If you do, you gain 2 life."

    The colour is not in the trigger's text: it is what the artifact recorded
    as it entered. The narrowing used to be dropped by the condition table
    outright, and only the effect parser refusing the leftover words kept the
    trigger from firing on every spell in the game — at the cost of the whole
    ability doing nothing.
    """
    torque = _W2G3Permanent(card=set_pool("MMQ")["Jeweled Torque"])
    torque.metadata["chosen_color"] = "R"
    game, p0, p1 = _w2g3_duel(torque)
    game.interactive_seats = {0}
    p0.mana_pool["C"] = 2
    p1.hand.append(_w2g3_card("Red Spell", "Instant", colors=("R",)))

    game.cast_from_hand(1, "Red Spell")
    assert [choice.kind for choice in game.pending_choices] == ["optional_pay"]
    assert game.confirm_optional_pay(0, accept=True)

    assert p0.life == 22


@_w2g3_pytest.mark.cr("614.1c")
def test_jeweled_torque_is_silent_for_every_other_colour(set_pool):
    """A trigger firing on any spell at all would be this card without the one
    printed phrase that narrows it."""
    torque = _W2G3Permanent(card=set_pool("MMQ")["Jeweled Torque"])
    torque.metadata["chosen_color"] = "R"
    game, p0, p1 = _w2g3_duel(torque)
    game.interactive_seats = {0}
    p0.mana_pool["C"] = 2
    p1.hand.append(_w2g3_card("Blue Spell", "Instant", colors=("U",)))

    game.cast_from_hand(1, "Blue Spell")

    assert game.pending_choices == []


@_w2g3_pytest.mark.cr("105.2b")
def test_jeweled_torque_reads_a_gold_spell_as_each_of_its_colours(set_pool):
    """CR 105.2b: an object with more than one colour **is** each of them, so a
    blue-and-red spell answers a Torque that chose either."""
    torque = _W2G3Permanent(card=set_pool("MMQ")["Jeweled Torque"])
    torque.metadata["chosen_color"] = "U"
    game, p0, p1 = _w2g3_duel(torque)
    game.interactive_seats = {0}
    p0.mana_pool["C"] = 2
    p1.hand.append(_w2g3_card("Gold Spell", "Instant", colors=("U", "R")))

    game.cast_from_hand(1, "Gold Spell")

    assert [choice.kind for choice in game.pending_choices] == ["optional_pay"]


@_w2g3_pytest.mark.cr("614.1c")
def test_jeweled_torque_with_no_colour_recorded_answers_nothing(set_pool):
    """A permanent whose entry choice never happened has no colour to compare,
    and a trigger with nothing to compare would answer **every** spell — the
    widest possible reading of a sentence that names one."""
    torque = _W2G3Permanent(card=set_pool("MMQ")["Jeweled Torque"])
    game, p0, p1 = _w2g3_duel(torque)
    game.interactive_seats = {0}
    p0.mana_pool["C"] = 2
    p1.hand.append(_w2g3_card("Red Spell", "Instant", colors=("R",)))

    game.cast_from_hand(1, "Red Spell")

    assert game.pending_choices == []


# -- Bargaining Table: CR 601.2b's announcement the card takes away ----------


@_w2g3_pytest.mark.cr("601.2b", "602.2b")
def test_bargaining_table_costs_the_opponents_hand_size(set_pool):
    """"{X}, {T}: Draw a card. X is the number of cards in an opponent's hand."

    The activator never announces X — the board decides it — and the table the
    grammar consumed the sentence through is the same one that charges it.
    """
    table = _W2G3Permanent(card=set_pool("MMQ")["Bargaining Table"])
    game, p0, p1 = _w2g3_duel(table)
    game.enforce_mana_costs = True
    p1.hand = [_w2g3_card("h%d" % index) for index in range(4)]
    p0.library = [_w2g3_card("top")]
    p0.mana_pool["C"] = 4

    result = game.activate_permanent_ability(0, "Bargaining Table")
    _w2g3_resolve(game)

    assert result.supported
    assert [card.name for card in p0.hand] == ["top"]
    assert sum(p0.mana_pool.values()) == 0, "X was announced rather than counted"


@_w2g3_pytest.mark.cr("601.2b")
def test_bargaining_table_cannot_be_activated_for_less_than_that(set_pool):
    """The half a consumed-but-uncharged definition hides: an {X} nobody prices
    is a free ability."""
    table = _W2G3Permanent(card=set_pool("MMQ")["Bargaining Table"])
    game, p0, p1 = _w2g3_duel(table)
    game.enforce_mana_costs = True
    p1.hand = [_w2g3_card("h%d" % index) for index in range(4)]
    p0.library = [_w2g3_card("top")]
    p0.mana_pool["C"] = 3

    result = game.activate_permanent_ability(0, "Bargaining Table")

    assert not result.supported
    assert p0.hand == []


@_w2g3_pytest.mark.cr("107.3")
def test_bargaining_tables_x_is_read_off_the_one_opponent_there_is(set_pool):
    """The reader itself, asked directly: a number off a *player* rather than
    off the source, which is why it is the first row in its table that needs
    the game."""
    table = _W2G3Permanent(card=set_pool("MMQ")["Bargaining Table"])
    game, _p0, p1 = _w2g3_duel(table)
    p1.hand = [_w2g3_card("h%d" % index) for index in range(6)]

    assert _w2g3_cost_x_value(
        game, table, set_pool("MMQ")["Bargaining Table"].oracle_text
    ) == 6


# -- Credit Voucher: an open-ended count answered mid-resolution -------------


def _w2g3_voucher(set_pool, hand=3, library=8):
    """A Credit Voucher with a hand to shuffle away and a library to draw."""
    voucher = _W2G3Permanent(card=set_pool("MMQ")["Credit Voucher"])
    game, p0, _p1 = _w2g3_duel(voucher)
    p0.hand = [_w2g3_card("h%d" % index) for index in range(hand)]
    p0.library = [_w2g3_card("L%d" % index) for index in range(library)]
    return game, p0
    # W2G3's Credit Voucher board helper ends here.


@_w2g3_pytest.mark.cr("402.1", "701.24a")
def test_credit_voucher_draws_exactly_what_its_controller_shuffled_away(set_pool):
    """"Shuffle any number of cards from your hand into your library, then draw
    that many cards."

    "That many" is the number the *answer* decided, which is why the draw rides
    the move rather than following it: nothing before the prompt knows it.
    """
    _w2g3_random.seed(17)
    game, p0 = _w2g3_voucher(set_pool)
    game.interactive_seats = {0}
    kept = p0.hand[1].name

    game.activate_permanent_ability(0, "Credit Voucher")
    assert game.confirm_hand_to_library(0, [0, 2])

    assert len(p0.hand) == 3, "the draw did not match what was shuffled away"
    assert kept in [card.name for card in p0.hand]
    assert len(p0.library) == 8


@_w2g3_pytest.mark.cr("402.1")
def test_credit_voucher_takes_an_empty_answer_as_declining_the_offer(set_pool):
    """"Any number" includes none, and the count the prompt carries is a
    ceiling — the exact-equality every other card reaching this prompt keeps
    would have refused the answer and left the ability owed for ever."""
    _w2g3_random.seed(4)
    game, p0 = _w2g3_voucher(set_pool)
    game.interactive_seats = {0}
    before = [card.name for card in p0.hand]

    game.activate_permanent_ability(0, "Credit Voucher")
    assert game.confirm_hand_to_library(0, [])

    assert [card.name for card in p0.hand] == before
    assert len(p0.library) == 8
    assert game.pending_choices == []


@_w2g3_pytest.mark.cr("402.1")
def test_credit_vouchers_default_takes_the_whole_offer(set_pool):
    """The stated policy for an "up to" whose offer buys something per card,
    which this one does: a card shuffled away is a card drawn."""
    _w2g3_random.seed(9)
    game, p0 = _w2g3_voucher(set_pool)

    game.activate_permanent_ability(0, "Credit Voucher")
    game.auto_resolve_pending_choices()

    assert len(p0.hand) == 3
    assert {card.name for card in p0.hand} <= {
        "L%d" % index for index in range(8)
    }


# -- Distorting Lens: CR 613 layer 5 with a window on it ---------------------


@_w2g3_pytest.mark.cr("613.1e", "105.2")
def test_distorting_lens_recolours_its_target_for_the_turn(set_pool):
    """"{T}: Target permanent becomes the color of your choice until end of
    turn."

    Alchor's Tomb's sentence with a duration, which is the only difference — so
    it is the same instruction writing the turn-long layer-5 channel instead of
    the indefinite one.
    """
    lens = _W2G3Permanent(card=set_pool("MMQ")["Distorting Lens"])
    victim = _W2G3Permanent(card=_w2g3_card("Bear", "Creature - Bear", colors=("G",)))
    game, _p0, _p1 = _w2g3_duel(lens, victim)

    result = game.activate_permanent_ability(
        0, "Distorting Lens", target_permanent_index=1,
        target_permanent_ids=[victim.permanent_id], mana_color="U",
    )
    _w2g3_resolve(game)

    assert result.supported
    assert game._effective_colors(victim) == {"U"}


@_w2g3_pytest.mark.cr("613.1e")
def test_distorting_lenss_colour_wears_off_with_the_turn(set_pool):
    """The half that says which channel was written: an indefinite lace would
    survive the cleanup step, and this must not."""
    lens = _W2G3Permanent(card=set_pool("MMQ")["Distorting Lens"])
    victim = _W2G3Permanent(card=_w2g3_card("Bear", "Creature - Bear", colors=("G",)))
    game, _p0, _p1 = _w2g3_duel(lens, victim)
    game.activate_permanent_ability(
        0, "Distorting Lens", target_permanent_index=1,
        target_permanent_ids=[victim.permanent_id], mana_color="U",
    )
    _w2g3_resolve(game)

    game.resolve_cleanup_step(0)

    assert game._effective_colors(victim) == {"G"}


# -- Rishadan Pawnshop: CR 108.3, read off the seat control never rewrites ---


@_w2g3_pytest.mark.cr("701.24a", "400.3")
def test_rishadan_pawnshop_shuffles_your_own_permanent_into_your_library(set_pool):
    """"{2}, {T}: Shuffle target nontoken permanent you control into its
    owner's library." A zone change, not a destruction — nothing reaches a
    graveyard."""
    _w2g3_random.seed(21)
    shop = _W2G3Permanent(card=set_pool("MMQ")["Rishadan Pawnshop"])
    mine = _W2G3Permanent(card=_w2g3_card("Mine"))
    game, p0, _p1 = _w2g3_duel(shop, mine)
    p0.library = [_w2g3_card("L%d" % index) for index in range(3)]

    result = game.activate_permanent_ability(
        0, "Rishadan Pawnshop", target_permanent_ids=[mine.permanent_id],
    )
    _w2g3_resolve(game)

    assert result.supported
    assert [perm.card.name for perm in game.controlled_by(0)] == [
        "Rishadan Pawnshop",
    ]
    assert sorted(card.name for card in p0.library) == ["L0", "L1", "L2", "Mine"]
    assert p0.graveyard == []


@_w2g3_pytest.mark.cr("108.3", "400.3")
def test_rishadan_pawnshop_sends_a_stolen_permanent_to_its_owners_library(set_pool):
    """The phrase says "you control" and CR 400.3 says whose library, and on a
    permanent taken by a control-change effect those are two different players.
    The answer is asked of ``Game.owner_index_of``, the one accessor for
    CR 108.3, rather than read off any field the handler could go stale
    against."""
    _w2g3_random.seed(22)
    shop = _W2G3Permanent(card=set_pool("MMQ")["Rishadan Pawnshop"])
    stolen = _W2G3Permanent(card=_w2g3_card("Stolen"))
    game, p0, p1 = _w2g3_duel(shop, seat1=[stolen])
    p0.library = [_w2g3_card("L%d" % index) for index in range(2)]
    p1.library = [_w2g3_card("R%d" % index) for index in range(2)]
    _w2g3_change_control(stolen, 0, source="a test")
    game._sync_control()

    game.activate_permanent_ability(
        0, "Rishadan Pawnshop", target_permanent_ids=[stolen.permanent_id],
    )
    _w2g3_resolve(game)

    assert sorted(card.name for card in p0.library) == ["L0", "L1"]
    assert sorted(card.name for card in p1.library) == ["R0", "R1", "Stolen"]


@_w2g3_pytest.mark.cr("601.2c", "602.2b")
def test_rishadan_pawnshop_refuses_a_token_with_nothing_paid(set_pool):
    """"**Nontoken**" is a printed narrowing, so the picker never offers a token
    and the activation is refused before the tap is paid — rather than
    activated onto a permanent the phrase excludes."""
    shop = _W2G3Permanent(card=set_pool("MMQ")["Rishadan Pawnshop"])
    token = _W2G3Permanent(card=_w2g3_card("Tok"))
    token.metadata["is_token"] = True
    game, p0, _p1 = _w2g3_duel(shop, token)
    p0.library = [_w2g3_card("L0")]

    result = game.activate_permanent_ability(
        0, "Rishadan Pawnshop", target_permanent_ids=[token.permanent_id],
    )

    assert not result.supported
    assert not shop.tapped
    assert [perm.card.name for perm in game.controlled_by(0)] == [
        "Rishadan Pawnshop", "Tok",
    ]
