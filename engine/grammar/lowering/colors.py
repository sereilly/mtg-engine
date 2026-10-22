"""Lowering the colour a ``becomes`` sentence gives its subject.

"Target spell or permanent becomes red" (the Lace cycle), "becomes white until
end of turn", "becomes the color of your choice" — CR 105 and CR 613 layer 5.

Split out of ``types.py`` at 1,010 lines, the round "target **spell or
permanent**" stopped being read as "target permanent" (Illusion, Blind Seer),
along the line that module's own first paragraph had drawn and then waived: it
lists animation, a gained card type, a supertype and a basic land type as
CR 205 and layer 4, "and the colour change …, which is CR 105 and layer 5 and
is **here anyway**". Its closing paragraph names the same seam as the CR's own
— "CR 105 what colour it is (layer 5) … and CR 205 is what it **is**" — and
that is the cut. The colour half is the one that grows with the pool where the
subject is concerned: a permanent, the source, an Aura's host, a bound
creature, a spell on the stack, and now a spell *or* a permanent, each with an
indefinite and a turn-long form.

The name is ``engine/color_changes.py``'s, the write API every handler behind
these instructions goes through, so the lowering and the record it feeds are
one word — the reuse ``untap_restrictions`` and ``linked_exile`` make of their
engine modules. Lowering-only: the parse half stays in ``effects/types.py``,
where the colour is one branch of the single ``becomes`` production and reads
the duration clause the other four read. The two halves share no helper;
everything either uses is in ``_common``, ``_events`` and ``_filters``.
"""

from ...oracle_types import (BLOCK_PAIR_SUBJECT, CHOSEN_COLOR_THIS_WAY,
                             SPELL_OR_OBJECT_TARGET, SUBJECT_FROM_TRIGGER,
                             OracleInstruction)
from .. import ast
from ..errors import LoweringError
from ._common import (_describe_several_targets, _describe_targets,
                      _is_enchanted, _is_source, _names_several_targets,
                      _restrictions_beyond)
from ._events import binds_block_pair

#: What a recolour can be told about the **spell** it targets, and the whole of
#: it: that it is a spell (``zone``) and which card types it may be. Both are
#: carried on the description, which is what the stack picker offers from and
#: what the handler re-asks at resolution. Any other word in the phrase — a
#: colour, a controller, a mana value — is a narrowing neither of them tests,
#: so it refuses rather than aiming the ability at spells the card never named.
_RECOLOURED_SPELL_FIELDS = frozenset({"zone", "card_types"})


def _spell_target_description(subject: ast.TargetSpec, node) -> dict[str, object]:
    """The ``targets`` description of "target [<types>] **spell**".

    ``{"quantifier": "target", "kind": "spell"}`` is the spelling every lowering
    that names a spell already emits (the counter, ``exile_target_spell``); this
    adds the printed card types beside it — "target **instant or sorcery**
    spell" (Vodalian Mystic) — under the key ``target_descriptions._from_targets_payload``
    hands the stack enumeration, so the picker offers exactly the spells the
    phrase names. Absent when the phrase names no type, which keeps the bare
    description byte-identical to what it was.
    """
    filt = subject.filter
    beyond = _restrictions_beyond(filt, _RECOLOURED_SPELL_FIELDS)
    if beyond:
        raise LoweringError(
            "no recolour tests this narrowing of a spell: " + ", ".join(beyond),
            node=node,
        )
    described: dict[str, object] = {"quantifier": "target", "kind": "spell"}
    if filt.card_types:
        described["card_types"] = list(filt.card_types)
    return described


def _spell_or_permanent_description(
    subject: ast.TargetSpec, node
) -> dict[str, object]:
    """The ``targets`` description of "target **spell or permanent**".

    One chosen object in one of two zones (CR 115.1: a target is an object, a
    player or a zone, and the phrase names two kinds of object). The kind says
    so in the description's own words — ``spell`` for the stack, ``object`` for
    the battlefield — and ``target_descriptions._from_targets_payload`` turns it into the
    ``spell_or_permanent`` picker the Lace cycle's kind row has always answered
    with, so the union has one spec whichever way a card reaches it.

    The bare union only. A narrowing beside it ("target **red** spell or
    permanent") would have to be asked of both halves, and nothing here tests
    one of a spell; "up to one" and a plural count are announcements the
    one-object handler does not read.
    """
    beyond = _restrictions_beyond(subject.filter, frozenset({"also_spell"}))
    if beyond or subject.quantifier != "target" or _names_several_targets(subject):
        raise LoweringError(
            "a recolour names one spell or permanent and narrows neither"
            + (": " + ", ".join(beyond) if beyond else ""),
            node=node,
        )
    return {"quantifier": "target", "kind": SPELL_OR_OBJECT_TARGET}


def _lower_become_color(
    node: ast.BecomeColor,
    event: str | None = None,
    event_subject: object | None = None,
) -> tuple[OracleInstruction, ...]:
    """The Lace cycle, and the five Legends colour spells beside it.

    Two instructions, told apart by the *duration* rather than by the number of
    targets: an indefinite change writes the permanent colour channel and a
    turn-long one writes the until-end-of-turn channel the cleanup step sweeps,
    and layer 5 reads both (`engine/layer_bridge.py`). One handler covers one
    target or several, since a single chosen slot is a list of one.
    """
    if node.color in (ast.CHOSEN_COLOR, ast.CHOSEN_COLORS):
        several = node.color == ast.CHOSEN_COLORS
        if _is_enchanted(node.subject):
            # "Enchanted creature becomes the color or colors of your choice."
            # (Dream Coat.) The Aura's own host rather than a target: an Aura's
            # activated ability acts on what it is attached to (CR 303.4), which
            # is nothing the activator chooses. Read as a target it refused, and
            # the ability compiled to nothing at all.
            if node.duration.kind is not None:
                raise LoweringError(
                    f"no handler recolours for {node.duration.kind!r}", node=node
                )
            return (
                OracleInstruction(
                    "recolor_enchanted_chosen_color", "", {"several": several}
                ),
            )
        if _is_source(node.subject):
            # "You may have **this creature** become the color or colors of your
            # choice." (Shyft.) The third subject the phrase is printed on, and
            # the one nobody chooses at all: an object the sentence names
            # outright. Its own kind rather than the Aura's, because which
            # permanent is recoloured is the whole difference and reading the
            # source off an ``attached_to`` that is never there would recolour
            # nothing.
            #
            # No duration: "(This effect lasts indefinitely.)" is CR 611.2's
            # default said out loud, so a printed one would be a different card.
            #
            # "{G}: This creature becomes the color of your choice **until end
            # of turn**." (Kavu Chameleon, Rainbow Crow.) That different card:
            # one colour, asked by the step in front (CR 608.2d, the
            # arrangement the targeted branch below states), and written to the
            # turn-long channel by the handler Raging Spirit's "becomes
            # colorless until end of turn" already uses — the same effect with
            # its colour read off the choice instead of off the text.
            if (
                not several
                and node.duration.kind in ("until_end_of_turn", "this_turn")
            ):
                return (
                    OracleInstruction("choose_color", "", {"chooser": "you"}),
                    OracleInstruction(
                        "recolor_self_until_eot", "",
                        {"color_from": CHOSEN_COLOR_THIS_WAY},
                    ),
                )
            if node.duration.kind is not None:
                raise LoweringError(
                    f"no handler recolours for {node.duration.kind!r}", node=node
                )
            return (
                OracleInstruction(
                    "recolor_self_chosen_color", "", {"several": several}
                ),
            )
        # "**Target permanent** becomes the color or colors of your choice."
        # (Prismatic Lace.) The set offer on a chosen object, which is the one
        # of the three subjects that had no path: the Aura's host and the
        # source itself both reached ``arm_color_set_choice`` and a target
        # refused outright. It is the same offer on the same permanent channel
        # — CR 105.2 makes a two-coloured object one object — so ``several``
        # rides the payload here exactly as it does on the two branches above,
        # and the handler asks the same prompt.
        # "Target permanent you control becomes the color of your choice."
        # (Alchor's Tomb.) Its own kind rather than a flag on the lace kind,
        # because the two describe different pickers: a lace targets a spell or
        # a permanent and names its colour in the text, while this one targets
        # whatever its printed noun phrase says and reads the colour back off
        # the choice made as the ability resolves. The noun phrase is
        # described here, so "you control" is enforced by the picker rather
        # than dropped — the lace kind's fixed `spell_or_permanent` spec would
        # have offered every permanent on the board.
        if not isinstance(node.subject, ast.TargetSpec) or not node.subject.targeted:
            raise LoweringError(
                "no handler recolours an object nobody targeted", node=node
            )
        # "{T}: Target permanent becomes the color of your choice **until end of
        # turn**." (Distorting Lens.) The same offer on the same object with a
        # window on it, so it is a key on this instruction rather than a kind of
        # its own: CR 613's layer 5 reads the indefinite channel and the
        # turn-long one side by side (`engine/layer_bridge.py`), and which of
        # the two a resolution writes is not a different effect — it is the one
        # sentence with the duration the card printed.
        #
        # Alchor's Tomb, one printing over, says exactly this with no duration
        # and keeps the write it had. A missing duration must stay the
        # indefinite write and not become a turn-long one, which is why the flag
        # is set from the printed kind rather than defaulted either way.
        if node.subject.filter.zone == "stack":
            # "{T}: Target instant or sorcery **spell** becomes the color of
            # your choice." (Vodalian Mystic.) The same offer made of an object
            # on the stack (CR 613.1 is about objects, not permanents): one
            # colour, named by the step in front as the ability resolves
            # (CR 608.2d), written to the spell's own colour record — the one
            # ``_stack_item_colors`` reads, so every "counter target <colour>
            # spell", every protection and every colour condition sees it.
            #
            # No duration and no set. The change is indefinite (CR 611.2a) — on
            # the spell, and on the permanent a permanent spell becomes
            # (CR 400.7a, ``color_changes.carry_spell_color_change``) — and the
            # colour-set prompt writes a permanent's channel. Neither is
            # printed on a phrase that names a spell alone, so both still
            # refuse here; the windowed form the record can now hold is the
            # union's, one branch down (Illusion, Blind Seer).
            if (
                several
                or node.duration.kind is not None
                or _names_several_targets(node.subject)
                or node.subject.filter.also_ability
            ):
                raise LoweringError(
                    "one spell takes one chosen colour for as long as it is "
                    "that spell", node=node,
                )
            return (
                OracleInstruction("choose_color", "", {"chooser": "you"}),
                OracleInstruction(
                    "recolor_target_chosen_color", "",
                    {"targets": _spell_target_description(node.subject, node)},
                ),
            )
        until_eot = node.duration.kind in ("until_end_of_turn", "this_turn")
        if node.duration.kind is not None and not until_eot:
            raise LoweringError(
                f"no handler recolours for {node.duration.kind!r}", node=node
            )
        if node.subject.filter.also_spell:
            # "Target **spell or permanent** becomes the color of your choice
            # until end of turn." (Illusion, Blind Seer.) The spell branch
            # above and the permanent branch below, offered as one choice: the
            # noun parser used to drop the union, so this fell through to the
            # permanent description and the spell half was unreachable — the
            # picker offered permanents alone, and a spell named anyway was set
            # aside for a permanent the resolver's scan found.
            #
            # A printed window is carried for both halves: it is the turn-long
            # channel on a permanent, and on a spell it is what the effect is
            # when the spell becomes one (CR 400.7a, ``color_changes``). No
            # set: the colour-set prompt writes a permanent's channel.
            if several:
                raise LoweringError(
                    "one spell or permanent takes one chosen colour", node=node
                )
            union: dict[str, object] = {
                "targets": _spell_or_permanent_description(node.subject, node)
            }
            if until_eot:
                union["until_eot"] = True
            return (
                OracleInstruction("choose_color", "", {"chooser": "you"}),
                OracleInstruction("recolor_target_chosen_color", "", union),
            )
        if until_eot and several:
            # The set offer goes on the standing prompt queue
            # (`arm_color_set_choice`), which writes the indefinite channel and
            # has no notion of a window — so a card printing "the color **or
            # colors** of your choice until end of turn" would be recoloured for
            # ever off a sentence that says "this turn". No such card is
            # printed; refusing is what keeps that true if one is.
            raise LoweringError(
                "the colour-set prompt writes no turn-long channel", node=node
            )
        if _names_several_targets(node.subject):
            # "**Any number of target creatures** become the color of your
            # choice until end of turn." (Sway of Illusion.) Several chosen
            # objects and one colour for all of them, so it is the
            # several-target recolour (Sylvan Paradise's "one or more target
            # creatures become green until end of turn") with its colour read
            # off the choosing step in front. It used to fall through to the
            # one-target kind below, whose description names one target and
            # here named none: the card reported supported, the picker offered
            # nothing, and the resolution recoloured whatever it happened on.
            if several or not until_eot:
                raise LoweringError(
                    "several targets take one chosen colour for a turn, and "
                    "nothing else is printed", node=node,
                )
            many: dict[str, object] = {"color_from": CHOSEN_COLOR_THIS_WAY}
            _describe_several_targets(many, node.subject)
            return (
                OracleInstruction("choose_color", "", {"chooser": "you"}),
                OracleInstruction("recolor_targets_until_eot", "", many),
            )
        payload: dict[str, object] = {}
        if several:
            payload["several"] = True
        if until_eot:
            payload["until_eot"] = True
        _describe_targets(payload, node.subject)
        recolor = OracleInstruction("recolor_target_chosen_color", "", payload)
        if several:
            # The set offer asks for itself, on the standing colour-set prompt
            # the handler arms against the target it has just resolved.
            return (recolor,)
        # One colour is asked by the step in front, CR 608.2d's arrangement for
        # every "of your choice" (``keywords._chosen_color_prelude`` states it
        # for the protection grant beside this): the controller of the ability
        # names it while the effect is applied, after every response, and the
        # recolour spends what that step recorded. It used to ride the
        # activation, which CR 602.2b does not announce.
        return (OracleInstruction("choose_color", "", {"chooser": "you"}), recolor)
    if node.duration.kind in ("until_end_of_turn", "this_turn"):
        # "{2}: **This creature** becomes colorless until end of turn." (Raging
        # Spirit.) The ability's own source, which is not a target and never
        # was — the branch below reads a chosen object, and reading the source
        # as one would recolour whatever the picker happened to offer.
        if _is_source(node.subject):
            return (
                OracleInstruction(
                    "recolor_self_until_eot", "", {"target_color": node.color}
                ),
            )
        if not isinstance(node.subject, ast.TargetSpec) or not node.subject.targeted:
            raise LoweringError(
                "no handler recolours an object nobody targeted", node=node
            )
        payload: dict[str, object] = {"target_color": node.color}
        if _names_several_targets(node.subject):
            _describe_several_targets(payload, node.subject)
        else:
            # "{T}: **Target permanent** becomes colorless until end of turn."
            # (Ersatz Gnomes.) The single-target spelling was described to
            # nobody, so `derive_activation_spec` had no evidence, the picker
            # offered nothing and the ability could not be aimed at all — a
            # supported card no player can use, which is what
            # `scripts/picker_sweep.py` exists to find.
            #
            # The several-target spelling beside it has always been described.
            # The handler reads neither: it resolves through
            # `resolve_target_permanents`, which asks the *context* for what was
            # chosen, so this description is the picker's evidence and nothing
            # else's — which is exactly why its absence was silent.
            #
            # Unlike the durationless Lace branch below, this one can be
            # described: "becomes <colour> until end of turn" is printed about
            # permanents, never about the "spell or permanent" union that
            # branch's comment refuses for.
            _describe_targets(payload, node.subject)
        return (OracleInstruction("recolor_targets_until_eot", "", payload),)
    if node.duration.kind is not None:
        raise LoweringError(
            f"no handler recolours for {node.duration.kind!r}", node=node
        )
    if not isinstance(node.subject, ast.TargetSpec) or node.subject.quantifier != "target":
        # "…**that creature** becomes green" (Aisling Leprechaun). Nobody chose
        # it, so there is no target — but a block trigger *bound* it, and under
        # one of those events the pronoun names exactly one creature. The
        # binding travels as payload rather than as a second instruction kind:
        # which object an effect acts on is not a different effect.
        if (
            binds_block_pair(event, event_subject)
            and isinstance(node.subject, ast.TargetSpec)
            and node.subject.quantifier == "that"
        ):
            return (
                OracleInstruction(
                    "recolor_target_from_text", "",
                    {
                        "target_color": node.color,
                        SUBJECT_FROM_TRIGGER: BLOCK_PAIR_SUBJECT,
                    },
                ),
            )
        raise LoweringError("no handler for recolouring a non-targeted object", node=node)
    payload: dict[str, object] = {"target_color": node.color}
    if node.subject.filter.also_ability:
        # "target spell **or ability**" — the union the counter one family over
        # reads (Diplomatic Escort). CR 113.7a: an ability on the stack has no
        # card and no colour to change, so recolouring one is not a thing this
        # sentence could mean; admitting the phrase would drop the union and
        # aim the picker at spells alone. No card prints it. Refused rather than
        # dropped, because the only other reader of this filter field is an
        # explicit one and a *silent* one here is how a rider disappears.
        raise LoweringError(
            "an ability on the stack has no colour to change", node=node
        )
    if node.subject.filter.zone == "stack":
        # "{T}: Target **spell** becomes colorless." (Ersatz Gnomes.) The
        # printed noun names an object on the stack and nothing else, so the
        # picker is the stack one — the same description ``exile_target_spell``
        # and the counter lowering already emit, rather than a third spelling.
        #
        # Described here so the spec stops coming from the instruction *kind*.
        # ``recolor_target_from_text``'s row in ``instruction_targets._KIND_TO_SPEC`` is
        # ``spell_or_permanent``, which is right for the Lace cycle and wrong
        # for this card by exactly one zone: with no description the shared kind
        # answered for both, and Ersatz Gnomes' ability could be aimed at a
        # permanent the card does not name — an illegal announcement under
        # CR 601.2c that the gate could not catch, because the gate reads the
        # same over-wide list the picker offers.
        #
        # Through ``_spell_target_description``, so a typed phrase ("target
        # **instant** spell becomes colorless") carries its type to the picker
        # or refuses — it used to lower to this bare description with the word
        # dropped. No card prints one; Ersatz Gnomes' payload is unchanged.
        payload["targets"] = _spell_target_description(node.subject, node)
    else:
        # Otherwise the Lace cycle's "target **spell or permanent**", and
        # nothing else: the kind's own row in ``instruction_targets._KIND_TO_SPEC`` is the
        # ``spell_or_permanent`` picker, so an undescribed instruction *is*
        # that union. It was reached by every phrase that fell this far —
        # "target creature becomes red" would have lowered here and been
        # aimable at any spell or permanent — because the noun parser dropped
        # the union and there was nothing to ask. It records it now, so this
        # asks: the bare union, checked by the reader the chosen-colour branch
        # describes it with.
        #
        # Left undescribed all the same. The vocabulary can say the union
        # (``SPELL_OR_OBJECT_TARGET``) and Illusion's lowering does; the five
        # Laces answer the identical spec from their kind row, and describing
        # them would move five shipped programs for no change in what they do.
        if not node.subject.filter.also_spell:
            raise LoweringError(
                "an indefinite recolour is aimed at a spell, or at a spell or "
                "permanent; this phrase names neither", node=node,
            )
        _spell_or_permanent_description(node.subject, node)
    return (OracleInstruction("recolor_target_from_text", "", payload),)
