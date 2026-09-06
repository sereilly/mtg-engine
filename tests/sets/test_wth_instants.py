"""Weatherlight instants.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: cumulative upkeep beyond a mana cost ---
    from engine import Game, PlayerState
    ...

Cards come from `set_pool("WTH")` / `set_cards("WTH")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`).
"""


# --- W1G1: the top of a graveyard as a cost ---

from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent


def _w1g1_card(name: str, type_line: str, colors: tuple = ()) -> CardDefinition:
    """A vanilla card to stack a graveyard with. The colour is what Spinning
    Darkness's cost scans for, so it is the one characteristic that varies."""
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=tuple(colors), color_identity=tuple(colors), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "2",
             "toughness": "2", "colors": list(colors)},
    )


def _w1g1_darkness(set_pool, graveyard):
    """Spinning Darkness in hand with *graveyard* behind it and a creature to
    aim at. The graveyard is bottom-first (CR 404.1: an arriving card goes on
    top, so the last element is the top card)."""
    victim = Permanent(card=_w1g1_card("Victim", "Creature — Bear"))
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("WTH")["Spinning Darkness"]],
                    graveyard=list(graveyard),
                    library=[_w1g1_card("Filler", "Artifact")] * 5),
        PlayerState(name="P2", battlefield=[victim],
                    library=[_w1g1_card("Filler", "Artifact")] * 5),
    ])
    game.start_turn(0)
    return game, victim


def test_spinning_darkness_is_cast_for_three_black_cards_and_no_mana(set_pool):
    """"You may exile the top three black cards of your graveyard rather than
    pay this spell's mana cost." (CR 118.9.)

    The mana is *never* paid — the game has no lands at all here — and the
    three cards come off the top of the pile, skipping the white card that
    happens to be above one of them. CR 118.9c leaves the printed {4}{B}{B}
    untouched; what is skipped is the payment.
    """
    game, victim = _w1g1_darkness(set_pool, [
        _w1g1_card("Black Deep", "Creature — Zombie", ("B",)),
        _w1g1_card("White Card", "Creature — Bear", ("W",)),
        _w1g1_card("Black Mid", "Creature — Zombie", ("B",)),
        _w1g1_card("Black Top", "Creature — Zombie", ("B",)),
    ])
    me = game.players[0]
    result = game.cast_from_hand(
        0, "Spinning Darkness", alternative_cost=True,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    assert sorted(card.name for card in me.exile) == [
        "Black Deep", "Black Mid", "Black Top"
    ]
    # The spell itself lands in the graveyard on resolution (CR 608.2m), so
    # the pile is read for what the *cost* left behind.
    assert [
        card.name for card in me.graveyard if card.name != "Spinning Darkness"
    ] == ["White Card"]
    if game.stack:
        game.resolve_top_of_stack()
    assert victim.damage_marked == 3
    assert me.life == 23


def test_spinning_darkness_refuses_a_pile_that_cannot_pay_in_full(set_pool):
    """CR 118.3: a cost is paid in full or not at all, and CR 601.2h then makes
    an unpayable alternative cost an *uncastable* spell — never one cast for
    nothing, which is what a partial charge would be once the mana payment has
    already been replaced."""
    game, _victim = _w1g1_darkness(set_pool, [
        _w1g1_card("Black One", "Creature — Zombie", ("B",)),
        _w1g1_card("Black Two", "Creature — Zombie", ("B",)),
    ])
    me = game.players[0]
    result = game.cast_from_hand(
        0, "Spinning Darkness", alternative_cost=True,
        target_player_index=1, target_permanent_index=0,
    )
    assert not result.supported
    assert len(me.graveyard) == 2, "the two black cards are still there"
    assert me.exile == []
    assert [card.name for card in me.hand] == ["Spinning Darkness"]


# --- W2G2: damage divided, doubled and prevented ---
from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle as _w2g2_compile


def _w2g2_vanilla(name: str, power: int, toughness: int):
    from engine.models import CardDefinition

    return CardDefinition(
        name=name, mana_cost="{1}", cmc=1.0, type_line="Creature — Bear",
        oracle_text="", colors=("G",), color_identity=("G",), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature — Bear",
             "power": str(power), "toughness": str(toughness)},
    )


def _w2g2_game(p1_hand=(), p2_board=()):
    game = Game(players=[
        PlayerState(name="P1", hand=list(p1_hand)),
        PlayerState(name="P2", battlefield=list(p2_board)),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def test_firestorm_deals_the_announced_x_to_each_of_x_targets(set_pool):
    """"As an additional cost to cast this spell, discard X cards. Firestorm
    deals X damage to each of X targets."

    One announcement doing three jobs (CR 107.3a): it prices the discard, it
    sizes the damage, and it fixes the number of targets. The check that matters
    is the *third* — the amounts have to land on the right recipients, and this
    is the shape (a cross-seat list) where an engine that only understood one
    target puts the whole spell on one face.
    """
    wth = set_pool("WTH")
    victim = Permanent(card=_w2g2_vanilla("Bear", 2, 2))
    game = _w2g2_game(
        p1_hand=[wth["Firestorm"], *[_w2g2_vanilla("Filler", 1, 1)] * 3],
        p2_board=[victim],
    )

    result = game.queue_from_hand(
        0, "Firestorm", x_value=2, divided_targets=[(1, 0), (1, None)],
    )
    assert result.supported, result.details
    assert len(game.players[0].hand) == 1, "two cards paid the additional cost"
    game.resolve_stack()

    assert victim.damage_marked == 2
    assert game.players[1].life == 18, "the face took its own 2, not the whole 4"


def test_firestorm_refuses_a_target_list_that_is_not_x_long(set_pool):
    """CR 601.2c fixes the number of targets as the spell is announced, and
    Firestorm's number is the X just announced. A shorter list is an illegal
    proposal, so CR 601.2e returns the game to before it — nothing discarded.
    """
    wth = set_pool("WTH")
    game = _w2g2_game(
        p1_hand=[wth["Firestorm"], *[_w2g2_vanilla("Filler", 1, 1)] * 3],
        p2_board=[Permanent(card=_w2g2_vanilla("Bear", 2, 2))],
    )

    result = game.queue_from_hand(
        0, "Firestorm", x_value=2, divided_targets=[(1, 0)],
    )
    assert not result.supported
    assert "exactly 2 targets" in result.details
    assert len(game.players[0].hand) == 4, "the refusal cost the caster nothing"


def test_firestorm_cannot_announce_an_x_the_hand_cannot_discard(set_pool):
    """CR 601.2h: an unpayable cost can't be paid, and the consequence is that
    the spell isn't cast — never that it is cast for less. The spell itself is
    on the stack before its costs are paid (CR 601.2a), so it is not one of the
    cards that can pay for itself.
    """
    wth = set_pool("WTH")
    game = _w2g2_game(
        p1_hand=[wth["Firestorm"], _w2g2_vanilla("Filler", 1, 1)],
        p2_board=[Permanent(card=_w2g2_vanilla("Bear", 2, 2))],
    )

    result = game.queue_from_hand(
        0, "Firestorm", x_value=2, divided_targets=[(1, 0), (1, None)],
    )
    assert not result.supported
    assert "additional cost" in result.details


def test_fatal_blow_only_reaches_a_creature_damaged_this_turn(set_pool):
    """"Destroy target creature that was dealt damage this turn."

    The simple past of Giant Shark's "has been dealt damage this turn", and the
    same record answers both — which is the whole point of the branch sharing a
    field rather than earning one.
    """
    wth = set_pool("WTH")
    program = _w2g2_compile(wth["Fatal Blow"])
    assert program.supported, program.reason
    (instruction,) = program.instructions
    assert instruction.payload["dealt_damage_this_turn"] is True
    assert instruction.payload["bypass_regeneration"] is True, (
        "the second sentence is still read"
    )

    untouched = Permanent(card=_w2g2_vanilla("Bear", 2, 2))
    game = _w2g2_game(p1_hand=[wth["Fatal Blow"]], p2_board=[untouched])
    assert not game.cast_target_spec(0, wth["Fatal Blow"])["valid_targets"], (
        "an undamaged creature is not a legal target"
    )

    untouched.metadata["was_dealt_damage_this_turn"] = True
    assert game.cast_target_spec(0, wth["Fatal Blow"])["valid_targets"]


def test_choking_vines_blocks_the_creatures_it_names_and_damages_those(set_pool):
    """"X target attacking creatures become blocked. Choking Vines deals 1
    damage to each of those creatures."

    The second sentence names what the first one chose (CR 611.2c fixed the set
    when the effect began), so the attacker nobody named is untouched — which a
    board read of "every blocked attacker" could not have got right.
    """
    wth = set_pool("WTH")
    named = [Permanent(card=_w2g2_vanilla("Bear", 2, 2)) for _ in range(2)]
    spare = Permanent(card=_w2g2_vanilla("Ox", 3, 3))
    for perm in (*named, spare):
        perm.metadata["summoning_sickness_turn"] = -99
    game = Game(players=[
        PlayerState(name="P1", battlefield=[*named, spare]),
        PlayerState(name="P2", hand=[wth["Choking Vines"]]),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()   # beginning of combat
    game.advance_combat_phase()   # declare attackers
    game.declare_attackers(0, [0, 1, 2])
    game.advance_combat_phase()   # declare blockers

    result = game.queue_from_hand(
        1, "Choking Vines", x_value=2,
        target_player_index=0, target_permanent_index=[0, 1],
    )
    assert result.supported, result.details
    game.resolve_stack()

    assert [perm.blocked for perm in named] == [True, True]
    assert [perm.damage_marked for perm in named] == [1, 1]
    assert not spare.blocked and spare.damage_marked == 0


# --- W2G1: costs charged and permissions granted ---
from engine import Game, PlayerState
from engine.cast_costs import additional_cost_for_line
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _w2g1_duel(hand=()):
    p1, p2 = PlayerState(name="A", hand=list(hand)), PlayerState(name="B")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game, p1, p2


def test_abjure_charges_the_blue_permanent_it_names(set_pool, catalog_by_name):
    """"As an additional cost to cast this spell, sacrifice a blue permanent."

    The cost table refused the phrase because it pinned no card *type*, and a
    refused cost line is a refused card (`cast_costs.unread_cost_sentence`) —
    which is the right direction, since the alternative is a counterspell cast
    for {U} and nothing else. "A blue permanent" names what may pay it exactly
    as precisely as "a creature" does; what it names is a colour.
    """
    pool = set_pool("WTH")
    cost = additional_cost_for_line(
        "As an additional cost to cast this spell, sacrifice a blue permanent."
    )
    assert cost is not None
    assert cost.sacrifice_filter == {"color_filter": "U"}
    assert compile_card_oracle(pool["Abjure"]).supported

    game, caster, victim = _w2g1_duel([pool["Abjure"]])
    blue = Permanent(card=catalog_by_name["Vodalian Soldiers"])
    caster.battlefield.append(blue)
    victim.hand = [catalog_by_name["Lightning Bolt"]]
    victim.library = [catalog_by_name["Island"]] * 4

    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    result = game.queue_from_hand(0, "Abjure", target_stack_index=0)
    game.resolve_stack()

    assert result.supported, result.details
    assert caster.battlefield == [], "the blue permanent paid for it"
    assert "Vodalian Soldiers" in [c.name for c in caster.graveyard]
    assert caster.life == 20, "and the bolt was countered"


def test_abjure_is_not_cast_with_no_blue_permanent_to_sacrifice(
    set_pool, catalog_by_name
):
    """CR 601.2h: an unpayable cost can't be paid, and casting rewinds. A green
    creature is not a legal payment, which is the whole of what the colour
    narrowing buys — dropped, this would eat the nearest thing on the board."""
    pool = set_pool("WTH")
    game, caster, victim = _w2g1_duel([pool["Abjure"]])
    green = Permanent(card=catalog_by_name["Grizzly Bears"])
    caster.battlefield.append(green)
    victim.hand = [catalog_by_name["Lightning Bolt"]]

    game.queue_from_hand(1, "Lightning Bolt", target_player_index=0)
    result = game.queue_from_hand(0, "Abjure", target_stack_index=0)

    assert not result.supported
    assert [c.name for c in caster.hand] == ["Abjure"], "still in hand"
    assert [p.card.name for p in caster.battlefield] == ["Grizzly Bears"]
    assert len(game.stack) == 1, "and the bolt is still on the stack"


# --- W2G5: enforcement, entry replacement and the last statics ---

from engine import Game, PlayerState  # noqa: E402
from engine.models import Permanent  # noqa: E402
from engine.oracle import compile_card_oracle  # noqa: E402
from engine.targeting import derive_cast_spec  # noqa: E402
from tests.helpers import _mk_card, _nosick  # noqa: E402


def _w2g5_creature(name: str, type_line: str = "Creature - Bear"):
    return _nosick(Permanent(card=_mk_card(name, type_line)))


def test_boiling_blood_forces_the_chosen_creature_to_attack(set_pool):
    """"Target creature attacks this turn if able. Draw a card."

    The card compiled to its **second** line alone: the production that reads
    the requirement existed for Kookus' trailing "…and attacks this turn if
    able" and nothing had ever asked it at the head of a sentence, so the whole
    first line was dropped and Boiling Blood was a two-mana cantrip. CR 508.1a's
    requirement now rides the same ``must_attack_until_eot`` mark the declare
    step already reads.
    """
    blood = set_pool("WTH")["Boiling Blood"]
    lazy = _w2g5_creature("Lazy Bear")
    idle = _w2g5_creature("Idle Ogre", "Creature - Ogre")
    game = Game(players=[
        # A library, because the second line of this card draws: an empty one
        # makes its controller lose at the next state-based check and the
        # combat this test is about never happens.
        PlayerState(
            name="P0", hand=[blood], library=[_mk_card("Top", "Land")] * 3
        ),
        PlayerState(name="P1", battlefield=[lazy, idle]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    # Cast on the *defender's* turn, because "this turn" is the window the
    # requirement lives in: on any other turn the mark is swept before the
    # creature is ever asked to attack.
    game.start_turn(1)
    game._close_current_priority_step()

    result = game.cast_from_hand(
        0, "Boiling Blood", target_player_index=1,
        target_permanent_index=game.battlefield_index_of(lazy),
    )
    game.resolve_stack()

    assert result.supported, result.details
    assert lazy.metadata.get("must_attack_until_eot") is True, game.log
    assert idle.metadata.get("must_attack_until_eot") is None, game.log

    game.advance_combat_phase()
    game.advance_combat_phase()
    refused, why = game.declare_attackers(1, [])
    assert not refused, "the requirement was not enforced"
    assert "Lazy Bear" in why
    assert game.declare_attackers(1, [game.battlefield_index_of(lazy)])[0]


def test_boiling_blood_still_draws_its_card(set_pool):
    """The line that used to be the whole card, kept — a round that teaches a
    sentence to parse can just as easily take the sentence beside it away."""
    blood = set_pool("WTH")["Boiling Blood"]
    bear = _w2g5_creature("Lazy Bear")
    game = Game(players=[
        PlayerState(name="P0", hand=[blood], library=[_mk_card("Top", "Land")] * 3),
        PlayerState(name="P1", battlefield=[bear]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    game.cast_from_hand(
        0, "Boiling Blood", target_player_index=1,
        target_permanent_index=0,
    )
    game.resolve_stack()

    assert [c.name for c in game.players[0].hand] == ["Top"], game.log


def test_boiling_blood_offers_a_creature_picker(set_pool):
    """The Roots class: a supported card the client sends a *bare* cast for,
    because the derivation answered None. It answers now, and it answers
    "creature" — the printed noun — rather than "any target"."""
    blood = set_pool("WTH")["Boiling Blood"]

    spec = derive_cast_spec(blood, compile_card_oracle(blood))

    assert spec is not None and spec.get("kind") == "creature"


def test_urborg_justice_sacrifices_one_creature_per_creature_you_lost(set_pool):
    """"Target opponent sacrifices a creature of their choice **for each
    creature put into your graveyard from the battlefield this turn**."

    The multiplier counts the *caster's* graveyard (CR 400.3's owner), so it
    rides the shared count channel rather than the per-payer one beside it —
    read per payer the spell would size itself from the sacrificing opponent's
    own losses and ask for nothing whenever they had lost nothing.
    """
    justice = set_pool("WTH")["Urborg Justice"]
    mine = [_w2g5_creature(f"Mine{i}") for i in range(2)]
    theirs = [_w2g5_creature(f"Theirs{i}", "Creature - Ogre") for i in range(4)]
    me = PlayerState(name="P0", hand=[justice], battlefield=mine)
    them = PlayerState(name="P1", battlefield=theirs)
    game = Game(players=[me, them])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    for perm in list(mine):
        game.remove_from_battlefield(perm)
        game._permanent_to_graveyard(me, perm)

    game.cast_from_hand(0, "Urborg Justice", target_player_index=1)
    game.resolve_stack()
    game._settle()

    assert len(them.battlefield) == 2, game.log
    assert len(them.graveyard) == 2, game.log


def test_urborg_justice_asks_for_nothing_when_you_lost_nothing(set_pool):
    """Zero is a legal answer and no prompt: CR 608.2 does as much as possible,
    and a seat that owes none is not asked."""
    justice = set_pool("WTH")["Urborg Justice"]
    theirs = [_w2g5_creature(f"Theirs{i}", "Creature - Ogre") for i in range(4)]
    them = PlayerState(name="P1", battlefield=theirs)
    game = Game(players=[
        PlayerState(name="P0", hand=[justice]), them,
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()

    game.cast_from_hand(0, "Urborg Justice", target_player_index=1)
    game.resolve_stack()
    game._settle()

    assert len(them.battlefield) == 4, game.log
    assert them.graveyard == [], game.log


def _w2g5_abeyance_game(set_pool):
    """Seat 0 casts Abeyance at seat 1, who holds an instant, a creature spell,
    an Icy Manipulator and a Forest."""
    from engine.card_loader import load_cards, manifest_set_path

    lea = {c.name: c for c in load_cards([manifest_set_path("LEA")])}
    victim = PlayerState(
        name="P1",
        hand=[
            _mk_card("Test Bolt", "{R}", "Instant", "Test Bolt deals 3 damage to any target."),
            _mk_card("Test Bear", "{1}{G}", "Creature - Bear", ""),
        ],
        battlefield=[
            _nosick(Permanent(card=lea["Icy Manipulator"])),
            Permanent(card=lea["Forest"]),
        ],
        library=[_mk_card("Top", "Land")] * 4,
    )
    caster = PlayerState(
        name="P0",
        hand=[set_pool("WTH")["Abeyance"]],
        battlefield=[Permanent(card=lea["Forest"])],
        library=[_mk_card("Top", "Land")] * 4,
    )
    game = Game(players=[caster, victim])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    result = game.cast_from_hand(0, "Abeyance", target_player_index=1)
    assert result.supported, result.details
    game.resolve_stack()
    return game, victim


def test_abeyance_stops_the_named_seats_instants_and_sorceries(set_pool):
    """"Until end of turn, target player can't cast instant or sorcery spells."

    CR 601.3a for one seat, and the whole line used to be dropped: the ``can't``
    dispatcher handed it to the combat production, which refuses everything it
    does not recognize with "expected 'be'" — a word this sentence never prints
    — so Abeyance compiled to "Draw a card." alone and was a two-mana cantrip
    that reported supported.
    """
    game, _victim = _w2g5_abeyance_game(set_pool)

    assert not game.cast_from_hand(1, "Test Bolt", target_player_index=0).supported


def test_abeyance_leaves_the_spell_types_it_does_not_name(set_pool):
    """The types are the narrowing, so a creature spell is unaffected — a ban
    that reached every spell would be a much larger card."""
    game, victim = _w2g5_abeyance_game(set_pool)

    assert game.cast_from_hand(1, "Test Bear").supported
    assert any(p.card.name == "Test Bear" for p in victim.battlefield), game.log


def test_abeyance_stops_a_non_mana_activated_ability(set_pool):
    """"…and that player can't activate abilities that aren't mana abilities."

    CR 602.5a, refused before any cost is paid — the Icy Manipulator is still
    untapped afterwards.
    """
    game, victim = _w2g5_abeyance_game(set_pool)
    icy = victim.battlefield[0]

    result = game.activate_permanent_ability(
        1, "Icy Manipulator", target_player_index=0, target_permanent_index=0
    )

    assert not result.supported
    assert "mana abilities" in game.log[-1], game.log[-1]
    assert not icy.tapped, "the cost was paid for a refused activation"


def test_abeyance_leaves_mana_abilities_alone(set_pool):
    """The exception names a **rule** (CR 605.1), not a card type — so it is
    asked of the engine's one ``is_mana_ability`` reader over the compiled
    instruction rather than of a second list of which permanents make mana."""
    from engine.card_loader import load_cards, manifest_set_path
    from engine.spell_prohibitions import forbid_nonmana_activations_this_turn

    lea = {c.name: c for c in load_cards([manifest_set_path("LEA")])}
    seat = PlayerState(
        name="P1", battlefield=[_nosick(Permanent(card=lea["Birds of Paradise"]))]
    )
    game = Game(players=[PlayerState(name="P0"), seat])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    forbid_nonmana_activations_this_turn(game, 1)

    assert game.activate_permanent_ability(1, "Birds of Paradise").supported
    assert sum(seat.mana_pool.values()) == 1, game.log


def test_abeyance_expires_with_the_turn(set_pool):
    """"**Until end of turn**." A prohibition that outlived its turn is a seat
    that quietly stops casting, which is why both records are dropped in the
    same turn-boundary sweep the land-play ones use."""
    game, _victim = _w2g5_abeyance_game(set_pool)
    assert not game.cast_from_hand(1, "Test Bolt", target_player_index=0).supported

    game.start_turn(1)

    assert game.cast_from_hand(1, "Test Bolt", target_player_index=0).supported


def test_abeyance_offers_a_player_picker(set_pool):
    """The Roots class again: the sentence that carries the target was the one
    being dropped, so ``derive_cast_spec`` answered None and the client sent a
    bare cast the engine refused."""
    from engine.oracle import compile_card_oracle

    abeyance = set_pool("WTH")["Abeyance"]

    spec = derive_cast_spec(abeyance, compile_card_oracle(abeyance))

    assert spec is not None and spec.get("kind") == "player"


def test_abeyance_names_one_player_not_two(set_pool):
    """"…and **that player**" is a back-reference to the seat the sentence in
    front of it already chose (CR 601.2c fixes one target), so the second clause
    carries no target description of its own — a second one would raise a second
    picker for a player the caster has already named."""
    from engine.oracle import compile_card_oracle

    program = compile_card_oracle(set_pool("WTH")["Abeyance"])
    steps = program.instructions[0].payload["steps"]

    assert [step.kind for step in steps] == [
        "forbid_casting_types_this_turn", "forbid_nonmana_activations_this_turn",
    ]
    assert "targets" in steps[0].payload
    assert "targets" not in steps[1].payload

# --- end W2G5 ---


# --- W2G3: phasing and end of combat ---
from engine import Game, PlayerState
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle


def _w2g3i_creature(name, power, toughness) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _w2g3i_debt(set_pool):
    """Debt of Loyalty in hand, an opponent's creature to point it at."""
    victim = Permanent(card=_w2g3i_creature("Victim", 2, 2))
    victim.summoning_sick = False
    game = Game(players=[
        PlayerState(name="P1", hand=[set_pool("WTH")["Debt of Loyalty"]]),
        PlayerState(name="P2", battlefield=[victim]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    result = game.cast_from_hand(
        0, "Debt of Loyalty", target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result
    for _ in range(20):
        if not game.stack:
            break
        game.resolve_top_of_stack()
    return game, victim


def test_debt_of_loyalty_delays_the_steal_until_the_shield_is_spent(set_pool):
    """"Regenerate target creature. You gain control of that creature **if it
    regenerates this way**." (CR 603.7, CR 701.19c.)

    The trailing "if" is a delay, not a condition on this resolution — CR 701.19c
    is explicit that creating a regeneration shield is not regenerating, so a
    reading that asked the question now would answer no on every board and the
    control change would never happen at all.

    The entry binds the spell's **target**, not its source: the source is an
    instant that is in a graveyard by the time the shield is spent, and
    CR 603.7d's own-source default would watch it.
    """
    program = compile_card_oracle(set_pool("WTH")["Debt of Loyalty"])
    assert program.supported, program.reason
    (sequence,) = program.instructions
    _regen, delay = sequence.payload["steps"]
    assert delay.payload["event"] == "source_regenerates"
    assert delay.payload["instruction"].kind == "gain_control_of_bound_permanent"
    assert delay.payload["binds_target"] is True

    game, victim = _w2g3i_debt(set_pool)
    assert victim.regeneration_shield == 1
    (entry,) = game.delayed_triggers
    assert entry.bound_permanent_id == victim.permanent_id
    assert game.controller_index_of(victim) == 1


def test_debt_of_loyalty_takes_the_creature_when_it_regenerates(set_pool):
    """The shield spent is the event, and the control change follows it."""
    game, victim = _w2g3i_debt(set_pool)

    game._destroy_swept_permanents(game.players[1], lambda p: p is victim)
    for _ in range(20):
        if not game.stack:
            break
        game.resolve_top_of_stack()
    game._settle()

    assert game.controller_index_of(victim) == 0, game.log
    assert victim in game.players[0].battlefield
    assert victim not in game.players[1].battlefield


def test_debt_of_loyalty_takes_nothing_if_the_creature_is_never_destroyed(set_pool):
    """The half the printed "if" is for.

    A card that gained control on resolution would be a strictly better spell
    than the one printed, and nothing in the compiled program would look wrong:
    the steal happens, the log says so, and the creature simply changes hands a
    turn early and unconditionally.
    """
    game, victim = _w2g3i_debt(set_pool)
    game._settle()

    assert game.controller_index_of(victim) == 1, game.log
    assert victim in game.players[1].battlefield


# --- Closer: Desperate Gambit ---

import random as _closer_random

import pytest as _closer_pytest

from engine import Game as _CloserGame, PlayerState as _CloserPlayerState
from engine.damage_events import deal_damage as _closer_deal_damage
from engine.models import (CardDefinition as _CloserCardDefinition,
                           Permanent as _CloserPermanent)
from engine.next_damage import (DAMAGE_DOUBLED_NEXT as _CLOSER_DOUBLED,
                                DAMAGE_PREVENTED_NEXT as _CLOSER_PREVENTED)
from engine.oracle import compile_card_oracle as _closer_compile


def _closer_vanilla(name: str, type_line: str = "Creature — Bear"):
    """A card with no text at all, so nothing but the Gambit is in play."""
    return _CloserCardDefinition(
        name=name, mana_cost="{2}", cmc=2.0, type_line=type_line, oracle_text="",
        colors=("G",), color_identity=("G",), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": "2", "toughness": "2"},
    )


def _closer_gambit_game(set_pool, sources: int = 1):
    """The Gambit in hand, *sources* permanents under it, and a creature to aim
    the damage at. Mana is stocked because the card's cost is not the subject."""
    mine = [
        _CloserPermanent(card=_closer_vanilla(f"Pinger{index}"))
        for index in range(sources)
    ]
    for permanent in mine:
        permanent.metadata["summoning_sick"] = False
    victim = _CloserPermanent(card=_closer_vanilla("Victim"))
    game = _CloserGame(players=[
        _CloserPlayerState(
            name="P1", hand=[set_pool("WTH")["Desperate Gambit"]],
            battlefield=list(mine), library=[_closer_vanilla("Filler")] * 5,
        ),
        _CloserPlayerState(
            name="P2", battlefield=[victim],
            library=[_closer_vanilla("Filler")] * 5,
        ),
    ])
    game.start_turn(0)
    for symbol in ("W", "U", "B", "R", "G", "C"):
        game.players[0].mana_pool[symbol] = 5
    return game, (mine[0] if mine else None), victim


def _closer_cast(game, *, win: bool):
    """Cast the Gambit with the coin forced. CR 705.2: the flipping player wins
    the flip when their call matches, so a forced coin is a forced branch."""
    real = _closer_random.random
    _closer_random.random = lambda: 0.0 if win else 0.99
    try:
        result = game.cast_from_hand(0, "Desperate Gambit")
        assert result.supported, result.details
        for _ in range(20):
            if not game.stack:
                break
            game.resolve_top_of_stack()
        game._settle()
    finally:
        _closer_random.random = real


def test_desperate_gambit_compiles_to_a_choice_a_flip_and_two_branches(set_pool):
    """The whole printed line, as four steps of one resolution.

    What this pins is that the two branches read the choice the *first* step
    made rather than each choosing again: both carry the same ``source_from``
    key, which is the record ``choose_permanent`` writes. Two independent
    choices would be a card that could double one source's damage and prevent
    another's off one coin flip.
    """
    program = _closer_compile(set_pool("WTH")["Desperate Gambit"])
    assert program.supported
    (sequence,) = program.instructions
    choose, flip, won, lost = sequence.payload["steps"]

    assert choose.kind == "choose_permanent"
    assert choose.payload["filter"] == {"controller": "you"}
    assert choose.payload["chooser"] == "you"
    assert flip.kind == "flip_coin"

    assert won.payload["condition"] == {"kind": "coin_flip", "won": True}
    (doubled,) = won.payload["then"]
    assert doubled.kind == "double_next_damage_from_chosen_source"

    assert lost.payload["condition"] == {"kind": "coin_flip", "won": False}
    (prevented,) = lost.payload["then"]
    assert prevented.kind == "prevent_next_damage_from_chosen_source"

    assert doubled.payload["source_from"] == choose.payload["result_key"]
    assert prevented.payload["source_from"] == choose.payload["result_key"]


def test_winning_the_flip_doubles_the_chosen_sources_next_damage(set_pool):
    game, pinger, victim = _closer_gambit_game(set_pool)
    _closer_cast(game, win=True)

    assert pinger.metadata[_CLOSER_DOUBLED] == 1
    outcome = _closer_deal_damage(game, {
        "recipient": game.players[1], "amount": 3, "source": pinger,
        "combat": False,
    })
    assert outcome.dealt == 6, game.log


def test_only_the_next_damage_is_doubled(set_pool):
    """"The **next** time" is one event, however many follow it. A rider spent
    by points rather than by instances would double the whole turn."""
    game, pinger, victim = _closer_gambit_game(set_pool)
    _closer_cast(game, win=True)
    event = {"recipient": game.players[1], "amount": 3, "source": pinger,
             "combat": False}

    assert _closer_deal_damage(game, dict(event)).dealt == 6
    assert _closer_deal_damage(game, dict(event)).dealt == 3
    assert _CLOSER_DOUBLED not in pinger.metadata


def test_losing_the_flip_prevents_the_chosen_sources_next_damage(set_pool):
    game, pinger, victim = _closer_gambit_game(set_pool)
    _closer_cast(game, win=False)

    assert pinger.metadata[_CLOSER_PREVENTED] == 1
    outcome = _closer_deal_damage(game, {
        "recipient": game.players[1], "amount": 3, "source": pinger,
        "combat": False,
    })
    assert outcome.dealt == 0, game.log


def test_only_the_next_damage_is_prevented(set_pool):
    game, pinger, victim = _closer_gambit_game(set_pool)
    _closer_cast(game, win=False)
    event = {"recipient": game.players[1], "amount": 3, "source": pinger,
             "combat": False}

    assert _closer_deal_damage(game, dict(event)).dealt == 0
    assert _closer_deal_damage(game, dict(event)).dealt == 3
    assert _CLOSER_PREVENTED not in pinger.metadata


@_closer_pytest.mark.parametrize("win,expected", [(True, 4), (False, 0)])
def test_the_rider_follows_the_source_and_not_a_recipient(set_pool, win, expected):
    """Neither branch names anything the damage is dealt *to*, so a creature on
    the other side of the table is covered exactly as the player is.

    A shield hung on a recipient would leave this event untouched, and the card
    would read as working for as long as every test aimed at a face.
    """
    game, pinger, victim = _closer_gambit_game(set_pool)
    _closer_cast(game, win=win)

    outcome = _closer_deal_damage(game, {
        "recipient": victim, "amount": 2, "source": pinger, "combat": True,
    })
    assert outcome.dealt == expected, game.log


def test_another_source_is_untouched(set_pool):
    """"That source" is one object. The rider lives on it, so nothing else in
    the game — including the opponent's creature dealing damage back — reads it.
    """
    game, pinger, victim = _closer_gambit_game(set_pool)
    _closer_cast(game, win=True)

    outcome = _closer_deal_damage(game, {
        "recipient": game.players[0], "amount": 3, "source": victim,
        "combat": True,
    })
    assert outcome.dealt == 3, game.log


def test_an_unspent_rider_expires_with_the_turn(set_pool):
    """CR 615.3's duration, and the CR 614 half beside it: "this turn" is the
    cleanup sweep, so a source that dealt no damage carries nothing into the
    next turn."""
    game, pinger, victim = _closer_gambit_game(set_pool)
    _closer_cast(game, win=True)
    assert pinger.metadata[_CLOSER_DOUBLED] == 1

    game.resolve_cleanup_step(0)
    game.start_turn(1)

    assert _CLOSER_DOUBLED not in pinger.metadata
    outcome = _closer_deal_damage(game, {
        "recipient": game.players[1], "amount": 3, "source": pinger,
        "combat": False,
    })
    assert outcome.dealt == 3, game.log


def test_a_controller_with_no_permanents_arms_nothing(set_pool):
    """CR 608.2's "as much as possible": the flip still happens and the spell
    still resolves, and the branch has no source to hang its rider on.

    The assertion is that nothing is armed **anywhere** — an implementation that
    fell back to "any source", as the sourceless prevention charges elsewhere in
    this engine legitimately do, would here prevent or double the next damage
    event in the game whoever dealt it.
    """
    game, _, victim = _closer_gambit_game(set_pool, sources=0)
    _closer_cast(game, win=False)

    assert "Desperate Gambit: no source was chosen" in game.log
    for permanent in game.all_permanents():
        assert _CLOSER_PREVENTED not in permanent.metadata
        assert _CLOSER_DOUBLED not in permanent.metadata
    outcome = _closer_deal_damage(game, {
        "recipient": game.players[0], "amount": 3, "source": victim,
        "combat": True,
    })
    assert outcome.dealt == 3, game.log
