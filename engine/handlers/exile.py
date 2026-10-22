"""Exiling (CR 701.13): an object moved to the exile zone.

The handler twin of ``engine/grammar/lowering/exile.py``. Off the battlefield: a
target permanent, the source itself, a created token or any number of the
tokens a creature created (Tetravus), every permanent a phrase
names (Ugin's −X), a creature until end of turn, and a creature whose controller
gains life equal to its power. Out of a graveyard: the whole of one, a position
in it, announced cards, everything a phrase names, what a cost sacrificed, a
creature a delayed ability bound once it has died (Whippoorwill), a discarded
card (Necropotence), and Yawgmoth's Will's window over every arrival. Off a
library: its top cards, or all of it. A card exiled under a record a later step
reads (``EXILED_THIS_WAY``) is recorded here; where that pile goes next is
``linked_exile.py``'s.

Split out of ``zones.py`` at the 2,000-line cap's split round.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..exiled_records import record_exiled_card
from ..linked_exile import link_exiled_card
from ..models import Permanent
from ..oracle_types import (EXILED_BY_SEAT, EXILED_THIS_WAY,
                            EXILED_THIS_WAY_OBJECTS, LAST_TARGET_CONTROLLER,
                            LAST_TARGET_NAME, PER_OBJECT_SEAT_RECORDS,
                            SWEPT_OWNER_SEATS)
from ..tokens import CREATED_TOKEN_RESULT_KEY, tokens_created_with
from ._amounts import resolve_amount
from ._filters import (_card_matches_filter, graveyard_card_matches,
                       permanent_matches_filter)
from ._targets import (_resolve_graveyard_slots, frozen_that_player_seat,
                       resolve_target_permanent, resolve_target_permanents)
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("exile_target_creature_until_eot")
def exile_target_creature_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    card = context.card
    # 610.3: zone-change one-shot "until" EOT; second one-shot returns at cleanup
    target_perm_idx = context.target_permanent_index
    exiled_perm: Permanent | None = None
    if isinstance(target_perm_idx, int) and 0 <= target_perm_idx < len(target.battlefield):
        candidate = target.battlefield[target_perm_idx]
        if candidate.is_creature:
            exiled_perm = candidate
            game.remove_from_battlefield(candidate)
    if exiled_perm is None:
        for perm in list(game.controlled_by(target)):
            if perm.is_creature:
                exiled_perm = perm
                game.remove_from_battlefield(perm)
                break
    if exiled_perm is not None:
        target.exile.append(exiled_perm.card)
        owner_idx = game.players.index(target)
        game.exile_until_eot.append((owner_idx, exiled_perm.card))
        game.log.append(f"{exiled_perm.card.name} exiled until end of turn by {card.name}")
    else:
        game.log.append(f"{card.name}: no valid creature to exile")
    return True, "resolved"


@effect_handler("exile_bound_card")
def exile_bound_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"When that creature dies this turn, exile **it**." (Whippoorwill.)

    The object a delayed ability was bound to, after the death that fired it —
    so what is exiled is a *card in a graveyard*, never a permanent. CR 603.7d
    makes the ability's source the permanent that created it, which is exactly
    the reading this handler exists to avoid: routed through ``exile_self``,
    Whippoorwill exiled itself every time its target died.

    The card is found by name in the owner's graveyard, the two facts the death
    seam freezes into the trigger's context (CR 608.2h): by resolution the
    permanent is gone, CR 400.7 makes its card a new object, and a graveyard
    has no controller to re-derive the seat from. Two copies of one card in a
    pile are literally one ``CardDefinition``, so which of them is taken is not
    a question with an answer — and the *last* one is taken, because a death
    puts the card on top.

    A card that has already left that pile exiles nothing rather than falling
    back to a scan: CR 608.2's "as much as possible", and a scan would exile
    whichever look-alike it reached first.

    **Two ways the card can have been recorded, and the identity one wins.**
    "Whenever a nontoken creature is put into your graveyard from the
    battlefield, exile that card" (Purgatory) fires from the death seam, which
    freezes the ``CardDefinition`` itself; the delayed spelling above it froze a
    seat and a *name*, because that fire site had nothing else. An identity is
    strictly the better answer — a graveyard holding two copies of one card
    holds one ``CardDefinition`` twice, so the name cannot tell them apart and
    the seat cannot either — so it is asked first and the name is the fallback
    rather than the rule.

    The exile is **recorded against the ability's source** (CR 610.3). Nothing
    here can know whether the permanent has a second ability naming "a card
    exiled with this enchantment" — Purgatory does, Whippoorwill does not — and
    the record is the only thing that could answer it, so it is always written.
    It ends nothing on its own: ``ends_on`` is empty, so no sweep gives these
    cards back.
    """
    from ..linked_exile import link_exiled_card

    trigger = context.trigger_context or {}
    card = trigger.get("dead_card")
    owner = None
    index = None
    if card is not None:
        for player in game.players:
            found = next(
                (i for i, held in enumerate(player.graveyard) if held is card), None
            )
            if found is not None:
                owner, index = player, found
                break
        if owner is None:
            game.log.append(
                f"{context.card.name}: {card.name} is no longer in a graveyard"
            )
            return True, "resolved"
    else:
        seat = trigger.get("event_subject_owner")
        name = trigger.get("dead_name")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)) or not name:
            game.log.append(f"{context.card.name}: no card was recorded to exile")
            return True, "resolved"
        owner = game.players[seat]
        index = next(
            (i for i in range(len(owner.graveyard) - 1, -1, -1)
             if owner.graveyard[i].name == name),
            None,
        )
        if index is None:
            game.log.append(
                f"{context.card.name}: {name} is no longer in {owner.name}'s graveyard"
            )
            return True, "resolved"
    exiled = owner.graveyard.pop(index)
    owner.exile.append(exiled)
    source = context.source_permanent
    if source is not None:
        link_exiled_card(source, exiled, game.players.index(owner))
    game.log.append(
        f"{context.card.name} exiled {exiled.name} from {owner.name}'s graveyard"
    )
    return True, "resolved"


@effect_handler("exile_self")
def exile_self(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile it." / "Exile this creature." (Archfiend's Vessel.)

    The ability's own source, which is not a target: nothing is chosen, so there
    is no picker, no legality check and nothing to re-resolve. A source that has
    already left the battlefield exiles nothing rather than falling back to a
    scan — CR 608.2b's "do as much as possible", and a scan here would exile
    whichever look-alike it reached first.

    Records whether it happened, so "**If you do**, create a 5/5 black Demon
    creature token" is the ordinary if-you-do branch rather than a fused
    instruction.

    ``counters`` is "…with two scream counters on it" (All Hallow's Eve): the
    card goes to exile carrying them, and the register in
    ``engine/exiled_records.py`` is what remembers so — a ``CardDefinition`` in
    an exile list has nowhere to keep them and no identity to key them on. The
    registration happens here, where the exiling is *decided*, for both paths:
    a spell exiling itself is binned at the very end of its own resolution
    (CR 608.2n), so this is the only moment both a permanent and a spell pass
    through.
    """
    def _register(owner_index: int, card) -> None:
        counters = instruction.payload.get("counters") or {}
        if not counters:
            return
        # ``resolve_amount`` rather than ``int``: a count may be the cast's X
        # (CR 107.3), which travels as the string ``"x"`` — the same spelling
        # every other counted payload in this engine carries. Resolved once,
        # because the register and the log must not disagree about how many.
        placed = {
            str(k): resolve_amount(v, context.x_value) for k, v in counters.items()
        }
        record_exiled_card(
            game, card, owner_index,
            # CR 108.4: a card in exile has no controller, so its abilities
            # belong to its owner. Recorded explicitly rather than left to
            # default, because "at the beginning of **your** upkeep" needs a
            # seat and the register is the only thing that still has one.
            controller_index=owner_index,
            counters=placed,
        )
        game.log.append(
            f"{card.name} was exiled with "
            + ", ".join(
                f"{count} {name} counter" + ("s" if count != 1 else "")
                for name, count in placed.items()
            )
        )

    source = context.source_permanent
    if source is None or not game.is_on_battlefield(source):
        # "When this creature dies, **exile it** if it had a death counter on
        # it." (Bogardan Phoenix.) A dies-trigger's source is in a graveyard by
        # the time the ability resolves (CR 603.3 puts the trigger on the stack
        # *after* the state-based action moved the card), and "it" means that
        # card — CR 603.10's last-known information names the object, and the
        # object's current zone is where the move comes from. Without this the
        # exile branch of a dies-trigger logged "nothing to exile" and the card
        # stayed in the graveyard, which for the Phoenix is the card returning
        # for ever.
        #
        # By identity through the hand/graveyard seam's own reasoning: two
        # copies of a card in a deck are the same immutable ``CardDefinition``,
        # so a name match would take whichever entry came first.
        # …and **an ability activated from a graveyard** (Carrionette's
        # "Exile this card and target creature", CR 113.6m). There is no
        # permanent at all there, so the branch below would read the sentence
        # as a spell exiling itself and set the resolving-spell flag on an
        # ability — which bins nothing and leaves the card in the pile, exactly
        # the failure the Phoenix note above describes.
        #
        # ``ability_text`` is the discriminator and it is the only sound one:
        # it is set for an activated ability and None for a spell, where the
        # zone is not. A graveyard scan run for a *spell* would find another
        # copy of the same card in the pile — two copies of a card in a deck
        # are the same object — and exile that one instead of the spell.
        #
        # Hoisted above the resolving-spell branch for that same reason: the
        # two are told apart by the discriminator rather than by which one is
        # tried first.
        if context.card is not None and (
            source is not None or context.ability_text is not None
        ):
            # The resolving seat's own pile first. Two copies of one card in
            # two graveyards are the *same* ``CardDefinition`` object, so a
            # scan in seat order would take an opponent's copy whenever they
            # sit earlier — and for a graveyard-activated ability CR 113.6m
            # names one pile in particular, the activator's.
            piles = [context.caster] + [
                player for player in game.players if player is not context.caster
            ]
            for player in piles:
                for index, held in enumerate(player.graveyard):
                    if held is context.card:
                        player.graveyard.pop(index)
                        player.exile.append(held)
                        context.results["exiled_self"] = True
                        _register(game.players.index(player), held)
                        game.log.append(
                            f"{context.card.name} was exiled from "
                            f"{player.name}'s graveyard"
                        )
                        return True, "resolved"
        # **A spell exiling itself** (Experimental Overload's "Exile Experimental
        # Overload."). There is no permanent — the object is the spell on the
        # stack — so this is CR 608.2n's "where the card goes" rather than a
        # zone change of something in play, and it routes through the same flag
        # the "if that spell would be put into your graveyard, exile it instead"
        # rider uses. Set rather than performed: the card is still resolving,
        # and the resolution tail is the one place that bins it.
        if source is None and context.card is not None:
            game.exile_resolving_spell = True
            context.results["exiled_self"] = True
            game.log.append(f"{context.card.name} will be exiled as it resolves")
            # Registered under the seat whose exile the resolution tail will
            # bin it to — its **owner's** (CR 400.3), which is the resolving
            # stack object's ``owner_index`` and not the caster when the spell
            # was cast out of another player's zone. A record keyed to the
            # caster would never be live, and All Hallow's Eve's scream
            # counters would never come off.
            resolving = (getattr(game, "resolving_items", None) or [None])[-1]
            owner_seat = (
                resolving.owner_index
                if resolving is not None and resolving.card is context.card
                else game.players.index(context.caster)
            )
            _register(owner_seat, context.card)
            return True, "resolved"
        game.log.append(f"{context.card.name}: nothing to exile")
        return True, "resolved"
    owner_index = game.owner_index_of(source)
    owner = game.players[owner_index] if owner_index is not None else context.caster
    game.remove_from_battlefield(source)
    if not source.metadata.get("is_token", False):
        # CR 111.7: a token ceases to exist rather than going to exile.
        owner.exile.append(source.card)
        # The seat the owner lookup already found. ``players.index(owner)``
        # would compare ``PlayerState`` by value, which is the look-alike bug
        # the control seam documents for permanents.
        _register(
            owner_index if owner_index is not None else game.players.index(context.caster),
            source.card,
        )
    context.results["exiled_self"] = True
    game.log.append(f"{source.card.name} was exiled")
    return True, "resolved"


@effect_handler("exile_created_token")
def exile_created_token(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile **that token**…" — the token an earlier step of this same effect
    created (Stangg).

    Not a target and not the source: the token maker wrote its ``permanent_id``
    to the resolution scratchpad, and this reads it back. By id rather than by
    a scan for a matching token, for the reason every bound object in this
    engine is an id — a second Stangg Twin on another battlefield is a
    look-alike, and a scan would reach whichever came first.

    The id is read from the firing trigger's context first: this instruction is
    normally the effect of a *delayed* ability, and by the time that ability
    fires the resolution that created the token is long over. The delayed entry
    froze the scratchpad (CR 608.2h), which is where the id then lives.

    ``created_with_source`` is the same object one reach further out — "exile
    **the token**" (Dance of Many), where the token maker is a *different
    ability of the same permanent* and fired turns ago. No scratchpad survives
    that, so the id comes off the durable record the maker stamped on the token
    (``tokens_created_with``). One kind rather than two, because what differs
    is where the id is read and not what is done with it.

    A token that is already gone exiles nothing (CR 608.2b, and CR 111.7 —
    a token that has left the battlefield has ceased to exist).
    """
    # "Create three … tokens. **Exile them** at the beginning of the next
    # cleanup step." (Waylay.) The plural of the same back-reference, reading
    # the list the maker recorded beside the single id — out of the *frozen*
    # scratchpad first, because this instruction is normally a delayed
    # ability's and the resolution that made the tokens is long over
    # (CR 608.2h). A token already gone exiles nothing (CR 111.7).
    recorded_key = instruction.payload.get("permanents_from")
    if recorded_key is not None:
        ids = (context.trigger_context or {}).get(str(recorded_key))
        if not isinstance(ids, (list, tuple)):
            ids = context.results.get(str(recorded_key))
        found = [
            game.permanent_by_id(one)
            for one in (ids or ())
            if isinstance(one, int)
        ]
        gone = [perm for perm in found if perm is not None]
        if not gone:
            game.log.append(f"{context.card.name}: the tokens it named are gone")
            return True, "resolved"
        for perm in gone:
            _exile_one_created_token(game, context, perm)
        return True, "resolved"
    if instruction.payload.get("created_with_source"):
        made = tokens_created_with(game, context.source_permanent)
        # The phrase is singular. A permanent that made several would leave
        # "the token" naming no one of them, so the sentence takes the one it
        # names and nothing otherwise — the same refusal every ambiguous
        # back-reference in this engine takes.
        token = made[0] if len(made) == 1 else None
    else:
        recorded = (context.trigger_context or {}).get(CREATED_TOKEN_RESULT_KEY)
        if not isinstance(recorded, int):
            recorded = context.results.get(CREATED_TOKEN_RESULT_KEY)
        token = game.permanent_by_id(recorded) if isinstance(recorded, int) else None
    if token is None:
        game.log.append(f"{context.card.name}: the token it named is gone")
        return True, "resolved"
    _exile_one_created_token(game, context, token)
    return True, "resolved"


def _exile_one_created_token(game: Game, context: OracleExecutionContext, token) -> None:
    """Send one recorded token where CR 111.7 and CR 400.3 send it.

    One body because the plural branch above exiles several and a second copy
    of the CR 111.7 test is a second chance for one of them to forget that a
    token ceases to exist rather than going to exile.
    """
    owner_index = game.owner_index_of(token)
    game.remove_from_battlefield(token)
    if not token.metadata.get("is_token", False) and owner_index is not None:
        # CR 111.7: a token ceases to exist rather than going to exile. The
        # check is here rather than assumed because the scratchpad records a
        # *permanent* id, and nothing stops a later card from recording one
        # that is not a token.
        game.players[owner_index].exile.append(token.card)
    game.log.append(f"{context.card.name} exiled {token.card.name}")


@effect_handler("exile_target_permanent")
def exile_target_permanent(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile target creature or planeswalker." / "Exile target nonland
    permanent." — the *permanent* exile, as distinct from
    ``exile_target_creature_until_eot``, which records a return at cleanup.
    Nothing here is remembered, because nothing comes back (CR 406.1).

    Three things this deliberately does not open-code:

    * **the removal.** ``remove_from_battlefield`` is the one transition off
      the battlefield; a hand-rolled rebuild would skip the combat renumbering
      every leave depends on, and ``list.remove`` matches a look-alike.
    * **the destination.** CR 400.3 sends an exiled card to its *owner's*
      exile, which is not the seat that was targeted once it was stolen.
    * **the controller, read before the removal.** "Its controller creates a
      token" is a later step of the same resolution, and once the permanent is
      gone there is nobody left to ask — which is why this is two composed
      instructions rather than one fused kind.
    """
    card = context.card
    payload = instruction.payload
    # "Exile **two target** nonartifact creatures." (Ashes to Ashes; Dust to
    # Dust prints the same over artifacts.) The several-targets description is
    # the opt-in: a list was collected at announcement, so each slot resolves
    # strictly and a target that has left is simply dropped (CR 608.2b) rather
    # than falling back to whatever a scan reaches first, which for two slots
    # would exile a permanent the player never chose. A lowering that dropped
    # ``count`` would exile one of the two and report the card supported.
    targets_desc = instruction.payload.get("targets") or {}
    # "Exile **X** target attacking creatures." (Vengeful Dreams.) The same
    # list announced at a count the cast's X sets (CR 601.2c), so it is the
    # several-targets branch at any X: read as the single target below, only
    # the first of X named attackers was exiled.
    if isinstance(targets_desc, dict) and (
        targets_desc.get("count") == "x"
        or (isinstance(targets_desc.get("count"), int) and targets_desc["count"] > 1)
    ):
        # The printed predicate rather than the default, which is "is it a
        # creature?" — Dust to Dust names artifacts, and a slot the resolver
        # rejects is a slot silently dropped. Idiom 9: the picker's enumeration
        # is a hint, so the printed filter is what decides, here as at
        # announcement.
        chosen = resolve_target_permanents(
            game, context,
            predicate=lambda candidate: permanent_matches_filter(candidate, payload),
        )
        if not chosen:
            game.log.append(f"{card.name}: no valid permanent to exile")
            return True, "resolved"
        # Each one to its **owner's** exile, read before its own removal: the
        # loop is one resolution and a controller read after the fact has
        # nobody left to ask.
        for perm in chosen:
            controller_index = game.controller_index_of(perm)
            owner_index = game.owner_index_of(perm)
            game.remove_from_battlefield(perm)
            if owner_index is None:
                owner_index = controller_index if controller_index is not None else 0
            game.players[owner_index].exile.append(perm.card)
            # "When this creature enters, exile two target lands. When this
            # creature leaves the battlefield, return **the exiled cards** to
            # the battlefield under their owners' control." (Petradon.) The
            # one-target branch below has always recorded its card as exiled
            # *with* the ability's source (CR 607.2a); the several-target one
            # did not, so a second linked ability had an empty pile to read.
            # A token is not recorded: CR 111.8 ends its existence as it
            # leaves, and there is no card for "the exiled cards" to name.
            if context.source_permanent is not None and not perm.metadata.get(
                "is_token"
            ):
                link_exiled_card(context.source_permanent, perm.card, owner_index)
            game.log.append(f"{card.name} exiled {perm.card.name}")
        # No `last_target_controller`: the key names *the* controller, and
        # a several-target exile has one per permanent. A later step reading it
        # would silently act on whichever one happened to be written last, so
        # the key is left absent and any card that needs it refuses for want of
        # a producer rather than acting on the wrong seat.
        return True, "resolved"
    # "Exile target permanent **you own or control**." (Telim'Tor's Edict;
    # Safe Haven prints "you control".) A *relative* narrowing — a question
    # about a seat rather than about the card — which the pure matcher
    # deliberately cannot answer and therefore silently drops. The picker's
    # spec for this kind carries no filter either, so the phrase was enforced
    # nowhere at all: the Edict exiled any permanent on the table.
    #
    # ``subject_matches`` is the one reader of what a printed noun phrase
    # means, with the resolving controller as "you" (CR 109.5) — idiom 9, the
    # picker's enumeration is a hint and the resolution re-checks the answer.
    from ..subject_filters import subject_matches

    described = {key: value for key, value in payload.items() if key != "targets"}
    observer = (
        game.players.index(context.caster)
        if context.caster in game.players else None
    )
    def _answers(candidate) -> bool:
        return subject_matches(
            game, candidate, described, observer=observer,
            source=context.source_permanent,
        )

    # **A recorded id is the choice** (CR 601.2c), read strictly: the permanent
    # it names if that still answers the printed description, and otherwise
    # nothing (CR 608.2b). ``resolve_target_permanent`` falls through to a scan
    # of the target's battlefield when the id fails its predicate, which is
    # right for a caller that recorded no choice and wrong for one that did:
    # Eradicate cast at a creature made black in response exiled the creature
    # beside it, and Topple ("…with the greatest power among creatures on the
    # battlefield") exiled whichever creature had just overtaken its target. A
    # seat-only announcement (no id) keeps the scan.
    recorded = context.target_permanent_id
    if isinstance(recorded, list):
        recorded = recorded[0] if recorded else None
    if isinstance(recorded, int):
        named = game.permanent_by_id(recorded)
        perm = named if named is not None and _answers(named) else None
    else:
        perm = resolve_target_permanent(game, context, predicate=_answers)
    if perm is None:
        game.log.append(f"{card.name}: no valid permanent to exile")
        return True, "resolved"
    controller_index = game.controller_index_of(perm)
    owner_index = game.owner_index_of(perm)
    # "You gain life equal to **its toughness**" (Exile) is a later step of the
    # same resolution asking a question about an object that will by then be a
    # card in exile — CR 613.1 gives it no computed characteristics at all, so
    # the number is frozen here, one line before the removal, exactly as
    # ``destroy_target_permanent`` freezes its pair one line before the destroy
    # (CR 608.2h). The effective value, so a pumped or counter-laden creature is
    # worth what it was worth on the battlefield.
    #
    # Toughness alone. The power of an exiled permanent has an owner already —
    # ``_fused_exile_then_controller_life`` — and ``_records._PRODUCES`` says
    # at length why declaring it here would un-refuse a near-miss that reads
    # the wrong seat.
    context.results["its_toughness"] = max(0, int(perm.effective_toughness))
    # "…all cards with the same name as **that creature**" (Eradicate, Scour,
    # Splinter, Sowing Salt). The name, frozen one line before the removal for
    # the toughness's reason above: the search runs after this step and by then
    # the permanent is a card in exile, which CR 400.7 makes a new object no
    # board read can find. Through ``effective_card`` (CR 707.2) so a Clone of
    # Grizzly Bears strips Grizzly Bears rather than the copy's printed face.
    context.results[LAST_TARGET_NAME] = perm.effective_card.name
    game.remove_from_battlefield(perm)
    if owner_index is None:
        owner_index = controller_index if controller_index is not None else 0
    game.players[owner_index].exile.append(perm.card)
    # "Exile target creature you control. Return **that card** to the
    # battlefield … at the beginning of the next end step." (Liberate.) Which
    # card this step exiled, under the key every "that card" behind an exile
    # reads — a delayed ability's creation freezes the scratchpad
    # (CR 603.7d), so the return finds this card by identity and not whatever
    # else has reached the zone since. A **token** is not recorded: CR 111.8
    # ends its existence when it leaves the battlefield, so there is no card
    # for the words to name and returning one would mint a card from nothing.
    context.results["exiled_cards"] = (
        [] if perm.metadata.get("is_token") else [perm.card]
    )
    # Recorded as exiled **with** the ability's source when that source is a
    # permanent (CR 610.3), exactly as ``exile_top_of_library`` does it and for
    # the same reason: nothing ends the link on its own — the entry carries no
    # ``ends_on`` — so it is inert for every card that never asks, and it is
    # everything for Safe Haven, whose upkeep trigger returns "each card exiled
    # with this land". Without it that trigger drains an empty pile and the
    # creatures never come back, which is the shape of a card reporting
    # supported and quietly doing nothing.
    if context.source_permanent is not None:
        link_exiled_card(context.source_permanent, perm.card, owner_index)
    if controller_index is not None:
        context.results[LAST_TARGET_CONTROLLER] = controller_index
    game.log.append(f"{card.name} exiled {perm.card.name}")
    return True, "resolved"


@effect_handler("exile_target_graveyard")
def exile_target_graveyard(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile target player's graveyard." (Tormod's Crypt.)

    The whole zone at once. A graveyard is its owner's (CR 404.1) and so is the
    exile zone, so every card goes from one to the other with no CR 400.3
    ownership lookup — and the list is emptied rather than filtered, because the
    card names no restriction.
    """
    # "Exile **all graveyards**." (Bazaar of Wonders.) Every pile, named by
    # nobody — which is why the payload key is what selects the sweep rather
    # than a sentinel seat: this sentence chooses no target (CR 115.1), and a
    # seat here would be one.
    victims = (
        list(game.players) if instruction.payload.get("every")
        else [context.target if context.target is not None else context.caster]
    )
    for victim in victims:
        exiled = list(victim.graveyard)
        victim.graveyard.clear()
        victim.exile.extend(exiled)
        game.log.append(
            f"{context.card.name} exiled {victim.name}'s graveyard "
            f"({len(exiled)} card(s))"
        )
    return True, "resolved"


@effect_handler("exile_graveyard_position")
def exile_graveyard_position(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile the bottom card of target player's graveyard." (Phyrexian
    Furnace.) The same handler runs the price of Barrow Ghoul's and Circling
    Vultures' "unless you exile the top creature card of your graveyard",
    which the board family decomposes into a ``May`` around this instruction.

    Which cards is ``graveyard_order.positions_named`` — the one scan, shared
    with the activation-cost payment path, so a phrase read as a cost and the
    same phrase read as an effect cannot name different cards. It answers with
    *indices* rather than cards because two copies of one card in one graveyard
    are the same Python object, and an identity filter over the list would take
    both.

    A pile with nothing the phrase names exiles nothing and still resolves:
    CR 608.2 finishes what it can, and an effect is not a cost. The **cost**
    reading of the same phrase refuses instead, which is CR 118.3 and lives at
    the payment site.
    """
    from ..graveyard_order import positions_named

    owner = instruction.payload.get("owner", "you")
    victim = (
        context.caster if owner == "you"
        else (context.target if context.target is not None else context.caster)
    )
    taken = positions_named(victim.graveyard, dict(instruction.payload))
    exiled = [victim.graveyard[index] for index in taken]
    # Highest index first: the positions were found against the pile as it
    # stands, and removing a lower one renumbers every position above it.
    for index in sorted(taken, reverse=True):
        del victim.graveyard[index]
    # A graveyard is its owner's and so is the exile zone (CR 404.1, CR 406.1),
    # so the cards go from one to the other with no CR 400.3 lookup.
    victim.exile.extend(exiled)
    if exiled:
        game.log.append(
            f"{context.card.name} exiled "
            + ", ".join(card.name for card in exiled)
            + f" from the {instruction.payload.get('position', 'top')} of "
            f"{victim.name}'s graveyard"
        )
    else:
        game.log.append(
            f"{victim.name}'s graveyard has nothing {context.card.name} can exile"
        )
    context.results["exiled_cards"] = exiled
    return True, "resolved"


@effect_handler("exile_cost_sacrifices")
def exile_cost_sacrifices(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…, then exile this artifact and those creature cards." (Sword of the
    Ages.)

    Everything the ability's own cost sacrificed, taken out of the graveyard the
    sacrifice put it in. CR 601.2h paid that cost before the ability reached the
    stack, so there is no battlefield step here and no permanent to move — each
    is a *card* now (CR 400.7), found in its **owner's** graveyard, which is not
    always the seat that controlled it.

    Each card is matched by object identity, never by name: two copies of the
    same creature in one graveyard are two cards, and exiling "a Grizzly Bears"
    would be free to take the wrong one.

    A cost that ate nothing but the source exiles just the source, which is what
    "any number of creatures" and none of them means.
    """
    cards = [
        permanent.card
        for permanent in ((context.choices or {}).get("sacrificed_set_for_cost") or ())
    ]
    source = context.source_permanent
    if source is not None:
        cards.append(source.card)
    exiled: list[str] = []
    for card in cards:
        for player in game.players:
            index = next(
                (i for i, held in enumerate(player.graveyard) if held is card), None
            )
            if index is not None:
                player.exile.append(player.graveyard.pop(index))
                exiled.append(card.name)
                break
    game.log.append(
        f"{context.card.name} exiled {', '.join(exiled)}"
        if exiled
        else f"{context.card.name}: nothing it sacrificed is still in a graveyard"
    )
    return True, "resolved"


@effect_handler("exile_target_graveyard_card")
def exile_target_graveyard_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile target card from a graveyard." (Return to Nature's third mode,
    which used to resolve having done nothing.)

    No permanent is involved, so none of the battlefield machinery applies: the
    card is popped out of the graveyard it is in and appended to that same
    player's exile — a graveyard is an owner's zone (CR 404.1), so CR 400.3
    needs no separate lookup.
    """
    card = context.card
    owner = context.target if context.target is not None else context.caster
    # **Last-known information is frozen at the fire site** (CR 608.2h, ROADMAP
    # idiom #6). "If it was a creature card" is asked after the card has left
    # the graveyard, so the answer is recorded here, as the card is taken, not
    # re-read from the exile pile at the next step — where another effect's
    # exile would answer for this one.
    context.results["exiled_cards"] = []
    index = context.target_permanent_index
    if not (isinstance(index, int) and 0 <= index < len(owner.graveyard)):
        # Honour the choice, else take the first legal one — the same fallback
        # pick_target_permanent uses, so a stale choice does not fizzle an
        # effect the rest of the engine is not written to fizzle.
        owner = next((player for player in game.players if player.graveyard), owner)
        index = 0 if owner.graveyard else None
    if index is None:
        game.log.append(f"{card.name}: no card in any graveyard to exile")
        return True, "resolved"
    exiled = owner.graveyard.pop(index)
    owner.exile.append(exiled)
    context.results["exiled_cards"] = [exiled]
    game.log.append(f"{card.name} exiled {exiled.name} from {owner.name}'s graveyard")
    return True, "resolved"


@effect_handler("exile_graveyard_cards")
def exile_graveyard_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile all creature cards from your graveyard." (Zombie Mob.)

    The sweep the battlefield one beside it cannot be: CR 613.1 gives a card in
    a graveyard no computed characteristics at all, so what the noun phrase
    narrows by is answered by the *card* matcher — the same reader a discard
    cost and a graveyard target already share.

    Nothing is chosen and nothing is ordered: exile is an unordered zone
    (CR 406.2 orders no zone but the library and the graveyard), and "all" names
    the whole matching set. The pile is read once into a list before anything
    moves, because removing from a list while iterating it skips entries — and
    a graveyard holds several copies of a popular card under one name, so the
    survivors are rebuilt by *slot* rather than by value (idiom 11).
    """
    payload = instruction.payload
    who = str(payload.get("graveyard_owner") or "")
    if who == "each_player":
        seats = list(range(len(game.players)))
    elif who == "you":
        seats = [game.players.index(context.caster)]
    elif who == "target_player" and context.target in game.players:
        # "Exile all cards from **target player's** graveyard …" (Haunting
        # Echoes): the one pile the announcement chose (CR 601.2c).
        seats = [game.players.index(context.target)]
    else:
        game.log.append(f"{context.card.name}: no graveyard named")
        return True, "resolved"
    described = dict(payload.get("filter") or {})
    # "…all cards **with flashback**…" (Tombfire.) Carried beside the filter
    # rather than in it: whether a card has flashback is a printed keyword *or
    # a grant somebody made this turn* (Recoup), and the second half needs the
    # game and the seat, which the card matcher's keys are not about.
    with_keyword = payload.get("with_keyword")
    if with_keyword not in (None, "flashback"):
        # A keyword nothing here can test would be a narrowing dropped, and a
        # dropped narrowing on a sweep is the whole graveyard. The lowering
        # admits only the one; this is the second lock on the same door.
        game.log.append(
            f"{context.card.name}: no card in a graveyard is tested for "
            f"{with_keyword!r}"
        )
        return True, "resolved"
    from ..flashback import has_flashback
    # One entry per seat, **including the empty ones**, and seeded before
    # anything moves. The sentence behind this one is read once per player
    # ("puts all cards *they* exiled this way onto the battlefield"), so a seat
    # the map never mentioned would fall through to whatever a `.get` default
    # is — and the honest default for "what did this player exile" is an empty
    # pile, not somebody else's.
    by_seat = context.results.setdefault(EXILED_BY_SEAT, {})
    for seat in seats:
        by_seat.setdefault(seat, [])
    # The flat pair beside the per-seat map, seeded before anything moves for
    # the same reason: "you gain 1 life **for each card exiled this way**"
    # (Honor the Fallen) is a later step of this same resolution, and a sweep
    # that emptied every pile of nothing has to answer it with a zero rather
    # than with whatever a `.get` default is. Three records, three questions —
    # whose, how many, which — and the map cannot answer the last two without a
    # reader that knows its shape.
    all_taken: list = []
    context.results[EXILED_THIS_WAY_OBJECTS] = all_taken
    context.results[EXILED_THIS_WAY] = 0
    exiled = 0
    for seat in seats:
        owner = game.players[seat]
        taken_slots = [
            index for index, card in enumerate(owner.graveyard)
            if _card_matches_filter(card, described, game=game, owner=owner)
            and (
                with_keyword is None
                or has_flashback(card, game=game, owner_seat=seat)
            )
        ]
        if not taken_slots:
            continue
        taken = [owner.graveyard[index] for index in taken_slots]
        kept = [
            card for index, card in enumerate(owner.graveyard)
            if index not in set(taken_slots)
        ]
        owner.graveyard[:] = kept
        owner.exile.extend(taken)
        by_seat[seat].extend(taken)
        all_taken.extend(taken)
        exiled += len(taken)
        game.log.append(
            f"{context.card.name} exiled {len(taken)} card(s) from "
            f"{owner.name}'s graveyard"
        )
    context.results[EXILED_THIS_WAY] = exiled
    if not exiled:
        game.log.append(f"{context.card.name}: no card in that graveyard to exile")
    return True, "resolved"


def _exile_announced_graveyard_slots(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext,
    holder,
) -> tuple[bool, str]:
    """Exile the graveyard cards an announcement named, out of *holder*'s pile.

    The two announced piles of ``exile_cards_from_graveyard`` — the caster's
    own (Midnight Ritual) and the one a "single graveyard" announcement's seat
    names — through ``_resolve_graveyard_slots``, the reader the graveyard
    return uses for Shattered Crypt: a slot is not an identity, so each is
    resolved to its card before anything leaves and the removals run highest
    slot first. *holder* is None when the announcement named no pile at all,
    which exiles nothing — as an empty list of slots does.

    CR 400.3: an exiled card goes to its **owner's** exile, and a card's owner
    is the player whose graveyard held it.
    """
    count = instruction.payload.get("count")
    wanted = int(context.x_value or 0) if count == "x" else int(count or 1)
    taken = [] if holder is None else _resolve_graveyard_slots(
        holder, context, wanted,
        lambda card: graveyard_card_matches(instruction.payload, card),
    )
    if holder is not None:
        holder.exile.extend(taken)
        # "…return **the exiled cards** to their owner's graveyard."
        # (Gravegouger, whose entry trigger announces its cards and so resolves
        # here.) CR 607.2a: linked to the permanent whose ability exiled them,
        # exactly as the resolution-time pick links them
        # (``_resolve_graveyard_exile_pick``) — inert for a permanent no other
        # ability of which asks (Carrion Beetles), and nothing for a spell.
        source = context.source_permanent
        if source is not None:
            seat = game.players.index(holder)
            for card in taken:
                link_exiled_card(source, card, seat)
    context.results[EXILED_THIS_WAY_OBJECTS] = list(taken)
    context.results[EXILED_THIS_WAY] = len(taken)
    # The pile is named only where a card came out of it, or where the sentence
    # printed one: an "up to" announcement that named nothing named no
    # graveyard either, and the seat this resolution happens to be carrying is
    # not one the card chose.
    printed_pile = instruction.payload.get("graveyard_owner") == "you"
    game.log.append(
        f"{context.card.name} exiled "
        + (", ".join(card.name for card in taken) or "nothing")
        + (
            f" from {holder.name}'s graveyard"
            if holder is not None and (taken or printed_pile) else ""
        )
    )
    return True, "resolved"


@effect_handler("exile_cards_from_graveyard")
def exile_cards_from_graveyard(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…exile up to two target creature cards from defending player's
    graveyard." (Rysorian Badger.)

    The counted twin of ``exile_target_graveyard_card``, and a *prompt* rather
    than an announced list of targets: no picker in this engine names two cards
    in one graveyard, and a triggered ability's targets are chosen at
    resolution here (see the CR 608.2b entry in ROADMAP.md). The seat that
    would have announced them picks them instead, out of the same pile, as the
    ability resolves.

    Whose pile is the seat the *combat* named (CR 506.2), frozen into the
    trigger's context by the declare-attackers fire site — the same key the
    defending player's discard reads. A seat nobody recorded is not a pile to
    exile from: the attacker can have left combat by the time this resolves,
    and picking some other graveyard would be a card doing what it never said.

    ``exiled_this_way`` is written by the *answer*, not here, which is why the
    choice spec suspends: "you gain 1 life for each card exiled this way" is a
    later step of this same resolution and would read a zero otherwise.
    """
    owner = str(instruction.payload.get("graveyard_owner") or "")
    caster_index = game.players.index(context.caster)
    announced = bool(instruction.payload.get("targets"))
    # "Exile up to three **target** cards from a single graveyard." (Ebony
    # Charm, Rapid Decay, Decompose; Carrion Beetles' and Famished Ghoul's
    # activations; Gravegouger's entry trigger.) On a spell, an activated
    # ability and a triggered one the cards were named as the object was put
    # on the stack (CR 601.2c, CR 602.2b, CR 603.3d) and the pile is
    # the one the announcement's seat names — so this resolves the announced
    # slots, exactly as the caster's own pile does below, and asks nobody
    # anything. A card that left in response is not replaced (CR 608.2b's last
    # sentence): its slot arrives here as None and is skipped. Naming none is
    # the legal "up to" announcement and exiles nothing.
    if owner == "chosen" and announced:
        holder = next(
            (player for player in game.players if player is context.target), None
        )
        return _exile_announced_graveyard_slots(game, instruction, context, holder)
    # The same pile with **no** target description: chosen as the effect
    # resolves, and only where there is a choice to make. One pile with a
    # legal card in it is not a decision, and none at all is not a prompt —
    # offering either would be a question with one answer or with none, which
    # the seat then has to dismiss. No compiled card reaches this today: the
    # sentence prints "target" wherever it is printed, and under a trigger
    # (Gravegouger) the cards are announced as the ability is put on the stack
    # since Torment's second wave, so this resolves the announced branch above.
    if owner == "chosen":
        piles = game.graveyard_piles_with_a_legal_card(dict(instruction.payload))
        if not piles:
            game.log.append(
                f"{context.card.name}: no graveyard holds a card it can exile"
            )
            context.results[EXILED_THIS_WAY_OBJECTS] = []
            context.results[EXILED_THIS_WAY] = 0
            return True, "resolved"
        if len(piles) == 1:
            game.arm_graveyard_exile_pick(
                caster_index, piles[0], dict(instruction.payload), context
            )
        else:
            game.arm_graveyard_pile_choice(
                caster_index, dict(instruction.payload), context
            )
        return True, "resolved"
    # "Exile **X target** creature cards from **your** graveyard." (Midnight
    # Ritual.) The one pile of the three whose seat is known when the spell goes
    # on the stack, so the cards are *announced* (CR 601.2c) rather than chosen
    # as it resolves — which is why this is the branch that resolves slots
    # instead of arming a prompt.
    #
    # Through ``_resolve_graveyard_slots``, the same reader the graveyard return
    # uses for Shattered Crypt's identical "X target … cards from your
    # graveyard": a graveyard slot is not an identity (two copies of one card in
    # one pile are literally one ``CardDefinition``), so what tells them apart is
    # the order of removal, and a second copy of that reasoning here is how one
    # of the two ends up popping the wrong card.
    #
    # A count of zero is a legal outcome, not a reason to guess: X may be 0, and
    # CR 608.2b says an announcement naming nothing exiles nothing.
    #
    # "…you may exile **a land card from your graveyard**" (Forgotten Harvest)
    # prints no "target", so nothing was announced: the lowering emits no
    # ``targets`` description and the controller picks as it resolves, through
    # the same prompt the other two piles use.
    if owner == "offered_player" and not instruction.payload.get("targets"):
        # "Target opponent may exile a card from **their** graveyard."
        # (Gravestorm.) The seat the offer was made to — which the offer left
        # in ``context.target`` — picks out of its own pile. Nobody recorded
        # is not a pile to exile from.
        seat = next(
            (index for index, player in enumerate(game.players)
             if player is context.target),
            None,
        )
        if seat is None:
            game.log.append(f"{context.card.name}: no player was offered the exile")
            return True, "resolved"
        game.arm_graveyard_exile_pick(seat, seat, dict(instruction.payload), context)
        return True, "resolved"
    if owner == "you" and not instruction.payload.get("targets"):
        game.arm_graveyard_exile_pick(
            caster_index, caster_index, dict(instruction.payload), context
        )
        return True, "resolved"
    if owner == "you":
        return _exile_announced_graveyard_slots(
            game, instruction, context, context.caster
        )
    # The two seats a firing event froze, each read off the key its fire site
    # stamps: CR 506.2's defender, and — "target card from **that player's**
    # graveyard" on a damage trigger (Zombie Cannibal) — the player the damage
    # was dealt to, which is the key ``mill_target_player`` reads for the same
    # words.
    seat_key = {
        "defending_player": "trigger_defending_player_index",
        "damaged_player": "defending_player_index",
    }.get(owner)
    if seat_key is None:
        game.log.append(f"{context.card.name}: no graveyard named")
        return True, "resolved"
    seat = (context.trigger_context or {}).get(seat_key)
    if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
        game.log.append(
            f"{context.card.name}: no {owner.replace('_', ' ')} was recorded"
        )
        return True, "resolved"
    game.arm_graveyard_exile_pick(
        caster_index, seat, dict(instruction.payload), context
    )
    return True, "resolved"


@effect_handler("exile_creature_gain_life_equal_to_power")
def exile_creature_gain_life_equal_to_power(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    card = context.card
    # Swords to Plowshares: exile target creature; its controller gains life = its power
    target_perm_idx = context.target_permanent_index
    exiled_perm: Permanent | None = None
    if isinstance(target_perm_idx, int) and 0 <= target_perm_idx < len(target.battlefield):
        candidate = target.battlefield[target_perm_idx]
        if candidate.is_creature:
            exiled_perm = candidate
            game.remove_from_battlefield(candidate)
    if exiled_perm is None:
        for perm in list(game.controlled_by(target)):
            if perm.is_creature:
                exiled_perm = perm
                game.remove_from_battlefield(perm)
                break
    if exiled_perm is not None:
        target.exile.append(exiled_perm.card)
        life_gain = exiled_perm.effective_power
        game.log.append(f"{exiled_perm.card.name} exiled by {card.name}")
        game._gain_life(target, life_gain, card.name)
    else:
        game.log.append(f"{card.name}: no valid creature to exile")
    return True, "resolved"


@effect_handler("exile_graveyard_arrivals_this_turn")
def exile_graveyard_arrivals_this_turn(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"If a card would be put into your graveyard from anywhere this turn,
    exile that card instead." (Yawgmoth's Will.)

    CR 614 for a window. The marker goes on the seat and the interceptor in
    ``engine/replacements.py`` reads it — the arrangement Disintegrate's
    "if it would die this turn" already has on a permanent, one object wider —
    because a sorcery is on no battlefield when the replacement is meant to
    apply, and the static reading of the same sentence works by scanning
    battlefields for the text.

    The seat is the spell's controller: "your graveyard" is CR 109.5's, and the
    lowering refuses every other printed scope rather than arming a record whose
    seat the interceptor could not answer.

    Swept with the rest of the turn (``turn_management``'s cleanup loop), which
    is CR 514.2 and the same place every other "this turn" record forgets.
    """
    context.caster.exile_cards_bound_for_graveyard_this_turn = True
    game.log.append(
        f"{context.caster.name}'s cards will be exiled instead of going to "
        "their graveyard this turn"
    )
    return True, "resolved"


@effect_handler("exile_all_matching")
def exile_all_matching(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile each permanent with mana value X or less that's one or more
    colors." (Ugin, the Spirit Dragon's −X.) A sweep, not a destruction:
    indestructible does not save anything and no dies-trigger fires. Each
    card goes to its owner's exile (CR 400.3)."""
    payload = instruction.payload
    bound = payload.get("mana_value")
    x_value = int(context.x_value or 0)

    # Every narrowing the noun phrase printed except the two the lowering
    # lifted off it. They are separated *here*, once, rather than inside the
    # loop: `mana_value` may be the spell's X, which is not a number until this
    # resolution, and `colored_only` asks about the computed colours rather
    # than about a named one — neither is a question the pure matcher answers.
    narrowings = {
        key: value for key, value in payload.items()
        if key not in ("mana_value", "colored_only", "name_from_event")
    }
    # "…exile all tokens **with the same name as that creature**." (Dual
    # Nature.) CR 201.2's comparison against the name the firing event froze —
    # the creature has left the battlefield by now (CR 400.7), so the id beside
    # it resolves to nothing and the name is the one thing the sentence still
    # has. The destroy sweep's reading of the same key, for Eye of Singularity.
    #
    # No name ends the resolution: a dropped narrowing on a sweep is not a card
    # that does less, it is one that exiles every token on the table.
    event_name: str | None = None
    if payload.get("name_from_event"):
        event_name = (context.trigger_context or {}).get("event_subject_name")
        if not event_name:
            game.log.append(f"{context.card.name}: no name for 'that name' to be")
            return True, "resolved"

    # "Exile all creatures **blocked by this creature**." (Wall of Nets.) A
    # relation to the ability's own source, which the pure matcher cannot
    # answer and silently drops — on a sweep that is every creature on the
    # table. ``subject_matches`` is the one reader that can, and it takes the
    # source and the observer this resolution already holds, so the whole
    # payload goes through it rather than one key being special-cased. A spell
    # has no source permanent, which is the direction that refuses rather than
    # widens: ``blocked_by_source`` with nothing to compare against matches
    # nobody.
    from ..subject_filters import subject_matches

    observer = (
        game.players.index(context.caster)
        if context.caster in game.players else None
    )
    source_permanent = context.source_permanent

    def matches(perm: Permanent) -> bool:
        if narrowings and not subject_matches(
            game, perm, narrowings, observer=observer, source=source_permanent
        ):
            return False
        if event_name is not None and perm.effective_card.name != event_name:
            return False
        if payload.get("colored_only") and not perm.effective_colors:
            return False
        if bound is not None:
            raw = bound.get("value")
            limit = x_value if raw == "x" else int(raw)
            value = perm.effective_card.cmc or 0
            op = bound.get("op")
            if op == "le" and not value <= limit:
                return False
            if op == "ge" and not value >= limit:
                return False
            if op == "eq" and not value == limit:
                return False
        return True

    victims = [perm for perm in game.all_permanents() if matches(perm)]
    # Who controlled each of them, read **before** the sweep (CR 608.2h /
    # idiom 6): "For each creature exiled this way, its controller draws a
    # card" (Martyr's Cry) asks about a permanent that no longer exists by the
    # time the loop runs, and CR 400.7 makes the exiled card a new object with
    # no controller at all.
    controllers = {
        perm.permanent_id: seat
        for perm in victims
        for seat in (game.controller_index_of(perm),)
        if seat is not None
    }
    # …and who **owned** each of them, read in the same place and for a reason
    # one relation over (CR 108.3): "each player chooses one of the exiled cards
    # and puts it onto the battlefield under their control" (Thieves' Auction)
    # gives the card to somebody who does not own it, and after CR 400.7 there
    # is no object left to ask. Filled in the loop below, where the owner is
    # already being resolved to route the card to the right pile.
    owners: dict[int, int] = {}
    for perm in victims:
        owner_idx = game.owner_index_of(perm)
        if owner_idx is not None:
            owners[perm.permanent_id] = owner_idx
        owner = game.players[owner_idx] if owner_idx is not None else context.caster
        if not perm.metadata.get("is_token", False):
            owner.exile.append(perm.card)
            # Recorded as exiled **with** the ability's source when there is one
            # (CR 610.3), exactly as ``exile_top_of_library`` records its pile
            # and for that handler's stated reason: nothing ends the link on its
            # own — the entries carry no ``ends_on`` — so it is inert for Ugin
            # and it is everything for Wall of Nets, whose leaves-the-
            # battlefield ability ("return all cards exiled with it") is the
            # only thing that ever moves the pile. A token is not recorded
            # because it simply ceases to exist (CR 111.7) and there is no card
            # to give back.
            if source_permanent is not None and owner_idx is not None:
                link_exiled_card(source_permanent, perm.card, owner_idx)
        game._remove_aura_effects(perm)
    game.remove_all_from_battlefield(victims)
    context.results[EXILED_THIS_WAY_OBJECTS] = victims
    context.results[EXILED_THIS_WAY] = len(victims)
    context.results[PER_OBJECT_SEAT_RECORDS["controller"]] = controllers
    context.results[SWEPT_OWNER_SEATS] = owners
    game.log.append(f"{context.card.name} exiled {len(victims)} permanent(s)")
    return True, "resolved"


@effect_handler("exile_top_of_library")
def exile_top_of_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile the top three cards of your library." (Chandra, Heart of Fire's
    +1.) The exiled cards are recorded under ``exiled_cards`` for the same
    resolution's "you may play cards exiled this way" to read — the exile is
    what makes that sentence mean anything.

    They are *also* recorded as exiled **with** the ability's source, when the
    source is a permanent (CR 610.3, engine/linked_exile.py). Nothing ends that
    link on its own — the entries carry no ``ends_on`` — so it is inert for
    Chandra and it is everything for Knowledge Vault, whose other two abilities
    are the only things that ever move the pile.

    ``face down`` (CR 406.3) needs that record to mean anything: two copies of
    one card in a deck are the same ``CardDefinition`` object, so the record of
    the exiling is the only sound answer to "which exiled card is hidden".

    **A spell has no permanent to hold that record**, and used to refuse the
    whole exile for want of one — which made "Exile the top three cards of your
    library face down" (Three Wishes) a sentence that compiled, lowered and did
    nothing. The register that answers for an exiler which never becomes a
    permanent is ``engine/exiled_records.py``, whose whole argument is this one:
    the identity of the exiled object is the record. So the fact goes there when
    there is no permanent and onto the permanent when there is, and
    ``linked_exile.face_down_exiled_cards`` reads both.
    """
    caster = context.caster
    amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    face_down = bool(instruction.payload.get("face_down"))
    source = context.source_permanent
    owner_index = game.players.index(caster)
    exiled = []
    for _ in range(min(amount, len(caster.library))):
        card = caster.library.pop(0)
        caster.exile.append(card)
        exiled.append(card)
        if source is not None:
            link_exiled_card(source, card, owner_index, face_down=face_down)
        elif face_down:
            record_exiled_card(game, card, owner_index, face_down=True)
    context.results["exiled_cards"] = exiled
    if exiled:
        game.log.append(
            f"{caster.name} exiled {', '.join(card.name for card in exiled)} "
            "from the top of their library"
        )
    else:
        game.log.append(f"{caster.name} has no cards left to exile")
    return True, "resolved"


@effect_handler("exile_entire_library")
def exile_entire_library(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"That player exiles all cards from their library." (Thought Lash, when
    its cumulative upkeep goes unpaid.)

    The whole zone, in order, so a later effect that could look at the pile
    sees what was on top. It does **not** end the game by itself: CR 704.5b
    makes a player lose only when they would draw from an empty library, which
    is the next draw step — so this leaves the seat alive with nothing to draw,
    exactly as the card reads.

    A seat the trigger did not freeze is a card acting on the wrong player, so
    an unresolvable recipient does nothing rather than falling back to the
    resolving seat: emptying the wrong library is the game, not a smaller
    effect.
    """
    recipient = str(instruction.payload.get("recipient", "caster"))
    if recipient == "caster":
        victim = context.caster
    else:
        seat = frozen_that_player_seat(game, context)
        if seat is None:
            game.log.append(
                f"{context.card.name}: no player was named to empty a library"
            )
            return True, "resolved"
        victim = game.players[seat]
    emptied = list(victim.library)
    victim.library.clear()
    victim.exile.extend(emptied)
    game.log.append(
        f"{victim.name} exiled their whole library "
        f"({len(emptied)} card(s)) to {context.card.name}"
    )
    return True, "resolved"


@effect_handler("exile_bound_card_from_graveyard")
def exile_bound_card_from_graveyard(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Necropotence: "Whenever you discard a card, exile that card from your
    graveyard."

    The card the discard announced, located by **identity** in the graveyard it
    was put into. A name match would find the wrong copy: a graveyard is a list
    of ``CardDefinition`` and every copy of a card in a deck is the same
    immutable object.

    Gone by the time this resolves — exiled in response, or moved by a
    replacement that sent the discard somewhere other than the graveyard
    (Library of Leng) — means the ability does nothing, which is CR 603.6's
    answer rather than a failure.
    """
    card = (context.trigger_context or {}).get("discarded_card")
    if card is None:
        return True, "resolved"
    owner = context.caster
    for index, held in enumerate(owner.graveyard):
        if held is card:
            owner.graveyard.pop(index)
            owner.exile.append(card)
            game.log.append(
                f"{card.name} was exiled from {owner.name}'s graveyard "
                f"({context.card.name})"
            )
            return True, "resolved"
    game.log.append(f"{card.name} was no longer in {owner.name}'s graveyard")
    return True, "resolved"


@effect_handler("exile_any_number_of_own_tokens")
def exile_any_number_of_own_tokens(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Tetravus: "Exile **any number of** tokens created with this creature."

    The set is found here rather than picked by a target picker, because the
    phrase names no target at all (CR 115.10a) — it names a set the game can
    identify, and asks its controller how many of it to take.

    **How many, not which.** Every token in that set was made by the same
    ability off the same permanent with the same characteristics, so which ones
    go is not a difference the game can observe; the ones taken are the
    oldest first, by `permanent_id`, so a replay is a replay. A card whose
    tokens could differ from one another would need a real picker, which is why
    the lowering admits this phrase and nothing wider.
    """
    source = context.source_permanent
    if source is None:
        return True, "resolved"
    owned = tokens_created_with(game, source)
    seat = game.controller_index_of(source)
    if seat is None or not owned:
        context.results["trigger_count"] = 0
        return True, "resolved"
    game.arm_pending_choice(
        "number_choice", seat,
        card_name=source.card.name, permanent=source,
        minimum=0, maximum=len(owned),
        # The "may" in front of the sentence already asked whether to do this
        # at all; a seat that got here said yes, so the default takes all of
        # them rather than making the answer mean nothing.
        default_number=len(owned),
        exile_own_tokens=True, results=context.results,
    )
    return True, "resolved"
