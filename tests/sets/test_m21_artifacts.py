"""Core Set 2021 (M21) artifacts.

M21 is a *measured* set, mid-implementation: cards land here with the round that
buys them (tests/sets/README.md, SET_PLAYBOOK.md Phase 3), and the pool resolves
through ``set_pool("M21")`` even though the set is not shipped — reading a card
file is not shipping it. The round each section names is written up in
ROADMAP.md; a round's cards are split across these files by the printed type of
the card each test is about.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.auras import attach_aura
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


# --- Round 133: a graveyard held by the permanent that exiled it ------------


def test_idol_of_endurance_compiles_supported(set_pool):
    program = compile_card_oracle(set_pool("M21")["Idol of Endurance"])
    assert program.supported, program.reason


def _idol_board(set_pool):
    """One Idol about to enter, over a graveyard with a card of each kind the
    printed phrase sorts on."""
    pool = set_pool("M21")
    idol = Permanent(card=pool["Idol of Endurance"])
    p1 = PlayerState(name="P1", graveyard=[
        pool["Alpine Watchdog"],     # creature, mana value 2 — taken
        pool["Shock"],               # mana value 1, but not a creature
        pool["Garruk's Gorehorn"], # creature, but mana value 5
        pool["Llanowar Visionary"],  # creature, mana value 3 — the boundary
    ])
    p2 = PlayerState(name="P2", graveyard=[pool["Alpine Watchdog"]])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    return game, p1, p2, idol


def test_idol_of_endurance_exiles_the_creature_cards_its_phrase_names(set_pool):
    """"all creature cards with mana value 3 or less from **your** graveyard".

    Both halves of the narrowing are checked against a card that fails only that
    half, and the boundary is included: "3 or less" takes the 3. The opponent's
    graveyard is the control for "your" — an identical card sits in it.
    """
    game, p1, p2, idol = _idol_board(set_pool)

    game._put_permanent_onto_battlefield(0, idol, None)
    game._settle()

    assert [c.name for c in p1.exile] == ["Alpine Watchdog", "Llanowar Visionary"]
    assert [c.name for c in p1.graveyard] == ["Shock", "Garruk's Gorehorn"]
    assert [c.name for c in p2.graveyard] == ["Alpine Watchdog"]
    assert p2.exile == []


def test_idol_of_endurance_casts_from_its_own_pile_for_free(set_pool):
    """CR 118.9: "without paying its mana cost" — the mana cost is skipped, with
    costs enforced so the waiver is what is being read and not a relaxed
    fixture."""
    game, p1, p2, idol = _idol_board(set_pool)
    game._put_permanent_onto_battlefield(0, idol, None)
    game._settle()

    assert game.activate_permanent_ability(0, "Idol of Endurance").supported
    game._settle()

    game.enforce_mana_costs = True
    p1.mana_pool = {}
    result = game.cast_from_hand(0, "Alpine Watchdog", from_zone="exile")
    assert result.supported, result.details
    game._settle()

    assert "Alpine Watchdog" in [p.card.name for p in game.controlled_by(0)]


def test_idol_of_endurance_grants_nothing_over_a_pile_it_did_not_exile(set_pool):
    """The permission is over *this* permanent's linked pile. A card sitting in
    the same exile zone from some other effect is not in it — otherwise the
    ability would read the zone rather than the card, and every exiled creature
    in the game would be castable."""
    game, p1, p2, idol = _idol_board(set_pool)
    stranger = p1.graveyard.pop(1)               # Shock, never linked to the Idol
    p1.exile.append(stranger)
    game._put_permanent_onto_battlefield(0, idol, None)
    game._settle()

    assert game.activate_permanent_ability(0, "Idol of Endurance").supported
    game._settle()

    game.enforce_mana_costs = True
    p1.mana_pool = {}
    assert not game.cast_from_hand(0, "Shock", from_zone="exile").supported
    assert game.cast_from_hand(0, "Alpine Watchdog", from_zone="exile").supported


def test_idol_of_endurance_returns_what_is_left_to_the_graveyard(set_pool):
    """CR 610.3: the second one-shot effect returns the object to its **previous
    zone**, which for these cards is the graveyard rather than the hand. A card
    already cast off the pile has moved on and is not returned (CR 400.7)."""
    game, p1, p2, idol = _idol_board(set_pool)
    game._put_permanent_onto_battlefield(0, idol, None)
    game._settle()
    assert game.activate_permanent_ability(0, "Idol of Endurance").supported
    game._settle()
    assert game.cast_from_hand(0, "Alpine Watchdog", from_zone="exile").supported
    game._settle()

    game.remove_from_battlefield(idol)

    assert [c.name for c in p1.graveyard] == ["Shock", "Garruk's Gorehorn", "Llanowar Visionary"]
    assert p1.exile == []
    assert p1.hand == [], "the cards came from a graveyard, so that is where they go back"
    assert "Alpine Watchdog" in [p.card.name for p in game.controlled_by(0)]


# --- The dead-ability round: a colour count, and a comma-separated union ----


def test_chromatic_orrery_compiles_both_abilities(set_pool):
    """The mana ability compiled and the draw did not, and the card reported
    supported on the strength of the first — which is the any-of permanent gate
    hiding a dead ability. Asked of the abilities, not of the card."""
    program = compile_card_oracle(set_pool("M21")["Chromatic Orrery"])
    assert [a.supported for a in program.activated_abilities] == [True, True]


@pytest.mark.parametrize(
    "colors, expected",
    [
        # CR 105.1: colourless is not a colour, so a board of artifacts draws
        # nothing at all — the case a "count the permanents" reading would get
        # most wrong.
        ([], 0),
        (["Llanowar Visionary"], 1),                            # green
        (["Llanowar Visionary", "Alpine Watchdog"], 2),         # green + white
        # Two permanents, one colour: the count is of *colours*, not of objects.
        (["Llanowar Visionary", "Llanowar Visionary"], 1),
    ],
)
def test_chromatic_orrery_draws_one_card_per_colour(set_pool, colors, expected):
    """"Draw a card for each **color among** permanents you control."

    Five permanents can be one colour and one permanent can be five (CR 105.2b),
    so this is a different question from counting them — which is why the
    parametrization pairs two-of-one-colour with one-each.
    """
    pool = set_pool("M21")
    orrery = Permanent(card=pool["Chromatic Orrery"])
    board = [orrery] + [Permanent(card=pool[name]) for name in colors]
    p1 = PlayerState(
        name="P1", battlefield=board,
        library=[pool["Shock"] for _ in range(6)],
    )
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game._sync_control()
    _nosick(orrery)

    assert game.activate_permanent_ability(0, "Chromatic Orrery", ability_index=1).supported
    game._settle()

    assert len(p1.hand) == expected


def test_animal_sanctuary_reads_the_whole_printed_subtype_list(set_pool):
    """"target Bird, Cat, Dog, Goat, Ox, or Snake" — six alternatives, printed
    with commas because English punctuates a list of six differently from a list
    of two. The card means one union either way, and reading only the first
    alternative would refuse five of the creatures it names."""
    program = compile_card_oracle(set_pool("M21")["Animal Sanctuary"])
    counter = next(
        a for a in program.activated_abilities
        if a.instruction is not None and a.instruction.kind == "add_counter_to_target"
    )
    assert counter.supported
    assert counter.instruction.payload["targets"]["filter"]["subtype_filter"] == [
        "bird", "cat", "dog", "goat", "ox", "snake",
    ]


# --- Round 139: two cards whose lines were recorded as unimplemented --------


def test_chromatic_orrery_lets_colourless_pay_a_coloured_pip(set_pool):
    """"You may spend mana as though it were mana of any color." The Orrery's
    own five {C} are what the permission is for, so colourless paying a coloured
    pip is the case that matters. Paired with the same board without it."""
    pool = set_pool("M21")
    for with_orrery, expected in ((True, True), (False, False)):
        p1 = PlayerState(name="P1")
        game = Game(players=[p1, PlayerState(name="P2")])
        game.enforce_mana_costs = False
        if with_orrery:
            game._put_permanent_onto_battlefield(
                0, Permanent(card=pool["Chromatic Orrery"]), None
            )
            game._settle()
        p1.mana_pool = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 5}

        paid = game._pay_mana_cost(
            p1, {"W": 0, "U": 0, "B": 0, "R": 1, "G": 0, "C": 0, "generic": 0}
        )

        assert paid is expected, f"orrery={with_orrery}"


def test_chromatic_orrery_does_not_make_coloured_mana_colourless(set_pool):
    """CR 105.1: colourless is not a colour, so "as though it were mana of any
    color" does not let a {C} in a cost be paid with white."""
    pool = set_pool("M21")
    p1 = PlayerState(name="P1")
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(0, Permanent(card=pool["Chromatic Orrery"]), None)
    game._settle()
    p1.mana_pool = {"W": 3, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}

    assert not game._pay_mana_cost(
        p1, {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 1, "generic": 0}
    )


def _scythe_board(set_pool):
    pool = set_pool("M21")
    scythe = Permanent(card=pool["Malefic Scythe"])
    p1 = PlayerState(name="P1")
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(0, scythe, None)
    bear = Permanent(card=pool["Alpine Watchdog"])       # 2/2
    p1.battlefield.append(bear)
    game._sync_control()
    attach_aura(scythe, bear)
    return game, p1, scythe, bear


def test_malefic_scythe_enters_with_its_counter_and_grants_per_counter(set_pool):
    """"This Equipment enters with a soul counter on it." / "Equipped creature
    gets +1/+1 **for each** soul counter on this Equipment."

    Read as a flat grant the Scythe is a permanent +1/+1 whose counters do
    nothing, which is what it was — the flat pattern matches this line's prefix.
    """
    from engine.named_counters import counters_on

    _game, _p1, scythe, bear = _scythe_board(set_pool)

    assert counters_on(scythe, "soul") == 1
    assert (bear.effective_power, bear.effective_toughness) == (3, 3)


def test_malefic_scythe_grows_when_the_equipped_creature_dies(set_pool):
    """"Whenever equipped creature dies, put a soul counter on this Equipment."

    The condition is about the permanent the Equipment is *attached to*, which
    is a scope no seat comparison can express — and the counter it places is the
    one the P/T grant above reads, so a second store would be a Scythe that
    counts up and never grows.
    """
    from engine.named_counters import counters_on

    game, p1, scythe, bear = _scythe_board(set_pool)

    game._permanent_to_graveyard(p1, bear)
    game._settle()

    assert counters_on(scythe, "soul") == 2

    second = Permanent(card=set_pool("M21")["Alpine Watchdog"])
    p1.battlefield.append(second)
    game._sync_control()
    attach_aura(scythe, second)

    assert (second.effective_power, second.effective_toughness) == (4, 4)


# --- Silent Dart: an object-targeted activated ability (CR 602.2b) -----------
# Recorded failing in-game: "no valid creature targets but the card sacrifices
# itself." Two bugs, one class — an ability that targets an object could be
# activated with no legal target (paying its cost, then dealing to the face or
# no-op), because the pre-cost target check was a per-kind if-chain that named
# only four instruction kinds.


def _silent_dart_board(set_pool, opponent=()):
    pool = set_pool("M21")
    dart = Permanent(card=pool["Silent Dart"])
    p1 = PlayerState(name="P1", battlefield=[dart])
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=pool[n]) for n in opponent])
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = "main"
    game.current_step = "precombat_main"
    return game, p1, p2, dart


def test_silent_dart_cannot_be_activated_with_no_creature_to_target(set_pool):
    game, p1, p2, dart = _silent_dart_board(set_pool)  # empty opposing board

    result = game.activate_permanent_ability(0, "Silent Dart")

    assert result.supported is False
    assert dart.tapped is False          # nothing was paid
    assert p1.graveyard == []            # not sacrificed
    assert p2.life == 20                 # and the opponent took nothing


def test_silent_dart_refuses_a_noncreature_target(set_pool):
    game, p1, p2, dart = _silent_dart_board(set_pool, opponent=["Forest"])
    forest = next(iter(game.controlled_by(1)))

    result = game.activate_permanent_ability(
        0, "Silent Dart", target_permanent_ids=[game.permanent_id_of(forest)]
    )

    assert result.supported is False
    assert dart.tapped is False
    assert p1.graveyard == []


def test_silent_dart_damages_a_named_creature(set_pool):
    game, p1, p2, dart = _silent_dart_board(set_pool, opponent=["Alpine Watchdog"])
    bear = next(iter(game.controlled_by(1)))

    result = game.activate_permanent_ability(
        0, "Silent Dart", target_permanent_ids=[game.permanent_id_of(bear)]
    )

    assert result.supported
    assert [c.name for c in p2.graveyard] == ["Alpine Watchdog"]  # 3 > toughness
    assert [c.name for c in p1.graveyard] == ["Silent Dart"]    # sacrificed as its cost
    assert p2.life == 20                                        # the face is never the target


def test_silent_dart_with_no_named_target_hits_a_creature_not_the_player(set_pool):
    """A headless/AI caller names no target. The target is an object, so a
    legal creature is scanned for — the face is never the fallback, which is
    the reported bug (opponent took 3 with a creature on the board unchosen)."""
    game, p1, p2, dart = _silent_dart_board(set_pool, opponent=["Alpine Watchdog"])

    result = game.activate_permanent_ability(0, "Silent Dart")

    assert result.supported
    assert [c.name for c in p2.graveyard] == ["Alpine Watchdog"]
    assert p2.life == 20
