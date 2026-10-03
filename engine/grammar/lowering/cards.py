"""Lowering cards off the top of a library: draw, mill, scry.

The other flows this module used to hold have families of their own: mana
production in `mana.py`, the hidden-zone search/reveal/exile-linkage flows in
`library.py`, and everything that names cards already in a hand — the discard
family with its two fused draw/discard shapes, and a hand put back onto a
library — in `hand.py`.
"""

from ...oracle_types import (DISCARDED_BY_SEAT, MILLED_THIS_WAY,
                             PER_OBJECT_SEAT_RECORDS,
                             X_FROM_COUNT, X_FROM_COUNT_PER_RECIPIENT,
                             OracleInstruction)
from .. import ast
from ..errors import LoweringError
from ._amounts import count_spec, halved_count_spec
# The characteristics ``count_from_payload`` reads off a cost-eaten
# permanent. A floor, shared with the damage family that named it: a mill
# sized by one asks the same question a damage sized by one does, and two
# copies of the list is how one of them comes to emit a characteristic the
# evaluator cannot answer.
from ._counted_damage import _READABLE_COST_SACRIFICE_CHARACTERISTICS
from ._common import (
    dropped_narrowings,
    _amount_payload,
    _describe_targets,
    _restrictions_beyond,
)
from ._events import (
    _DAMAGED_PLAYER_EVENTS,
    _DEFENDING_PLAYER_EVENTS,
    _EVENT_SUBJECT_PLAYERS,
    EVENT_SUBJECT_PLAYER,
    _back_reference_payload,
)








def _lower_next_draw_replacement(
    node: "ast.NextDrawReplacement", effect: tuple[OracleInstruction, ...],
) -> tuple[OracleInstruction, ...]:
    """"The next time you would draw a card this turn, instead <effect>."
    (Mangara's Tome.)

    *effect* is the inner sentence, already lowered by the dispatch — the same
    arrangement ``_lower_create_delayed_trigger`` has, and for its reason: what
    the sentence means does not depend on being wrapped, and lowering it here
    would be a second dispatch. It is lowered under the *line's* own event
    rather than under the replaced draw, which is the difference from a delayed
    ability: nothing in "instead put the top card of the exiled pile into its
    owner's hand" is relative to a draw, where "you gain **that much** life"
    behind a delay is relative to the event the delay names.

    An effect that lowered to nothing refuses, exactly as a delayed ability
    with no effect does: a replacement armed over an empty instruction takes
    the draw away and gives the player nothing back, which is a strictly worse
    card than the one printed.
    """
    if not effect:
        raise LoweringError("this replacement has no effect", node=node)
    # Several sentences behind one "instead" are one replacement's effect
    # (CR 608.2), so they compose the way every other multi-step effect does.
    instruction = (
        effect[0] if len(effect) == 1
        else OracleInstruction("sequence", "", {"steps": list(effect)})
    )
    return (
        OracleInstruction("arm_draw_replacement", "", {"instruction": instruction}),
    )


#: The single-number scratchpad key a step writes, and the per-seat map it
#: writes *beside* it. A looped drawer's "that many" has one answer per player,
#: so it reads the map; the flat key is the same event asked by one seat about
#: its own answer, and reading it here would give every player the last
#: answer's number. Two keys because one cannot be both — the same reason
#: ``DISCARDED_BY_SEAT`` exists at all.
_LOOPED_SEAT_RECORDS: dict[str, str] = {
    "discarded_count": DISCARDED_BY_SEAT,
}


def _lower_draw(
    node: ast.Draw,
    produced: frozenset[str] = frozenset(),
    event: str | None = None,
) -> tuple[OracleInstruction, ...]:
    """"You draw" and "target player draws" are different handlers, not one
    handler with a recipient flag: ``draw_controller_cards`` draws for the
    effect's controller, ``draw_target_cards`` for the chosen player. Picking by
    the drawer keeps each one's existing contract intact.

    *produced* and *event* are what a back-referenced count needs — "draws **as
    many cards as they discarded this way**" (Forget) — and they are the reason
    this lowering is dispatched from ``lower.py``'s chain rather than from
    ``by_node``'s name-only table.
    """
    # "For each creature exiled this way, **its controller** draws a card."
    # (Martyr's Cry.) A possessive with no target in front of it: whose hand it
    # is, is a fact an earlier step recorded about the loop's object, so it
    # travels as the record's name and the handler resolves it per iteration.
    #
    # Without this the pronoun fell into the branch below and drew for
    # ``context.target`` — a seat this sentence never named — which is the
    # silent widening `PER_OBJECT_SEAT_RECORDS` exists to close.
    if node.up_to:
        # "…may draw **up to** two cards" (Truce). A ceiling is a *decision* —
        # how many, answered by the drawing seat — and only the prompt behind
        # `each_player_draws_up_to_cards` asks one.
        #
        # "**Then each player draws up to seven cards.**" (Diminishing Returns.)
        # The same decision with no "may" printed in front of it, which is not a
        # different card: "up to seven" already lets a seat draw none, so the
        # offer `_collapses._each_player_optional_draw` collapses was never
        # what made the choice — the ceiling was. That collapse reaches this
        # instruction from a `May` node; this reaches it from the bare sentence,
        # and both arrive at one handler so what a seat is asked cannot depend
        # on which spelling the card used.
        if node.player.kind in ("each_player", "each_opponent"):
            return (
                OracleInstruction(
                    "each_player_draws_up_to_cards", "",
                    {"amount": _amount_payload(node.count), "actor": node.player.kind},
                ),
            )
        # "**That player** draws up to three cards." (Fatal Lore, inside the
        # mode an opponent chose.) One seat rather than a set, which is
        # `draw_up_to_cards` — the kind Arcane Denial already uses, reading its
        # drawer off a *record* rather than off `context.target`, and
        # `EVENT_SUBJECT_PLAYER` is that record for every phrase whose seat an
        # announcement froze. So the sentence needs no handler of its own: the
        # ceiling prompt, the seat lookup and the CR 614 draw are all already
        # behind that kind.
        #
        # Gated on the event, exactly as the mill and the damage readings of the
        # same two words are: with nothing frozen, "that player" names whoever
        # the resolution happened to be carrying, which is a choice the card
        # never offers.
        if node.player.kind == "that_player" and event in _EVENT_SUBJECT_PLAYERS:
            return (
                OracleInstruction(
                    "draw_up_to_cards", "",
                    {
                        "amount": _amount_payload(node.count),
                        "drawer_seat_record": EVENT_SUBJECT_PLAYER,
                    },
                ),
            )
        # Every other drawer still refuses: read as an amount they would draw
        # the maximum, and a forced draw is a different card from an offered
        # one — on Truce, the difference is the whole of what the card does.
        raise LoweringError(
            "no draw handler offers a ceiling the drawer chooses under",
            node=node,
        )
    drawer_seat = (
        PER_OBJECT_SEAT_RECORDS["controller"]
        if node.player.kind == "controller" else None
    )
    kind = (
        "draw_controller_cards" if node.player.kind == "you" else "draw_target_cards"
    )
    # "**Each player** draws a card." (Winter Sky.) A *set* of seats, which the
    # bare `draw_target_cards` reading cannot express: the handler draws for
    # `context.target`, one seat, so a card printing "each player" drew for the
    # opponent alone — the right answer for nobody and, in a duel, half the
    # card. The same ``recipient`` key `mill_target_player` already reads for
    # exactly this phrase one zone over, so nothing new is invented: which
    # seats an effect happens to is one convention across the engine.
    looped_seats = (
        node.player.kind
        if node.player.kind in ("each_player", "each_opponent") else None
    )
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
    elif isinstance(node.count, ast.GreatestDiscardedThisWay):
        # "…draws cards equal to **the greatest number of cards a player
        # discarded this way**." (Windfall.) A maximum over the per-seat record
        # the discard in front of this one wrote — not a count of any zone, so
        # it travels the shared ``x_from_count`` channel with an aggregate the
        # evaluator answers rather than a zone spec. One number for every
        # drawer, which is what makes the loop below leave it alone.
        #
        # Gated on that record really being written: with no producer the words
        # name nothing, and every player would draw zero on a card reporting
        # itself supported.
        if DISCARDED_BY_SEAT not in produced:
            raise LoweringError(
                f"back-reference to {DISCARDED_BY_SEAT!r} with no producer in "
                "this effect",
                node=node,
            )
        payload: dict[str, object] = {
            "amount": "x",
            X_FROM_COUNT: {"greatest_per_seat": DISCARDED_BY_SEAT},
        }
    elif isinstance(node.count, ast.CountOfSacrificesThisWay):
        # "Sacrifice any number of artifacts, creatures, and/or lands. Draw a
        # card **for each permanent sacrificed this way**." (Reprocess.) The
        # number is what the sentence in front of this one actually took, and
        # nothing on a board holds it: "any number" prints no count, and by now
        # the permanents are cards in a graveyard (CR 400.7) among everything
        # else that ever arrived there.
        #
        # So it travels on ``recorded_cards`` — the channel Song of Blood's
        # milled-card count already uses — which counts the entries of a
        # recorded *list* against a printed phrase, rather than reading a slot
        # that holds a number. Gated on a step of this same effect really
        # writing that list: with no producer the words name nothing and the
        # draw would be zero on a card reporting itself supported.
        if "sacrificed_cards" not in produced:
            raise LoweringError(
                "back-reference to 'sacrificed_cards' with no producer in "
                "this effect",
                node=node,
            )
        from ...subject_filters import card_only_filter

        described = card_only_filter(node.count.filter.to_payload())
        if described is None or dropped_narrowings(
            node.count.filter, node.count.filter.to_payload()
        ):
            # Only what is *printed* is testable off a record (CR 613.1): the
            # permanents are gone, and what was kept is their cards. A narrowing
            # the card matcher cannot answer refuses rather than being counted
            # as though it were not there — a count that is too large is a draw
            # the card never offered.
            raise LoweringError(
                "a sacrificed-permanent count cannot test this restriction",
                node=node,
            )
        payload: dict[str, object] = {
            "amount": "x",
            X_FROM_COUNT: {
                "recorded_cards": "sacrificed_cards", "filter": described,
            },
        }
    elif isinstance(node.count, ast.SacrificedForCost):
        # "Sacrifice a creature: Draw cards equal to **the sacrificed
        # creature's power**, then discard three cards." (Greater Good.) A
        # characteristic of the permanent the ability's own cost ate
        # (CR 601.2h), so it is on no board by the time this resolves — read
        # off the record the activation kept (CR 608.2h), through the same
        # ``x_from_count`` channel `_lower_mill` already reads it on for Altar
        # of Dementia. One evaluator, so the two sentences cannot count
        # differently; and the characteristic is held to what that evaluator
        # answers, because one it cannot is a card that reports supported and
        # draws nothing.
        if node.count.characteristic not in _READABLE_COST_SACRIFICE_CHARACTERISTICS:
            raise LoweringError(
                "no handler reads the sacrificed permanent's "
                f"{node.count.characteristic!r}",
                node=node,
            )
        payload: dict[str, object] = {
            "amount": "x",
            X_FROM_COUNT: {
                "cost_sacrifice_characteristic": node.count.characteristic
            },
        }
    elif isinstance(node.count, ast.CountersOnSource):
        # "…draws an additional card **for each growth counter on this
        # enchantment**." (Malignant Growth.) A number on the ability's own
        # source, which only a resolution knows — so it travels as the same
        # ``x_from_count`` spec the where-clause spelling of the identical phrase
        # produces (`where_x._lower_where_x_counters`), resolved at the one
        # substitution point. One evaluator, so the two printed word orders
        # cannot count differently.
        payload: dict[str, object] = {
            "amount": "x", X_FROM_COUNT: {"source_counters": node.count.kind},
        }
    elif isinstance(node.count, ast.ThatMuch):
        # "Target player discards two cards, then draws **as many cards as they
        # discarded this way**." (Forget.) The number is one an earlier step of
        # this same resolution recorded, and where it is read from is decided in
        # the one place that decides it for every back-reference — which refuses
        # outright when no step of this effect produces the key, because the
        # words would otherwise name nothing and draw zero on a card reporting
        # itself supported.
        payload: dict[str, object] = {"amount": 0}
        payload.update(_back_reference_payload(node.count, produced, event))
    else:
        payload = {"amount": _amount_payload(node.count)}
    if drawer_seat is not None:
        payload["drawer_seat"] = drawer_seat
    if looped_seats is not None:
        payload["recipient"] = looped_seats
        # "**Each player** draws a card **for each creature card in their
        # graveyard**." (Nature's Resurgence.) One number per seat, so it
        # cannot be the single X: `draw_target_cards`' looping branch resolves
        # ``amount`` once, against the *cast's* X, and a shared count there
        # would have every seat draw whatever `context.x_value` held — zero for
        # a spell that announces no X, which is a card compiling supported and
        # drawing nothing.
        #
        # Moved onto the per-recipient channel `each_player_discards_a_card`
        # already reads for "a third of the cards in **their** hand", and for
        # that channel's reason: the evaluator is owner-blind and is handed the
        # seat, which is exactly what "their" names. A count scoped to somebody
        # *else* ("…for each card in **your** hand") is one shared number and
        # belongs on the ordinary channel — but the looping handler has no
        # reader for that at all, so it refuses rather than drawing zero.
        # "…**then draws that many cards**." (Flux.) The number the *same seat*
        # just gave, which the each-player discard writes per seat as each
        # prompt is answered. The bare back-reference above resolved it to
        # ``discarded_count`` — one number, the last seat to answer — so every
        # player would have drawn whatever the final answer happened to be.
        recorded = payload.pop("amount_from", None)
        if recorded is not None:
            per_seat = _LOOPED_SEAT_RECORDS.get(recorded)
            if per_seat is None:
                raise LoweringError(
                    f"no per-seat record behind a looped draw of {recorded!r}",
                    node=node,
                )
            payload.pop("amount", None)
            payload[X_FROM_COUNT_PER_RECIPIENT] = {"seat_record": per_seat}
            _describe_targets(payload, node.player)
            return (OracleInstruction(kind, "", payload),)
        shared = payload.get(X_FROM_COUNT)
        # "…draws cards equal to **the greatest** number of cards **a player**
        # discarded this way." (Windfall.) One number for the whole table, which
        # is the opposite of the per-seat counts below: the aggregate is taken
        # *across* the seats, so moving it onto the per-recipient channel would
        # re-take the maximum once per drawer and answer the same thing every
        # time — or, read as a zone count, refuse a spec that names no zone.
        # It stays on the shared channel, where the one substitution point
        # resolves it into `context.x_value` before the looping handler reads
        # ``amount`` once.
        if shared is not None and "greatest_per_seat" not in shared:
            payload.pop(X_FROM_COUNT, None)
            if shared.get("owner") not in ("owner", "target"):
                raise LoweringError(
                    "a looped draw counts each drawer's own zone", node=node,
                )
            payload.pop("amount", None)
            payload[X_FROM_COUNT_PER_RECIPIENT] = shared
    if node.player.kind == "that_player" and event in _EVENT_SUBJECT_PLAYERS:
        # "At the beginning of each opponent's draw step, **that player** draws
        # an additional card." (Malignant Growth.) The seat the fire site froze
        # (CR 603.10) — the reading `_lower_mill` takes of the same two words
        # below, off the record `draw_up_to_cards` already reads for the ceiling
        # spelling. Without it the draw fell through to ``context.target``, which
        # for a trigger that chose nothing is whatever the resolution held: this
        # card would have drawn its own controller the cards.
        payload["drawer_seat_record"] = EVENT_SUBJECT_PLAYER
    elif node.player.kind == "that_player" and event in _DAMAGED_PLAYER_EVENTS:
        # "Whenever this creature deals damage to a player, **that player**
        # discards all the cards in their hand, then draws that many cards."
        # (Shocker.) The **other** record the same two words name — a damage
        # event freezes the damaged player under ``defending_player_index``,
        # and the branch above is keyed on the seat-subject one. Shocker had
        # neither: the discard carried ``who: "damaged_player"`` and the draw
        # beside it carried nothing at all, so the opponent emptied their hand
        # and Shocker's own controller drew the cards.
        payload["drawer_seat_record"] = "defending_player_index"
    elif node.player.kind == "defending_player":
        # "Whenever this creature becomes blocked, **defending player** discards
        # all the cards in their hand, then draws that many cards." (Robber
        # Fly.) CR 506.2's seat, stamped by the combat fire sites under the key
        # every other reader of the phrase asks — and refused where no event
        # froze one, because the fall-through below describes no target for this
        # word and the draw would land on whatever seat the resolution held.
        if event not in _DEFENDING_PLAYER_EVENTS:
            raise LoweringError(
                '"defending player" names a seat this event did not record',
                node=node,
            )
        payload["drawer_seat_record"] = "trigger_defending_player_index"
    _describe_targets(payload, node.player)
    return (OracleInstruction(kind, "", payload),)


def _lower_mill(
    node: ast.Mill, event: str | None = None
) -> tuple[OracleInstruction, ...]:
    """"Target player mills N cards." (CR 701.17a, Millstone.)

    The miller travels on the payload under the same ``recipient`` key
    ``deal_damage`` and ``target_loses_life`` already read — one convention for
    "who does this happen to" rather than a second one per effect family.
    Absent still means the chosen target, so no payload in the pool changes
    shape. A recipient the handler cannot name refuses rather than defaulting,
    which is the original reason this function refused everything.
    """
    # "Target player mills cards equal to **the sacrificed creature's power**."
    # (Altar of Dementia.) A characteristic of the permanent the ability's own
    # cost ate (CR 601.2h), so it is on no board by the time this resolves — it
    # is read off the record the activation kept, through the one
    # ``x_from_count`` channel `_execute_oracle_instruction` resolves for every
    # family. The characteristic is checked against what the evaluator can
    # actually answer, because one it cannot is a card that reports supported
    # and mills nothing.
    if isinstance(node.count, ast.SacrificedForCost):
        if node.count.characteristic not in _READABLE_COST_SACRIFICE_CHARACTERISTICS:
            raise LoweringError(
                "no handler reads the sacrificed permanent's "
                f"{node.count.characteristic!r}",
                node=node,
            )
        payload: dict[str, object] = {
            "amount": "x",
            X_FROM_COUNT: {
                "cost_sacrifice_characteristic": node.count.characteristic
            },
        }
    else:
        payload = {"amount": _amount_payload(node.count)}
    if node.player.kind == "that_player":
        # "Whenever this creature deals damage to an opponent, **that player**
        # mills a card." (Reef Pirates.) The seat is the one the damage event
        # froze (CR 603.10), read from the trigger's context under the key
        # every damage announcement stamps — the same reading the on-damage
        # discard (Nicol Bolas) and the on-damage poison counter (Pit Scorpion)
        # take of the same two words.
        #
        # Gated on the event rather than admitted outright, because a trigger
        # that offers no choice has nothing in ``context.target`` but whatever
        # the resolution was already carrying: this phrase reads a seat the
        # fire site froze or it refuses, which is the contract `_events.py`
        # states and the one the damage family's own fall-through breaks.
        #
        # Two records, because two different fire sites freeze two different
        # seats under two different keys. A damage event freezes the seat the
        # damage went to (`defending_player_index`); a step whose *subject is a
        # player* — "at the beginning of each player's upkeep, **that player**
        # mills a card" (Worry Beads) — freezes whose step it is
        # (`EVENT_SUBJECT_PLAYER`). The draw one family up has read both since
        # Malignant Growth and its comment already claimed this function did
        # too; it did not, and the words are the same words. A card printing
        # them under a seat-freezing step reported "no handler" and the set's
        # own artifact was unsupported for a record that was already stamped.
        if event in _EVENT_SUBJECT_PLAYERS:
            payload["recipient"] = EVENT_SUBJECT_PLAYER
            return (OracleInstruction("mill_target_player", "", payload),)
        if event not in _DAMAGED_PLAYER_EVENTS:
            raise LoweringError(
                '"that player" mills only under a trigger whose event froze a '
                "damaged player or the seat whose step it is",
                node=node,
            )
        payload["recipient"] = "damaged_player"
        return (OracleInstruction("mill_target_player", "", payload),)
    if node.player.kind in ("target_player", "target_opponent"):
        # "Target **opponent** mills two cards" (Teferi's Tutelage). The handler
        # already mills ``context.target``, whoever that is; what "opponent"
        # changes is which seats the picker may offer (CR 102.2/102.3), and that rides
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
    if node.player.kind == "each_player":
        # "{3}: **Each player** mills two cards." (Whetstone.) The same
        # ``recipient`` key the draw one zone over already reads for the same
        # two words, and the same reason it is a set of seats rather than a
        # target: each miller mills their own library, so the handler loops.
        # CR 101.4's order is the handler's, where the active player is known.
        payload["recipient"] = "each_player"
        return (OracleInstruction("mill_target_player", "", payload),)
    if node.player.kind == "defending_player":
        # "Whenever this creature becomes blocked, **defending player** mills
        # three cards." (Flint Golem.) CR 506.2's seat, frozen into the
        # trigger's context by the combat fire site — the reading the draw
        # above, the discard and the life loss already take of the same two
        # words, behind the same gate: under any other event nothing recorded a
        # defender, and a mill aimed at nobody compiles clean and then lands on
        # whichever seat the resolution happened to be carrying.
        if event not in _DEFENDING_PLAYER_EVENTS:
            raise LoweringError(
                '"defending player" names a seat this event did not record',
                node=node,
            )
        payload["recipient"] = "defending_player"
        return (OracleInstruction("mill_target_player", "", payload),)
    raise LoweringError(
        f"mill_target_player cannot mill {node.player.kind!r}", node=node
    )


def _lower_mill_until(node: ast.MillUntil) -> tuple[OracleInstruction, ...]:
    """"Target opponent mills a card, then repeats this process until a
    creature card or X cards have been put into their graveyard this way,
    whichever comes first." (Helm of Obedience.)

    Its own kind rather than ``mill_target_player`` with two extra keys: that
    handler moves N cards in one go and never looks at them, and a loop is not
    a count. Reading this as one would mill X cards whatever came off the top,
    which is the same card with its whole point removed.

    The miller is a *target* opponent and nothing else. "Whose graveyard" is
    the question the record behind this sentence answers, so a wording naming a
    seat the picker cannot offer refuses rather than defaulting to whoever the
    resolution happened to be carrying.
    """
    if node.player.kind not in ("target_player", "target_opponent"):
        raise LoweringError(
            f"a repeated mill cannot mill {node.player.kind!r}", node=node
        )
    leftover = _restrictions_beyond(
        node.stop_filter, {"card_types", "is_card", "type_match"}
    )
    if leftover:
        raise LoweringError(
            "a repeated mill cannot stop on this restriction: "
            + ", ".join(leftover),
            node=node,
        )
    payload: dict[str, object] = {
        # A card-filter payload rather than a bare list of type words, because
        # what tests it is ``_card_matches_filter`` — the one matcher that can
        # answer of a card in a zone, where the shared permanent matcher asks
        # ``has_type`` of a battlefield object that does not exist here.
        "stop_filter": {"type_filter": list(node.stop_filter.card_types)},
        "limit": _amount_payload(node.limit),
    }
    _describe_targets(payload, node.player)
    return (OracleInstruction("mill_until_matching", "", payload),)


def _lower_put_milled_card_onto_battlefield(
    node: ast.PutMilledCardOntoBattlefield, produced: frozenset[str]
) -> tuple[OracleInstruction, ...]:
    """"…put one of them onto the battlefield under your control." (Helm of
    Obedience.)

    The producer is demanded exactly as "that much" life is: "them" names a set
    an earlier step of this same effect recorded, and a sentence with nothing
    in front of it that recorded one is the sentence read wrong. Without the
    check it would compile against an empty list and put nothing onto the
    battlefield, which is a supported card that does nothing.
    """
    if MILLED_THIS_WAY not in produced:
        raise LoweringError(
            "'one of them' with no repeated mill in this effect to have named "
            "a set",
            node=node,
        )
    return (
        OracleInstruction(
            "put_milled_card_onto_battlefield", "",
            {"cards_from": MILLED_THIS_WAY, "under_your_control": True},
        ),
    )


def _lower_scry(node: ast.Scry) -> tuple[OracleInstruction, ...]:
    """"Scry N." (CR 701.22a.)

    One instruction carrying only the count. Deliberately no recipient key: the
    one mill and life loss carry exists because those effects name a victim,
    and scry never does — CR 701.22a is defined over the controller's own
    library, so the handler reads ``context.caster``.
    """
    return (OracleInstruction("scry", "", {"amount": _amount_payload(node.count)}),)
