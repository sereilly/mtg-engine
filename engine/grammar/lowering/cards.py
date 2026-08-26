"""Lowering cards moving between hand and library: draw, discard, mill, scry.

Includes the two fused draw/discard shapes that genuinely are one effect
rather than a sequence. The other flows this module used to hold have
families of their own: mana production in `mana.py`, the hidden-zone
search/reveal/exile-linkage flows in `library.py`.
"""

from ...oracle_types import X_FROM_COUNT, OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._common import (
    chargeable_card_filter,
    _amount_payload,
    halved_count_spec,
    _describe_targets,
    _is_you,
    count_spec,
)
from ._events import (
    _DAMAGED_PLAYER_EVENTS,
)


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
    # Only the controller's own discard carries a narrowing today; every other
    # handler below arms a prompt that takes the whole hand, so a filter reaching
    # them would be silently dropped.
    if node.filter is not None and node.player.kind != "you":
        raise LoweringError(
            f"no {node.player.kind!r} discard handler carries a narrowing", node=node
        )
    if node.whole_hand:
        if node.player.kind == "you":
            return (OracleInstruction("discard_hand", "", {}),)
        # "…, that player discards their hand" (Nicol Bolas). The same effect
        # aimed at the seat the firing event recorded, so it is the same
        # instruction with a `who` — a second kind would be a second copy of
        # emptying a hand. Admitted only under a trigger whose fire site
        # actually froze a damaged player: under any other event the words name
        # a seat nobody recorded, and the discard would silently empty the
        # ability's own controller's hand.
        if node.player.kind == "that_player" and event in _DAMAGED_PLAYER_EVENTS:
            return (
                OracleInstruction("discard_hand", "", {"who": "damaged_player"}),
            )
        raise LoweringError(
            f"no whole-hand discard handler for {node.player.kind!r}", node=node
        )
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
        payload: dict[str, object] = {"amount": amount}
        # "Discard a **creature** card" (Crypt Lurker). Gated by the same reader
        # the discard *cost* is (round 87): the prompt and its re-check ask
        # ``_card_matches_filter``, so a phrase reaching past what that can
        # answer would be dropped where it is applied — and a dropped narrowing
        # here is a discard that takes any card at all while the card still
        # reports supported.
        if node.filter is not None:
            described = chargeable_card_filter(node.filter)
            if not described:
                raise LoweringError(
                    "no discard prompt can test this narrowing", node=node
                )
            payload["filter"] = described
        return (OracleInstruction("discard_controller_cards", "", payload),)
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


def _fused_discard_then_draw(
    steps: tuple[ast.Statement, ...]
) -> tuple[OracleInstruction, ...] | None:
    """"Discard up to two cards, then draw that many cards." (Kinetic Augur.)

    The mirror of :func:`_fused_draw_then_discard`, and fused for a *different*
    reason. That one is fused because no controller-discard handler existed;
    this one because **the second number is the answer to the first**. "That
    many" is however many cards the player chose to discard, and the choice is a
    pending prompt — so decomposed, the draw would run while the prompt was
    still owed and draw nothing at all, with the card reporting supported.

    One instruction arms the prompt and records what to do when it is answered.
    That is also why the pair must be exactly this shape: any other second step
    has no reason to wait, and any other count has nothing to read.
    """
    if len(steps) != 2:
        return None
    discard, draw = steps
    if not (isinstance(discard, ast.Discard) and isinstance(draw, ast.Draw)):
        return None
    if not (_is_you(discard.player) and _is_you(draw.player)):
        return None
    if discard.at_random or discard.whole_hand or discard.filter is not None:
        return None
    if not isinstance(discard.count, ast.Fixed) or not isinstance(draw.count, ast.ThatMuch):
        return None
    return (
        OracleInstruction(
            "discard_then_draw_that_many", "",
            {"amount": discard.count.value, "up_to": discard.up_to},
        ),
    )


def _lower_draw(node: ast.Draw) -> tuple[OracleInstruction, ...]:
    """"You draw" and "target player draws" are different handlers, not one
    handler with a recipient flag: ``draw_controller_cards`` draws for the
    effect's controller, ``draw_target_cards`` for the chosen player. Picking by
    the drawer keeps each one's existing contract intact."""
    kind = "draw_controller_cards" if node.player.kind == "you" else "draw_target_cards"
    halved = (
        halved_count_spec(node.count, node) if isinstance(node.count, ast.Half) else None
    )
    if halved is not None:
        # "…draws cards equal to **half** the number of cards in their library"
        # (Peer into the Abyss). The same spec a plain count travels on, with the
        # division recorded on it — see `halved_count_spec`.
        payload: dict[str, object] = {"amount": "x", X_FROM_COUNT: halved}
    elif isinstance(node.count, ast.ColorsAmong):
        # "Draw a card **for each color among** permanents you control"
        # (Chromatic Orrery). The same spec a plain count travels on, with the
        # aggregate that says colours rather than objects — one evaluator, so
        # the where-clause form of this phrase and the per-each form cannot
        # disagree about what "colour" counts.
        payload: dict[str, object] = {
            "amount": "x",
            X_FROM_COUNT: count_spec(
                node.count.filter, node, aggregate="distinct_colors"
            ),
        }
    elif isinstance(node.count, ast.CountOf):
        # "Draw cards equal to the number of …" (Frantic Inventory). The count
        # is taken at *resolution* (CR 608.2), so it travels as the same
        # ``x_from_count`` spec a where-clause defines and the amount is the
        # string the single dispatch point already resolves. Stamped on this
        # instruction alone rather than over the sentence: the count belongs to
        # this draw, and "draw a card, then draw cards equal to …" has a
        # literal 1 in front of it that must stay one.
        payload: dict[str, object] = {
            "amount": "x", X_FROM_COUNT: count_spec(node.count.filter, node),
        }
    else:
        payload = {"amount": _amount_payload(node.count)}
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
    if node.player.kind in ("target_player", "target_opponent"):
        # "Target **opponent** mills two cards" (Teferi's Tutelage). The handler
        # already mills ``context.target``, whoever that is; what "opponent"
        # changes is which seats the picker may offer (CR 115.4), and that rides
        # on the targets description `_describe_targets` builds — the same
        # `opponents_only` flag every other opponent-targeted effect carries.
        # Reading it as a plain target player would have let the caster mill
        # themselves.
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
