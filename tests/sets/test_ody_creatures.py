"""Odyssey creatures.

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
    return game  # _w1g5_table (creatures)


def _w1g5_put(game, seat, name):
    """*name* onto *seat*'s battlefield through the one entry path, awake."""
    permanent = _W1G5Permanent(card=game._w1g5_card(name))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g5_put (creatures)


def _w1g5_slot(game, seat, permanent) -> int:
    return next(
        index for index, perm in enumerate(game.controlled_by(seat))
        if perm is permanent
    )  # _w1g5_slot (creatures)


def _w1g5_dealt(game, recipient, amount, source, source_seat=None):
    """One damage event through CR 120.4, reporting what was dealt."""
    event = {"recipient": recipient, "amount": amount, "source": source,
             "combat": False}
    if source_seat is not None:
        event["source_seat"] = source_seat
    return _w1g5_deal_damage(game, event).dealt  # _w1g5_dealt (creatures)


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


def _w1g5_offered(game, seat, name):
    """The names a cast of *name* by *seat* is offered as permanent targets."""
    spec = game.cast_target_spec(seat, game._w1g5_card(name))
    return sorted(
        target["name"] for target in spec.get("valid_targets", ())
        if target.get("kind") == "permanent"
    )  # _w1g5_offered (creatures)


# Iridescent Angel -------------------------------------------------------------


def test_w1g5_iridescent_angel_has_five_protections_and_none_from_colourless(
    catalog_by_name, set_pool,
):
    """"Flying, protection from each color" — CR 702.16h: shorthand for five
    separate protection abilities (the card's own ruling spells them out). No
    coloured spell may target it, no coloured Aura may be put on it, damage
    from a coloured source is prevented — and a colourless source does all
    three. The wire names the five colours, which is what a player reads."""
    from web.serialization import _effective_keywords

    game = _w1g5_table(catalog_by_name, set_pool, hand1=[
        "Terror", "Lightning Bolt", "Swords to Plowshares", "Unsummon",
        "Giant Growth", "Holy Strength",
    ])
    angel = _w1g5_put(game, 0, "Iridescent Angel")
    rod = _w1g5_put(game, 1, "Rod of Ruin")

    assert game._protection_qualities(angel) == {
        ("color", symbol) for symbol in "WUBRG"
    }
    for name in ("Terror", "Lightning Bolt", "Swords to Plowshares", "Unsummon",
                 "Giant Growth", "Holy Strength"):
        assert "Iridescent Angel" not in _w1g5_offered(game, 1, name), name
        refused = game.cast_from_hand(
            1, name, target_permanent_ids=[angel.permanent_id],
        )
        assert not refused.supported, (name, refused.details)
    assert len(game.players[1].hand) == 6, "a refused cast spends nothing"

    assert _w1g5_dealt(game, angel, 3, catalog_by_name["Lightning Bolt"], 1) == 0
    assert _w1g5_dealt(game, angel, 1, rod) == 1
    shot = game.activate_permanent_ability(
        1, "Rod of Ruin", target_permanent_ids=[angel.permanent_id],
    )
    _w1g5_resolve_stack(game)
    assert shot.supported, shot.details
    assert any("Rod of Ruin dealt 1 damage to Iridescent Angel" in line
               for line in game.log)

    badge = [word for word in _effective_keywords(angel, game)
             if word.startswith("Protection")]
    assert badge == ["Protection from black and blue and green and red and white"]


def test_w1g5_iridescent_angel_is_blocked_only_by_a_colourless_creature(
    catalog_by_name, set_pool,
):
    """CR 702.16f: an attacker with protection can't be blocked by a creature
    with the quality. A Serra Angel (white, flying) may not block it; an
    Ornithopter (colourless, flying) may."""
    game = _w1g5_table(catalog_by_name, set_pool)
    angel = _w1g5_put(game, 0, "Iridescent Angel")
    serra = _w1g5_put(game, 1, "Serra Angel")
    thopter = _w1g5_put(game, 1, "Ornithopter")

    _w1g5_to_declare_attackers(game)
    slot = _w1g5_slot(game, 0, angel)
    assert game.declare_attackers(0, [slot])[0]
    game.advance_combat_phase()
    assert not game.declare_blockers(1, {_w1g5_slot(game, 1, serra): slot})[0]
    assert game.declare_blockers(1, {_w1g5_slot(game, 1, thopter): slot})[0]
    _w1g5_finish_combat(game)

    assert game.players[1].life == 20
    assert [card.name for card in game.players[1].graveyard] == ["Ornithopter"]


# Devoted Caretaker ------------------------------------------------------------


def test_w1g5_devoted_caretaker_protects_from_instant_and_sorcery_spells_only(
    catalog_by_name, set_pool,
):
    """"{W}, {T}: Target permanent you control gains protection from instant
    spells and from sorcery spells until end of turn." Two protection
    abilities (CR 702.16g) whose quality is a card type narrowed to *spells*.
    The card's ruling: it can't be targeted by instant and sorcery spells and
    damage from them is prevented. What it does **not** stop is everything
    that is not such a spell — an Aura spell, an activated ability, a
    creature's damage."""
    from web.serialization import _effective_keywords

    game = _w1g5_table(catalog_by_name, set_pool, hand1=[
        "Lightning Bolt", "Terror", "Unsummon", "Holy Strength",
    ])
    caretaker = _w1g5_put(game, 0, "Devoted Caretaker")
    bears = _w1g5_put(game, 0, "Grizzly Bears")
    _w1g5_put(game, 0, "Forest")
    giant = _w1g5_put(game, 1, "Hill Giant")
    _w1g5_put(game, 1, "Prodigal Sorcerer")

    spec = game.activation_target_spec(
        0, _w1g5_slot(game, 0, caretaker), ability_index=0,
    )
    assert sorted(t["name"] for t in spec["valid_targets"]) == [
        "Devoted Caretaker", "Forest", "Grizzly Bears",
    ], "'target permanent you control' — any permanent, and only the activator's"
    refused = game.activate_permanent_ability(
        0, "Devoted Caretaker", target_permanent_ids=[giant.permanent_id],
    )
    assert not refused.supported and not caretaker.tapped, refused.details

    granted = game.activate_permanent_ability(
        0, "Devoted Caretaker", target_permanent_ids=[bears.permanent_id],
    )
    _w1g5_resolve_stack(game)
    assert granted.supported, granted.details
    assert game._protection_qualities(bears) == {
        ("spell_type", "instant"), ("spell_type", "sorcery"),
    }
    assert [word for word in _effective_keywords(bears, game)
            if word.startswith("Protection")] == [
        "Protection from instant spells and sorcery spells"
    ]

    for name in ("Lightning Bolt", "Terror", "Unsummon"):
        refused = game.cast_from_hand(
            1, name, target_permanent_ids=[bears.permanent_id],
        )
        assert not refused.supported, (name, refused.details)
    aura = game.cast_from_hand(
        1, "Holy Strength", target_permanent_ids=[bears.permanent_id],
    )
    _w1g5_resolve_stack(game)
    assert aura.supported, "an Aura spell is neither an instant nor a sorcery"
    assert (bears.effective_power, bears.effective_toughness) == (3, 4)

    ping = game.activate_permanent_ability(
        1, "Prodigal Sorcerer", target_permanent_ids=[bears.permanent_id],
    )
    _w1g5_resolve_stack(game)
    assert ping.supported, "an ability is not a spell"
    assert any("Prodigal Sorcerer dealt 1 damage to Grizzly Bears" in line
               for line in game.log)

    assert _w1g5_dealt(game, bears, 3, catalog_by_name["Lightning Bolt"], 1) == 0
    assert _w1g5_dealt(game, bears, 2, catalog_by_name["Earthquake"], 1) == 0
    assert _w1g5_dealt(game, bears, 2, giant) == 2

    game.resolve_cleanup_step(0)
    assert game._protection_qualities(bears) == set(), "until end of turn"


# Spellbane Centaur ------------------------------------------------------------


def test_w1g5_spellbane_centaur_stops_blue_spells_and_blue_sources_abilities(
    catalog_by_name, set_pool,
):
    """"Creatures you control can't be the targets of blue spells or abilities
    from blue sources." Two conjuncts, separately targeted things (CR 115.1a,
    CR 115.1c/d): a blue *spell* is refused, an *ability* of a blue permanent
    is refused, and a red spell and a colourless artifact's ability are not.
    "You control" is the Centaur's controller — and it covers the Centaur, and
    its controller's own blue spells, because the sentence names no caster."""
    game = _w1g5_table(
        catalog_by_name, set_pool,
        hand0=["Unsummon"], hand1=["Unsummon", "Control Magic", "Lightning Bolt"],
    )
    centaur = _w1g5_put(game, 0, "Spellbane Centaur")
    bears = _w1g5_put(game, 0, "Grizzly Bears")
    forest = _w1g5_put(game, 0, "Forest")
    sorcerer = _w1g5_put(game, 1, "Prodigal Sorcerer")
    _w1g5_put(game, 1, "Rod of Ruin")
    _w1g5_put(game, 1, "Hill Giant")

    assert _w1g5_offered(game, 1, "Unsummon") == ["Hill Giant", "Prodigal Sorcerer"]
    for target in (bears, centaur):
        refused = game.cast_from_hand(
            1, "Unsummon", target_permanent_ids=[target.permanent_id],
        )
        assert not refused.supported, refused.details
    assert not game.cast_from_hand(
        1, "Control Magic", target_permanent_ids=[bears.permanent_id],
    ).supported
    assert not game.cast_from_hand(
        0, "Unsummon", target_permanent_ids=[centaur.permanent_id],
    ).supported, "the sentence names no caster: its controller's blue spells too"

    spec = game.activation_target_spec(
        1, _w1g5_slot(game, 1, sorcerer), ability_index=0,
    )
    assert sorted(
        t["name"] for t in spec["valid_targets"] if t["kind"] == "permanent"
    ) == ["Hill Giant", "Prodigal Sorcerer"]
    blue_ping = game.activate_permanent_ability(
        1, "Prodigal Sorcerer", target_permanent_ids=[bears.permanent_id],
    )
    assert not blue_ping.supported and not sorcerer.tapped, blue_ping.details

    rod_ping = game.activate_permanent_ability(
        1, "Rod of Ruin", target_permanent_ids=[bears.permanent_id],
    )
    _w1g5_resolve_stack(game)
    assert rod_ping.supported, "a colourless source's ability is not a blue one"
    bolt = game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[centaur.permanent_id],
    )
    _w1g5_resolve_stack(game)
    assert bolt.supported and not game.is_on_battlefield(centaur)

    # The Centaur gone, the sentence is gone with it (CR 611.3a).
    assert "Grizzly Bears" in _w1g5_offered(game, 1, "Unsummon")
    assert game.is_on_battlefield(forest)


def test_w1g5_spellbane_centaur_entering_in_response_fizzles_a_blue_spell(
    catalog_by_name, set_pool,
):
    """CR 608.2b: a target that became illegal by resolution is not affected.
    An Unsummon is cast at a Grizzly Bears; the Centaur enters in response;
    the spell leaves the stack having done nothing. And the opponent's
    creatures were never covered — "creatures **you** control"."""
    game = _w1g5_table(catalog_by_name, set_pool, hand1=["Unsummon", "Unsummon"])
    bears = _w1g5_put(game, 0, "Grizzly Bears")
    theirs = _w1g5_put(game, 1, "Hill Giant")

    assert game.queue_from_hand(
        1, "Unsummon", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g5_put(game, 0, "Spellbane Centaur")
    _w1g5_resolve_stack(game)
    assert game.is_on_battlefield(bears)
    assert [card.name for card in game.players[1].graveyard] == ["Unsummon"]

    assert game.cast_from_hand(
        1, "Unsummon", target_permanent_ids=[theirs.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert not game.is_on_battlefield(theirs)

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
