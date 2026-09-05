"""Rules tests earned by Visions wave 2, group 2 — continuous statics and
printed restrictions.

Each of these is about a Comprehensive Rule rather than about a card, which is
what puts it here instead of in ``tests/sets/``; the cards that provoked them
are named in the docstrings and have their own per-card tests beside their set.

The family's failure mode is never a crash and never a missing ability — it is
an ability that works **more often than the card allows**, wrong in the
player's favour and silent. So every test here watches a refusal happen rather
than watching a payload exist.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path, manifest_set_paths
from engine.combat_restrictions import combat_restriction_for
from engine.grammar import compile_line
from engine.models import Permanent
from engine.oracle import compile_card_oracle, normalize_creature_line


def _catalog():
    return {
        card.name: card
        for card in load_cards(manifest_set_paths(include_measured=True))
    }


def _pool(code):
    return {
        card.name: card
        for card in load_cards(manifest_set_path(code, include_measured=True))
    }


def _game(*battlefields, hands=None):
    players = [
        PlayerState(
            name=f"P{index + 1}",
            battlefield=list(pile),
            hand=list((hands or {}).get(index, [])),
        )
        for index, pile in enumerate(battlefields)
    ]
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for player in players:
        for permanent in player.battlefield:
            permanent.metadata["summoning_sickness_turn"] = -99
    return game


def _index_of(player, permanent):
    """The battlefield slot *permanent* sits in, found by identity.

    Never ``list.index``: ``Permanent`` compares by value, so a second copy of
    the same card answers first (tests/engine/test_control_reads.py).
    """
    return next(i for i, perm in enumerate(player.battlefield) if perm is permanent)


# ---------------------------------------------------------------------------
# CR 509.1c — a blocking requirement narrowed by a keyword
# ---------------------------------------------------------------------------


@pytest.mark.cr("509.1c", "509.1b")
def test_a_lure_requirement_compels_only_the_creatures_its_noun_phrase_names():
    """CR 509.1c counts requirements against the *maximum* obeyable without
    breaking a restriction — so a requirement over a narrowed set must compel
    exactly that set and nobody else.

    Talruum Piper's "All creatures **with flying** able to block this creature
    do so" is Lure narrowed by an ability rather than by a printed
    characteristic, which is why the noun phrase is a filter and not a subtype
    word: the two rows this replaced could spell "Walls" and "creatures" and
    had nothing to put a keyword in.
    """
    catalog = _catalog()
    piper = Permanent(card=_pool("VIS")["Talruum Piper"])
    flier = Permanent(card=catalog["Air Elemental"])
    ground = Permanent(card=catalog["Grizzly Bears"])
    game = _game([piper], [flier, ground])

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [_index_of(game.players[0], piper)])[0]
    game.advance_combat_phase()

    # The flier is compelled; blocking with nobody is an illegal declaration.
    declared, message = game.declare_blockers(1, {})
    assert not declared, game.log
    assert "must block" in message, message

    # The ground creature is not: a declaration with only the flier obeys the
    # maximum number of requirements CR 509.1c can count.
    declared, message = game.declare_blockers(
        1, {_index_of(game.players[1], flier): [_index_of(game.players[0], piper)]}
    )
    assert declared, (message, game.log)


@pytest.mark.cr("509.1c")
def test_a_lure_requirement_refuses_a_noun_phrase_nothing_can_test():
    """The row ends in ``.+``, so a phrase the noun reader cannot read must
    refuse the whole line rather than reaching the blockers step as an empty
    filter — which would compel *every* creature, turning Talruum Piper into
    Lure.

    The positive cases all pass either way; this is the assertion that says the
    catch-all is not one.
    """
    assert combat_restriction_for(
        "all creatures with flying able to block this creature do so"
    ) is not None
    for phrase in (
        "creatures with three heads",
        "creatures that like cheese",
        "shiny things",
    ):
        assert combat_restriction_for(
            f"all {phrase} able to block this creature do so"
        ) is None, phrase


# ---------------------------------------------------------------------------
# CR 508.1c / 509.1b — a board-wide prohibition over a described set
# ---------------------------------------------------------------------------


@pytest.mark.cr("508.1c", "509.1b")
def test_one_sentence_may_forbid_attacking_and_blocking_over_one_noun_phrase():
    """CR 508.1c and CR 509.1b are two separate checks in two separate steps,
    so a sentence that forbids both has to reach both.

    Katabatic Winds prints all of it once — "Creatures with flying can't attack
    or block, and their activated abilities with {T} in their costs can't be
    activated" — over one noun phrase. One derivation row arms three kinds
    (``CombatRestriction.also_kinds``) so the subject is read once and the
    three enforcement sites cannot come to disagree about which creatures it
    names.
    """
    catalog = _catalog()
    winds = Permanent(card=_pool("VIS")["Katabatic Winds"])
    flier = Permanent(card=catalog["Birds of Paradise"])
    ground = Permanent(card=catalog["Grizzly Bears"])
    # The enchantment on the *other* battlefield: it has phasing, and its own
    # controller's untap step would phase it out before the first declaration.
    game = _game([flier, ground], [winds])
    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()

    assert not game.declare_attackers(0, [_index_of(game.players[0], flier)])[0]
    assert game.declare_attackers(0, [_index_of(game.players[0], ground)])[0]

    attacker = Permanent(card=catalog["Hill Giant"])
    blocking = _game([flier, ground], [winds, attacker])
    assert not blocking._can_block_attacker(flier, attacker)
    assert blocking._can_block_attacker(ground, attacker)


@pytest.mark.cr("602.5", "602.5a")
def test_a_board_wide_static_can_shut_off_tap_abilities_of_a_described_set():
    """CR 602.5: a player can't begin to activate an ability that's prohibited
    from being activated.

    The narrowing Katabatic Winds prints is on the ability's **cost** ("with
    {T} in their costs"), which is the same axis CR 602.5a reads and a
    different one from Faith's Fetters' mana-ability exception. Reading one as
    the other is the whole difference between the two cards: a Birds of
    Paradise under Katabatic Winds may not tap for mana, and under Faith's
    Fetters it may.
    """
    catalog = _catalog()
    winds = Permanent(card=_pool("VIS")["Katabatic Winds"])
    flier = Permanent(card=catalog["Birds of Paradise"])
    game = _game([flier], [winds])
    game.start_turn(0)

    refused = game.activate_permanent_ability(0, "Birds of Paradise", mana_color="G")

    assert not refused.supported, game.log
    assert "Katabatic Winds" in refused.details, refused.details
    assert game.players[0].mana_pool.get("G", 0) == 0

    # And nothing is prohibited with the enchantment gone.
    alone = _game([Permanent(card=catalog["Birds of Paradise"])], [])
    alone.start_turn(0)
    assert alone.activate_permanent_ability(0, "Birds of Paradise", mana_color="G").supported


@pytest.mark.cr("508.1c")
def test_the_static_cant_attack_reads_the_same_in_both_front_ends():
    """A durationless "<noun phrase> can't attack" is a static ability, and the
    grammar now claims the sentence so that a duration printed in *front* of it
    has a node to attach to (Peace Talks).

    A line two front ends read is only safe while they read it the same way, so
    the grammar must produce the derivation table's instruction and payload
    exactly — which is what ``test_grammar_derived_lines`` asserts over the
    whole shipped pool and what this pins for the three printed spellings.
    """
    for line in (
        "Creatures without flying can't attack.",
        "Creatures you control can't attack.",
        "Non-Eye creatures you control can't attack.",
    ):
        derived = combat_restriction_for(normalize_creature_line(line))
        compiled = compile_line(line)
        assert derived is not None, line
        assert [(i.kind, i.payload) for i in compiled.instructions] == [
            (derived.kind, derived.payload)
        ], line


@pytest.mark.cr("508.1c")
def test_a_creatures_own_cant_attack_line_still_refuses_the_parser():
    """The durationless claim above is for a **plural** subject only.

    "This creature can't attack" is a restriction on one permanent with its own
    instruction kind and no grammar production, and "can't attack **or block**"
    is a longer sentence the derivation table reads whole — so stopping at
    "attack" would take three prohibitions down to one. Both must keep failing
    the parser.
    """
    assert compile_line("This creature can't attack.").parse_error is not None
    assert compile_line(
        "Creatures with flying can't attack or block, and their activated "
        "abilities with {T} in their costs can't be activated."
    ).parse_error is not None


# ---------------------------------------------------------------------------
# CR 613.1f / 702.16b — a board-wide protection grant
# ---------------------------------------------------------------------------


@pytest.mark.cr("613.1f", "702.16b")
def test_a_lord_may_grant_protection_from_a_quality_at_layer_six():
    """CR 613.1f applies ability-adding effects at layer 6, and CR 702.16b is
    what the granted ability then does.

    Righteous War grants it over a *described set* ("White creatures you
    control"), so the grant is derived from the source on every read and ends
    when the source leaves with nothing to clear. The derivation table has read
    this sentence since Feline Sovereign; the grammar refused it at lowering,
    and a lowering error does not fall through to the table on the noncreature
    path — so the enchantment printings reported unsupported while the creature
    printings worked.
    """
    catalog = _catalog()
    war = Permanent(card=_pool("VIS")["Righteous War"])
    white = Permanent(card=catalog["Savannah Lions"])
    black = Permanent(card=catalog["Bog Wraith"])
    opposing_white = Permanent(card=catalog["Savannah Lions"])
    game = _game([war, white, black], [opposing_white])

    assert ("color", "B") in game._protection_qualities(white)
    assert ("color", "W") in game._protection_qualities(black)
    # "You control" scopes it: the opponent's white creature gets nothing.
    assert game._protection_qualities(opposing_white) == set()

    # And it is derived, not stamped: the grant is gone with the source.
    game.remove_from_battlefield(war)
    assert game._protection_qualities(white) == set()


@pytest.mark.cr("702.16a", "613.1f")
def test_a_protection_quality_no_shield_can_answer_refuses_the_anthem():
    """CR 702.16a's quality "can be any characteristic value or information",
    and this engine models four families of it.

    A word outside them makes the grant *inert* rather than unreadable, which
    is an anthem that compiles, reports supported and protects nobody — so both
    front ends refuse the line instead. Asked of both, because a gate only one
    of them has is a gate a card can walk around by being printed on the other
    kind of permanent.
    """
    from engine.lord_buffs import lord_buff_for

    assert lord_buff_for(
        "white creatures you control have protection from black"
    ) is not None
    assert lord_buff_for(
        "white creatures you control have protection from bananas"
    ) is None
    assert compile_line(
        "White creatures you control have protection from bananas."
    ).instructions == ()


# ---------------------------------------------------------------------------
# CR 508.1g — an attack toll priced off the attacker's own counters
# ---------------------------------------------------------------------------


@pytest.mark.cr("508.1g", "122.1a")
def test_an_attack_toll_may_be_priced_by_the_attackers_own_counters():
    """CR 508.1g's cost is determined as attackers are declared, so a price
    read off the board is answerable there and only there.

    Phyrexian Marauder's "{1} for each +1/+1 counter on it" is the multiplier;
    CR 122.1a is the counter it counts. The gate and the charge go through one
    reader, so a declaration cannot be approved at one price and billed at
    another.
    """
    from engine.pt import add_pt_counters

    catalog = _catalog()

    def board(counters, mountains):
        marauder = Permanent(card=_pool("VIS")["Phyrexian Marauder"])
        if counters:
            add_pt_counters(marauder, "+1/+1", counters)
        lands = [Permanent(card=catalog["Mountain"]) for _ in range(mountains)]
        game = _game([marauder, *lands], [])
        game.start_turn(0)
        game._close_current_priority_step()
        game.advance_combat_phase()
        game.advance_combat_phase()
        return game, marauder, lands

    game, marauder, lands = board(3, 3)
    assert game._attack_mana_costs_of(marauder, 1) == [{"generic": 3}]
    assert game.declare_attackers(0, [_index_of(game.players[0], marauder)])[0]
    assert sum(land.tapped for land in lands) == 3, game.log

    # One short is a refused declaration with nothing spent.
    game, marauder, lands = board(3, 2)
    declared, _ = game.declare_attackers(0, [_index_of(game.players[0], marauder)])
    assert not declared, game.log
    assert not any(land.tapped for land in lands)

    # And "for each" at zero is zero owed, not a cost of {1}.
    game, marauder, _ = board(0, 0)
    assert game._attack_mana_costs_of(marauder, 1) == []


# ---------------------------------------------------------------------------
# CR 601.3 / 602.5 — a board-wide own-turn-only window
# ---------------------------------------------------------------------------


@pytest.mark.cr("601.3", "602.5", "117.1a")
def test_a_permanent_may_restrict_every_players_casting_and_activating_window():
    """CR 601.3 lets an effect prohibit a player from *beginning* to cast, and
    CR 602.5 does the same for activating; CR 117.1a is the window they narrow.

    City of Solitude's one printed sentence says both, so both gates ask one
    reader — claiming the casting half alone would ship an enchantment that
    stops a Counterspell and lets an Icy Manipulator through, which is not the
    card. The sentence names no seat, so it binds its own controller too.
    """
    catalog = _catalog()
    city = Permanent(card=_pool("VIS")["City of Solitude"])
    icy = Permanent(card=catalog["Icy Manipulator"])
    bear = Permanent(card=catalog["Grizzly Bears"])
    game = _game([city, icy], [bear], hands={0: [catalog["Lightning Bolt"]]})
    # P2's turn: the enchantment's own controller is the one being stopped.
    game.start_turn(1)

    cast = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)
    assert not cast.supported, game.log
    assert "City of Solitude" in cast.details, cast.details

    activation = game.activate_permanent_ability(
        0, "Icy Manipulator", target_player_index=1, target_permanent_index=0
    )
    assert not activation.supported, game.log
    assert "City of Solitude" in activation.details, activation.details
    assert not bear.tapped


@pytest.mark.cr("601.3", "602.5")
def test_the_own_turn_window_leaves_the_active_player_alone():
    """The restriction is a *window*, not a ban: the same seat acts freely on
    its own turn. A gate that refused both turns would be a card nobody could
    play around, which is the over-restricting direction this file watches for.
    """
    catalog = _catalog()
    city = Permanent(card=_pool("VIS")["City of Solitude"])
    icy = Permanent(card=catalog["Icy Manipulator"])
    bear = Permanent(card=catalog["Grizzly Bears"])
    game = _game([city, icy], [bear], hands={0: [catalog["Lightning Bolt"]]})
    game.start_turn(0)

    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    assert game.activate_permanent_ability(
        0, "Icy Manipulator", target_player_index=1, target_permanent_index=0
    ).supported
    assert bear.tapped


# ---------------------------------------------------------------------------
# CR 115.1a / 611.2a / 514.2 — a targeting ban with a two-turn window
# ---------------------------------------------------------------------------


@pytest.mark.cr("115.1a", "601.2c")
def test_a_targeting_ban_stops_a_spell_that_names_a_player_as_well_as_one_that_names_a_permanent():
    """CR 601.2c chooses targets as a spell is cast and CR 115.1a is what
    "target" means, so a ban on being chosen has to reach a spell aimed at a
    **face** as surely as one aimed at a permanent.

    That is the half a permanent-only reader misses: a Lightning Bolt at a
    player names no permanent, so every check keyed on a named permanent index
    passed it straight through.
    """
    catalog = _catalog()
    peace = _pool("VIS")["Peace Talks"]
    bear = Permanent(card=catalog["Grizzly Bears"])
    hand = [peace, catalog["Lightning Bolt"], catalog["Lightning Bolt"]]
    game = _game([bear], [Permanent(card=catalog["Hill Giant"])], hands={0: hand})
    game.start_turn(0)

    assert game.cast_from_hand(0, "Peace Talks").supported, game.log

    at_face = game.cast_from_hand(0, "Lightning Bolt", target_player_index=1)
    assert not at_face.supported, game.log
    assert game.players[1].life == 20

    at_permanent = game.cast_from_hand(
        0, "Lightning Bolt", target_player_index=1, target_permanent_index=0
    )
    assert not at_permanent.supported, game.log


@pytest.mark.cr("611.2a", "514.2")
def test_a_stated_two_turn_window_survives_exactly_one_cleanup():
    """CR 611.2a: a continuous effect lasts as long as the spell creating it
    says. "This turn and next turn" says *two*, and CR 514.2's cleanup is where
    a turn ends — so the sweep counts down instead of clearing.

    Reading the phrase as "this turn" would end both of Peace Talks' clauses a
    whole turn early, which is the half of the card its caster paid for.
    """
    catalog = _catalog()
    peace = _pool("VIS")["Peace Talks"]
    bear = Permanent(card=catalog["Grizzly Bears"])
    hill = Permanent(card=catalog["Hill Giant"])
    hands = {0: [peace, catalog["Lightning Bolt"]], 1: [catalog["Lightning Bolt"]]}
    game = _game([bear], [hill], hands=hands)
    game.players[0].library = [catalog["Mountain"]] * 30
    game.players[1].library = [catalog["Mountain"]] * 30
    game.start_turn(0)
    assert game.cast_from_hand(0, "Peace Talks").supported, game.log

    def end_turn():
        seat = game.active_player_index
        game.resolve_end_step(seat)
        game.resolve_cleanup_step(seat)

    end_turn()
    game.start_next_turn()
    # The next turn: still banned, and still no attacking.
    assert not game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert not game.declare_attackers(1, [_index_of(game.players[1], hill)])[0]

    end_turn()
    game.start_next_turn()
    # The turn after that: both clauses are over.
    assert game.targeting_bans == []
    assert game.attack_restrictions_until_eot == []
    assert game.cast_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.declare_attackers(0, [_index_of(game.players[0], bear)])[0]


# ---------------------------------------------------------------------------
# CR 701.19c — "that creature can't be regenerated"
# ---------------------------------------------------------------------------


@pytest.mark.cr("701.19c", "701.19a")
def test_a_destroy_riders_no_regeneration_clause_reads_the_back_reference_spelling():
    """CR 701.19c: an effect that says a permanent can't be regenerated stops
    the shield CR 701.19a puts up.

    Nekrataal prints the rider as a *back-reference* — "**That creature** can't
    be regenerated" — where Terror prints the pronoun. One rule, five printed
    spellings, one reader: parsed apart, the back-reference is a standalone
    restriction with no duration, which lowers to nothing at all.
    """
    program = compile_card_oracle(_pool("VIS")["Nekrataal"])
    assert program.supported, program.reason
    trigger = program.triggered_abilities[0]
    assert trigger.supported
    assert trigger.instruction.payload["bypass_regeneration"] is True

    # And the durationed sentence is still ``_parse_cant_be``'s, not this
    # rider's — the two say different things and the tail must not be eaten.
    node = compile_line("That creature can't be regenerated this turn.").node
    assert type(node.statement).__name__ == "CantBe"


@pytest.mark.cr("109.5", "613.1f")
def test_both_halves_of_a_you_control_anthem_are_scoped_to_the_same_seat():
    """CR 109.5: "you" on a permanent's static ability is that permanent's
    controller — for **every** effect the sentence has, not for the one whose
    reader remembered.

    Feline Sovereign is the shipped card that shows it: "Other Cats **you
    control** get +1/+1 and have protection from Dogs." The layer-7c refresh
    narrowed the battlefields it walked before asking the matcher, so the P/T
    half was scoped; the protection reader asked the same matcher *without*
    that narrowing, so an opponent's Cats were shielded from Dogs while staying
    the size the card left them. One sentence, two answers.

    The seat is part of "does this lord reach this permanent?", so it is the
    matcher's answer now and the caller has none of its own — which is what
    stops the next reader of that predicate from inheriting the same hole.
    """
    catalog = _catalog()
    cat = next(
        card for name, card in sorted(catalog.items())
        if "Cat" in (card.type_line or "") and name != "Feline Sovereign"
    )
    sovereign = Permanent(card=catalog["Feline Sovereign"])
    mine = Permanent(card=cat)
    theirs = Permanent(card=cat)
    game = _game([sovereign, mine], [theirs])
    game._settle()

    assert ("subtype", "dog") in game._protection_qualities(mine)
    assert mine.effective_power == int(cat.power) + 1

    assert game._protection_qualities(theirs) == set()
    assert theirs.effective_power == int(cat.power)
