"""CR 603.3 — when a trigger that fired goes on the stack, and whether it does.

Two questions that look unrelated and are the same question: a trigger has to
reach the stack, and it has to reach it *at the right moment*. Both were
answered by the fire site rather than by the rules.

**Whether.** ``_permanent_to_graveyard`` fired a card's own dies-trigger through
one loop per instruction kind, each added by the card that needed it — so a
dies-trigger of any other shape did nothing at all. Onulet ("When this creature
dies, you gain 2 life") ships in the shipped pool at 388/388 supported and
gained no life in its life.

**When.** CR 601.2a puts a spell on the stack before its costs are paid
(CR 601.2h), and CR 602.2a/602.2b say the same of an activated ability, so a
trigger fired *by* a cost belongs above the object that cost paid for. This
engine pays first and pushes second — the rewind of an unpayable cost is done by
never having built the stack item — which put every such trigger underneath.
"""

import pytest

from engine import Game, PlayerState, load_cards
from engine.card_loader import load_catalog, manifest_set_path
from engine.models import CardDefinition, Permanent
from engine.oracle_types import OracleInstruction

_CATALOG = {c.name: c for c in load_catalog()}
_M21 = {
    c.name: c
    for c in load_cards(manifest_set_path("M21", include_measured=True))
}


def _duel(active: int = 0) -> tuple[Game, PlayerState, PlayerState]:
    p1, p2 = PlayerState(name="A"), PlayerState(name="B")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = active
    return game, p1, p2


def _nosick(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


# ---------------------------------------------------------------------------
# Whether it fires at all
# ---------------------------------------------------------------------------


@pytest.mark.cr("603.3", "700.4")
def test_a_dies_trigger_fires_whatever_its_effect_is():
    """Onulet: "When this creature dies, you gain 2 life."

    The shipped-pool card whose only ability never happened. Its effect lowers
    to ``target_gains_life``, which the fire site did look for — but only with
    Conclave Mentor's "equal to its power" payload key, so a fixed amount fell
    through every loop there was.

    Nothing caught it because nothing had looked: Onulet is one of the nineteen
    cards Revised added that the verification tracker has no recorded result
    for, while the generated file on disk claimed there were none.
    """
    game, p1, p2 = _duel(active=1)
    p1.battlefield.append(Permanent(card=_CATALOG["Onulet"]))
    p2.hand = [_CATALOG["Lightning Bolt"]]

    game.cast_from_hand(1, "Lightning Bolt", target_player_index=0, target_permanent_index=0)
    game._settle()

    assert [p.card.name for p in p1.battlefield] == [], "it died"
    assert p1.life == 22, "and its controller gained the 2 life it promises"


@pytest.mark.cr("603.3")
def test_a_dies_trigger_that_deals_damage_fires_too():
    """Pitchburn Devils — a third shape (``deal_damage``), which is the point:
    the loop is over the card's dies-triggers now, not over the kinds this
    engine has previously met."""
    game, p1, p2 = _duel(active=1)
    p1.battlefield.append(Permanent(card=_M21["Pitchburn Devils"]))
    p2.hand = [_CATALOG["Lightning Bolt"]] * 3

    for _ in range(3):
        if not p1.battlefield:
            break
        game.cast_from_hand(1, "Lightning Bolt", target_player_index=0, target_permanent_index=0)
        game._settle()

    assert [p.card.name for p in p1.battlefield] == []
    assert p2.life == 17, "3 damage to any target, aimed at the opponent"


# ---------------------------------------------------------------------------
# When it goes on the stack
# ---------------------------------------------------------------------------


@pytest.mark.cr("601.2a", "601.2h", "603.3")
def test_a_trigger_fired_by_a_spells_cost_resolves_before_the_spell():
    """Village Rites sacrifices a creature to be cast; Havoc Jester answers.

    CR 601.2a has the spell on the stack before CR 601.2h pays for it, so the
    Jester's ability goes on the stack *above* Village Rites and resolves
    first. ``queue_from_hand`` is used rather than ``cast_from_hand`` because
    the latter settles the whole stack — the order is the thing under test.
    """
    game, p1, p2 = _duel()
    p1.battlefield += [
        _nosick(Permanent(card=_M21["Havoc Jester"])),
        _nosick(Permanent(card=_M21["Alpine Watchdog"])),
    ]
    p1.hand = [_M21["Village Rites"]]
    p1.library = [_M21["Swamp"]] * 4

    game.queue_from_hand(0, "Village Rites")

    assert [item.card.name for item in game.stack] == ["Village Rites", "Havoc Jester"], (
        "bottom-first: the trigger is above the spell that paid for it"
    )
    assert game.resolve_top_of_stack()
    assert p2.life == 19, "the ping resolved first"
    assert len(p1.hand) == 0, "and the spell has not drawn yet"


@pytest.mark.cr("602.2a", "602.2b", "603.3")
def test_a_trigger_fired_by_an_abilitys_cost_resolves_before_the_ability():
    """The same rule reached through CR 602.2b, which routes activation through
    601.2b–i. Witch's Cauldron eats a creature to pay for itself."""
    game, p1, p2 = _duel()
    p1.battlefield += [
        _nosick(Permanent(card=_M21["Havoc Jester"])),
        _nosick(Permanent(card=_M21["Witch's Cauldron"])),
        _nosick(Permanent(card=_M21["Alpine Watchdog"])),
    ]
    p1.library = [_M21["Swamp"]] * 4

    game.queue_permanent_ability(0, "Witch's Cauldron")

    assert [item.card.name for item in game.stack] == ["Witch's Cauldron", "Havoc Jester"]
    assert game.resolve_top_of_stack()
    assert p2.life == 19
    assert p1.life == 20, "the Cauldron's life gain has not happened yet"


@pytest.mark.cr("601.2h", "603.3", "700.4")
def test_a_dies_trigger_from_a_sacrificed_cost_also_waits_for_the_spell():
    """Both halves at once, and the reason the deferral had to live at the
    single-ability enqueue rather than at the batch: a dies-trigger is put on
    the stack from ``_permanent_to_graveyard``, one at a time, and a creature
    sacrificed to pay a cost dies exactly there."""
    game, p1, _p2 = _duel()
    p1.battlefield.append(Permanent(card=_CATALOG["Onulet"]))
    p1.hand = [_CATALOG["Sacrifice"]]

    game.queue_from_hand(0, "Sacrifice")

    assert [item.card.name for item in game.stack] == ["Sacrifice", "Onulet"]
    assert game.resolve_top_of_stack()
    assert p1.life == 22, "Onulet's life gain resolved first"
    assert p1.mana_pool["B"] == 0, "and Sacrifice has not resolved yet"


# ---------------------------------------------------------------------------
# CR 603.2d — how many times it triggers
# ---------------------------------------------------------------------------


def _invented(name: str, type_line: str, oracle_text: str) -> CardDefinition:
    """A card nobody printed, carrying a template the engine claims to read.

    The point of inventing one: a table keyed on printed text is only text-keyed
    if a card the pool has never seen works through it. A real card would pass
    equally well against a name-keyed reading.
    """
    return CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line=type_line,
        oracle_text=oracle_text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": name, "type_line": type_line,
                               "oracle_text": oracle_text},
    )


_DOUBLER_TEXT = (
    "If a triggered ability of another Beast you control triggers while you "
    "control three or more Beasts, that ability triggers an additional time."
)


def _beast(name: str) -> Permanent:
    return Permanent(card=_invented(name, "Creature — Beast", ""))


@pytest.mark.cr("603.2d")
def test_603_2d_an_ability_triggers_the_stated_number_of_extra_times():
    """603.2d: "determine how many times it should trigger, then that ability
    triggers that many times" — two stack objects, not one copied.

    The card is invented, so what is being tested is the printed template rather
    than a name: the subtype and the threshold are both different from the one
    card in the pool that prints this sentence.
    """
    game, p1, _ = _duel()
    doubler = Permanent(card=_invented("Beast Chorus", "Enchantment", _DOUBLER_TEXT))
    triggerer = _beast("First Beast")
    p1.battlefield = [doubler, triggerer, _beast("Second Beast"), _beast("Third Beast")]
    game._sync_control()

    game._enqueue_triggered_ability(
        controller_index=0, source_permanent=triggerer,
        instruction=OracleInstruction("gain_life", "", {"amount": 1}),
        effect_kind="triggered_life",
    )

    assert len(game.stack) == 2


@pytest.mark.cr("603.2d")
def test_603_2d_below_the_printed_threshold_it_triggers_once():
    """The same board one Beast short. Paired with the test above so the count
    is what is being read and not the presence of the enchantment."""
    game, p1, _ = _duel()
    doubler = Permanent(card=_invented("Beast Chorus", "Enchantment", _DOUBLER_TEXT))
    triggerer = _beast("First Beast")
    p1.battlefield = [doubler, triggerer, _beast("Second Beast")]
    game._sync_control()

    game._enqueue_triggered_ability(
        controller_index=0, source_permanent=triggerer,
        instruction=OracleInstruction("gain_life", "", {"amount": 1}),
        effect_kind="triggered_life",
    )

    assert len(game.stack) == 1


@pytest.mark.cr("603.2d", "603.7")
def test_603_2d_a_delayed_trigger_with_no_source_permanent_is_not_doubled():
    """603.2d: the effect "refers only to triggered abilities that object has,
    not to any delayed or reflexive triggered abilities". A delayed trigger has
    no source permanent to be an ability *of*, so it fires once."""
    game, p1, _ = _duel()
    doubler = Permanent(card=_invented("Beast Chorus", "Enchantment", _DOUBLER_TEXT))
    p1.battlefield = [doubler, _beast("A"), _beast("B"), _beast("C")]
    game._sync_control()

    game._enqueue_triggered_ability(
        controller_index=0, source_permanent=None,
        card=_invented("Delayed", "Instant", ""),
        instruction=OracleInstruction("gain_life", "", {"amount": 1}),
        effect_kind="triggered_life",
    )

    assert len(game.stack) == 1
    # A Beast on this same board doubles, so the board is over the threshold and
    # what the delayed trigger lacks is a source permanent to be an ability of.
    game._enqueue_triggered_ability(
        controller_index=0, source_permanent=p1.battlefield[1],
        instruction=OracleInstruction("gain_life", "", {"amount": 1}),
        effect_kind="triggered_life",
    )
    assert len(game.stack) == 3


@pytest.mark.cr("603.3", "503.1")
def test_603_3_an_ordinary_upkeep_trigger_goes_on_the_stack():
    """603.3: a triggered ability is put on the stack the next time a player
    would receive priority — an upkeep trigger included.

    The upkeep step used to dispatch every trigger through a registry keyed by
    (condition, instruction kind), whose entries are the interactive
    pay-or-consequence shapes; a trigger with no entry did nothing at all, and
    the lowering refused such cards rather than let them compile and be silent.
    An ordinary one now takes the ordinary route.

    The card is invented so this is the *route* being tested rather than the one
    pool card that reaches it.
    """
    game, p1, _ = _duel()
    source = Permanent(card=_invented(
        "Dawn Bell", "Enchantment",
        "At the beginning of your upkeep, draw a card.",
    ))
    p1.battlefield = [source]
    p1.library = [_invented("Somewhere", "Instant", "")]
    game._sync_control()

    game.resolve_upkeep(0)

    # The upkeep step opens its own priority window, so by the time it returns
    # the trigger has been on the stack and come off again — which the log
    # records and an empty stack does not distinguish from never firing.
    assert "Dawn Bell ability resolved" in game.log
    assert [c.name for c in p1.hand] == ["Somewhere"]


# ---------------------------------------------------------------------------
# What it targets, and when it chooses (CR 603.3d)
# ---------------------------------------------------------------------------


def _r32_invented_creature(name: str, oracle_text: str) -> CardDefinition:
    """A 2/2 nobody printed, carrying *oracle_text*."""
    raw = {
        "name": name, "type_line": "Creature - Test",
        "oracle_text": oracle_text, "power": "2", "toughness": "2",
    }
    return CardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line="Creature - Test",
        oracle_text=oracle_text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw=raw,
    )


_R32_UNBLOCKED_DESTROY = (
    "Whenever this creature attacks and isn't blocked, destroy target artifact "
    "defending player controls."
)


def _r32_unblocked_attack(game):
    """Attack with slot 0 and run to the moment blocks lock."""
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [0])[0]
    game._settle()
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0]
    game._settle()
    game.advance_combat_phase()


@pytest.mark.cr("603.3d", "601.2c", "509.1h")
def test_a_targeted_trigger_chooses_its_target_as_it_goes_on_the_stack():
    """CR 603.3d routes a trigger's remaining announcement through CR 601.2c,
    which is where targets are chosen — so the choice belongs to the moment the
    ability is put on the stack, not to its resolution.

    The card is invented, so what is tested is the route rather than the one
    pool card that reaches it. The narrowing matters twice over: "defending
    player controls" must exclude the *attacker's* own artifact, and the fire
    site used to stamp the attacking creature's own battlefield slot as the
    target — which on this board is exactly that artifact.
    """
    raider = _nosick(Permanent(card=_r32_invented_creature(
        "Sapper", _R32_UNBLOCKED_DESTROY,
    )))
    ours = Permanent(card=_invented("Our Engine", "Artifact", ""))
    theirs = Permanent(card=_invented("Their Engine", "Artifact", ""))
    game, p1, p2 = _duel()
    p1.battlefield = [raider, ours]
    p2.battlefield = [theirs]
    game.interactive_seats = {0}
    game._sync_control()

    _r32_unblocked_attack(game)

    pending = list(game.pending_choices_of("trigger_target"))
    assert len(pending) == 1, game.log
    assert [t["name"] for t in pending[0].data["targets"]] == ["Their Engine"]


@pytest.mark.cr("603.3d", "608.2")
def test_a_targeted_trigger_cannot_resolve_before_its_target_is_chosen():
    """The choice is part of *putting the ability on the stack*, so an ability
    that still owes it has not finished being announced and cannot resolve.

    This is the half a prompt armed mid-resolution already had: those record
    their stack object and hold it. An announcement prompt records the object
    too, and until it was read the ability resolved with no target at all —
    destroying nothing while the picker was still on screen.
    """
    raider = _nosick(Permanent(card=_r32_invented_creature(
        "Sapper", _R32_UNBLOCKED_DESTROY,
    )))
    theirs = Permanent(card=_invented("Their Engine", "Artifact", ""))
    game, p1, p2 = _duel()
    p1.battlefield = [raider]
    p2.battlefield = [theirs]
    game.interactive_seats = {0}
    game._sync_control()

    _r32_unblocked_attack(game)

    assert len(game.stack) == 1, game.log
    assert [p.card.name for p in p2.battlefield] == ["Their Engine"]

    pending = list(game.pending_choices_of("trigger_target"))[0]
    assert game.confirm_trigger_target(0, pending.data["targets"][0]["permanent_id"])
    game._settle()

    assert p2.battlefield == [], game.log


@pytest.mark.cr("603.3d")
def test_a_targeted_trigger_with_nothing_to_name_leaves_the_stack():
    """CR 603.3d's last sentence: "If a choice is required when the triggered
    ability goes on the stack but no legal choices can be made for it … the
    ability is simply removed from the stack." Not resolved into a no-op —
    removed, which is a different game state that nothing responds to.
    """
    raider = _nosick(Permanent(card=_r32_invented_creature(
        "Sapper", _R32_UNBLOCKED_DESTROY,
    )))
    ours = Permanent(card=_invented("Our Engine", "Artifact", ""))
    game, p1, p2 = _duel()
    p1.battlefield = [raider, ours]
    game.interactive_seats = {0}
    game._sync_control()

    _r32_unblocked_attack(game)

    assert not game.stack, game.log
    assert not list(game.pending_choices_of("trigger_target"))
    assert [p.card.name for p in p1.battlefield] == ["Sapper", "Our Engine"]


# ---------------------------------------------------------------------------
# 603.3d: a trigger whose printed noun phrase names "that player" (VIS w2g5)
# ---------------------------------------------------------------------------

from engine.card_loader import load_cards as _w2g5_load
from engine.card_loader import manifest_set_paths as _w2g5_paths
from engine.game_types import StackItem
from engine.events import emit as _w2g5_emit


def _w2g5_pool():
    return {c.name: c for c in _w2g5_load(_w2g5_paths(include_measured=True))}


def _w2g5_card(name, type_line):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "1", "toughness": "1"},
    )


def _w2g5_cat_board(seats, *, interactive):
    """Feline Sovereign under seat 0, one artifact per other seat named."""
    pool = _w2g5_pool()
    players = [PlayerState(name=f"P{i + 1}") for i in range(seats)]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.active_player_index = 0
    if interactive:
        game.interactive_seats = {0}
    cat = Permanent(card=pool["Feline Sovereign"])
    cat.permanent_id = 1
    cat.metadata["base_controller_index"] = 0
    players[0].battlefield.append(cat)
    return game, players, cat


@pytest.mark.cr("603.3d", "601.2c")
def test_603_3d_a_trigger_naming_that_player_offers_only_that_players_board():
    """"Destroy up to one target artifact or enchantment **that player**
    controls" (Feline Sovereign).

    The seat is one the *event* picked and the fire site froze (CR 603.10), so
    the picker has to be given it. Without it the narrowing cannot be tested at
    all and the ability offers nothing — which reads as "no legal target" and
    takes the ability off the stack.
    """
    game, players, cat = _w2g5_cat_board(3, interactive=True)
    for seat, name in ((1, "Their Bauble"), (2, "Third Bauble")):
        perm = Permanent(card=_w2g5_card(name, "Artifact"))
        perm.permanent_id = 10 + seat
        perm.metadata["base_controller_index"] = seat
        players[seat].battlefield.append(perm)

    _w2g5_emit(
        game, "one_or_more_deal_combat_damage",
        subject=cat, source_seat=0, defending_player_index=2,
    )

    (offer,) = game.pending_choices
    assert offer.kind == "trigger_target"
    assert [t["name"] for t in offer.data["targets"]] == ["Third Bauble"]


@pytest.mark.cr("603.3d", "601.2c")
def test_603_3d_the_controller_chooses_which_of_several_legal_targets():
    """Two legal targets means a decision, and the ability waits for it.

    This is the half a fallback hides: with the picker declining, the handler
    took the first permanent on the board that matched — a legal target nobody
    chose, and never the second one.
    """
    game, players, cat = _w2g5_cat_board(2, interactive=True)
    for index, name in enumerate(("Cheap Bauble", "Precious Relic")):
        perm = Permanent(card=_w2g5_card(name, "Artifact"))
        perm.permanent_id = 20 + index
        perm.metadata["base_controller_index"] = 1
        players[1].battlefield.append(perm)

    _w2g5_emit(
        game, "one_or_more_deal_combat_damage",
        subject=cat, source_seat=0, defending_player_index=1,
    )

    (offer,) = game.pending_choices
    assert [t["name"] for t in offer.data["targets"]] == [
        "Cheap Bauble", "Precious Relic",
    ]
    # Nothing has been destroyed while the decision is owed.
    assert [p.card.name for p in players[1].battlefield] == [
        "Cheap Bauble", "Precious Relic",
    ]

    relic = next(
        t["permanent_id"] for t in offer.data["targets"]
        if t["name"] == "Precious Relic"
    )
    game.confirm_trigger_target(0, relic)
    game.resolve_stack(pause_for_choices=True)

    assert [p.card.name for p in players[1].battlefield] == ["Cheap Bauble"]


@pytest.mark.cr("603.10", "109.5")
def test_603_10_the_frozen_seat_is_read_through_one_key_list():
    """The picker and the resolution must name the same player.

    ``_that_player_seat`` reads ``handlers/_common._THAT_PLAYER_CONTEXT_KEYS``
    — the tuple ``frozen_that_player_seat`` reads at resolution — so a second
    copy cannot drift into offering one board and acting on another.
    """
    from engine.handlers._common import _THAT_PLAYER_CONTEXT_KEYS

    game, players, cat = _w2g5_cat_board(2, interactive=False)
    item = StackItem(
        card=cat.card, caster_index=0, target_player_index=None,
        target_permanent_index=None, x_value=None,
        trigger_context={"defending_player_index": 1},
    )

    assert "defending_player_index" in _THAT_PLAYER_CONTEXT_KEYS
    assert game._that_player_seat(item) == 1
    assert game._that_player_seat(
        StackItem(
            card=cat.card, caster_index=0, target_player_index=None,
            target_permanent_index=None, x_value=None, trigger_context={},
        )
    ) is None


# ---------------------------------------------------------------------------
# W4G3 - CR 603.3d/601.2c: a triggered ability's *player* target
#
# `_choose_trigger_targets` announced object targets and nothing else, so a
# trigger printing "target player" or "target opponent" announced nothing and
# the resolution fell through to `_default_opposing_seat` - the first living
# opponent. Right in a duel by coincidence, because there is only one of those;
# at three seats the engine chose for the player, and CR 601.2c says the
# ability's controller does.
# ---------------------------------------------------------------------------

import pytest as _w4g3_pytest

from engine import Game as _W4G3Game, PlayerState as _W4G3Player, load_cards as _w4g3_load
from engine.card_loader import manifest_set_path as _w4g3_path
from engine.models import Permanent as _W4G3Permanent

_W4G3_POOLS: dict = {}


def _w4g3_card(code: str, name: str):
    pool = _W4G3_POOLS.get(code)
    if pool is None:
        pool = {c.name: c for c in _w4g3_load(_w4g3_path(code, include_measured=True))}
        _W4G3_POOLS[code] = pool
    return pool[name]


def _w4g3_table(seats: int, *, interactive: bool):
    game = _W4G3Game(players=[_W4G3Player(name=f"P{i + 1}") for i in range(seats)])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    if interactive:
        game.interactive_seats = {0}
    return game


def _w4g3_put(game, seat: int, card):
    perm = _W4G3Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(perm)
    game._sync_control()
    return perm


def _w4g3_fire(game, perm, *, index: int = 0):
    """Put one of *perm*'s triggered abilities on the stack, targets unbound.

    Straight through ``_enqueue_triggered_ability`` rather than through a fire
    site, because the subject is what happens *as the ability goes on the
    stack* and every fire site funnels into the same ``_stack_push``.
    """
    from engine.oracle import compile_card_oracle

    abilities = [
        ability for ability in compile_card_oracle(perm.card).triggered_abilities
        if ability.instruction is not None and ability.supported
    ]
    ability = abilities[index]
    game._enqueue_triggered_ability(
        controller_index=0, source_permanent=perm, card=perm.card,
        instruction=ability.instruction, effect_kind=ability.effect_kind,
    )
    return ability


def _w4g3_library(player, card, count: int) -> None:
    player.library.extend([card] * count)


@_w4g3_pytest.mark.cr("603.3d", "601.2c")
def test_603_3d_a_trigger_naming_target_opponent_announces_a_seat():
    """"Whenever you draw a card, **target opponent** mills two cards."
    (Teferi's Tutelage, shipped.)

    Three seats, because two cannot tell the two readings apart: with one
    opponent the seat nobody chose and the seat the card names are the same
    player. With two, the ability milled P2 every time and P3 never - a legal
    target, chosen by the engine.
    """
    game = _w4g3_table(3, interactive=True)
    tutelage = _w4g3_put(game, 0, _w4g3_card("M21", "Teferi's Tutelage"))
    filler = _w4g3_card("LEA", "Mountain")
    for seat in (1, 2):
        _w4g3_library(game.players[seat], filler, 5)

    _w4g3_fire(game, tutelage, index=1)

    (offer,) = game.pending_choices
    assert offer.kind == "trigger_target"
    assert offer.player_index == 0
    assert [(t["kind"], t["seat"]) for t in offer.data["targets"]] == [
        ("player", 1), ("player", 2),
    ]

    assert game.confirm_trigger_target(0, seat=2)
    game.resolve_stack(pause_for_choices=True)

    assert len(game.players[2].graveyard) == 2, game.log
    assert game.players[1].graveyard == [], "the opponent the trigger did not name"


@_w4g3_pytest.mark.cr("603.3d", "117.3b", "608.2")
def test_603_3d_the_ability_waits_on_the_stack_while_the_seat_is_owed():
    """The choice is part of putting the ability on the stack, so nothing of the
    ability has happened while it is owed - and nobody receives priority."""
    game = _w4g3_table(3, interactive=True)
    tutelage = _w4g3_put(game, 0, _w4g3_card("M21", "Teferi's Tutelage"))
    for seat in (1, 2):
        _w4g3_library(game.players[seat], _w4g3_card("LEA", "Mountain"), 5)

    _w4g3_fire(game, tutelage, index=1)

    assert [item.card.name for item in game.stack] == ["Teferi's Tutelage"]
    waiting = game.waiting_prompt()
    assert waiting is not None and waiting.kind == "trigger_target"
    assert game.players[1].graveyard == [] and game.players[2].graveyard == []


@_w4g3_pytest.mark.cr("603.3d", "601.2c")
def test_603_3d_a_seat_nobody_is_asked_lands_where_it_landed_before():
    """The default a non-interactive seat takes is not a policy: it is the seat
    ``_default_opposing_seat`` would have handed the resolution out of
    ``target_player_index`` being None.

    That equality is what makes announcing the target a change to what a
    *player* is asked and to nothing else - headless play, AI play and every
    duel resolve exactly where they resolved before.
    """
    for seats in (2, 3):
        game = _w4g3_table(seats, interactive=False)
        tutelage = _w4g3_put(game, 0, _w4g3_card("M21", "Teferi's Tutelage"))
        for seat in range(1, seats):
            _w4g3_library(game.players[seat], _w4g3_card("LEA", "Mountain"), 5)

        _w4g3_fire(game, tutelage, index=1)

        assert game.pending_choices == [], "nothing queues for a seat nobody asks"
        (item,) = game.stack
        assert item.target_player_index == game._default_opposing_seat(0)


@_w4g3_pytest.mark.cr("603.3c", "603.3d")
def test_603_3c_a_trigger_with_no_legal_seat_leaves_the_stack():
    """"…deals X damage to **target opponent previously dealt damage by it**"
    (Diseased Vermin).

    The narrowing is a record on the source, and with nobody in it there is no
    legal target - so the ability is taken back off the stack rather than
    resolving into damage aimed at whichever opponent came first, which is what
    it did while nothing announced.
    """
    game = _w4g3_table(3, interactive=True)
    vermin = _w4g3_put(game, 0, _w4g3_card("ALL", "Diseased Vermin"))

    _w4g3_fire(game, vermin, index=1)

    assert game.stack == []
    assert game.pending_choices == []
    assert any("603.3c" in line for line in game.log), game.log
    assert [player.life for player in game.players] == [20, 20, 20]


@_w4g3_pytest.mark.cr("603.3d", "603.10")
def test_603_3d_a_seat_the_firing_event_named_is_not_asked_for():
    """"Whenever this creature deals damage to a player, **that player**
    discards a card." (Abyssal Specter.)

    The compiler's kind table answers ``{"kind": "player"}`` for the discard
    whatever the printed line said, so the spec alone cannot tell this from
    "target player discards a card". The printed phrase can, and does: the seat
    here is the one the *event* picked (CR 603.10), and a prompt in front of it
    would be a question whose answer nothing reads.
    """
    game = _w4g3_table(3, interactive=True)
    specter = _w4g3_put(game, 0, _w4g3_card("ICE", "Abyssal Specter"))

    _w4g3_fire(game, specter, index=0)

    assert game.pending_choices == []


@_w4g3_pytest.mark.cr("601.2c", "115.4")
def test_601_2c_a_kind_table_default_never_widens_the_printed_phrase():
    """"Whenever you gain life, **target opponent** loses that much life."
    (Vito, Thorn of the Dusk Rose.)

    The same gate from the other side. Vito's lowering keeps no target
    description, so the spec is the kind table's ``{"kind": "player"}`` - every
    seat, the caster's own included. Announcing on that spec would have offered
    Vito's controller as a legal target for a phrase that says "opponent", so
    the printed evidence is required and Vito keeps the standing seat.
    """
    from engine.targeting import derive_instruction_spec

    game = _w4g3_table(3, interactive=True)
    vito = _w4g3_put(game, 0, _w4g3_card("M21", "Vito, Thorn of the Dusk Rose"))
    ability = _w4g3_fire(game, vito, index=0)

    spec = derive_instruction_spec([ability.instruction])
    assert spec == {"kind": "player"}, "the widened spec this gate exists for"
    assert game.pending_choices == []


@_w4g3_pytest.mark.cr("115.4", "601.2c")
def test_115_4_any_target_on_a_trigger_offers_faces_and_creatures_alike():
    """"When this creature dies, it deals 3 damage to **any target**."
    (Pitchburn Devils.)

    CR 115.4's target is a creature, a player or a planeswalker, and the
    trigger offered none of them: the resolution dealt to the first living
    opponent's face and a creature could never be chosen at all.

    The non-interactive answer is still that face, which is the equivalence
    half - what changed is that a player is now asked.
    """
    game = _w4g3_table(3, interactive=True)
    devils = _w4g3_put(game, 0, _w4g3_card("M21", "Pitchburn Devils"))
    bear = _w4g3_put(game, 2, _w4g3_card("LEA", "Grizzly Bears"))

    _w4g3_fire(game, devils, index=0)

    (offer,) = game.pending_choices
    kinds = {(t["kind"], t.get("seat")) for t in offer.data["targets"]}
    assert ("player", 0) in kinds and ("player", 1) in kinds and ("player", 2) in kinds
    assert ("permanent", 2) in kinds

    chosen = next(
        t["permanent_id"] for t in offer.data["targets"]
        if t["kind"] == "permanent" and t["name"] == "Grizzly Bears"
    )
    assert game.confirm_trigger_target(0, chosen)
    game.resolve_stack(pause_for_choices=True)

    assert bear.damage_marked == 3, game.log
    assert [player.life for player in game.players] == [20, 20, 20], (
        "the face it would have hit unasked is untouched"
    )


@_w4g3_pytest.mark.cr("115.4", "601.2c")
def test_115_4_the_unasked_answer_for_any_target_is_the_face_it_always_hit():
    """The same card with nobody to ask: the standing opponent's face, exactly
    as before the announcement existed."""
    game = _w4g3_table(3, interactive=False)
    devils = _w4g3_put(game, 0, _w4g3_card("M21", "Pitchburn Devils"))
    _w4g3_put(game, 2, _w4g3_card("LEA", "Grizzly Bears"))

    _w4g3_fire(game, devils, index=0)
    game.resolve_stack(pause_for_choices=True)

    assert [player.life for player in game.players] == [20, 17, 20], game.log


@_w4g3_pytest.mark.cr("601.2c", "603.3d")
def test_601_2c_a_seat_the_picker_never_offered_is_refused():
    """Targets are chosen once, out of the list that was offered - so an answer
    naming a seat that was not on it leaves the prompt owed rather than being
    quietly performed."""
    game = _w4g3_table(3, interactive=True)
    tutelage = _w4g3_put(game, 0, _w4g3_card("M21", "Teferi's Tutelage"))
    for seat in (1, 2):
        _w4g3_library(game.players[seat], _w4g3_card("LEA", "Mountain"), 5)

    _w4g3_fire(game, tutelage, index=1)

    assert not game.confirm_trigger_target(0, seat=0), "its own controller"
    assert not game.confirm_trigger_target(0, seat=7), "and no seat at all"
    assert len(game.pending_choices) == 1


@_w4g3_pytest.mark.cr("113.3c", "115.1a", "603.3d")
def test_113_3c_a_ban_on_spells_and_activated_abilities_spares_a_trigger():
    """"…players and permanents can't be the targets of spells or activated
    abilities." (Peace Talks.)

    A triggered ability is neither (CR 113.3c), so the ban does not reach its
    announcement. Read as a spell's, the enumerator returned nothing and
    CR 603.3d's "no legal choices" would have taken **every** announcing trigger
    off the stack for two turns - a strictly larger card than the one printed.
    """
    game = _w4g3_table(3, interactive=True)
    tutelage = _w4g3_put(game, 0, _w4g3_card("M21", "Teferi's Tutelage"))
    for seat in (1, 2):
        _w4g3_library(game.players[seat], _w4g3_card("LEA", "Mountain"), 5)
    game.targeting_bans.append({"remaining_turns": 2, "source_name": "Peace Talks"})

    _w4g3_fire(game, tutelage, index=1)

    assert [item.card.name for item in game.stack] == ["Teferi's Tutelage"]
    (offer,) = game.pending_choices
    assert [t["seat"] for t in offer.data["targets"]] == [1, 2]


@_w4g3_pytest.mark.cr("603.3d", "115.4")
def test_603_3d_a_seat_the_fire_site_bound_stays_the_fire_site_s():
    """"When a spell or ability an opponent controls causes you to discard this
    card, it deals 4 damage to **any target**." (Guerrilla Tactics.)

    The boundary of this round, written down rather than assumed. The discard
    seam stamps the causing seat onto the trigger, so the ability arrives on the
    stack with ``target_player_index`` already set - and the announcement steps
    aside, exactly as it does for an object the fire site bound.

    That is CR 601.2c's choice made by the engine rather than by the player, and
    it is a *pre-existing* approximation this round leaves where it found it:
    announcing here would move the damage off the discarder and onto
    ``_default_opposing_seat``, which is a live behaviour change nothing in this
    round pays for. A fire site that names a seat for a phrase that says
    "any target" is its own question.
    """
    game = _w4g3_table(3, interactive=True)
    tactics = _w4g3_card("ALL", "Guerrilla Tactics")
    game.players[0].hand.append(tactics)
    game.resolving_seats.append(2)
    try:
        game.take_card_from_hand(game.players[0], tactics)
        game._announce_discard_triggers(game.players[0], tactics)
    finally:
        game.resolving_seats.pop()

    assert game.pending_choices == [], "the fire site made the choice"
    (item,) = game.stack
    assert item.target_player_index == 2
    game.resolve_stack(pause_for_choices=True)
    assert [player.life for player in game.players] == [20, 20, 16], game.log
