"""The statements a player answers by **naming** something or making a choice.

Split from ``statement_dispatch.py`` at Tempest's Phase 0, under
SET_PLAYBOOK.md's rule that a module two groups will both reach is pre-split
before the fan-out rather than at integration: that file stood eight lines
under the 1,000-line cap with five groups about to land arms in it, and every
new statement kind lands in that chain.

The seam is the one the arms already draw. Everything here reads a **decision**
rather than a board: a card name (Necromentia, Nebuchadnezzar, Cursed Scroll),
a number, a colour, a card type, a player, a coin. The lowering carries the
bounds of the choice and nothing else, because what the choice is *for* is a
different sentence on the card that reads back what this one recorded — which
is why the cluster shares no helper with the damage, destruction or counter
arms it sat between.

The four that are not choices came with them for the reason a split follows
the arms rather than the vocabulary: ``ExileBoundCard``, ``PutExiledCardIntoZone``,
``RevealUntil`` and the two copy nodes are the rest of one printed paragraph —
"name a card, reveal until you find it, exile the rest" is one sentence's worth
of arms, and cutting between them would put half a card in each file.

``lower_statement`` calls :func:`lower_naming_statement` where the arms used to
sit, and a ``None`` means "no arm here matched" — the chain continues. That is
the same contract ``by_node.py`` has with its table.
"""

from __future__ import annotations

from ..oracle_types import OracleInstruction
from . import ast
from .errors import LoweringError
from .lowering._deaths import BOUND_CARD_EVENTS
from .lowering._events import CHOSEN_PLAYER, chooser_payload as _chooser_payload
from .lowering import (
    _amount_payload,
    _lower_put_exiled_card_into_zone,
    _lower_reveal_top_sorting_by_chosen_name,
    _lower_reveal_until,
    _targets_payload,
)


def lower_naming_statement(
    statement: ast.Statement,
    produced: frozenset[str],
    event: str | None,
) -> tuple[OracleInstruction, ...] | None:
    """The arms above, or None when this statement is none of them."""
    if isinstance(statement, ast.NameAndStrip):
        # "Search **target opponent's** graveyard, hand, and library …"
        # (Necromentia). The searched seat is chosen as the spell is cast
        # (CR 601.2c) and the production spells the words out, so the
        # description is emitted here the way its sibling below emits
        # Nebuchadnezzar's — and for the same reason: the kind table answers a
        # bare ``{"kind": "player"}`` for `name_and_strip`, which offered the
        # caster their own graveyard, hand and library (CR 115.4). The picker
        # offers exactly what this describes.
        return (
            OracleInstruction(
                "name_and_strip", "",
                {
                    "zones": list(statement.zones),
                    "token_zone": statement.token_zone,
                    "token": {
                        "power": statement.token_power,
                        "toughness": statement.token_toughness,
                        "colors": list(statement.token_colors),
                        "subtypes": list(statement.token_subtypes),
                    },
                    "targets": {
                        "quantifier": "target",
                        "kind": "player",
                        "opponents_only": True,
                    },
                },
            ),
        )

    if isinstance(statement, ast.NameAndRandomReveal):
        # "Target opponent" is the only seat this paragraph names, and every
        # sentence after the first is about that same seat — "that player" is
        # the revealer. A description is emitted so the picker chooses the
        # opponent at activation (CR 601.2c), and the count rides as the
        # announced amount rather than a number, because X is not known until
        # the ability is activated.
        return (
            OracleInstruction(
                "name_and_random_reveal", "",
                {
                    "count": _amount_payload(statement.count),
                    "zone": statement.zone,
                    "targets": {
                        "quantifier": "target",
                        "kind": "player",
                        "opponents_only": True,
                    },
                },
            ),
        )

    if isinstance(statement, ast.RepeatedGraveyardPick):
        # "**Target opponent** chooses" — a chosen seat, which the picker has to
        # offer and the handler has to read. Any other reference names a seat
        # nothing chose.
        if statement.chooser.kind != "target_opponent":
            raise LoweringError(
                "the repeated graveyard pick is made by the opponent this "
                "spell targets",
                node=statement,
            )
        payload: dict[str, object] = {
            "cost": {symbol: count for symbol, count in statement.cost.pips},
            "targets": _targets_payload(statement.chooser),
        }
        return (OracleInstruction("repeated_graveyard_pick", "", payload),)

    if isinstance(statement, ast.PutExiledCardIntoZone):
        return _lower_put_exiled_card_into_zone(statement, produced)

    if isinstance(statement, ast.ExileBoundCard):
        # "Whenever a nontoken creature is put into your graveyard from the
        # battlefield, **exile that card**." (Purgatory.) No printed zone,
        # because the trigger's own condition already said which one — so the
        # card is the ``dead_card`` the death seam froze (CR 603.10) and the
        # handler looks for it by identity wherever CR 404.1 put it.
        #
        # Gated on the same ``BOUND_CARD_EVENTS`` every other reading of "that
        # card" is gated on: an event that records no card makes these two
        # words name nothing, and the honest answer is a refusal rather than a
        # handler that finds nothing while the card compiles supported.
        if statement.from_zone is None:
            if event not in BOUND_CARD_EVENTS:
                raise LoweringError(
                    "'that card' names the firing event's object, and this "
                    "event records none",
                    node=statement,
                )
            return (OracleInstruction("exile_bound_card", "", {}),)
        # "Exile **that card** from your graveyard." (Necropotence.) The object
        # the firing event named, so the event has to be one whose fire site
        # records it — under anything else the words name a card nobody wrote
        # down, and the handler would find nothing while the card compiled
        # supported.
        if event != "you_discard_card":
            raise LoweringError(
                "'that card' names the firing event's object, and this event "
                "records none",
                node=statement,
            )
        if statement.from_zone.name != "graveyard" or (
            statement.from_zone.owner is None
            or statement.from_zone.owner.kind != "you"
        ):
            raise LoweringError(
                "the bound-card exile reaches the discarding player's own "
                "graveyard",
                node=statement,
            )
        return (OracleInstruction("exile_bound_card_from_graveyard", "", {}),)

    if isinstance(statement, ast.NameThenConsult):
        return (
            OracleInstruction(
                "name_then_consult", "",
                {"exile_count": _amount_payload(statement.exile_count)},
            ),
        )

    if isinstance(statement, ast.NameThenRevealTop):
        # "Target player chooses…" is the only subject printed on this
        # paragraph, and it is the whole shape of the effect: the chooser, the
        # revealer and the card's destination are all the *same* seat. A
        # sentence naming anyone else would be a different card, so it refuses
        # rather than lowering onto a seat the handler would then have to guess
        # between.
        if statement.who.kind != "target_player":
            raise LoweringError(
                "the guess is made by the player the spell targets",
                node=statement,
            )
        payload: dict[str, object] = {
            "match_zone": statement.match_zone,
            "miss_zone": statement.miss_zone,
            "targets": _targets_payload(statement.who),
        }
        if statement.miss_damage:
            # Emitted only when the card prints it, so Petra Sphinx's payload
            # stays byte-identical and no behaviour signature moves.
            payload["miss_damage"] = statement.miss_damage
        return (OracleInstruction("name_then_reveal_top", "", payload),)

    if isinstance(statement, ast.RevealUntil):
        return _lower_reveal_until(statement, produced)

    if isinstance(statement, ast.RevealTopSortingByChosenName):
        # "Reveal the top four cards of your library and put all of them with
        # **that name** into your hand." (Wood Sage.) An arm here rather than a
        # row in ``by_node``: it reads ``produced``, because the name is the
        # one an earlier step of the same ability chose — which is this
        # module's own subject, a sentence that reads back a decision another
        # sentence recorded.
        return _lower_reveal_top_sorting_by_chosen_name(statement, produced)

    if isinstance(statement, ast.CopyThatSpell):
        return (OracleInstruction("copy_triggering_spell", "", {}),)

    if isinstance(statement, ast.CopySpell):
        # "Copy **this** spell" — the resolving object, which this engine has
        # already popped off the stack, so the handler reads
        # `Game.resolving_items[-1]` rather than scanning. Who gets the copy is
        # payload (CR 707.10a): the sentence's printed subject, which for Chain
        # Lightning is the player who paid and not the spell's controller.
        return (
            OracleInstruction(
                "copy_this_spell", "",
                {
                    "controller": statement.controller.kind,
                    "may_choose_new_target": bool(statement.may_choose_new_target),
                },
            ),
        )

    if isinstance(statement, ast.EndTheTurn):
        return (OracleInstruction("end_the_turn", "", {}),)

    if isinstance(statement, ast.ChooseNumber):
        # The bounds are all there is to carry: what the number is *for* is a
        # different sentence on the card (Shapeshifter's characteristic-defining
        # P/T), which reads it back off the permanent.
        return (
            OracleInstruction(
                "choose_number", "",
                {"minimum": statement.minimum, "maximum": statement.maximum},
            ),
        )

    if isinstance(statement, ast.ChooseColor):
        # The colour is not printed and the permanent it lands on is the
        # ability's own source — see the node. What can vary is *who* names it.
        return (
            OracleInstruction(
                "choose_color", "", _chooser_payload(statement, event, "colour")
            ),
        )

    if isinstance(statement, ast.ChooseCardType):
        # The colour choice's sibling above, with the same two readings of who
        # names it and the same refusals — the printed option list is the only
        # thing it carries that the colour does not, because that one has a
        # catalog and this one has a sentence.
        return (
            OracleInstruction(
                "choose_card_type", "",
                {
                    "options": list(statement.options),
                    **_chooser_payload(statement, event, "type"),
                },
            ),
        )

    if isinstance(statement, ast.ChoosePlayerWhoCast):
        # "Choose a player who cast one or more sorcery spells this turn."
        # (Backdraft.) The choice and nothing else: what the chosen player is
        # *for* is the sentence after it, which reads the seat this one records
        # (`_PRODUCES`) — the same shape the coin flip below has, and for the
        # same reason.
        return (
            OracleInstruction(
                "choose_player_who_cast", "",
                {
                    "card_type": statement.card_type,
                    "minimum": statement.minimum,
                    "result_key": CHOSEN_PLAYER,
                },
            ),
        )

    if isinstance(statement, ast.FlipCoin):
        # CR 705.1: the flip is the whole sentence, and it takes no payload. What
        # happens next is the conditional sentences after it, which read the
        # result this one records (`_PRODUCES`).
        return (OracleInstruction("flip_coin", "", {}),)

    if isinstance(statement, ast.DrawGame):
        # "The game is a draw." (CR 104.4c.) `game_is_draw` takes an empty
        # payload and the sentence carries nothing else, so there is nothing to
        # check and nothing that could be dropped.
        return (OracleInstruction("game_is_draw", "", {}),)

    return None
