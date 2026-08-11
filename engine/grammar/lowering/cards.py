"""Lowering cards moving: draw, discard, mill, search, and mana.

Includes the two fused shapes that genuinely are one effect rather than a
sequence — "draw then discard" and the tapped-land mana trigger — and the
search filter fields the search flow can actually honour, which is a closed set
because a filter it cannot honour must refuse rather than be dropped.
"""

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._common import (
    _amount_payload,
    _describe_targets,
    _is_you,
    _restrictions_beyond,
    _targets_only,
)


# Trigger events that hand a damaged player to the effect after them. The
# handler for "that player discards a card at random" reads which player took
# the damage out of the trigger's captured context and nothing at all out of its
# payload, so it is only a reading of the sentence while one of these fired —
# under any other trigger the same words would name a player nobody recorded.
_DAMAGED_PLAYER_EVENTS = frozenset({
    "creature_deals_damage_to_opponent",
    "deals_damage_to_player",
    "creature_deals_combat_damage",
})


def _lower_discard(node: ast.Discard, event: str | None = None) -> tuple[OracleInstruction, ...]:
    """"Target player discards N cards [at random]."

    Only the targeted form has a handler; "you discard" and "each player
    discards" are different effects, not this one with a flag.

    **Who picks the cards is what separates the two handlers**, so "at random"
    decides which one this lowers to rather than being a rider either could
    carry. ``discard_target_cards`` raises a pending choice and lets the
    discarding player choose (Disrupting Scepter); ``discard_x_target_cards``
    takes them with ``random.sample`` (Mind Twist). Lowering an "at random"
    line onto the first would hand the victim the choice their card denies
    them, and lowering a plain discard onto the second would take it away.

    The random handler is also the *variable* one: it sizes itself from the X
    chosen as the spell was cast (``context.x_value``) and never reads the
    payload, which is why the amount is emitted only for the counted form —
    matching what the legacy rule wrote, and keeping the payload honest about
    what the handler actually consults.
    """
    if node.player.kind not in ("target_player", "that_player"):
        raise LoweringError(f"no discard handler for {node.player.kind!r}", node=node)
    amount = _amount_payload(node.count)
    # "…, that player discards a card at random" on a damage trigger. The
    # handler discards exactly one, at random, from the player the trigger
    # recorded — so every part of that shape is checked rather than assumed, and
    # a count, a chooser or a trigger other than those makes it fall through to
    # the general forms below and be refused there.
    if (
        node.player.kind == "that_player"
        and node.at_random
        and amount == 1
        and event in _DAMAGED_PLAYER_EVENTS
    ):
        return (OracleInstruction("opponent_discards_random_card_on_damage", "", {}),)
    payload: dict[str, object] = {}
    if amount == "x":
        if not node.at_random:
            raise LoweringError(
                "the only variable-count discard handler discards at random; "
                "a chosen discard of X cards has none",
                node=node,
            )
        kind = "discard_x_target_cards"
    else:
        if node.at_random:
            raise LoweringError(
                "no handler discards a fixed number of cards at random", node=node
            )
        kind = "discard_target_cards"
        payload["amount"] = amount
    _describe_targets(payload, node.player)
    return (OracleInstruction(kind, "", payload),)


def _fused_draw_then_discard(
    steps: tuple[ast.Statement, ...]
) -> tuple[OracleInstruction, ...] | None:
    """"Draw N cards, then discard M cards." (Bazaar of Baghdad.)

    Kept fused because the decomposition has nowhere to go. ``draw_controller_cards``
    exists, but there is no controller-*discard* handler at all —
    ``discard_target_cards`` makes a chosen player discard — so a
    two-instruction lowering would draw the cards and then either discard
    nothing or empty the wrong player's hand, while the card reported as
    supported. ``draw_then_discard_self`` performs exactly this pair for the
    effect's controller and is already parameterised by both counts, so nothing
    about it is per-card: the legacy rule it replaces reads the two numbers out
    of the sentence the same way.

    Returning None rather than raising leaves a near-miss ("…then discard three
    cards at random") to the ordinary step lowering, which refuses it by name.
    """
    if len(steps) != 2:
        return None
    draw, discard = steps
    if not (isinstance(draw, ast.Draw) and isinstance(discard, ast.Discard)):
        return None
    if not (_is_you(draw.player) and _is_you(discard.player)) or discard.at_random:
        return None
    if not (isinstance(draw.count, ast.Fixed) and isinstance(discard.count, ast.Fixed)):
        return None
    return (
        OracleInstruction(
            "draw_then_discard_self", "",
            {"draw": draw.count.value, "discard": discard.count.value},
        ),
    )


def _lower_draw(node: ast.Draw) -> tuple[OracleInstruction, ...]:
    """"You draw" and "target player draws" are different handlers, not one
    handler with a recipient flag: ``draw_controller_cards`` draws for the
    effect's controller, ``draw_target_cards`` for the chosen player. Picking by
    the drawer keeps each one's existing contract intact."""
    kind = "draw_controller_cards" if node.player.kind == "you" else "draw_target_cards"
    payload: dict[str, object] = {"amount": _amount_payload(node.count)}
    _describe_targets(payload, node.player)
    return (OracleInstruction(kind, "", payload),)


def _lower_mill(node: ast.Mill) -> tuple[OracleInstruction, ...]:
    """"Target player mills N cards." (CR 701.13a, Millstone.)

    ``mill_target_player`` mills ``context.target`` and reads no player from its
    payload, so only a *chosen* player lowers. "You mill three cards" and "each
    player mills a card" are real templates Magic prints, and both would compile
    cleanly onto this handler and mill whoever happened to be targeted — so they
    refuse by name until a handler exists that takes the miller.
    """
    if node.player.kind != "target_player":
        raise LoweringError(
            "mill_target_player mills the chosen target; no handler mills "
            f"{node.player.kind!r}",
            node=node,
        )
    payload: dict[str, object] = {"amount": _amount_payload(node.count)}
    _describe_targets(payload, node.player)
    return (OracleInstruction("mill_target_player", "", payload),)


def _lower_add_mana(node: ast.AddMana) -> tuple[OracleInstruction, ...]:
    """Emit the mana as structured pips rather than clause text.

    "Add one mana of any color" (Birds of Paradise, Celestial Prism) is the one
    player-chosen shape that lowers, and it is the exception that keeps the
    text. ``add_mana_from_text``'s any-colour branch is ``_add_mana_from_text``
    probing for the literal phrase "one mana of any color"; the chosen symbol
    arrives separately as ``color``, injected by mixins/stack/activation when
    ``any_color`` is set. Structured pips would say nothing the handler could
    read, so the clause rides along in ``oracle_text`` exactly as the legacy
    rule wrote it — which is what :attr:`ast.AddMana.source_text` exists for,
    and what keeps this payload byte-identical while the handler stays
    text-keyed.

    Any other count refuses. That probe recognizes *one* mana and no other
    number, so Black Lotus's "Add three mana of any one color" lowered here
    would add nothing while reporting success; it keeps its own fused
    ``sacrifice_self_for_mana`` handler on the legacy path.
    """
    if node.pips:
        return (OracleInstruction("add_mana_from_text", "", {"pips": node.pips}),)
    if node.any_color != 1:
        raise LoweringError(
            "only one mana of any colour has a handler; "
            f"{node.any_color} does not",
            node=node,
        )
    return (
        OracleInstruction(
            "add_mana_from_text", "", {"oracle_text": node.source_text, "any_color": True}
        ),
    )


# Which player the mana goes to, from the clause's own subject. Both spellings
# name the same seat in this engine — a player can only tap lands they control,
# so the tapping player *is* the land's controller — but they are different
# referents on the card and the handler resolves each one by name rather than
# assuming they coincide.
_TAPPED_LAND_MANA_RECIPIENTS = {
    "that_player": "that_player",   # Mana Flare: "that player"
    "controller": "land_controller",  # Gauntlet of Might: "its controller"
}


def _lower_add_mana_for_tapped_land(
    node: ast.AddManaForTappedLand, event: str | None
) -> tuple[OracleInstruction, ...]:
    """Mana Flare / Gauntlet of Might's mana, as one parameterised instruction.

    ``add_mana_for_tapped_land`` is resolved inline by
    ``Game.tap_land_for_mana`` rather than through the stack, which is what
    CR 605.4a requires of a triggered mana ability.

    The event is checked rather than assumed. "That player" and "any type that
    land produced" are bound by the trigger, so under any other condition there
    is no land and no tapping player for the handler to read — it would add
    mana of an arbitrary type to an arbitrary seat. Refusing here keeps the
    clause unclaimed and visible instead.
    """
    if event != "land_tapped_for_mana":
        raise LoweringError(
            "'that land'/'that player' are bound by a land_tapped_for_mana "
            f"trigger; {event!r} binds neither",
            node=node,
        )
    recipient = _TAPPED_LAND_MANA_RECIPIENTS.get(node.recipient.kind)
    if recipient is None:
        raise LoweringError(
            f"no tapped-land mana recipient for {node.recipient.kind!r}", node=node
        )
    payload: dict[str, object] = {"recipient": recipient}
    if node.pips:
        payload["pips"] = node.pips
    if node.of_type_produced:
        payload["of_type_produced"] = node.of_type_produced
    if node.additional:
        payload["additional"] = True
    return (OracleInstruction("add_mana_for_tapped_land", "", payload),)


def _lower_look_at_hand(node: ast.LookAtHand) -> tuple[OracleInstruction, ...]:
    """"Look at target player's hand." (Glasses of Urza.)

    ``look_at_target_hand`` reads one chosen player off the resolution context
    and builds a single reveal from their hand. "Each opponent's hand" would
    need a loop it does not have and "your hand" is not an effect at all, so
    only the targeted form has a contract to lower onto.
    """
    if node.player.kind != "target_player":
        raise LoweringError(
            f"no handler for looking at {node.player.kind!r}'s hand", node=node
        )
    return (OracleInstruction("look_at_target_hand", "", _targets_only(node.player)),)


# Restrictions the search flow can honour. `card_type` is compared against the
# card's `primary_type` by ai_policy.choose_search_library_index and by the web
# picker, and `is_card` only says the noun phrase named cards — which a library
# holds by definition (CR 400.1). Every other field of the noun phrase is
# refused by _restrictions_beyond, because nothing in the flow tests one: the
# player would simply be offered their whole library.
_SEARCH_HONOURED_FILTER_FIELDS = frozenset({"card_types", "is_card"})


def _lower_search_library(node: ast.SearchLibrary) -> tuple[OracleInstruction, ...]:
    """"Search your library for a card, put that card into your hand, then
    shuffle." (Demonic Tutor.)

    ``search_library`` arms ``pending_search_library``, and
    ``confirm_search_library`` moves exactly **one** card into the *searcher's*
    hand and shuffles. That is its whole contract, so the two halves the parser
    read are checked against it here rather than dropped: a destination other
    than the searcher's own hand has no flow, and a restriction the picker
    cannot test would leave the player choosing from their entire library while
    the card still reported as supported.

    ``count`` is emitted even though only the UI displays it — the legacy rule
    wrote it and the payload has to stay byte-identical — but it is pinned to
    1, the number the confirm flow actually moves.
    """
    if node.player.kind != "you":
        raise LoweringError(
            f"no flow searches {node.player.kind!r}'s library", node=node
        )
    if node.to.name != "hand" or node.to.owner is None or node.to.owner.kind != "you":
        raise LoweringError(
            "the search flow puts the found card into the searcher's own hand", node=node
        )
    filt = node.filter
    if not filt.is_card:
        # "Search your library for a creature" would be a permanent; a library
        # holds cards. Refusing keeps the noun phrase's head word load-bearing.
        raise LoweringError("a library holds cards, not permanents", node=node)
    leftover = _restrictions_beyond(filt, _SEARCH_HONOURED_FILTER_FIELDS)
    if leftover:
        raise LoweringError(
            "the search picker cannot test this restriction: " + ", ".join(leftover),
            node=node,
        )
    if len(filt.card_types) > 1:
        # The picker compares one `primary_type`, so a union would silently
        # widen to whichever type happened to be written first.
        raise LoweringError("the search picker tests one card type", node=node)
    card_type = filt.card_types[0] if filt.card_types else "any"
    return (
        OracleInstruction("search_library", "", {"count": 1, "card_type": card_type}),
    )
