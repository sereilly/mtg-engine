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
