"""Regression: a modal spell is held to CR 601.2c for the mode it announced.

CR 601.2b chooses a spell's mode and CR 601.2c then chooses that mode's
targets, so "is this a legal target?" is a question about the mode. The engine
asked it about **mode 0** — ``derive_cast_spec`` reads the card — and, because
that refused legal casts (Healing Salve's second mode targets a creature and
its first a player), every gate built since then simply declined modal spells:
``cast_target_obligation``, ``cast_target_refusal``, the stack-target gate and
CR 608.2b's ``illegal_targets_refusal`` each opened with ``if program.modes:
return None``. What was left was the per-kind arms in
``_validate_cast_targets``, which name eleven instruction kinds and read the
target's *index*.

So a mode named by id was checked by nobody, and a mode whose kind has no arm
was checked by neither spelling. Planeshift prints five Charms and Hull Breach:

* Rith's Charm ("destroy target **nonbasic** land") was accepted at a basic
  land and Crosis's Charm ("destroy target **nonblack** creature") at a black
  one, each then fizzling with the card spent;
* Treva's Charm ("exile target **attacking** creature") was accepted at a
  creature that was not attacking, and castable outside combat altogether;
* Hull Breach's third mode ("destroy target artifact **and** target
  enchantment") was castable with no enchantment anywhere and behaved as its
  first — and Reign of Chaos' second mode, the other way round, was *refused*
  a legal Island and blue creature for not being a Plains and a white one;
* the browser was sent each mode's picker by a table of its own
  (``web/serialization._mode_target_kind``) whose fall-through answered
  "player", so "deals 1 damage to target creature" asked for a player.

The fix is one derivation — ``targeting.announced_mode_instructions`` /
``derive_cast_spec(mode_index=)`` — read by all of them. The census at the
bottom is the ratchet: every mode of every modal instant and sorcery in both
manifest roles, against an oracle that never read the cast gate (what the same
sentence printed on an *activated ability* would be offered). On the tree
before the fix it reported 1,066 of 1,516 illegal named targets accepted, 220
of those then acting on a permanent nobody named, 18 of 46 mandatory modes
castable with no legal target anywhere, and 33 of 47 object modes sent to the
client with the wrong picker.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.legality import targeting_instruction
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import _first_described_slot, derive_cast_spec, spec_roles
from tests.helpers import _mk_card, resolve_stack

_GATE_608 = "every target is illegal (608.2b)"


def _w2g2_pool() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        cards.setdefault(card.name, card)
    return cards


_POOL = _w2g2_pool()


def _w2g2_perm(card) -> Permanent:
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w2g2_table(spells, *, mine=(), theirs=(), active: int = 0) -> Game:
    forest = _POOL["Forest"]
    game = Game(players=[
        PlayerState(name="P0", hand=list(spells), library=[forest] * 10, battlefield=list(mine)),
        PlayerState(name="P1", library=[forest] * 10, battlefield=list(theirs)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(active)
    game._close_current_priority_step()
    return game


def _w2g2_creature(name, colors=(), power=2, toughness=2, type_line="Creature - Bear"):
    return _w2g2_perm(
        _mk_card(name=name, type_line=type_line, colors=colors, power=power, toughness=toughness)
    )


def _w2g2_hand(game) -> list[str]:
    return [card.name for card in game.players[0].hand]


# ---------------------------------------------------------------------------
# The sightings, one card each
# ---------------------------------------------------------------------------


def test_w2g2_riths_charm_refuses_a_basic_land_and_destroys_a_nonbasic_one():
    """"Destroy target nonbasic land." The basic was accepted by id and the
    spell then did nothing; refused now, with the card still in hand."""
    charm = _POOL["Rith's Charm"]
    island = _w2g2_perm(_POOL["Island"])
    tower = _w2g2_perm(_mk_card(name="Tower", type_line="Land"))
    game = _w2g2_table([charm], theirs=[island, tower])

    refused = game.cast_from_hand(0, charm.name, mode_index=0, target_permanent_ids=[island.permanent_id])
    assert not refused.supported, "a basic land was accepted for 'target nonbasic land'"
    assert _w2g2_hand(game) == [charm.name]
    assert game.is_on_battlefield(island)

    cast = game.cast_from_hand(0, charm.name, mode_index=0, target_permanent_ids=[tower.permanent_id])
    assert cast.supported, cast.details
    assert not game.is_on_battlefield(tower), game.log
    assert game.is_on_battlefield(island)


def test_w2g2_crosis_charm_refuses_a_black_creature_for_its_nonblack_mode():
    charm = _POOL["Crosis's Charm"]
    black = _w2g2_creature("Black Knight", colors=("B",))
    green = _w2g2_creature("Green Bear", colors=("G",))
    game = _w2g2_table([charm], theirs=[black, green])

    refused = game.cast_from_hand(0, charm.name, mode_index=1, target_permanent_ids=[black.permanent_id])
    assert not refused.supported, "a black creature was accepted for 'target nonblack creature'"
    assert game.is_on_battlefield(black) and game.is_on_battlefield(green)
    assert _w2g2_hand(game) == [charm.name]

    cast = game.cast_from_hand(0, charm.name, mode_index=1, target_permanent_ids=[green.permanent_id])
    assert cast.supported, cast.details
    assert not game.is_on_battlefield(green), game.log
    assert game.is_on_battlefield(black), "the creature nobody named was destroyed"


def test_w2g2_trevas_charm_exiles_an_attacker_and_nothing_else():
    """"Exile target attacking creature." No arm names the kind, so the mode
    was castable at any creature — and with nobody attacking at all."""
    charm = _POOL["Treva's Charm"]
    attacker = _w2g2_creature("Attacker")
    idler = _w2g2_creature("Idler")
    enchantment = _w2g2_perm(_mk_card(name="Glow", type_line="Enchantment"))

    quiet = _w2g2_table([charm], theirs=[attacker, idler])
    outside_combat = quiet.cast_from_hand(0, charm.name, mode_index=1)
    assert not outside_combat.supported, "castable with no attacking creature anywhere"
    by_name = quiet.cast_from_hand(
        0, charm.name, mode_index=1, target_permanent_ids=[idler.permanent_id]
    )
    assert not by_name.supported

    attacker, idler = _w2g2_creature("Attacker"), _w2g2_creature("Idler")
    game = _w2g2_table([charm], theirs=[attacker, idler, enchantment], active=1)
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers"
    game.declare_attackers(1, [0], defending_player_index=0)

    refused = game.queue_from_hand(0, charm.name, mode_index=1, target_permanent_ids=[idler.permanent_id])
    assert not refused.supported, "a creature that is not attacking was accepted"
    wrong_mode = game.queue_from_hand(0, charm.name, mode_index=0, target_permanent_ids=[idler.permanent_id])
    assert not wrong_mode.supported, "a creature was accepted for 'destroy target enchantment'"

    cast = game.queue_from_hand(0, charm.name, mode_index=1, target_permanent_ids=[attacker.permanent_id])
    assert cast.supported, cast.details
    resolve_stack(game)
    assert not game.is_on_battlefield(attacker), game.log
    assert game.is_on_battlefield(idler) and game.is_on_battlefield(enchantment)


def test_w2g2_hull_breach_third_mode_names_an_artifact_and_an_enchantment():
    """A mode with **two** targets. Its spec is two roles, which nothing
    counted while the gate read mode 0's ("destroy target artifact") — so the
    mode was castable with no enchantment in existence and behaved as mode 0."""
    breach = _POOL["Hull Breach"]
    rock = _w2g2_perm(_mk_card(name="Rock", type_line="Artifact"))
    glow = _w2g2_perm(_mk_card(name="Glow", type_line="Enchantment"))

    lonely = _w2g2_table([breach], theirs=[rock])
    assert not lonely.cast_from_hand(
        0, breach.name, mode_index=2, target_permanent_ids=[rock.permanent_id]
    ).supported, "castable with no enchantment to name"
    assert lonely.is_on_battlefield(rock)
    assert 2 not in lonely.announceable_modes(0, breach)
    assert lonely.announceable_modes(0, breach) == [0]

    rock = _w2g2_perm(_mk_card(name="Rock", type_line="Artifact"))
    game = _w2g2_table([breach], theirs=[rock, glow])
    assert not game.cast_from_hand(
        0, breach.name, mode_index=2, target_permanent_ids=[rock.permanent_id]
    ).supported, "one target named for a mode that prints two"
    assert not game.cast_from_hand(
        0, breach.name, mode_index=2,
        target_permanent_ids=[glow.permanent_id, rock.permanent_id],
    ).supported, "the enchantment was accepted as the artifact"

    cast = game.cast_from_hand(
        0, breach.name, mode_index=2,
        target_permanent_ids=[rock.permanent_id, glow.permanent_id],
    )
    assert cast.supported, cast.details
    assert not game.is_on_battlefield(rock) and not game.is_on_battlefield(glow), game.log


def test_w2g2_reign_of_chaos_second_mode_is_judged_as_the_second_mode():
    """The other direction: a **legal** cast that was refused. Both modes are
    two roles, and mode 1's Island and blue creature were held to mode 0's
    Plains and white creature."""
    reign = _POOL["Reign of Chaos"]
    island = _w2g2_perm(_POOL["Island"])
    merfolk = _w2g2_creature("Merfolk", colors=("U",))
    plains = _w2g2_perm(_POOL["Plains"])
    game = _w2g2_table([reign], theirs=[island, merfolk, plains])

    assert not game.cast_from_hand(
        0, reign.name, mode_index=1,
        target_permanent_ids=[plains.permanent_id, merfolk.permanent_id],
    ).supported, "a Plains was accepted as mode 1's Island"
    cast = game.cast_from_hand(
        0, reign.name, mode_index=1,
        target_permanent_ids=[island.permanent_id, merfolk.permanent_id],
    )
    assert cast.supported, cast.details
    assert not game.is_on_battlefield(island) and not game.is_on_battlefield(merfolk), game.log
    assert game.is_on_battlefield(plains)


def test_w2g2_a_mode_with_nothing_to_target_is_refused_and_its_sibling_is_not():
    """CR 601.2c's first half, per mode. "Chaos Charm deals 1 damage to target
    creature" has no arm in ``_validate_cast_targets``, so it was announceable
    at an empty board; its siblings are judged on their own."""
    chaos = _POOL["Chaos Charm"]
    game = _w2g2_table([chaos])
    for mode in (0, 1, 2):
        result = game.queue_from_hand(0, chaos.name, mode_index=mode)
        assert not result.supported, f"mode {mode} was castable at an empty board"
    assert game.announceable_modes(0, chaos) == []

    riths = _POOL["Rith's Charm"]
    game = _w2g2_table([riths])
    assert game.announceable_modes(0, riths) == [1, 2]
    assert not game.queue_from_hand(0, riths.name, mode_index=0).supported
    cast = game.cast_from_hand(0, riths.name, mode_index=1)
    assert cast.supported, cast.details
    assert len([p for p in game.controlled_by(0) if p.is_creature]) == 3, game.log


def test_w2g2_an_up_to_mode_may_name_nobody():
    """"Return **up to two** target creatures to their owners' hands" (Read the
    Tides). Zero is a legal number of targets (CR 601.2c), and the arm that
    knows so was told "not for a modal spell" — the mode was uncastable at a
    board with no creature."""
    tides = _POOL["Read the Tides"]
    game = _w2g2_table([tides])

    cast = game.cast_from_hand(0, tides.name, mode_index=1)

    assert cast.supported, cast.details
    assert game.announceable_modes(0, tides) == [0, 1]


def test_w2g2_a_mode_target_made_illegal_in_response_counters_the_spell():
    """CR 608.2b for the chosen mode. The description re-check excluded modal
    spells (it would have re-asked mode 0's), so a Crosis's Charm whose target
    turned black fell to its handler — and, where a handler's resolver refuses
    the id and scans on, to a creature nobody named."""
    charm = _POOL["Crosis's Charm"]
    named = _w2g2_creature("Named", colors=("G",))
    bystander = _w2g2_creature("Bystander", colors=("G",))
    game = _w2g2_table([charm], theirs=[named, bystander])

    queued = game.queue_from_hand(0, charm.name, mode_index=1, target_permanent_ids=[named.permanent_id])
    assert queued.supported, queued.details
    named.metadata["color_override"] = ("B",)
    resolve_stack(game)

    assert game.is_on_battlefield(named), game.log
    assert game.is_on_battlefield(bystander), "a creature nobody named was destroyed"
    assert any(_GATE_608 in line for line in game.log), game.log
    assert charm.name in [c.name for c in game.players[0].graveyard]


def test_w2g2_a_bounce_mode_is_not_countered_for_failing_another_modes_description():
    """The exclusion's own reason, now answered rather than avoided: Active
    Volcano's "return target Island" re-asked as mode 0's "target blue
    permanent" countered every Island bounce."""
    volcano = _POOL["Active Volcano"]
    island = _w2g2_perm(_POOL["Island"])
    game = _w2g2_table([volcano], theirs=[island])

    queued = game.queue_from_hand(0, volcano.name, mode_index=1, target_permanent_ids=[island.permanent_id])
    assert queued.supported, queued.details
    resolve_stack(game)

    assert not game.is_on_battlefield(island), game.log
    assert not any(_GATE_608 in line for line in game.log)


def test_w2g2_each_chosen_mode_of_a_choose_one_or_more_spell_is_gated():
    """``mode_choices`` — every chosen mode names its own targets, and every
    gate was handed the cast's own (empty) fields beside the first mode's
    index, so a mode's named target was checked against nothing."""
    epiphany = _POOL["Sublime Epiphany"]
    land = _w2g2_perm(_POOL["Island"])
    bear = _w2g2_creature("Bear")
    game = _w2g2_table([epiphany], theirs=[land, bear])

    refused = game.queue_from_hand(
        0, epiphany.name,
        mode_choices=[
            {"index": 2, "target_player_index": 1, "target_permanent_index": 0},
            {"index": 4, "target_player_index": 0},
        ],
    )
    assert not refused.supported, "a land was accepted for 'target nonland permanent'"

    cast = game.cast_from_hand(
        0, epiphany.name,
        mode_choices=[
            {"index": 2, "target_player_index": 1, "target_permanent_index": 1},
            {"index": 4, "target_player_index": 0},
        ],
    )
    assert cast.supported, cast.details
    assert not game.is_on_battlefield(bear), game.log
    assert game.is_on_battlefield(land)
    assert len(game.players[0].hand) == 1, "the caster drew for the fifth mode"


def test_w2g2_the_spec_of_a_mode_is_derived_per_mode():
    """The derivation itself: one function, asked with the mode."""
    riths = _POOL["Rith's Charm"]
    program = compile_card_oracle(riths)

    assert derive_cast_spec(riths, program, mode_index=0)["kind"] == "land"
    assert derive_cast_spec(riths, program, mode_index=1) is None
    # a cast naming no mode resolves mode 0, so that is what it is asked about
    assert derive_cast_spec(riths, program) == derive_cast_spec(riths, program, mode_index=0)
    hull = _POOL["Hull Breach"]
    roles = spec_roles(derive_cast_spec(hull, compile_card_oracle(hull), mode_index=2))
    assert [role["role"] for role in roles] == ["artifact", "enchantment"]


# ---------------------------------------------------------------------------
# The census: every mode of every modal instant and sorcery
# ---------------------------------------------------------------------------

_OBJECT_KINDS = frozenset({"creature", "artifact", "land", "permanent", "enchantment"})


def _census_bait() -> list:
    return [
        _mk_card(name="Bait White", type_line="Creature - Human Soldier", colors=("W",), power=2, toughness=2),
        _mk_card(name="Bait Blue Flyer", type_line="Creature - Bird", colors=("U",), power=1, toughness=1, oracle_text="Flying"),
        _mk_card(name="Bait Black", type_line="Creature - Zombie", colors=("B",), power=3, toughness=3),
        _mk_card(name="Bait Red", type_line="Creature - Goblin", colors=("R",), power=2, toughness=2),
        _mk_card(name="Bait Green", type_line="Creature - Beast", colors=("G",), power=4, toughness=4),
        _mk_card(name="Bait Wall", type_line="Creature - Wall", power=0, toughness=4, oracle_text="Defender"),
        _mk_card(name="Bait Golem", type_line="Artifact Creature - Golem", power=3, toughness=3),
        _mk_card(name="Bait Artifact", type_line="Artifact"),
        _mk_card(name="Bait Enchantment", type_line="Enchantment", colors=("W",)),
        _mk_card(name="Bait Nonbasic", type_line="Land"),
        _POOL["Plains"], _POOL["Island"], _POOL["Mountain"],
    ]


_CENSUS_AURA = _mk_card(
    name="Bait Aura", type_line="Enchantment - Aura", colors=("G",),
    oracle_text="Enchant creature",
)


def _census_board(card, *, combat: bool) -> Game:
    """A mirrored zoo — the same bait on both sides, so a scan that ignored
    the announcement has somewhere wrong to land. *combat*: seat 1 is
    attacking seat 0 with two of its creatures."""
    game = _w2g2_table(
        [card],
        mine=[Permanent(card=c) for c in _census_bait()],
        theirs=[Permanent(card=c) for c in _census_bait()],
        active=1 if combat else 0,
    )
    for perm in game.all_permanents():
        perm.metadata["summoning_sickness_turn"] = -99
    for seat in (0, 1):
        aura = Permanent(card=_CENSUS_AURA)
        game._put_permanent_onto_battlefield(seat, aura, seat)
        attach_aura(aura, next(iter(game.controlled_by(seat))))
    if combat:
        game.advance_combat_phase()
        game.advance_combat_phase()
        assert game.current_step == "declare_attackers", game.current_step
        game.declare_attackers(1, [2, 3], defending_player_index=0)
    return game


def _census_oracle(game, card, spec, instruction) -> set:
    """What the mode's sentence would be offered on an **activated ability** —
    the enumeration that never read the cast gate, which is what makes it an
    oracle rather than the thing under test asked twice."""
    return {
        (entry["seat"], entry["index"])
        for entry in game._enumerate_targets(
            0, card, dict(spec), for_cast=False,
            ability_instruction=targeting_instruction(instruction),
        )
        if entry.get("kind") == "permanent"
    }


def _census_mandatory(instruction) -> bool:
    described = (instruction.payload or {}).get("targets")
    if not isinstance(described, dict):
        return True
    return described.get("quantifier") not in ("up_to", "any_number") and described.get("count") != "x"


def _census_signature(game, skip=None) -> dict:
    sig = {"life": tuple(p.life for p in game.players)}
    for perm in game.all_permanents():
        if perm is skip:
            continue
        sig[perm.permanent_id] = (
            game.controller_index_of(perm), perm.tapped, perm.damage_marked,
            perm.effective_power if perm.is_creature else None,
            perm.effective_toughness if perm.is_creature else None,
        )
    return sig


def _census_cast(game, card, mode_index, **kwargs):
    x_value = 2 if "{X}" in (card.mana_cost or "") else None
    return game.queue_from_hand(0, card.name, mode_index=mode_index, x_value=x_value, **kwargs)


def _census_modal_cards() -> list[str]:
    names = []
    for name, card in sorted(_POOL.items()):
        if card.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        # CR 700.2e: where an opponent chooses the mode, the caster names no
        # target as it casts; `arm_modal_mode_targets` asks afterwards.
        if program.supported and len(program.modes) >= 2 and program.mode_chooser is None:
            names.append(name)
    return names


_MODAL = _census_modal_cards()


def _census_modes(card):
    """``(index, mode, spec, instruction)`` for every supported mode."""
    program = compile_card_oracle(card)
    for index, mode in enumerate(program.modes):
        if not mode.supported or mode.instruction is None:
            continue
        slot = _first_described_slot((mode.instruction,))
        yield index, mode, (slot[0] if slot else None), (slot[1] if slot else None)


def _object_mode(spec) -> bool:
    return (
        spec is not None and not spec_roles(spec)
        and spec.get("kind") in _OBJECT_KINDS and not spec.get("source_of_choice")
    )


def test_w2g2_the_census_examines_what_it_claims_to():
    """The floor. A census over a pool is worth what it looked at, and every
    exclusion above shrinks that — an ingest that renamed a kind, or a helper
    that began skipping roles, would leave the sweep below green over nothing."""
    cards = [_POOL[name] for name in _MODAL]
    modes = [(card, row) for card in cards for row in _census_modes(card)]
    object_modes = [1 for _card, (_i, _m, spec, _ins) in modes if _object_mode(spec)]
    roles_modes = [1 for _card, (_i, _m, spec, _ins) in modes if spec is not None and spec_roles(spec)]
    untargeted = [1 for _card, (_i, _m, spec, _ins) in modes if spec is None]

    assert len(cards) >= 34, len(cards)
    assert len(modes) >= 88, len(modes)
    assert len(object_modes) >= 47, len(object_modes)
    assert len(roles_modes) >= 3, len(roles_modes)
    assert len(untargeted) >= 13, len(untargeted)
    for sighting in ("Rith's Charm", "Crosis's Charm", "Treva's Charm", "Hull Breach"):
        assert sighting in _MODAL


@pytest.mark.parametrize("name", _MODAL)
def test_w2g2_every_mode_is_held_to_its_own_targets(name):
    """Per mode: a named permanent is accepted exactly when the mode's own
    sentence admits it; with nothing legal anywhere a mandatory mode cannot be
    cast and an optional or untargeted one can; a mode of several roles needs
    each of them; and a target that has left takes nothing else with it."""
    card = _POOL[name]
    problems: list[str] = []
    for index, mode, spec, instruction in _census_modes(card):
        tag = f"[{index}] {mode.label[:44]!r}"
        if spec is None or spec.get("kind") == "none":
            game = _census_board(card, combat=False)
            result = _census_cast(game, card, index)
            if not result.supported:
                problems.append(f"{tag}: targets nothing and was refused: {result.details}")
            continue
        roles = spec_roles(spec)
        if roles:
            game = _census_board(card, combat=False)
            per_role = [_census_oracle(game, card, role, mode.instruction) for role in roles]
            assert all(per_role), f"{name} {tag}: the census board has no candidate for a role"
            chosen = [game.permanent_at(*sorted(slots)[-1]) for slots in per_role]
            if _census_cast(game, card, index, target_permanent_ids=[chosen[0].permanent_id]).supported:
                problems.append(f"{tag}: one target accepted for {len(roles)} roles")
            if _census_cast(
                game, card, index,
                target_permanent_ids=[p.permanent_id for p in reversed(chosen)],
            ).supported:
                problems.append(f"{tag}: the roles were accepted in each other's slots")
            scarce = _census_board(card, combat=False)
            last = _census_oracle(scarce, card, roles[-1], mode.instruction)
            scarce.remove_all_from_battlefield([scarce.permanent_at(*slot) for slot in last])
            first = _census_oracle(scarce, card, roles[0], mode.instruction)
            if first and _census_cast(
                scarce, card, index,
                target_permanent_ids=[scarce.permanent_at(*sorted(first)[-1]).permanent_id],
            ).supported:
                problems.append(f"{tag}: castable with no candidate for the last role")
            if index in scarce.announceable_modes(0, card):
                problems.append(f"{tag}: offered as announceable with a role unfillable")
            result = _census_cast(game, card, index, target_permanent_ids=[p.permanent_id for p in chosen])
            if not result.supported:
                problems.append(f"{tag}: a complete legal announcement was refused: {result.details}")
            continue
        if not _object_mode(spec):
            continue

        combat = False
        game = _census_board(card, combat=False)
        legal = _census_oracle(game, card, spec, mode.instruction)
        if not legal and card.primary_type == "instant":
            combat = True
            game = _census_board(card, combat=True)
            legal = _census_oracle(game, card, spec, mode.instruction)
        assert legal, f"{name} {tag}: no legal target on either census board ({spec})"

        # the engine's own list for the mode is the oracle's
        offered = {
            (entry["seat"], entry["index"])
            for entry in game.cast_target_spec(0, card, mode_index=index)["valid_targets"]
            if entry.get("kind") == "permanent"
        }
        if offered != legal:
            problems.append(
                f"{tag}: the cast list differs from the sentence's own — "
                f"{len(offered - legal)} illegal offered, {len(legal - offered)} legal missing"
            )
        # every permanent the sentence does not admit is refused by name
        # (a refused cast changes nothing, so one board serves them all)
        before = _census_signature(game)
        for perm in list(game.all_permanents()):
            slot = (game.controller_index_of(perm), game.battlefield_index_of(perm))
            if slot in legal:
                continue
            if _census_cast(game, card, index, target_permanent_ids=[perm.permanent_id]).supported:
                problems.append(f"{tag}: {perm.card.name} (seat {slot[0]}) was ACCEPTED")
                game = _census_board(card, combat=combat)
        if not problems:
            assert _census_signature(game) == before, f"{name} {tag}: a refused cast changed the board"
        # a legal one is accepted, on each side that has one
        for seat in sorted({seat for seat, _ in legal}):
            game = _census_board(card, combat=combat)
            target = game.permanent_at(*sorted(s for s in legal if s[0] == seat)[-1])
            result = _census_cast(game, card, index, target_permanent_ids=[target.permanent_id])
            if not result.supported:
                problems.append(f"{tag}: legal {target.card.name} (seat {seat}) refused: {result.details}")
        # CR 608.2b: the named target gone, nothing else is touched
        game = _census_board(card, combat=combat)
        target = game.permanent_at(*sorted(legal)[-1])
        if _census_cast(game, card, index, target_permanent_ids=[target.permanent_id]).supported:
            game.remove_from_battlefield(target)
            before = _census_signature(game)
            resolve_stack(game)
            if _census_signature(game) != before:
                problems.append(f"{tag}: its target left and something else changed on resolution")
        # nothing legal anywhere
        game = _census_board(card, combat=combat)
        game.remove_all_from_battlefield(
            [game.permanent_at(*slot) for slot in _census_oracle(game, card, spec, mode.instruction)]
        )
        assert not _census_oracle(game, card, spec, mode.instruction)
        bare = _census_cast(game, card, index)
        announceable = index in game.announceable_modes(0, card)
        if _census_mandatory(instruction):
            if bare.supported:
                problems.append(f"{tag}: castable with no legal target anywhere")
            if announceable:
                problems.append(f"{tag}: offered as announceable with no legal target anywhere")
        else:
            if not bare.supported:
                problems.append(f"{tag}: an 'up to' mode refused for having nobody to name: {bare.details}")
            if not announceable:
                problems.append(f"{tag}: an 'up to' mode not offered as announceable")
    assert not problems, f"{name}: " + "; ".join(problems)
