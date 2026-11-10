"""Damage moved to another recipient (CR 614.9): what a redirect **does**.

``engine/damage_redirects.py`` is what a redirect *is* — the recorded
``DamageRedirect`` a resolving effect arms — and this module registers what one
does when damage would be dealt: the general recorded redirect (Shimian Night
Stalker, Nova Pentacle, Jade Monolith), offered as a choice where the printed
sentence says "you may"; Veteran Bodyguard's untapped protector and the source
class it answers to; and Personal Incarnation's one point to its owner. The chosen-colour spell redirect's
matcher is here too, for ``damage_redirects`` to read.

Every redirect is ordered ahead of every prevention shield, for the reason
``registry.py``'s order bands give.

Split out of ``replacements.py`` at the 2,000-line cap's split round. How much
damage there is, is ``damage.py``'s.
"""

from __future__ import annotations

import re

from ..damage_redirects import (
    DamageRedirect,
    _is_permanent,
    applicable_redirect,
    drop_spent,
    event_dealing_moment,
    live_recipient,
)
from ..models import PlayerState
from ..replacement_choices import (
    ReplacementChoice,
    offer_replacement_choice,
    replacement_choice,
)
from .damage import _source_answers_class
from .registry import (RECORDED_REDIRECT, REDIRECT_ONE_POINT,
                       REDIRECT_WHOLE_EVENT, ReplacementOutcome,
                       replacement_effect)


VETERAN_BODYGUARD_TEXT = (
    "all damage that would be dealt to you by unblocked creatures is dealt to "
    "this creature instead"
)

#: "As long as this creature is untapped, all damage that would be dealt to you
#: by **<source class>** is dealt to this creature instead." Veteran Bodyguard
#: says "unblocked creatures"; Martyrs of Korlis says "artifacts". One
#: redirection with the class as data, because the two sentences differ in
#: nothing else — and the untapped condition is part of the printed line rather
#: than a separate static, which is why it is matched here and not asked
#: elsewhere.
_REDIRECT_TO_SELF = re.compile(
    r"^as long as this creature is untapped, all damage that would be dealt to "
    r"you by (?P<source_class>unblocked creatures|artifacts|creatures) is dealt "
    r"to this creature instead$"
)


def redirect_to_self_source_class(line: str) -> str | None:
    """The class of source *line* redirects, or None if it is not that line.

    One matcher, asked by the interceptor and by the claim reader, so what is
    redirected and what is claimed cannot drift.
    """
    return _match_group(_REDIRECT_TO_SELF, line, "source_class")


#: "If an **instant or sorcery** spell of the chosen color would deal damage to
#: you, it deals that damage to its controller instead." (Harsh Judgment.) A
#: CR 614.9 redirection whose source class is a *spell* of a card type and of
#: the colour this permanent recorded as it entered (CR 614.1c). The types are
#: payload, read the way ``damage.py``'s ``_SOURCE_DAMAGE_CAP`` reads its own class; the
#: colour is not in the sentence at all, so it is read off the permanent by
#: ``damage_redirects.chosen_color_spell_redirects`` when the damage would be
#: dealt.
_CHOSEN_COLOR_SPELL_REDIRECT = re.compile(
    r"^if an? (?P<source_class>[a-z ]+?) spell of the chosen color would deal "
    r"damage to you, it deals that damage to its controller instead$"
)


def chosen_color_spell_redirect(line: str) -> tuple[str, ...] | None:
    """The spell types whose damage *line* sends back, or None if it is not
    that line.

    One matcher, asked by the redirect scan and by
    :func:`replacement_claims_line`, so what is redirected and what is claimed
    cannot drift. A class naming no readable card type refuses the line for
    ``source_damage_cap``'s reason: ``source_has_type`` answers False for a
    word it does not know, and a redirect that can never fire is the silent
    shape the claim reader exists to keep out of the supported pool.
    """
    from ..grammar.vocabulary import CARD_TYPES

    source_class = _match_group(_CHOSEN_COLOR_SPELL_REDIRECT, line, "source_class")
    if source_class is None:
        return None
    types = tuple(word.strip() for word in source_class.split(" or ") if word.strip())
    if not types or any(word not in CARD_TYPES for word in types):
        return None
    return types


def _match_group(pattern, line: str, group: str) -> str | None:
    match = pattern.match(" ".join((line or "").strip().lower().rstrip(".").split()))
    return match.group(group) if match is not None else None


def deal_redirected_damage(
    game, new_recipient, amount: int, *, source, combat: bool,
    then=None, redirect: DamageRedirect | None = None,
) -> None:
    """Deal the damage a redirect moved to *new_recipient* (CR 614.9).

    **The one hand-off every redirect here makes**, and the answer to what
    CR 616.1e's question is inside another event's 616.1 process. A redirect
    is chosen and applied in the *original* event's process, by its affected
    player; what it leaves behind — the same damage, dealt to someone else —
    is CR 616.2's modified event, and the effects now applicable to it are
    the new recipient's, chosen by the new affected player (CR 616.1: "the
    affected object's controller … or the affected player"). CR 616.1g's
    order is kept by construction: nothing about the moved damage is chosen
    until the redirect has been. The moved damage is run as a fresh
    ``deal_damage`` for the new recipient, and nothing has been applied to it
    when it asks, so it may suspend and be re-run whole on the answer —
    exactly what every other asking call does. The original event does not
    wait: it is consumed, or carries its unmoved remainder on, and nothing it
    still does depends on the moved damage; a loop it was a step of stops
    behind the question (``resumption.run_resumable``). Every redirect here
    dealt its moved damage without asking, so the new recipient took the
    default order (SET_PLAYBOOK's Known-gaps entry: eight calls).

    *combat* is the original event's flag, and required: damage a redirect
    moves keeps being combat damage (CR 510.2; Wall of Souls' ruling,
    2004-10-04: "Redirected damage is still combat damage"; Pariah's,
    2024-04-12), so a "prevent all combat damage" shield still applies to it
    and "whenever … deals combat damage to a player" still sees it. Three of
    the six hand-offs here (Jade Monolith, Personal Incarnation, an optional
    redirect taken) passed nothing, and the player seam dropped the flag for
    every one of them.

    *then* is what the redirect reports once the damage has landed, given the
    amount dealt; it runs inside the event, so a suspended hand-off reports
    nothing until it is dealt. *redirect*'s ``applying`` is held over the
    hand-off — and over its re-run — so a record aimed back at its own
    recipient cannot apply to the damage it has just moved (CR 614.5).

    A permanent dealt the damage is dealt it in full: its "whenever this
    creature is dealt damage" triggers fire (``_fire_dealt_damage_triggers``),
    which the bare marking seam the redirects called does not do — so the
    damage a Veteran Bodyguard or a Shimian Night Stalker took went unseen by
    every such trigger on the creature that took it.
    """

    def landed(dealt: int) -> None:
        if dealt > 0 and not isinstance(new_recipient, PlayerState):
            game._fire_dealt_damage_triggers(
                new_recipient, dealt, combat=combat, source=source,
            )
        if then is not None:
            then(dealt)

    def hand_off() -> None:
        held = redirect.applying if redirect is not None else None
        if redirect is not None:
            redirect.applying = True
        try:
            if isinstance(new_recipient, PlayerState):
                # *combat* travels to a player as it does to a creature:
                # redirected combat damage is still combat damage (CR 510.2;
                # Pariah's ruling), which the player seam used to drop.
                game._deal_damage_to_player(
                    new_recipient, amount, source=source, then=landed,
                    restart=hand_off, combat=combat,
                )
            else:
                game._mark_damage_on_permanent(
                    new_recipient, amount, source=source, combat=combat,
                    then=landed, restart=hand_off,
                )
        finally:
            if redirect is not None:
                redirect.applying = held

    hand_off()


def _protecting_bodyguard(game, payload: dict):
    """The untapped permanent that would take this damage instead, or None.

    Veteran Bodyguard and Martyrs of Korlis are one effect with different
    source classes, so the class is read off each candidate's own line and
    checked against the damage's source — rather than one card's sentence being
    a constant and the other needing a second interceptor.
    """
    if payload["amount"] <= 0:
        return None
    for permanent in game.controlled_by(payload["recipient"]):
        if permanent.tapped:
            continue
        for line in (permanent.effective_card.oracle_text or "").splitlines():
            source_class = redirect_to_self_source_class(line)
            if source_class is None:
                continue
            if _source_answers_class(
                game, payload.get("source"), source_class,
                payload.get("source_seat"),
            ):
                return permanent
    return None


def _applies_bodyguard_redirect(game, payload: dict) -> bool:
    return _protecting_bodyguard(game, payload) is not None


def _bodyguard_sources(game, payload: dict) -> list:
    """The untapped creature that would take this damage (Veteran Bodyguard,
    Martyrs of Korlis), as :func:`_protecting_bodyguard` finds it. Pure."""
    found = _protecting_bodyguard(game, payload)
    return [] if found is None else [found]


@replacement_effect(
    "damage_to_player", REDIRECT_WHOLE_EVENT, applies=_applies_bodyguard_redirect,
    redirects=True, sources=_bodyguard_sources,
    label="The damage is dealt to the untapped creature instead",
)
def _redirect_damage_to_bodyguard(game, payload: dict) -> ReplacementOutcome | None:
    """Veteran Bodyguard: "As long as this creature is untapped, all damage that
    would be dealt to you by unblocked creatures is dealt to this creature
    instead."

    All damage, not all combat damage — an unblocked attacker's activated ability
    is redirected too, which reading the source's combat state gets right for
    free. Ordered before the shields protecting the player, because a shield
    spent here would be spent on damage that is about to become the creature's.
    """
    bodyguard = _protecting_bodyguard(game, payload)
    recipient = payload["recipient"]
    amount = payload["amount"]
    deal_redirected_damage(
        game, bodyguard, amount,
        source=payload.get("source"),
        combat=bool(payload.get("combat")),
        then=lambda _dealt: game.log.append(
            f"{bodyguard.card.name} takes {amount} damage instead of "
            f"{recipient.name} (redirect)"
        ),
    )
    return ReplacementOutcome(replaced=True)


def _applies_redirect_one_damage(game, payload: dict) -> bool:
    charges = int(
        payload["recipient"].metadata.get("redirect_one_damage_to_owner_until_eot", 0)
    )
    return charges > 0 and payload["amount"] > 0


def _the_recipient(game, payload: dict) -> list:
    """The damaged creature, whose own ability armed its redirect (Personal
    Incarnation). Pure."""
    return [payload["recipient"]]


@replacement_effect(
    "damage_to_creature", REDIRECT_ONE_POINT, applies=_applies_redirect_one_damage,
    redirects=True, sources=_the_recipient,
    label="1 of that damage is dealt to its owner instead",
)
def _redirect_one_damage_to_owner(game, payload: dict) -> ReplacementOutcome | None:
    """Personal Incarnation: "The next 1 damage that would be dealt to this
    creature this turn is dealt to its owner instead." One point per charge,
    replaced before the rest is marked."""
    permanent = payload["recipient"]
    amount = payload["amount"]
    redirect = int(permanent.metadata.get("redirect_one_damage_to_owner_until_eot", 0))
    permanent.metadata["redirect_one_damage_to_owner_until_eot"] = redirect - 1
    # "…is dealt to **its owner** instead" — the owner (CR 108.3), not whoever
    # controls it now, and by the source that was dealing it (CR 614.9 moves
    # the recipient only). It read the controller and dropped the source.
    owner_seat = game.owner_index_of(permanent)
    owner = game.players[owner_seat] if owner_seat is not None else None
    if owner is not None:
        deal_redirected_damage(
            game, owner, 1, source=payload.get("source"),
            combat=bool(payload.get("combat")),
            then=lambda _dealt: game.log.append(
                f"1 damage redirected from {permanent.card.name} to {owner.name}"
            ),
        )
    return ReplacementOutcome(new_amount=amount - 1)


def _recorded_redirect(game, payload: dict):
    """The general redirect record that would move this damage, or None. Pure —
    see ``engine/damage_redirects.py`` for why the predicate may not spend one."""
    if payload["amount"] <= 0:
        return None
    return applicable_redirect(
        game, payload["recipient"], payload.get("source"),
        combat=bool(payload.get("combat")),
    )


def _applies_recorded_redirect(game, payload: dict) -> bool:
    return _recorded_redirect(game, payload) is not None


def _recorded_redirect_sources(game, payload: dict) -> list:
    """The card that armed the redirect record that would move this damage
    (Shimian Night Stalker, Nova Pentacle), by the record's name. Pure."""
    found = _recorded_redirect(game, payload)
    named = getattr(found, "source_name", None) if found is not None else None
    return [named] if named else []


@replacement_effect(
    "damage_to_player", RECORDED_REDIRECT, applies=_applies_recorded_redirect,
    redirects=True, sources=_recorded_redirect_sources,
    label="That damage is dealt to another recipient instead",
)
@replacement_effect(
    "damage_to_creature", RECORDED_REDIRECT, applies=_applies_recorded_redirect,
    redirects=True, sources=_recorded_redirect_sources,
    label="That damage is dealt to another recipient instead",
)
def _apply_recorded_redirect(game, payload: dict) -> ReplacementOutcome | None:
    """CR 614.9: the damage is dealt to another recipient instead.

    One interceptor for both ends of the event, registered twice, because a
    redirect is one effect that happens to be printed with a player on one side
    (Shimian Night Stalker moves *your* damage onto a creature) or a permanent
    (Jade Monolith's shape, moving a creature's onto a player). Which of the two
    kinds the event is says nothing about what the record does.

    **The damage is dealt, not prevented.** It is handed to the ordinary damage
    path for its new recipient with the same source, so lifelink (CR 120.3f),
    "whenever ~ deals damage" triggers, deathtouch and the dealt-damage records
    all see it exactly as they would have seen the original event — none of which
    a prevention-plus-fresh-damage spelling would get right. The original event
    is then consumed, which is what stops the same damage landing twice.

    The combat flag travels with it: damage redirected during the combat damage
    step is still combat damage (CR 510.2 does not stop being true because the
    recipient changed), so a Fog or a Circle still sees what it should.

    **A record may move only part of the event.** "The next 1 damage that would
    be dealt to target white creature this turn is dealt to this creature
    instead" (Daughter of Autumn, Hazduhr the Abbot) carries a point pool, spent
    the way CR 615.7 spends a numeric shield: the points it covers move and the
    rest of the event carries on to its original recipient, which is what
    ``ReplacementOutcome.new_amount`` says. A record with no pool moves the
    whole event and consumes it, as every other printing in the pool does.
    """
    redirect = _recorded_redirect(game, payload)
    if redirect is None:  # pragma: no cover - the predicate just said otherwise
        return None
    if redirect.optional:
        return _offer_optional_redirect(game, payload, redirect)
    recipient = payload["recipient"]
    amount = payload["amount"]
    source = payload.get("source")
    # The source is handed over because one record's new recipient is derived
    # from it — "…is dealt to **that source's controller** instead" (Reflect
    # Damage), a seat that has no value until there is an event to ask about.
    new_recipient = live_recipient(game, redirect, source)
    moved = redirect.moves(amount)
    if moved <= 0:  # pragma: no cover - `spent` already excludes an empty pool
        return None
    # The chunk's dealing, for a recipient-keyed shared occasion (Glarecaster:
    # every chunk dealt to it at that time) and for CR 615.8's source-keyed
    # instance (Reflect Damage: the source's other chunks of it).
    redirect.spend(
        moved, dealing=event_dealing_moment(game, payload), source=source,
    )
    from_name = getattr(recipient, "name", None) or getattr(
        getattr(recipient, "card", None), "name", "it"
    )
    taker = (
        new_recipient.name if isinstance(new_recipient, PlayerState)
        else new_recipient.card.name
    )
    # ``applying`` is held while the hand-off runs (and over its re-run) so a
    # pair of records aimed at each other cannot recurse: the new event runs
    # the whole contention set again, and an unspent record with no uses
    # limit would still be applicable.
    deal_redirected_damage(
        game, new_recipient, moved, source=source,
        combat=bool(payload.get("combat")), redirect=redirect,
        then=lambda _dealt: game.log.append(
            f"{moved} damage to {from_name} is dealt to {taker} instead"
            + (f" ({redirect.source_name})" if redirect.source_name else "")
        ),
    )
    drop_spent(recipient)
    for items in (getattr(game, "resolving_items", None) or (),):
        for item in items:
            drop_spent(item)
    if moved < amount:
        return ReplacementOutcome(new_amount=amount - moved)
    return ReplacementOutcome(replaced=True)


#: The seat a class-scoped optional redirect asks, and the labels it offers.
#: Option 0 takes the damage; option 1 leaves it where it was dealt.
_TAKE_THE_DAMAGE = 0
_LEAVE_THE_DAMAGE = 1


def _would_be_lethal(permanent, amount: int) -> bool:
    """Whether *amount* more damage would be lethal to *permanent* (CR 704.5g).

    ``effective_toughness`` rather than the printed number, because that is the
    layer-aware accessor every other read of a creature's size goes through.
    """
    return permanent.effective_toughness - int(permanent.damage_marked or 0) <= amount


def _optional_redirect_default(game, payload: dict, redirect: DamageRedirect) -> int:
    """The stated policy a non-interactive seat takes on "you may have that
    damage dealt to you instead".

    Take the damage exactly when it would otherwise kill the creature *and* the
    taker survives at 1 or more life. That is a policy about the two facts the
    sentence trades between and nothing about which card printed it: below
    lethal, the creature keeps the damage and heals at cleanup, so paying life
    for it buys nothing; at or above the taker's life total it loses the game
    to save a creature, which no board state makes worth it.

    Stated here rather than defaulting to the offer (the shape every other
    ``ReplacementChoice`` takes) because this offer is the only one in the
    engine that can *lose the game* — Blood of the Martyr's controller is
    offered every point of damage every creature on the board would take,
    including their opponents' burn aimed at their opponents' creatures.
    """
    taker = redirect.new_recipient
    recipient = payload["recipient"]
    amount = int(payload["amount"])
    if getattr(taker, "life", 0) - amount < 1:
        return _LEAVE_THE_DAMAGE
    if _is_permanent(recipient) and _would_be_lethal(recipient, amount):
        return _TAKE_THE_DAMAGE
    return _LEAVE_THE_DAMAGE


def _offer_optional_redirect(
    game, payload: dict, redirect: DamageRedirect
) -> ReplacementOutcome | None:
    """CR 614 + CR 614.9: "you **may** have that damage dealt to you instead."

    The event is consumed either way and the resolver deals the damage, because
    that is what makes both answers one code path: "yes" is the ordinary
    redirect above and "no" is the event running again with this record held
    out of it. An interceptor that declined by returning ``None`` could not
    exist — the answer arrives on a later request, and by then
    ``apply_replacements`` has long returned.
    """
    taker = redirect.new_recipient
    if not isinstance(taker, PlayerState):  # pragma: no cover - lowering refuses it
        return None
    recipient = payload["recipient"]
    from_name = getattr(recipient, "name", None) or getattr(
        getattr(recipient, "card", None), "name", "it"
    )
    suspended, _ = offer_replacement_choice(
        game,
        ReplacementChoice(
            kind="optional_damage_redirect",
            player_index=game.players.index(taker),
            options=(
                f"take the {payload['amount']} damage yourself",
                f"leave it on {from_name}",
            ),
            default_option=_optional_redirect_default(game, payload, redirect),
            data={
                "_redirect": redirect,
                "_recipient": recipient,
                "_source": payload.get("source"),
                "amount": int(payload["amount"]),
                "combat": bool(payload.get("combat")),
                "from_name": from_name,
            },
        ),
    )
    if suspended:
        game.log.append(
            f"{taker.name} may take the {payload['amount']} damage headed for "
            f"{from_name} ({redirect.source_name or 'redirect'})"
        )
    return ReplacementOutcome(replaced=True)


@replacement_choice("optional_damage_redirect")
def _resolve_optional_damage_redirect(
    game, choice: ReplacementChoice, option_index: int
) -> int:
    """Deal the damage the offer suspended, to whichever recipient was chosen.

    ``applying`` is held over the hand-off in both branches and for the same
    reason it is in the compulsory redirect: the damage is re-run through the
    whole contention set, so a record still applicable would offer itself
    again — forever on the declining branch, which is the one the flag exists
    for here.
    """
    redirect = choice.data["_redirect"]
    recipient = choice.data["_recipient"]
    source = choice.data["_source"]
    amount = int(choice.data["amount"])
    taker = game.players[choice.player_index]
    if option_index == _TAKE_THE_DAMAGE:
        redirect.spend()
        deal_redirected_damage(
            game, taker, amount, source=source, redirect=redirect,
            combat=bool(choice.data["combat"]),
            then=lambda _dealt: game.log.append(
                f"{amount} damage to {choice.data['from_name']} is dealt to "
                f"{taker.name} instead"
                + (f" ({redirect.source_name})" if redirect.source_name else "")
            ),
        )
    else:
        # Declined: the damage goes where it was headed, as the event run
        # again with this record held out of it — the same hand-off, back to
        # the original recipient, whose seat is asked in its turn.
        deal_redirected_damage(
            game, recipient, amount, source=source,
            combat=bool(choice.data["combat"]), redirect=redirect,
        )
    return 0
