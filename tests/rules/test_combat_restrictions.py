"""Tests for Magic: The Gathering Comprehensive Rules Section 506.

Covers:
  506.3 — A creature can only attack if the game's restrictions allow it

These pin the *derivation* of combat restrictions from oracle text
(engine/combat_restrictions.py), which replaced an `elif` chain of exact string
comparisons inside the oracle compiler. That chain hardcoded Island, so this
uses an invented card printed with a different land type — a test naming only
Dandân would have passed against the broken version.
"""

import pytest

from engine import Game, PlayerState
from engine.combat_restrictions import combat_restriction_for
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle, normalize_creature_line
from tests.helpers import _nosick


def _fish(land_type: str) -> CardDefinition:
    text = f"This creature can't attack unless defending player controls a {land_type}."
    return CardDefinition(
        name=f"{land_type} Fish", mana_cost="{U}{U}", cmc=2.0,
        type_line="Creature — Fish", oracle_text=text,
        colors=("U",), color_identity=("U",), keywords=(), produced_mana=(),
        raw={"name": f"{land_type} Fish", "type_line": "Creature — Fish",
             "power": "4", "toughness": "1"},
    )


@pytest.mark.cr("506.3")
def test_506_3_the_required_land_type_is_read_from_the_text():
    """The restriction names a land type, and that type is data. It used to be
    baked into the instruction's *name*, matched by exact string equality
    against the Island wording — so a card naming any other type compiled to a
    bare static line and attacked freely while still reporting supported."""
    for land_type in ("Island", "Mountain", "Forest", "Plains", "Swamp"):
        line = normalize_creature_line(
            f"This creature can't attack unless defending player controls a {land_type}."
        )
        restriction = combat_restriction_for(line)

        assert restriction is not None, land_type
        assert restriction.kind == "cant_attack_without_land_type"
        assert restriction.payload == {"land_type": land_type.lower()}


@pytest.mark.cr("506.3")
def test_506_3_a_non_island_restriction_is_actually_enforced():
    """The whole point: the restriction has to *stop the attack*, not merely
    parse. A creature needing a Mountain may attack a player who controls one
    and may not attack a player who controls an Island."""
    catalog = {c.name: c for c in __import__("engine.card_loader", fromlist=["x"]).load_catalog()}

    def can_attack(defender_land: str) -> bool:
        attacker = _nosick(Permanent(card=_fish("Mountain")))
        p1 = PlayerState(name="P1", battlefield=[attacker])
        p2 = PlayerState(name="P2", battlefield=[Permanent(card=catalog[defender_land])])
        game = Game(players=[p1, p2])
        game.start_turn(0)
        game._close_current_priority_step()
        game.advance_combat_phase()
        game.advance_combat_phase()
        return game.declare_attackers(0, [0])[0]

    assert can_attack("Mountain") is True
    assert can_attack("Island") is False


@pytest.mark.cr("506.3")
def test_506_3_unrelated_lines_impose_no_combat_restriction():
    """A loose match here would silently stop a creature attacking.

    "…can't be blocked except by walls" used to be in this list, because the
    table did not read the whitelist form at all and Invisibility's version was
    an Aura restriction of its own. It is a restriction now (Evil Eye of
    Orms-by-Gore prints it about itself), so the negative case it stood for is
    made by the unreadable union below instead.
    """
    for line in (
        "this creature can't be blocked except by gorillas riding unicycles",
        "this creature gets +1/+1 as long as you control a swamp",
        "flying",
        "",
    ):
        assert combat_restriction_for(line) is None, line


@pytest.mark.cr("509.1b")
def test_509_1b_an_except_by_clause_names_the_only_legal_blockers():
    """"…can't be blocked except by Walls and/or creatures with flying"
    (Elven Riders). A whitelist: a blocker matching no member of the union is
    illegal, where "can't be blocked by Walls" lets the rest of the board
    through."""
    restriction = combat_restriction_for(
        "this creature can't be blocked except by walls and/or creatures with flying"
    )
    assert restriction is not None
    assert restriction.kind == "cant_be_blocked_except_by"
    assert restriction.payload["allowed_blockers"] == [
        {"subtype_filter": "wall"},
        {"type_filter": "creature", "with_keywords": ["flying"]},
    ]


@pytest.mark.cr("509.1b")
def test_509_1b_an_unreadable_union_refuses_the_whole_line():
    """The pattern ends in a catch-all, so the union is parsed where the
    restriction is built. A phrase it cannot read must refuse the line rather
    than admit a restriction that allows everything — the widening direction."""
    assert combat_restriction_for(
        "this creature can't be blocked except by creatures with three heads"
    ) is None


# ---------------------------------------------------------------------------
# Characteristic-defining land-count P/T (CR 604.3)
# ---------------------------------------------------------------------------


def _orc(text: str) -> CardDefinition:
    return CardDefinition(
        name="Probe Orc", mana_cost="{1}{R}", cmc=2.0,
        type_line="Creature — Orc", oracle_text=text,
        colors=("R",), color_identity=("R",), keywords=(), produced_mana=(),
        raw={"name": "Probe Orc", "type_line": "Creature — Orc",
             "power": "2", "toughness": "2"},
    )


@pytest.mark.cr("509.1b")
def test_509_1b_cant_block_power_threshold_is_data_not_part_of_the_kind():
    """"Can't block creatures with power N or greater" is one restriction with a
    number in it. The threshold used to be baked into the instruction kind
    (`cant_block_power_2_or_greater`), so the identical restriction printed with
    any other number produced no instruction at all."""
    for threshold in (1, 2, 3, 4, 7):
        program = compile_card_oracle(
            _orc(f"This creature can't block creatures with power {threshold} or greater.")
        )
        assert program.supported
        blocks = [i for i in program.instructions if i.kind == "cant_block_power_n_or_greater"]
        assert len(blocks) == 1, f"power {threshold} produced {program.instructions}"
        assert blocks[0].payload["power"] == threshold


@pytest.mark.cr("509.1b")
def test_509_1b_a_higher_threshold_actually_gates_blocking():
    """Payload-correct is not behaviour-correct: drive the real block check."""
    blocker_card = _orc("This creature can't block creatures with power 4 or greater.")
    attacker_card = CardDefinition(
        name="Big Attacker", mana_cost="{3}{R}", cmc=4.0,
        type_line="Creature — Giant", oracle_text="", colors=("R",),
        color_identity=("R",), keywords=(), produced_mana=(),
        raw={"name": "Big Attacker", "type_line": "Creature — Giant",
             "power": "3", "toughness": "3"},
    )
    attacker_p1, defender_p2 = PlayerState(name="A"), PlayerState(name="B")
    attacker = _nosick(Permanent(card=attacker_card))
    blocker = _nosick(Permanent(card=blocker_card))
    attacker_p1.battlefield.append(attacker)
    defender_p2.battlefield.append(blocker)
    game = Game(players=[attacker_p1, defender_p2])
    game.enforce_mana_costs = False

    # Power 3 is under the printed threshold of 4, so this block is legal —
    # against the old hardcoded "2 or greater" it would have been refused.
    assert game._can_block_attacker(blocker, attacker) is True

    attacker.metadata["derived_buff_power"] = 1   # now 4/3, at the threshold
    assert game._can_block_attacker(blocker, attacker) is False


@pytest.mark.cr("506.3")
def test_506_3_an_unrecognized_restriction_rider_is_unsupported_not_silently_dropped():
    """The gate and the dispatch must read the same table.

    The gate matched its literals by `startswith` while the dispatch patterns
    are anchored, so "can't block creatures with flying" was admitted by the
    prefix "this creature can't block", matched no anchored pattern, and fell
    through to a bare static line: supported, restriction absent. Failing loud
    is the contract — a card the engine cannot enforce must not claim support.
    """
    for text in (
        "This creature can't block creatures with flying.",
        "This creature can't attack unless you control a Wall.",
        "This creature can't attack unless defending player controls a Desert.",
    ):
        program = compile_card_oracle(_orc(text))
        assert not program.supported, f"silently admitted: {text}"


# ---------------------------------------------------------------------------
# Restrictions are cumulative (CR 508.1c)
# ---------------------------------------------------------------------------


@pytest.mark.cr("508.1c")
def test_508_1c_a_satisfied_restriction_does_not_answer_the_others():
    """"If **any** restrictions are being disobeyed, the declaration of
    attackers is illegal" â€” so restrictions are cumulative and satisfying one
    settles only that one.

    The attack check used to *return* the land-type restriction's answer, which
    skipped every check after it. Sea Serpent and Island Sanctuary have shipped
    together since Alpha, and they meet on exactly the board where both are
    played: the Serpent's own clause requires the defender to control an Island,
    which is the board an Island Sanctuary player has. So the Serpent â€” no
    flying, no islandwalk â€” attacked straight through it. The same return also
    skipped the defender check below, so a creature printed with both that clause
    and defender would have attacked with no permission at all.

    Nothing in the suite noticed, because every other restriction is checked
    after this one.
    """
    from engine.card_loader import load_catalog

    catalog = {c.name: c for c in load_catalog()}
    serpent = _nosick(Permanent(card=_fish("Island")))
    p2 = PlayerState(name="P2", battlefield=[Permanent(card=catalog["Island"])])
    game = Game(players=[PlayerState(name="P1", battlefield=[serpent]), p2])
    game.enforce_mana_costs = False

    assert game.can_attack(serpent, 1) is True

    p2.island_sanctuary_protected = True

    assert game.can_attack(serpent, 1) is False, (
        "no flying and no islandwalk, so Island Sanctuary still applies"
    )


# ---------------------------------------------------------------------------
# "As though" is not removal (CR 609.4)
# ---------------------------------------------------------------------------


def _dozing_lizard() -> CardDefinition:
    """Drowsing Tyrannodon's template on an invented card.

    Named nothing the pool prints: the permission has to fall out of the printed
    sentence, so a test that could only pass for one name would not tell the
    difference between a production and a hook.
    """
    text = (
        "Defender\n"
        "As long as you control a creature with power 4 or greater, this "
        "creature can attack as though it didn't have defender."
    )
    return CardDefinition(
        name="Dozing Lizard", mana_cost="{1}{G}", cmc=2.0,
        type_line="Creature â€” Lizard", oracle_text=text,
        colors=("G",), color_identity=("G",), keywords=("Defender",),
        produced_mana=(),
        raw={"name": "Dozing Lizard", "type_line": "Creature â€” Lizard",
             "power": "3", "toughness": "3"},
    )


def _bruiser(power: int) -> CardDefinition:
    return CardDefinition(
        name=f"{power}-Power Bruiser", mana_cost="{4}{G}", cmc=5.0,
        type_line="Creature â€” Beast", oracle_text="", colors=("G",),
        color_identity=("G",), keywords=(), produced_mana=(),
        raw={"name": f"{power}-Power Bruiser",
             "type_line": "Creature â€” Beast",
             "power": str(power), "toughness": "3"},
    )


def _lizard_game(friend_power: int | None):
    lizard = _nosick(Permanent(card=_dozing_lizard()))
    battlefield = [lizard]
    if friend_power is not None:
        battlefield.append(_nosick(Permanent(card=_bruiser(friend_power))))
    game = Game(players=[PlayerState(name="P1", battlefield=battlefield),
                         PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game._recompute_continuous_effects()
    return game, lizard


@pytest.mark.cr("609.4", "702.3b")
def test_609_4_an_as_though_permission_does_not_remove_defender():
    """CR 609.4: the game treats the condition as true *for that effect only*.

    Implementing the line by taking the keyword away would pass an attack test
    and then be wrong everywhere else the keyword is read â€” a defender-narrowed
    noun phrase (Portcullis Vine's "sacrifice a creature with defender") would
    stop matching, and layer 6 would report a creature the card never changed.
    """
    from engine.subject_filters import subject_matches

    game, lizard = _lizard_game(friend_power=5)

    assert game.can_attack(lizard, 1) is True
    assert game._has_keyword(lizard, "defender"), "the permission is not a removal"
    assert subject_matches(
        game, lizard, {"type_filter": "creature", "with_keywords": ["defender"]},
        observer=0,
    )


@pytest.mark.cr("609.4")
def test_609_4_the_condition_is_re_asked_rather_than_latched():
    """"As long as" exists exactly while its condition does. A 3-power friend
    never grants it, and a 5-power friend stops granting it when it leaves."""
    game, lizard = _lizard_game(friend_power=3)
    assert game.can_attack(lizard, 1) is False

    game, lizard = _lizard_game(friend_power=5)
    assert game.can_attack(lizard, 1) is True
    game.remove_from_battlefield(game.players[0].battlefield[1])
    game._settle()

    assert game.can_attack(lizard, 1) is False


@pytest.mark.cr("509.1a")
def test_a_creatures_own_cant_block_is_asked_of_the_blocker():
    """"This creature can't block." compiled to a ``cant_block`` instruction,
    reported the card supported, and was read by nobody.

    ``engine/combat_restrictions.py``'s own comment named
    ``phases/declare_blockers_step`` as the enforcement site, and that file had
    never mentioned the kind — every question in ``_can_block_attacker`` is
    about the *attacker*, which is how a restriction on the blocker came to have
    no home at all. The pool prints the line on no card today, which is why it
    went unnoticed; it is one of the commonest templates in Magic."""
    from engine import Game
    from engine.models import Permanent, PlayerState
    from tests.helpers import _mk_creature_card

    banned = Permanent(card=_mk_creature_card(
        "Idle Hands", 2, 2, "This creature can't block.",
    ))
    willing = Permanent(card=_mk_creature_card("Eager", 2, 2, ""))
    attacker = Permanent(card=_mk_creature_card("Attacker", 3, 3, ""))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker]),
        PlayerState(name="P2", battlefield=[banned, willing]),
    ])

    assert game._can_block_attacker(willing, attacker), (
        "the control: an unrestricted creature blocks"
    )
    assert not game._can_block_attacker(banned, attacker)


@pytest.mark.cr("509.1a", "702.16f")
def test_a_clone_of_a_creature_that_cant_block_cannot_block_either():
    """CR 707.2: the copy has the copied card's abilities. Asked of the
    *effective* card, like every other read in that function."""
    from engine import Game
    from engine.models import Permanent, PlayerState
    from tests.helpers import _mk_creature_card

    from engine.copies import become_copy

    original = Permanent(card=_mk_creature_card(
        "Idle Hands", 2, 2, "This creature can't block.",
    ))
    clone = Permanent(card=_mk_creature_card("Shapeshifter", 0, 0, ""))
    become_copy(clone, original)
    attacker = Permanent(card=_mk_creature_card("Attacker", 3, 3, ""))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[attacker]),
        PlayerState(name="P2", battlefield=[original, clone]),
    ])

    assert not game._can_block_attacker(clone, attacker)
