"""Ice Age (ICE) artifact cards.

ICE is a *measured* set, mid-implementation: cards land here with the round
that buys them (tests/sets/README.md, SET_PLAYBOOK.md Phase 3), and the pool
resolves through ``set_pool("ICE")`` even though the set is not shipped —
reading a card file is not shipping it. The round each section names is
written up in ROADMAP.md; a round's cards are split across these files by the
printed type of the card each test is about.

CR-level tests for the mechanics this set introduced live in ``tests/rules/`` —
cumulative upkeep is ``tests/rules/test_cumulative_upkeep.py``. What belongs
here is the *card*: that this printing compiles, and that its own numbers and
text do what the card says.
"""

from __future__ import annotations

from engine import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick


# --- Round 17: a keyword family named whole, and a negated supertype ---
def test_staff_of_the_ages_switches_off_every_landwalk(set_pool):
    """"Creatures with **landwalk abilities** can be blocked as though they
    didn't have **those abilities**."

    The evasion-negation table read one keyword per sentence. CR 702.14a makes
    landwalk a *family* whose members are **open** — the ability's name is built
    from a printed quality, so "snow forestwalk" is one — which is why the
    negation carries the family word rather than a list of members. Enumerating
    the five basics was the first attempt, and it left Rime Dryad's snow
    forestwalk enforced against a Staff that says it is not.
    """
    from engine.evasion_negation import evasion_negation_for
    from engine.landwalk import LANDWALK

    assert evasion_negation_for(
        "creatures with landwalk abilities can be blocked as though they "
        "didn't have those abilities"
    ) == frozenset({LANDWALK})
    assert compile_card_oracle(set_pool("ICE")["Staff of the Ages"]).supported
def _combat(game: Game, attacker_indices: list[int]) -> None:
    """Advance seat 0's turn to the declare-blockers step with those attackers."""
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()  # beginning_of_combat
    game.advance_combat_phase()  # declare_attackers
    ok, msg = game.declare_attackers(0, attacker_indices)
    assert ok, msg
    game.advance_combat_phase()  # declare_blockers
    assert game.current_step == "declare_blockers"
def test_staff_of_the_ages_lets_a_forestwalker_be_blocked(set_pool):
    """Run in real combat: with a Forest out, forestwalk normally forbids the
    block, and the Staff lifts the restriction (CR 509.1b) without removing the
    keyword."""
    pool = set_pool("ICE")

    def _blocks(with_staff: bool) -> bool:
        walker = Permanent(card=pool["Rime Dryad"])  # snow forestwalk
        blocker = Permanent(card=pool["Balduvian Bears"])
        snow = Permanent(card=pool["Snow-Covered Forest"])
        theirs = [blocker, snow]
        if with_staff:
            theirs.append(Permanent(card=pool["Staff of the Ages"]))
        p1 = PlayerState(name="P1", battlefield=[walker], life=20)
        p2 = PlayerState(name="P2", battlefield=theirs, life=20)
        game = Game(players=[p1, p2])
        _combat(game, [0])
        return game.declare_blockers(1, {0: 0})[0]

    assert not _blocks(with_staff=False)
    assert _blocks(with_staff=True)
# --- Round 27: a supertype is a computed characteristic (CR 205.4, layer 4) ---
def _board(set_pool, *names, opponent=()):
    """A board of ICE cards, mine and the opponent's, ready to activate."""
    pool = set_pool("ICE")
    mine = [Permanent(card=pool[n]) for n in names]
    theirs = [Permanent(card=pool[n]) for n in opponent]
    game = Game(
        players=[
            PlayerState(name="P1", battlefield=mine, life=20),
            PlayerState(name="P2", battlefield=theirs, life=20),
        ]
    )
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._sync_control()
    for perm in mine:
        _nosick(perm)
    return game, mine, theirs
def test_arcums_weathervane_freezes_a_nonsnow_basic_land(set_pool):
    """"{2}, {T}: Target nonsnow basic land becomes snow."

    CR 205.4a's half of the type line, changed in layer 4. No "in addition to
    its other types" tail, because a supertype displaces nothing — and the
    Plains is still basic afterwards (CR 205.4b).
    """
    game, (vane, plains), _ = _board(set_pool, "Arcum's Weathervane", "Plains")
    assert not plains.has_supertype("snow")

    result = game.activate_permanent_ability(
        0, "Arcum's Weathervane", ability_index=1,
        target_player_index=0, target_permanent_index=1,
    )
    game._settle()

    assert result.supported, result.details
    assert plains.has_supertype("snow")
    assert plains.has_supertype("basic"), "CR 205.4b: the other supertypes stay"
def test_arcums_weathervane_thaws_a_snow_land(set_pool):
    """"{2}, {T}: Target snow land is no longer snow." The same handler with
    the polarity flipped — one row, because what differs between the
    Weathervane's two abilities is a single printed word."""
    game, (vane, snow), _ = _board(
        set_pool, "Arcum's Weathervane", "Snow-Covered Forest"
    )
    assert snow.has_supertype("snow")

    result = game.activate_permanent_ability(
        0, "Arcum's Weathervane", ability_index=0,
        target_player_index=0, target_permanent_index=1,
    )
    game._settle()

    assert result.supported, result.details
    assert not snow.has_supertype("snow")
    assert snow.has_supertype("basic")
# --- Round 32: a shield that narrows nothing, and one around the enchanted creature ---
def test_pentagram_of_the_ages_prevents_the_whole_next_hit_from_its_chosen_source(set_pool):
    """"{4}, {T}: The next time a source of your choice would deal damage to you
    this turn, prevent that damage." (CR 615.8.)

    The pool had four narrowings of this sentence before it had the sentence:
    a colour (Circle of Protection), a card type (CoP: Artifacts), a fraction
    (Dark Sphere) and a rider (Reverse Damage). The unnarrowed form refused as
    "no handler for this source-scoped shield".
    """
    from tests.helpers import _damage_dealt

    pentagram = Permanent(card=set_pool("ICE")["Pentagram of the Ages"])
    ogre = Permanent(card=set_pool("ICE")["Balduvian Bears"])
    p1 = PlayerState(name="P1", battlefield=[pentagram], life=20)
    p2 = PlayerState(name="P2", battlefield=[ogre], life=20)
    game = Game(players=[p1, p2])

    result = game.activate_permanent_ability(
        0, "Pentagram of the Ages", target_permanent_index=0, target_player_index=1
    )

    assert result.supported
    assert pentagram.tapped
    assert _damage_dealt(game, p1, 7, source=ogre) == 0, "the whole instance"
    assert p1.life == 20
def test_pentagram_of_the_ages_gains_no_life_for_the_damage_it_prevents(set_pool):
    """Reverse Damage prints the life gain; this card stops at the prevention.
    Sharing one shield kind between them would have paid for both."""
    from tests.helpers import _damage_dealt

    pentagram = Permanent(card=set_pool("ICE")["Pentagram of the Ages"])
    ogre = Permanent(card=set_pool("ICE")["Balduvian Bears"])
    p1 = PlayerState(name="P1", battlefield=[pentagram], life=20)
    p2 = PlayerState(name="P2", battlefield=[ogre], life=20)
    game = Game(players=[p1, p2])

    game.activate_permanent_ability(
        0, "Pentagram of the Ages", target_permanent_index=0, target_player_index=1
    )
    _damage_dealt(game, p1, 6, source=ogre)

    assert p1.life == 20
def test_pentagram_of_the_ages_shield_waits_for_the_source_it_chose(set_pool):
    from tests.helpers import _damage_dealt

    pentagram = Permanent(card=set_pool("ICE")["Pentagram of the Ages"])
    ogre = Permanent(card=set_pool("ICE")["Balduvian Bears"])
    other = Permanent(card=set_pool("ICE")["Tor Giant"])
    p1 = PlayerState(name="P1", battlefield=[pentagram], life=20)
    p2 = PlayerState(name="P2", battlefield=[ogre, other], life=20)
    game = Game(players=[p1, p2])

    game.activate_permanent_ability(
        0, "Pentagram of the Ages", target_permanent_index=0, target_player_index=1
    )

    assert _damage_dealt(game, p1, 3, source=other) == 3
    assert _damage_dealt(game, p1, 3, source=ogre) == 0


# --- Round 35: the pronoun names what the sentence in front of it chose ---


def test_celestial_sword_sacrifices_the_creature_it_pumped(set_pool):
    """"{3}, {T}: Target creature you control gets +3/+3 until end of turn. Its
    controller sacrifices it at the beginning of the next end step."

    Krovikan Elementalist prints the same delayed sacrifice with the actor left
    implicit; this one writes it out. A sacrifice is its controller moving their
    own permanent and nobody else can perform it (CR 701.21a), so naming them
    narrows nothing — and it was refused as "another player sacrificing", the
    one reading the sentence cannot have.
    """
    sword = Permanent(card=set_pool("ICE")["Celestial Sword"])
    bear = Permanent(card=set_pool("ICE")["Balduvian Bears"])
    _nosick(sword)
    p1 = PlayerState(
        name="P1", battlefield=[sword, bear], life=20, mana_pool={"C": 3}
    )
    game = Game(players=[p1, PlayerState(name="P2", life=20)])

    result = game.activate_permanent_ability(
        0, "Celestial Sword", target_permanent_index=1, target_player_index=0
    )
    while game.stack:
        game.resolve_top_of_stack()

    assert result.supported
    assert sword.tapped
    assert (bear.effective_power, bear.effective_toughness) == (5, 5)

    game.resolve_end_step(0)

    assert [p.card.name for p in p1.battlefield] == ["Celestial Sword"]
    assert [c.name for c in p1.graveyard] == ["Balduvian Bears"]


# --- Round 36: an activation restriction is not evidence the permanent works ---


def test_amulet_of_quoz_is_not_supported_on_the_strength_of_its_timing_clause(set_pool):
    """"{T}, Sacrifice this artifact: Target opponent may ante the top card of
    their library. … **Activate only during your upkeep.**"

    The ability is the whole card and the compiler cannot read it. What kept the
    artifact reported *supported* was the last sentence: "activate only during
    your upkeep" is claimed by `activation_restrictions.py`, which leaves a
    `derived_static_rule` instruction behind, and the gate took any instruction
    that was not a bare whitelist marker as evidence the permanent does
    something.

    It is not. A restriction says *when an ability may be activated*, so it is a
    clause of that ability — and when no ability of the card is readable it is a
    rule about nothing.
    """
    program = compile_card_oracle(set_pool("ICE")["Amulet of Quoz"])

    assert not program.supported
    assert "no ability of this permanent is implemented" in (program.reason or "")


def test_a_derived_static_rule_that_is_real_behaviour_still_supports_its_card(set_pool):
    """The narrowing is one claim wide, and deliberately: thirty shipped cards
    have a `derived_static_rule` and nothing else — Winter Orb's untap
    restriction, Howling Mine's draw-step modifier, Gloom's cost tax — and each
    of those *is* what the permanent does."""
    from engine.card_loader import load_cards, manifest_set_paths

    pool = {c.name: c for c in load_cards(manifest_set_paths())}
    for name in ("Winter Orb", "Howling Mine", "Gloom", "Meekstone"):
        assert compile_card_oracle(pool[name]).supported, name


# --- W1G4: library, hand and graveyard ---
def _bottle_board(set_pool):
    """Elkin Bottle in play with one card on top of its controller's library."""
    pool = set_pool("ICE")
    bottle = _nosick(Permanent(card=pool["Elkin Bottle"]))
    p1 = PlayerState(
        name="P1", battlefield=[bottle], library=[pool["Balduvian Bears"]], life=20
    )
    game = Game(players=[p1, PlayerState(name="P2", life=20)])
    game.enforce_mana_costs = False
    game._sync_control()
    return pool, p1, game


def test_elkin_bottle_exiles_the_top_card_and_permits_playing_it(set_pool):
    """"{3}, {T}: Exile the top card of your library. Until the beginning of
    your next upkeep, you may play that card." (CR 601.3.)"""
    from engine.cast_permissions import permission_for

    pool, p1, game = _bottle_board(set_pool)

    result = game.activate_permanent_ability(0, "Elkin Bottle")
    assert result.supported, result.details
    game._settle()

    assert p1.library == []
    assert [card.name for card in p1.exile] == ["Balduvian Bears"]
    assert permission_for(game, 0, p1.exile[0], "exile") is not None

    played = game.cast_from_hand(0, "Balduvian Bears", from_zone="exile")
    assert played.supported, played.details
    game._settle()
    assert any(perm.card.name == "Balduvian Bears" for perm in p1.battlefield)


def test_elkin_bottles_permission_survives_this_turns_cleanup(set_pool):
    """"Until the beginning of your next upkeep" is not "until end of turn":
    reading it as the nearer duration throws the exiled card away tonight."""
    from engine.cast_permissions import permission_for

    pool, p1, game = _bottle_board(set_pool)
    game.activate_permanent_ability(0, "Elkin Bottle")
    game._settle()

    game.resolve_cleanup_step(0)

    assert permission_for(game, 0, p1.exile[0], "exile") is not None


def test_elkin_bottles_permission_ends_at_its_controllers_next_upkeep(set_pool):
    """…and it is not unbounded either. The sweep runs as that upkeep begins,
    beside the layer-6 grants carrying the same printed duration."""
    from engine.cast_permissions import permission_for

    pool, p1, game = _bottle_board(set_pool)
    game.activate_permanent_ability(0, "Elkin Bottle")
    game._settle()
    exiled = p1.exile[0]

    game.resolve_upkeep(1)
    assert permission_for(game, 0, exiled, "exile") is not None, (
        "the opponent's upkeep is not this seat's next upkeep"
    )

    game.resolve_upkeep(0)

    assert permission_for(game, 0, exiled, "exile") is None
    assert [card.name for card in p1.exile] == ["Balduvian Bears"], (
        "the card stays in exile; only the permission ends"
    )
def _cap_board(set_pool, card_name, victim_library, victim_hand=()):
    """One Jester in play for seat 0, with seat 1 holding the named cards."""
    pool = set_pool("ICE")
    jester = _nosick(Permanent(card=pool[card_name]))
    p1 = PlayerState(name="P1", battlefield=[jester], life=20)
    p2 = PlayerState(
        name="P2",
        library=[pool[name] for name in victim_library],
        hand=[pool[name] for name in victim_hand],
        life=20,
    )
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = {0, 1}
    game._sync_control()
    return pool, p1, p2, game


def test_jesters_cap_searches_the_targets_library_and_exiles_three(set_pool):
    """"{2}, {T}, Sacrifice this artifact: Search target player\'s library for
    three cards and exile them. Then that player shuffles."

    CR 608.2c: the ability\'s controller chooses, and the library is somebody
    else\'s — two seats, which is what makes this a different effect from the
    tutor that searches your own.
    """
    pool, p1, p2, game = _cap_board(
        set_pool, "Jester\'s Cap",
        ["Balduvian Bears", "Brown Ouphe", "Tor Giant", "Scaled Wurm"],
    )

    result = game.activate_permanent_ability(0, "Jester\'s Cap")
    assert result.supported, result.details

    prompt = game.pending_choice_of("search_library", 0)
    assert prompt is not None, "the searcher is the one who chooses"
    assert prompt.data["zone_seat"] == 1, "and the library is the target\'s"

    assert game.confirm_search_library_picks(
        0, [{"zone": "library", "index": 0},
            {"zone": "library", "index": 1},
            {"zone": "library", "index": 2}]
    )
    game._settle()

    assert sorted(card.name for card in p2.exile) == [
        "Balduvian Bears", "Brown Ouphe", "Tor Giant",
    ], "CR 400.3 sends each card to its own owner\'s exile"
    assert [card.name for card in p2.library] == ["Scaled Wurm"]
    assert p1.exile == [] and p1.hand == []


def test_jesters_cap_leaves_the_searchers_own_library_alone(set_pool):
    """The seat whose zone is opened is payload, and getting it wrong is
    silent: the search would still find three cards and still report done."""
    pool, p1, p2, game = _cap_board(
        set_pool, "Jester\'s Cap", ["Balduvian Bears", "Brown Ouphe", "Tor Giant"]
    )
    p1.library = [pool["Scaled Wurm"]]

    game.activate_permanent_ability(0, "Jester\'s Cap")
    game.confirm_search_library_picks(0, [{"zone": "library", "index": 0}])
    game._settle()

    assert [card.name for card in p1.library] == ["Scaled Wurm"]
    assert [card.name for card in p2.exile] == ["Balduvian Bears"]


def test_jesters_mask_empties_the_hand_then_gives_that_many_back(set_pool):
    """"Target opponent puts the cards from their hand on top of their library.
    Search that player\'s library for that many cards. That player puts those
    cards into their hand, then shuffles."

    Three sentences and one effect: the count comes from the first, the cards
    from the second, and the seat that receives them is the searched player —
    not the searcher.
    """
    pool, p1, p2, game = _cap_board(
        set_pool, "Jester\'s Mask",
        ["Scaled Wurm", "Tor Giant"],
        victim_hand=["Balduvian Bears", "Brown Ouphe"],
    )

    result = game.activate_permanent_ability(0, "Jester\'s Mask")
    assert result.supported, result.details

    # The hand goes back first, and its owner chooses the order (CR 401.4).
    assert game.confirm_hand_to_library(1, [0, 1])
    game._settle()
    assert p2.hand == []

    prompt = game.pending_choice_of("search_library", 0)
    assert prompt is not None, "the searcher searches"
    assert prompt.data["zone_seat"] == 1
    assert prompt.data["count"] == 2, "that many is the number the hand held"

    assert game.confirm_search_library_picks(
        0, [{"zone": "library", "index": 0}, {"zone": "library", "index": 1}]
    )
    game._settle()

    assert len(p2.hand) == 2, "the searched player gets the finds, not the searcher"
    assert p1.hand == []
    assert len(p2.library) == 2, "four cards in the library, two taken out"


def test_jesters_mask_on_an_empty_hand_searches_for_nothing(set_pool):
    """"That many" of nothing is nothing: the search is not armed at all, so
    the library is never opened."""
    pool, p1, p2, game = _cap_board(
        set_pool, "Jester\'s Mask", ["Scaled Wurm", "Tor Giant"],
    )

    result = game.activate_permanent_ability(0, "Jester\'s Mask")
    assert result.supported, result.details
    game._settle()

    assert game.pending_choice_of("search_library", 0) is None
    assert [card.name for card in p2.library] == ["Scaled Wurm", "Tor Giant"]
# --- end W1G4 ---
