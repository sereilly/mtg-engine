"""CR 603.3 — every ability whose trigger condition is met triggers.

Two things are pinned here.

The first is that a permanent with more than one matching trigger fires all of
them. The scan used to stop at the first match per permanent, so a card with
two upkeep triggers would silently fire only one. No card in the current pool
has that shape, which is exactly why it needs a synthetic test: the bug was
invisible and would have surfaced as a mystery when the first such card
arrived.

The second is the event bus (``engine/events.py``): announcing an event must
find matching triggers wherever they are, without the caller knowing which
cards exist.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.events import Event, collect, emit
from engine.models import CardDefinition, Permanent
from engine.trigger_utils import iter_triggered_abilities


def _card(name: str, oracle_text: str, type_line: str = "Creature — Test") -> CardDefinition:
    raw: dict = {"name": name, "type_line": type_line}
    if "Creature" in type_line:
        raw["power"], raw["toughness"] = "2", "2"
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text=oracle_text,
        colors=(), color_identity=(), keywords=(), produced_mana=(), raw=raw,
        power=raw.get("power"), toughness=raw.get("toughness"),
    )


def _game(*permanents: Permanent) -> tuple[Game, PlayerState, PlayerState]:
    owner = PlayerState(name="P1", battlefield=list(permanents), life=20)
    opponent = PlayerState(name="P2", life=20)
    game = Game(players=[owner, opponent])
    game.enforce_mana_costs = False
    return game, owner, opponent


@pytest.mark.cr("603.3")
def test_a_permanent_with_two_matching_triggers_fires_both():
    twice = Permanent(card=_card(
        "Twice-Triggered Thing",
        "At the beginning of your upkeep, this creature deals 1 damage to you.\n"
        "At the beginning of your upkeep, this creature deals 2 damage to you.",
    ))
    game, owner, _ = _game(twice)

    matches = list(
        iter_triggered_abilities(game, condition_kinds={"upkeep_self"})
    )
    assert len(matches) == 2, "both upkeep triggers must be found, not just the first"


@pytest.mark.cr("603.3")
def test_first_match_only_is_opt_in():
    """The capped scan still exists for presence checks — it just is not the
    default any more."""
    twice = Permanent(card=_card(
        "Twice-Triggered Thing",
        "At the beginning of your upkeep, this creature deals 1 damage to you.\n"
        "At the beginning of your upkeep, this creature deals 2 damage to you.",
    ))
    game, _, _ = _game(twice)

    capped = list(
        iter_triggered_abilities(
            game, condition_kinds={"upkeep_self"}, first_match_only=True
        )
    )
    assert len(capped) == 1


@pytest.mark.cr("603.3")
def test_emit_puts_every_matching_trigger_on_the_stack():
    one = Permanent(card=_card(
        "Pinger", "At the beginning of your upkeep, this creature deals 1 damage to you."
    ))
    two = Permanent(card=_card(
        "Other Pinger", "At the beginning of your upkeep, this creature deals 2 damage to you."
    ))
    game, _, _ = _game(one, two)

    fired = emit(game, "upkeep_self")
    assert fired == 2
    assert len(game.stack) == 2


@pytest.mark.cr("603.3")
def test_emit_finds_nothing_when_no_trigger_matches():
    plain = Permanent(card=_card("Bear", ""))
    game, _, _ = _game(plain)
    assert emit(game, "upkeep_self") == 0
    assert game.stack == []


@pytest.mark.cr("603.2")
def test_collect_reports_the_controller_of_each_trigger():
    """Trigger events carry the controller index, which is what
    ``_enqueue_triggered_batch`` orders by (CR 603.3b, APNAP)."""
    mine = Permanent(card=_card(
        "Mine", "At the beginning of your upkeep, this creature deals 1 damage to you."
    ))
    theirs = Permanent(card=_card(
        "Theirs", "At the beginning of your upkeep, this creature deals 1 damage to you."
    ))
    owner = PlayerState(name="P1", battlefield=[mine], life=20)
    opponent = PlayerState(name="P2", battlefield=[theirs], life=20)
    game = Game(players=[owner, opponent])

    events = collect(game, Event("upkeep_self"))
    assert {event["controller_index"] for event in events} == {0, 1}


@pytest.mark.cr("603.3")
def test_emit_can_be_scoped_to_one_players_permanents():
    mine = Permanent(card=_card(
        "Mine", "At the beginning of your upkeep, this creature deals 1 damage to you."
    ))
    theirs = Permanent(card=_card(
        "Theirs", "At the beginning of your upkeep, this creature deals 1 damage to you."
    ))
    owner = PlayerState(name="P1", battlefield=[mine], life=20)
    opponent = PlayerState(name="P2", battlefield=[theirs], life=20)
    game = Game(players=[owner, opponent])

    events = collect(game, Event("upkeep_self", players=[owner]))
    assert [event["source_permanent"] for event in events] == [mine]


@pytest.mark.cr("603.3", "701.26a")
def test_become_tapped_announces_the_event_on_the_bus():
    """``Game.become_tapped`` is the single "becomes tapped" transition, and it
    announces the event rather than calling a name-keyed hook.

    Written with a synthetic card so it tests the wiring, not Lifetap: any card
    whose text compiles to this condition fires here, which is the property that
    made the hook deletable."""
    watcher = Permanent(card=_card(
        "Watcher",
        "Whenever a Forest an opponent controls becomes tapped, you gain 1 life.",
        type_line="Enchantment",
    ))
    forest = Permanent(card=_card("Forest", "", type_line="Basic Land — Forest"))
    owner = PlayerState(name="P1", battlefield=[watcher], life=20)
    opponent = PlayerState(name="P2", battlefield=[forest], life=20)
    game = Game(players=[owner, opponent])

    assert game.become_tapped(forest) is True
    assert len(game.stack) == 1

    game.resolve_stack()
    assert owner.life == 21


@pytest.mark.cr("603.3")
def test_a_becomes_tapped_trigger_ignores_a_permanent_its_filter_excludes():
    """The condition's own payload decides applicability — the type and the
    controller scope both. Without the filter every such card would fire on
    every tap on the board."""
    watcher = Permanent(card=_card(
        "Watcher",
        "Whenever a Forest an opponent controls becomes tapped, you gain 1 life.",
        type_line="Enchantment",
    ))
    own_forest = Permanent(card=_card("Forest", "", type_line="Basic Land — Forest"))
    their_island = Permanent(card=_card("Island", "", type_line="Basic Land — Island"))
    owner = PlayerState(name="P1", battlefield=[watcher, own_forest], life=20)
    opponent = PlayerState(name="P2", battlefield=[their_island], life=20)
    game = Game(players=[owner, opponent])

    game.become_tapped(own_forest)     # right type, wrong controller
    game.become_tapped(their_island)   # right controller, wrong type

    assert game.stack == []


@pytest.mark.cr("603.2")
def test_event_payload_reaches_the_trigger_as_context():
    pinger = Permanent(card=_card(
        "Pinger", "At the beginning of your upkeep, this creature deals 1 damage to you."
    ))
    game, _, _ = _game(pinger)

    events = collect(game, Event("upkeep_self", payload={"amount": 7}))
    assert events[0]["trigger_context"] == {"amount": 7}


# --- CR 119.9 — "whenever you gain life" is an event, not a state read -------


_VITO_TEXT = "Whenever you gain life, target opponent loses that much life."


@pytest.mark.cr("119.9", "109.5")
def test_a_life_gain_trigger_fires_for_its_own_controller_only():
    """"You" on a triggered ability is the ability's controller (CR 109.5), so
    the game-wide announcement has to be narrowed by the trigger's own word —
    an opponent's life gain must leave it silent."""
    mine = Permanent(card=_card("Drainer", _VITO_TEXT))
    theirs = Permanent(card=_card("Their Drainer", _VITO_TEXT))
    owner = PlayerState(name="P1", battlefield=[mine], life=20)
    opponent = PlayerState(name="P2", battlefield=[theirs], life=20)
    game = Game(players=[owner, opponent])

    game._gain_life(owner, 2, "a test")
    game._settle()

    assert owner.life == 22
    assert opponent.life == 18, "only the gaining seat's own trigger fired"


@pytest.mark.cr("119.9")
def test_a_gain_of_zero_life_is_not_a_life_gain_event():
    """CR 119.9 in as many words: "If a player gains 0 life, no life gain event
    has occurred, and these abilities won't trigger.\""""
    drainer = Permanent(card=_card("Drainer", _VITO_TEXT))
    game, owner, opponent = _game(drainer)

    game._gain_life(owner, 0, "a test")

    assert game.stack == []
    assert (owner.life, opponent.life) == (20, 20)


@pytest.mark.cr("119.9", "614.1")
def test_the_announced_amount_is_the_life_that_arrived():
    """The event is emitted after CR 614's replacements have had the number, so
    a trigger reading "that much" reads what actually happened rather than what
    the source set out to do."""
    drainer = Permanent(card=_card("Drainer", _VITO_TEXT))
    game, owner, opponent = _game(drainer)

    game._gain_life(owner, 5, "a test")
    game._settle()

    assert owner.life == 25
    assert opponent.life == 15


@pytest.mark.cr("115.1d", "102.3")
def test_an_unchosen_trigger_target_is_never_the_abilitys_own_controller():
    """This engine picks a trigger's target at its fire site or not at all, a
    standing approximation of CR 603.3d. Where nothing chose, the seat it falls
    back to still has to be a legal one: "target opponent" is by definition not
    the ability's controller (CR 102.3), and the old `1 - caster_index` answered
    the *caster* at seat 2 of a three-handed game."""
    drainer = Permanent(card=_card("Drainer", _VITO_TEXT))
    seats = [
        PlayerState(name="P1", life=20),
        PlayerState(name="P2", life=20),
        PlayerState(name="P3", battlefield=[drainer], life=20),
    ]
    game = Game(players=seats)

    game._gain_life(seats[2], 3, "a test")
    game._settle()

    assert seats[2].life == 23, "the drainer's controller is not its own target"
    assert [seats[0].life, seats[1].life] == [17, 20]


# --- A trigger whose subject is an object filter ----------------------------


_WATCHER = (
    "Whenever a creature you control with flying attacks, you gain 1 life."
)


@pytest.mark.cr("109.5")
def test_a_subject_filtered_trigger_scopes_you_to_its_own_controller():
    """"A creature **you control**" is the ability's controller (CR 109.5). The
    event is announced game-wide for every attacker, so this narrowing is the
    only thing keeping an opponent's flier from feeding the watcher."""
    watcher = Permanent(card=_card("Watcher", _WATCHER, type_line="Enchantment"))
    mine = Permanent(card=_card("Mine", "Flying"))
    theirs = Permanent(card=_card("Theirs", "Flying"))
    owner = PlayerState(name="P1", battlefield=[watcher, mine], life=20)
    opponent = PlayerState(name="P2", battlefield=[theirs], life=20)
    game = Game(players=[owner, opponent])

    events = collect(
        game, Event("matching_creature_attacks", subject=mine)
    )
    assert len(events) == 1, "the controller's own flier is in the set"

    assert collect(
        game, Event("matching_creature_attacks", subject=theirs)
    ) == [], "an opponent's flier is not"


@pytest.mark.cr("603.2")
def test_a_subject_filter_asks_the_layers_rather_than_the_printed_card():
    """A creature *granted* flying answers a flying-narrowed trigger exactly as
    a printed one does — the keyword is asked of layer 6, like every other
    keyword read in the engine."""
    from engine.keywords import grant_keyword

    watcher = Permanent(card=_card("Watcher", _WATCHER, type_line="Enchantment"))
    grounded = Permanent(card=_card("Grounded", ""))
    game, _, _ = _game(watcher, grounded)

    assert collect(game, Event("matching_creature_attacks", subject=grounded)) == []
    grant_keyword(grounded, "flying", until_eot=True)
    assert len(collect(game, Event("matching_creature_attacks", subject=grounded))) == 1


@pytest.mark.cr("603.2")
def test_a_subject_the_engine_cannot_test_refuses_the_whole_condition():
    """The gate that makes the rest safe. A narrowing the dispatcher cannot
    apply would make the trigger fire on a strictly larger set than the card
    prints, so the *condition* refuses at compile time — the card is honestly
    unsupported instead."""
    from engine.oracle import _parse_trigger_condition, normalize_creature_line

    readable, _ = _parse_trigger_condition(normalize_creature_line(
        "Whenever a creature you control with flying attacks, you gain 1 life."
    ))
    assert readable is not None
    assert readable.payload["attacker_filter"]["with_keywords"] == ["flying"]

    unreadable, _ = _parse_trigger_condition(normalize_creature_line(
        "Whenever a creature card in your graveyard attacks, you gain 1 life."
    ))
    assert unreadable is None, "a zone-scoped subject has no dispatcher, so no condition"


# ---------------------------------------------------------------------------
# 603.8 — state triggers
#
# A state trigger watches a *condition*, not an event, so it has no call site
# to hang on: it is checked in the state-based-action sweep, beside the record
# every path already feeds. Mazemind Tome ("When there are four or more page
# counters on this artifact, exile it") is the pool's example.
# ---------------------------------------------------------------------------

@pytest.mark.cr("603.8")
def test_603_8_a_state_trigger_fires_as_soon_as_the_condition_is_true(set_pool):
    """A state trigger triggers as soon as the game state matches.

    Nothing "happens" to make it fire — no counter is put on during this call;
    the sweep simply finds the condition already true and announces it.
    """
    from engine.named_counters import add_counters

    tome = Permanent(card=set_pool("M21")["Mazemind Tome"])
    p1 = PlayerState(name="P1", battlefield=[tome])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    add_counters(tome, "page", 4)

    game.check_state_based_actions()

    assert tome.metadata.get("_state_trigger_announced")


@pytest.mark.cr("603.8")
def test_603_8_the_condition_being_false_leaves_the_trigger_silent(set_pool):
    """Below the threshold the state does not match, so nothing triggers —
    the sweep runs constantly and must not announce on every pass."""
    from engine.named_counters import add_counters

    tome = Permanent(card=set_pool("M21")["Mazemind Tome"])
    p1 = PlayerState(name="P1", battlefield=[tome])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    add_counters(tome, "page", 3)

    game.check_state_based_actions()

    assert not tome.metadata.get("_state_trigger_announced")


@pytest.mark.cr("603.8")
def test_603_8_a_state_trigger_announces_once_while_the_state_holds(set_pool):
    """It fires once, not once per check.

    The sweep runs at every priority check, so a state trigger that announced
    each time would put an unbounded number of copies on the stack. The
    permanent remembers that it announced, and forgets when the state stops
    matching.
    """
    from engine.named_counters import add_counters

    tome = Permanent(card=set_pool("M21")["Mazemind Tome"])
    p1 = PlayerState(name="P1", battlefield=[tome])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    add_counters(tome, "page", 4)

    game.check_state_based_actions()
    announced_after_first = set(tome.metadata.get("_state_trigger_announced") or ())
    game.check_state_based_actions()
    game.check_state_based_actions()

    assert set(tome.metadata.get("_state_trigger_announced") or ()) == announced_after_first
    assert announced_after_first == {("page", 4)}


# ---------------------------------------------------------------------------
# 603.12 — reflexive triggered abilities
#
# "…you may pay {1}. When you do, you may tap or untap target creature."
# (Tolarian Kraken.) The "when you do" half is a *separate* ability created by
# the payment, not a second half of the first one — which is why it chooses its
# own targets and is kept under its own key rather than merged into the
# then-branch.
# ---------------------------------------------------------------------------

@pytest.mark.cr("603.12")
def test_603_12_the_when_you_do_clause_is_a_separate_ability(set_pool):
    """A reflexive trigger is kept apart from the action that creates it.

    The optional payment lowers to a ``may`` carrying its cost and a
    ``reflexive`` payload; the reflexive half is not folded into ``then``,
    because a ``then`` branch has no targets of its own to choose.
    """
    from engine.oracle import compile_card_oracle

    kraken = set_pool("M21")["Tolarian Kraken"]
    program = compile_card_oracle(kraken)

    trigger = next(t for t in program.triggered_abilities
                   if t.condition.kind == "draws_card")
    payload = trigger.instruction.payload

    assert trigger.instruction.kind == "may"
    assert payload["cost"] == {"generic": 1}
    assert payload.get("reflexive"), "the reflexive ability was not kept separate"
    assert "then" not in payload


@pytest.mark.cr("603.12")
def test_603_12_the_reflexive_ability_carries_its_own_effect(set_pool):
    """The reflexive half holds the effect that happens "when you do" — here
    the tap-or-untap — so the payment creates a real second ability rather than
    an extra step of the first."""
    from engine.oracle import compile_card_oracle

    kraken = set_pool("M21")["Tolarian Kraken"]
    program = compile_card_oracle(kraken)
    trigger = next(t for t in program.triggered_abilities
                   if t.condition.kind == "draws_card")

    reflexive = trigger.instruction.payload["reflexive"]

    assert reflexive
    # "you *may* tap or untap": the reflexive ability is itself an optional
    # action, so its effect sits one level down in that offer's action list.
    inner = reflexive[0]
    assert inner.kind == "may"
    assert [step.kind for step in inner.payload["action"]] == ["tap_or_untap_target"]
