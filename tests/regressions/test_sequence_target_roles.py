"""Regression: a sentence that announces two targets and spends them a step
at a time.

"Shower of Sparks deals 1 damage to target creature **and** 1 damage to target
player or planeswalker." Two instances of the word "target", so CR 601.2c
announces two objects. The line lowered to a ``sequence`` of two ordinary
``deal_damage`` steps carrying one target description each, and
``targeting._from_instructions`` answers with the *first* spec any step
describes — so the caster was asked for a creature, the seat was never
announced at all, and the second step resolved against the target the first one
was still holding. The log read "Shower of Sparks dealt 1 damage to Grizzly
Bears" **twice** and the player took none.

Nothing could see it. The card compiled ``supported``, carried no hollow line,
claimed every printed sentence and passed ``picker_sweep`` — its picker agreed
with its printed line as far as the derivation could read one. Only casting it
and reading the log shows the second point landing on the creature.

Soldevi Heretic is the same shape one channel over and is the worse half:
"Prevent the next 2 damage that would be dealt to target creature this turn.
Target opponent may draw a card." The creature's battlefield seat and the target
opponent are one ``target_player_index``, so naming the opponent aimed the
*shield* at a player — a prevention shield that no damage to a creature can ever
consult — and naming the creature's seat offered the draw to whoever happened to
be sitting there.

**No test asserted the old behaviour and that was deliberate**: a test asserting
the current wrong answer is worse than none. These are written as the fix lands.

What decides whether a line announces one target or two is
``grammar/lowering/_roles.describe_sequence_target_roles``; the sweep at the
bottom is the ratchet over the whole pool, because the half of the class this
round does *not* claim is the half where both descriptions name the same kind
of thing, and that half must stay visible rather than quietly grow.
"""

from __future__ import annotations

from engine.faces import compilation_units
from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec, derive_cast_spec, spec_roles
from tests.helpers import resolve_stack


def _roles_board(catalog_by_name, *, hand=(), mine=(), theirs=(), seats=2):
    """A game with *hand* in seat 0 and creatures on seat 1's battlefield.

    Three seats where a test asks for them: a two-player game makes "the
    announced opponent" and "the only opponent" the same answer, which is
    exactly the coincidence that let one ``target_player_index`` carry two
    different announcements without anybody noticing.
    """
    players = [PlayerState(
        name="P0", life=20,
        hand=[catalog_by_name[name] for name in hand],
        battlefield=[Permanent(card=catalog_by_name[name]) for name in mine],
        library=[catalog_by_name["Grizzly Bears"]] * 5,
    )]
    for index in range(1, seats):
        players.append(PlayerState(
            name=f"P{index}", life=20,
            battlefield=[
                Permanent(card=catalog_by_name[name]) for name in
                (theirs if index == 1 else ())
            ],
            library=[catalog_by_name["Grizzly Bears"]] * 5,
        ))
    game = Game(players=players)
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._sync_control()
    for player in game.players:
        for permanent in player.battlefield:
            permanent.metadata["summoning_sickness_turn"] = -99
    return game


def test_shower_of_sparks_announces_a_creature_and_a_seat(catalog_by_name):
    """The derived announcement, which is what the picker and the cast gate
    both read: two roles, the creature first and the seat second, in the order
    the sentence prints them."""
    card = catalog_by_name["Shower of Sparks"]
    spec = derive_cast_spec(card, compile_card_oracle(card))

    roles = spec_roles(spec)
    assert [role["role"] for role in roles] == ["creature", "player"]
    assert roles[0]["kind"] == "creature"
    assert roles[1]["kind"] == "player_or_planeswalker"


def test_shower_of_sparks_splits_its_damage_between_the_two(catalog_by_name):
    """The bug, as the log showed it: both points on the creature and none on
    the player."""
    game = _roles_board(
        catalog_by_name, hand=("Shower of Sparks",), theirs=("Grizzly Bears",)
    )
    (bear,) = game.players[1].battlefield

    result = game.cast_from_hand(
        0, "Shower of Sparks", target_player_index=1,
        target_permanent_ids=[game.permanent_id_of(bear), None],
    )
    resolve_stack(game)

    assert result.supported, game.log[-3:]
    assert game.players[1].life == 19
    assert sum("dealt 1 damage to Grizzly Bears" in line for line in game.log) == 1


def test_shower_of_sparks_can_burn_a_creature_and_the_caster(catalog_by_name):
    """"Target **player**", not "target opponent": the caster's own seat is a
    legal answer to the second role and the picker offers it. The two roles are
    independent, so the creature on the other board is damaged all the same."""
    game = _roles_board(
        catalog_by_name, hand=("Shower of Sparks",), theirs=("Grizzly Bears",)
    )
    (bear,) = game.players[1].battlefield

    game.cast_from_hand(
        0, "Shower of Sparks", target_player_index=0,
        target_permanent_ids=[game.permanent_id_of(bear), None],
    )
    resolve_stack(game)

    assert game.players[0].life == 19
    assert game.players[1].life == 20
    assert any("dealt 1 damage to Grizzly Bears" in line for line in game.log)


def test_shower_of_sparks_still_burns_the_seat_when_the_creature_has_gone(
    catalog_by_name
):
    """CR 608.2b's last sentence, which is what makes the per-step scoping a
    *skip* rather than a fallback: one illegal target does not stop the spell,
    and the step that has lost its object must do nothing rather than resolve
    against whatever the resolution is still carrying."""
    game = _roles_board(
        catalog_by_name, hand=("Shower of Sparks",), theirs=("Grizzly Bears",)
    )
    (bear,) = game.players[1].battlefield

    game.queue_from_hand(
        0, "Shower of Sparks", target_player_index=1,
        target_permanent_ids=[game.permanent_id_of(bear), None],
    )
    game.remove_from_battlefield(bear)
    resolve_stack(game)

    assert game.players[1].life == 19
    assert not any("dealt 1 damage to Grizzly Bears" in line for line in game.log)


def test_soldevi_heretic_shields_the_creature_not_the_named_seat(catalog_by_name):
    """Three seats, so the announced opponent and the creature's owner differ.

    The shield goes on the *creature*. It used to go on whichever player the
    seat channel named, which is a prevention shield no damage to a creature can
    ever consult — the card did nothing at all, twice over.
    """
    game = _roles_board(
        catalog_by_name, mine=("Soldevi Heretic",), theirs=("Grizzly Bears",),
        seats=3,
    )
    (bear,) = game.players[1].battlefield
    game.interactive_seats = {0, 1, 2}

    result = game.activate_permanent_ability(
        0, "Soldevi Heretic",
        target_role_refs=[
            {"permanent_id": game.permanent_id_of(bear)}, {"seat": 2},
        ],
    )
    resolve_stack(game)

    assert result.supported, game.log[-3:]
    assert any(
        "Grizzly Bears gains prevention shield" in line for line in game.log
    ), game.log[-4:]
    assert not any("P2 gains prevention shield" in line for line in game.log)


def test_soldevi_heretic_names_two_roles_not_one_creature(catalog_by_name):
    """The activation's derived spec, which is what
    ``legality.activation_target_refusal`` gates the whole announcement
    through. It used to be ``{"kind": "creature"}`` — the first step's — so the
    seat was never part of the announcement at all."""
    ability = compile_card_oracle(
        catalog_by_name["Soldevi Heretic"]
    ).activated_abilities[0]

    roles = spec_roles(derive_activation_spec(ability))
    assert [role["role"] for role in roles] == ["creature", "player"]
    # "Target **opponent**" — the printed narrowing travels onto the role, so
    # the picker never offers the activator their own seat.
    assert roles[1]["opponents_only"] is True


def _announced_kinds(instructions) -> "tuple | None":
    """Every *undescribed* target phrase an instruction tree announces, by kind.

    None where a step already carries an ordered-roles description: the
    announcement has been described, which is the outcome the sweep is looking
    for rather than a finding.
    """
    kinds: list[str] = []
    for instruction in instructions:
        described = instruction.payload.get("targets")
        if isinstance(described, dict):
            if described.get("kind") == "roles":
                return None
            if described.get("quantifier") == "target":
                kinds.append(str(described.get("kind")))
        for key in ("steps", "action", "then", "else", "otherwise", "unpaid"):
            nested = instruction.payload.get(key)
            if isinstance(nested, (list, tuple)):
                nested_kinds = _announced_kinds(nested)
                if nested_kinds is None:
                    return None
                kinds.extend(nested_kinds)
    return tuple(kinds)


def test_no_announcement_mixes_a_seat_and_an_object_without_roles():
    """The sweep, over both manifest roles.

    The half of this class the round claims is the pair where one phrase names
    a seat and one names an object. A printed back-reference is resolved by the
    parser into a *copy* of its antecedent, so one target named twice and two
    targets named once are the same shape by the time a line is lowered — and
    the one thing a back-reference cannot do is change what kind of thing it
    points at. The rest of the class stays a shared list with its known loss;
    this is the ratchet on the half that is answerable, so a newly ingested
    card in it arrives as a failure rather than as a silent under-announcement.

    Carried with a floor on how much it examined, because a census that
    measured nothing looks exactly like a census that found nothing — the
    failure UDS's own wave-2 count of this class had, when it asked
    ``activate_permanent_ability`` a question that settles the stack itself and
    so examined zero announcements while passing.
    """
    from engine.targeting import SEAT_ROLE_KINDS

    cards = compilation_units(load_cards(manifest_set_paths(include_measured=True)))
    examined = 0
    unroled: list[str] = []
    for card in cards:
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        # **One announcement is one spell or one ability** (CR 601.2c /
        # 602.2b / 603.3d). ``program.instructions`` holds every ability's
        # instruction for a permanent, so reading it as a spell's would count
        # two separate announcements as one and report a card whose two
        # abilities each name one target (Witch Hunter, Brash Taunter).
        announcements = [
            program.instructions
            if not (program.activated_abilities or program.triggered_abilities)
            else ()
        ]
        announcements += [
            (ability.instruction,) for ability in program.activated_abilities
            if ability.instruction is not None
        ]
        announcements += [
            (trigger.instruction,) for trigger in program.triggered_abilities
            if trigger.instruction is not None
        ]
        for instructions in announcements:
            if not instructions:
                continue
            examined += 1
            kinds = _announced_kinds(instructions)
            if kinds is None or len(kinds) != 2:
                continue
            seats = [kind for kind in kinds if kind in SEAT_ROLE_KINDS]
            objects = [kind for kind in kinds if kind == "object"]
            if len(seats) == 1 and len(objects) == 1:
                unroled.append(card.name)

    assert examined > 4000, (
        f"the sweep examined {examined} announcements, which is too few to be "
        "measuring the pool"
    )
    assert sorted(set(unroled)) == ["Keeper of the Dead"], (
        "an announcement naming one seat and one object must be described as "
        f"ordered roles: {sorted(set(unroled))}. Keeper of the Dead is the one "
        "the conversion declines, and by name: its object slot is narrowed by "
        "'that player controls' — a seat nothing hands the enumerator, so a "
        "role built from it would offer nothing. It is not silent about that "
        "today either; it announces its seat and then picks the creature "
        "itself at resolution, which is a target the activator is supposed to "
        "choose (CR 601.2c)."
    )
