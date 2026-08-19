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
