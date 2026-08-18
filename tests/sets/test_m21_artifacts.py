"""Core Set 2021 (M21) artifacts.

M21 is a *measured* set, mid-implementation: cards land here with the round that
buys them (tests/sets/README.md, SET_PLAYBOOK.md Phase 3), and the pool resolves
through ``set_pool("M21")`` even though the set is not shipped — reading a card
file is not shipping it. The round each section names is written up in
ROADMAP.md; a round's cards are split across these files by the printed type of
the card each test is about.
"""

from __future__ import annotations

from engine import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


# --- Exiling a whole zone ---------------------------------------------------


def test_tormods_crypt_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Tormod's Crypt"])
    assert program.supported, program.reason


def test_tormods_crypt_exiles_the_whole_graveyard_and_sacrifices_itself(set_pool):
    """A whole *zone*, not a card in one — so there is nothing to filter and
    nothing to target among the cards. A graveyard is its owner's (CR 404.1) and
    so is the exile zone, which is why no CR 400.3 lookup is needed."""
    pool = set_pool("M21")
    crypt = Permanent(card=pool["Tormod's Crypt"])
    p1 = PlayerState(name="P1", battlefield=[crypt])
    p2 = PlayerState(
        name="P2",
        graveyard=[pool["Shock"], pool["Alpine Watchdog"], pool["Island"]],
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    result = game.activate_permanent_ability(0, "Tormod's Crypt", target_player_index=1)
    assert result.supported, result.details
    game._settle()

    assert p2.graveyard == []
    assert len(p2.exile) == 3
    assert not game.is_on_battlefield(crypt), "sacrificed as part of the cost"


def test_tormods_crypt_leaves_the_other_graveyard_alone(set_pool):
    """One player's, named by the target — the card says "target player's", not
    "each"."""
    pool = set_pool("M21")
    crypt = Permanent(card=pool["Tormod's Crypt"])
    p1 = PlayerState(name="P1", battlefield=[crypt], graveyard=[pool["Shock"]])
    p2 = PlayerState(name="P2", graveyard=[pool["Island"]])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    game.activate_permanent_ability(0, "Tormod's Crypt", target_player_index=1)
    game._settle()

    # The Crypt itself joins its controller's graveyard — it was sacrificed to
    # pay the cost — and everything that was already there stays.
    assert [c.name for c in p1.graveyard] == ["Shock", "Tormod's Crypt"]
    assert p2.graveyard == []


# --- Artifact creatures ----------------------------------------------------


def test_epitaph_golem_bottoms_a_chosen_graveyard_card(set_pool):
    pool = set_pool("M21")
    golem = Permanent(card=pool["Epitaph Golem"])
    p1 = PlayerState(
        name="P1", battlefield=[golem],
        graveyard=[pool["Shock"], pool["Concordia Pegasus"]],
        library=[pool["Island"]],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    result = game.activate_permanent_ability(
        0, "Epitaph Golem", ability_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    assert result.supported, result.details
    assert [c.name for c in p1.graveyard] == ["Shock"]
    assert [c.name for c in p1.library] == ["Island", "Concordia Pegasus"]


def test_sparkhunter_masticore_keeps_its_planeswalker_protection(set_pool):
    """The card the cost line was hiding. "Protection from planeswalkers" is a
    quality this engine models (CR 702.16), and the whole card was unsupported
    only because the compiler stopped at line one."""
    pool = set_pool("M21")
    masticore = _nosick(Permanent(card=pool["Sparkhunter Masticore"]))
    walker = Permanent(card=pool["Basri Ket"], metadata={"loyalty_counters": 4})
    p1 = PlayerState(name="P1", battlefield=[masticore])
    p2 = PlayerState(name="P2", battlefield=[walker])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False

    assert ("card_type", "planeswalker") in game._protection_qualities(masticore)


# --- Round 86: a condition about two permanents at once ---------------------


def _replicator_board(set_pool, mine=(), theirs=(), my_tokens=()):
    """Chrome Replicator in hand over the board *mine*/*theirs* describes."""
    pool = set_pool("M21")
    from engine.tokens import make_token_card

    battlefield = [Permanent(card=pool[name]) for name in mine]
    battlefield += [
        Permanent(
            card=make_token_card(name, 2, 2, "Creature — Bear"),
            metadata={"is_token": True},
        )
        for name in my_tokens
    ]
    p1 = PlayerState(
        name="P1", battlefield=battlefield, hand=[pool["Chrome Replicator"]]
    )
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=pool[n]) for n in theirs])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game


def _constructs(game):
    return [
        perm
        for perm in game.controlled_by(0)
        if perm.metadata.get("is_token") and perm.card.name == "Construct Token"
    ]


def test_chrome_replicator_compiles_supported(set_pool):
    """The token half already worked; the whole card was its intervening-if.
    "…with the same name as one another" is a relation *between* the counted
    permanents, so it rides the condition rather than the object filter — an
    ObjectFilter is asked about one permanent at a time, and no one permanent
    can answer whether something else shares its name."""
    program = compile_card_oracle(set_pool("M21")["Chrome Replicator"])
    assert program.supported, program.reason

    (trigger,) = program.triggered_abilities
    gate = trigger.instruction.payload["intervening_if"]
    assert gate["count"] == 2 and gate["op"] == "ge" and gate["shared_name"]
    assert gate["filter"] == {"exclude_types": ["land"], "nontoken": True}


def test_a_pair_sharing_a_name_makes_the_construct(set_pool):
    game = _replicator_board(set_pool, mine=["Alpine Watchdog", "Alpine Watchdog"])

    game.cast_from_hand(0, "Chrome Replicator")
    game._settle()

    assert len(_constructs(game)) == 1


def test_three_names_with_one_pair_among_them_still_counts(set_pool):
    """The threshold bounds the largest same-name *group*, not the matching set.
    Three permanents match the noun phrase here and only two share a name — and
    that is what the card asks for."""
    game = _replicator_board(
        set_pool, mine=["Alpine Watchdog", "Gale Swooper", "Alpine Watchdog"]
    )

    game.cast_from_hand(0, "Chrome Replicator")
    game._settle()

    assert len(_constructs(game)) == 1


def test_two_permanents_with_different_names_make_nothing(set_pool):
    """Two matching permanents, no shared name. Counting the matching set the
    way every other ``controls`` condition does would satisfy this — which is
    exactly the reading the relation exists to rule out."""
    game = _replicator_board(set_pool, mine=["Alpine Watchdog", "Gale Swooper"])

    game.cast_from_hand(0, "Chrome Replicator")
    game._settle()

    assert _constructs(game) == []


def test_the_pair_has_to_be_one_you_control(set_pool):
    """"**You** control" — an opponent's matched set is a different player's."""
    game = _replicator_board(set_pool, theirs=["Alpine Watchdog", "Alpine Watchdog"])

    game.cast_from_hand(0, "Chrome Replicator")
    game._settle()

    assert _constructs(game) == []


def test_lands_sharing_a_name_do_not_count(set_pool):
    """"Nonland" is read, not decoration — two Mountains share a name and are
    excluded anyway."""
    game = _replicator_board(set_pool, mine=["Mountain", "Mountain"])

    game.cast_from_hand(0, "Chrome Replicator")
    game._settle()

    assert _constructs(game) == []


def test_tokens_sharing_a_name_do_not_count(set_pool):
    """"Nontoken", the other half of the noun phrase — and the half that keeps
    the card from feeding itself: two Constructs it made would otherwise satisfy
    the next copy's condition."""
    game = _replicator_board(set_pool, my_tokens=["Bear", "Bear"])

    game.cast_from_hand(0, "Chrome Replicator")
    game._settle()

    assert _constructs(game) == []


# --- Mazemind Tome: an inert counter and a state trigger (round 127) --------


def _tome_board(set_pool, library=10):
    pool = set_pool("M21")
    tome = Permanent(card=pool["Mazemind Tome"])
    p1 = PlayerState(name="P1", life=20, library=[pool["Mountain"]] * library)
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(0, tome, None)
    return game, p1, tome


def _use(game, tome, ability_index):
    tome.tapped = False
    result = game.activate_permanent_ability(
        0, "Mazemind Tome", ability_index=ability_index,
    )
    game._settle()
    return result


def test_mazemind_tome_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Mazemind Tome"])
    assert program.supported, program.reason
    (trigger,) = program.triggered_abilities
    assert trigger.condition.kind == "counters_reach_threshold"
    assert trigger.supported


def test_the_counter_is_a_cost_that_adds(set_pool):
    """"Put a page counter on this artifact" spends nothing, so it can never be
    unpayable — which is why it is its own cost rather than a counter removal
    with the sign flipped."""
    from engine.named_counters import counters_on

    game, p1, tome = _tome_board(set_pool)

    assert _use(game, tome, 0).supported
    assert counters_on(tome, "page") == 1
    assert _use(game, tome, 1).supported
    assert counters_on(tome, "page") == 2
    assert len(p1.hand) == 1, "the second ability draws"


def test_the_fourth_counter_exiles_the_tome_and_gains_four_life(set_pool):
    """CR 603.8: a *state* trigger, checked by the state-based sweep rather than
    announced from a call site — there is no event to hang it on."""
    game, p1, tome = _tome_board(set_pool)

    for _ in range(4):
        _use(game, tome, 1)

    assert [c.name for c in p1.exile] == ["Mazemind Tome"]
    assert list(game.controlled_by(0)) == []
    assert p1.life == 24


def test_the_state_trigger_fires_once(set_pool):
    """CR 603.8b: it fires once and not again until the state stops matching.
    Remembering forever would be wrong too — the rule is forgetting — so the
    permanent records that it announced and drops the record if the count ever
    falls back."""
    from engine.named_counters import add_counters

    game, p1, tome = _tome_board(set_pool)
    add_counters(tome, "page", 4)

    game.check_state_based_actions()
    game._settle()
    first = len(p1.exile)
    game.check_state_based_actions()
    game._settle()

    assert first == 1 and len(p1.exile) == 1


def test_an_inert_counter_does_not_touch_power_or_toughness(set_pool):
    """CR 122.1: a counter whose kind is a word the card invents has no rules
    meaning. Routing it through the +1/+1 channel would change a creature's
    size; through the loyalty one, a walker's survival."""
    from engine.named_counters import add_counters, counters_on
    from tests.helpers import _mk_creature_card

    perm = Permanent(card=_mk_creature_card("Bear", 2, 2, ""))
    add_counters(perm, "page", 3)

    assert counters_on(perm, "page") == 3
    assert (perm.effective_power, perm.effective_toughness) == (2, 2)
