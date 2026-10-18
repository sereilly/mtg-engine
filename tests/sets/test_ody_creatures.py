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
# (moved whole to test_ody_creatures_first_groups.py when this file reached its size cap)

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.
# (moved whole to test_ody_creatures_first_groups.py when this file reached its size cap)

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.
# (moved whole to test_ody_creatures_first_groups.py when this file reached its size cap)

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


# Obstinate Familiar -----------------------------------------------------------


def test_w1g5_obstinate_familiar_asks_its_controller_about_each_draw(
    catalog_by_name, set_pool,
):
    """"If you would draw a card, you may skip that draw instead." An optional
    replacement of one draw by nothing (CR 614.10), asked through the one draw
    seam. A two-card draw is two draws (CR 121.2), so two offers: the first is
    skipped — no card moves — and the second is declined, and the draw it
    leaves is made without the Familiar being asked again (CR 614.5)."""
    game = _w1g5_table(catalog_by_name, set_pool, interactive={0})
    _w1g5_put(game, 0, "Obstinate Familiar")
    alice = game.players[0]

    assert game._draw_with_replacements(alice, 2) == 0, "the draw is suspended"
    assert [c.kind for c in game.pending_replacement_choices] == ["skip_draw"]
    assert game.pending_skip_draws[0]["options"] == ["draw the card", "skip the draw"]
    assert game.waiting_prompt() is not None, "the game waits on the answer"

    assert game.confirm_skip_draw(0, skip=True)
    assert alice.hand == [] and len(alice.library) == 20
    assert len(game.pending_skip_draws) == 1, "the second draw is its own offer"

    assert game.confirm_skip_draw(0, skip=False)
    assert len(alice.hand) == 1 and len(alice.library) == 19
    assert game.pending_replacement_choices == []


def test_w1g5_obstinate_familiar_is_its_controllers_own_and_saves_an_empty_library(
    catalog_by_name, set_pool,
):
    """"If **you** would draw" is the Familiar's controller (CR 109.5): an
    opponent's draw is not offered. And a seat nobody asks takes the choice a
    player would make — it draws while there is a card to draw, and skips a
    draw from an empty library, so the Familiar's controller is never decked
    (CR 704.5b) beside the permanent that prevents it."""
    game = _w1g5_table(catalog_by_name, set_pool, interactive={1})
    _w1g5_put(game, 0, "Obstinate Familiar")
    alice, bob = game.players

    assert game._draw_with_replacements(bob, 1) == 1
    assert game.pending_replacement_choices == []

    assert game._draw_with_replacements(alice, 2) == 2
    alice.library = []
    assert game._draw_with_replacements(alice, 1) == 0
    game.check_state_based_actions()
    assert not alice.lost
    assert any("Alice skipped a draw (Obstinate Familiar)" in line for line in game.log)

    # Without the Familiar the same draw is the game.
    familiar = next(p for p in game.all_permanents() if p.card.name == "Obstinate Familiar")
    game.remove_from_battlefield(familiar)
    game._draw_with_replacements(alice, 1)
    game.check_state_based_actions()
    assert alice.lost


def test_w1g5_obstinate_familiar_is_asked_in_the_draw_step(catalog_by_name, set_pool):
    """The turn-based draw (CR 504.1) is a draw like any other: the Familiar's
    controller is asked, and the game waits until they answer."""
    game = _w1g5_table(catalog_by_name, set_pool, interactive={0})
    _w1g5_put(game, 0, "Obstinate Familiar")
    game.turn = 3
    game.start_turn(0)

    assert [c.kind for c in game.pending_replacement_choices] == ["skip_draw"]
    assert game.players[0].hand == []
    assert game.confirm_skip_draw(0, skip=False)
    assert len(game.players[0].hand) == 1


def test_w1g5_the_skip_draw_prompt_is_rendered_with_its_labels(
    catalog_by_name, set_pool,
):
    """The server half of the wire. The prompt carries the option labels the
    resolver accepts, the source's name, how many offers are queued and the
    size of the library — which is the decision. **The browser has no
    renderer for this key yet** (W1G5 stayed out of ``web/static/``):
    ``tests/ui/test_prompt_client_coverage.py`` names ``skip_draw`` until one
    is added."""
    from web.prompts import PROMPT_RENDERERS

    game = _w1g5_table(catalog_by_name, set_pool, interactive={0})
    _w1g5_put(game, 0, "Obstinate Familiar")
    game._draw_with_replacements(game.players[0], 2)

    class _Ctx:  # the two attributes this renderer reads
        pass

    ctx = _Ctx()
    ctx.game = game
    assert PROMPT_RENDERERS["skip_draw"](ctx, list(game.pending_replacement_choices)) == {
        "player_seat": 0,
        "source_name": "Obstinate Familiar",
        "options": ["draw the card", "skip the draw"],
        "remaining": 1,
        "library_size": 20,
    }


# The creatures that compiled at the ingest, each given a game -----------------


def _w1g5_activation_targets(game, seat, permanent, ability_index=0):
    """The names an activation of *permanent*'s ability is offered."""
    spec = game.activation_target_spec(
        seat, _w1g5_slot(game, seat, permanent), ability_index=ability_index,
    )
    return sorted(
        target["name"] for target in spec.get("valid_targets", ())
        if target.get("kind") == "permanent"
    )  # _w1g5_activation_targets


@_w1g5_pytest.mark.parametrize("name, spell, same, other", [
    ("Aven Smokeweaver", "Lightning Bolt", "Hill Giant", "Grizzly Bears"),
    ("Treetop Sentinel", "Giant Growth", "Grizzly Bears", "Hill Giant"),
])
def test_w1g5_the_protection_fliers_fly_and_are_protected_from_their_colour(
    catalog_by_name, set_pool, name, spell, same, other,
):
    """"Flying, protection from red" / "…from green". A spell of the colour is
    an illegal target, a creature of the colour deals it no damage, and a
    Giant Spider — green, with reach — may block the Smokeweaver and not the
    Sentinel (CR 702.16f)."""
    game = _w1g5_table(catalog_by_name, set_pool, hand1=[spell])
    bird = _w1g5_put(game, 0, name)
    coloured = _w1g5_put(game, 1, same)
    plain = _w1g5_put(game, 1, other)
    spider = _w1g5_put(game, 1, "Giant Spider")

    assert not game.cast_from_hand(
        1, spell, target_permanent_ids=[bird.permanent_id],
    ).supported
    assert _w1g5_dealt(game, bird, 2, coloured) == 0
    assert _w1g5_dealt(game, bird, 1, plain) == 1
    bird.damage_marked = 0

    _w1g5_to_declare_attackers(game)
    slot = _w1g5_slot(game, 0, bird)
    assert game.declare_attackers(0, [slot])[0]
    game.advance_combat_phase()
    assert not game.declare_blockers(1, {_w1g5_slot(game, 1, plain): slot})[0], "flying"
    assert game.declare_blockers(1, {_w1g5_slot(game, 1, spider): slot})[0] is (
        name == "Aven Smokeweaver"
    )


def test_w1g5_beloved_chaplain_is_protected_from_creatures_and_from_nothing_else(
    catalog_by_name, set_pool,
):
    """"Protection from creatures": a creature's ability may not target it, no
    creature — an artifact creature included — may block it or damage it, and
    a noncreature source (a spell, a Rod of Ruin) is not a creature."""
    game = _w1g5_table(catalog_by_name, set_pool, hand1=["Lightning Bolt"])
    chaplain = _w1g5_put(game, 0, "Beloved Chaplain")
    sorcerer = _w1g5_put(game, 1, "Prodigal Sorcerer")
    giant = _w1g5_put(game, 1, "Hill Giant")
    thopter = _w1g5_put(game, 1, "Ornithopter")
    _w1g5_put(game, 1, "Rod of Ruin")

    assert "Beloved Chaplain" not in _w1g5_activation_targets(game, 1, sorcerer)
    assert not game.activate_permanent_ability(
        1, "Prodigal Sorcerer", target_permanent_ids=[chaplain.permanent_id],
    ).supported
    assert _w1g5_dealt(game, chaplain, 3, giant) == 0

    _w1g5_to_declare_attackers(game)
    slot = _w1g5_slot(game, 0, chaplain)
    assert game.declare_attackers(0, [slot])[0]
    game.advance_combat_phase()
    for blocker in (giant, thopter):
        assert not game.declare_blockers(1, {_w1g5_slot(game, 1, blocker): slot})[0]
    assert game.declare_blockers(1, {})[0]
    _w1g5_finish_combat(game)
    assert game.players[1].life == 19

    rod = game.activate_permanent_ability(
        1, "Rod of Ruin", target_permanent_ids=[chaplain.permanent_id],
    )
    _w1g5_resolve_stack(game)
    assert rod.supported and not game.is_on_battlefield(chaplain)


def test_w1g5_aven_archer_and_skyshooter_shoot_only_what_is_in_combat(
    catalog_by_name, set_pool,
):
    """"…deals 2 damage to target attacking or blocking creature." / "{T},
    Sacrifice this creature: Destroy target attacking or blocking creature
    with flying." Outside combat neither has a target and neither pays
    anything; in combat the Archer may shoot any attacker and the Skyshooter
    only the one with flying."""
    game = _w1g5_table(catalog_by_name, set_pool)
    archer = _w1g5_put(game, 1, "Aven Archer")
    shooter = _w1g5_put(game, 1, "Skyshooter")
    serra = _w1g5_put(game, 0, "Serra Angel")
    giant = _w1g5_put(game, 0, "Hill Giant")
    idle = _w1g5_put(game, 0, "Birds of Paradise")

    assert _w1g5_activation_targets(game, 1, archer) == []
    assert not game.activate_permanent_ability(
        1, "Aven Archer", target_permanent_ids=[giant.permanent_id],
    ).supported
    assert not archer.tapped

    _w1g5_to_declare_attackers(game)
    assert game.declare_attackers(
        0, [_w1g5_slot(game, 0, serra), _w1g5_slot(game, 0, giant)],
    )[0]
    assert _w1g5_activation_targets(game, 1, archer) == ["Hill Giant", "Serra Angel"]
    assert _w1g5_activation_targets(game, 1, shooter) == ["Serra Angel"]
    for wrong in (giant, idle):
        assert not game.activate_permanent_ability(
            1, "Skyshooter", target_permanent_ids=[wrong.permanent_id],
        ).supported
        assert game.is_on_battlefield(shooter), "a refused activation sacrifices nothing"

    assert game.activate_permanent_ability(
        1, "Aven Archer", target_permanent_ids=[giant.permanent_id],
    ).supported
    assert game.activate_permanent_ability(
        1, "Skyshooter", target_permanent_ids=[serra.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert giant.damage_marked == 2 and archer.tapped
    assert not game.is_on_battlefield(serra) and not game.is_on_battlefield(shooter)


def test_w1g5_skyshooter_has_reach(catalog_by_name, set_pool):
    game = _w1g5_table(catalog_by_name, set_pool)
    shooter = _w1g5_put(game, 1, "Skyshooter")
    serra = _w1g5_put(game, 0, "Serra Angel")
    _w1g5_to_declare_attackers(game)
    slot = _w1g5_slot(game, 0, serra)
    assert game.declare_attackers(0, [slot])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {_w1g5_slot(game, 1, shooter): slot})[0]


def test_w1g5_dreamwinder_needs_an_island_to_attack_and_makes_one(
    catalog_by_name, set_pool,
):
    """"This creature can't attack unless defending player controls an Island.
    {U}, Sacrifice an Island: Target land becomes an Island until end of
    turn." The cost is an Island of its controller's, the target any land, and
    "becomes" replaces the land's types (CR 305.7) until cleanup."""
    game = _w1g5_table(catalog_by_name, set_pool)
    winder = _w1g5_put(game, 0, "Dreamwinder")
    _w1g5_put(game, 0, "Island")
    forest = _w1g5_put(game, 1, "Forest")

    _w1g5_to_declare_attackers(game)
    assert not game.declare_attackers(0, [_w1g5_slot(game, 0, winder)])[0]
    assert not game.activate_permanent_ability(
        0, "Dreamwinder", target_permanent_ids=[winder.permanent_id],
    ).supported, "a creature is not a land"

    turned = game.activate_permanent_ability(
        0, "Dreamwinder", target_permanent_ids=[forest.permanent_id],
    )
    _w1g5_resolve_stack(game)
    assert turned.supported
    assert not any(p.card.name == "Island" for p in game.controlled_by(0))
    assert forest.has_type("island") and not forest.has_type("forest")
    assert game.declare_attackers(0, [_w1g5_slot(game, 0, winder)])[0]

    game.resolve_cleanup_step(0)
    assert forest.has_type("forest") and not forest.has_type("island")
    assert not game.activate_permanent_ability(
        0, "Dreamwinder", target_permanent_ids=[forest.permanent_id],
    ).supported, "no Island left to sacrifice"


def test_w1g5_ember_beast_neither_attacks_nor_blocks_alone(catalog_by_name, set_pool):
    game = _w1g5_table(catalog_by_name, set_pool)
    beast = _w1g5_put(game, 0, "Ember Beast")
    bears = _w1g5_put(game, 0, "Grizzly Bears")
    _w1g5_to_declare_attackers(game)
    assert not game.declare_attackers(0, [_w1g5_slot(game, 0, beast)])[0]
    assert game.declare_attackers(
        0, [_w1g5_slot(game, 0, beast), _w1g5_slot(game, 0, bears)],
    )[0]

    game = _w1g5_table(catalog_by_name, set_pool)
    beast = _w1g5_put(game, 1, "Ember Beast")
    friend = _w1g5_put(game, 1, "Grizzly Bears")
    giant = _w1g5_put(game, 0, "Hill Giant")
    ogre = _w1g5_put(game, 0, "Gray Ogre")
    _w1g5_to_declare_attackers(game)
    first, second = _w1g5_slot(game, 0, giant), _w1g5_slot(game, 0, ogre)
    assert game.declare_attackers(0, [first, second])[0]
    game.advance_combat_phase()
    assert not game.declare_blockers(1, {_w1g5_slot(game, 1, beast): first})[0]
    assert game.declare_blockers(1, {
        _w1g5_slot(game, 1, beast): first, _w1g5_slot(game, 1, friend): second,
    })[0]


def test_w1g5_escape_artist_cant_be_blocked_and_discards_to_go_home(
    catalog_by_name, set_pool,
):
    game = _w1g5_table(catalog_by_name, set_pool)
    artist = _w1g5_put(game, 0, "Escape Artist")
    wall = _w1g5_put(game, 1, "Wall of Stone")
    assert not game.activate_permanent_ability(0, "Escape Artist").supported, (
        "no card to discard"
    )
    _w1g5_to_declare_attackers(game)
    slot = _w1g5_slot(game, 0, artist)
    assert game.declare_attackers(0, [slot])[0]
    game.advance_combat_phase()
    assert not game.declare_blockers(1, {_w1g5_slot(game, 1, wall): slot})[0]
    assert game.declare_blockers(1, {})[0]
    _w1g5_finish_combat(game)
    assert game.players[1].life == 19

    game.players[0].hand = [catalog_by_name["Forest"]]
    home = game.activate_permanent_ability(0, "Escape Artist")
    _w1g5_resolve_stack(game)
    assert home.supported and not game.is_on_battlefield(artist)
    assert [c.name for c in game.players[0].hand] == ["Escape Artist"]
    assert [c.name for c in game.players[0].graveyard] == ["Forest"]


def test_w1g5_luminous_guardian_buys_one_more_block_per_activation(
    catalog_by_name, set_pool,
):
    """"{W}: This creature gets +0/+1 until end of turn. {2}: This creature
    can block an additional creature this turn." One block by default
    (CR 509.1a), one more for each resolved {2} — and no more than that."""
    game = _w1g5_table(catalog_by_name, set_pool)
    guardian = _w1g5_put(game, 1, "Luminous Guardian")
    attackers = [_w1g5_put(game, 0, name)
                 for name in ("Grizzly Bears", "Savannah Lions", "Hill Giant")]
    assert game.activate_permanent_ability(1, "Luminous Guardian", ability_index=0).supported
    _w1g5_resolve_stack(game)
    assert (guardian.effective_power, guardian.effective_toughness) == (1, 5)

    _w1g5_to_declare_attackers(game)
    slots = [_w1g5_slot(game, 0, attacker) for attacker in attackers]
    assert game.declare_attackers(0, slots)[0]
    game.advance_combat_phase()
    mine = _w1g5_slot(game, 1, guardian)
    assert not game.declare_blockers(1, {mine: slots[:2]})[0]
    assert game.activate_permanent_ability(1, "Luminous Guardian", ability_index=1).supported
    _w1g5_resolve_stack(game)
    assert not game.declare_blockers(1, {mine: slots})[0], "one activation, one more"
    assert game.declare_blockers(1, {mine: slots[:2]})[0]


def test_w1g5_master_apothecary_taps_any_cleric_for_two_points_of_prevention(
    catalog_by_name, set_pool,
):
    """"Tap an untapped Cleric you control: Prevent the next 2 damage that
    would be dealt to any target this turn." The cost is a Cleric, not the
    {T} symbol, so the Apothecary pays with itself, then with another Cleric,
    then cannot pay; each activation is a CR 615.7 pool of two points."""
    game = _w1g5_table(catalog_by_name, set_pool, hand1=["Lightning Bolt"] * 2)
    apothecary = _w1g5_put(game, 0, "Master Apothecary")
    caretaker = _w1g5_put(game, 0, "Devoted Caretaker")
    bears = _w1g5_put(game, 0, "Grizzly Bears")

    assert game.activate_permanent_ability(
        0, "Master Apothecary", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert apothecary.tapped and not caretaker.tapped
    assert game.activate_permanent_ability(
        0, "Master Apothecary", target_player_index=0,
    ).supported
    _w1g5_resolve_stack(game)
    assert caretaker.tapped
    assert not game.activate_permanent_ability(
        0, "Master Apothecary", target_player_index=0,
    ).supported, "no untapped Cleric left"

    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert game.is_on_battlefield(bears) and bears.damage_marked == 1
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g5_resolve_stack(game)
    assert game.players[0].life == 19


def test_w1g5_patchwork_gnomes_discards_to_regenerate(catalog_by_name, set_pool):
    game = _w1g5_table(catalog_by_name, set_pool, hand1=["Shatter", "Lightning Bolt"])
    gnomes = _w1g5_put(game, 0, "Patchwork Gnomes")
    assert not game.activate_permanent_ability(0, "Patchwork Gnomes").supported
    game.players[0].hand = [catalog_by_name["Forest"]]
    assert game.activate_permanent_ability(0, "Patchwork Gnomes").supported
    _w1g5_resolve_stack(game)
    assert [c.name for c in game.players[0].graveyard] == ["Forest"]

    assert game.cast_from_hand(
        1, "Shatter", target_permanent_ids=[gnomes.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert game.is_on_battlefield(gnomes) and gnomes.tapped, "regenerated"
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[gnomes.permanent_id],
    ).supported
    _w1g5_resolve_stack(game)
    assert not game.is_on_battlefield(gnomes), "the shield was one use"


def test_w1g5_phantom_whelp_goes_home_at_end_of_combat_only_if_it_is_still_there(
    catalog_by_name, set_pool,
):
    """"When this creature attacks or blocks, return it to its owner's hand at
    end of combat. (Return it only if it's on the battlefield.)" An unblocked
    attack deals its 2 and comes home; a Whelp that died in the block stays in
    the graveyard."""
    game = _w1g5_table(catalog_by_name, set_pool)
    whelp = _w1g5_put(game, 0, "Phantom Whelp")
    _w1g5_to_declare_attackers(game)
    assert game.declare_attackers(0, [_w1g5_slot(game, 0, whelp)])[0]
    _w1g5_resolve_stack(game)
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0]
    _w1g5_finish_combat(game)
    assert game.players[1].life == 18 and not game.is_on_battlefield(whelp)
    assert [c.name for c in game.players[0].hand] == ["Phantom Whelp"]

    game = _w1g5_table(catalog_by_name, set_pool)
    whelp = _w1g5_put(game, 1, "Phantom Whelp")
    bears = _w1g5_put(game, 0, "Grizzly Bears")
    _w1g5_to_declare_attackers(game)
    slot = _w1g5_slot(game, 0, bears)
    assert game.declare_attackers(0, [slot])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {_w1g5_slot(game, 1, whelp): slot})[0]
    _w1g5_resolve_stack(game)
    _w1g5_finish_combat(game)
    assert [c.name for c in game.players[1].graveyard] == ["Phantom Whelp"]
    assert game.players[1].hand == []


def test_w1g5_pianna_pumps_the_attackers_and_only_them(catalog_by_name, set_pool):
    game = _w1g5_table(catalog_by_name, set_pool)
    pianna = _w1g5_put(game, 0, "Pianna, Nomad Captain")
    bears = _w1g5_put(game, 0, "Grizzly Bears")
    home = _w1g5_put(game, 0, "Hill Giant")
    _w1g5_to_declare_attackers(game)
    assert game.declare_attackers(
        0, [_w1g5_slot(game, 0, pianna), _w1g5_slot(game, 0, bears)],
    )[0]
    _w1g5_resolve_stack(game)
    assert (pianna.effective_power, bears.effective_power, home.effective_power) == (3, 3, 3)
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0]
    _w1g5_finish_combat(game)
    assert game.players[1].life == 14
    game.resolve_cleanup_step(0)
    assert bears.effective_power == 2


@_w1g5_pytest.mark.parametrize("name, spell, source", [
    ("Pilgrim of Justice", "Lightning Bolt", "Hill Giant"),
    ("Pilgrim of Virtue", "Terror", "Scathe Zombies"),
])
def test_w1g5_a_pilgrim_is_sacrificed_to_stop_one_source_of_its_colour_whoever_it_hits(
    catalog_by_name, set_pool, name, spell, source,
):
    """"Protection from red. {W}, Sacrifice this creature: The next time a red
    source of your choice would deal damage this turn, prevent that damage."
    No recipient is printed (CR 615.8 names only the source), so the chosen
    source's next damage is prevented whether it was headed for the Pilgrim's
    controller, one of their creatures or the opponent — and only the next."""
    for recipient in ("me", "mine", "theirs"):
        game = _w1g5_table(catalog_by_name, set_pool, hand1=[spell])
        pilgrim = _w1g5_put(game, 0, name)
        wurm = _w1g5_put(game, 0, "Craw Wurm")
        threat = _w1g5_put(game, 1, source)
        assert not game.cast_from_hand(
            1, spell, target_permanent_ids=[pilgrim.permanent_id],
        ).supported, "protection from its colour"

        armed = game.activate_permanent_ability(
            0, name, target_permanent_ids=[threat.permanent_id],
        )
        _w1g5_resolve_stack(game)
        assert armed.supported and not game.is_on_battlefield(pilgrim)
        hit = {"me": game.players[0], "mine": wurm, "theirs": game.players[1]}[recipient]
        assert _w1g5_dealt(game, hit, 3, threat) == 0, recipient
        assert _w1g5_dealt(game, hit, 3, threat) == 3, "the next time, once"


def test_w1g5_rabid_elephant_grows_for_each_blocker(catalog_by_name, set_pool):
    game = _w1g5_table(catalog_by_name, set_pool)
    elephant = _w1g5_put(game, 0, "Rabid Elephant")
    bears = _w1g5_put(game, 1, "Grizzly Bears")
    ogre = _w1g5_put(game, 1, "Gray Ogre")
    _w1g5_to_declare_attackers(game)
    slot = _w1g5_slot(game, 0, elephant)
    assert game.declare_attackers(0, [slot])[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {
        _w1g5_slot(game, 1, bears): slot, _w1g5_slot(game, 1, ogre): slot,
    })[0]
    _w1g5_resolve_stack(game)
    assert (elephant.effective_power, elephant.effective_toughness) == (7, 8)

    game.advance_combat_phase()
    assert game.resolve_all_combat_damage(0, attacker_damage={slot: {
        _w1g5_slot(game, 1, bears): 3, _w1g5_slot(game, 1, ogre): 4,
    }})[0]
    assert sorted(c.name for c in game.players[1].graveyard) == ["Gray Ogre", "Grizzly Bears"]
    assert game.is_on_battlefield(elephant) and elephant.damage_marked == 4


def test_w1g5_resilient_wanderer_discards_and_is_asked_its_colour_as_it_resolves(
    catalog_by_name, set_pool,
):
    """"First strike. Discard a card: This creature gains protection from the
    color of your choice until end of turn." With an empty hand the activation
    is refused — which is what the pool-wide colour-choice guard was reporting
    as a failure of the card. With a card, the named one is discarded and the
    colour is asked at resolution (CR 608.2d), after any response."""
    game = _w1g5_table(
        catalog_by_name, set_pool, hand1=["Terror", "Lightning Bolt"],
        interactive={0},
    )
    wanderer = _w1g5_put(game, 0, "Resilient Wanderer")
    assert game._has_keyword(wanderer, "first strike")
    assert not game.activate_permanent_ability(0, "Resilient Wanderer").supported

    game.players[0].hand = [catalog_by_name["Forest"], catalog_by_name["Island"]]
    assert game.queue_permanent_ability(
        0, "Resilient Wanderer", cost_hand_index=1,
    ).supported
    assert [c.name for c in game.players[0].graveyard] == ["Island"]
    game.resolve_top_of_stack()
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("color_choice", 0)]
    assert game._protection_qualities(wanderer) == set()
    assert game.resolve_pending_choice("color_choice", 0, mana_color="B")
    _w1g5_resolve_stack(game)

    assert game._protection_qualities(wanderer) == {("color", "B")}
    assert not game.cast_from_hand(
        1, "Terror", target_permanent_ids=[wanderer.permanent_id],
    ).supported
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_permanent_ids=[wanderer.permanent_id],
    ).supported

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.
# (moved whole to test_ody_creatures_later_groups.py when this file reached its size cap)

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.
# (moved whole to test_ody_creatures_later_groups.py when this file reached its size cap)

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.
#
# They are in `test_ody_creatures_w1g8.py`, a file of the group's own: the
# five creatures it implemented and the twenty-three it drove came to some
# 900 lines, and this file had 415 lines of room with four sections still to
# land. Split along a section boundary, the axis `tests/sets/README.md` names
# once the printed type has run out, so each section stays whole.

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
    return game  # _w1g9_duel (creatures)


def _w1g9_on(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


def _w1g9_names(cards):
    return [card.name for card in cards]


# --- Aboshan, Cephalid Emperor ---------------------------------------------

def test_aboshan_taps_every_creature_without_flying(set_pool):
    game = _w1g9_duel(
        set_pool, bf0=["Aboshan, Cephalid Emperor", "Cephalid Retainer"],
        bf1=["Air Elemental", "Gray Ogre", "Mox Pearl"],
    )
    assert game.activate_permanent_ability(
        0, "Aboshan, Cephalid Emperor", ability_index=1
    ).supported
    _w1g9_resolve_stack(game)
    tapped = {p.card.name for p in game.all_permanents() if p.tapped}
    assert tapped == {
        "Aboshan, Cephalid Emperor", "Cephalid Retainer", "Gray Ogre",
    }


def test_aboshan_taps_the_octopus_its_controller_names_to_tap_a_permanent(set_pool):
    """"Tap an untapped Octopus you control: Tap target permanent." The payer
    is the activator's choice (CR 601.2h) - another Octopus leaves Aboshan
    untapped - and a creature that is no Octopus pays nothing."""
    game = _w1g9_duel(
        set_pool, bf0=["Aboshan, Cephalid Emperor", "Cephalid Retainer"],
        bf1=["Gray Ogre", "Mox Pearl"],
    )
    aboshan = _w1g9_on(game, 0, "Aboshan, Cephalid Emperor")
    retainer = _w1g9_on(game, 0, "Cephalid Retainer")
    mox, ogre = _w1g9_on(game, 1, "Mox Pearl"), _w1g9_on(game, 1, "Gray Ogre")
    assert game.activate_permanent_ability(
        0, "Aboshan, Cephalid Emperor", ability_index=0,
        target_permanent_ids=[mox.permanent_id],
        cost_permanent_ids=[retainer.permanent_id],
    ).supported
    _w1g9_resolve_stack(game)
    assert (aboshan.tapped, retainer.tapped, mox.tapped) == (False, True, True)

    refused = game.activate_permanent_ability(
        0, "Aboshan, Cephalid Emperor", ability_index=0,
        target_permanent_ids=[ogre.permanent_id],
        cost_permanent_ids=[ogre.permanent_id],
    )
    assert not refused.supported
    assert (aboshan.tapped, ogre.tapped) == (False, False)

    aboshan.tapped = True
    assert not game.activate_permanent_ability(
        0, "Aboshan, Cephalid Emperor", ability_index=0,
        target_permanent_ids=[ogre.permanent_id],
    ).supported
    assert not ogre.tapped


def _w1g9_to_declare_attackers(game, active):
    """Step the real turn structure to the declare-attackers step."""
    game.active_player_index = active
    for _ in range(4):
        game.advance_combat_phase()
        if game.current_step == "declare_attackers":
            return
    raise AssertionError(f"never reached declare attackers: {game.current_step}")


def _w1g9_squirrel_token(game, set_pool, seat):
    """A real token, made by the set's own token maker."""
    game.players[seat].hand.append(set_pool("ODY")["Chatter of the Squirrel"])
    assert game.cast_from_hand(seat, "Chatter of the Squirrel").supported
    _w1g9_resolve_stack(game)
    return next(
        p for p in game.controlled_by(seat) if p.metadata.get("is_token")
    )


# --- Dogged Hunter: "{T}: Destroy target creature token." ------------------

def test_dogged_hunter_destroys_a_creature_token(set_pool):
    game = _w1g9_duel(set_pool, bf0=["Dogged Hunter"], bf1=["Grizzly Bears"])
    token = _w1g9_squirrel_token(game, set_pool, 1)
    spec = game.activation_target_spec(0, 0)
    assert [t["name"] for t in spec["valid_targets"]] == ["Squirrel Token"]
    assert game.queue_permanent_ability(
        0, "Dogged Hunter", target_permanent_ids=[token.permanent_id]
    ).supported
    _w1g9_resolve_stack(game)
    assert _w1g9_names(p.card for p in game.controlled_by(1)) == ["Grizzly Bears"]


def test_dogged_hunter_cannot_be_aimed_at_a_creature_that_is_no_token(set_pool):
    """"Token" is CR 111.1's fact about the object, held by the picker and by
    the activation gate: a card named for it is refused with nothing paid."""
    game = _w1g9_duel(set_pool, bf0=["Dogged Hunter"], bf1=["Grizzly Bears"])
    hunter = _w1g9_on(game, 0, "Dogged Hunter")
    bears = _w1g9_on(game, 1, "Grizzly Bears")
    assert game.activation_target_spec(0, 0)["valid_targets"] == []
    for ids in ([bears.permanent_id], None):
        refused = game.queue_permanent_ability(
            0, "Dogged Hunter", target_permanent_ids=ids
        )
        assert not refused.supported
        assert not hunter.tapped and not game.stack
    assert bears in game.all_permanents()


@_w1g9_pytest.mark.parametrize("line, supported", [
    ("{T}: Destroy target creature token.", True),
    ("{T}: Destroy target artifact creature token.", True),
    ("{T}: Destroy target creature token card.", False),
])
def test_token_reads_after_a_card_type_and_only_there(line, supported):
    card = _w1g9_mk_card("Token Hound", "{W}", "Creature - Hound", line)
    program = _w1g9_compile(card)
    assert program.supported is supported
    if supported:
        assert program.instructions[0].payload["token_only"] is True


# --- Lieutenant Kirtar -----------------------------------------------------

def test_lieutenant_kirtar_is_sacrificed_to_exile_an_attacker(set_pool):
    """"{1}{W}, Sacrifice Lieutenant Kirtar: Exile target attacking creature."
    The cost names the card (CR 201.5) where every other card prints "this
    creature" - and it is charged: Kirtar is in the graveyard before the
    ability resolves."""
    game = _w1g9_duel(
        set_pool, bf0=["Lieutenant Kirtar"], bf1=["Gray Ogre", "Grizzly Bears"],
        costs=True,
    )
    kirtar = _w1g9_on(game, 0, "Lieutenant Kirtar")
    ogre, bears = _w1g9_on(game, 1, "Gray Ogre"), _w1g9_on(game, 1, "Grizzly Bears")
    (ability,) = _w1g9_compile(kirtar.card).activated_abilities
    assert ability.cost.sacrifice_self

    _w1g9_to_declare_attackers(game, 1)
    assert game.declare_attackers(1, [0], defending_player_index=0)[0]
    game.players[0].mana_pool.update({"W": 2})
    refused = game.queue_permanent_ability(
        0, "Lieutenant Kirtar", target_permanent_ids=[bears.permanent_id]
    )
    assert not refused.supported, "the Bears are not attacking"
    assert kirtar in game.all_permanents()
    assert game.players[0].mana_pool["W"] == 2

    assert game.queue_permanent_ability(
        0, "Lieutenant Kirtar", target_permanent_ids=[ogre.permanent_id]
    ).supported
    assert _w1g9_names(game.players[0].graveyard) == ["Lieutenant Kirtar"]
    assert ogre in game.all_permanents(), "the ability is still on the stack"
    _w1g9_resolve_stack(game)
    assert _w1g9_names(game.players[1].exile) == ["Gray Ogre"]


def test_lieutenant_kirtar_has_nothing_to_exile_outside_combat(set_pool):
    game = _w1g9_duel(
        set_pool, bf0=["Lieutenant Kirtar"], bf1=["Gray Ogre"], costs=True,
    )
    game.players[0].mana_pool.update({"W": 2})
    ogre = _w1g9_on(game, 1, "Gray Ogre")
    assert not game.queue_permanent_ability(
        0, "Lieutenant Kirtar", target_permanent_ids=[ogre.permanent_id]
    ).supported
    assert _w1g9_on(game, 0, "Lieutenant Kirtar")
    assert game.players[0].mana_pool["W"] == 2


@_w1g9_pytest.mark.parametrize("cost, field", [
    ("Sacrifice Old Sergeant", "sacrifice_self"),
    ("Exile Old Sergeant", "exile_self"),
    ("Return Old Sergeant to its owner's hand", "return_self_to_hand"),
])
def test_a_cost_naming_its_own_card_is_charged(cost, field):
    """An invented legend, not a name: each of the three self-costs is read
    off the card's name exactly as off "this creature"."""
    card = _w1g9_mk_card(
        "Old Sergeant", "{W}", "Legendary Creature - Human Soldier",
        f"{cost}: Draw a card.",
    )
    (ability,) = _w1g9_compile(card).activated_abilities
    assert ability.supported and getattr(ability.cost, field) is True


# --- Squirrel Mob: "+1/+1 for each other Squirrel on the battlefield" -------

def test_squirrel_mob_counts_every_other_squirrel_and_not_itself(set_pool):
    """It was 3/3 alone: the count was handed nothing to leave out, so "other"
    was read and dropped. An opponent's Squirrels count, a second Mob counts
    the first, and a Bear counts for nothing."""
    game = _w1g9_duel(set_pool, bf0=["Squirrel Mob"])
    first = _w1g9_on(game, 0, "Squirrel Mob")
    game._recompute_continuous_effects()
    assert (first.effective_power, first.effective_toughness) == (2, 2)

    second = _w1g9_Permanent(card=set_pool("ODY")["Squirrel Mob"])
    game._put_permanent_onto_battlefield(1, second, None)
    _w1g9_squirrel_token(game, set_pool, 1)
    game._put_permanent_onto_battlefield(
        0, _w1g9_Permanent(card=set_pool("LEA")["Grizzly Bears"]), None
    )
    game._recompute_continuous_effects()
    assert [(m.effective_power, m.effective_toughness) for m in (first, second)] == [
        (4, 4), (4, 4),
    ]


# --- Graceful Antelope: a land type set until the Antelope leaves ----------

def _w1g9_land_types(permanent):
    return [
        word for word in ("plains", "island", "swamp", "mountain", "forest")
        if permanent.has_type(word)
    ]


def _w1g9_antelope_connects(game, land, *, accept=True, before_resolving=None):
    """Attack with the Antelope (seat 0), unblocked; name *land* for the
    trigger and answer its "you may". *before_resolving* runs with the
    trigger on the stack and its target chosen."""
    _w1g9_to_declare_attackers(game, 0)
    assert game.declare_attackers(0, [0], defending_player_index=1)[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {})[0]
    for _ in range(6):
        if game.pending_choices or game.stack:
            break
        game.advance_combat_phase()
    assert game.players[1].life == 19
    prompt = game.pending_choice_of("trigger_target")
    assert prompt is not None and prompt.player_index == 0
    assert game.confirm_trigger_target(0, permanent_id=land.permanent_id)
    if before_resolving is not None:
        before_resolving()
    game.resolve_top_of_stack(pause_for_choices=True)
    if game.pending_choices:
        assert game.confirm_optional_pay(0, accept=accept)


def _w1g9_antelope_table(set_pool):
    game = _w1g9_duel(
        set_pool, bf0=["Graceful Antelope", "Mountain"],
        bf1=["Forest"],
    )
    game.interactive_seats = {0, 1}
    return game, _w1g9_on(game, 0, "Graceful Antelope"), _w1g9_on(game, 1, "Forest")


def test_graceful_antelope_makes_a_land_a_plains_until_it_leaves(set_pool):
    """"Whenever this creature deals combat damage to a player, you may have
    target land become a Plains until this creature leaves the battlefield."
    CR 305.7: the Forest is a Plains and nothing else, taps for {W}, and is a
    Forest again the moment the Antelope is gone - here, to a hand."""
    game, antelope, forest = _w1g9_antelope_table(set_pool)
    _w1g9_antelope_connects(game, forest)
    assert _w1g9_land_types(forest) == ["plains"]
    assert game.tap_land_for_mana(1, "Forest", permanent_id=forest.permanent_id)
    assert game.players[1].mana_pool["W"] == 1 and game.players[1].mana_pool["G"] == 0

    game.remove_from_battlefield(antelope)
    game.put_card_into_hand(game.players[0], antelope.card)
    assert _w1g9_land_types(forest) == ["forest"]


def test_graceful_antelope_asks_and_takes_no_for_an_answer(set_pool):
    game, _antelope, forest = _w1g9_antelope_table(set_pool)
    _w1g9_antelope_connects(game, forest, accept=False)
    assert _w1g9_land_types(forest) == ["forest"]


def test_graceful_antelope_changes_nothing_once_it_has_left(set_pool):
    """CR 611.2b: the duration ended before the effect would begin, so the
    effect does nothing - a land changed then would be a Plains for good,
    with nothing left to end it."""
    game, antelope, forest = _w1g9_antelope_table(set_pool)

    def kill():
        game.remove_from_battlefield(antelope)
        game._permanent_to_graveyard(game.players[0], antelope)

    _w1g9_antelope_connects(game, forest, before_resolving=kill)
    _w1g9_resolve_stack(game)
    assert _w1g9_land_types(forest) == ["forest"]


def test_graceful_antelope_keeps_its_plains_while_only_phased_out(set_pool):
    """CR 702.26d: phasing out is not leaving the battlefield."""
    game, antelope, forest = _w1g9_antelope_table(set_pool)
    _w1g9_antelope_connects(game, forest)
    antelope.metadata["phased_out"] = True
    game.remove_from_battlefield(antelope, zone_change=False)
    assert _w1g9_land_types(forest) == ["plains"]


@_w1g9_pytest.mark.parametrize("leaves", ["hand", "exile", "library", "graveyard"])
def test_a_land_type_set_until_its_source_leaves_ends_whichever_way_it_goes(
    set_pool, leaves
):
    """The same window on the card that has printed it since Alpha. Gaea's
    Liege reverted its lands from a name-keyed hook on the graveyard path
    alone: bounced, exiled or tucked, it left them Forests for the rest of
    the game."""
    game = _w1g9_duel(set_pool, bf0=["Gaea's Liege", "Forest"], bf1=["Plains"])
    liege, plains = _w1g9_on(game, 0, "Gaea's Liege"), _w1g9_on(game, 1, "Plains")
    assert game.activate_permanent_ability(
        0, "Gaea's Liege", target_permanent_ids=[plains.permanent_id]
    ).supported
    _w1g9_resolve_stack(game)
    assert _w1g9_land_types(plains) == ["forest"]

    owner = game.players[0]
    game.remove_from_battlefield(liege)
    if leaves == "hand":
        game.put_card_into_hand(owner, liege.card)
    elif leaves == "exile":
        owner.exile.append(liege.card)
    elif leaves == "library":
        game.put_card_into_library(owner, liege.card, position="top")
    else:
        game._permanent_to_graveyard(owner, liege)
    assert _w1g9_land_types(plains) == ["plains"]


def test_a_land_type_with_no_printed_window_outlives_its_source(set_pool):
    """The other half of the mark on the record: a change that prints no
    duration is keyed on its source too, and lasts indefinitely (CR 611.2a)."""
    shaper = _w1g9_mk_card(
        "Terraformer", "{G}", "Creature - Druid",
        "{T}: Target land becomes a Forest.",
    )
    assert _w1g9_compile(shaper).supported
    game = _w1g9_duel(set_pool, bf1=["Plains"])
    permanent = _w1g9_Permanent(card=shaper)
    game._put_permanent_onto_battlefield(0, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    plains = _w1g9_on(game, 1, "Plains")
    assert game.activate_permanent_ability(
        0, "Terraformer", target_permanent_ids=[plains.permanent_id]
    ).supported
    _w1g9_resolve_stack(game)
    game.remove_from_battlefield(permanent)
    game._permanent_to_graveyard(game.players[0], permanent)
    assert _w1g9_land_types(plains) == ["forest"]


# --- The cards that compiled on arrival, each given a game ------------------

def _w1g9_pt(permanent):
    return permanent.effective_power, permanent.effective_toughness


def test_aven_fisher_offers_its_controller_a_card_when_it_dies(set_pool):
    game = _w1g9_duel(set_pool, hand0=["Lightning Bolt"], bf1=["Aven Fisher"])
    game.interactive_seats = {0, 1}
    fisher = _w1g9_on(game, 1, "Aven Fisher")
    assert game.queue_from_hand(
        0, "Lightning Bolt", target_permanent_ids=[fisher.permanent_id]
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    game.check_state_based_actions()
    assert _w1g9_names(i.card for i in game.stack) == ["Aven Fisher"]
    game.resolve_top_of_stack(pause_for_choices=True)
    offer = game.pending_choices[0]
    assert (offer.kind, offer.player_index) == ("optional_pay", 1)
    assert game.confirm_optional_pay(1, accept=True)
    assert len(game.players[1].hand) == 1


def test_cephalid_retainer_taps_only_a_creature_without_flying(set_pool):
    """The picker leaves the flyer out, a flyer named anyway is refused with
    nothing paid, and an Ogre given flying in response is not tapped."""
    game = _w1g9_duel(
        set_pool, hand1=["Jump"], bf0=["Cephalid Retainer"],
        bf1=["Air Elemental", "Gray Ogre"], costs=True,
    )
    game.players[0].mana_pool.update({"U": 4})
    air, ogre = _w1g9_on(game, 1, "Air Elemental"), _w1g9_on(game, 1, "Gray Ogre")
    offered = {t["name"] for t in game.activation_target_spec(0, 0)["valid_targets"]}
    assert offered == {"Cephalid Retainer", "Gray Ogre"}
    assert not game.queue_permanent_ability(
        0, "Cephalid Retainer", target_permanent_ids=[air.permanent_id]
    ).supported
    assert game.players[0].mana_pool["U"] == 4

    game.players[1].mana_pool.update({"U": 1})
    assert game.queue_permanent_ability(
        0, "Cephalid Retainer", target_permanent_ids=[ogre.permanent_id]
    ).supported
    assert game.queue_from_hand(
        1, "Jump", target_permanent_ids=[ogre.permanent_id]
    ).supported
    _w1g9_resolve_stack(game)
    assert not ogre.tapped, "it has flying as the ability resolves (CR 608.2b)"


def test_the_nantuko_druids_pump_and_make_mana(set_pool):
    game = _w1g9_duel(
        set_pool, costs=True,
        bf0=["Nantuko Disciple", "Nantuko Elder", "Nantuko Mentor", "Grizzly Bears"],
    )
    game.players[0].mana_pool.update({"G": 2, "C": 2})
    bears = _w1g9_on(game, 0, "Grizzly Bears")
    assert game.activate_permanent_ability(
        0, "Nantuko Disciple", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g9_resolve_stack(game)
    assert _w1g9_pt(bears) == (4, 4)
    # "+X/+X, where X is that creature's power" - read as the ability
    # resolves, off the 4 the Disciple just made it.
    assert game.activate_permanent_ability(
        0, "Nantuko Mentor", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g9_resolve_stack(game)
    assert _w1g9_pt(bears) == (8, 8)
    assert sum(game.players[0].mana_pool.values()) == 0
    # "{T}: Add {C}{G}." A mana ability: no stack object.
    assert game.activate_permanent_ability(0, "Nantuko Elder").supported
    assert not game.stack
    pool = game.players[0].mana_pool
    assert (pool["C"], pool["G"]) == (1, 1)


def test_puppeteer_taps_an_untapped_creature_and_untaps_a_tapped_one(set_pool):
    """"You may tap or untap target creature": decided as it resolves (the
    ruling of 2004-10-04), and the engine reads which off the creature."""
    game = _w1g9_duel(set_pool, bf0=["Puppeteer"], bf1=["Gray Ogre"])
    puppeteer, ogre = _w1g9_on(game, 0, "Puppeteer"), _w1g9_on(game, 1, "Gray Ogre")
    for expected in (True, False):
        puppeteer.tapped = False
        assert game.activate_permanent_ability(
            0, "Puppeteer", target_permanent_ids=[ogre.permanent_id]
        ).supported
        _w1g9_resolve_stack(game)
        game.auto_resolve_pending_choices()
        assert ogre.tapped is expected


def test_seton_taps_a_druid_for_green_mana(set_pool):
    """"Tap an untapped Druid you control: Add {G}." The cost taps *another*
    permanent, so the Druid is its controller's to name, a creature that is no
    Druid pays nothing, and a Druid that arrived this turn can pay (CR 302.6
    is about the {T} symbol)."""
    game = _w1g9_duel(
        set_pool,
        bf0=["Seton, Krosan Protector", "Nantuko Elder", "Grizzly Bears"],
    )
    seton = _w1g9_on(game, 0, "Seton, Krosan Protector")
    elder, bears = _w1g9_on(game, 0, "Nantuko Elder"), _w1g9_on(game, 0, "Grizzly Bears")
    elder.metadata["summoning_sickness_turn"] = game.turn
    assert game._is_summoning_sick(elder)
    assert game.activate_permanent_ability(
        0, "Seton, Krosan Protector", cost_permanent_ids=[elder.permanent_id]
    ).supported
    assert (seton.tapped, elder.tapped) == (False, True) and not game.stack
    assert game.players[0].mana_pool["G"] == 1
    assert not game.activate_permanent_ability(
        0, "Seton, Krosan Protector", cost_permanent_ids=[bears.permanent_id]
    ).supported
    assert not bears.tapped
    # Seton is a Druid itself: the last one left.
    assert game.activate_permanent_ability(0, "Seton, Krosan Protector").supported
    assert seton.tapped and game.players[0].mana_pool["G"] == 2
    assert not game.activate_permanent_ability(0, "Seton, Krosan Protector").supported


def test_blessed_orator_and_the_two_firebreathers(set_pool):
    game = _w1g9_duel(
        set_pool, costs=True,
        bf0=["Blessed Orator", "Aven Flock", "Whispering Shade"], bf1=["Grizzly Bears"],
    )
    game.players[0].mana_pool.update({"W": 2, "B": 1})
    orator = _w1g9_on(game, 0, "Blessed Orator")
    flock, shade = _w1g9_on(game, 0, "Aven Flock"), _w1g9_on(game, 0, "Whispering Shade")
    game._recompute_continuous_effects()
    # "Other creatures you control get +0/+1": not itself, not theirs.
    assert _w1g9_pt(orator) == (1, 4) and _w1g9_pt(flock) == (2, 4)
    assert _w1g9_pt(_w1g9_on(game, 1, "Grizzly Bears")) == (2, 2)
    for name in ("Aven Flock", "Aven Flock", "Whispering Shade"):
        assert game.activate_permanent_ability(0, name).supported
    _w1g9_resolve_stack(game)
    assert _w1g9_pt(flock) == (2, 6) and _w1g9_pt(shade) == (2, 3)
    assert not game.activate_permanent_ability(0, "Aven Flock").supported
    game.resolve_cleanup_step(0)
    game._recompute_continuous_effects()
    assert _w1g9_pt(flock) == (2, 4) and _w1g9_pt(shade) == (1, 2)

# ==== end W1G9 ======================================================
