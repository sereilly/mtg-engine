"""Odyssey instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ODY")` / `set_cards("ODY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.
# (moved whole to test_ody_instants_first_groups.py when this file reached its size cap)

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.
# (moved whole to test_ody_instants_first_groups.py when this file reached its size cap)

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.
# (moved whole to test_ody_instants_first_groups.py when this file reached its size cap)

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.
import pytest as _w1g5_pytest  # noqa: E402

from engine import Game as _W1G5Game, PlayerState as _W1G5PlayerState  # noqa: E402
from engine.damage_events import deal_damage as _w1g5_deal_damage  # noqa: E402
from engine.models import Permanent as _W1G5Permanent  # noqa: E402
from tests.helpers import resolve_stack as _w1g5_resolve_stack  # noqa: E402


def _w1g5_table(catalog_by_name, set_pool, hand0=(), hand1=(), interactive=()):
    """Two seats, mana off, a library each so a draw is a draw. Cards are
    looked up in Odyssey first and the shipped pool second."""
    ody = set_pool("ODY")

    def card(name):
        return ody[name] if name in ody else catalog_by_name[name]

    game = _W1G5Game(players=[
        _W1G5PlayerState(name="Alice", library=[catalog_by_name["Island"]] * 20),
        _W1G5PlayerState(name="Bob", library=[catalog_by_name["Island"]] * 20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.players[0].hand = [card(name) for name in hand0]
    game.players[1].hand = [card(name) for name in hand1]
    game.active_player_index = 0
    game.current_turn_phase = "main1"
    game._w1g5_card = card
    return game  # _w1g5_table (instants)


def _w1g5_put(game, seat, name):
    """*name* onto *seat*'s battlefield through the one entry path, awake."""
    permanent = _W1G5Permanent(card=game._w1g5_card(name))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g5_put (instants)


def _w1g5_slot(game, seat, permanent) -> int:
    return next(
        index for index, perm in enumerate(game.controlled_by(seat))
        if perm is permanent
    )  # _w1g5_slot (instants)


def _w1g5_dealt(game, recipient, amount, source, source_seat=None):
    """One damage event through CR 120.4, reporting what was dealt."""
    event = {"recipient": recipient, "amount": amount, "source": source,
             "combat": False}
    if source_seat is not None:
        event["source_seat"] = source_seat
    return _w1g5_deal_damage(game, event).dealt  # _w1g5_dealt (instants)


def _w1g5_to_declare_attackers(game, seat=0):
    """*seat*'s turn, at the declare-attackers step, nobody summoning sick."""
    for permanent in game.all_permanents():
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(seat)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers", game.current_step  # _w1g5_to_declare_attackers


def _w1g5_finish_combat(game):
    for _ in range(8):
        if game.current_step == "postcombat_main":
            break
        game.advance_combat_phase()
        _w1g5_resolve_stack(game)
    assert game.current_step == "postcombat_main", game.current_step  # _w1g5_finish_combat


# Spiritualize -----------------------------------------------------------------


def test_w1g5_spiritualize_gains_its_caster_life_for_every_damage_the_creature_deals(
    catalog_by_name, set_pool,
):
    """"Until end of turn, whenever target creature deals damage, you gain that
    much life. Draw a card." The first sentence was implemented by nothing at
    the ingest — the card was supported on its draw. It is a delayed triggered
    ability (CR 603.7) with a stated duration, so it triggers every time
    (CR 603.7b), for **any** damage the creature is the source of, and it uses
    the stack: the life arrives when the trigger resolves, not with the
    damage."""
    game = _w1g5_table(catalog_by_name, set_pool, hand0=["Spiritualize"])
    sorcerer = _w1g5_put(game, 0, "Prodigal Sorcerer")
    alice, bob = game.players

    assert sorted(
        t["name"] for t in game.cast_target_spec(
            0, game._w1g5_card("Spiritualize"))["valid_targets"]
    ) == ["Prodigal Sorcerer"]
    assert game.cast_from_hand(
        0, "Spiritualize", target_permanent_ids=[sorcerer.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert len(alice.hand) == 1, "Draw a card."

    assert game.queue_permanent_ability(
        0, "Prodigal Sorcerer", target_player_index=1,
    ).supported
    game.resolve_top_of_stack()
    assert (alice.life, bob.life) == (20, 19), "the trigger is on the stack"
    assert [item.card.name for item in game.stack] == ["Spiritualize"]
    _w1g5_resolve_stack(game)
    assert alice.life == 21

    # A second event is a second trigger; "that much" is the damage dealt.
    assert _w1g5_dealt(game, bob, 4, sorcerer) == 4
    _w1g5_resolve_stack(game)
    assert alice.life == 25

    # "Until end of turn."
    game.resolve_cleanup_step(0)
    assert _w1g5_dealt(game, bob, 4, sorcerer) == 4
    _w1g5_resolve_stack(game)
    assert alice.life == 25


def test_w1g5_spiritualize_watches_an_opponents_creature_and_combat_damage_too(
    catalog_by_name, set_pool,
):
    """"Target creature" is any creature, and "you" is the caster: aimed at an
    attacker coming at its caster, each point that lands comes back. Combat
    damage is damage (the narrower combat-only event is Acidic Dagger's, and
    is not this one). A prevented event deals nothing and gains nothing."""
    game = _w1g5_table(catalog_by_name, set_pool, hand1=["Spiritualize"])
    giant = _w1g5_put(game, 0, "Hill Giant")
    alice, bob = game.players

    _w1g5_to_declare_attackers(game)
    assert game.declare_attackers(0, [_w1g5_slot(game, 0, giant)])[0]
    assert game.cast_from_hand(
        1, "Spiritualize", target_permanent_ids=[giant.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0]
    _w1g5_finish_combat(game)

    assert (alice.life, bob.life) == (20, 20), "3 taken, 3 gained"
    assert any("Bob gained 3 life from Spiritualize" in line for line in game.log)

    from engine.shields import END_OF_TURN, PREVENT_NEXT_N, Shield, shields_on

    shields_on(alice).append(Shield(kind=PREVENT_NEXT_N, amount=5, lifetime=END_OF_TURN))
    assert _w1g5_dealt(game, alice, 3, giant) == 0
    _w1g5_resolve_stack(game)
    assert bob.life == 20


def test_w1g5_spiritualize_targets_as_it_is_cast_and_fizzles_without_its_target(
    catalog_by_name, set_pool,
):
    """The creature is a **cast** target (CR 601.2c) although the word sits in
    a delayed trigger's opener: the stack-target reader lists it, and a spell
    whose only target is gone by resolution is removed from the stack whole
    (CR 608.2b) — no ability is created and no card is drawn. The pool-wide
    stack-target census named this card until ``line_names_a_cast_target``
    learned that an opener may choose its own subject."""
    from engine.stack_targets import chosen_targets

    game = _w1g5_table(
        catalog_by_name, set_pool, hand0=["Spiritualize"], hand1=["Unsummon"],
    )
    sorcerer = _w1g5_put(game, 0, "Prodigal Sorcerer")
    assert game.queue_from_hand(
        0, "Spiritualize", target_permanent_ids=[sorcerer.permanent_id],
    ).supported
    assert [target.permanent_id for target in chosen_targets(game, game.stack[-1])] == [
        sorcerer.permanent_id
    ]

    assert game.cast_from_hand(
        1, "Unsummon", target_permanent_ids=[sorcerer.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert [c.name for c in game.players[0].hand] == ["Prodigal Sorcerer"], "no draw"
    assert game.delayed_triggers == []
    assert any("Spiritualize was removed from the stack: every target is illegal"
               in line for line in game.log)


def test_w1g5_the_shorter_damage_opener_leaves_acidic_daggers_sentence_alone(
    catalog_by_name,
):
    """The opener that chooses its creature learned a shorter sentence. Its
    longer one — "whenever target creature deals **combat** damage **to a
    non-Wall creature this turn**" — still compiles to the combat event with
    its narrowing, and a combat form with a word missing is no card's."""
    from engine.grammar import compile_line
    from engine.oracle import compile_card_oracle

    dagger = compile_card_oracle(catalog_by_name["Acidic Dagger"])
    armed = dagger.activated_abilities[0].instruction.payload["steps"][0]
    assert armed.payload["event"] == "bound_permanent_deals_combat_damage"
    assert armed.payload["agent_filter"] == {
        "type_filter": "creature", "exclude_subtypes": ["wall"],
    }
    refused = compile_line(
        "Until end of turn, whenever target creature deals combat damage, "
        "you gain that much life."
    )
    assert not refused.instructions


# The instants that compiled at the ingest, each given a game ------------------


def _w1g5_offered(game, seat, name):
    spec = game.cast_target_spec(seat, game._w1g5_card(name))
    return sorted(
        target["name"] for target in spec.get("valid_targets", ())
        if target.get("kind") == "permanent"
    )  # _w1g5_offered (instants)


def test_w1g5_execute_kills_a_white_creature_through_regeneration_and_draws(
    catalog_by_name, set_pool,
):
    """"Destroy target white creature. It can't be regenerated. Draw a card."
    Only a white creature is a legal target; a regeneration shield (Refresh,
    cast first) does not save it; and the caster draws."""
    game = _w1g5_table(catalog_by_name, set_pool, hand0=["Execute"], hand1=["Refresh"])
    lions = _w1g5_put(game, 1, "Savannah Lions")
    bears = _w1g5_put(game, 1, "Grizzly Bears")
    assert _w1g5_offered(game, 0, "Execute") == ["Savannah Lions"]
    assert not game.cast_from_hand(
        0, "Execute", target_permanent_ids=[bears.permanent_id],
    ).supported

    assert game.cast_from_hand(
        1, "Refresh", target_permanent_ids=[lions.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert game.cast_from_hand(
        0, "Execute", target_permanent_ids=[lions.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert not game.is_on_battlefield(lions)
    assert [c.name for c in game.players[0].hand] == ["Island"]
    assert [c.name for c in game.players[1].hand] == ["Island"], "Refresh drew too"


def test_w1g5_refresh_regenerates_its_target_once(catalog_by_name, set_pool):
    game = _w1g5_table(
        catalog_by_name, set_pool, hand0=["Refresh"], hand1=["Lightning Bolt"] * 2,
    )
    bears = _w1g5_put(game, 0, "Grizzly Bears")
    assert game.cast_from_hand(
        0, "Refresh", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    for survives in (True, False):
        assert game.cast_from_hand(
            1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
        ).supported
        _w1g5_resolve_stack(game)
        assert game.is_on_battlefield(bears) is survives
    assert bears.tapped, "regeneration tapped it"


def test_w1g5_gallantry_and_second_thoughts_name_only_a_creature_in_combat(
    catalog_by_name, set_pool,
):
    """"Target **blocking** creature gets +4/+4 until end of turn." / "Exile
    target **attacking** creature." Each has no target outside combat and is
    not cast; in combat each names the one creature in its role, and each
    draws its caster a card."""
    game = _w1g5_table(
        catalog_by_name, set_pool, hand1=["Gallantry", "Second Thoughts"],
    )
    giant = _w1g5_put(game, 0, "Hill Giant")
    ogre = _w1g5_put(game, 0, "Gray Ogre")
    bears = _w1g5_put(game, 1, "Grizzly Bears")
    idle = _w1g5_put(game, 1, "Scathe Zombies")
    for name, target in (("Gallantry", bears), ("Second Thoughts", giant)):
        assert _w1g5_offered(game, 1, name) == []
        assert not game.cast_from_hand(
            1, name, target_permanent_ids=[target.permanent_id],
        ).supported

    _w1g5_to_declare_attackers(game)
    first, second = _w1g5_slot(game, 0, giant), _w1g5_slot(game, 0, ogre)
    assert game.declare_attackers(0, [first, second])[0]
    assert _w1g5_offered(game, 1, "Second Thoughts") == ["Gray Ogre", "Hill Giant"]
    assert game.cast_from_hand(
        1, "Second Thoughts", target_permanent_ids=[ogre.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert [c.name for c in game.players[0].exile] == ["Gray Ogre"]

    game.advance_combat_phase()
    assert game.declare_blockers(
        1, {_w1g5_slot(game, 1, bears): _w1g5_slot(game, 0, giant)},
    )[0]
    assert _w1g5_offered(game, 1, "Gallantry") == ["Grizzly Bears"]
    assert not game.cast_from_hand(
        1, "Gallantry", target_permanent_ids=[idle.permanent_id],
    ).supported
    assert game.cast_from_hand(
        1, "Gallantry", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == (6, 6)
    assert len(game.players[1].hand) == 2, "one card each"
    _w1g5_finish_combat(game)
    assert game.is_on_battlefield(bears) and not game.is_on_battlefield(giant)
    game.resolve_cleanup_step(0)
    assert (bears.effective_power, bears.effective_toughness) == (2, 2)


def test_w1g5_shelter_asks_its_colour_at_resolution_and_only_shelters_its_casters_own(
    catalog_by_name, set_pool,
):
    """"Target creature you control gains protection from the color of your
    choice until end of turn. Draw a card." The colour is chosen as the spell
    resolves (CR 608.2d), so an interactive caster is asked then; the picker
    offers only the caster's creatures."""
    game = _w1g5_table(
        catalog_by_name, set_pool, hand0=["Shelter"],
        hand1=["Terror", "Lightning Bolt"], interactive={0},
    )
    bears = _w1g5_put(game, 0, "Grizzly Bears")
    theirs = _w1g5_put(game, 1, "Hill Giant")
    assert _w1g5_offered(game, 0, "Shelter") == ["Grizzly Bears"]
    assert not game.cast_from_hand(
        0, "Shelter", target_permanent_ids=[theirs.permanent_id],
    ).supported

    assert game.queue_from_hand(
        0, "Shelter", target_permanent_ids=[bears.permanent_id],
    ).supported
    game.resolve_top_of_stack()
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("color_choice", 0)]
    assert game.resolve_pending_choice("color_choice", 0, mana_color="R")
    _w1g5_resolve_stack(game)

    assert game._protection_qualities(bears) == {("color", "R")}
    assert [c.name for c in game.players[0].hand] == ["Island"]
    assert not game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    assert game.cast_from_hand(
        1, "Terror", target_permanent_ids=[bears.permanent_id],
    ).supported

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

import pytest as _w1g6_pytest

from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_game(
    mine=(), theirs=(), yard=(), their_yard=(), library=(), their_library=(),
    hand=(), their_hand=(),
):
    """Two seats, costs unenforced, nobody summoning sick. Cards are handed
    over as ``CardDefinition``s; the returned game has not started a turn."""
    def board(cards):
        permanents = [_W1G6Permanent(card=card) for card in cards]
        for permanent in permanents:
            permanent.metadata["summoning_sickness_turn"] = -99
        return permanents

    game = _W1G6Game(players=[
        _W1G6PlayerState(
            name="P1", battlefield=board(mine), graveyard=list(yard),
            library=list(library), hand=list(hand), life=20,
        ),
        _W1G6PlayerState(
            name="P2", battlefield=board(theirs), graveyard=list(their_yard),
            library=list(their_library), hand=list(their_hand), life=20,
        ),
    ])
    game.enforce_mana_costs = False
    return game  # _w1g6_game


def _w1g6_named(game, seat, name):
    return next(
        permanent for permanent in game.controlled_by(seat)
        if permanent.card.name == name
    )  # _w1g6_named


def _w1g6_names(game, seat):
    return sorted(permanent.card.name for permanent in game.controlled_by(seat))


def _w1g6_pile(player, zone="graveyard"):
    return [card.name for card in getattr(player, zone)]


# --- Skeletal Scrying -------------------------------------------------------
# "As an additional cost to cast this spell, exile X cards from your
# graveyard. / You draw X cards and you lose X life." Refused at the support
# gate ("printed cost nothing charges"): the graveyard-exile clause reader
# admitted only a phrase naming a card type, and this one prints "cards".

def test_w1g6_skeletal_scrying_charges_x_cards_for_x_cards_and_x_life(set_pool):
    from engine.cast_costs import additional_costs

    lea, ody = set_pool("LEA"), set_pool("ODY")
    scrying = ody["Skeletal Scrying"]
    (cost,) = additional_costs(scrying)
    assert cost.exile_graveyard_filter == {} and cost.exile_graveyard_count_x

    game = _w1g6_game(
        hand=[scrying],
        yard=[lea["Forest"], lea["Lightning Bolt"], lea["Hill Giant"]],
        library=[lea["Island"]] * 6,
    )
    game.start_turn(0)
    # The X box is capped by what the graveyard can pay.
    assert game.cast_target_spec(0, scrying)["max_x"] == 3

    cast = game.queue_from_hand(0, "Skeletal Scrying", x_value=2)
    assert cast.supported, cast.details
    # Paid as it is cast (CR 601.2h): two cards are gone before it resolves.
    assert len(game.players[0].exile) == 2 and len(game.players[0].graveyard) == 1
    assert not game.players[0].hand and game.players[0].life == 20
    _w1g6_resolve_stack(game)

    assert _w1g6_pile(game.players[0], "hand") == ["Island", "Island"]
    assert game.players[0].life == 18
    assert len(game.players[0].library) == 4


def test_w1g6_skeletal_scrying_cannot_announce_more_than_the_graveyard_holds(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        hand=[ody["Skeletal Scrying"]], yard=[lea["Forest"], lea["Lightning Bolt"]],
        library=[lea["Island"]] * 6,
    )
    game.start_turn(0)

    refused = game.queue_from_hand(0, "Skeletal Scrying", x_value=3)

    assert not refused.supported
    assert "holds 2 card(s) and its additional cost exiles 3" in refused.details
    assert _w1g6_pile(game.players[0], "hand") == ["Skeletal Scrying"]
    assert len(game.players[0].graveyard) == 2 and not game.players[0].exile


def test_w1g6_skeletal_scrying_pays_x_in_mana_as_well_as_in_cards(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        hand=[ody["Skeletal Scrying"]], yard=[lea["Forest"]] * 3,
        library=[lea["Island"]] * 6,
    )
    game.enforce_mana_costs = True
    game.start_turn(0)

    game.players[0].mana_pool["B"] = 2
    short = game.queue_from_hand(0, "Skeletal Scrying", x_value=2)
    assert not short.supported
    assert len(game.players[0].graveyard) == 3, "a refused cast exiled nothing"

    game.players[0].mana_pool["B"] = 3
    cast = game.queue_from_hand(0, "Skeletal Scrying", x_value=2)
    assert cast.supported, cast.details
    _w1g6_resolve_stack(game)
    assert game.players[0].life == 18 and len(game.players[0].hand) == 2


# --- Ghastly Demise ---------------------------------------------------------
# "Destroy target nonblack creature if its toughness is less than or equal to
# the number of cards in your graveyard." The target is legal whatever its
# toughness (Scryfall ruling 2020-11-10: "Ghastly Demise can target any
# nonblack creature. Compare the creature's toughness to the number of cards
# in your graveyard as Ghastly Demise resolves"); the comparison is CR 608.2c's
# trailing "if", against a count taken as it resolves.

def _w1g6_demise(set_pool, yard_size, target="Hill Giant"):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        hand=[ody["Ghastly Demise"]],
        theirs=[lea["Hill Giant"], lea["Drudge Skeletons"], lea["Grizzly Bears"]],
        yard=[lea["Forest"]] * yard_size,
    )
    game.start_turn(0)
    aimed = _w1g6_named(game, 1, target)
    cast = game.queue_from_hand(
        0, "Ghastly Demise", target_permanent_ids=[aimed.permanent_id]
    )
    return game, cast  # _w1g6_demise


@_w1g6_pytest.mark.parametrize(
    "yard_size, destroyed", [(3, True), (4, True), (2, False), (0, False)]
)
def test_w1g6_ghastly_demise_compares_toughness_with_the_graveyard(
    set_pool, yard_size, destroyed
):
    game, cast = _w1g6_demise(set_pool, yard_size)  # Hill Giant: toughness 3
    # Castable either way: the condition is not a targeting restriction.
    assert cast.supported, cast.details
    _w1g6_resolve_stack(game)

    assert ("Hill Giant" in _w1g6_names(game, 1)) is not destroyed
    assert ("Hill Giant" in _w1g6_pile(game.players[1])) is destroyed
    # The spell resolves and goes to the graveyard whether or not it destroyed.
    assert _w1g6_pile(game.players[0])[-1] == "Ghastly Demise"


def test_w1g6_ghastly_demise_does_not_count_itself(set_pool):
    """Ruling 2020-11-10: "Because Ghastly Demise isn't put into your graveyard
    until it's finished resolving, it won't be counted". A 2/2 against one
    card in the graveyard survives; the Demise makes two only afterwards."""
    game, cast = _w1g6_demise(set_pool, 1, target="Grizzly Bears")
    assert cast.supported
    _w1g6_resolve_stack(game)

    assert "Grizzly Bears" in _w1g6_names(game, 1)
    assert len(game.players[0].graveyard) == 2


def test_w1g6_ghastly_demise_counts_as_it_resolves(set_pool):
    lea = set_pool("LEA")
    game, cast = _w1g6_demise(set_pool, 2)
    assert cast.supported
    # A third card arrives while the spell is on the stack.
    game.players[0].graveyard.append(lea["Forest"])
    _w1g6_resolve_stack(game)

    assert "Hill Giant" not in _w1g6_names(game, 1)


def test_w1g6_ghastly_demise_cannot_be_aimed_at_a_black_creature_or_at_nothing(
    set_pool,
):
    game, refused = _w1g6_demise(set_pool, 5, target="Drudge Skeletons")
    assert not refused.supported
    assert _w1g6_pile(game.players[0], "hand") == ["Ghastly Demise"]

    lea, ody = set_pool("LEA"), set_pool("ODY")
    empty = _w1g6_game(hand=[ody["Ghastly Demise"]], yard=[lea["Forest"]] * 5)
    empty.start_turn(0)
    assert not empty.queue_from_hand(0, "Ghastly Demise").supported

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

import random as _w1g7_random

import pytest as _w1g7_pytest

from engine import Game as _w1g7_Game, PlayerState as _w1g7_PlayerState
from engine.models import Permanent as _w1g7_Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import _mk_card as _w1g7_mk_card
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_duel(set_pool, *, hand0=(), hand1=(), gy0=(), gy1=(), lib0=(),
               lib1=(), bf0=(), bf1=(), interactive=()):
    """A two-seat game with costs off, built from card names (ODY over LEA).
    A seat in *interactive* is asked its decisions instead of defaulting."""
    pool = {**set_pool("LEA"), **set_pool("ODY")}
    seats = [
        _w1g7_PlayerState(
            name=f"P{seat}", life=20,
            hand=[pool[n] for n in hand], graveyard=[pool[n] for n in gy],
            library=[pool[n] for n in lib],
        )
        for seat, (hand, gy, lib) in enumerate(
            ((hand0, gy0, lib0), (hand1, gy1, lib1))
        )
    ]
    game = _w1g7_Game(players=seats)
    game.enforce_mana_costs = False
    for seat in interactive:
        game.interactive_seats.add(seat)
    for seat, names in enumerate((bf0, bf1)):
        for name in names:
            perm = _w1g7_Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
    return game


def _w1g7_names(cards):
    return [card.name for card in cards]


def _w1g7_on_board(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def _w1g7_settle(game, limit=50):
    """Drain the stack and give every owed prompt its default answer."""
    for _ in range(limit):
        _w1g7_resolve_stack(game)
        if not game.pending_choices and not game.pending_replacement_choices:
            return
        game.auto_resolve_pending_choices()
        game.auto_resolve_pending_replacement_choices()
    raise AssertionError("the game did not settle")


def _w1g7_pt(game, seat=0):
    return sorted(
        (p.card.name, p.effective_power, p.effective_toughness)
        for p in game.controlled_by(seat) if p.is_creature
    )


# --- Sacred Rites: a pump sized by what was discarded --------------------------

def test_sacred_rites_buffs_its_controllers_creatures_by_the_cards_discarded(
    set_pool,
):
    """"Discard any number of cards. Creatures you control get +0/+1 until end
    of turn for each card discarded this way." The caster names the cards, the
    pump waits for that answer (CR 608.2), reaches only their own creatures and
    ends at cleanup (CR 514.2)."""
    game = _w1g7_duel(
        set_pool, hand0=["Sacred Rites", "Forest", "Island", "Swamp"],
        bf0=["Grizzly Bears", "Grizzly Bears"], bf1=["Grizzly Bears"],
        interactive=(0,),
    )
    assert game.cast_from_hand(0, "Sacred Rites").supported
    (choice,) = game.pending_choices
    assert (choice.kind, choice.data["count"], choice.data["up_to"]) == ("discard", 3, True)
    assert _w1g7_pt(game) == [("Grizzly Bears", 2, 2)] * 2, "nothing yet"

    assert game.confirm_discard(0, [0, 2])
    assert _w1g7_pt(game) == [("Grizzly Bears", 2, 4)] * 2
    assert _w1g7_pt(game, 1) == [("Grizzly Bears", 2, 2)]
    assert _w1g7_names(game.players[0].hand) == ["Island"]
    assert sorted(_w1g7_names(game.players[0].graveyard)) == [
        "Forest", "Sacred Rites", "Swamp",
    ]

    game.resolve_cleanup_step(0)
    assert _w1g7_pt(game) == [("Grizzly Bears", 2, 2)] * 2


def test_sacred_rites_with_nothing_discarded_buffs_by_nothing(set_pool):
    """"Any number" includes none, and an empty hand is not asked at all."""
    game = _w1g7_duel(
        set_pool, hand0=["Sacred Rites", "Forest"], bf0=["Grizzly Bears"],
        interactive=(0,),
    )
    game.cast_from_hand(0, "Sacred Rites")
    assert game.confirm_discard(0, [])
    assert _w1g7_pt(game) == [("Grizzly Bears", 2, 2)]
    assert _w1g7_names(game.players[0].hand) == ["Forest"]

    empty = _w1g7_duel(
        set_pool, hand0=["Sacred Rites"], bf0=["Grizzly Bears"], interactive=(0,),
    )
    empty.cast_from_hand(0, "Sacred Rites")
    assert not empty.pending_choices and not empty.stack
    assert _w1g7_pt(empty) == [("Grizzly Bears", 2, 2)]


def test_two_identical_cards_discarded_to_sacred_rites_are_two_cards(set_pool):
    """A hand holds one immutable card object per copy: discarding one of two
    Forests leaves the other, and counts one."""
    game = _w1g7_duel(
        set_pool, hand0=["Sacred Rites", "Forest", "Forest"],
        bf0=["Grizzly Bears"], interactive=(0,),
    )
    game.cast_from_hand(0, "Sacred Rites")
    assert game.confirm_discard(0, [0])
    assert _w1g7_names(game.players[0].hand) == ["Forest"]
    assert _w1g7_pt(game) == [("Grizzly Bears", 2, 3)]


def test_a_pump_for_each_card_discarded_this_way_is_any_cards_sentence(set_pool):
    """The clause is the record's, so it sizes a pump on a class, on one
    target and on the source alike — and refuses where nothing was discarded
    or where no duration would make it a continuous effect over a frozen
    number."""
    def card(text, type_line="Sorcery"):
        return _w1g7_mk_card("Rite", "{1}", type_line, text)

    opener = "Discard any number of cards. "
    tail = " until end of turn for each card discarded this way."
    assert _w1g7_compile(card(opener + "Creatures you control get +1/+1" + tail)).supported
    assert _w1g7_compile(card(opener + "Target creature gets +2/+0" + tail)).supported
    # No producer: the words name nothing.
    assert not _w1g7_compile(card("Creatures you control get +1/+1" + tail)).supported
    # A noun the record does not hold.
    assert not _w1g7_compile(card(
        opener + "Creatures you control get +1/+1 until end of turn for each "
        "creature discarded this way."
    )).supported

    game = _w1g7_duel(
        set_pool, hand0=["Forest", "Island"], bf0=["Grizzly Bears"],
        bf1=["Grizzly Bears"], interactive=(0,),
    )
    game.players[0].hand.append(card(opener + "Target creature gets +2/+0" + tail))
    theirs = _w1g7_on_board(game, 1, "Grizzly Bears")
    assert game.cast_from_hand(
        0, "Rite", target_permanent_ids=[theirs.permanent_id]
    ).supported
    assert game.confirm_discard(0, [0, 1])
    assert _w1g7_pt(game, 1) == [("Grizzly Bears", 6, 2)]
    assert _w1g7_pt(game, 0) == [("Grizzly Bears", 2, 2)]


# --- Rites of Initiation: the player chooses how many, chance chooses which ----

def test_rites_of_initiation_asks_how_many_and_discards_that_many_at_random(
    set_pool,
):
    """"Discard any number of cards **at random**." Two decisions split between
    two parties: the number is the caster's (asked, with the hand as its
    ceiling) and the cards are chance's."""
    def run(seed):
        _w1g7_random.seed(seed)
        game = _w1g7_duel(
            set_pool,
            hand0=["Rites of Initiation", "Forest", "Island", "Swamp", "Plains"],
            bf0=["Grizzly Bears"], bf1=["Grizzly Bears"], interactive=(0,),
        )
        assert game.cast_from_hand(0, "Rites of Initiation").supported
        (choice,) = game.pending_choices
        assert choice.kind == "number_choice"
        assert (choice.data["minimum"], choice.data["maximum"]) == (0, 4)
        assert _w1g7_pt(game) == [("Grizzly Bears", 2, 2)]
        assert game.confirm_number_choice(0, 2)
        assert not game.stack and not game.pending_choices
        return game

    first = run(11)
    assert _w1g7_pt(first) == [("Grizzly Bears", 4, 2)]
    assert _w1g7_pt(first, 1) == [("Grizzly Bears", 2, 2)]
    assert len(first.players[0].hand) == 2
    assert len(first.players[0].graveyard) == 3, "two discards and the spell"

    # Determinism: the seeded RNG picks, so a seed replays the same cards...
    assert _w1g7_names(run(11).players[0].hand) == _w1g7_names(first.players[0].hand)
    # ...and across seeds the caster does not get to pick.
    kept = {tuple(_w1g7_names(run(seed).players[0].hand)) for seed in range(12)}
    assert len(kept) > 1

    first.resolve_cleanup_step(0)
    assert _w1g7_pt(first) == [("Grizzly Bears", 2, 2)]


def test_rites_of_initiation_refuses_a_number_the_hand_cannot_cover(set_pool):
    game = _w1g7_duel(
        set_pool, hand0=["Rites of Initiation", "Forest", "Island"],
        bf0=["Grizzly Bears"], interactive=(0,),
    )
    game.cast_from_hand(0, "Rites of Initiation")
    assert not game.confirm_number_choice(0, 3)
    assert not game.confirm_number_choice(0, -1)
    assert game.pending_choices, "a refused answer leaves the prompt owed"
    assert game.confirm_number_choice(0, 0)
    assert _w1g7_pt(game) == [("Grizzly Bears", 2, 2)]
    assert len(game.players[0].hand) == 2


def test_rites_of_initiation_with_an_empty_hand_asks_nothing(set_pool):
    game = _w1g7_duel(
        set_pool, hand0=["Rites of Initiation"], bf0=["Grizzly Bears"],
        interactive=(0,),
    )
    game.cast_from_hand(0, "Rites of Initiation")
    assert not game.pending_choices and not game.stack
    assert _w1g7_pt(game) == [("Grizzly Bears", 2, 2)]


def test_a_seat_nobody_asks_takes_the_whole_offer_on_both_rites(set_pool):
    """The stated policy for a ceiling a seat does not evaluate
    (``_default_discard``), and the random spelling defaults alike."""
    for name, expected in (
        ("Sacred Rites", ("Grizzly Bears", 2, 4)),
        ("Rites of Initiation", ("Grizzly Bears", 4, 2)),
    ):
        _w1g7_random.seed(3)
        game = _w1g7_duel(
            set_pool, hand0=[name, "Forest", "Island"], bf0=["Grizzly Bears"],
        )
        game.cast_from_hand(0, name)
        _w1g7_settle(game)
        assert game.players[0].hand == [], name
        assert _w1g7_pt(game) == [expected], name


def test_a_narrowed_any_number_random_discard_is_refused():
    assert not _w1g7_compile(_w1g7_mk_card(
        "Narrow Rite", "{R}", "Instant",
        "Discard any number of creature cards at random.",
    )).supported


# --- Rites of Refusal (compiled before this round; driven) ---------------------

def _w1g7_refusal(set_pool, lands):
    game = _w1g7_duel(
        set_pool, hand0=["Rites of Refusal", "Forest", "Island", "Swamp"],
        hand1=["Grizzly Bears"], bf1=["Forest"] * lands, interactive=(0, 1),
    )
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    assert game.queue_from_hand(0, "Rites of Refusal", target_stack_index=0).supported
    game.enforce_mana_costs = True
    game.resolve_top_of_stack(pause_for_choices=True)
    return game


def test_rites_of_refusal_prices_the_toll_at_three_per_card_discarded(set_pool):
    """"Counter target spell unless its controller pays {3} for each card
    discarded this way." Two cards is {6}: paid from six lands the spell
    resolves, and declined it is countered."""
    paid = _w1g7_refusal(set_pool, lands=6)
    assert paid.confirm_discard(0, [0, 1])
    owed = paid.pending_mana_payment
    assert owed is not None and owed["player_index"] == 1 and owed["amount"] == 6
    assert paid.confirm_mana_payment(1, True) is True
    _w1g7_resolve_stack(paid)
    assert "Grizzly Bears" in [p.card.name for p in paid.controlled_by(1)]
    assert all(p.tapped for p in paid.controlled_by(1) if p.card.name == "Forest")

    declined = _w1g7_refusal(set_pool, lands=6)
    assert declined.confirm_discard(0, [0])
    assert declined.pending_mana_payment["amount"] == 3
    assert declined.confirm_mana_payment(1, False) is True
    _w1g7_resolve_stack(declined)
    assert _w1g7_names(declined.players[1].graveyard) == ["Grizzly Bears"]


def test_rites_of_refusal_with_nothing_discarded_counters_nothing(set_pool):
    """{3} for each of no cards is {0}, which is always paid."""
    game = _w1g7_refusal(set_pool, lands=0)
    assert game.confirm_discard(0, [])
    _w1g7_settle(game)
    assert "Grizzly Bears" in [p.card.name for p in game.controlled_by(1)]
    assert len(game.players[0].hand) == 3


def test_rites_of_refusal_needs_a_spell_and_asks_nothing_if_it_leaves(set_pool):
    """CR 601.2c: no spell, no cast. CR 608.2b: with its only target gone the
    spell does not resolve, so no discard is asked for either."""
    alone = _w1g7_duel(set_pool, hand0=["Rites of Refusal", "Forest"])
    assert not alone.cast_from_hand(0, "Rites of Refusal").supported
    assert len(alone.players[0].hand) == 2

    game = _w1g7_duel(
        set_pool, hand0=["Rites of Refusal", "Forest"], hand1=["Grizzly Bears"],
        interactive=(0, 1),
    )
    game.queue_from_hand(1, "Grizzly Bears")
    game.queue_from_hand(0, "Rites of Refusal", target_stack_index=0)
    del game.stack[0]
    game.resolve_top_of_stack(pause_for_choices=True)
    assert not game.pending_choices
    assert _w1g7_names(game.players[0].hand) == ["Forest"]
    assert _w1g7_names(game.players[0].graveyard) == ["Rites of Refusal"]


# --- The sheet's instants that compiled before this round, driven ----------------

def test_repel_puts_a_creature_on_top_of_its_owners_library(set_pool):
    """Its **owner's** library (CR 400.3), so a creature under another
    player's control goes home; a noncreature is no target, and with no
    creature the spell cannot be cast (CR 601.2c)."""
    from engine.control import change_control

    game = _w1g7_duel(
        set_pool, hand0=["Repel"], bf1=["Grizzly Bears"], lib0=["Island"],
        lib1=["Swamp"],
    )
    bears = _w1g7_on_board(game, 1, "Grizzly Bears")
    change_control(bears, 0, source="test")
    game._sync_control()
    assert game.cast_from_hand(
        0, "Repel", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g7_settle(game)
    assert _w1g7_names(game.players[1].library) == ["Grizzly Bears", "Swamp"]
    assert _w1g7_names(game.players[0].library) == ["Island"]

    ring = _w1g7_duel(set_pool, hand0=["Repel"], bf1=["Sol Ring"])
    artifact = _w1g7_on_board(ring, 1, "Sol Ring")
    assert not ring.cast_from_hand(
        0, "Repel", target_permanent_ids=[artifact.permanent_id]
    ).supported
    assert [p.card.name for p in ring.controlled_by(1)] == ["Sol Ring"]


def test_words_of_wisdom_draws_two_for_you_and_one_for_each_other_player(set_pool):
    game = _w1g7_duel(
        set_pool, hand0=["Words of Wisdom"], lib0=["Island", "Swamp", "Plains"],
        lib1=["Forest", "Mountain"],
    )
    game.cast_from_hand(0, "Words of Wisdom")
    _w1g7_settle(game)
    assert _w1g7_names(game.players[0].hand) == ["Island", "Swamp"]
    assert _w1g7_names(game.players[1].hand) == ["Forest"]

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

import pytest as _w1g9_pytest

from engine import Game as _w1g9_Game, PlayerState as _w1g9_PlayerState
from engine.models import Permanent as _w1g9_Permanent
from engine.oracle import compile_card_oracle as _w1g9_compile
from tests.helpers import _mk_card as _w1g9_mk_card
from tests.helpers import resolve_stack as _w1g9_resolve_stack


def _w1g9_duel(set_pool, *, hand0=(), hand1=(), bf0=(), bf1=(), gy0=(),
               gy1=(), costs=False):
    """A two-seat game built from card names (Odyssey first, then Alpha),
    with ten Forests in each library and nobody summoning-sick."""
    pool = {**set_pool("LEA"), **set_pool("ODY")}
    game = _w1g9_Game(players=[
        _w1g9_PlayerState(
            name=f"P{seat}", life=20, hand=[pool[n] for n in hand],
            graveyard=[pool[n] for n in gy], library=[pool["Forest"]] * 10,
        )
        for seat, (hand, gy) in enumerate(((hand0, gy0), (hand1, gy1)))
    ])
    game.enforce_mana_costs = costs
    for seat, names in enumerate((bf0, bf1)):
        for name in names:
            permanent = _w1g9_Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
    return game  # _w1g9_duel (instants)


def _w1g9_on(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def _w1g9_names(cards):
    return [card.name for card in cards]


# --- Deluge: "Tap all creatures without flying." ---------------------------

def test_deluge_taps_every_creature_without_flying_and_nothing_else(set_pool):
    game = _w1g9_duel(
        set_pool, hand0=["Deluge"], bf0=["Grizzly Bears"],
        bf1=["Air Elemental", "Gray Ogre", "Forest", "Mox Pearl"],
    )
    assert game.cast_from_hand(0, "Deluge").supported
    _w1g9_resolve_stack(game)
    tapped = {p.card.name for p in game.all_permanents() if p.tapped}
    assert tapped == {"Grizzly Bears", "Gray Ogre"}


def test_deluge_asks_what_a_creature_has_as_it_resolves(set_pool):
    """A keyword is CR 613 layer 6: an Ogre given flying in response is not
    tapped, and an Air Elemental whose flying is gone is."""
    game = _w1g9_duel(
        set_pool, hand0=["Deluge"], hand1=["Jump"],
        bf1=["Gray Ogre", "Grizzly Bears"],
    )
    ogre = _w1g9_on(game, 1, "Gray Ogre")
    assert game.queue_from_hand(0, "Deluge").supported
    assert game.queue_from_hand(
        1, "Jump", target_permanent_ids=[ogre.permanent_id]
    ).supported
    _w1g9_resolve_stack(game)
    assert not ogre.tapped
    assert _w1g9_on(game, 1, "Grizzly Bears").tapped


def test_a_tap_sweep_still_refuses_a_keyword_it_was_never_shown(set_pool):
    """The whitelist grew by the one field the pool prints: "with flying" on
    a tap sweep is still a refusal, not a sweep of everything."""
    assert _w1g9_compile(_w1g9_mk_card(
        "Low Tide", "{U}", "Instant", "Tap all creatures without flying."
    )).supported
    assert not _w1g9_compile(_w1g9_mk_card(
        "High Tide Probe", "{U}", "Instant", "Tap all creatures with flying."
    )).supported


# --- Syncopate: a price, and a destination if it goes unpaid ----------------

def _w1g9_zones(game, seat):
    player = game.players[seat]
    return (
        _w1g9_names(player.graveyard), _w1g9_names(player.exile),
        _w1g9_names(p.card for p in game.controlled_by(seat)),
    )


def test_syncopate_exiles_the_spell_it_counters(set_pool):
    """"Counter target spell unless its controller pays {X}. If that spell is
    countered this way, exile it instead of putting it into its owner's
    graveyard." The payer cannot cover {2}: countered, and the card is in
    exile, never in a graveyard."""
    game = _w1g9_duel(
        set_pool, hand0=["Syncopate"], hand1=["Grizzly Bears"], costs=True,
    )
    game.players[0].mana_pool.update({"U": 3})
    game.players[1].mana_pool.update({"G": 2})
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    assert game.queue_from_hand(
        0, "Syncopate", target_stack_index=0, x_value=2
    ).supported
    _w1g9_resolve_stack(game)
    assert _w1g9_zones(game, 1) == ([], ["Grizzly Bears"], [])
    assert _w1g9_names(game.players[0].graveyard) == ["Syncopate"]


def test_syncopate_leaves_a_spell_whose_controller_pays(set_pool):
    game = _w1g9_duel(
        set_pool, hand0=["Syncopate"], hand1=["Grizzly Bears"], costs=True,
    )
    game.players[0].mana_pool.update({"U": 3})
    game.players[1].mana_pool.update({"G": 4})
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    assert game.queue_from_hand(
        0, "Syncopate", target_stack_index=0, x_value=2
    ).supported
    _w1g9_resolve_stack(game)
    assert _w1g9_zones(game, 1) == ([], [], ["Grizzly Bears"])
    assert sum(game.players[1].mana_pool.values()) == 0


def test_syncopate_asks_a_person_and_exiles_when_they_decline(set_pool):
    """The destination rides the payment prompt: a seat that could pay and
    says no has the spell countered by the answer, and it is exiled there."""
    game = _w1g9_duel(
        set_pool, hand0=["Syncopate"], hand1=["Grizzly Bears"], costs=True,
    )
    game.interactive_seats = {0, 1}
    game.players[0].mana_pool.update({"U": 3})
    game.players[1].mana_pool.update({"G": 4})
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    assert game.queue_from_hand(
        0, "Syncopate", target_stack_index=0, x_value=2
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    prompt = game.pending_choice_of("mana_payment")
    assert prompt is not None and prompt.player_index == 1
    assert _w1g9_names(i.card for i in game.stack)[0] == "Grizzly Bears"
    assert game.resolve_pending_choice("mana_payment", 1, pay=False)
    assert _w1g9_zones(game, 1) == ([], ["Grizzly Bears"], [])
    assert game.players[1].mana_pool["G"] == 2, "only the Bears were paid for"


def test_syncopate_for_nothing_counters_nothing_and_needs_a_spell(set_pool):
    game = _w1g9_duel(
        set_pool, hand0=["Syncopate", "Syncopate"], hand1=["Grizzly Bears"],
    )
    refused = game.queue_from_hand(0, "Syncopate", x_value=2)
    assert not refused.supported and len(game.players[0].hand) == 2
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    assert game.queue_from_hand(
        0, "Syncopate", target_stack_index=0, x_value=0
    ).supported
    _w1g9_resolve_stack(game)
    assert _w1g9_zones(game, 1) == ([], [], ["Grizzly Bears"])


@_w1g9_pytest.mark.parametrize("tail, where", [
    ("put it on top of its owner's library instead of into that player's "
     "graveyard.", "library"),
    ("put it into its owner's hand instead of into that player's graveyard.",
     "hand"),
])
def test_a_priced_counter_sends_the_card_wherever_its_tail_prints(
    set_pool, tail, where
):
    """An invented card: the tail is Memory Lapse's and Remand's, and behind
    a price it reaches the same mover the hard counter uses."""
    tax = _w1g9_mk_card(
        "Toll Lapse", "{1}{U}", "Instant",
        "Counter target spell unless its controller pays {2}. If that spell "
        "is countered this way, " + tail,
    )
    assert _w1g9_compile(tax).supported
    game = _w1g9_duel(set_pool, hand1=["Grizzly Bears"], costs=True)
    game.players[0].hand.append(tax)
    game.players[0].mana_pool.update({"U": 2})
    game.players[1].mana_pool.update({"G": 2})
    assert game.queue_from_hand(1, "Grizzly Bears").supported
    assert game.queue_from_hand(0, "Toll Lapse", target_stack_index=0).supported
    _w1g9_resolve_stack(game)
    victim = game.players[1]
    assert _w1g9_zones(game, 1) == ([], [], [])
    if where == "library":
        assert victim.library[0].name == "Grizzly Bears"
    else:
        assert _w1g9_names(victim.hand) == ["Grizzly Bears"]


# --- Cease-Fire: a turn-long ban on one seat, by spell type -----------------

def test_cease_fire_stops_its_target_casting_creature_spells_this_turn(set_pool):
    """Enforced by the one cast-prohibition table its three readers ask: the
    engine refuses the cast, and the same call says no to the AI and the
    castable highlight."""
    from engine.cast_prohibitions import cast_prohibition

    game = _w1g9_duel(
        set_pool, hand0=["Cease-Fire", "Grizzly Bears"],
        hand1=["Grizzly Bears", "Juggernaut", "Lightning Bolt"],
    )
    spec = game.cast_target_spec(0, game.players[0].hand[0])
    assert spec["kind"] == "player" and spec["requires_target"]
    assert game.queue_from_hand(0, "Cease-Fire", target_player_index=1).supported
    _w1g9_resolve_stack(game)
    assert len(game.players[0].hand) == 2, "and its caster drew a card"

    victim = game.players[1]
    for name in ("Grizzly Bears", "Juggernaut"):  # an artifact creature too
        card = next(c for c in victim.hand if c.name == name)
        refusal = cast_prohibition(game, 1, card)
        assert refusal is not None and "creature spells this turn" in refusal.details
        assert not game.queue_from_hand(1, name).supported
    assert len(victim.hand) == 3 and not game.stack
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    # The caster named somebody else: their own creatures are not stopped.
    assert game.queue_from_hand(0, "Grizzly Bears").supported


def test_cease_fire_ends_with_the_turn(set_pool):
    game = _w1g9_duel(set_pool, hand0=["Cease-Fire"], hand1=["Grizzly Bears"])
    assert game.queue_from_hand(0, "Cease-Fire", target_player_index=1).supported
    _w1g9_resolve_stack(game)
    assert not game.queue_from_hand(1, "Grizzly Bears").supported
    game.start_next_turn()
    assert game.spell_types_forbidden_this_turn == {}
    assert game.queue_from_hand(1, "Grizzly Bears").supported


@_w1g9_pytest.mark.parametrize("line, supported", [
    ("Target player can't cast creature spells this turn.", True),
    ("Target player can't cast instant or sorcery spells this turn.", True),
    # A window the record does not have, and no window at all (a permanent's
    # static ability, which a table reads): both refuse.
    ("Target player can't cast creature spells until your next turn.", False),
    ("Target player can't cast creature spells.", False),
    ("Target player can't cast green creature spells this turn.", False),
])
def test_a_typed_cast_ban_reads_only_the_window_it_can_keep(line, supported):
    card = _w1g9_mk_card("Truce Probe", "{W}", "Instant", line)
    assert _w1g9_compile(card).supported is supported


# --- Aura Graft: take an Aura and move it to something else it can enchant --

def _w1g9_enchant(game, set_pool, seat, aura_name, host):
    from engine.auras import attach_aura

    pool = {**set_pool("LEA"), **set_pool("ODY")}
    aura = _w1g9_Permanent(card=pool[aura_name])
    game._put_permanent_onto_battlefield(seat, aura, None)
    attach_aura(aura, host)
    game._recompute_continuous_effects()
    return aura


def _w1g9_where(game, aura):
    """``(who controls the Aura, the permanent it is on)``."""
    return game.controller_index_of(aura), aura.metadata.get("attached_to")


def test_aura_graft_takes_an_aura_and_moves_it_to_another_permanent(set_pool):
    """"Gain control of target Aura that's attached to a permanent. Attach it
    to another permanent it can enchant." The opponent's Weakness comes off
    my Bears, becomes mine, and goes onto their Ogre."""
    game = _w1g9_duel(
        set_pool, hand0=["Aura Graft"], bf0=["Grizzly Bears"], bf1=["Gray Ogre"],
    )
    bears, ogre = _w1g9_on(game, 0, "Grizzly Bears"), _w1g9_on(game, 1, "Gray Ogre")
    weakness = _w1g9_enchant(game, set_pool, 1, "Weakness", bears)
    spec = game.cast_target_spec(0, game.players[0].hand[0])
    assert [t["name"] for t in spec["valid_targets"]] == ["Weakness"]
    assert game.queue_from_hand(
        0, "Aura Graft", target_permanent_ids=[weakness.permanent_id]
    ).supported
    _w1g9_resolve_stack(game)
    controller, host = _w1g9_where(game, weakness)
    assert controller == 0 and host is ogre


def test_aura_graft_asks_its_caster_for_the_new_host_and_offers_legal_ones(set_pool):
    """The host is chosen as the spell resolves (no second "target"), by the
    caster, among the *other* permanents the Aura can enchant: the two
    creatures across the table, not the Bears it is on and not a Forest."""
    game = _w1g9_duel(
        set_pool, hand0=["Aura Graft"], bf0=["Grizzly Bears"],
        bf1=["Gray Ogre", "Hill Giant", "Forest"],
    )
    game.interactive_seats = {0, 1}
    bears, giant = _w1g9_on(game, 0, "Grizzly Bears"), _w1g9_on(game, 1, "Hill Giant")
    weakness = _w1g9_enchant(game, set_pool, 1, "Weakness", bears)
    assert game.queue_from_hand(
        0, "Aura Graft", target_permanent_ids=[weakness.permanent_id]
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    prompt = game.pending_choice_of("permanent_choice")
    assert prompt is not None and prompt.player_index == 0
    offered = {p.card.name for p in game.live_permanent_choices(prompt)}
    assert offered == {"Gray Ogre", "Hill Giant"}
    assert game.confirm_permanent_choice(0, permanent_id=giant.permanent_id)
    _w1g9_resolve_stack(game)
    assert _w1g9_where(game, weakness) == (0, giant)


def test_aura_graft_keeps_an_aura_it_has_nowhere_to_move(set_pool):
    """The ruling of 2004-10-04: "If there is no legal place to move the
    enchantment, then it doesn't move but you still control it."""
    game = _w1g9_duel(
        set_pool, hand0=["Aura Graft"], bf0=["Grizzly Bears"], bf1=["Forest"],
    )
    bears = _w1g9_on(game, 0, "Grizzly Bears")
    weakness = _w1g9_enchant(game, set_pool, 1, "Weakness", bears)
    assert game.queue_from_hand(
        0, "Aura Graft", target_permanent_ids=[weakness.permanent_id]
    ).supported
    _w1g9_resolve_stack(game)
    assert _w1g9_where(game, weakness) == (0, bears)


def test_aura_graft_moves_an_aura_its_caster_already_controls(set_pool):
    """The ruling of 2007-07-15: "You can target an Aura you already control
    just to move that Aura to a new permanent." And the Aura's own enchant
    line is what decides where: a land Aura goes to a land."""
    game = _w1g9_duel(
        set_pool, hand0=["Aura Graft"], bf0=["Forest", "Grizzly Bears"],
        bf1=["Forest"],
    )
    mine, theirs = _w1g9_on(game, 0, "Forest"), _w1g9_on(game, 1, "Forest")
    growth = _w1g9_enchant(game, set_pool, 0, "Wild Growth", mine)
    assert game.queue_from_hand(
        0, "Aura Graft", target_permanent_ids=[growth.permanent_id]
    ).supported
    _w1g9_resolve_stack(game)
    assert _w1g9_where(game, growth) == (0, theirs)


def test_aura_graft_needs_an_aura_to_aim_at(set_pool):
    game = _w1g9_duel(set_pool, hand0=["Aura Graft"], bf1=["Crusade"])
    crusade = _w1g9_on(game, 1, "Crusade")
    for ids in ([crusade.permanent_id], None):
        assert not game.queue_from_hand(
            0, "Aura Graft", target_permanent_ids=ids
        ).supported
    assert _w1g9_names(game.players[0].hand) == ["Aura Graft"]


@_w1g9_pytest.mark.parametrize("text, supported", [
    ("Gain control of target Aura that's attached to a permanent. Attach it "
     "to another permanent it can enchant.", True),
    ("Destroy target Aura that's attached to a permanent.", True),
    # "It" after a sentence that chose an object is that object: attaching it
    # to a second *target* is a pair of targets nothing here reads, and it
    # compiled as the spell attaching itself.
    ("Gain control of target Aura. Attach it to target creature.", False),
])
def test_the_attach_pronoun_names_what_the_sentence_in_front_took(text, supported):
    card = _w1g9_mk_card("Graft Probe", "{U}", "Instant", text)
    assert _w1g9_compile(card).supported is supported


# --- The instants that compiled on arrival, each given a game ---------------

def _w1g9_settle(game, answer=None):
    """Resolve the stack one object at a time, answering what each leaves
    owed before the next resolves. *answer* is offered every prompt first and
    returns True when it has dealt with it; the rest take their default.

    Not `resolve_stack`: an offer made to a seat nobody is sitting in does not
    hold the stack, so that helper resolves the spell underneath before the
    offer is answered - which for Divert is the whole card.
    """
    for _ in range(40):
        if game.pending_choices:
            choice = game.pending_choices[0]
            if answer is None or not answer(choice):
                game.take_choice_default(choice)
            continue
        if not game.stack:
            return
        game.resolve_top_of_stack(pause_for_choices=True)
    raise AssertionError("the stack never settled")


def test_afflict_shrinks_a_creature_and_draws(set_pool):
    game = _w1g9_duel(set_pool, hand0=["Afflict"], bf1=["Llanowar Elves", "Forest"])
    elves, forest = _w1g9_on(game, 1, "Llanowar Elves"), _w1g9_on(game, 1, "Forest")
    assert not game.queue_from_hand(
        0, "Afflict", target_permanent_ids=[forest.permanent_id]
    ).supported
    assert game.queue_from_hand(
        0, "Afflict", target_permanent_ids=[elves.permanent_id]
    ).supported
    _w1g9_resolve_stack(game)
    game.check_state_based_actions()
    assert _w1g9_names(game.players[1].graveyard) == ["Llanowar Elves"]
    assert len(game.players[0].hand) == 1


def test_afflict_draws_nothing_once_its_only_target_is_gone(set_pool):
    """CR 608.2b: every target illegal, so the spell does not resolve - the
    second line is not a consolation prize."""
    game = _w1g9_duel(
        set_pool, hand0=["Afflict"], hand1=["Unsummon"], bf1=["Grizzly Bears"],
    )
    bears = _w1g9_on(game, 1, "Grizzly Bears")
    assert game.queue_from_hand(
        0, "Afflict", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert game.queue_from_hand(
        1, "Unsummon", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g9_resolve_stack(game)
    assert game.players[0].hand == []


def test_peek_shows_its_caster_a_hand_without_telling_the_table(set_pool):
    game = _w1g9_duel(set_pool, hand0=["Peek"], hand1=["Grizzly Bears", "Forest"])
    game.interactive_seats = {0, 1}
    assert game.queue_from_hand(0, "Peek", target_player_index=1).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    shown = game.pending_choices[0]
    assert (shown.kind, shown.player_index) == ("hand_reveal", 0)
    assert len(game.players[0].hand) == 1, "and it drew"
    assert not any("Grizzly Bears" in line for line in game.log), game.log


def test_vivify_makes_a_land_a_creature_that_is_still_a_land(set_pool):
    game = _w1g9_duel(set_pool, hand0=["Vivify"], bf0=["Forest", "Grizzly Bears"])
    forest, bears = _w1g9_on(game, 0, "Forest"), _w1g9_on(game, 0, "Grizzly Bears")
    assert not game.queue_from_hand(
        0, "Vivify", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert game.queue_from_hand(
        0, "Vivify", target_permanent_ids=[forest.permanent_id]
    ).supported
    _w1g9_resolve_stack(game)
    assert forest.is_creature and forest.has_type("land") and forest.has_type("forest")
    assert (forest.effective_power, forest.effective_toughness) == (3, 3)
    assert game.tap_land_for_mana(0, "Forest", permanent_id=forest.permanent_id)
    assert len(game.players[0].hand) == 1
    game.resolve_cleanup_step(0)
    game._recompute_continuous_effects()
    assert not forest.is_creature


def _w1g9_divert_table(set_pool, payer_mana):
    game = _w1g9_duel(
        set_pool, hand0=["Divert"], hand1=["Lightning Bolt"],
        bf0=["Grizzly Bears"], bf1=["Gray Ogre"], costs=True,
    )
    game.interactive_seats = {0, 1}
    game.players[0].mana_pool.update({"U": 1})
    game.players[1].mana_pool.update({"R": 1 + payer_mana})
    bears, ogre = _w1g9_on(game, 0, "Grizzly Bears"), _w1g9_on(game, 1, "Gray Ogre")
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert game.queue_from_hand(0, "Divert", target_stack_index=0).supported
    return game, bears, ogre


def test_divert_turns_a_spell_onto_the_target_its_caster_names(set_pool):
    """"Change the target of target spell with a single target unless that
    spell's controller pays {2}." Unpaid, Divert's controller chooses among the
    *other* legal targets (CR 115.7a) and the Bolt lands there."""
    game, bears, ogre = _w1g9_divert_table(set_pool, payer_mana=2)

    def answer(choice):
        if choice.kind == "optional_pay":
            assert choice.player_index == 1, "the Bolt's controller is asked"
            return game.confirm_optional_pay(1, accept=False)
        if choice.kind == "retarget_choice":
            assert choice.player_index == 0
            names = [option["name"] for option in choice.data["options"]]
            assert "Grizzly Bears" not in names and "Gray Ogre" in names
            return game.confirm_retarget_choice(0, names.index("Gray Ogre"))
        return False

    _w1g9_settle(game, answer)
    game.check_state_based_actions()
    assert bears in game.all_permanents() and ogre not in game.all_permanents()
    assert game.players[1].mana_pool["R"] == 2


def test_divert_does_nothing_to_a_spell_whose_controller_pays(set_pool):
    game, bears, _ogre = _w1g9_divert_table(set_pool, payer_mana=2)
    _w1g9_settle(
        game,
        lambda c: c.kind == "optional_pay" and game.confirm_optional_pay(1, accept=True),
    )
    game.check_state_based_actions()
    assert bears not in game.all_permanents()
    assert game.players[1].mana_pool["R"] == 0


def test_divert_cannot_be_aimed_at_a_spell_with_no_target(set_pool):
    game = _w1g9_duel(set_pool, hand0=["Divert"], hand1=["Wrath of God"])
    assert game.queue_from_hand(1, "Wrath of God").supported
    assert not game.queue_from_hand(0, "Divert", target_stack_index=0).supported
    assert _w1g9_names(game.players[0].hand) == ["Divert"]

# ==== end W1G9 ======================================================
