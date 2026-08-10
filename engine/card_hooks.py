"""Name-keyed registries for card-specific behavior.

Most cards should be handled generically by parse rules (engine/parsing) and
effect handlers (engine/handlers). When a card needs truly bespoke logic that
no generic instruction covers, register it here instead of hardcoding the card
name inside engine internals. This keeps per-card behavior in one place and
lets the card pool grow without touching the core rules code.

Cast triggers used to live here as two name-keyed registries, covering six
cards whose conditions the oracle compiler already understood — they were
name-keyed only because nothing dispatched "whenever a player casts a … spell"
and because "you may pay {N}" had no generic representation. Both gaps are
closed: the condition's colour is captured into its payload and dispatched by
``engine/events.py``, and the optional cost is an ordinary ``may`` instruction.
Prefer that route before adding a registry entry here.

Hook registries:
- ON_SELF_RESOLVED    — fired when the named instant/sorcery itself resolves
                        (keyed by the resolving card's own name), for bespoke
                        effects the single compiled instruction can't express.
- ON_SPELL_COUNTERED  — fired after the named card counters a spell (keyed by
                        the counterspell's own name).
- ON_LEAVE_BATTLEFIELD — fired when the named permanent is put into a graveyard
                        from the battlefield (keyed by the permanent's name).
- DRAW_STEP_MODIFIERS — the skip-your-draw-for-protection behavior (Island
                        Sanctuary), consumed by engine/phases/draw_step. Untap
                        restrictions and symmetric bonus draws left this file:
                        they are templates, derived from oracle text by
                        engine/untap_restrictions.py and
                        engine/draw_step_modifiers.py.
- ENCHANTED_LAND_TAPPED_FOR_MANA — bespoke behavior for the Aura on a land tapped
                        for mana (Kudzu), keyed by Aura name, consumed by
                        engine/mixins/turn_management.
Cost taxes left this file too: "<colour> spells cost {N} more to cast" is a
template, derived from oracle text by engine/cost_modifiers.py. So did the
land-tapping triggers (Mana Flare, Gauntlet of Might, Lifetap) — the compiler
now produces their conditions, so they are ordinary triggered abilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from .auras import attach_aura, detach_aura
from .land_types import end_land_type_change

if TYPE_CHECKING:
    from .game import Game
    from .game_types import StackItem
    from .models import CardDefinition, Permanent, PlayerState

SelfResolvedHook = Callable[["Game", "PlayerState", "CardDefinition", int, "int | None"], None]
SpellCounteredHook = Callable[["Game", "CardDefinition", "StackItem"], None]
LeaveBattlefieldHook = Callable[["Game", "PlayerState", "Permanent"], None]


def _guardian_angel(
    game: Game,
    caster: PlayerState,
    resolved_card: CardDefinition,
    target_player_index: int,
    target_permanent_index: int | None,
) -> None:
    # The first sentence (prevent the next X damage) resolves through the compiled
    # instruction. This hook adds the second sentence's granted ability: an emblem
    # the caster may activate ("pay {1}: prevent next 1 damage") until end of turn.
    # "That permanent or player" is the spell's original target, so the emblem
    # remembers it and never re-prompts on activation.
    caster.prevent_one_damage_emblems.append({
        "target_player_index": target_player_index,
        "target_permanent_index": target_permanent_index,
    })
    game.log.append(f"{caster.name} gains a Guardian Angel prevention emblem until end of turn")


ON_SELF_RESOLVED: dict[str, SelfResolvedHook] = {
    "Guardian Angel": _guardian_angel,
}


def _power_sink(game: Game, counter_card: CardDefinition, countered: StackItem) -> None:
    ctrl = game.players[countered.caster_index]
    for perm in game.controlled_by(countered.caster_index):
        if perm.card.primary_type == "land":
            game.become_tapped(perm)
    ctrl.mana_pool = {k: 0 for k in ctrl.mana_pool}
    game.log.append(f"{counter_card.name} tapped all lands and drained mana from {ctrl.name}")


ON_SPELL_COUNTERED: dict[str, SpellCounteredHook] = {
    "Power Sink": _power_sink,
}


def _cyclopean_tomb_leaves(game: Game, owner: PlayerState, permanent: Permanent) -> None:
    # "When this artifact is put into a graveyard from the battlefield, at the
    # beginning of each of your upkeeps for the rest of the game, remove all mire
    # counters from a land that a mire counter was put onto with this artifact but
    # that a mire counter has not been removed from with this artifact."
    #
    # Set up a rest-of-game obligation that removes the mire counter from one such
    # land per upkeep (drained in Game.resolve_upkeep). Only lands that are still
    # mired qualify — any whose counter was already removed are excluded.
    mired = permanent.metadata.get("mired_lands") or []
    remaining = [land for land in mired if land.metadata.get("mire_counter")]
    if not remaining:
        return
    controller_index = game.players.index(owner)
    game.mire_cleanup_obligations.append(
        {"controller_index": controller_index, "lands": remaining}
    )
    game.log.append(
        f"{permanent.card.name} left the battlefield; "
        f"{len(remaining)} mired land(s) will be freed over future upkeeps"
    )


def _consecrate_land_leaves(game: Game, owner: PlayerState, permanent: Permanent) -> None:
    # "Enchanted land has indestructible and can't be enchanted by other Auras."
    # Both are continuous effects from this Aura — when it leaves the battlefield
    # the enchanted land loses indestructibility and may again be enchanted.
    land = permanent.metadata.get("attached_to")
    if land is None:
        return
    land.metadata.pop("is_indestructible", None)
    land.metadata.pop("cant_be_enchanted_by_auras", None)
    detach_aura(permanent, land)


def _gaeas_liege_leaves(game: Game, owner: PlayerState, permanent: Permanent) -> None:
    # "{T}: Target land becomes a Forest until this creature leaves the
    # battlefield." When Gaea's Liege leaves, the lands it forested revert to
    # their printed type (CR 611.3 — the duration ends).
    # Dropping this creature's own contribution, not clearing the land's type:
    # the land goes back to whatever the *remaining* effects say it is, which is
    # what "the duration ended" means. Reading the stored type back to check it
    # was still Forest was the bookkeeping this replaces — and it was wrong
    # whenever something newer had made the land something else, since the
    # Liege's effect would then have gone on applying invisibly.
    reverted = 0
    for land in permanent.metadata.get("forested_lands", []) or []:
        if end_land_type_change(land, source=permanent):
            reverted += 1
    if reverted:
        game.log.append(
            f"{permanent.card.name} left the battlefield; {reverted} land(s) reverted from Forest"
        )
    game._refresh_dynamic_creatures()


def _revert_linked_steal_on_leave(game: Game, owner: PlayerState, permanent: Permanent) -> None:
    # A linked-duration "gain control for as long as you control this" steal
    # (Aladdin's artifact, Old Man of the Sea's creature) ends when its source
    # leaves the battlefield (CR 611.3), mirroring how Control Magic / Steal
    # Artifact revert when their Aura leaves. Old Man's other end conditions
    # (untaps / stolen power exceeds its own) are swept continuously in
    # game_ending.py.
    game.end_control_changes_from(permanent)


def _oubliette_leaves(game: Game, owner: PlayerState, permanent: Permanent) -> None:
    # "Target creature phases out until this enchantment leaves the
    # battlefield. Tap that creature as it phases in this way." Scoped
    # exile-and-return (not full CR 702.26 phasing) tracked on Oubliette
    # itself — the phased creature and any Auras/Equipment that phased out
    # with it return, tapped, when Oubliette leaves.
    phased = permanent.metadata.pop("phased_out_permanent", None)
    owner_index = permanent.metadata.pop("phased_out_owner_index", None)
    attachments = permanent.metadata.pop("phased_out_attachments", None) or []
    if phased is not None and isinstance(owner_index, int) and 0 <= owner_index < len(game.players):
        phased.tapped = True
        game.players[owner_index].battlefield.append(phased)
        game.log.append(
            f"{phased.card.name} phases back in, tapped ({permanent.card.name} left the battlefield)"
        )
    for seat, attached_perm in attachments:
        if 0 <= seat < len(game.players):
            game.players[seat].battlefield.append(attached_perm)


ON_LEAVE_BATTLEFIELD: dict[str, LeaveBattlefieldHook] = {
    "Cyclopean Tomb": _cyclopean_tomb_leaves,
    "Consecrate Land": _consecrate_land_leaves,
    "Gaea's Liege": _gaeas_liege_leaves,
    "Aladdin": _revert_linked_steal_on_leave,
    "Old Man of the Sea": _revert_linked_steal_on_leave,
    "Oubliette": _oubliette_leaves,
}


# --------------------------------------------------------------------------
# Resolve-time trigger hooks
# --------------------------------------------------------------------------
# A triggered ability whose effect is a name-keyed hook is put on the stack like
# any other trigger. When it resolves, resolve_top_of_stack dispatches to
# TRIGGER_HOOKS[stack_item.hook_key], passing the StackItem; the handler reads
# stack_item.hook_event (captured when the trigger fired) and runs the effect.
# This is how the Rod/Cup/Sphere cycle and Verduran Enchantress raise their
# "you may pay {1} / draw a card" prompts at resolution rather than at fire time.

TriggerStackHook = Callable[["Game", "StackItem"], None]


def _resolve_optional_pay_trigger(game: Game, item: StackItem) -> None:
    """Resolve a deferred "you may pay {N}: gain life" / "you may draw a card"
    trigger (the color Rods, Verduran Enchantress). The pay/draw prompt is registered
    here — at resolution — so it appears only after the trigger leaves the stack,
    matching the Soul Net death-trigger behavior. A paid rider (Rods) is offered only
    when the controller can actually pay the {N}; a free rider (Verduran's draw) is
    always offered."""
    ev = item.hook_event or {}
    player_index = ev.get("player_index")
    if player_index is None or not (0 <= player_index < len(game.players)):
        return
    cost = int(ev.get("cost", 0))
    if cost > 0 and not game._player_can_pay_generic(game.players[player_index], cost):
        return
    entry: dict = {
        "card_name": ev["card_name"],
        "cost": cost,
        "life": int(ev.get("life", 0)),
    }
    if "draw" in ev:
        entry["draw"] = ev["draw"]
    if "prompt" in ev:
        entry["prompt"] = ev["prompt"]
    game.arm_pending_choice("optional_pay", player_index, **entry)


# hook_key → resolver.
TRIGGER_HOOKS: dict[str, TriggerStackHook] = {
    "optional_pay": _resolve_optional_pay_trigger,
}


# --------------------------------------------------------------------------
# Untap-step restrictions (CR 502) — moved out
# --------------------------------------------------------------------------
# Stasis, Winter Orb, Smoke, Meekstone and Magnetic Mountain used to be five
# name-keyed UntapRestriction entries here. Their wordings are templates, so
# the restriction is now derived from oracle text in
# engine/untap_restrictions.py and a card printed with one of those templates
# needs no registration at all.


# --------------------------------------------------------------------------
# Untapped artifact protectors
# --------------------------------------------------------------------------
# Guardian Beast: "As long as this creature is untapped, noncreature artifacts
# you control can't be enchanted, have indestructible, and other players
# can't gain control of them." Checked by
# effects.py:_untapped_artifact_protector_active at each relevant site
# (destroy, enchant-target legality, control-change legality) rather than
# precomputed, since the protection tracks the source's tapped state.

UNTAPPED_ARTIFACT_PROTECTORS: frozenset[str] = frozenset({"Guardian Beast"})


# --------------------------------------------------------------------------
# Top-of-library discard replacements — moved out
# --------------------------------------------------------------------------
# Library of Leng was a name-keyed frozenset here. It is now a text-keyed
# `discard` replacement in engine/replacements.py, offering the optional
# destination as a ReplacementChoice.


# --------------------------------------------------------------------------
# Draw-step modifiers (CR 504)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class DrawStepModifier:
    """Draw-step behavior granted by a permanent.

    optional_skip_grants_protection -- its controller may skip their draw to
                  gain "attack only me with flyers" protection (Island Sanctuary)
    """

    optional_skip_grants_protection: bool = False


# Howling Mine's "that player draws an additional card" moved out to
# engine/draw_step_modifiers.py: it is a template a long line of cards
# reprints, so it is derived from oracle text instead of registered here.
# Island Sanctuary stays because the quality it grants protection against
# ("creatures with flying and/or islandwalk") is specific to the card — until
# a second card grants a different quality there is nothing to generalize.
DRAW_STEP_MODIFIERS: dict[str, DrawStepModifier] = {
    "Island Sanctuary": DrawStepModifier(optional_skip_grants_protection=True),
}


# --------------------------------------------------------------------------
# Land-tapping triggers — moved out
# --------------------------------------------------------------------------
# Mana Flare, Gauntlet of Might and Lifetap were three name-keyed entries here,
# across two registries (MANA_PRODUCTION_MODIFIERS and ON_BECOMES_TAPPED). All
# three are templates the compiler now reads:
#
#   "Whenever a <type> [an opponent controls] becomes tapped, …" compiles to a
#   `permanent_becomes_tapped` condition carrying the type and the controller
#   scope as payload, dispatched by engine/events.py.
#   "Whenever a [<land type>] is tapped for mana, <player> adds …" compiles to
#   `land_tapped_for_mana` plus an `add_mana_for_tapped_land` instruction,
#   resolved inline by Game.tap_land_for_mana (CR 605.4a — a triggered mana
#   ability never uses the stack).
#
# A card printed with either template needs no registration at all.


# --------------------------------------------------------------------------
# Enchanted-land "when tapped for mana" bespoke effects
# --------------------------------------------------------------------------
# Fired for the Aura enchanting a land that was just tapped for mana, when the
# Aura needs behavior the generic paths can't express — beyond the
# enchanted_land_tapped trigger (Psychic Venom) and the "adds an additional"
# mana clause (Wild Growth) both handled inline in tap_land_for_mana. Keyed by
# Aura name. Signature: (game, controller_index, land, land_index, aura,
# reattach_index, defer_choice).

EnchantedLandTappedHook = Callable[
    ["Game", int, "Permanent", int, "Permanent", "int | None", bool], None
]


def _kudzu_on_land_tapped(
    game: Game,
    controller_index: int,
    land: Permanent,
    land_index: int,
    aura: Permanent,
    reattach_index: int | None,
    defer_choice: bool,
) -> None:
    """Kudzu: "Whenever enchanted land is tapped for mana, destroy that land.
    That land's controller may attach Kudzu to a land of their choice." The
    reattach target comes from ``reattach_index``; with no explicit choice a
    human controller defers to an interactive prompt (``pending_kudzu_reattach``,
    resolved by ``confirm_kudzu_reattach``), while AI/headless play deterministically
    takes the first other land."""
    player = game.players[controller_index]
    player.battlefield.pop(land_index)
    player.graveyard.append(land.card)
    aura.metadata.pop("attached_to", None)
    detach_aura(aura, land)
    game.log.append(f"Kudzu destroyed {land.card.name}")
    new_land = None
    if (
        isinstance(reattach_index, int)
        and 0 <= reattach_index < len(player.battlefield)
        and player.battlefield[reattach_index].card.primary_type == "land"
    ):
        new_land = player.battlefield[reattach_index]
    # A controller who is being asked picks the land to re-enchant: defer when no
    # choice was supplied and there is a land to move to. Headless/AI play keeps
    # the deterministic "first other land" default below.
    if new_land is None and defer_choice and any(
        p.card.primary_type == "land" for p in game.controlled_by(controller_index)
    ):
        game.arm_pending_choice("kudzu_reattach", controller_index, aura=aura)
        return
    if new_land is None:
        new_land = next(
            (p for p in game.controlled_by(controller_index) if p.card.primary_type == "land"),
            None,
        )
    if new_land is not None:
        attach_aura(aura, new_land)
        game.log.append(f"Kudzu attached to {new_land.card.name}")


ENCHANTED_LAND_TAPPED_FOR_MANA: dict[str, EnchantedLandTappedHook] = {
    "Kudzu": _kudzu_on_land_tapped,
}


# --------------------------------------------------------------------------
# Cost modifiers — moved out
# --------------------------------------------------------------------------
# Gloom was two hand-written functions keyed by name. "<colour> spells cost
# {N} more to cast" is a template Magic reprints constantly, so the tax is
# now derived from oracle text in engine/cost_modifiers.py.
