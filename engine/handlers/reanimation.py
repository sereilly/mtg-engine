"""A card put onto the battlefield from a graveyard: reanimation.

The half of ``engine/grammar/lowering/returns.py`` that lands on the
battlefield, under the engine's own word for it (``reanimate_creature``,
:data:`REANIMATED_PERMANENTS`). A target card, a card a trigger bound (Seraph),
the ability's own source (Takklemaggot, Silversmote Ghoul), a graveyard position
(Bone Dancer), announced cards (Victimize), a card at random (Search for
Survivors), a sweep that returns Auras attached to the hosts chosen for them
(All Hallow's Eve, Replenish), and Goblin Welder's simultaneous exchange.

Split out of ``zones.py`` at the 2,000-line cap's split round. A return to a
**hand** is ``returns.py``'s.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from ..auras import PUT_ONTO_BATTLEFIELD_BY
from ..keywords import grant_keyword
from ..models import Permanent
from ..replacements.zone_changes import EXILE_ON_LEAVING_BATTLEFIELD
from ..resumption import run_resumable
from ..search_filters import card_has_type
from ._filters import _card_matches_filter, graveyard_card_matches
from ._targets import (_resolve_graveyard_slots, resolve_role_graveyard_card,
                       resolve_role_permanent, roles_still_legal)
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


#: The scratchpad key a reanimation records its arrival under. Spelled again in
#: ``grammar/lowering/_events.py`` rather than imported across the seam, and
#: held to it by ``lowering/_records._PRODUCES`` — the same arrangement the
#: tap's ``tapped_permanents`` has.
REANIMATED_PERMANENTS = "reanimated_permanents"


def _holds_a_reanimable_card(player, index, card_filter, card_type="creature") -> bool:
    """Whether *player*'s graveyard holds a card of *card_type* this effect may
    take.

    With *index* given, the question is only about that slot — the announced
    target — because a named target that is legal settles where the card comes
    from and no search happens at all.
    """
    graveyard = getattr(player, "graveyard", ())

    def eligible(card) -> bool:
        return card_has_type(card, card_type) and (
            card_filter is None or card_filter(card)
        )

    if isinstance(index, int):
        return 0 <= index < len(graveyard) and eligible(graveyard[index])
    return any(eligible(card) for card in graveyard)


def _reanimable_slot(player, card_filter, card_type="creature"):
    """The first slot of *player*'s graveyard this effect may take, or nothing.

    A generator so the caller can write one ``next`` over seats and slots
    together: an empty pile contributes no slot rather than a None to filter
    out afterwards.
    """
    for index, card in enumerate(getattr(player, "graveyard", ())):
        if card_has_type(card, card_type) and (
            card_filter is None or card_filter(card)
        ):
            yield index
            return


def _entering_characteristics(payload: dict, context: OracleExecutionContext):
    """What a reanimated permanent enters as, as a function of the arrival —
    or None when the sentence says nothing about it.

    "That creature is black and is a Nightmare in addition to its other
    creature types." (Chainer, Dementia Master.) Its ruling (2022-12-08):
    "black only, not black in addition to its other colors … a Nightmare in
    addition to its other creature types … As it enters the battlefield, it is
    already a black Nightmare." So the colour is a layer-5 *set* through the
    colour seam and the type a layer-4 *addition* through the type seam, both
    indefinite (no duration is printed, CR 611.2a), both written before the
    permanent enters. Each write stamps its own timestamp (CR 613.7b), so a
    later colour or type effect still applies over it.
    """
    colors = tuple(payload.get("entering_colors") or ())
    subtypes = tuple(payload.get("entering_subtypes") or ())
    if not colors and not subtypes:
        return None
    from ..color_changes import change_color
    from ..type_changes import gain_types

    source_name = context.card.name if context.card is not None else "effect"

    def write(permanent) -> None:
        if colors:
            change_color(permanent, colors[0] if len(colors) == 1 else colors)
        if subtypes:
            gain_types(
                permanent, subtypes=subtypes, source=source_name,
                duration="permanent",
            )

    return write


@effect_handler("reanimate_creature")
def reanimate_creature(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    # Resurrection returns "target creature card from your graveyard", so the chosen
    # index is into the caster's own graveyard regardless of which seat the UI tags.
    # "…from a graveyard" (Liliana, Waker of the Dead's emblem) widens the source
    # to the chosen player's graveyard; "under your control" is already how
    # _reanimate_creature_to_battlefield puts it into play for the caster.
    idx = context.target_permanent_index
    idx = idx if isinstance(idx, int) else None
    # "Return target **artifact** card from your graveyard to the battlefield."
    # (Argivian Restoration.) Which kind of card comes back is the sentence's
    # own word and rides the payload; "creature" is what every printing before
    # it said, so a payload written without the key means exactly what it did.
    # Every reader of it below goes through ``card_has_type`` — CR 205.2a gives
    # a card every type its line names, and ``primary_type`` picks one of them
    # by the order of a list, which is what made an Artifact Creature card
    # invisible to a phrase naming an artifact.
    card_type = str(instruction.payload.get("card_type", "creature"))
    # "Return **the top** creature card of your graveyard to the
    # battlefield." (Shallow Grave.) CR 404.1 puts an arriving card on *top* of
    # its owner's graveyard and CR 404.2 keeps the pile in that order, and this
    # engine appends — so the top card is the last entry, the most recently
    # added, and "the top creature card" is the last one of them. Nobody
    # chooses, so any index the wire happened to carry is not this effect's: it
    # is overwritten rather than preferred.
    #
    # (CR 404.3 is the *simultaneous-arrival* tie-break and is not this rule;
    # ``engine/graveyard_order.py`` records the correction and the W1G1 report
    # lists the sites that copied it.)
    if instruction.payload.get("from_top"):
        idx = next(
            (
                slot
                for slot in range(len(caster.graveyard) - 1, -1, -1)
                if card_has_type(caster.graveyard[slot], card_type)
            ),
            None,
        )
        if idx is None:
            game.log.append(
                f"{context.card.name}: no {card_type} card in the graveyard"
            )
            context.results[REANIMATED_PERMANENTS] = ()
            return True, "resolved"
    any_graveyard = bool(instruction.payload.get("any_graveyard"))
    source_player = caster
    if any_graveyard and context.target is not None:
        source_player = context.target
    # "target **white or black** creature card" (Dreams of the Dead). Applied
    # here as well as at announcement, through the one predicate the picker and
    # the activation gate ask (`graveyard_card_matches`) — a picker and a
    # resolution that disagree are a target the player may announce and the
    # effect then declines to affect. A card with no printed colour hands over
    # no filter at all, so every reanimation written before this is unchanged.
    colors = tuple(instruction.payload.get("colors") or ())
    # "target **Aura** card from a graveyard" (Iridescent Drake). CR 205.3b: a
    # subtype, carried on the key ``graveyard_card_matches`` reads it under, so
    # the same predicate answers the colour narrowing beside it. The two are
    # gathered into one spec rather than into two lambdas because a card must
    # satisfy every word the phrase printed.
    subtypes = tuple(instruction.payload.get("graveyard_subtypes") or ())
    spec: dict[str, object] = {}
    if colors:
        spec["graveyard_colors"] = list(colors)
    if subtypes:
        spec["graveyard_subtypes"] = list(subtypes)
    if spec:
        # The type word travels with the narrowings rather than being left to
        # the predicate's default. ``graveyard_card_matches`` ends "a spec that
        # names no type is about a creature card" — right for the reanimation
        # Auras it was written for, and wrong for "target **Aura** card", whose
        # subtype narrows a phrase that names no card type at all: the subtype
        # test passed and the creature default then refused every Aura in the
        # pile. Written as the word this handler is already searching by, so
        # the two readers ask one question; a payload with no ``card_type`` key
        # spells "creature" here exactly as the default did.
        spec["card_type"] = card_type
    # "…onto the battlefield under your control **attached to this creature**."
    # (Iridescent Drake.) CR 303.4g: an Aura entering with no legal object to
    # enchant *remains in its current zone* — so the host is not a step behind
    # the move, it is part of which cards this sentence can move at all, and it
    # therefore rides the same filter the picker and the resolution share.
    #
    # A source that has left the battlefield names no host, so 303.4g leaves
    # nothing that could legally arrive: the effect does nothing rather than
    # putting an Aura into play attached to nothing for the next state-based
    # sweep to bin (CR 704.5m).
    attach_host = None
    if instruction.payload.get("attach_to") == "source":
        attach_host = context.source_permanent
        if attach_host is None or not game.is_on_battlefield(attach_host):
            game.log.append(
                f"{context.card.name}: it is no longer on the battlefield"
            )
            context.results[REANIMATED_PERMANENTS] = ()
            return True, "resolved"
    card_filter = None
    if spec or attach_host is not None:
        from ..auras import enchant_card_refusal

        caster_seat = (
            game.players.index(caster) if caster in game.players else None
        )

        def card_filter(card, _spec=spec, _host=attach_host, _seat=caster_seat):
            if _spec and not graveyard_card_matches(_spec, card):
                return False
            if _host is None:
                return True
            # The one enchant gate the cast, the sweep and both pickers ask —
            # so "can this Aura enchant that creature?" has one answer here as
            # everywhere else.
            return (
                _seat is not None
                and enchant_card_refusal(game, card, _seat, _host) is None
            )
    if any_graveyard and (
        idx is None
        or not _holds_a_reanimable_card(source_player, idx, card_filter, card_type)
    ):
        # **No card was named** — or the one that was is not one this effect
        # may take. The index fallback below searches the *caster's* graveyard,
        # which is right for "from your graveyard" and blind for "from a
        # graveyard": an AI seat announces the effect without picking a slot, so
        # Hymn of Rebirth resolved and put nothing onto the battlefield whenever
        # the only creature card was in someone else's pile. The order is the
        # Aura printing's, which has searched this way all along
        # (``mixins/oracle_instructions.py``): the named seat, then the caster,
        # then everyone else.
        #
        # Asked whenever no slot was named, and not only when the named seat
        # holds nothing. It read the second way, and that left one case
        # unsearched: a seat *other than the caster* named, holding a card. The
        # seat passed the test, no slot was recorded, and the fallback below
        # then looked in the caster's pile regardless — the wrong pile, or
        # none. Nothing reached it while an entry trigger nobody announced for
        # ran with its own controller as "the target player"; as a stack
        # object it takes the default every other trigger takes, an opponent,
        # and a Necromancy put onto the battlefield with the only creature card
        # in that opponent's graveyard returned nothing.
        found = next(
            (
                (player, slot)
                for player in (source_player, caster, *game.players)
                for slot in _reanimable_slot(player, card_filter, card_type)
            ),
            None,
        )
        if found is not None:
            # The slot travels with the seat. The fallback one level down
            # searches the *caster's* pile by construction — right for every
            # other reanimation, and the reason the seat alone would not have
            # been enough here.
            source_player, idx = found
    reanimated = game._reanimate_creature_to_battlefield(
        caster, source_player, idx, card_filter=card_filter, card_type=card_type,
        entering_as=_entering_characteristics(instruction.payload, context),
    )
    # "enchant creature **put onto the battlefield with Necromancy**" — the
    # relation that clause is about, stamped by the step that performs it
    # because nothing else can say so: the ability's target was a *card* in a
    # graveyard, and CR 400.7 makes what arrived a new object with no history on
    # the board. `auras.enchant_card_refusal` reads it back. Unconditional: a
    # permanent nobody asks the question about carries a spare id, where a
    # permanent the question *is* asked about and that was not stamped would be
    # a legal host the card never allowed.
    if reanimated is not None and context.source_permanent is not None:
        reanimated.metadata[PUT_ONTO_BATTLEFIELD_BY] = (
            context.source_permanent.permanent_id
        )
    # "It gains haste." — folded into the reanimation because the permanent
    # does not exist until this step runs, and read off the arrival itself
    # rather than off "the newest permanent the caster controls", which an
    # enters-trigger creating a token makes wrong.
    # "…**attached to this creature**." (Iridescent Drake.) CR 303.4f attaches
    # the Aura as part of the same move, inside this one resolution — nothing
    # checks state-based actions between the arrival and this line, so the Aura
    # is never an unattached one for CR 704.5m to find. Through ``attach_aura``,
    # which stamps the CR 613.7e timestamp and records both directions.
    if reanimated is not None and attach_host is not None:
        from ..auras import attach_aura

        attach_aura(reanimated, attach_host)
    gains = tuple(instruction.payload.get("gains") or ())
    if reanimated is not None and gains:
        for keyword in gains:
            grant_keyword(reanimated, keyword)
    # "If the creature would leave the battlefield, exile it instead of putting
    # it anywhere else." (Dreams of the Dead.) Armed on the permanent this step
    # created, which is the only object the sentence can be about — the
    # ability's target is a card in a graveyard. The marker is what
    # `engine/replacements/zone_changes.py`'s `would_leave_battlefield` interceptor reads,
    # and it lives on the permanent rather than on the card because a
    # `CardDefinition` is shared between every copy of a card in a deck.
    if reanimated is not None and instruction.payload.get("exile_on_leave"):
        reanimated.metadata[EXILE_ON_LEAVING_BATTLEFIELD] = True
    # What this step put onto the battlefield, for the sentences that name it
    # afterwards ("that creature gains …"). By id, like every other producer:
    # the permanent may leave between two steps of one resolution, and a
    # returning one is a new object (CR 400.7).
    context.results[REANIMATED_PERMANENTS] = (
        (reanimated.permanent_id,) if reanimated is not None else ()
    )
    # "You lose life equal to **that card's mana value**." (Reanimate.) The
    # number frozen where the object still had it (CR 608.2h): the sentence
    # behind this one cannot go and look, because the ability's target was a
    # card in a graveyard and CR 400.7 makes what arrived a new object.
    #
    # Written **unconditionally**, zero when nothing came back. The lowering
    # admitted the phrase on the strength of this producer, so a resolution that
    # sometimes writes nothing is a reader that sometimes finds nothing, and
    # "nothing arrived" has a right answer: you lose no life. CR 202.3 off the
    # effective card, exactly as the destroy that shares this record does — a
    # permanent that entered as a copy has the copied cost.
    context.results["its_mana_value"] = (
        int(getattr(reanimated.effective_card, "cmc", 0) or 0)
        if reanimated is not None else 0
    )
    game.log.append(
        f"Reanimated {card_type} to battlefield" if reanimated is not None
        else f"No {card_type} to reanimate"
    )
    return True, "resolved"


@effect_handler("reanimate_aura_onto_source")
def reanimate_aura_onto_source(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Return target Aura card from your graveyard to the battlefield
    **attached to Hakim**." (Hakim, Loreweaver.)

    Its own handler rather than a rider on ``reanimate_creature``, because
    CR 303.4f makes the attachment part of the entry rather than a step after
    it: an Aura that entered attached to nothing is what CR 704.5m puts
    straight back in the graveyard, so a version that put the card down and
    then attached would be a card that works only when nothing looks in
    between.

    **The host is the ability's own source and nothing else.** It is read off
    ``context.source_permanent`` rather than off the board, because a permanent
    that has left between activation and resolution has no host to offer
    (CR 608.2b) — and picking some other creature would be an Aura landing
    where the card never said.

    Legality is ``auras.aura_attach_refusal``, the one predicate the cast gate,
    the CR 704.5m sweep and the two other resolutions ask. CR 303.4j: an
    attachment that would be illegal simply does not happen, and here that
    means the card stays in the graveyard — putting it onto the battlefield
    unattached would be strictly worse than not resolving, since the sweep
    would bin it and the card would be gone.
    """
    from ..auras import attach_aura, aura_attach_refusal

    caster = context.caster
    host = context.source_permanent
    if host is None or not game.is_on_battlefield(host):
        game.log.append(f"{context.card.name}: nothing to attach the Aura to")
        context.results[REANIMATED_PERMANENTS] = ()
        return True, "resolved"
    spec = dict(instruction.payload)
    idx = context.target_permanent_index
    if not (
        isinstance(idx, int)
        and 0 <= idx < len(caster.graveyard)
        and graveyard_card_matches(spec, caster.graveyard[idx])
    ):
        # The same order every other reanimation falls back through: an AI seat
        # announces the ability without naming a slot, so the first legal card
        # in the pile is the one this takes. A re-check rather than a trust,
        # for the reason `reanimate_creature` re-checks: a picker and a
        # resolution that disagree are a target the player may announce and the
        # effect then declines.
        idx = next(
            (
                slot
                for slot, card in enumerate(caster.graveyard)
                if graveyard_card_matches(spec, card)
            ),
            None,
        )
    if idx is None:
        game.log.append(f"{context.card.name}: no Aura card in the graveyard")
        context.results[REANIMATED_PERMANENTS] = ()
        return True, "resolved"
    aura_card = caster.graveyard[idx]
    arrival = Permanent(card=aura_card)
    refusal = aura_attach_refusal(game, arrival, host)
    if refusal is not None:
        game.log.append(
            f"{context.card.name}: {aura_card.name} cannot enchant "
            f"{host.card.name} ({refusal})"
        )
        context.results[REANIMATED_PERMANENTS] = ()
        return True, "resolved"
    caster.graveyard.pop(idx)
    game._put_permanent_onto_battlefield(
        game.seat_index(caster), arrival, None, from_zone="graveyard"
    )
    attach_aura(arrival, host)
    # CR 704.5m is asked at once, the way the attach handler asks it: layer
    # contributions are computed on read, so nothing has to be refreshed — but
    # an Aura that arrived on a host it may not stay on has to go now rather
    # than at the next sweep.
    game.check_state_based_actions()
    context.results[REANIMATED_PERMANENTS] = (arrival.permanent_id,)
    game.log.append(
        f"{aura_card.name} returned to the battlefield attached to "
        f"{host.card.name}"
    )
    return True, "resolved"


@effect_handler("reanimate_bound_card")
def reanimate_bound_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put that card onto the battlefield under your control." (Seraph,
    Krovikan Vampire.)

    ``return_bound_card_to_owners_hand`` with a different destination, and the
    same three reasons for every line of it: the bound object is the card of the
    creature whose death fired the trigger, the fire site froze the card itself
    (CR 603.10) because by resolution nothing else could name it, and it is
    located by identity and removed with ``pop`` at the found index — a name
    match finds the wrong entry in a graveyard holding two copies.

    Under **your** control, which CR 400.3 lets an effect say; ownership does
    not move, so the card goes back to its owner's graveyard when it next dies.
    ``control="owner"`` is the other seat the phrase can name — "return that
    card to the battlefield **under its owner's control**" (Abduction), where
    the Aura took the creature while it lived and gives it back when it dies.
    Absent, the payload means CR 110.2a's default, which is this seat.

    "Sacrifice the creature when you lose control of this creature" is the same
    sentence's second half, and it is recorded here rather than lowered as a
    step of its own: the rider names a permanent that does not exist until this
    instruction makes one. ``engine/linked_sacrifice.py`` holds the record and
    the state-based sweep re-checks it.
    """
    from ..damage_deaths import creatures_it_damaged_that_died
    from ..linked_sacrifice import link_sacrifice_to_source
    from ..models import Permanent

    if instruction.payload.get("from_damage_deaths"):
        # Krovikan Vampire's "that card" is the one its own intervening-if
        # found. **Every** one of them, when the ledger holds several: the
        # trigger fires once per end step and its condition asks whether *a*
        # creature died, so with two deaths the sentence names two cards and
        # nothing in it says which one to prefer. Reanimating the first would be
        # a choice the card never offers anybody.
        cards = creatures_it_damaged_that_died(context.source_permanent)
    else:
        card = (context.trigger_context or {}).get("dead_card")
        cards = [card] if card is not None else []
    context.results["reanimated_bound_card"] = False
    if not cards:
        game.log.append(
            f"{context.card.name}: no recorded card to put onto the battlefield"
        )
        return True, "resolved"
    controller_seat = game.players.index(context.caster)
    to_owner = instruction.payload.get("control") == "owner"
    for card in cards:
        for player in game.players:
            found = next(
                (i for i, held in enumerate(player.graveyard) if held is card), None
            )
            if found is None:
                continue
            owner_seat = game.players.index(player)
            # CR 404.1 put the card in its *owner's* graveyard, so the seat
            # holding it is the owner — which is what "under its owner's
            # control" names, found here rather than passed in because it is
            # the graveyard scan that discovers it.
            seat = owner_seat if to_owner else controller_seat
            player.graveyard.pop(found)
            permanent = Permanent(card=card)
            # CR 400.3: "under your control" moves control, never ownership, so
            # the card goes to its **owner's** graveyard when it next leaves.
            # Recorded on the permanent for the reason Animate Dead's
            # reanimation records it: the base controller is the owner
            # everywhere else in this pool, and here the two differ by
            # construction.
            if owner_seat != seat:
                permanent.metadata["owner_player_index"] = owner_seat
            game._put_permanent_onto_battlefield(seat, permanent, None)
            context.results["reanimated_bound_card"] = True
            if instruction.payload.get("sacrifice_when_control_lost"):
                source = context.source_permanent
                if source is not None:
                    link_sacrifice_to_source(permanent, source, seat)
            game.log.append(
                f"{card.name} entered the battlefield under "
                f"{game.players[seat].name}'s control ({context.card.name})"
            )
            break
        else:
            # CR 603.6: the ability looks for the object in the zone it moves it
            # out of. Exiled in response, or already reanimated by an earlier
            # firing of this same ability.
            game.log.append(f"{card.name} was no longer in a graveyard")
    return True, "resolved"


@effect_handler("return_source_card_to_battlefield")
def return_source_card_to_battlefield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Return this card to the battlefield under your control [attached to
    that creature] [as a non-Aura enchantment]." (Takklemaggot.)

    The ability's own source, printed with no source zone — the same reach
    ``return_source_card_to_owners_hand`` makes, and for its reason: by the time
    an Aura's death trigger resolves the CR 704.5m sweep has usually already put
    the card in a graveyard, but a caller that resolves the stack without an
    intervening priority pass finds it still on the battlefield, and a handler
    that looked in one zone would silently do nothing in the other.

    Every rider is payload, and each is recorded on the permanent as a *layer*
    contribution rather than applied: the lost subtype is layer 4
    (``type_changes.lose_types``), the lost and gained ability lines are layer 6
    (``keywords``), and both are read back by ``Permanent.effective_card`` and
    ``computed_types``. So the CR 704.5m sweep, the UI and the compiler all get
    one answer to "what is this permanent now?" — which is the whole reason the
    non-Aura half is not a flag the sweep checks for itself.
    """
    from ..auras import attach_aura, aura_attach_refusal
    from ..keywords import grant_ability_line, remove_ability_line
    from ..type_changes import lose_types

    card = context.card
    source = context.source_permanent
    seat = game.seat_index(context.caster)
    # "…under **its owner's** control." (Ivory Gargoyle.) CR 400.3's seat, which
    # is not the ability's controller for a creature that changed hands before
    # it died. Read off the *permanent* while there still is one and off the
    # graveyard that held the card once there is not — CR 404.3 puts a card in
    # its owner's graveyard, so the pile that had it names the owner. An absent
    # payload key is every card written before the phrase existed and keeps
    # meaning "you".
    owners_control = instruction.payload.get("control") == "owner"
    if instruction.payload.get("control") == "event_subject_controller":
        # "…**that creature's controller** returns this Aura … to the
        # battlefield." (Traveling Plague.) CR 110.2a: an object a player is
        # instructed to put onto the battlefield enters under that player's
        # control, and that is the seat the departing host's fire site froze — never re-derived,
        # because the host has no controller any more. With no seat recorded
        # nobody puts it anywhere.
        frozen = (context.trigger_context or {}).get("event_subject_controller")
        if not isinstance(frozen, int) or not 0 <= frozen < len(game.players):
            game.log.append(f"{card.name}: no controller was recorded to return it")
            return True, "resolved"
        seat = frozen
    if owners_control and source is not None:
        from ..control import base_controller

        # CR 108.3's answer, which this engine reads off the seat the permanent
        # *entered* under — never off where it currently sits, which is the
        # thief's side and the whole reason the card names the owner.
        owner = base_controller(source)
        if isinstance(owner, int):
            seat = owner
    if source is not None and game.is_on_battlefield(source):
        game.remove_from_battlefield(source)
    else:
        for player in game.players:
            for index, held in enumerate(player.graveyard):
                if held is card:
                    player.graveyard.pop(index)
                    if owners_control:
                        seat = game.seat_index(player)
                    break
            else:
                continue
            break
        else:
            # CR 603.6: the ability looks for the object in the zone it moves it
            # out of. Gone means the ability does nothing, rather than making a
            # second copy of the card.
            game.log.append(f"{card.name} was no longer in a graveyard")
            return True, "resolved"

    payload = instruction.payload
    permanent = Permanent(card=card)
    for subtype in payload.get("losing_subtypes") or ():
        lose_types(permanent, subtypes=[str(subtype)], source=card.name)
    for line in payload.get("losing_abilities") or ():
        remove_ability_line(permanent, line)
    for line in payload.get("gaining_abilities") or ():
        grant_ability_line(permanent, line[:1].upper() + line[1:])
    # Whose upkeep the granted trigger watches and who it hits: the seat this
    # resolution asked to choose. Recorded on the permanent because the ability
    # it was granted is compiled from the *permanent's* text, with no memory of
    # the resolution that granted it — the same channel Storm World's chosen
    # player already uses.
    chosen_seat = context.results.get("chosen_player")
    if isinstance(chosen_seat, int):
        permanent.metadata["chosen_player_index"] = chosen_seat

    game._put_permanent_onto_battlefield(seat, permanent, None)
    # "…return it to the battlefield under your control **and put a death
    # counter on it**." (Bogardan Phoenix.) The permanent this step created,
    # recorded by id for the sentence behind it — CR 400.7 makes it a *new
    # object*, so "it" cannot mean the one that died, and every other reader in
    # the resolution is still holding the dead one. The reanimation's own
    # channel, because the question is the reanimation's question asked of the
    # ability's own source.
    context.results.setdefault(REANIMATED_PERMANENTS, []).append(
        permanent.permanent_id
    )
    game.log.append(
        f"{card.name} returned to the battlefield under {game.players[seat].name}'s control"
    )

    host_key = payload.get("attached_to")
    if host_key:
        host = game.permanent_by_id(context.results.get(host_key))
        # CR 303.4j asked one more time at the move itself, over the same
        # predicate the picker used: a host chosen legally may have stopped
        # being one while the rest of this resolution ran.
        refusal = aura_attach_refusal(game, permanent, host)
        if refusal is None:
            attach_aura(permanent, host)
            game.log.append(f"{card.name} attached to {host.card.name}")
        else:
            game.log.append(f"{card.name} could not attach: {refusal}")
    return True, "resolved"


@effect_handler("return_self_from_graveyard")
def return_self_from_graveyard(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Return this card from your graveyard to the battlefield [tapped]."
    (Silversmote Ghoul; CR 113.6m.)

    The object is the ability's own source, so nothing is chosen and there is no
    target index to read. CR 108.4a decides whose graveyard is searched: a card
    in a graveyard has no controller, so the ability's "your" is its owner's seat
    — the seat the fire site enqueued it under.

    Located by **identity**, not by name and not by index. A graveyard is a list
    of ``CardDefinition`` and two copies of one card are the same immutable
    object, so a name match finds the wrong entry and a list-comprehension
    rebuild removes *both* — which is exactly what the Nether Shadow scan in
    ``phases/upkeep_step.py`` does today. ``pop`` at an identity-found index
    removes one.
    """
    caster = context.caster
    card = context.card
    # "{3}{U}, **Exile this creature**: … return this card to the battlefield."
    # (Shifty Doppelganger.) The zone is payload: the ability's own cost put
    # the source in exile, so that is the pile it comes back out of. Absent
    # means the graveyard, which is what every other card printing the
    # sentence means. Never both — a card that is not where its ability left
    # it is a new object (CR 400.7) and is not looked for anywhere else.
    zone = "exile" if instruction.payload.get("from") == "exile" else "graveyard"
    pile = caster.exile if zone == "exile" else caster.graveyard
    for index, held in enumerate(pile):
        if held is card:
            pile.pop(index)
            break
    else:
        # CR 603.6: the ability looks for the object in the zone it moves it out
        # of. Gone (exiled in response, shuffled away) means the ability does
        # nothing, rather than conjuring a second copy of the card.
        game.log.append(
            f"{card.name} was no longer in "
            + ("exile" if zone == "exile" else "the graveyard")
        )
        return True, "resolved"
    # "…to your **hand**." (Whiteout.) The destination is payload rather than a
    # second handler, because everything above it — the object is the ability's
    # own source, found by identity in the graveyard the ability functions from
    # — is the same work either way. Absent means the battlefield, which is what
    # every payload written before the hand spelling existed says.
    if instruction.payload.get("to") == "hand":
        # Through the write seam, so CR 903.9b rides it like every other
        # put-into-a-hand.
        if game.put_card_into_hand(caster, card):
            game.log.append(f"{card.name} returned from the graveyard to hand")
        return True, "resolved"
    tapped = bool(instruction.payload.get("tapped"))
    arrived = Permanent(card=card, tapped=tapped)
    game._put_permanent_onto_battlefield(
        game.players.index(caster), arrived, None
    )
    game.log.append(
        f"{card.name} returned from "
        + ("exile" if zone == "exile" else "the graveyard")
        + " to the battlefield"
        + (" tapped" if tapped else "")
    )
    # "…**with a +1/+1 counter on it**." (Sand Golem.) CR 121.2 puts the
    # counters on as the permanent arrives, so they go on *this* object rather
    # than on whatever a later step might find — the permanent is new
    # (CR 400.7) and no target names it.
    #
    # Through the placement seams rather than by poking metadata, so the P/T
    # pair reaches layer 7d and the CR 704.5q sweep can find it: a counter
    # placed by hand is a counter nothing can take off.
    for kind, count in (instruction.payload.get("counters") or {}).items():
        if str(kind) == "+1/+1":
            game.place_plus1_counters(arrived, int(count))
        else:
            game.place_pt_counters(arrived, str(kind), int(count))
        game.log.append(f"{card.name} enters with {count} {kind} counter(s)")
    return True, "resolved"


@effect_handler("reanimate_graveyard_position")
def reanimate_graveyard_position(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put the top creature card of defending player's graveyard onto the
    battlefield **under your control**." (Bone Dancer.)

    Which card is ``graveyard_order.positions_named`` — the one scan, shared
    with ``exile.exile_graveyard_position`` and with the activation-cost payment
    path, so a printed position read as a cost and the same position read as an
    effect cannot name different cards. It answers with an **index** rather than
    a card because two copies of one card in one graveyard are the same Python
    object, and an identity filter over the pile would take both.

    Whose pile is CR 506.2's defending player, frozen into the trigger's context
    by the combat fire site rather than read off the board — the same key
    ``exile_cards_from_graveyard`` reads, and for its reason: this resolves in a
    priority window after the declaration, and an attacker removed from combat
    in between would leave a board read naming nobody.

    Whose **battlefield** is the ability's controller, which is the whole of the
    card: CR 404.1 puts the card in its owner's graveyard, so the default
    arrival (CR 400.3) would hand the creature back to the player being
    attacked.

    An empty pile reanimates nothing and still resolves (CR 608.2 finishes what
    it can) — and returns False from the ``may`` it sits inside, which is what
    keeps "If you do, this creature assigns no combat damage this turn" from
    firing on a turn where nothing came back.
    """
    from ..graveyard_order import positions_named

    if instruction.payload.get("graveyard_owner") != "defending_player":
        game.log.append(f"{context.card.name}: no graveyard named")
        return True, "resolved"
    seat = (context.trigger_context or {}).get("trigger_defending_player_index")
    if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
        game.log.append(
            f"{context.card.name}: no defending player was recorded"
        )
        return True, "no graveyard"
    victim = game.players[seat]
    taken = positions_named(victim.graveyard, dict(instruction.payload))
    if not taken:
        game.log.append(
            f"{victim.name}'s graveyard has nothing {context.card.name} can "
            f"return"
        )
        return True, "no card"
    caster_index = game.players.index(context.caster)
    moved = []
    # Highest index first: the positions were found against the pile as it
    # stands, and removing a lower one renumbers every position above it.
    for index in sorted(taken, reverse=True):
        moved.append(victim.graveyard.pop(index))
    for card in moved:
        game._put_permanent_onto_battlefield(
            caster_index, Permanent(card=card), None, from_zone="graveyard"
        )
        game.log.append(
            f"{context.card.name} returned {card.name} from {victim.name}'s "
            f"graveyard under {context.caster.name}'s control"
        )
    return True, "resolved"


@effect_handler("move_random_graveyard_card")
def move_random_graveyard_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Reorder your graveyard at random. An opponent chooses a card at random
    in your graveyard. If it's a creature card, put it onto the battlefield.
    Otherwise, exile it." (Search for Survivors.)

    The graveyard is an ordered pile here (CR 404.1's top card is read by
    other cards), so the reorder is performed, not skipped. A pick "at random"
    is nobody's decision, so no prompt is armed; it needs an opponent to make
    it, and with none left nothing is chosen. The module RNG, which
    ``run_ai_simulation`` seeds, so a seed replays the run.
    """
    caster = context.caster
    caster_index = game.players.index(caster)
    payload = instruction.payload
    pile = caster.graveyard
    if payload.get("shuffle_first"):
        random.shuffle(pile)
    if not pile or not list(game.opponents_of(caster_index)):
        game.log.append(f"{context.card.name}: no card was chosen")
        return True, "resolved"
    card = pile.pop(random.randrange(len(pile)))
    if card_has_type(card, str(payload.get("card_type") or "creature")):
        game._put_permanent_onto_battlefield(
            caster_index, Permanent(card=card), None, from_zone="graveyard"
        )
        game.log.append(f"{context.card.name} put {card.name} onto the battlefield")
    else:
        caster.exile.append(card)
        game.log.append(f"{context.card.name} exiled {card.name}")
    return True, "resolved"


@effect_handler("choose_target_cards")
def choose_target_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Choose two target creature cards in your graveyard." (Victimize.)

    The announcement, and nothing else: CR 601.2c chose the cards as the spell
    was cast, and this sentence prints no effect. It exists so
    ``engine/targeting.py`` can derive the picker from the compiled program,
    which is where every other card's comes from — the same job
    ``choose_target_permanent`` does one zone over.

    Nothing is *recorded* either, and that is the difference from the plural
    permanent choice: the announced slots ride the stack item for the whole
    resolution, so the sentence behind this reads the same list this picker
    filled. A record would be a second copy of it, free to disagree the moment
    an earlier step moved a card in the pile.

    Nothing leaves the graveyard here. "Sacrifice a creature. **If you do**,
    return the chosen cards" is a price that may not be paid, and cards taken
    out now would be cards in no zone at all.
    """
    game.log.append(f"{context.card.name}: cards chosen from the graveyard")
    return True, "resolved"


@effect_handler("reanimate_announced_cards")
def reanimate_announced_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…return **the chosen cards** to the battlefield tapped." (Victimize.)

    The cards an earlier sentence of this same spell announced (CR 601.2c),
    read off the resolution's own target list rather than out of a record —
    ``choose_target_cards`` says why.

    Through ``_resolve_graveyard_slots``, the one reader of a list of graveyard
    slots: a card in a pile has no ``permanent_id`` and two copies of one card
    there are the same ``CardDefinition``, so only the order of removal can tell
    two slots apart. A slot whose card has left, or that names a card the
    printed phrase does not (CR 608.2b), is dropped and the rest still happen.

    Under the spell's controller (CR 110.2a), which is the seat whose graveyard
    the phrase named.
    """
    caster = context.caster
    tapped = bool(instruction.payload.get("tapped"))
    seat = game.players.index(caster)

    def _eligible(card) -> bool:
        # The picker's own predicate, asked here so the resolution and the
        # announcement cannot disagree about which cards were legal.
        return graveyard_card_matches(instruction.payload, card)

    picked = _resolve_graveyard_slots(caster, context, len(caster.graveyard), _eligible)
    for card in picked:
        permanent = Permanent(card=card)
        if tapped:
            permanent.tapped = True
        game._put_permanent_onto_battlefield(seat, permanent, None)
        game.log.append(
            f"{caster.name} returned {card.name} to the battlefield from the graveyard"
        )
    if not picked:
        game.log.append(f"{context.card.name}: no announced card to return")
    return True, "resolved"


@effect_handler("return_all_cards_from_graveyard")
def return_all_cards_from_graveyard(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Each player returns all creature cards from their graveyard to the
    battlefield." (All Hallow's Eve.)

    A sweep reanimation: no target, no pick, every card a printed noun phrase
    names. ``who`` is the returning player — ``each_player`` or the ability's
    controller — and it is payload rather than two kinds because the sentence
    is the same one either way.

    Each card comes back under **its own player's** control, which is what the
    printed subject says: "each player returns … from *their* graveyard".
    Reading the sentence without its subject would hand the table's graveyards
    to whoever's upkeep it was, which is a different card.

    The graveyard is drained highest-index-first, so popping one does not
    renumber the slots still to come — the ordering every other multi-card
    graveyard move in this engine follows, and the reason it is not a removal
    by value: two copies of one card in a graveyard are the *same*
    ``CardDefinition``, so ``.remove()`` would take whichever came first.
    """
    described = dict(instruction.payload.get("filter") or {})
    who = str(instruction.payload.get("who", "you"))
    # "…to **your hand**." (Crystal Chimes.) The pair of zones is what picks the
    # move, and the graveyard half is the same either way — which is why it is
    # one key rather than a second kind that would re-derive the same sweep.
    # Absent means the battlefield, so every payload written before this means
    # what it meant.
    destination = str(instruction.payload.get("destination", "battlefield"))
    # "…to the battlefield **tapped**." (Planar Birth.) CR 110.5b.
    tapped = bool(instruction.payload.get("tapped"))
    # "…**that were put there from the battlefield this turn**." (No Rest for
    # the Wicked.) Beside the filter and not inside it, because how a card
    # reached a pile is not on the card: a graveyard has a printed type line and
    # nothing else (CR 613.1), so the record the game kept as the move happened
    # is the only thing that can answer.
    only_this_turn = bool(instruction.payload.get("put_there_this_turn"))
    # "…return all cards in your graveyard **destroyed this way** to the
    # battlefield." (Cleansing Meditation.) The pile intersected with what the
    # destroy step in front of this one recorded — beside the filter for the
    # history's reason above, and answered the same way, by count of entries.
    destroyed_only = bool(instruction.payload.get("destroyed_this_way"))
    if who == "each_player":
        # CR 101.4's order, and a seat that has left the game returns nothing
        # (CR 800.4a): a lost player has no battlefield, so putting a card onto
        # it makes a permanent nobody controls. This read the raw seat range,
        # which is All Hallow's Eve mis-played in the one game shape where the
        # difference exists — and the two per-seat handlers beside it already
        # answer the question this way.
        total = len(game.players)
        active = game.active_player_index or 0
        seats = sorted(
            (i for i, p in enumerate(game.players) if not p.lost),
            key=lambda i: ((i - active) % total, i),
        )
    else:
        seats = [game.players.index(context.caster)]
    # CR 303.4f's hosts are the permanents **already** on the battlefield: the
    # cards ruling for both printings (Replenish, Cleansing Meditation, 2005-08-
    # 01) is that "Auras returning to the battlefield can only enchant
    # something that was already on the battlefield", so the board is read once,
    # before anything this effect returns has arrived.
    already_there = list(game.all_permanents()) if destination == "battlefield" else []
    # What each seat returns, as (slot, card) pairs, and each Aura card's host
    # by (seat, slot) — decided before anything moves (CR 303.4f), because the
    # cards enter together and an Aura enters attached.
    plans: list[tuple[int, list]] = []
    hosts: dict[tuple[int, int], object] = {}
    asks: list[tuple[int, int, object, list]] = []
    for seat in seats:
        player = game.players[seat]
        taken = [
            index for index, card in enumerate(player.graveyard)
            if _card_matches_filter(card, described, game=game, owner=player)
        ]
        if only_this_turn:
            # Matched by **count of entries**, not by membership: two copies of
            # a card in a deck are the same immutable ``CardDefinition``, so a
            # graveyard holding one that died this turn and one that was
            # discarded last turn holds one object twice — and the record says
            # how many of them arrived the way the sentence names. Newest first,
            # since a death puts the card on top and that is the copy the record
            # is about.
            arrived = list(
                player.cards_put_into_your_graveyard_from_battlefield_this_turn
            )
            allowed: list[int] = []
            for index in sorted(taken, reverse=True):
                card = player.graveyard[index]
                match = next(
                    (i for i, held in enumerate(arrived) if held is card), None
                )
                if match is None:
                    continue
                arrived.pop(match)
                allowed.append(index)
            taken = allowed
        if destroyed_only:
            taken = _destroyed_this_way_slots(player, taken, context)
        if destination == "battlefield":
            for index in list(taken):
                card = player.graveyard[index]
                if not _is_aura_card(card):
                    continue
                legal = _legal_returning_aura_hosts(game, seat, card, already_there)
                if not legal:
                    # CR 303.4g: nothing it could enchant, so it stays where it
                    # is rather than entering attached to nothing for CR 704.5m
                    # to bin. Replenish's reminder text says so.
                    taken.remove(index)
                    game.log.append(
                        f"{card.name} has nothing it could enchant and stays in "
                        f"{player.name}'s graveyard"
                    )
                    continue
                if len(legal) > 1 and seat in game.interactive_seats:
                    asks.append((seat, index, card, legal))
                    continue
                from ..ai_policy import choose_returning_aura_host

                # One legal host is no question; a seat nobody asks takes the
                # policy's pick (``ai_policy.choose_returning_aura_host``).
                hosts[(seat, index)] = (
                    legal[0] if len(legal) == 1
                    else choose_returning_aura_host(game, seat, card, legal)
                )
        plans.append((seat, [(index, player.graveyard[index]) for index in taken]))

    card_name = getattr(context.card, "name", "") or "Effect"

    def step(ask) -> None:
        # CR 303.4f: "that player chooses what it will enchant". One prompt per
        # Aura with a choice to make, each the general "choose a permanent as
        # the effect resolves" (``permanent_choice``, suspending), so nothing
        # moves until the last answer — the cards enter together, after it.
        if ask is not None:
            seat, index, card, legal = ask
            game.arm_permanent_choice(
                seat,
                card_name=card_name,
                prompt=(
                    f"Choose what {card.name} enchants as it returns to the "
                    "battlefield."
                ),
                result_key=_returning_aura_host_key(seat, index),
                payload={
                    "legal_host_for_card": card,
                    "host_controller": seat,
                    "default_prefers": "returning_aura_host",
                },
                context=context,
                candidates=legal,
            )
            return
        for seat, index, _card, _legal in asks:
            chosen = context.results.get(_returning_aura_host_key(seat, index))
            hosts[(seat, index)] = (
                game.permanent_by_id(chosen) if isinstance(chosen, int) else None
            )
        _return_planned_cards(
            game, plans, hosts, destination=destination, tapped=tapped,
            card_name=card_name,
        )

    # One step per question and a last one that moves everything. The loop is
    # the last thing this handler does, which is ``engine/resumption.py``'s rule.
    run_resumable(game, [*asks, None], step)
    return True, "resolved"


def _returning_aura_host_key(seat: int, index: int) -> str:
    """The scratchpad key one returning Aura's chosen host is written under."""
    return f"returning_aura_host:{seat}:{index}"


def _return_planned_cards(
    game, plans, hosts, *, destination: str, tapped: bool, card_name: str,
) -> None:
    """Move every planned card at once, each Aura attached to its host.

    *plans* is ``(seat, [(slot, card), ...])`` in the order the seats return;
    *hosts* holds every Aura's host by ``(seat, slot)``, None where a seat's
    answer named nothing. A host is asked once more as the Aura enters — the
    choice was legal when it was made, and CR 303.4f's "must choose a legal
    object" is about the moment of entry — and an Aura without one stays in
    the graveyard (CR 303.4g).
    """
    from ..auras import attach_aura, enchant_card_refusal

    returned = 0
    for seat, entries in plans:
        player = game.players[seat]
        moving = []
        for index, card in entries:
            if (seat, index) in hosts:
                host = hosts[(seat, index)]
                if host is None or enchant_card_refusal(game, card, seat, host) is not None:
                    game.log.append(
                        f"{card.name} has nothing it could enchant and stays in "
                        f"{player.name}'s graveyard"
                    )
                    continue
            moving.append((index, card))
        # Highest slot first, so a pop does not renumber the slots still to
        # come — and each slot checked to still hold its card: a graveyard is a
        # list of shared ``CardDefinition`` objects, so the slot is the
        # identity, and a slot that no longer holds the card is a card that left.
        for index, card in sorted(moving, key=lambda entry: entry[0], reverse=True):
            if index < len(player.graveyard) and player.graveyard[index] is card:
                player.graveyard.pop(index)
            else:
                moving.remove((index, card))
        for index, card in moving:
            if destination == "hand":
                # CR 903.9b's seam, never `player.hand.append` — a bounce, a
                # tuck and a regrowth are all "would be put into its owner's
                # hand", and this is one of the thirty fire sites that rule has
                # no single one of.
                game.put_card_into_hand(player, card)
                game.log.append(
                    f"{player.name} returned {card.name} to their hand from the graveyard"
                )
                returned += 1
                continue
            permanent = Permanent(card=card)
            if tapped:
                permanent.tapped = True
            game._put_permanent_onto_battlefield(seat, permanent, None)
            host = hosts.get((seat, index))
            if host is not None:
                # Attached as part of the same move, inside this resolution —
                # the arrangement ``reanimate_aura_onto_source`` keeps, so the
                # Aura is never an unattached one for CR 704.5m to find.
                attach_aura(permanent, host)
                game.log.append(
                    f"{player.name} returned {card.name} to the battlefield "
                    f"from the graveyard attached to {host.card.name}"
                )
                returned += 1
                continue
            game.log.append(
                f"{player.name} returned {card.name} to the battlefield from the graveyard"
            )
            returned += 1
    if not returned:
        game.log.append(f"{card_name}: no cards to return")


def _is_aura_card(card) -> bool:
    """Whether *card*, in a graveyard, is an Aura with an enchant ability —
    the test the Aura spell's own resolution asks before CR 303.4g bins it
    (``resolution``'s "had no legal target"), off the printed card because a
    card in a graveyard has nothing else (CR 613.1)."""
    from ..auras import aura_enchant_clause

    return "Aura" in (card.type_line or "") and aura_enchant_clause(
        card.oracle_text or ""
    ) is not None


def _legal_returning_aura_hosts(game, seat: int, card, already_there) -> list:
    """The permanents an Aura card a mass return puts onto the battlefield
    under *seat*'s control could enchant — empty when it can enchant nothing
    (CR 303.4g: it stays in the graveyard).

    CR 303.4f: an Aura put onto the battlefield by an effect that names no
    host is attached to an object its controller chooses, as it enters, and
    "doing this does not target the permanent" (Replenish's and Cleansing
    Meditation's ruling, 2004-10-04) — so shroud and hexproof are no bar. The
    enchant ability and protection (CR 702.16c, "can't be enchanted by Auras
    that have the stated quality") are ``enchant_card_refusal``, the one
    predicate every host chooser asks. Only a permanent that was on the
    battlefield before the return (*already_there*), in board order.

    **Who chooses.** An interactive seat with more than one legal host is
    asked (``permanent_choice``, armed by the handler, the candidates this
    list). Every other seat takes ``ai_policy.choose_returning_aura_host`` —
    an Aura whose text works against its host goes on an opponent's
    permanent, any other on its controller's — which is also that prompt's
    default (``default_prefers: "returning_aura_host"``).
    """
    from ..auras import enchant_card_refusal

    return [
        host for host in already_there
        if game.is_on_battlefield(host)
        and enchant_card_refusal(game, card, seat, host) is None
    ]


def _destroyed_this_way_slots(player, taken, context) -> list[int]:
    """The slots of *taken* (indices into *player*'s graveyard) holding a card
    an earlier step of this resolution destroyed, newest first.

    "Destroy all enchantments, then return all cards in your graveyard
    **destroyed this way** to the battlefield." (Cleansing Meditation.) The
    destroy step recorded the *permanents* (``destroyed_this_way_objects``);
    what lies in the pile now is a new object with no memory of them (CR
    400.7), and two copies of one card in a pile are one ``CardDefinition`` —
    so a slot is admitted by **count of entries**, the way the "put there this
    turn" history beside it is: a copy already in the graveyard before the
    sweep is not returned because a second copy of it was destroyed.

    Held to the arrival record as well: a destroyed permanent whose card a
    replacement sent somewhere else (CR 614) never reached this pile, and its
    name must not claim an older copy that did. A token's card never gets here
    (CR 111.7), and the seam records the whole card (CR 709.4), so the
    permanent's card is compared the same way.
    """
    from ..faces import whole_card

    destroyed = [
        whole_card(perm.card)
        for perm in context.results.get("destroyed_this_way_objects") or ()
        if not perm.metadata.get("is_token")
    ]
    arrived = list(player.cards_put_into_your_graveyard_from_battlefield_this_turn)
    allowed: list[int] = []
    for index in sorted(taken, reverse=True):
        card = player.graveyard[index]
        was_destroyed = next(
            (i for i, held in enumerate(destroyed) if held is card), None
        )
        came_from_battlefield = next(
            (i for i, held in enumerate(arrived) if held is card), None
        )
        if was_destroyed is None or came_from_battlefield is None:
            continue
        destroyed.pop(was_destroyed)
        arrived.pop(came_from_battlefield)
        allowed.append(index)
    return allowed


@effect_handler("sacrifice_and_return_targets")
def sacrifice_and_return_targets(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"Choose target artifact a player controls and target artifact card in
    that player's graveyard. If both targets are still legal as this ability
    resolves, that player simultaneously sacrifices the artifact and returns
    the artifact card to the battlefield." (Goblin Welder.)

    **The rider is the whole of what this handler adds to the two moves.**
    CR 608.2b removes an object from the stack only when *every* target is
    illegal, so with one target gone the default rule would still run the half
    that is left — an artifact sacrificed for a card that never comes back, or
    a card returned for nothing. The card says otherwise, and the payload
    carries the sentence that says it. Both roles are re-checked through
    ``roles_still_legal``, which asks the same relation table the picker
    narrowed with, so what the activator was offered and what happens here
    cannot come apart.

    **Simultaneously** (CR 608.2's "as much as possible at once") is why the
    card leaves the graveyard *before* the artifact is sacrificed into it: the
    sacrifice feeds the very pile the return reads, and the return must not be
    able to see it. Written for the rule rather than for a failing case, and
    the test beside it says so — the stamp is keyed by ordinal, so on today's
    boards the reversed order resolves to the same copy and nothing observable
    separates them. That is a fact about the stamp, not a licence.

    Who acts is "that player" — the seat the first slot's own "a player
    controls" bound — so the card comes back under *their* control, on *their*
    battlefield, which is the same seat whose graveyard it was chosen from.
    Nothing here is relative to the ability's controller, and reading it as
    "you" would let a Welder steal an opponent's artifact out of their pile.
    """
    payload = instruction.payload or {}
    roles = ((payload.get("targets") or {}).get("roles") or ())
    if len(roles) != 2:
        return False, "a weld names two roles"
    sacrificed_role, returned_role = roles[0].get("role"), roles[1].get("role")
    observer = game.players.index(context.caster)
    # The printed rider, read off the payload rather than assumed from the
    # kind. It is always present today — the lowering refuses the sentence
    # without it, because CR 608.2b's partial resolution is a card nothing here
    # implements — so this is a reader of what the card says, not a defence
    # against a payload that cannot arrive.
    if payload.get("all_targets_required") and not roles_still_legal(
        game, context, payload, observer=observer
    ):
        # Not a fizzle: CR 608.2b counters the ability only if *every* target
        # is illegal, and that is decided above this handler
        # (``legality.illegal_targets_refusal``). This is the printed
        # condition, so the ability resolves and does nothing.
        game.log.append(
            f"{context.card.name}: both targets are not still legal — nothing happens"
        )
        return True, "resolved"
    artifact = resolve_role_permanent(game, context, payload, sacrificed_role)
    stamp = resolve_role_graveyard_card(game, context, payload, returned_role)
    if artifact is None or stamp is None:
        game.log.append(f"{context.card.name}: a chosen target is gone")
        return True, "resolved"
    seat = game.controller_index_of(artifact)
    slot = game.graveyard_index_of(stamp)
    if seat is None or slot is None:
        game.log.append(f"{context.card.name}: a chosen target is gone")
        return True, "resolved"
    actor = game.players[stamp.seat]
    # Out of the pile first — see the docstring: the sacrifice below puts a
    # card into this very graveyard, and "simultaneously" means the return may
    # not see it.
    returning = actor.graveyard.pop(slot)
    game.sacrifice_permanent(artifact)
    arrival = Permanent(card=returning)
    game._put_permanent_onto_battlefield(stamp.seat, arrival, None)
    game.log.append(
        f"{context.card.name}: {actor.name} sacrifices {artifact.card.name} "
        f"and returns {returning.name} to the battlefield"
    )
    return True, "resolved"
