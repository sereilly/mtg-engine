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
    bare static line and attacked freely while still reporting supported.

    The payload is an ordinary object **filter** now rather than a land-type
    word, which is what lets the same kind carry a phrase no regex could: the
    enforcing check reads it through `subject_matches` like every other printed
    noun, and needs no land scan of its own (CR 205.3i puts a land subtype only
    on a land).
    """
    for land_type in ("Island", "Mountain", "Forest", "Plains", "Swamp"):
        line = normalize_creature_line(
            f"This creature can't attack unless defending player controls a {land_type}."
        )
        restriction = combat_restriction_for(line)

        assert restriction is not None, land_type
        assert restriction.kind == "cant_attack_unless_defender_controls"
        assert restriction.payload == {
            "subject": {"subtype_filter": land_type.lower()},
            "required": True,
        }


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
        # "Walls" reads as creatures of that subtype now that the union's
        # members go through the grammar's noun parser rather than through five
        # regexes of this file's own — the same set, spelled the way every other
        # filter in the engine spells it.
        {"type_filter": "creature", "subtype_filter": "wall"},
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
    any other number produced no instruction at all — and then into a *capture*
    named ``power``, so a card stacking any other narrowing on the same
    sentence (Orcish Veteran's colour) had nowhere to put it. The whole noun
    phrase is the payload now."""
    for threshold in (1, 2, 3, 4, 7):
        program = compile_card_oracle(
            _orc(f"This creature can't block creatures with power {threshold} or greater.")
        )
        assert program.supported
        blocks = [i for i in program.instructions if i.kind == "cant_block_subject"]
        assert len(blocks) == 1, f"power {threshold} produced {program.instructions}"
        assert blocks[0].payload["blockee_filters"] == [
            {"type_filter": "creature", "power": {"op": "ge", "value": threshold}}
        ]


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

    That first example is now *enforced* rather than refused, and its place is
    taken by the sentence with the same shape the gate still cannot answer: a
    keyword no behaviour is registered under. ``Game._has_keyword`` says no for
    every creature, so the restriction would forbid nothing — the same silent
    admission by a different route, which is what this guard is about.
    """
    for text in (
        "This creature can't block creatures with shadow.",
        "This creature can't attack unless you control a Wall.",
        "This creature can't attack unless defending player controls a snowfield.",
    ):
        program = compile_card_oracle(_orc(text))
        assert not program.supported, f"silently admitted: {text}"


@pytest.mark.cr("506.3")
def test_506_3_a_nonbasic_land_requirement_is_read_and_enforced():
    """The other side of the guard above, and the reason it had to change.

    "…unless defending player controls a **Desert**" was unsupported, and the
    limit was the *enforcement's* rather than the card's: the check scanned the
    defender's lands for one of five basic type words. It reads a filter through
    `subject_matches` now, so any printed land type is the same restriction —
    which is what the payload being a noun phrase buys, one card beyond the one
    that needed it.
    """
    program = compile_card_oracle(_orc(
        "This creature can't attack unless defending player controls a Desert."
    ))
    assert program.supported
    restriction = next(
        i for i in program.instructions
        if i.kind == "cant_attack_unless_defender_controls"
    )
    assert restriction.payload == {
        "subject": {"subtype_filter": "desert"}, "required": True,
    }


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


# ---------------------------------------------------------------------------
# Board-wide "can't attack" restrictions over a described set (CR 506.3),
# and the per-turn history conditions beside them
# ---------------------------------------------------------------------------


@pytest.mark.cr("506.3")
def test_506_3_a_subject_filtered_attack_restriction_reads_its_words_as_payload():
    """"Creatures without flying can't attack" (Moat) and "Non-Eye creatures
    you control can't attack" (Evil Eye) are one kind whose subject filter is
    payload — so a card printed with any other keyword or subtype is the same
    restriction with a different word in it."""
    restriction = combat_restriction_for("creatures without trample can't attack")
    assert restriction is not None
    assert restriction.kind == "creatures_cant_attack"
    assert restriction.payload == {
        "subject": {"type_filter": "creature", "without_keywords": ["trample"]},
    }

    restriction = combat_restriction_for("non-goblin creatures you control can't attack")
    assert restriction is not None
    assert restriction.kind == "creatures_cant_attack"
    assert restriction.payload == {
        "subject": {
            "type_filter": "creature",
            "exclude_subtypes": ["goblin"],
            "controller": "you",
        },
    }


@pytest.mark.cr("506.3")
def test_506_3_an_untestable_subject_word_refuses_the_whole_line():
    """A keyword the engine does not implement would make "without <keyword>"
    true of every creature — the restriction over-applying, which is exactly as
    silent as the widening this table refuses everywhere else. An unknown
    subtype is the mirror: "non-<word>" would exclude nothing and ground the
    card's own exempted creatures. Both refuse, loudly.

    The keyword named here has to be one the engine genuinely does not
    implement, so it is checked against the registry rather than assumed —
    "shroud" stood here until round 27 built it, at which point the assertion
    was testing that an implemented keyword is refused.
    """
    from engine.grammar.vocabulary import IMPLEMENTED_KEYWORDS

    assert "shadow" not in IMPLEMENTED_KEYWORDS
    assert combat_restriction_for("creatures without shadow can't attack") is None
    assert combat_restriction_for(
        "non-blorb creatures you control can't attack"
    ) is None


@pytest.mark.cr("506.3", "508.1c")
def test_506_3_a_noncreature_permanent_carrying_the_restriction_enforces_it():
    """The wording is a template, not Moat: an invented enchantment printing a
    different keyword restricts exactly the set its words describe, from the
    same compiled-program scan `can_attack` reads for a creature carrying it."""
    fog_bank = CardDefinition(
        name="Test Miasma", mana_cost="{2}", cmc=2.0, type_line="Enchantment",
        oracle_text="Creatures without trample can't attack.",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": "Test Miasma", "type_line": "Enchantment"},
    )
    program = compile_card_oracle(fog_bank)
    assert program.supported
    assert any(i.kind == "creatures_cant_attack" for i in program.instructions)

    def bear(name: str, keywords=()) -> Permanent:
        return Permanent(card=CardDefinition(
            name=name, mana_cost="", cmc=0.0, type_line="Creature — Bear",
            oracle_text="", colors=(), color_identity=(),
            keywords=tuple(keywords), produced_mana=(),
            raw={"name": name, "type_line": "Creature — Bear",
                 "power": "2", "toughness": "2",
                 "keywords": list(keywords)},
        ))

    grounded = bear("Soft Bear")
    trampler = bear("Heavy Bear", ["Trample"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[grounded, trampler]),
        PlayerState(name="P2", battlefield=[Permanent(card=fog_bank)]),
    ])
    game.start_turn(0)

    assert not game.can_attack(grounded, 1)
    assert game.can_attack(trampler, 1)


@pytest.mark.cr("508.1c")
def test_508_1c_the_last_turn_record_is_the_seats_own_ordinal_not_turn_parity():
    """"…if it attacked during your last turn" (Giant Turtle) across a Time
    Walk: the extra turn IS the controller's next turn, so the creature that
    attacked rests through it — a global turn-parity read would have looked at
    whose turn number was odd and let it through."""
    turtle_card = CardDefinition(
        name="Test Turtle", mana_cost="{1}{G}", cmc=2.0,
        type_line="Creature — Turtle",
        oracle_text="This creature can't attack if it attacked during your last turn.",
        colors=("G",), color_identity=("G",), keywords=(), produced_mana=(),
        raw={"name": "Test Turtle", "type_line": "Creature — Turtle",
             "power": "2", "toughness": "4"},
    )
    turtle = Permanent(card=turtle_card)
    game = Game(players=[
        PlayerState(name="P1", battlefield=[turtle]), PlayerState(name="P2"),
    ])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    ok, msg = game.declare_attackers(0, [0])
    assert ok, msg

    game.extra_turn_queue.append(0)   # Time Walk: P1 takes the next turn too
    game.start_next_turn()
    assert game.active_player_index == 0
    assert not game.can_attack(turtle, 1), (
        "the extra turn is the controller's next turn; it attacked during "
        "their last one"
    )

    game.start_next_turn()   # P2's turn
    game.start_next_turn()   # P1: last turn (the extra one) it rested
    assert game.can_attack(turtle, 1)


@pytest.mark.cr("506.3")
def test_506_3_the_next_turn_restriction_refuses_a_trigger_that_binds_no_blocked_creature():
    """"That creature can't attack during its controller's next turn" reads
    the blocked ids the blocks fire site records — under any other trigger the
    handler would find nothing and the card would compile clean while
    restricting nobody, so the lowering refuses the line by name."""
    from engine.grammar import compile_line

    blocks = compile_line(
        "Whenever this creature blocks a creature, that creature can't attack "
        "during its controller's next turn.",
        card_name="Probe Wall",
    )
    assert blocks.parsed and blocks.lowering_error is None

    attacks = compile_line(
        "Whenever this creature attacks, that creature can't attack during "
        "its controller's next turn.",
        card_name="Probe Wall",
    )
    assert not attacks.usable


# ---------------------------------------------------------------------------
# 508.1c/d — a cap on how many creatures may attack
# ---------------------------------------------------------------------------


def _r27_cap_enchantment(text: str) -> CardDefinition:
    return CardDefinition(
        name="Cap", mana_cost="", cmc=0.0, type_line="Enchantment",
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={"name": "Cap", "type_line": "Enchantment"},
    )


def _r27_attacker(name: str, text: str = "") -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature — Test",
        oracle_text=text, colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature — Test",
             "power": "1", "toughness": "1"},
    )


def _r27_attack_cap_game(cap_text: str | None, attacker_text: str = ""):
    """Three attackers, with the cap enchantment (if any) on the defender's
    side. Advanced to the declare-attackers step."""
    attackers = [
        _nosick(Permanent(card=_r27_attacker(f"A{i}", attacker_text)))
        for i in range(3)
    ]
    defender_board = []
    if cap_text is not None:
        defender_board.append(Permanent(card=_r27_cap_enchantment(cap_text)))
    game = Game(players=[
        PlayerState(name="P1", battlefield=attackers),
        PlayerState(name="P2", battlefield=defender_board),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    return game


@pytest.mark.cr("508.1c")
def test_508_1c_a_cap_on_attackers_makes_a_larger_declaration_illegal():
    """"No more than two creatures can attack each combat." No single creature
    is the illegal one, so this cannot be a per-creature predicate — it is a
    restriction on the declaration, checked where the declaration is made."""
    game = _r27_attack_cap_game("No more than two creatures can attack each combat.")

    ok, msg = game.declare_attackers(0, [0, 1, 2])
    assert not ok
    assert "attack each combat" in msg

    ok, msg = game.declare_attackers(0, [0, 1])
    assert ok, msg


@pytest.mark.cr("508.1c")
def test_508_1c_the_printed_number_is_payload():
    """A card printed with any other number is the same restriction. The count
    is read out of the sentence, so the one-creature form needs no code — and
    the noun agrees with it, which is why the plural is optional."""
    game = _r27_attack_cap_game("No more than one creature can attack each combat.")

    assert not game.declare_attackers(0, [0, 1])[0]
    assert game.declare_attackers(0, [0])[0]


@pytest.mark.cr("508.1c")
def test_508_1c_nothing_caps_the_attack_without_such_a_permanent():
    """The control: three attackers is a legal declaration on an ordinary
    board."""
    game = _r27_attack_cap_game(None)

    ok, msg = game.declare_attackers(0, [0, 1, 2])
    assert ok, msg


@pytest.mark.cr("508.1d")
def test_508_1d_a_requirement_cannot_force_a_declaration_past_a_restriction():
    """"…the maximum possible number of requirements that could be obeyed
    **without disobeying any restrictions**." Three creatures that attack each
    combat if able, under a cap of two: attacking with two is legal, and
    enforcing the third requirement anyway would make every declaration
    illegal."""
    game = _r27_attack_cap_game(
        "No more than two creatures can attack each combat.",
        attacker_text="This creature attacks each combat if able.",
    )

    ok, msg = game.declare_attackers(0, [0, 1])
    assert ok, msg


@pytest.mark.cr("508.1d")
def test_508_1d_the_requirement_still_binds_below_the_cap():
    """The control for the clause above: with room left under the cap, an able
    creature that must attack still has to."""
    game = _r27_attack_cap_game(
        "No more than two creatures can attack each combat.",
        attacker_text="This creature attacks each combat if able.",
    )

    ok, _ = game.declare_attackers(0, [0])
    assert not ok


# ---------------------------------------------------------------------------
# The declaration's sacrifice costs are one payment (CR 508.1g)
# ---------------------------------------------------------------------------


@pytest.mark.cr("508.1g")
def test_508_1g_two_attackers_sacrifice_costs_are_summed_over_the_declaration(set_pool):
    """"This creature can't attack unless you sacrifice two Islands."
    (Leviathan.) Two of them owe **four** Islands, not two.

    `can_attack` is a per-creature predicate: it can say "there are two Islands
    for this one" and cannot say "and two more for the next". So a declaration
    the board could not pay was accepted and then charged for one creature —
    the mana half of this same rule has been planned over the whole declaration
    since it was written, and the sacrifice half was not.

    The planner is a *matching* rather than a greedy pass, for `plan_payment`'s
    reason: costs can overlap, and spending the wrong permanent on the looser
    one under-reports a board that could pay.
    """
    lea = set_pool("LEA")
    drk = set_pool("DRK")

    def _declare(islands: int) -> tuple[bool, int]:
        leviathans = [Permanent(card=drk["Leviathan"]) for _ in range(2)]
        for perm in leviathans:
            _nosick(perm)
        pool = [Permanent(card=lea["Island"]) for _ in range(islands)]
        game = Game(players=[
            PlayerState(name="P1", battlefield=[*leviathans, *pool]),
            PlayerState(name="P2"),
        ])
        game.enforce_mana_costs = False
        game.active_player_index = 0
        game.current_turn_phase = "combat"
        game.current_step = "declare_attackers"
        ok, _message = game.declare_attackers(0, [0, 1])
        left = sum(
            1 for perm in game.players[0].battlefield if perm.has_type("island")
        )
        return ok, left

    assert _declare(3) == (False, 3), "three Islands cannot pay four, and pay none"
    assert _declare(4) == (True, 0), "four Islands pay four"


@pytest.mark.cr("508.1g")
def test_508_1g_the_sacrifice_plan_prefers_the_permanent_each_cost_can_only_use(set_pool):
    """Overlapping costs are a matching, and a greedy pass gets this wrong.

    Flooded Woodlands wants **a land** for the attacking green creature;
    Leviathan wants **two Islands** for itself. With two Islands and one Forest
    on the board the declaration is payable — but only if the Forest answers
    "a land". A reader that spent an Island there would refuse a board that can
    pay, which is the direction CR 508.1g's "able to" forbids.
    """
    lea = set_pool("LEA")
    ice = set_pool("ICE")
    leviathan = _nosick(Permanent(card=set_pool("DRK")["Leviathan"]))
    bear = _nosick(Permanent(card=ice["Balduvian Bears"]))  # green
    islands = [Permanent(card=lea["Island"]) for _ in range(2)]
    forest = Permanent(card=lea["Forest"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[leviathan, bear, *islands, forest]),
        PlayerState(
            name="P2", battlefield=[Permanent(card=ice["Flooded Woodlands"])]
        ),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.current_turn_phase = "combat"
    game.current_step = "declare_attackers"

    ok, message = game.declare_attackers(0, [0, 1])

    assert ok, message
    assert not [
        perm for perm in game.players[0].battlefield
        if perm.card.primary_type == "land"
    ], "all three lands paid: two Islands for the Leviathan, the Forest for the Bear"
