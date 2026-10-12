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

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

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

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
