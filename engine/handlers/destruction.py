"""Destroying, sacrificing or exiling **one** object, or a chosen list of them.

The handler side of ``engine/grammar/lowering/destruction.py`` and its
neighbours: a target (``destroy_target_permanent``), the source itself, a
permanent a trigger or a delayed ability bound, a block-pair partner, an event's
subject, an attached permanent, a recorded choice, and the tolls that destroy or
sacrifice what a player declines to pay for. Chaos Orb's flip is here because
what it destroys is whatever it touches, one permanent at a time.

A sweep — "destroy all …", every permanent a noun phrase names — is
``destroy_sweeps.py``'s, split out at the 2,000-line cap's split round.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..dexterity import flip_lands_on
from ..models import Permanent, PlayerState
from ..destruction_events import (begin_destruction_hold,
                                  end_destruction_hold,
                                  mark_delayed_destruction)
from ..oracle_types import (ATTACHED_PERMANENT_CONTROLLER,
                            LAST_TARGET_CONTROLLER,
                            LAST_TARGET_NAME,
                            LAST_TARGET_OWNER,
                            OracleInstruction, PER_OBJECT_SEAT_RECORDS,
                            named_no_target)
from ..resumption import run_resumable
from ._filters import permanent_matches_filter
from ._targets import (one_recorded_permanent_id, attached_host,
                       block_pair_permanents, frozen_that_player_seat,
                       resolve_role_permanent, resolve_target_permanent,
                       resolve_target_permanents)
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext


def _record_destroyed_this_way(
    context: OracleExecutionContext,
    died: list[Permanent],
    controllers: dict[int, int],
) -> None:
    """What a destroy step leaves behind for the sentence after it.

    Three records, written together because they are three questions about one
    step and a branch that answers two of them is a producer the lowering may
    cite and the handler never wrote -- which reads back as zero with nothing
    failing. ``destroy_target_permanent`` has four branches and the singular one
    already carries that lesson in its own comment; this is the same lesson
    taken one record further.

    *controllers* is ``{permanent_id: seat}`` collected **before** the
    destruction (CR 608.2h / CR 400.7): "the number of artifacts **they
    controlled** that were put into a graveyard this way" (Builder's Bane) asks
    about permanents that are cards in a graveyard by the time it is read, and
    under a control-change effect that seat was never the owner either.
    """
    context.results["destroyed_this_way_objects"] = died
    context.results["destroyed_this_way"] = len(died)
    context.results[PER_OBJECT_SEAT_RECORDS["controller"]] = {
        perm.permanent_id: controllers[perm.permanent_id]
        for perm in died
        if perm.permanent_id in controllers
    }


@effect_handler("destroy_target_permanent")
def destroy_target_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # Function-level, like every other `..targeting` reader in `handlers/`:
    # that module reads the cast-cost tables, which read the filters, which
    # read this package.
    from ..targeting import payload_own_role

    target = context.target
    card = context.card
    source_permanent = context.source_permanent
    # "…destroy target nonartifact creature that player controls **of their
    # choice**." (The Abyss.) The victim was picked by another seat as this
    # resolution ran, so it comes out of the scratchpad rather than off the
    # ability's own target — the same ``permanents_from`` reading
    # ``steal_target_linked_to_source`` makes of the very same producer, which
    # records one id rather than a list.
    #
    # Nothing recorded is a legal outcome, not an error: the seat had no
    # creature, or the one they chose left before the destroy step ran
    # (CR 400.7 — what comes back is a new object).
    recorded_key = instruction.payload.get("permanents_from")
    if recorded_key is not None:
        permanent_id = one_recorded_permanent_id(context, recorded_key)
        victim = (
            game.permanent_by_id(permanent_id) if permanent_id is not None else None
        )
        died: list[Permanent] = []
        controllers: dict[int, int] = {}
        if victim is not None:
            seat = game.controller_index_of(victim)
            if seat is not None:
                controllers[victim.permanent_id] = seat
                died = game._destroy_swept_permanents(
                    game.players[seat],
                    lambda candidate, chosen=victim: candidate is chosen,
                    allow_regeneration=not instruction.payload.get(
                        "bypass_regeneration"
                    ),
                )
        _record_destroyed_this_way(context, died, controllers)
        game.log.append(
            f"{card.name} destroyed " + ", ".join(p.card.name for p in died)
            if died else f"{card.name}: nothing to destroy"
        )
        return True, "resolved"
    # "Destroy X target snow lands." (Avalanche.) The several-targets
    # description says a *list* was collected, so each slot resolves strictly
    # and one that has left is dropped rather than slid onto another
    # (CR 608.2b) — the same reading `untap_target_permanent` takes for
    # Candelabra of Tawnos, through the same helper.
    targets_desc = instruction.payload.get("targets") or {}
    if (
        isinstance(targets_desc, dict)
        and targets_desc.get("kind") == "roles"
        # **…and the announcement is this instruction's whole business.** A
        # roles description reaches a handler in two shapes, and they mean
        # opposite things. Fumarole's one instruction *is* the announcement and
        # spends every slot, which the branch below does. Crooked Scales' two
        # slots are announced together and spent a step at a time — the same
        # ordered list on both steps, each naming its own slot with ``role``
        # (``grammar/lowering/_roles.describe_sequence_target_roles``) — and by
        # the time such a step runs, ``control_flow._role_scoped`` has already
        # put *its* object in the ordinary target channels. So the singular
        # path below is the right one, and taking this branch instead destroyed
        # nothing at all: the scoped context carries one id where
        # ``resolve_role_permanent`` reads a list.
        and payload_own_role(instruction.payload) is None
    ):
        # "Destroy target creature **and target land**." (Fumarole.) Several
        # targeted phrases of one announcement, each with its own noun — so each
        # slot is resolved *by its role* rather than by position, through the
        # same ``targets`` description the picker and the cast gate read.
        #
        # Per role rather than all-or-nothing: CR 608.2b removes the spell from
        # the stack only when **every** target is illegal (which
        # ``legality_resolution.illegal_targets_refusal`` answers above this), and an
        # illegal one among several is simply skipped. So a land that left is
        # not destroyed and the creature still is.
        #
        # The filter is re-asked at resolution for the reason the picker asked
        # it at announcement: a creature that became a land between the two is
        # no longer the thing the caster chose for that role.
        from ..subject_filters import subject_matches

        observer = (
            game.players.index(context.caster) if context.caster in game.players
            else None
        )
        died: list[Permanent] = []
        controllers: dict[int, int] = {}
        for role in targets_desc.get("roles") or ():
            victim = resolve_role_permanent(
                game, context, instruction.payload, role.get("role")
            )
            if victim is None or not game.is_on_battlefield(victim):
                continue
            if not subject_matches(
                game, victim, role.get("filter") or {},
                observer=observer, source=source_permanent,
            ):
                continue
            seat = game.controller_index_of(victim)
            if seat is None:
                continue
            controllers[victim.permanent_id] = seat
            died.extend(game._destroy_swept_permanents(
                game.players[seat],
                lambda candidate, chosen=victim: candidate is chosen,
                allow_regeneration=not instruction.payload.get("bypass_regeneration"),
            ))
        _record_destroyed_this_way(context, died, controllers)
        game.log.append(
            f"{card.name} destroyed " + ", ".join(p.card.name for p in died)
            if died else f"{card.name}: nothing to destroy"
        )
        return True, "resolved"
    if isinstance(targets_desc, dict) and targets_desc.get("count") not in (None, 1):
        from ..subject_filters import subject_matches

        filters = {
            key: value for key, value in instruction.payload.items()
            if key not in ("targets", "bypass_regeneration")
        }
        observer = (
            game.players.index(context.caster) if context.caster in game.players
            else None
        )
        # "up to two target creatures **that player** controls" (Fatal Lore).
        # `subject_matches` refuses this key outright and says why — it names a
        # seat the *announcement* picked, not one a board read can make — and a
        # refusal here is not a narrowing dropped, it is **every** target
        # rejected: the branch would destroy nothing and log itself resolved.
        # Stripped and asked as its own question, exactly as the singular branch
        # below and the sweep (``destroy_sweeps.destroy_all_matching``) already
        # do.
        that_player_seat: int | None = None
        if filters.get("controller") == "that_player":
            that_player_seat = frozen_that_player_seat(game, context)
            if that_player_seat is None:
                game.log.append(
                    f"{card.name}: no player for 'that player' to name"
                )
                return True, "resolved"
            filters = {k: v for k, v in filters.items() if k != "controller"}
        chosen = resolve_target_permanents(
            game, context,
            predicate=lambda perm: (
                (
                    that_player_seat is None
                    or game.controller_index_of(perm) == that_player_seat
                )
                and subject_matches(
                    game, perm, filters,
                    observer=observer, source=source_permanent,
                )
            ),
        )
        died: list[Permanent] = []
        controllers: dict[int, int] = {}
        for perm in chosen:
            seat = game.controller_index_of(perm)
            if seat is None:
                continue
            controllers[perm.permanent_id] = seat
            died.extend(game._destroy_swept_permanents(
                game.players[seat],
                lambda candidate, victim=perm: candidate is victim,
                allow_regeneration=not instruction.payload.get("bypass_regeneration"),
            ))
        # What a later sentence of the same spell counts. Recorded under the
        # key the sweep uses, because "the number of Mountains put into a
        # graveyard this way" is the same question whichever branch destroyed
        # them.
        _record_destroyed_this_way(context, died, controllers)
        game.log.append(
            f"{card.name} destroyed " + ", ".join(p.card.name for p in died)
            if died else f"{card.name}: nothing to destroy"
        )
        return True, "resolved"
    # "…destroy up to one target artifact or enchantment **that player**
    # controls." (Feline Sovereign.) A seat the firing event picked — whoever
    # the Cats damaged — and not one any read of the board can name, so
    # ``subject_matches`` refuses it outright and the resolution holding the
    # trigger's context is what answers. Answered as *whose battlefield* rather
    # than as a filter key, because that is what the resolver below scans: the
    # keyword arguments it takes are the filter, and ``controller`` is not among
    # them, so the phrase was simply dropped and the destroy landed on
    # ``context.target`` — the default opposing seat, which is the right player
    # in a two-player game by coincidence and the wrong one the moment there are
    # three.
    #
    # An unresolvable seat ends the resolution, for the reason the sweep beside
    # this one ends: a dropped seat is not an ability that destroys less, it is
    # one that destroys somebody else's permanent.
    singular_that_player: int | None = None
    if instruction.payload.get("controller") == "that_player":
        seat = frozen_that_player_seat(game, context)
        if seat is None:
            game.log.append(f"{card.name}: no player for 'that player' to name")
            return True, "resolved"
        target = game.players[seat]
        # Handed to the filter as well as used to pick the battlefield, because
        # the key stays in the payload and ``subject_matches`` refuses it
        # outright without a seat. Two readings of one frozen fact rather than
        # one reading and one silent drop.
        singular_that_player = seat
    # "Destroy **up to one** target artifact or enchantment…" announced naming
    # nobody (CR 601.2c). The branch below this one hands an unnamed target to
    # ``_destroy_target_permanent``, whose scan takes the first permanent the
    # noun phrase describes — it is this handler's own fall-through, beside
    # ``resolve_target_permanent``'s rather than through it, so the record is
    # read here too. Feline Sovereign destroyed a shrouded artifact that way:
    # the picker offered nothing, the ability went on the stack with no
    # target, and the scan found the artifact the picker had refused.
    if named_no_target(context.choices):
        _record_destroyed_this_way(context, [], {})
        game.log.append(f"{card.name}: no target was named")
        return True, "resolved"
    # A later step of the same resolution may read the victim's controller
    # ("Destroy target creature. Its controller loses 2 life." — Liliana,
    # Death Mage), and by then the permanent is gone — record it now
    # (CR 608.2h, last-known information).
    chosen_index = context.target_permanent_index
    # **Was a target named at all** — by slot *or* by stable id. The gate used
    # to ask only about the slot, which is a gate standing in for a question it
    # does not ask: a caller that names its target the way CLAUDE.md asks for,
    # by `permanent_id` alone, left `chosen_index` None and skipped this whole
    # block — so `its_mana_value`, `destroyed_target` and the P/T records were
    # never written and every rider reading them read a zero. Divine Offering
    # gained 5 life for an artifact named by slot and **0** for the same
    # artifact named by id, with nothing failing. The web layer sends both
    # (`web/actions.py`), which is why the app never showed it — the same
    # "one caller's spelling enforced, another's silently not" the CR 702.16b
    # gate in `mixins/stack/casting.py` records about itself.
    singular_seat: int | None = None
    named_id = context.target_permanent_id
    if isinstance(named_id, list):
        named_id = next((pid for pid in named_id if isinstance(pid, int)), None)
    if isinstance(chosen_index, int) or isinstance(named_id, int):
        # Resolved **once**, by id, and the slot re-derived from what came back.
        # This site used to resolve twice: `chosen_permanent` here for the
        # last-known-information records, and the raw index again inside
        # `_destroy_target_permanent`. Both followed the slot when the id no
        # longer answered, so an ability whose target left destroyed whichever
        # permanent had slid into its place -- Royal Assassin killing a creature
        # nobody named, and the "its controller" / "its mana value" riders then
        # describing that creature as though it had been chosen.
        #
        # Strictly, with no fallback scan: an index was supplied, so this is a
        # named target, and CR 608.2b's answer to a target that has left is that
        # nothing happens -- not that the next legal permanent is substituted.
        # `predicate` is every permanent because the printed noun phrase is
        # `_destroy_target_permanent`'s own `_is_legal_target`; the resolver's
        # creature default would refuse "destroy target artifact" outright.
        #
        # Spells never reach this with a departed target -- `illegal_targets_refusal`
        # removes them from the stack first -- so what changes here is the 28
        # activated and triggered abilities that gate has always declined.
        victim = resolve_target_permanent(
            game, context, player=target,
            predicate=lambda p: True, fallback_players=(),
        )
        if victim is None:
            game.log.append(f"{card.name}: its target is gone (608.2b)")
            return True, "resolved"
        chosen_index = game.battlefield_index_of(victim)
        seat = game.controller_index_of(victim)
        # "Destroy target creature. **Its owner** gains 4 life." (Path of
        # Peace.) CR 108.3's seat, which is not CR 109.5's: a stolen creature
        # is destroyed by its controller's opponent and the *owner* is the one
        # the card heals. Written here beside the controller and for the same
        # reason — one moment later the permanent is a card in a graveyard
        # (CR 608.2h) — and through the same accessor `base_controller_index`
        # that CR 108.3 ownership is read off everywhere else in the engine.
        owner_seat = game.owner_index_of(victim)
        if owner_seat is not None:
            context.results[LAST_TARGET_OWNER] = owner_seat
        # "Destroy target land **and all other lands with the same name as that
        # land**." (Wake of Destruction.) The sweep behind this step compares
        # against a permanent this step is about to destroy, so the name is
        # frozen here beside the two seats and for their reason — CR 608.2h,
        # last-known information. ``effective_card`` for CR 707.2: a Clone of a
        # land is a land with that land's name and goes with the rest of them.
        context.results[LAST_TARGET_NAME] = victim.effective_card.name
        if seat is not None:
            context.results[LAST_TARGET_CONTROLLER] = seat
            # The same seat under the per-object key, so a sentence counting
            # "the artifacts **they** controlled" reaches it whichever branch
            # of this handler ran. Read here rather than after the destroy for
            # this block's own stated reason: by then the permanent is a card
            # in a graveyard with no controller at all (CR 400.7).
            singular_seat = seat
        # "You gain life equal to **its** mana value." (Divine Offering.)
        # Recorded here, before the destruction, for two reasons: the
        # permanent is gone by the time the next step runs (CR 608.2h), and
        # the words name the object rather than the outcome — a regenerated
        # or indestructible artifact still has a mana value to gain.
        # Through `effective_card` so a copy effect's cost is the one read
        # (CR 707.2), which is the same reading Crumble's fused kind takes.
        context.results["its_mana_value"] = int(victim.effective_card.cmc or 0)
        # "**If that land was a snow land**, …" (Icequake, Thermokarst).
        # The permanent itself, recorded here for the same reason its mana
        # value is and one moment earlier than it would survive: after the
        # destroy it is a card in a graveyard with no characteristics at all
        # (CR 613.1), so a condition asking what it *was* has to read the
        # object it was (CR 608.2h). The `Permanent` keeps its state after
        # leaving the battlefield, which is exactly what last-known
        # information means.
        context.results["destroyed_target"] = victim
        # "…Its power is equal to **that creature's power** and its toughness is
        # equal to **that creature's toughness**." (Broken Visage.) Frozen here
        # for the mana value's reason and one step more urgently: P/T is
        # *computed* (CR 613), and a card in a graveyard has no computed
        # characteristics at all — so read after the destroy both numbers would
        # be the printed ones, or nothing. The effective values, so a pumped or
        # counter-laden creature is worth what it was worth on the battlefield.
        context.results["its_power"] = max(0, int(victim.effective_power))
        context.results["its_toughness"] = max(0, int(victim.effective_toughness))
    # One reading of "what does this destroy name", shared with the picker and
    # the cast gate. Imported here rather than at module scope for the reason
    # `handlers/stack.py` does the same: `targeting` reads `subject_filters`,
    # which reads this package.
    from ..targeting import destroy_subject_filter

    # The **whole** printed noun phrase, through the same reader the picker and
    # the cast gate use. Nine keys were named here by hand, which made every
    # other key the lowering can emit a narrowing this resolution ignored:
    # "with islandwalk" (Merfolk Assassin), "without flying" (Pit Trap), "you
    # own" (Despotic Scepter), "blocking this creature" (Urborg Panther).
    destroyed = game._destroy_target_permanent(
        target,
        described=destroy_subject_filter(instruction.payload),
        target_permanent_index=chosen_index,
        bypass_regeneration=instruction.payload.get("bypass_regeneration", False),
        observer=(
            game.players.index(context.caster) if context.caster in game.players
            else None
        ),
        source=source_permanent,
        defending=game.defending_player_index_now(),
        that_player=singular_that_player,
    )
    # The record every other branch of this handler keeps, and this one did
    # not: "the number of Mountains put into a graveyard this way" is the same
    # question whichever branch destroyed them, and `_PRODUCES` declares the
    # key for the *kind* — so a branch that skipped it was a producer the
    # lowering could cite and a record the handler never wrote, which reads as
    # zero with nothing failing. Derived from the list so the two records
    # cannot disagree; a regenerated or indestructible target is in neither
    # (CR 701.8c: a replaced destruction is not a death).
    died = [destroyed] if destroyed is not None else []
    _record_destroyed_this_way(
        context, died,
        {destroyed.permanent_id: singular_seat}
        if destroyed is not None and singular_seat is not None else {},
    )
    if destroyed is not None:
        if source_permanent is not None:
            game.log.append(f"{card.name} destroyed {destroyed.card.name}")
        else:
            game.log.append(f"Destroyed {destroyed.card.name}")
    else:
        game.log.append("No valid target permanent found")
    return True, "resolved"


@effect_handler("chaos_orb_flip")
def chaos_orb_flip(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    source_permanent = context.source_permanent
    # Collect all permanents from all players except Chaos Orb itself
    candidates: list[tuple[PlayerState, Permanent]] = [
        (game.players[seat], perm)
        for seat, perm in game.permanents_with_controller()
        if perm is not source_permanent
    ]
    # The flip itself is a CR 100.7 physical action the engine cannot perform;
    # ``engine.dexterity`` is the one place that substitution is made and
    # explained. Only the count is this card's ("up to two permanents").
    chosen = flip_lands_on(candidates, maximum=2)
    # "…**destroy** all nontoken permanents it touches. Then **destroy** this
    # artifact." Two destructions, through the destroy seam every sibling here
    # uses. They were a bare removal and a move to the graveyard — one of the
    # two destructions in the engine that went round the seam — so the Orb
    # destroyed an indestructible permanent, destroyed a creature through its
    # regeneration shield (CR 702.12b, CR 701.8c), and nothing watching a
    # destruction heard of either.
    for victim_player, victim_perm in chosen:
        if game._destroy_swept_permanents(
            victim_player, lambda perm, victim=victim_perm: perm is victim
        ):
            game.log.append(f"Chaos Orb flip destroyed {victim_perm.card.name}")
        else:
            game.log.append(
                f"Chaos Orb flip touched {victim_perm.card.name}, which was "
                "not destroyed"
            )
    # "Then destroy this artifact."
    if source_permanent is not None:
        holder = game.controller_index_of(source_permanent)
        if holder is not None and game._destroy_swept_permanents(
            game.players[holder], lambda perm: perm is source_permanent
        ):
            game.log.append("Chaos Orb was destroyed after flip")
    return True, "resolved"


@effect_handler("sacrifice_expansion_permanents")
def sacrifice_expansion_permanents(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Golgothian Sylex: "Each nontoken permanent with a name originally printed
    in the Antiquities expansion is sacrificed by its controller."

    The set is a code on the payload, resolved from the manifest when the line
    was parsed — so this is the same effect for any set, which is what Homelands'
    Apocalypse Chime is.

    "Originally printed" is ``CardDefinition.original_printing`` — ``printings[0]``,
    the first set the card appeared in — and *not* whichever set happened to load
    first. That distinction is the whole content of the word "originally": nineteen
    Antiquities cards were reprinted in Revised, and reading the loaded set code
    would miss every one of them. It is the same read City in a Bottle makes.

    **Read off ``effective_card``, because CR 206.3b is a list of *names*.** The
    rule spells the set out as "those names are Amulet of Kroog, Argivian
    Archaeologist, …", so what the sweep asks is whether *this object's* name is
    one of them — and a copy's name is the name it copied (CR 707.2). A Copy
    Artifact copying Su-Chi is a permanent named Su-Chi and the Sylex takes it;
    reading the printed face asked where the physical card came from, which is a
    different question, and left it on the battlefield.

    The Sylex sacrifices itself: it is an Antiquities card and its own ability
    does not exempt it. Nothing here excludes the source, deliberately.
    """
    wanted = str(instruction.payload.get("set_code", "")).lower()
    if not wanted:
        return False, "no expansion named"

    doomed = [
        (seat, perm)
        for seat, perm in game.permanents_with_controller()
        if not perm.metadata.get("is_token")
        and perm.effective_card.original_printing.lower() == wanted
    ]
    for seat, perm in doomed:
        game._permanent_to_graveyard(game.players[seat], perm)
        game.log.append(f"{perm.card.name} sacrificed ({context.card.name})")
    game.remove_all_from_battlefield([perm for _seat, perm in doomed])
    return True, "resolved"


@effect_handler("arm_self_action_at_next_end_step")
def arm_self_action_at_next_end_step(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Destroy this artifact at the beginning of the next end step." (Rocket
    Launcher.) "Return this artifact to its owner's hand …" (Rakalite.)

    Creates a delayed triggered ability (CR 603.7) rather than doing anything
    now. The permanent is recorded by ``permanent_id``, so one that leaves and
    comes back is a new object (CR 400.7) and the ability that was waiting for
    the old one finds nothing — which is right: the delayed trigger names the
    object it was created for, not whatever is standing in its place.
    """
    source = context.source_permanent
    if str(instruction.payload.get("subject", "source")) == "bound":
        # "Destroy **it** at the beginning of the next end step." (Glyph of
        # Destruction.) The object the sentence in front of this one named,
        # which for a spell is the target it chose. Resolved here rather than at
        # compile time because the printed pronoun does not say which of the two
        # it is, and the fallback is the source — the reading every other
        # printing of this sentence has.
        #
        # Asked only when the resolution actually *names* something. With no
        # index and no id, `resolve_target_permanent` does not answer None - it
        # falls through to `pick_target_permanent`'s battlefield scan, and with
        # an always-true predicate that scan returns `context.target`'s first
        # permanent, which for a targetless activation is the **opponent's**.
        # Goblin Ski Patrol ("This creature gets +2/+0 and gains flying. Its
        # controller sacrifices it at the beginning of the next end step")
        # sacrificed whatever the opponent happened to have in slot 0 and kept
        # its own pump for good: the drawback never applied and an opponent's
        # permanent went with it. It is the only carrier of this payload that
        # names no target - Glyph of Destruction, Krovikan Elementalist,
        # Barbarian Guides and Celestial Sword all target, so all four keep the
        # reading above unchanged.
        names_a_target = (
            context.target_permanent_index is not None
            or context.target_permanent_id is not None
        )
        chosen = resolve_target_permanent(
            game, context,
            predicate=lambda perm: True,
            fallback_on_invalid_choice=False,
        ) if names_a_target else None
        if chosen is not None:
            source = chosen
    if source is None:
        return False, "ability not implemented"
    # Onto the flags the end step's existing delayed-removal sweep already
    # reads. Rocket Launcher's self-destruction has been marked this way since
    # before the grammar could read its sentence — the damage handler set it
    # from a payload flag — so writing a second queue beside it would have been
    # two mechanisms for one rule, and the *older* one is the one every other
    # delayed removal in the engine (Dragon Whelp, Berserk) already uses.
    # "**Sacrifice** it at the beginning of the next end step." (Krovikan
    # Elementalist, Celestial Sword.) Its own flag rather than the destruction
    # one, because the end step's sweep already reads both and its comment says
    # why keeping them apart is a rules feature: a sacrifice is not a
    # destruction (CR 701.21a), so no replacement effect applies to it.
    action = str(instruction.payload.get("self_action", "destroy"))
    key = {
        "bounce": "bounce_at_next_end_step",
        "sacrifice": "sacrifice_at_next_end_step",
    }.get(action, "destroy_at_next_end_step")
    if key == "destroy_at_next_end_step":
        # A destruction, so the mark carries who set it up (CR 603.7d–e) —
        # the end step that carries it out has no spell or ability resolving.
        mark_delayed_destruction(game, source, key)
    else:
        source.metadata[key] = True
    return True, "resolved"


@effect_handler("destroy_self")
def destroy_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"**Destroy this Aura.**" (Imprison.)

    The twin of ``sacrifice_self``: the sentence names the ability's own
    source, so nothing is chosen and nothing is looked up. Destruction rather
    than sacrifice because the two are different events — a destroy is a
    CR 701.8 action a regeneration shield or indestructible can answer, and a
    sacrifice (CR 701.21) is neither — and a card that prints one must not
    perform the other.

    Through ``_destroy_swept_permanents``, the same seam
    ``destroy_attached_permanent`` beside it uses, so regeneration, the
    indestructible check and the graveyard move behave as they do for a
    targeted destroy. A source already gone destroys nothing, which is
    CR 608.2b doing as much as possible rather than a failure.
    """
    source = context.source_permanent
    seat = game.controller_index_of(source) if source is not None else None
    if source is None or seat is None:
        game.log.append(f"{context.card.name}: nothing left to destroy")
        return True, "resolved"
    destroyed = game._destroy_swept_permanents(
        game.players[seat],
        lambda candidate: candidate is source,
        allow_regeneration=not instruction.payload.get("bypass_regeneration"),
    )
    if destroyed:
        game.log.append(f"{context.card.name} was destroyed")
    return True, "resolved"


@effect_handler("sacrifice_attached_permanent")
def sacrifice_attached_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…unless they sacrifice **that artifact**." (Curse Artifact.)

    The permanent read off the source's own attachment, exactly as
    ``destroy_attached_permanent`` below reads it and for the same reason: the
    trigger's condition named it ("the upkeep of enchanted artifact's
    controller"), so the sentence chooses nothing and there is nothing for a
    picker to have offered.

    Through ``Game.sacrifice_permanent``, never a hand-rolled removal — that is
    the one seam a sacrifice passes through (ownership, tokens, replacements,
    Aura teardown, the death count and the dies-triggers all hang off it), and
    a second spelling of it is how seven of those were skipped before it
    existed.

    CR 701.21a: only the permanent's controller may sacrifice it, and that is
    who the offer was made to — ``handlers/control_flow._action_is_takeable``
    withdraws the offer when the Aura has come unattached, so reaching here
    with nothing attached means the offer was never narrowed and the right
    answer is to do nothing rather than to charge a cost that cannot be paid.
    """
    source = context.source_permanent
    # Last-known information (CR 608.2h), for ``destroy_attached_permanent``'s
    # reason: a Slow Motion destroyed with its upkeep trigger on the stack still
    # names the creature it was on, and the trigger still offers "sacrifice
    # that creature unless you pay {2}". The offer side
    # (``control_flow._action_is_takeable``) reads the same helper.
    attached = attached_host(game, source)
    if attached is None:
        game.log.append(f"{context.card.name}: nothing attached to sacrifice")
        return True, "resolved"
    game.sacrifice_permanent(attached)
    game.log.append(f"{context.card.name}: {attached.card.name} was sacrificed")
    # Every handler answers ``(supported, detail)``. This one fell off the end
    # and answered None, which the dispatcher hands to whatever unpacks it.
    return True, "resolved"


@effect_handler("destroy_bound_permanent")
def destroy_bound_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"When this artifact leaves the battlefield this turn, **destroy that
    creature**." (War Barge.)

    The victim is the object the creating ability bound (CR 603.7c), carried by
    id in the trigger's context — the creature War Barge's own activation
    targeted, which is *not* the object the delay watched. Nothing is chosen
    here and nothing is addressed by index: an id is the identity a permanent
    keeps across everything that renumbers a battlefield (CR 400.7).

    Through ``_destroy_swept_permanents``, the same seam ``destroy_self`` and
    ``destroy_attached_permanent`` beside it use, so the indestructible check
    and the graveyard move behave as they do for a targeted destroy — and "a
    creature destroyed this way can't be regenerated" is this handler's
    ``bypass_regeneration``, not a second reading of CR 701.19c.

    A creature already gone is destroyed by nothing, which is CR 608.2b doing
    as much as it can rather than a failure.
    """
    victim = game.permanent_by_id(
        (context.trigger_context or {}).get("bound_permanent_id")
    )
    seat = game.controller_index_of(victim) if victim is not None else None
    if victim is None or seat is None:
        game.log.append(f"{context.card.name}: the creature it named is gone")
        return True, "resolved"
    destroyed = game._destroy_swept_permanents(
        game.players[seat],
        lambda candidate: candidate is victim,
        allow_regeneration=not instruction.payload.get("bypass_regeneration"),
    )
    if destroyed:
        game.log.append(f"{context.card.name} destroyed {victim.card.name}")
    return True, "resolved"


@effect_handler("destroy_block_pair_partner")
def destroy_block_pair_partner(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Whenever a creature becomes blocked by a creature with lesser power,
    **destroy the blocking creature**." / "Whenever a creature blocks a creature
    with lesser power, **destroy the attacking creature**." (No Quarter.)

    The other half of the pair the firing was about, which is the referent
    ``block_pair_permanents`` already resolves for every block-pair effect in
    the engine — the pumps, the keyword grants and the end-of-combat destroy all
    read it, and this is the immediate destroy beside them.

    One handler for both printed roles, because the *event* is what says which
    creature the words name: the becomes-blocked announcement is about the
    attacker and its partner is the blocker, and the blocks announcement is the
    mirror. The lowering is what holds a role to its event
    (``ROLE_NAMES_BLOCK_PARTNER``), so nothing here has to know the word.

    Through ``_destroy_swept_permanents`` like every other destroy here, so
    regeneration and indestructibility behave as they do for a targeted one. A
    creature that has already left is destroyed by nothing, which is CR 608.2b
    doing as much as it can.
    """
    destroyed: list[str] = []
    for victim in block_pair_permanents(game, context):
        seat = game.controller_index_of(victim)
        if seat is None:
            continue
        destroyed.extend(
            perm.card.name
            for perm in game._destroy_swept_permanents(
                game.players[seat],
                lambda candidate, victim=victim: candidate is victim,
                allow_regeneration=not instruction.payload.get(
                    "bypass_regeneration"
                ),
            )
        )
    if destroyed:
        game.log.append(
            f"{context.card.name} destroyed {', '.join(destroyed)}"
        )
    else:
        game.log.append(
            f"{context.card.name}: the creature it named is gone"
        )
    return True, "resolved"


@effect_handler("destroy_event_subject")
def destroy_event_subject(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Whenever a Djinn or Efreet enters, **destroy it**. It can't be
    regenerated." (Suleiman's Legacy.)

    The victim is the object the *trigger's own event* was about, carried by id
    in the trigger's context (CR 603.10 — the ability uses the information the
    game had when it triggered, and by resolution an index is not an identity).
    Nothing is chosen: the card printed no target, so this cannot ride the
    targeted destroy, which would raise a picker for a choice CR 603.3d says was
    never offered and then destroy whatever the resolution context held.

    No re-check of the printed noun. The event's filter already decided that
    this permanent is what the trigger was about; asking again at resolution
    would let a Djinn that stopped being one between the two escape a destroy
    the rules have already aimed at it.

    Through ``_destroy_swept_permanents``, the seam every sibling here uses, so
    "it can't be regenerated" is this handler's ``bypass_regeneration`` rather
    than a second reading of CR 701.19c. A permanent already gone is destroyed
    by nothing, which is CR 608.2b doing as much as it can.
    """
    victim = game.permanent_by_id(
        (context.trigger_context or {}).get("event_subject_permanent_id")
    )
    seat = game.controller_index_of(victim) if victim is not None else None
    if victim is None or seat is None:
        game.log.append(f"{context.card.name}: the permanent it named is gone")
        return True, "resolved"
    destroyed = game._destroy_swept_permanents(
        game.players[seat],
        lambda candidate: candidate is victim,
        allow_regeneration=not instruction.payload.get("bypass_regeneration"),
    )
    if destroyed:
        game.log.append(f"{context.card.name} destroyed {victim.card.name}")
    return True, "resolved"


@effect_handler("exile_event_subject")
def exile_event_subject(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Whenever a creature enters, if there are two or more other creatures on
    the battlefield, **exile that creature. Return that card to the battlefield
    under its owner's control when this artifact leaves the battlefield.**"
    (Portcullis.)

    ``destroy_event_subject``'s twin one keyword action over (CR 701.13a rather
    than 701.7), reading the same frozen id for the same reason: the victim is
    the object the trigger's own event was about, and by resolution an index is
    not an identity (CR 400.7). Nothing is chosen — the card printed no target —
    so this cannot ride the targeted exile, which would raise a picker for a
    choice CR 603.3d says was never offered.

    ``until_source_leaves`` is the card's **second** printed sentence, and it is
    this instruction's business rather than a delayed ability of its own: the
    two sentences are one CR 610.3 linked pair, and the record they need is the
    one ``engine/linked_exile.py`` already keeps and the one
    leaves-the-battlefield transition already gives back. A delayed trigger
    beside it would be a second mechanism for one relation, which is how a
    return comes to fire twice or not at all.

    A **token** is exiled and simply ceases to exist (CR 111.7), so nothing is
    linked: there would be no card to give back.
    """
    from ..linked_exile import LEAVES, link_exiled_card

    victim = game.permanent_by_id(
        (context.trigger_context or {}).get("event_subject_permanent_id")
    )
    if victim is None or not game.is_on_battlefield(victim):
        game.log.append(f"{context.card.name}: the permanent it named is gone")
        return True, "resolved"
    owner_seat = game.owner_index_of(victim)
    owner = game.players[owner_seat] if owner_seat is not None else context.caster
    card = victim.card
    is_token = bool(victim.metadata.get("is_token"))
    game.remove_from_battlefield(victim)
    if not is_token:
        # CR 400.3: a card goes to its owner's exile, whoever controlled it.
        owner.exile.append(card)
        source = context.source_permanent
        if source is not None and owner_seat is not None and instruction.payload.get(
            "until_source_leaves"
        ):
            link_exiled_card(
                source, card, owner_seat,
                to="battlefield", ends_on=(LEAVES,),
            )
    game.log.append(f"{context.card.name} exiled {card.name}")
    game._recompute_continuous_effects()
    return True, "resolved"


@effect_handler("exile_bound_permanent")
def exile_bound_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…**Exile it** at the beginning of the next end step." (Zirilan of the
    Claw, Shallow Grave.)

    The object the creating ability bound (CR 603.7c), carried by id in the
    trigger's context — which here is neither a target nor the source: what
    the delay is about is the permanent an *earlier step of the same
    resolution* put onto the battlefield, and by the time this fires that
    resolution's scratchpad is a turn gone. So the id is frozen when the
    ability is created and read back here.

    Its own kind beside ``destroy_bound_permanent`` and
    ``sacrifice_bound_permanent`` for their reason: exiling, destroying and
    sacrificing are three different events (CR 701.8, 701.21, 406), and a
    permanent already gone is exiled by nothing — CR 608.2b doing as much as it
    can rather than a failure.
    """
    victim = game.permanent_by_id(
        (context.trigger_context or {}).get("bound_permanent_id")
    )
    if victim is None or not game.is_on_battlefield(victim):
        game.log.append(f"{context.card.name}: the permanent it named is gone")
        return True, "resolved"
    owner_seat = game.owner_index_of(victim)
    owner = game.players[owner_seat] if owner_seat is not None else context.caster
    game.remove_from_battlefield(victim)
    if not victim.metadata.get("is_token"):
        # CR 400.3: a card goes to its owner's exile, whoever controlled it.
        # A token ceases to exist instead (CR 111.7), which the removal above
        # already accomplishes.
        owner.exile.append(victim.card)
    game.log.append(f"{context.card.name} exiled {victim.card.name}")
    game._recompute_continuous_effects()
    return True, "resolved"


@effect_handler("destroy_delayed_agent")
def destroy_delayed_agent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Whenever target creature deals combat damage to a non-Wall creature this
    turn, destroy **that non-Wall creature**." (Acidic Dagger.)

    ``destroy_bound_permanent``'s twin at the *other* end of the event. The
    entry is bound to the creature that dealt the damage — that is what the
    ability targeted — and the words act on what it hit, which the fire site
    stamps as the event's agent because by resolution the combat damage step is
    over and nothing on a board says which creature took it.

    The restated noun phrase is re-checked here, for the reason every other
    re-check in this file exists: the word is carried, so it is read. A creature
    already gone is destroyed by nothing, which is CR 608.2b doing as much as it
    can rather than a failure.
    """
    from ..delayed_triggers import DELAYED_AGENT_ID
    from ..subject_filters import subject_matches

    agent_id = (context.trigger_context or {}).get(DELAYED_AGENT_ID)
    victim = game.permanent_by_id(agent_id) if isinstance(agent_id, int) else None
    if victim is None or not game.is_on_battlefield(victim):
        game.log.append(f"{context.card.name}: the creature it named is gone")
        return True, "resolved"
    described = _filter_payload_of(instruction)
    if described and not subject_matches(
        game, victim, described,
        observer=game.players.index(context.caster),
        source=context.source_permanent,
    ):
        game.log.append(
            f"{context.card.name}: {victim.card.name} no longer answers the clause"
        )
        return True, "resolved"
    game._destroy_swept_permanents(
        game.players[game.controller_index_of(victim) or 0],
        lambda perm: perm is victim,
        allow_regeneration=not instruction.payload.get("bypass_regeneration"),
    )
    game.log.append(f"{context.card.name} destroyed {victim.card.name}")
    return True, "resolved"


def _filter_payload_of(instruction: OracleInstruction) -> dict:
    """The printed noun phrase on a bound-object destroy, without the riders.

    ``bypass_regeneration`` rides the same payload and is not part of the
    phrase; handed to ``subject_matches`` it would be a key no matcher tests,
    which is the silent-drop this engine refuses everywhere else.
    """
    return {
        key: value for key, value in instruction.payload.items()
        if key != "bypass_regeneration"
    }


@effect_handler("sacrifice_bound_permanent")
def sacrifice_bound_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"When this creature leaves the battlefield this turn, **sacrifice that
    creature**." (Phantasmal Mount.)

    ``destroy_bound_permanent``'s twin, and a different rule: CR 701.21a is a
    sacrifice, so it is not a destruction — regeneration does not save it, an
    indestructible creature still goes, and no "if it would be destroyed"
    replacement ever sees an event. That is why it is its own kind rather than
    the destroy with a flag.

    The victim is the object the creating ability bound (CR 603.7c), carried by
    id in the trigger's context, and it is sacrificed by **its own controller**
    (CR 701.21a) — which need not be whoever controls this ability. A creature
    already gone is sacrificed by nothing, which is CR 608.2b doing as much as
    it can rather than a failure.
    """
    from ..oracle_types import LAST_TARGET_CONTROLLER

    # "**If the player does**, they create a 0/2 … Wall …" (Basalt Golem). Both
    # halves of the rider read this step: whether it took place, and whose
    # creature it was. The seat is recorded **before** the sacrifice, which is
    # the only moment it can be — by the sentence behind it the creature is a
    # card in a graveyard (CR 400.7) and its controller is nobody's to read.
    #
    # Written as a zero and a None on the path that does nothing, for the reason
    # ``discard_target_cards`` writes its zero: a missing key and a false one
    # read the same to the rider, and writing it is what says this step answered.
    context.results["sacrificed_this_way"] = 0
    victim = game.permanent_by_id(
        (context.trigger_context or {}).get("bound_permanent_id")
    )
    if victim is None or not game.is_on_battlefield(victim):
        game.log.append(f"{context.card.name}: the creature it named is gone")
        return True, "resolved"
    seat = game.controller_index_of(victim)
    if (
        instruction.payload.get("sacrificed_by") == "you"
        and seat != game.players.index(context.caster)
    ):
        # "…**sacrifice** it" with no other subject is this ability's
        # controller doing the sacrificing, and CR 701.21a: "A player can't
        # sacrifice … a permanent they don't control." A creature stolen back
        # before the delay fires stays where it is, and "if you do" is false.
        game.log.append(
            f"{context.card.name}: {context.caster.name} doesn't control "
            f"{victim.card.name} and can't sacrifice it"
        )
        return True, "resolved"
    if isinstance(seat, int):
        context.results[LAST_TARGET_CONTROLLER] = seat
    # "If you do, you gain life equal to **its toughness**." (Spinal Embrace.)
    # Last-known information (CR 608.2h), read before the sacrifice for the
    # seat's reason one line up: a moment later it is a card in a graveyard
    # with no computed characteristics. The keys every other step that gives
    # up one object writes (``_record_sacrificed_card``, the destroy).
    context.results["its_power"] = max(0, int(victim.effective_power))
    context.results["its_toughness"] = max(0, int(victim.effective_toughness))
    game.sacrifice_permanent(victim)
    context.results["sacrificed_this_way"] = 1
    game.log.append(f"{context.card.name}: {victim.card.name} was sacrificed")
    return True, "resolved"


@effect_handler("destroy_attached_permanent")
def destroy_attached_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"When enchanted land becomes tapped, destroy it." (Blight.)

    The victim is read off the source's own attachment rather than from a
    target: CR 303.4b makes "enchanted" a name for the object this Aura is
    already attached to, so the sentence chooses nothing and there is nothing
    for a picker to have offered or for the resolution context to carry.

    It goes through ``_destroy_swept_permanents`` — the same seam every other
    "destroy this particular permanent" handler uses — so regeneration, the
    indestructible check and the graveyard move behave exactly as they do for a
    targeted destroy. An Aura that has come unattached destroys nothing, which
    is the window CR 303.4c's state-based action has not closed yet.

    "When this Aura leaves the battlefield, destroy enchanted creature."
    (Parallax Dementia.) Read through ``_targets.attached_host`` rather than the
    live ``attached_to`` slot, because by the time a leaves-the-battlefield
    ability resolves the Aura's teardown has cleared that slot — and CR 608.2h
    says an effect reading an object that has left uses its last known
    information, which ``detach_aura`` records for exactly this. Reading the
    slot directly, the creature survived every way the Aura could leave and
    the card's whole drawback was gone. The host must still be on the
    battlefield either way, so a creature that left first is not chased.
    """
    attached = attached_host(game, context.source_permanent)
    if attached is None:
        game.log.append(f"{context.card.name}: nothing attached to destroy")
        return True, "resolved"
    seat = game.controller_index_of(attached)
    if seat is None:
        game.log.append(f"{context.card.name}: nothing attached to destroy")
        return True, "resolved"
    # "…**and this Aura deals 2 damage to that land's controller**." (Orcish
    # Mine.) The seat is recorded *before* the destroy, which is the only moment
    # it can be read: the sentence behind this step names the land's controller,
    # and by then the land is a card in a graveyard that CR 400.7 makes a
    # different object with no controller at all. Declared in
    # ``grammar/lowering/_records._PRODUCES``, which is what admits the phrase.
    context.results[ATTACHED_PERMANENT_CONTROLLER] = seat
    destroyed = game._destroy_swept_permanents(
        game.players[seat],
        lambda candidate: candidate is attached,
        allow_regeneration=not instruction.payload.get("bypass_regeneration"),
    )
    if destroyed:
        game.log.append(f"{context.card.name} destroyed {attached.card.name}")
    return True, "resolved"


#: The stand-in a per-controller buyout puts where a seat number would go. A
#: sentinel rather than a seat, because which seat "its controller" names is a
#: question about *this member of the loop* at the moment its round comes up:
#: the loop removes permanents as it goes, and a control change between two
#: rounds moves the offer with the permanent (CR 613 layer 2).
_CONTROLLER = object()


@effect_handler("destroy_each_unless_life_paid")
def destroy_each_unless_life_paid(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"For each land, destroy that land unless any player pays 1 life."
    (Cleansing.)

    A sweep whose members are bought off one at a time. The offer goes to
    **every** player in APNAP order (CR 101.4) about **each** land in turn, and
    the first seat to pay ends that land's round — so a seat that saved one
    land has said nothing about the next, which is the whole difference between
    this and "destroy all lands unless a player pays".

    The loop is resumable (``engine/resumption.py``): a human seat's offer
    suspends it and answering carries it on from the land it stopped at. That
    is why the destruction is a *step of the loop* — the ``None`` seat at the
    end of each land's round — rather than work written after it. Work after a
    resumable loop does not run when a step suspends, and nothing records it.

    The lands are frozen as ids before the first offer (CR 400.7: an index is
    not an identity, and this loop removes permanents as it goes). A land that
    has left by the time its round comes up is simply skipped: it is no longer
    there to destroy, and nobody should be charged to save it.

    Two payload keys say which card this is, and both are absent for Cleansing
    so its behaviour is untouched:

    * ``payer`` — "…unless **its controller** pays 2 life" (Giant Albatross)
      offers each member's round to exactly one seat rather than to every seat
      in turn. The seat is read per member, as the round comes up, because a
      control change between two members' rounds moves the offer with the
      permanent (CR 613 layer 2).
    * ``from_damage_record`` — "for each creature **that dealt damage to this
      creature this turn**". Not a narrowing of the board sweep but the set
      itself, read off the record the damage seam kept on the victim. Giant
      Albatross' trigger fires on its own death, so at resolution the source is
      a card in a graveyard and there is no battlefield read that could answer
      (CR 603.10) — the record travels with the removed ``Permanent``, which is
      the same reading Brine Hag's base-P/T rewrite makes of the same relation.
    """
    filters = dict(instruction.payload.get("filter") or {})
    life = int(instruction.payload.get("life", 1))
    payer = str(instruction.payload.get("payer") or "any_player")
    allow_regeneration = not instruction.payload.get("bypass_regeneration")
    seats = len(game.players)
    active = game.active_player_index if game.active_player_index is not None else 0
    apnap = [(active + offset) % seats for offset in range(seats)]
    if instruction.payload.get("from_damage_record"):
        source = context.source_permanent
        # The record is a list of ``Permanent`` objects; a damager that has
        # itself left is skipped here rather than at its round, because
        # ``permanent_by_id`` is what the loop addresses members by and a
        # departed permanent has no live id to offer.
        damagers = (
            (source.metadata.get("damaged_by_sources_this_turn") or [])
            if source is not None else []
        )
        candidates = [
            perm for perm in damagers if game.is_on_battlefield(perm)
        ]
    else:
        candidates = list(game.all_permanents())
    targets = [
        perm.permanent_id
        for perm in sorted(candidates, key=lambda p: p.permanent_id)
        if permanent_matches_filter(perm, filters)
    ]
    if not targets:
        game.log.append(f"{context.card.name}: nothing to destroy")
        return True, "resolved"
    saved: set[int] = set()
    # One flat list of steps rather than a loop inside a loop: `run_resumable`
    # records the rest of *itself* before each step, and a nested loop would
    # need its own record for the offers still owed about the land it stopped
    # on. The `None` seat is that land's verdict.
    #
    # ``_CONTROLLER`` stands where a seat number would for the per-controller
    # form: which seat that is cannot be settled here, because the loop removes
    # permanents as it goes and a control change between two rounds moves the
    # offer with its permanent.
    offered = apnap if payer == "any_player" else [_CONTROLLER]
    steps = [
        (permanent_id, seat)
        for permanent_id in targets
        for seat in [*offered, None]
    ]
    # Whose spell or ability this is (CR 109.5), read now and handed to every
    # destruction below. A verdict reached after a human seat's answer runs
    # when nothing is resolving any more — the loop is resumed from the prompt
    # — so "whatever is resolving" would be nobody, and a land an opponent's
    # Cleansing destroyed would have been destroyed by no one.
    destroyer = game.players.index(context.caster)
    # …and the whole loop is one effect, however many answers it stops for:
    # what its destructions trigger waits for the last verdict (CR 603.3b), so
    # the final step — the only place a resumable loop may put work it owes —
    # is what lets them go.
    _FINISHED = object()
    steps.append((_FINISHED, None))
    begin_destruction_hold(game)

    def _step(item) -> None:
        permanent_id, seat = item
        if permanent_id is _FINISHED:
            end_destruction_hold(game)
            return
        permanent = game.permanent_by_id(permanent_id)
        if permanent is None or permanent_id in saved:
            return
        if seat is None:
            controller = game.controller_index_of(permanent)
            if controller is None:
                return
            game._destroy_swept_permanents(
                game.players[controller],
                lambda candidate, target=permanent: candidate is target,
                allow_regeneration=allow_regeneration,
                cause=destroyer,
            )
            game.log.append(
                f"{context.card.name} destroyed {permanent.card.name} "
                "(nobody paid to save it)"
            )
            return
        if seat is _CONTROLLER:
            seat = game.controller_index_of(permanent)
            if seat is None:
                return
        if game.players[seat].lost:
            return
        game.arm_pending_choice(
            "pay_life_to_save", seat,
            permanent_id=permanent_id,
            permanent_name=permanent.card.name,
            life=life,
            card_name=context.card.name,
            _saved=saved,
        )

    run_resumable(game, steps, _step)
    return True, "resolved"


@effect_handler("sacrifice_recorded_permanent")
def sacrifice_recorded_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"That player chooses and sacrifices one of those creatures."
    (Retribution.)

    The sacrifice half of Preacher's decomposition, one rule over from
    ``destroy_target_permanent``'s ``permanents_from`` reading: a
    ``choose_permanent`` step ahead of this one asked the affected seat which,
    and recorded the answer by id.

    Its own kind rather than the destroy with a flag, for
    ``sacrifice_bound_permanent``'s reason: CR 701.21a is a sacrifice, so
    regeneration does not save it, an indestructible permanent still goes, and
    no "if it would be destroyed" replacement ever sees an event.

    Nothing recorded, or a permanent that has left since, sacrifices nothing —
    CR 608.2b doing as much as it can rather than a failure.
    """
    recorded = one_recorded_permanent_id(
        context, instruction.payload.get("permanents_from")
    )
    victim = game.permanent_by_id(recorded) if recorded is not None else None
    if victim is None or not game.is_on_battlefield(victim):
        game.log.append(f"{context.card.name}: nothing was chosen to sacrifice")
        return True, "resolved"
    game.sacrifice_permanent(victim)
    game.log.append(f"{context.card.name}: {victim.card.name} was sacrificed")
    return True, "resolved"


@effect_handler("exile_recorded_permanent")
def exile_recorded_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile one of those creatures and put two +1/+1 counters on the other."
    (Cannibalize.)

    :func:`sacrifice_recorded_permanent` above with the other fate, and beside
    it for that reason: both read the id a ``choose_permanent`` step ahead of
    them recorded, and they differ only in where the permanent goes. Its own
    kind rather than a flag on that one, because CR 701.21a's sacrifice and
    CR 701.13a's exile are different events — a sacrifice is a death and this
    is not, so no dies-trigger fires and no regeneration is offered.

    Nothing recorded, or a permanent that has left since, exiles nothing —
    CR 608.2b doing as much as it can rather than a failure.
    """
    recorded = one_recorded_permanent_id(
        context, instruction.payload.get("permanents_from")
    )
    victim = game.permanent_by_id(recorded) if recorded is not None else None
    if victim is None or not game.is_on_battlefield(victim):
        game.log.append(f"{context.card.name}: nothing was chosen to exile")
        return True, "resolved"
    # CR 400.3: a card put into exile is still owned by whoever owns it, and the
    # departure is the one transition every leaves-the-battlefield rule rides.
    owner_index = game.owner_index_of(victim)
    exiled = victim.card
    game.remove_from_battlefield(victim)
    game.players[
        owner_index if owner_index is not None else game.players.index(context.caster)
    ].exile.append(exiled)
    game.log.append(f"{context.card.name}: {exiled.name} was exiled")
    return True, "resolved"


@effect_handler("each_player_pays_or_sacrifices_greatest")
def each_player_pays_or_sacrifices_greatest(
    game: "Game", instruction: "OracleInstruction", context: "OracleExecutionContext"
) -> tuple[bool, str]:
    """Tariff's whole paragraph.

    "Each player sacrifices the creature they control with the greatest mana
    value unless they pay that creature's mana cost. If two or more creatures a
    player controls are tied for greatest, that player chooses one."

    **Nothing here is a new mechanism**, which is the point. Per seat it runs
    two ordinary instructions the engine already dispatches:

    * ``choose_permanent`` narrowed to that seat's permanents of the printed
      type with the greatest mana value, asked ``only_on_tie`` — which is the
      second printed sentence, and with one candidate no prompt is made because
      the card names it outright. Juxtapose's two sides are the same three
      payload keys.
    * ``may``, with the cost read off what that step recorded (``cost_from``,
      the key Flash's "unless you pay **its** mana cost" already uses) and
      ``sacrifice_recorded_permanent`` on the decline (Retribution's).

    What the handler contributes is the **loop**, and it has to be here because
    "each player" is a number of *pairs* of steps only the resolution knows: a
    lowering that decomposed this the way Juxtapose's does would have to know
    the seat count. Each seat's key is its own, so one seat's answer cannot be
    read as another's.

    The pairs are run through ``run_resumable`` and flat rather than nested —
    the offer for a seat sits directly behind that seat's choice in one list, so
    a tie-break prompt that suspends resumes at the offer it was asked for, and
    the seat behind it after that. CR 101.4's order, active player first: both
    the choice and the payment are choices made during one resolution, and each
    seat makes theirs knowing the earlier ones.

    A seat with no creature at all is skipped rather than asked: with nothing to
    sacrifice there is no toll, which is CR 608.2b doing as much as it can.
    """
    card_type = str(instruction.payload.get("card_type", "creature"))
    total = len(game.players)
    active = game.active_player_index or 0
    seats = sorted(
        (i for i, p in enumerate(game.players) if not p.lost),
        key=lambda i: ((i - active) % total, i),
    )
    described = {"type_filter": card_type}
    steps: list[OracleInstruction] = []
    for seat in seats:
        if not any(
            permanent_matches_filter(perm, described)
            for perm in game.controlled_by(seat)
        ):
            # A seat with nothing of the printed type is skipped rather than
            # asked: with nothing to sacrifice there is no toll, which is
            # CR 608.2b doing as much as it can. Asked anyway it would be an
            # offer to pay nothing for nothing, shown to a live player.
            continue
        # Namespaced per seat *and* per resolution key, so two copies of this
        # paragraph in one sequence cannot read each other's answers.
        key = f"greatest_{card_type}_seat_{seat}"
        steps.append(
            OracleInstruction(
                "choose_permanent", "",
                {
                    "result_key": key,
                    "filter": {"type_filter": card_type},
                    "controlled_by": seat,
                    "chooser": seat,
                    # CR 202.3's "greatest mana value", as the two payload words
                    # ``ast.Superlative`` gives every printed superlative. It was
                    # ``greatest_mana_value: True`` — one corner of the phrase
                    # spelled into a flag of its own, which a card printing
                    # "least toughness" could not reuse.
                    "superlative": {"extreme": "greatest", "characteristic": "mana_value"},
                    "only_on_tie": True,
                    "prompt": (
                        f"Choose which {card_type} with the greatest mana value "
                        "to sacrifice or pay for."
                    ),
                },
            )
        )
        steps.append(
            OracleInstruction(
                "may", "",
                {
                    "actor": seat,
                    "cost": {"cost_from": key},
                    "otherwise": (
                        OracleInstruction(
                            "sacrifice_recorded_permanent", "",
                            {"permanents_from": key},
                        ),
                    ),
                },
            )
        )

    def run(step) -> None:
        game._execute_oracle_instruction(step, context)

    # Last thing this function does — ``engine/resumption.py``'s rule for any
    # loop that can be interrupted, and every step here can be.
    run_resumable(game, steps, run)
    return True, "resolved"
