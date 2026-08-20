"""Equipment (CR 301.5), the equip keyword (CR 702.6) and the attach keyword
action (CR 701.3), with their state-based action (CR 704.5n).

Driven through the two Equipment M21 ships — Short Sword and Malefic Scythe —
plus hand-built fixtures for the shapes no printed card in the pool exercises
(a coloured Equipment against protection, an Equipment that is itself a
creature, CR 702.6c's "Equip [quality]"). The engine's seam is
``engine/equipment.py``; the equip keyword reaches it as an ordinary activated
ability, which is why most of these tests drive ``activate_permanent_ability``
rather than calling the attach function directly.
"""

from __future__ import annotations

import dataclasses

import pytest

from engine import Game, PlayerState
from engine.ai_policy import choose_activation_action
from engine.equipment import (
    EQUIP_RULES_TEXT,
    attach_equipment,
    equip_refusal,
    equipped_creature,
    expand_equip_line,
    expand_equip_lines,
    is_equipment,
    unattach_illegal_equipment,
)
from engine.models import CardDefinition, Permanent
from engine.named_counters import counters_on
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec

from tests.helpers import _game, _mk_card, _mk_creature_card, _nosick, client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SHORT_SWORD_EQUIP = (
    "{1}: Attach this permanent to target creature you control. "
    "Activate only as a sorcery."
)


def _sword(pool) -> Permanent:
    return Permanent(card=pool["Short Sword"])


def _scythe(pool) -> Permanent:
    return Permanent(card=pool["Malefic Scythe"])


def _creature(name: str, power: int = 2, toughness: int = 2, colors=()) -> Permanent:
    card = _mk_creature_card(name, power, toughness)
    if colors:
        card = dataclasses.replace(card, colors=tuple(colors), color_identity=tuple(colors))
    return _nosick(Permanent(card=card))


def _equipment(name: str, text: str, colors=(), type_line: str = "Artifact — Equipment") -> Permanent:
    return Permanent(card=_mk_card(name, type_line, text, colors=tuple(colors)))


def _main_phase(p1: PlayerState, p2: PlayerState, active: int = 0) -> Game:
    """A game sitting in *active*'s precombat main phase with an empty stack —
    the only window a sorcery-speed ability may be activated in (CR 307.1)."""
    game = _game(p1, p2)
    game.active_player_index = active
    game.current_turn_phase = "precombat_main"
    return game


def _equip(game: Game, seat: int, equipment: Permanent, creature: Permanent):
    """Activate *equipment*'s equip ability at *creature* and let it resolve."""
    owner = game.controller_index_of(creature)
    return game.activate_permanent_ability(
        seat,
        equipment.card.name,
        permanent_index=game.battlefield_index_of(equipment),
        target_player_index=owner,
        target_permanent_index=game.battlefield_index_of(creature),
    )


# ---------------------------------------------------------------------------
# CR 702.6a — "Equip [cost]" means "[Cost]: Attach this permanent to target
# creature you control. Activate only as a sorcery."
# ---------------------------------------------------------------------------


@pytest.mark.cr("702.6a")
def test_702_6a_equip_line_expands_to_its_rules_text():
    """The keyword is defined as a rewrite, and the engine performs exactly that
    rewrite: cost first, the attach sentence, the sorcery-speed clause."""
    printed = "Equip {1} ({1}: Attach to target creature you control. Equip only as a sorcery.)"
    assert expand_equip_line(printed) == SHORT_SWORD_EQUIP
    assert expand_equip_line("Equip {2}{W}") == EQUIP_RULES_TEXT.format(cost="{2}{W}", noun="creature")
    # Not an equip line: the Equipment's effect line, and a creature's keywords.
    assert expand_equip_line("Equipped creature gets +1/+1.") is None
    assert expand_equip_line("Flying, vigilance") is None
    # Whole-text form leaves every other line where it was.
    text = "Equipped creature gets +1/+1.\nEquip {1}"
    assert expand_equip_lines(text) == "Equipped creature gets +1/+1.\n" + SHORT_SWORD_EQUIP


@pytest.mark.cr("702.6a", "301.5b")
def test_702_6a_short_sword_compiles_to_one_equip_activated_ability(set_pool):
    """Short Sword's program carries the equip as an activated ability costing
    {1} whose instruction attaches the source to one chosen creature of the
    activator's — and nothing else that would attach it as it enters."""
    program = compile_card_oracle(set_pool("M21")["Short Sword"])
    assert program.supported, program.reason
    assert len(program.activated_abilities) == 1
    equip = program.activated_abilities[0]
    assert equip.supported
    assert equip.source_line == SHORT_SWORD_EQUIP
    assert equip.cost.mana["generic"] == 1 and not equip.cost.requires_tap
    assert equip.instruction.kind == "attach_source_to_target"
    assert equip.instruction.payload["type_filter"] == "creature"
    assert equip.instruction.payload["controller"] == "you"
    # What the picker is told: one creature, the activator's own.
    spec = derive_activation_spec(equip)
    assert spec["kind"] == "creature"
    assert spec.get("own_only") is True


@pytest.mark.cr("702.6a", "301.5a", "613.4")
def test_702_6a_activating_equip_attaches_and_the_equipped_creature_gets_the_bonus(set_pool):
    """Short Sword onto a 2/2: the creature is the "equipped creature" and its
    +1/+1 is derived from the Equipment's text through layer 7c."""
    sword, bear = _sword(set_pool("M21")), _creature("Bear")
    game = _main_phase(PlayerState(name="P1", battlefield=[sword, bear]), PlayerState(name="P2"))

    result = _equip(game, 0, sword, bear)

    assert result.supported, result.details
    assert equipped_creature(sword) is bear
    assert (bear.effective_power, bear.effective_toughness) == (3, 3)
    assert is_equipment(sword)


@pytest.mark.cr("702.6a", "602.2b")
def test_702_6a_equip_uses_the_stack_and_attaches_on_resolution(set_pool):
    """Equip is an activated ability, not a special action: it goes on the
    stack, and the Equipment moves only when it resolves."""
    sword, bear = _sword(set_pool("M21")), _creature("Bear")
    game = _main_phase(PlayerState(name="P1", battlefield=[sword, bear]), PlayerState(name="P2"))

    queued = game.queue_permanent_ability(
        0, "Short Sword", permanent_index=0, target_player_index=0, target_permanent_index=1
    )

    assert queued.supported and queued.details == "queued"
    assert len(game.stack) == 1 and game.stack[0].ability_instruction.kind == "attach_source_to_target"
    assert equipped_creature(sword) is None
    assert bear.effective_power == 2
    game.resolve_top_of_stack()
    assert equipped_creature(sword) is bear
    assert bear.effective_power == 3


@pytest.mark.cr("702.6a", "307.1", "602.5")
def test_702_6a_equip_is_sorcery_speed(set_pool):
    """"Activate only as a sorcery": refused outside the activator's own main
    phase, and refused in a main phase while the stack is not empty."""
    pool = set_pool("M21")
    sword, bear = _sword(pool), _creature("Bear")
    game = _main_phase(PlayerState(name="P1", battlefield=[sword, bear]), PlayerState(name="P2"))

    game.current_turn_phase = "combat"
    denied = _equip(game, 0, sword, bear)
    assert not denied.supported and "sorcery" in denied.details
    assert equipped_creature(sword) is None

    # The opponent's main phase is not the activator's.
    game.current_turn_phase = "precombat_main"
    game.active_player_index = 1
    assert not _equip(game, 0, sword, bear).supported

    # Own main phase, but something is on the stack — here a first equip
    # activation that has not resolved yet.
    game.active_player_index = 0
    game.queue_permanent_ability(
        0, "Short Sword", permanent_index=0, target_player_index=0, target_permanent_index=1
    )
    assert len(game.stack) == 1
    second = game.queue_permanent_ability(
        0, "Short Sword", permanent_index=0, target_player_index=0, target_permanent_index=1
    )
    assert not second.supported and "sorcery" in second.details
    assert len(game.stack) == 1


@pytest.mark.cr("702.6a", "602.2b", "601.2h")
def test_702_6a_equip_cost_is_paid_from_the_mana_pool(set_pool):
    """{1} is a real cost: with costs enforced an empty pool cannot activate it,
    and one mana pays for exactly one activation."""
    sword, bear = _sword(set_pool("M21")), _creature("Bear")
    game = _main_phase(PlayerState(name="P1", battlefield=[sword, bear]), PlayerState(name="P2"))
    game.enforce_mana_costs = True

    broke = _equip(game, 0, sword, bear)
    assert not broke.supported and "mana" in broke.details.lower()
    assert equipped_creature(sword) is None

    game.players[0].mana_pool["G"] = 1
    paid = _equip(game, 0, sword, bear)
    assert paid.supported, paid.details
    assert equipped_creature(sword) is bear
    assert game.players[0].mana_pool.get("G", 0) == 0


@pytest.mark.cr("702.6a", "115.1c", "601.2c")
def test_702_6a_equip_targets_only_a_creature_the_activator_controls(set_pool):
    """"Target creature you control": an opponent's creature is not a legal
    target, and the ability cannot be activated at it — no cost is paid and
    nothing moves."""
    sword, mine, theirs = _sword(set_pool("M21")), _creature("Mine"), _creature("Theirs")
    game = _main_phase(
        PlayerState(name="P1", battlefield=[sword, mine]),
        PlayerState(name="P2", battlefield=[theirs]),
    )

    refused = _equip(game, 0, sword, theirs)

    assert not refused.supported
    assert "no valid target" in refused.details
    assert equipped_creature(sword) is None
    assert game.stack == []
    # The picker the web layer is handed offers the activator's creature alone.
    spec = game.activation_target_spec(0, 0)
    assert spec["kind"] == "creature"
    assert [(t["seat"], t["index"]) for t in spec["valid_targets"]] == [(0, 1)]


@pytest.mark.cr("702.6c")
def test_702_6c_equip_quality_narrows_the_legal_targets():
    """"Equip legendary creature {3}" may target only a legendary creature the
    activator controls; the narrowing rides the same noun phrase every other
    targeted ability uses."""
    blade = _equipment("Hero's Blade", "Equipped creature gets +3/+2.\nEquip legendary creature {3}")
    program = compile_card_oracle(blade.card)
    assert program.supported, program.reason
    equip = program.activated_abilities[0]
    assert equip.source_line == EQUIP_RULES_TEXT.format(cost="{3}", noun="legendary creature")
    assert equip.instruction.payload["supertypes"] == ["legendary"]

    legend_card = dataclasses.replace(
        _mk_creature_card("Hero", 2, 2), type_line="Legendary Creature — Human",
        raw={"name": "Hero", "type_line": "Legendary Creature — Human", "power": "2", "toughness": "2"},
    )
    hero, grunt = _nosick(Permanent(card=legend_card)), _creature("Grunt")
    game = _main_phase(PlayerState(name="P1", battlefield=[blade, hero, grunt]), PlayerState(name="P2"))

    assert not _equip(game, 0, blade, grunt).supported
    assert equipped_creature(blade) is None
    assert _equip(game, 0, blade, hero).supported
    assert equipped_creature(blade) is hero
    assert (hero.effective_power, hero.effective_toughness) == (5, 4)


@pytest.mark.cr("702.6e")
def test_702_6e_equip_planeswalker_is_refused_rather_than_admitted_inert(set_pool):
    """The planeswalker variant attaches "as though that planeswalker were a
    creature", which the attach path does not model. The card is reported
    unsupported naming the line — never supported with an equip that cannot
    resolve."""
    probe = dataclasses.replace(
        set_pool("M21")["Short Sword"], name="Probe Sword",
        oracle_text="Equipped creature gets +1/+1.\nEquip planeswalker {1}",
    )
    program = compile_card_oracle(probe)
    assert not program.supported
    assert "equip ability not implemented" in program.reason
    assert "Equip planeswalker {1}" in program.reason


# ---------------------------------------------------------------------------
# CR 701.3 — Attach
# ---------------------------------------------------------------------------


@pytest.mark.cr("701.3a", "701.3c", "613.7e")
def test_701_3a_equipping_a_second_creature_moves_the_equipment(set_pool):
    """Attaching takes the Equipment from where it is: the first creature loses
    the bonus, the second gains it, and the Equipment is attached to exactly
    one of them — with a new timestamp for the new attachment."""
    sword, bear, wolf = _sword(set_pool("M21")), _creature("Bear"), _creature("Wolf")
    game = _main_phase(PlayerState(name="P1", battlefield=[sword, bear, wolf]), PlayerState(name="P2"))

    assert _equip(game, 0, sword, bear).supported
    first_stamp = sword.metadata["aura_timestamp"]
    assert _equip(game, 0, sword, wolf).supported

    assert equipped_creature(sword) is wolf
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)
    assert (wolf.effective_power, wolf.effective_toughness) == (3, 3)
    assert bear.metadata.get("attached_auras", []) == []
    assert [a for a in wolf.metadata["attached_auras"]] == [sword]
    assert sword.metadata["aura_timestamp"] > first_stamp


@pytest.mark.cr("701.3b")
def test_701_3b_attaching_to_the_creature_it_already_equips_does_nothing(set_pool):
    """Re-equipping the same creature is a legal activation that changes nothing
    — no double bonus, no new timestamp."""
    sword, bear = _sword(set_pool("M21")), _creature("Bear")
    game = _main_phase(PlayerState(name="P1", battlefield=[sword, bear]), PlayerState(name="P2"))

    assert _equip(game, 0, sword, bear).supported
    stamp = sword.metadata["aura_timestamp"]
    assert _equip(game, 0, sword, bear).supported

    assert equipped_creature(sword) is bear
    assert bear.metadata["attached_auras"] == [sword]
    assert (bear.effective_power, bear.effective_toughness) == (3, 3)
    assert sword.metadata["aura_timestamp"] == stamp


@pytest.mark.cr("701.3b", "301.5b")
def test_701_3b_an_illegal_attach_leaves_the_equipment_where_it_is(set_pool):
    """An effect attaching an Equipment to something it can't equip doesn't move
    it — asked of the attach function directly, as a spell's effect would."""
    sword, bear = _sword(set_pool("M21")), _creature("Bear")
    rock = Permanent(card=_mk_card("Rock", "Artifact", ""))
    game = _main_phase(PlayerState(name="P1", battlefield=[sword, bear, rock]), PlayerState(name="P2"))

    assert attach_equipment(game, sword, bear)
    assert not attach_equipment(game, sword, rock)
    assert equipped_creature(sword) is bear
    assert rock.metadata.get("attached_auras", []) == []


@pytest.mark.cr("701.3d", "704.5n")
def test_701_3d_an_equipment_that_leaves_the_battlefield_stops_equipping(set_pool):
    """Leaving the battlefield counts as becoming unattached: the creature it
    was on loses the bonus and no longer lists it among its attachments."""
    sword, bear = _sword(set_pool("M21")), _creature("Bear")
    shatter = _mk_card("Shatter", "Instant", "Destroy target artifact.")
    p1 = PlayerState(name="P1", battlefield=[sword, bear])
    p2 = PlayerState(name="P2", hand=[shatter])
    game = _main_phase(p1, p2)
    assert _equip(game, 0, sword, bear).supported
    assert bear.effective_power == 3

    game.cast_from_hand(1, "Shatter", target_player_index=0, target_permanent_index=0)
    game._settle()

    assert sword not in p1.battlefield
    assert any(c.name == "Short Sword" for c in p1.graveyard)
    assert bear.metadata.get("attached_auras", []) == []
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)


# ---------------------------------------------------------------------------
# CR 301.5 — what an Equipment may be attached to
# ---------------------------------------------------------------------------


@pytest.mark.cr("301.5", "301.5c")
def test_301_5_only_a_creature_may_be_equipped_and_never_the_equipment_itself(set_pool):
    """The one legality predicate every reader asks: a noncreature is refused,
    the Equipment itself is refused, a creature is admitted."""
    sword, bear = _sword(set_pool("M21")), _creature("Bear")
    rock = Permanent(card=_mk_card("Rock", "Artifact", ""))
    game = _main_phase(PlayerState(name="P1", battlefield=[sword, bear, rock]), PlayerState(name="P2"))

    assert equip_refusal(game, sword, bear) is None
    assert "not a creature" in equip_refusal(game, sword, rock)
    assert "itself" in equip_refusal(game, sword, sword)
    # And the activation path refuses the noncreature before any cost is paid.
    assert not _equip(game, 0, sword, rock).supported
    assert game.stack == []


@pytest.mark.cr("301.5c")
def test_301_5c_an_equipment_that_is_a_creature_cannot_equip():
    """An artifact creature with the Equipment subtype (and no reconfigure)
    can't equip: the ability is refused rather than attaching a creature to a
    creature."""
    golem = _equipment(
        "Living Blade", "Equipped creature gets +2/+0.\nEquip {1}",
        type_line="Artifact Creature — Equipment Golem",
    )
    golem.card = dataclasses.replace(
        golem.card, raw={**golem.card.raw, "power": "1", "toughness": "1"}
    )
    bear = _creature("Bear")
    game = _main_phase(PlayerState(name="P1", battlefield=[golem, bear]), PlayerState(name="P2"))

    assert golem.is_creature and is_equipment(golem)
    assert "is a creature" in equip_refusal(game, golem, bear)
    assert not _equip(game, 0, golem, bear).supported
    assert equipped_creature(golem) is None
    assert bear.effective_power == 2


@pytest.mark.cr("301.5d")
def test_301_5d_control_of_the_creature_and_of_the_equipment_are_separate(set_pool):
    """Stealing the equipped creature does not steal the Equipment: it stays
    attached and keeps granting its bonus to the creature's new controller, its
    own controller can't re-equip it onto a creature they no longer control,
    and the thief — not the Equipment's controller — can't activate equip."""
    sword, bear, spare = _sword(set_pool("M21")), _creature("Bear"), _creature("Spare")
    thief = Permanent(card=_mk_card("Thief", "Enchantment", ""))
    p1 = PlayerState(name="P1", battlefield=[sword, bear, spare])
    p2 = PlayerState(name="P2", battlefield=[thief])
    game = _main_phase(p1, p2)
    assert _equip(game, 0, sword, bear).supported

    game.take_control(bear, 1, source=thief)

    assert game.controller_index_of(bear) == 1
    assert game.controller_index_of(sword) == 0
    assert equipped_creature(sword) is bear
    assert (bear.effective_power, bear.effective_toughness) == (3, 3)
    # The Equipment's controller may not aim it at a creature they don't control…
    assert not _equip(game, 0, sword, bear).supported
    # …and the creature's new controller may not activate an Equipment they
    # don't control, even on their own main phase.
    game.active_player_index = 1
    with pytest.raises(ValueError):
        game.activate_permanent_ability(
            1, "Short Sword", permanent_index=0, target_player_index=1,
            target_permanent_index=game.battlefield_index_of(bear),
        )
    # Its controller can still move it to a creature they do control.
    game.active_player_index = 0
    assert _equip(game, 0, sword, spare).supported
    assert equipped_creature(sword) is spare
    assert bear.effective_power == 2


@pytest.mark.cr("301.5b")
def test_301_5b_an_equipment_enters_the_battlefield_unattached(set_pool):
    """Cast like any artifact: it resolves onto the battlefield attached to
    nothing, and the creature beside it is unchanged until equip is activated."""
    pool = set_pool("M21")
    bear = _creature("Bear")
    p1 = PlayerState(name="P1", hand=[pool["Short Sword"]], battlefield=[bear])
    game = _main_phase(p1, PlayerState(name="P2"))

    result = game.cast_from_hand(0, "Short Sword", target_player_index=1)
    game._settle()

    assert result.supported, result.details
    sword = next(p for p in p1.battlefield if p.card.name == "Short Sword")
    assert equipped_creature(sword) is None
    assert bear.effective_power == 2


# ---------------------------------------------------------------------------
# CR 704.5n — an Equipment attached to an illegal permanent becomes unattached
# and remains on the battlefield
# ---------------------------------------------------------------------------


@pytest.mark.cr("704.5n", "701.3d")
def test_704_5n_equipment_stays_when_the_equipped_creature_dies(set_pool):
    """The creature dies; the Equipment is unattached, still on the battlefield,
    and ready to be equipped again."""
    sword, bear, wolf = _sword(set_pool("M21")), _creature("Bear"), _creature("Wolf")
    p1 = PlayerState(name="P1", battlefield=[sword, bear, wolf])
    game = _main_phase(p1, PlayerState(name="P2"))
    assert _equip(game, 0, sword, bear).supported

    game.sacrifice_permanent(bear)
    game.check_state_based_actions()

    assert sword in p1.battlefield
    assert equipped_creature(sword) is None
    assert bear not in p1.battlefield
    assert _equip(game, 0, sword, wolf).supported
    assert wolf.effective_power == 3


@pytest.mark.cr("704.5n", "301.5")
def test_704_5n_equipment_on_a_permanent_that_is_no_longer_a_creature_is_unattached():
    """An attachment record pointing at a noncreature — what is left when an
    animation ends — is an illegal attachment, and the sweep undoes it without
    touching the Equipment's place on the battlefield."""
    sword = _equipment("Sword", "Equipped creature gets +1/+1.\nEquip {1}")
    rock = Permanent(card=_mk_card("Rock", "Artifact", ""))
    p1 = PlayerState(name="P1", battlefield=[sword, rock])
    game = _game(p1, PlayerState(name="P2"))
    # Written by hand: the legal attach path would refuse this, which is the
    # point — the sweep is what catches a record an effect *made* illegal.
    from engine.auras import attach_aura
    attach_aura(sword, rock)
    assert rock.metadata["attached_auras"] == [sword]

    assert unattach_illegal_equipment(game)

    assert sword in p1.battlefield
    assert equipped_creature(sword) is None
    assert rock.metadata.get("attached_auras", []) == []
    assert not unattach_illegal_equipment(game)


@pytest.mark.cr("702.16d", "704.5n")
def test_702_16d_protection_unattaches_the_equipment_and_ends_its_bonus():
    """A white Equipment on a creature that gains protection from white becomes
    unattached — and the +1/+1 goes with it. The previous sweep cleared the
    Equipment's own record and left it in the creature's list, so the creature
    kept a bonus from an Equipment it no longer wore."""
    sword = _equipment("White Sword", "Equipped creature gets +1/+1.\nEquip {1}", colors=("W",))
    knight = _creature("Knight")
    p1 = PlayerState(name="P1", battlefield=[sword, knight])
    game = _main_phase(p1, PlayerState(name="P2"))
    assert _equip(game, 0, sword, knight).supported
    assert knight.effective_power == 3

    knight.metadata["protection_from_white"] = True
    game.check_state_based_actions()

    assert sword in p1.battlefield
    assert equipped_creature(sword) is None
    assert knight.metadata.get("attached_auras", []) == []
    assert (knight.effective_power, knight.effective_toughness) == (2, 2)
    # And it can't be equipped back on while the protection lasts.
    assert not _equip(game, 0, sword, knight).supported


@pytest.mark.cr("608.2b", "702.6a")
def test_608_2b_equip_does_nothing_when_its_target_is_gone_at_resolution(set_pool):
    """The creature dies with the equip on the stack: the ability resolves with
    an illegal target, nothing is attached, and no other creature is picked
    in its place."""
    sword, bear, wolf = _sword(set_pool("M21")), _creature("Bear"), _creature("Wolf")
    p1 = PlayerState(name="P1", battlefield=[sword, bear, wolf])
    game = _main_phase(p1, PlayerState(name="P2"))
    queued = game.queue_permanent_ability(
        0, "Short Sword", permanent_index=0, target_player_index=0, target_permanent_index=1
    )
    assert queued.supported and len(game.stack) == 1

    game.sacrifice_permanent(bear)
    game.resolve_top_of_stack()

    assert equipped_creature(sword) is None
    assert wolf.effective_power == 2
    assert wolf.metadata.get("attached_auras", []) == []


@pytest.mark.cr("702.6a", "113.7a")
def test_an_equipment_destroyed_in_response_attaches_nothing(set_pool):
    """The ability exists independently of its source once activated, but with
    the Equipment in the graveyard there is nothing to move: the creature is
    unchanged and no card is "attached" from another zone."""
    sword, bear = _sword(set_pool("M21")), _creature("Bear")
    p1 = PlayerState(name="P1", battlefield=[sword, bear])
    game = _main_phase(p1, PlayerState(name="P2"))
    assert game.queue_permanent_ability(
        0, "Short Sword", permanent_index=0, target_player_index=0, target_permanent_index=1
    ).supported

    game.remove_from_battlefield(sword)
    game._permanent_to_graveyard(p1, sword)
    game.resolve_top_of_stack()

    assert bear.metadata.get("attached_auras", []) == []
    assert bear.effective_power == 2
    assert equipped_creature(sword) is None


# ---------------------------------------------------------------------------
# CR 301.5f — "equipped creature" is whatever the permanent is attached to, and
# the attached-effect templates read it as they read "enchanted creature"
# ---------------------------------------------------------------------------


@pytest.mark.cr("301.5f", "613.4", "702.9a")
def test_301_5f_equipped_creature_keyword_and_pt_grants_are_derived_like_an_auras():
    """"Equipped creature gets +2/+0 and has flying" — both halves derived from
    the Equipment's text while attached, through the layer bridge, and both
    gone the moment it moves."""
    wings = _equipment("Wings", "Equipped creature gets +2/+0 and has flying.\nEquip {2}")
    bear, wolf = _creature("Bear"), _creature("Wolf")
    game = _main_phase(PlayerState(name="P1", battlefield=[wings, bear, wolf]), PlayerState(name="P2"))
    assert compile_card_oracle(wings.card).supported

    assert _equip(game, 0, wings, bear).supported
    assert (bear.effective_power, bear.effective_toughness) == (4, 2)
    assert bear.has_keyword("flying")

    assert _equip(game, 0, wings, wolf).supported
    assert not bear.has_keyword("flying") and bear.effective_power == 2
    assert wolf.has_keyword("flying") and wolf.effective_power == 4


# ---------------------------------------------------------------------------
# Malefic Scythe — the M21 Equipment with a counter loop
# ---------------------------------------------------------------------------


@pytest.mark.cr("702.6a", "122.6", "301.5f")
def test_malefic_scythe_enters_with_a_soul_counter_and_grows_when_the_equipped_creature_dies(set_pool):
    """Enters with one soul counter; the equipped creature gets +1/+1 per
    counter; when that creature dies the Scythe is unattached (704.5n), gains a
    counter, and grants +2/+2 to the next creature it equips."""
    pool = set_pool("M21")
    bear, wolf = _creature("Bear"), _creature("Wolf")
    p1 = PlayerState(name="P1", hand=[pool["Malefic Scythe"]], battlefield=[bear, wolf])
    game = _main_phase(p1, PlayerState(name="P2"))
    assert game.cast_from_hand(0, "Malefic Scythe", target_player_index=1).supported
    game._settle()
    scythe = next(p for p in p1.battlefield if p.card.name == "Malefic Scythe")
    assert counters_on(scythe, "soul") == 1
    assert equipped_creature(scythe) is None

    assert _equip(game, 0, scythe, bear).supported
    assert (bear.effective_power, bear.effective_toughness) == (3, 3)

    game.sacrifice_permanent(bear)
    game._settle()

    assert counters_on(scythe, "soul") == 2
    assert scythe in p1.battlefield and equipped_creature(scythe) is None
    assert _equip(game, 0, scythe, wolf).supported
    assert (wolf.effective_power, wolf.effective_toughness) == (4, 4)


# ---------------------------------------------------------------------------
# The AI and the web layer, which reach equip through the same ability
# ---------------------------------------------------------------------------


@pytest.mark.cr("702.6a", "301.5d")
def test_the_ai_equips_its_biggest_creature_and_then_leaves_the_sword_alone(set_pool):
    """The policy chooses the creature itself (the handler declines a target it
    was not given) and stops once the Equipment is on the best one, rather than
    paying {1} every main phase to re-equip the same creature."""
    sword, bear, giant = _sword(set_pool("M21")), _creature("Bear", 2, 2), _creature("Giant", 4, 4)
    p1 = PlayerState(name="P1", battlefield=[sword, bear, giant])
    game = _main_phase(p1, PlayerState(name="P2"))

    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Short Sword"
    assert action.target_player_index == 0
    assert p1.battlefield[action.target_permanent_index] is giant

    result = game.activate_permanent_ability(
        0, action.permanent_name, permanent_index=action.permanent_index,
        target_player_index=action.target_player_index,
        target_permanent_index=action.target_permanent_index,
    )
    assert result.supported and equipped_creature(sword) is giant
    assert choose_activation_action(game, 0) is None


@pytest.mark.cr("702.6a", "301.5a")
def test_equip_through_the_web_api_offers_own_creatures_and_renders_the_attachment():
    """End to end over the API: the permanent carries a creature picker over the
    activator's own creatures, the activate action takes the chosen id, and the
    state afterwards reports the Equipment attached to that creature."""
    created = client.post(
        "/api/sessions",
        json={"mode": "human_vs_human", "host_name": "P1", "host_colors": 2, "enable_pregame": False},
    ).json()
    sid = created["session_id"]
    client.post(f"/api/sessions/{sid}/join", json={"guest_name": "P2"})
    raw = {
        "turn_number": 3, "current_turn": 0,
        "current_turn_phase": "precombat_main", "current_step": "precombat_main",
        "priority_player": 0, "priority_pass_count": 0,
        "players": [
            {"name": "P1", "life": 20, "mana_pool": {"G": 2}, "hand": [],
             "battlefield": [{"name": "Short Sword"}, {"name": "Grizzly Bears"}],
             "graveyard": [], "exile": []},
            {"name": "P2", "life": 20, "mana_pool": {}, "hand": [],
             "battlefield": [{"name": "Grizzly Bears"}], "graveyard": [], "exile": []},
        ],
    }
    assert client.post(f"/api/sessions/{sid}/raw-state", json={"state": raw}).status_code == 200

    state = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    sword, bears = state["players"][0]["battlefield"]
    assert sword["name"] == "Short Sword" and sword["attached_to_index"] is None
    spec = sword["target_spec"]
    assert spec["kind"] == "creature" and spec["requires_target"]
    assert [(t["seat"], t["index"]) for t in spec["valid_targets"]] == [(0, 1)]

    activated = client.post(
        f"/api/sessions/{sid}/action",
        json={"seat": 0, "action": "activate", "permanent_name": "Short Sword",
              "permanent_index": 0, "target_seat": 0, "target_permanent_id": bears["id"]},
    )
    assert activated.status_code == 200, activated.text
    client.post(f"/api/sessions/{sid}/action", json={"seat": 0, "action": "pass_priority"})
    client.post(f"/api/sessions/{sid}/action", json={"seat": 1, "action": "pass_priority"})

    after = client.get(f"/api/sessions/{sid}/state?seat=0").json()
    assert after["stack"] == []
    sword, bears = after["players"][0]["battlefield"]
    assert sword["attached_to_index"] == 1 and sword["attached_to_seat"] == 0
    assert (bears["power"], bears["toughness"]) == (3, 3)
