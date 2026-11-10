"""The honesty checks a simulated game is held to (``ai_simulator.run_ai_simulation``).

Both are deliberately independent of the program they check. **Zone
conservation** (``_zone_counter``), asked after every turn: every card in the
game by name — every zone, the stack, the sideboards, a permanent another one
holds out of play — against the count the game started with, so a card may
move anywhere and may not stop existing or start existing twice. And **the
printed card's expectation** (``_assert_expected``, over ``_snap``'s clones of
both seats taken before and after a cast): what a handful of cards the decks
can deal are printed to do, read off the card by a human rather than derived
from the compiled program under test.

Split out of ``engine/ai_simulator.py`` at the size band (round kg3).
"""

from __future__ import annotations

from collections import Counter

from .faces import whole_card
from .game import Game
from .models import CardDefinition, Permanent, PlayerState
from .search_filters import card_has_type


def _zone_counter(game: Game) -> Counter[str]:
    """Every card in the game, by name — the whole board, not one seat's.

    Two corrections, both of which only a deck built from a whole set can
    reach. **Every zone counts**: this read library, hand, graveyard and
    battlefield, which were all the zones the old eight-card decklist could put
    a card in. Feldon's Cane exiles itself to shuffle a graveyard back and
    Contract from Below antes the top card, so both looked like a card
    vanishing from the game — a false alarm, reported dozens of times per run.

    And the count is **global rather than per seat**, because a card legally
    changing hands is not a leak: Old Man of the Sea takes control of a
    creature and Contract from Below antes into another player's zone, either
    of which fails a per-seat comparison while nothing is wrong. What is left
    is the invariant actually worth asserting — a card may move anywhere, and
    may not stop existing or start existing twice.

    **And a seat's sideboard counts**, though it is not in the game at all (CR
    400.11a). A Wish or Ring of Ma'rûf brings one of its cards *into* the game
    (CR 400.11b), and counted from the game's zones alone that card read as
    one starting to exist — measured at Judgment with sideboards given to the
    seats by hand: fourteen false alarms in four games. Every seat is dealt
    one now (`limited_sideboard`, CR 100.4b), so this is the reservoir the
    invariant runs over in every game.
    """
    counter: Counter[str] = Counter()
    for player in game.players:
        for zone in (
            player.library, player.hand, player.graveyard,
            player.exile, player.ante, player.command_zone,
            player.sideboard,
        ):
            for card in zone:
                counter[card.name] += 1
        for permanent in player.phased_out:
            if not permanent.metadata.get("is_token"):
                counter[whole_card(permanent.card).name] += 1
    for _seat, permanent in game.permanents_with_controller():
        # Ignore generated tokens in zone conservation checks.
        if permanent.metadata.get("is_token"):
            continue
        # By the card it is: a face-down permanent's card is the blank 2/2
        # (CR 708.2a), and the card it hides is the one in the game
        # (``faces.whole_card``, CR 708.9) — the stack's reading below.
        counter[whole_card(permanent.card).name] += 1
    # A spell or ability mid-resolution is still a card in the game. The check
    # runs after the pending-choice drain, so this is normally empty — but a
    # prompt that suspends leaves its object here, and counting it stops that
    # from reading as a disappearance.
    for item in game.stack:
        # An *ability* on the stack is not a card (CR 113.7) and its `card` is
        # the source permanent's, which is counted on the battlefield already —
        # so counting it duplicates the permanent. `ability_instruction` is the
        # discriminator `StackItem` actually carries; there is no `is_ability`,
        # and asking for one with a default quietly counted every ability.
        if item.ability_instruction is None and item.card is not None:
            # By the *whole* card's name (CR 709.2: it is one card): a split
            # card's spell is its half, under the half's name, and counting
            # that would read a suspended Assault as an Assault // Battery
            # vanishing and an "Assault" appearing. Every other zone holds the
            # whole card, so a half found *there* — a card that left the stack
            # without becoming whole again (CR 709.4) — is counted under the
            # half's name and is reported as exactly that leak.
            counter[whole_card(item.card).name] += 1
    return counter


def _assert_expected(
    card: CardDefinition,
    before: tuple[PlayerState, PlayerState],
    after: tuple[PlayerState, PlayerState],
    caster_index: int,
    target_index: int,
    named_a_permanent: bool = False,
) -> str | None:
    """What each card of the decklist above is expected to have done.

    *named_a_permanent* is whether the cast named an object rather than a
    seat. "Any target" is a player **or** a permanent, and the Bolt's check
    below is about the player: aimed at a creature it deals that player none.

    **These card names stay.** The engine's standing rule is that names live only
    in ``card_hooks.py``, and ``ai_policy``'s valuations were derived out for
    exactly that reason — but this is a *test oracle*, and a test oracle derived
    from the system under test asserts nothing. Measured: compile Lightning Bolt
    with its damage mis-parsed as 1, cast it, and the printed expectation below
    fires ("damage did not match prevention/cap effects") while the same check
    reading ``deal_damage``'s payload expects 1, sees 1, and passes. The numbers
    here are read off the printed card by a human on purpose; that independence
    is the whole value of the check.

    The decay this *is* exposed to is the decklist moving out from under it — an
    expectation for a card ``_build_deck`` no longer plays stops firing with
    nothing failing. ``tests/ai/test_ai_simulator.py`` holds the two in step.

    A cast naming no seat (Wheel and Deal announced as none) has nothing here.
    """
    if target_index is None:
        return None
    before_target = before[target_index]
    after_target = after[target_index]

    # **Both life checks read the per-turn records, not the life total**, and
    # that is the second time this oracle has lied rather than the engine: the
    # cast is a window other permanents act in too. "Whenever a player casts a
    # red spell, you may pay {1}. If you do, you gain 1 life" (Iron Star) gained
    # the Bolt's target a life in the same window, so the total fell by 2 and
    # the check said the Bolt dealt 2 — LEB's and 2ED's default seeded runs
    # exited 1 on it, and Ivory Cup did the same to Healing Salve in 6ED's.
    # Damage dealt and life gained are counted separately by the engine
    # (`damage_taken_this_turn`, `life_gained_this_turn`), so each check reads
    # the one its card prints. The damage is still compared exactly — nothing
    # else in these pools deals damage to the Bolt's target as it is cast — and
    # the gain as a floor, because a cast trigger adding life on top is the
    # very thing that fooled it.
    if card.name == "Lightning Bolt":
        # A Forcefield charge is not read: it answers an unblocked creature's
        # combat damage, never a Bolt's (``shields.make_capped_charge``).
        base_damage = 3
        expected_damage = (
            0 if named_a_permanent
            else max(0, base_damage - before_target.damage_prevention_pool)
        )
        actual_damage = (
            after_target.damage_taken_this_turn - before_target.damage_taken_this_turn
        )
        if actual_damage != expected_damage:
            return "Lightning Bolt damage did not match prevention/cap effects"

    if card.name == "Ancestral Recall":
        hand_delta = len(after_target.hand) - len(before_target.hand)
        cast_offset = 1 if target_index == caster_index else 0
        drawn = hand_delta + cast_offset
        if drawn != min(3, len(before_target.library)):
            return "Ancestral Recall did not draw expected cards"

    if card.name == "Healing Salve" and not named_a_permanent:
        life_gain = after_target.life_gained_this_turn - before_target.life_gained_this_turn
        prevention_gain = after_target.damage_prevention_pool - before_target.damage_prevention_pool
        if life_gain < 3 and prevention_gain != 3:
            return "Healing Salve did not apply expected life-gain or prevention mode"
    # CR 205.2b: a card has **every** type its line names, so Ornithopter is an
    # artifact card *and* a creature card. Both checks below used
    # ``card.primary_type``, which picks one of them by the order of a list --
    # and the Disenchant one was therefore wrong for every artifact creature on
    # the board, which is the class ``search_filters.card_has_type`` exists to
    # end. It reported a **false** issue at Mercadian Masques' Phase 5: Toymaker
    # ("Artifact Creature -- Spellshaper") answers "creature" to
    # ``primary_type``, so the destroyed permanent was in neither count and the
    # total looked unchanged. The engine had destroyed exactly the right
    # permanent; only the honesty check was lying, in the direction that costs
    # an investigation rather than a game.
    #
    # And a permanent's type is not its card's (CR 613.1d): Living Lands makes
    # every Forest a 1/1 creature that is still a land, so an Unsummon that
    # bounced one read as "did not remove one target creature" beside the
    # defender's printed creatures, counted alike before and after (kg5,
    # LEA+ATQ seed 70). The clones belong to no game and no layer reaches them,
    # so each is counted by the types the table gave it when it was snapshot
    # (``_snapped_type``).
    if card.name == "Unsummon" and any(
        _snapped_type(perm, "creature") for perm in before_target.battlefield
    ):
        creature_before = sum(
            1 for perm in before_target.battlefield if _snapped_type(perm, "creature")
        )
        creature_after = sum(
            1 for perm in after_target.battlefield if _snapped_type(perm, "creature")
        )
        if creature_after != creature_before - 1:
            return "Unsummon did not remove one target creature"

    def _artifact_or_enchantment(perm) -> bool:
        return _snapped_type(perm, "artifact") or _snapped_type(perm, "enchantment")

    if card.name == "Disenchant" and any(
        _artifact_or_enchantment(perm) for perm in before_target.battlefield
    ):
        ae_before = sum(1 for perm in before_target.battlefield if _artifact_or_enchantment(perm))
        ae_after = sum(1 for perm in after_target.battlefield if _artifact_or_enchantment(perm))
        if ae_after != ae_before - 1:
            return "Disenchant did not destroy one target artifact or enchantment"

    return None


#: The clone's metadata key holding the card types ``_assert_expected`` counts
#: by, as CR 613's layer 4 gave them to the permanent when it was snapshot.
_SNAPPED_TYPES = "_simulation_snapshot_types"
_COUNTED_TYPES = ("creature", "artifact", "enchantment")


def _layer_four_types(perm: Permanent) -> frozenset:
    """*perm*'s card types among ``_COUNTED_TYPES``, read through the layers
    while it is still on the table (``Permanent.is_creature``, ``has_type``)."""
    return frozenset(
        card_type for card_type in _COUNTED_TYPES
        if (perm.is_creature if card_type == "creature" else perm.has_type(card_type))
    )


def _snapped_type(perm: Permanent, card_type: str) -> bool:
    """Whether the snapshot *perm* is a clone from had *card_type* — its
    recorded layer-4 types (``_clone_player``), else its card's (CR 205.2b)."""
    snapped = perm.metadata.get(_SNAPPED_TYPES)
    if snapped is None:
        return card_has_type(perm.card, card_type)
    return card_type in snapped


def _clone_player(game: Game, player: PlayerState) -> PlayerState:
    return PlayerState(
        name=player.name,
        life=player.life,
        hand=list(player.hand),
        library=list(player.library),
        battlefield=[
            Permanent(
                card=perm.card,
                tapped=perm.tapped,
                power_bonus=perm.power_bonus,
                toughness_bonus=perm.toughness_bonus,
                regeneration_shield=perm.regeneration_shield,
                metadata={**perm.metadata, _SNAPPED_TYPES: _layer_four_types(perm)},
            )
            for perm in game.controlled_by(player)
        ],
        graveyard=list(player.graveyard),
        mana_pool=dict(player.mana_pool),
        damage_prevention_pool=player.damage_prevention_pool,
        combat_damage_cap_one_charges=player.combat_damage_cap_one_charges,
        has_no_max_hand_size=player.has_no_max_hand_size,
        can_spend_white_as_red=player.can_spend_white_as_red,
        # What `_assert_expected` reads instead of the life total — see there.
        damage_taken_this_turn=player.damage_taken_this_turn,
        life_gained_this_turn=player.life_gained_this_turn,
    )


def _snap(game: Game) -> tuple[PlayerState, PlayerState]:
    return (_clone_player(game, game.players[0]), _clone_player(game, game.players[1]))
