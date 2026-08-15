"""Lowering cards moving: draw, discard, mill, search, and mana.

Includes the two fused shapes that genuinely are one effect rather than a
sequence — "draw then discard" and the tapped-land mana trigger — and the
search filter fields the search flow can actually honour, which is a closed set
because a filter it cannot honour must refuse rather than be dropped.
"""

from ...oracle_types import OracleInstruction
from ...search_filters import SEARCH_COMPARISONS, SEARCH_RESTRICTIONS
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
    # "Discard your hand" (Chandra, Heart of Fire) — the effect's controller
    # discards every card. Checked before the targeted forms: the subject is
    # the implied "you", which they refuse.
    if node.whole_hand:
        if node.player.kind != "you":
            raise LoweringError(
                f"no whole-hand discard handler for {node.player.kind!r}", node=node
            )
        return (OracleInstruction("discard_hand", "", {}),)
    # "Each player discards a card." (Liliana, Waker of the Dead.) The handler
    # records which players could not, because the printed rider "Each opponent
    # who can't loses 3 life." reads that answer out of the same resolution.
    if node.player.kind == "each_player":
        if not isinstance(node.count, ast.Fixed) or node.count.value != 1 or node.at_random:
            raise LoweringError("each-player discards have a one-card handler", node=node)
        return (OracleInstruction("each_player_discards_a_card", "", {}),)
    # "You may draw a card. If you do, discard a card." (Jeskai Elder) — the
    # effect's own controller discards, choosing the cards through the same
    # pending choice the targeted form uses. Fixed counts only: the variable
    # form stays with the random handler below, whose contract it is.
    if node.player.kind == "you":
        amount = _amount_payload(node.count)
        if node.at_random or not isinstance(amount, int):
            raise LoweringError(
                "the controller discard is chosen and fixed-count", node=node
            )
        return (OracleInstruction("discard_controller_cards", "", {"amount": amount}),)
    # "Each opponent discards two cards." (Bad Deal.) Chosen discards, one
    # pending choice per opponent — the random and variable forms stay with the
    # targeted handlers below, whose contracts they are.
    if node.player.kind == "each_opponent":
        amount = _amount_payload(node.count)
        if node.at_random or not isinstance(amount, int):
            raise LoweringError(
                "the each-opponent discard is chosen and fixed-count", node=node
            )
        return (
            OracleInstruction("each_opponent_discards_cards", "", {"amount": amount}),
        )
    if node.player.kind not in ("target_player", "target_opponent", "that_player"):
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

    The miller travels on the payload under the same ``recipient`` key
    ``deal_damage`` and ``target_loses_life`` already read — one convention for
    "who does this happen to" rather than a second one per effect family.
    Absent still means the chosen target, so no payload in the pool changes
    shape. A recipient the handler cannot name refuses rather than defaulting,
    which is the original reason this function refused everything.
    """
    payload: dict[str, object] = {"amount": _amount_payload(node.count)}
    if node.player.kind == "target_player":
        _describe_targets(payload, node.player)
        return (OracleInstruction("mill_target_player", "", payload),)
    if node.player.kind == "you":
        payload["recipient"] = "caster"
        return (OracleInstruction("mill_target_player", "", payload),)
    if node.player.kind == "each_opponent":
        payload["recipient"] = "each_opponent"
        return (OracleInstruction("mill_target_player", "", payload),)
    raise LoweringError(
        f"mill_target_player cannot mill {node.player.kind!r}", node=node
    )


def _lower_scry(node: ast.Scry) -> tuple[OracleInstruction, ...]:
    """"Scry N." (CR 701.22a.)

    One instruction carrying only the count. Deliberately no recipient key: the
    one mill and life loss carry exists because those effects name a victim,
    and scry never does — CR 701.22a is defined over the controller's own
    library, so the handler reads ``context.caster``.
    """
    return (OracleInstruction("scry", "", {"amount": _amount_payload(node.count)}),)


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


def _lower_reveal_top(node: ast.RevealTopToHandOrBottom) -> tuple[OracleInstruction, ...]:
    """"Reveal the top card of your library. If it's a <filter> card, put it
    into your hand. Otherwise, put it on the bottom of your library." (Garruk,
    Savage Herald's +1.) The filter is the whole decision, so it is carried as
    payload the handler tests with primary_type."""
    if not node.filter.is_card or len(node.filter.card_types) != 1:
        raise LoweringError("the reveal-top handler tests one card type", node=node)
    return (
        OracleInstruction(
            "reveal_top_to_hand_or_bottom", "", {"card_type": node.filter.card_types[0]}
        ),
    )


# The ``ObjectFilter`` fields the revealed-hand picker can test. The exclusion
# is the only narrowing any printing of this template uses, and
# `search_filters.search_matches` is what tests it — so a field outside this set
# refuses the line rather than leaving the caster choosing from the whole hand
# while the card claims a restriction. Same rule the search lowering follows,
# and the same predicate underneath it.
_REVEALED_HAND_FIELDS = frozenset({"excluded_types", "is_card"})


def _lower_reveal_hand_and_choose(
    node: ast.RevealHandAndChoose,
) -> tuple[OracleInstruction, ...]:
    """"Target opponent reveals their hand. You choose a noncreature, nonland
    card from it. That player discards that card." (Duress.)

    One instruction for the whole template: the reveal is what makes the choice
    legal, and the discard is what the choice was for, so splitting them would
    put a chosen card between two instructions with nothing carrying it.
    """
    leftover = _restrictions_beyond(node.filter, _REVEALED_HAND_FIELDS)
    if leftover:
        raise LoweringError(
            "the revealed-hand picker cannot narrow by: " + ", ".join(leftover),
            node=node,
        )
    payload: dict[str, object] = {"fate": node.fate}
    if node.filter.excluded_types:
        payload["exclude_types"] = list(node.filter.excluded_types)
    _describe_targets(payload, node.player)
    return (OracleInstruction("reveal_hand_and_choose", "", payload),)


def _lower_exile_graveyard(node: ast.ExileGraveyard) -> tuple[OracleInstruction, ...]:
    """"Exile target player's graveyard." (Tormod's Crypt.)

    The whole zone, so there is no filter to carry and no card to resolve —
    only which player's graveyard, which is the target description.
    """
    return (
        OracleInstruction("exile_target_graveyard", "", _targets_only(node.player)),
    )


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
# card's `primary_type`, and `is_card` only says the noun phrase named cards —
# which a library holds by definition (CR 400.1). The rest come from
# `search_filters.SEARCH_RESTRICTIONS`, the one predicate the engine, the AI and
# the web picker all answer with, so this set cannot claim a restriction nobody
# tests. Every other field of the noun phrase is still refused by
# _restrictions_beyond, because nothing in the flow tests one: the player would
# simply be offered their whole library.
_SEARCH_HONOURED_FILTER_FIELDS = frozenset({"card_types", "is_card"}) | SEARCH_RESTRICTIONS


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
    # Two destinations have a flow: the searcher's own hand (Demonic Tutor)
    # and the battlefield ("search your library for a creature card, put it
    # onto the battlefield" — Garruk, Unleashed's emblem). Anywhere else
    # refuses rather than landing the card in the wrong zone.
    to_battlefield = node.to.name == "battlefield"
    if not to_battlefield and (
        node.to.name != "hand" or node.to.owner is None or node.to.owner.kind != "you"
    ):
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
    restrictions: dict[str, object] = {}
    if filt.named is not None:
        restrictions["named"] = filt.named
    if filt.mana_value is not None:
        # A comparison the predicate cannot apply, or a bound that is not a
        # number ("with mana value X"), refuses rather than lowering to a search
        # that ignores the half of the sentence that made the card printable.
        value = _amount_payload(filt.mana_value.value)
        if filt.mana_value.op not in SEARCH_COMPARISONS or not isinstance(value, int):
            raise LoweringError(
                "the search picker cannot test this mana value: "
                f"{filt.mana_value.op} {value}",
                node=node,
            )
        restrictions["mana_value"] = {"op": filt.mana_value.op, "value": value}
    payload: dict[str, object] = {"count": 1, "card_type": card_type}
    # Both keys are emitted only when the card carries them, so the payload of
    # every search printed before this change — Demonic Tutor's — stays
    # byte-identical and a behaviour signature does not move.
    if restrictions:
        payload["restrictions"] = restrictions
    if node.graveyard:
        payload["zones"] = ("library", "graveyard")
    if to_battlefield:
        payload["destination"] = "battlefield"
    return (OracleInstruction("search_library", "", payload),)


def _lower_exile_top_of_library(node: ast.ExileTopOfLibrary) -> tuple[OracleInstruction, ...]:
    """"Exile the top three cards of your library." (Chandra, Heart of Fire's
    +1.) The handler records what it exiled under ``exiled_cards``, which is
    what makes a following "you may play cards exiled this way" lowerable —
    see ``_lower_cast_permission``'s producer check."""
    amount = _amount_payload(node.count)
    if not isinstance(amount, int) or amount <= 0:
        raise LoweringError(
            "the top-of-library exile handler takes a fixed count", node=node
        )
    return (OracleInstruction("exile_top_of_library", "", {"amount": amount}),)


# Restrictions the exile-search picker tests (engine/search_filters.py's
# vocabulary is not reused because this picker admits a *union* of card types,
# which the single-tutor flow deliberately refuses).
_SEARCH_EXILE_HONOURED = frozenset({"card_types", "colors", "is_card", "type_match"})


def _lower_search_and_exile(node: ast.SearchAndExile) -> tuple[OracleInstruction, ...]:
    """"Search your graveyard and library for any number of red instant and/or
    sorcery cards, exile them, then shuffle." (Chandra, Heart of Fire's −9.)

    Arms the multi-select search choice; the picks are validated against the
    same payload by the resolver, the AI default and the web renderer, so
    every seat answers the same search. A restriction the picker cannot test
    refuses rather than being dropped.
    """
    filt = node.filter
    if not filt.is_card:
        raise LoweringError("a search finds cards, not permanents", node=node)
    leftover = _restrictions_beyond(filt, _SEARCH_EXILE_HONOURED)
    if leftover:
        raise LoweringError(
            "the exile-search picker cannot test this restriction: "
            + ", ".join(leftover),
            node=node,
        )
    payload: dict[str, object] = {
        "zones": ("graveyard", "library"),
        "card_types": tuple(filt.card_types),
        "colors": tuple(filt.colors),
    }
    return (OracleInstruction("search_and_exile_matching", "", payload),)


def _lower_cast_permission(
    node: ast.CastPermission, produced: frozenset[str]
) -> tuple[OracleInstruction, ...]:
    """A cast-or-play permission sentence (CR 601.3), one instruction kind for
    all its printed forms — the differences are payload:

    * ``exiled_this_way`` reads the cards a step of this same effect exiled,
      so it demands the producer exactly as "that much" life does — a
      permission with nothing to permit is the sentence read wrong;
    * ``target_card`` carries the chosen graveyard card and the "exile it
      instead" rider, and deliberately no duration (CR 611.2a);
    * ``spells_from_hand`` is a cost waiver and must carry one, or it would
      state the rules default.
    """
    if node.what == "exiled_this_way":
        if "exiled_cards" not in produced:
            raise LoweringError(
                "back-reference to 'cards exiled this way' with no exile "
                "in this effect",
                node=node,
            )
        if not node.until_end_of_turn:
            raise LoweringError(
                "an exiled-cards permission without its printed duration "
                "would outlive the card that granted it",
                node=node,
            )
        return (
            OracleInstruction(
                "grant_cast_permission", "",
                {
                    "zone": "exile",
                    "mode": node.mode,
                    "cards_from": "exiled_cards",
                    "duration": "end_of_turn",
                },
            ),
        )

    if node.what == "target_card":
        spec = node.target
        filt = spec.filter if spec is not None else None
        if node.mode != "cast" or filt is None:
            raise LoweringError("a targeted permission casts a chosen card", node=node)
        if filt.zone != "graveyard" or filt.zone_owner is None or filt.zone_owner.kind != "you":
            raise LoweringError(
                "the graveyard cast permission reads the caster's own "
                f"graveyard, not the {filt.zone}",
                node=node,
            )
        leftover = _restrictions_beyond(
            filt, _SEARCH_EXILE_HONOURED | {"zone", "zone_owner"}
        )
        if leftover:
            raise LoweringError(
                "the graveyard cast picker cannot test this restriction: "
                + ", ".join(leftover),
                node=node,
            )
        return (
            OracleInstruction(
                "grant_cast_permission", "",
                {
                    "zone": "graveyard",
                    "mode": "cast",
                    "target_graveyard_card": True,
                    "card_types": tuple(filt.card_types),
                    "colors": tuple(filt.colors),
                    "exile_instead": node.exile_instead,
                    "duration": "end_of_turn" if node.until_end_of_turn else None,
                },
            ),
        )

    if node.what == "spells_from_hand":
        if not node.free:
            raise LoweringError(
                "a hand permission without a cost waiver states the rules "
                "default",
                node=node,
            )
        if not node.until_end_of_turn:
            raise LoweringError(
                "an unbounded cost waiver is a different card", node=node
            )
        return (
            OracleInstruction(
                "grant_cast_permission", "",
                {
                    "zone": "hand",
                    "mode": "cast",
                    "free": True,
                    "duration": "end_of_turn",
                },
            ),
        )

    raise LoweringError(f"no cast-permission lowering for {node.what!r}", node=node)


def _lower_look_top_pick(node: ast.LookTopPickToHand) -> tuple[OracleInstruction, ...]:
    """"Look at the top three cards of your library. Put one of those cards
    into your hand and the rest on the bottom of your library in any order.
    …" (See the Truth.) The handler asks its controller through the
    pending-choice queue when cast from the hand, and skips the choice
    entirely when the cast came from anywhere else — the conditional reads
    ``OracleExecutionContext.cast_from_zone``."""
    amount = _amount_payload(node.count)
    if not isinstance(amount, int) or amount <= 0:
        raise LoweringError("the look-top pick takes a fixed count", node=node)
    return (OracleInstruction("look_top_pick_to_hand", "", {"amount": amount}),)
