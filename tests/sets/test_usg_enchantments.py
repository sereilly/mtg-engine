"""Urza's Saga enchantments.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("USG")` / `set_cards("USG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G5: the cards that reported supported and did nothing ---
import dataclasses

import pytest

from engine import Game, PlayerState
from engine.auras import PUT_ONTO_BATTLEFIELD_BY
from engine.models import Permanent
from engine.named_counters import add_counters
from engine.oracle import compile_card_oracle
from tests.helpers import _damage_dealt, _mk_creature_card, resolve_stack


def _g5_game(*, interactive=()):
    """Two seats, no mana enforcement, and whichever of them answers prompts.

    A ``_g5_`` prefix and a body ending on ``return game, p1, p2`` rather than on
    the bare ``return game`` every other wave helper ends on, per SET_PLAYBOOK.md's
    note about a union splicing one helper's body onto another's signature.
    """
    p1, p2 = PlayerState(name="G5A"), PlayerState(name="G5B")
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, p1, p2


def _g5_put(game, seat, card):
    """One permanent onto *seat*'s battlefield, through the entry path."""
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    game._sync_control()
    return permanent


def _g5_colored(name, power, toughness, colors):
    return dataclasses.replace(
        _mk_creature_card(name, power, toughness), colors=colors
    )


def test_w1g5_war_dance_pumps_by_the_verse_counters_it_was_sacrificed_with(set_pool):
    """Sacrifice this enchantment: Target creature gets +X/+X until end of turn,
    where X is the number of verse counters on this enchantment.

    The counters are read after the cost has already eaten the enchantment
    (CR 601.2h before CR 608.2), so this is CR 608.2h's last known information —
    and it works because the counters live on the permanent object, which the
    resolution still holds.
    """
    game, p1, _p2 = _g5_game()
    dance = _g5_put(game, 0, set_pool("USG")["War Dance"])
    bear = _g5_put(game, 0, _mk_creature_card("G5 Bear", 2, 2))
    add_counters(dance, "verse", 3)

    result = game.activate_permanent_ability(
        0, "War Dance", target_permanent_ids=[bear.permanent_id]
    )
    assert result.supported
    resolve_stack(game)

    assert dance not in p1.battlefield, "the cost sacrificed it"
    assert (bear.effective_power, bear.effective_toughness) == (5, 5)


def test_w1g5_war_dance_with_no_counters_pumps_by_nothing(set_pool):
    """The same read, at zero: a card whose X counted nothing must not fall back
    to the cast's X, which for an ability is None."""
    game, _p1, _p2 = _g5_game()
    _g5_put(game, 0, set_pool("USG")["War Dance"])
    bear = _g5_put(game, 0, _mk_creature_card("G5 Bear", 2, 2))

    game.activate_permanent_ability(
        0, "War Dance", target_permanent_ids=[bear.permanent_id]
    )
    resolve_stack(game)
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)


@pytest.mark.parametrize(
    "counters,targets,expected",
    [
        (1, 1, ["G5 W0"]),
        (2, 2, ["G5 W0", "G5 W1"]),
        (3, 3, ["G5 W0", "G5 W1", "G5 W2"]),
    ],
)
def test_w1g5_vile_requiem_destroys_exactly_its_verse_counters(
    set_pool, counters, targets, expected
):
    """{1}{B}, Sacrifice this enchantment: Destroy up to X target nonblack
    creatures, where X is the number of verse counters on this enchantment."""
    game, _p1, p2 = _g5_game()
    requiem = _g5_put(game, 0, set_pool("USG")["Vile Requiem"])
    victims = [
        _g5_put(game, 1, _g5_colored("G5 W%d" % i, 1, 1, ("W",))) for i in range(3)
    ]
    add_counters(requiem, "verse", counters)

    assert game.activate_permanent_ability(
        0, "Vile Requiem",
        target_permanent_ids=[v.permanent_id for v in victims[:targets]],
    ).supported
    resolve_stack(game)
    assert [card.name for card in p2.graveyard] == expected


def test_w1g5_vile_requiem_refuses_more_targets_than_it_has_counters(set_pool):
    """CR 601.2c, and the whole reason this test exists: "up to X" is a printed
    ceiling, and an unenforced ceiling is an ability that works more often than
    the card allows — silently, and in the player's favour.

    Nothing is paid: the enchantment is still on the battlefield afterwards.
    """
    game, p1, p2 = _g5_game()
    requiem = _g5_put(game, 0, set_pool("USG")["Vile Requiem"])
    victims = [
        _g5_put(game, 1, _g5_colored("G5 W%d" % i, 1, 1, ("W",))) for i in range(3)
    ]
    add_counters(requiem, "verse", 1)

    result = game.activate_permanent_ability(
        0, "Vile Requiem",
        target_permanent_ids=[v.permanent_id for v in victims],
    )
    assert not result.supported
    assert p2.graveyard == []
    assert requiem in p1.battlefield, "an illegal announcement pays nothing"


def test_w1g5_vile_requiem_beats_a_regeneration_shield(set_pool):
    """"They can't be regenerated." — the rider the where-clause used to hide."""
    game, _p1, p2 = _g5_game()
    requiem = _g5_put(game, 0, set_pool("USG")["Vile Requiem"])
    victim = _g5_put(game, 1, _g5_colored("G5 W0", 1, 1, ("W",)))
    victim.regeneration_shield = 1
    add_counters(requiem, "verse", 1)

    game.activate_permanent_ability(
        0, "Vile Requiem", target_permanent_ids=[victim.permanent_id]
    )
    resolve_stack(game)
    assert [card.name for card in p2.graveyard] == ["G5 W0"]


def test_w1g5_recantation_returns_every_permanent_it_named(set_pool):
    """{U}, Sacrifice this enchantment: Return up to X target permanents to
    their owners' hands.

    A **permanent**, not a creature: the several-target resolver defaults to
    creatures, so the land named as one of the three was dropped before the
    handler could see it.
    """
    game, _p1, p2 = _g5_game()
    recantation = _g5_put(game, 0, set_pool("USG")["Recantation"])
    bear = _g5_put(game, 1, _mk_creature_card("G5 Bear", 2, 2))
    land = _g5_put(game, 1, set_pool("USG")["Gaea's Cradle"])
    ogre = _g5_put(game, 1, _mk_creature_card("G5 Ogre", 3, 3))
    add_counters(recantation, "verse", 3)

    assert game.activate_permanent_ability(
        0, "Recantation",
        target_permanent_ids=[
            bear.permanent_id, land.permanent_id, ogre.permanent_id
        ],
    ).supported
    resolve_stack(game)

    assert p2.battlefield == []
    assert sorted(card.name for card in p2.hand) == [
        "G5 Bear", "G5 Ogre", "Gaea's Cradle",
    ]


def test_w1g5_discordant_dirge_discards_its_verse_counters_worth(set_pool):
    """{B}, Sacrifice this enchantment: Look at target opponent's hand and
    choose up to X cards from it. That player discards those cards."""
    game, _p1, p2 = _g5_game()
    dirge = _g5_put(game, 0, set_pool("USG")["Discordant Dirge"])
    for i in range(4):
        p2.hand.append(_mk_creature_card("G5 H%d" % i, 1, 1))
    add_counters(dirge, "verse", 2)

    assert game.activate_permanent_ability(
        0, "Discordant Dirge", target_player_index=1
    ).supported
    resolve_stack(game)

    for _ in range(2):
        pending = next(
            choice for choice in game.pending_choices
            if choice.kind == "revealed_hand_pick"
        )
        game.confirm_revealed_hand_pick(0, pending.data["legal_indices"][0])
    assert len(p2.graveyard) == 2
    assert len(p2.hand) == 2


def test_w1g5_discordant_dirge_may_choose_fewer_than_x(set_pool):
    """The printed "up to". Read as a plain count the chooser would be made to
    take every card the number allows, which is a different card whenever taking
    fewer is better — and the prompt chain had no way out at all."""
    game, _p1, p2 = _g5_game()
    dirge = _g5_put(game, 0, set_pool("USG")["Discordant Dirge"])
    for i in range(4):
        p2.hand.append(_mk_creature_card("G5 K%d" % i, 1, 1))
    add_counters(dirge, "verse", 3)

    game.activate_permanent_ability(0, "Discordant Dirge", target_player_index=1)
    resolve_stack(game)
    pending = next(
        choice for choice in game.pending_choices
        if choice.kind == "revealed_hand_pick"
    )
    game.confirm_revealed_hand_pick(0, pending.data["legal_indices"][0])
    assert game.confirm_revealed_hand_pick(0, None), "the ceiling permits stopping"
    assert len(p2.graveyard) == 1
    assert not game.pending_choices


def test_w1g5_a_plain_revealed_hand_pick_cannot_be_declined():
    """The other half of the same permission: Duress prints no "up to", so an
    answer naming no card is refused rather than resolving the spell for free."""
    game, _p1, p2 = _g5_game()
    p2.hand.append(_mk_creature_card("G5 Victim", 1, 1))
    game.arm_pending_choice(
        "revealed_hand_pick", 0,
        card_name="Duress", victim_index=1, legal_indices=[0], remaining=1,
        fate="discard",
    )
    assert not game.confirm_revealed_hand_pick(0, None)
    assert game.pending_choices, "the prompt is still owed"


def test_w1g5_serras_hymn_splits_its_verse_counters_among_the_targets(set_pool):
    """Sacrifice this enchantment: Prevent the next X damage that would be dealt
    this turn to any number of targets, divided as you choose.

    The pool's first activated ability with a divided target, so every step of
    CR 601.2d had to reach the activation path: the announcement, the ids it is
    stamped with, and the gate that checks the shares total X.
    """
    game, p1, _p2 = _g5_game()
    hymn = _g5_put(game, 0, set_pool("USG")["Serra's Hymn"])
    bear = _g5_put(game, 0, _mk_creature_card("G5 Bear", 4, 4))
    add_counters(hymn, "verse", 5)

    assert game.activate_permanent_ability(
        0, "Serra's Hymn",
        divided_targets=[(0, None, 3), (0, p1.battlefield.index(bear), 2)],
    ).supported
    resolve_stack(game)

    assert _damage_dealt(game, p1, 5) == 2, "3 of the 5 prevented"
    assert _damage_dealt(game, bear, 4) == 2, "2 of the 4 prevented"


def test_w1g5_serras_hymn_refuses_a_division_that_does_not_total_x(set_pool):
    """CR 601.2d, asked of an ability — and asked *before* the cost, so an
    illegal announcement leaves the enchantment on the battlefield."""
    game, p1, _p2 = _g5_game()
    hymn = _g5_put(game, 0, set_pool("USG")["Serra's Hymn"])
    bear = _g5_put(game, 0, _mk_creature_card("G5 Bear", 4, 4))
    add_counters(hymn, "verse", 4)

    result = game.activate_permanent_ability(
        0, "Serra's Hymn",
        divided_targets=[(0, None, 3), (0, p1.battlefield.index(bear), 2)],
    )
    assert not result.supported
    assert hymn in p1.battlefield
    assert p1.damage_prevention_pool == 0
    assert bear.damage_prevention_pool == 0


def test_w1g5_sporogenesis_makes_one_saproling_per_fungus_counter(set_pool):
    """Whenever a creature with a fungus counter on it dies, create a 1/1 green
    Saproling creature token for each fungus counter on that creature.

    The count is the *last known* one (CR 603.10 / 608.2h): by the time the
    trigger resolves the creature is a card in a graveyard with no counters at
    all (CR 400.7), so a live read answers zero on every board.
    """
    game, p1, _p2 = _g5_game()
    _g5_put(game, 0, set_pool("USG")["Sporogenesis"])
    victim = _g5_put(game, 0, _mk_creature_card("G5 Victim", 2, 2))
    add_counters(victim, "fungus", 3)

    victim.damage_marked = 99
    game.check_state_based_actions()
    resolve_stack(game)

    tokens = [
        permanent for permanent in p1.battlefield
        if permanent.metadata.get("is_token")
    ]
    assert len(tokens) == 3
    assert all(token.card.name == "Saproling Token" for token in tokens)


def test_w1g5_sporogenesis_ignores_a_death_with_no_fungus_counters(set_pool):
    """The trigger is narrowed by the printed noun phrase, so an ordinary death
    makes nothing — a dropped narrowing here would be a token per death."""
    game, p1, _p2 = _g5_game()
    _g5_put(game, 0, set_pool("USG")["Sporogenesis"])
    bystander = _g5_put(game, 0, _mk_creature_card("G5 Bystander", 2, 2))

    bystander.damage_marked = 99
    game.check_state_based_actions()
    resolve_stack(game)
    assert not [
        permanent for permanent in p1.battlefield
        if permanent.metadata.get("is_token")
    ]


def test_w1g5_diabolic_servitude_exiles_the_creature_it_returned(set_pool):
    """When the creature put onto the battlefield with this enchantment dies,
    exile it and return this enchantment to its owner's hand.

    Both halves. The trigger used to be classified as the *source's* own death,
    so it fired when the enchantment went to the graveyard and never when the
    creature did; and "exile it" lowered to ``exile_self``, the enchantment
    exiling itself.
    """
    game, p1, _p2 = _g5_game()
    p1.graveyard.append(_mk_creature_card("G5 Zombie", 2, 2))
    servitude = _g5_put(game, 0, set_pool("USG")["Diabolic Servitude"])
    resolve_stack(game)

    zombie = next(p for p in p1.battlefield if p.card.name == "G5 Zombie")
    assert zombie.metadata[PUT_ONTO_BATTLEFIELD_BY] == servitude.permanent_id

    zombie.damage_marked = 99
    game.check_state_based_actions()
    resolve_stack(game)

    assert [card.name for card in p1.exile] == ["G5 Zombie"]
    assert [card.name for card in p1.hand] == ["Diabolic Servitude"]
    assert p1.graveyard == []


def test_w1g5_diabolic_servitude_exiles_the_creature_when_it_leaves(set_pool):
    """When this enchantment leaves the battlefield, exile the creature put onto
    the battlefield with this enchantment. The other direction, and the one that
    names the creature while it is still a permanent."""
    game, p1, _p2 = _g5_game()
    p1.graveyard.append(_mk_creature_card("G5 Zombie", 2, 2))
    servitude = _g5_put(game, 0, set_pool("USG")["Diabolic Servitude"])
    resolve_stack(game)

    # The one leave transition, which announces CR 603.6c itself — no separate
    # fire call, and none to forget.
    game.remove_from_battlefield(servitude)
    p1.graveyard.append(servitude.card)
    resolve_stack(game)

    assert [card.name for card in p1.exile] == ["G5 Zombie"]
    assert not [p for p in p1.battlefield if p.card.name == "G5 Zombie"]


def test_w1g5_diabolic_servitude_leaves_another_enchantments_creature_alone(set_pool):
    """The record is per-permanent and by id: a second Servitude's creature is
    not this one's, and a sweep that dropped the narrowing would exile it."""
    game, p1, _p2 = _g5_game()
    p1.graveyard.append(_mk_creature_card("G5 Zombie", 2, 2))
    first = _g5_put(game, 0, set_pool("USG")["Diabolic Servitude"])
    resolve_stack(game)
    p1.graveyard.append(_mk_creature_card("G5 Ghoul", 1, 1))
    _g5_put(game, 0, set_pool("USG")["Diabolic Servitude"])
    resolve_stack(game)

    game.remove_from_battlefield(first)
    p1.graveyard.append(first.card)
    resolve_stack(game)

    assert [card.name for card in p1.exile] == ["G5 Zombie"]
    assert [p.card.name for p in p1.battlefield if p.is_creature] == ["G5 Ghoul"]


def test_w1g5_every_usg_hollow_card_now_carries_an_instruction(set_pool):
    """The guard this group exists for. Each of these compiled as *supported*
    while the named part carried no instruction at all — which is what
    ``--hollow-lines`` reports and what no ratchet test can see, because a card
    is supported when **any** of its lines is."""
    pool = set_pool("USG")
    for name in (
        "War Dance", "Vile Requiem", "Recantation", "Discordant Dirge",
        "Serra's Hymn", "Diabolic Servitude", "Sporogenesis",
        "Phyrexian Processor", "Smokestack",
    ):
        program = compile_card_oracle(pool[name])
        parts = list(program.activated_abilities) + list(program.triggered_abilities)
        hollow = [part.source_line for part in parts if part.instruction is None]
        assert not hollow, "%s still has an instruction-less part: %s" % (name, hollow)
