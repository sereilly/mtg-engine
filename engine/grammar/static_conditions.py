"""Lowering the **condition** on a static ability — the "as long as" half.

Split out of ``statics.py`` at the 1,000-line guard, the round Odyssey's
threshold put a quoted ability, a colour and a static sentence behind a
condition. The seam is the one that module's own docstring drew when it named
its other half: a lord buff's correctness is a *round trip* through
``engine/lord_buffs.py``, and nothing here makes one. Everything here answers
the two questions a criteria clause adds (CR 613.1's "as long as"):

* **which conditions may gate a continuous effect at all** — exactly the kinds
  ``static_bonuses.conditional_static_holds`` evaluates, held to that
  evaluator by :func:`_lower_anthem_condition_payload`, for an anthem and for
  one permanent alike; and
* **what one permanent has while its condition holds** — the
  ``conditional_static`` instruction, whose delta, keywords, colour and
  granted lines are each read by the pass that owns their layer.

The name is the mirror's first word and this half's own: ``static_lines`` is
the parse side of both halves, ``statics`` keeps the dispatch and the anthem,
and ``engine/static_bonuses.py`` is the evaluator these payloads are written
for.

Sits between ``lowering/`` and ``statics`` in the layer order; ``statics``
imports it and it imports nothing back.
"""

from __future__ import annotations

import dataclasses

from ..lord_buffs import grantable_keywords
from ..oracle_types import OracleInstruction
from ..search_filters import SEARCH_COMPARISONS
from ..static_bonuses import RECIPIENT_SUBJECT
from ..subject_filters import OBJECT_ONLY_FILTER_KEYS
from . import ast
from .errors import LoweringError
from .lowering import _is_enchanted, _lower_condition, _lower_pump, _signed


def _lower_anthem_condition_payload(payload: dict, node: ast.StaticAbilityNode) -> dict:
    """:func:`_lower_anthem_condition`'s gate, asked of an already-lowered
    payload — which is what a conjunct is.

    Split out so a conjunction is checked by the *same* rules as the clause it
    would have been printed as on its own, rather than by a second, laxer copy
    of them.
    """
    # "During your turn" (Vibrating Sphere) and "it's blocking" (Snow Devil)
    # carry no filter and no seat word, so none of the ``controls`` gates below
    # apply to them — asking those of a payload that has no such parts would
    # refuse a clause the evaluator implements in full.
    if payload.get("kind") in ("your_turn", "is_state"):
        return payload
    # "As long as there is exactly one tide counter on this **enchantment**, all
    # blue creatures get -2/-0." (Tidal Influence.) A count of the *source's*
    # own counters, which carries no filter and no seat word either — and which
    # `conditional_static_holds` answers off the permanent it is handed. Named
    # here beside the two above rather than falling into the `controls` gates,
    # which would refuse it for parts the sentence does not have.
    if payload.get("kind") == "source_counter_count":
        return payload
    # "…as long as **they all share a color**" (Common Cause). Named here beside
    # the three above rather than falling into the `controls` gates below, which
    # would refuse it for parts the sentence does not have: it carries no seat
    # word and no board noun phrase of its own — the set is the anthem's, copied
    # on at the call site.
    if payload.get("kind") == "all_share_a_color":
        return payload
    # "…as long as **white is the most common color among all permanents** or
    # is tied for most common" (the Invasion Djinns). A census of the whole
    # battlefield: no seat word and no noun phrase for the `controls` gates
    # below to hold to anything, and `conditional_static_holds` answers it
    # through `engine/color_census.py`.
    if payload.get("kind") == "color_is_most_common":
        return payload
    # "…as long as **there are seven or more cards in your graveyard**"
    # (threshold) / "…there are **no** cards in your graveyard" (Gorilla
    # Titan). A count of cards in a zone: no seat word and no board noun for
    # the `controls` gates below to hold to anything. The condition lowering
    # has already refused a bound that is not a printed number, a pile that is
    # neither yours nor everybody's, and a narrowing a card in a zone cannot
    # answer; `conditional_static_holds` answers what is left through
    # `evaluate_count`, the recompute's own count reader. Only the two
    # comparisons `_compare_count` is asked with a number for are admitted, so
    # a parity or a comparison invented later refuses here by name.
    if payload.get("kind") == "cards_in_zones":
        if payload.get("op") not in ("ge", "le", "eq") or not isinstance(
            payload.get("value"), int
        ):
            raise LoweringError(
                "conditional_static_holds compares a card count with a printed "
                "number, at least, at most or exactly",
                node=node,
            )
        return payload
    # "…as long as **it's blocking and you control a snow land**" (Snow Devil).
    # CR 613 puts no limit on how many clauses a static's criteria have, so each
    # conjunct is checked by *this same gate* rather than by a second, laxer
    # copy — and the whole conjunction refuses if any part is one the evaluator
    # cannot answer, because a conjunct silently dropped is a static holding on
    # a board the card does not name.
    if payload.get("kind") == "all_of":
        return {
            **payload,
            "conditions": [
                _lower_anthem_condition_payload(part, node)
                for part in payload.get("conditions") or ()
            ],
        }
    if payload.get("kind") != "controls":
        raise LoweringError(
            "conditional_static_holds evaluates no such condition on a "
            "continuous buff",
            node=node,
        )
    who = payload.get("who")
    # "…as long as **its controller** controls another creature" (Favorable
    # Destiny). A fourth seat word, and the one that is a *pronoun*: it names
    # the controller of the permanent the sentence is about rather than a seat
    # fixed relative to the ability's own controller. CR 109.5 is why that is a
    # real distinction and not a synonym for "you" — an Aura's controller and
    # its host's controller part company the moment either is stolen, and this
    # clause follows the host.
    #
    # "…as long as **no opponent** controls a white or blue creature" (Kavu
    # Runner, Skittish Kavu) is the fifth, ``each_opponent``: every opponent's
    # board at once. Admitted only with the printed zero — the condition
    # lowering has already refused that seat with any other count, because a
    # pooled tally and an every-opponent test part company above zero — and
    # checked again here, since this gate is also handed payloads that did not
    # come through it.
    if who == "each_opponent" and (
        payload.get("op"), payload.get("count")
    ) != ("eq", 0):
        raise LoweringError(
            "conditional_static_holds answers 'no opponent controls' and no "
            "other count over every opponent",
            node=node,
        )
    if who not in ("you", "opponent", "target_opponent", "controller", "each_opponent"):
        raise LoweringError(
            f"conditional_static_holds answers 'controls' for you or an "
            f"opponent, not {who!r}",
            node=node,
        )
    if payload.get("shared_name"):
        raise LoweringError(
            "conditional_static_holds counts matches, not same-name relations",
            node=node,
        )
    if "count" in payload and payload.get("op") not in SEARCH_COMPARISONS:
        raise LoweringError(
            f"conditional_static_holds applies no {payload.get('op')!r} "
            "comparison to a buff condition",
            node=node,
        )
    described = payload.get("filter") or {}
    # ``exclude_self`` on top of the object-only set, because *this* caller has
    # a source to compare against: ``_controls_count_holds`` is handed the
    # permanent the static is about and passes it straight to the matcher. The
    # key is out of ``OBJECT_ONLY_FILTER_KEYS`` for the callers that have none
    # (a forced-sacrifice prompt, a cost charger), and refusing it here as well
    # cost Favorable Destiny's "another creature" a condition the evaluator
    # answers in full.
    extra = set(described) - (OBJECT_ONLY_FILTER_KEYS | {"exclude_self"})
    if extra:
        raise LoweringError(
            "subject_matches cannot test a buff condition's "
            + ", ".join(sorted(extra)),
            node=node,
        )
    if who == "target_opponent":
        payload = {**payload, "who": "opponent"}
    return payload


def _lower_anthem_condition(condition: ast.Condition, node: ast.StaticAbilityNode) -> dict:
    """The payload form of an "as long as" clause on a lord buff, or a refusal.

    Lowered by the one condition lowering (so "an opponent controls a nontoken
    red permanent" is the same payload here as on an intervening-if) and then
    held to what ``conditional_static_holds`` actually evaluates for a
    continuous buff. Everything outside that refuses — a threshold or a
    relative key the consumer cannot test would make the buff apply on a
    different board than the card prints, silently.
    """
    return _lower_anthem_condition_payload(_lower_condition(condition), node)


def _recipient_seat_condition(
    condition: ast.Condition, subject: ast.TargetSpec, node: ast.StaticAbilityNode
) -> dict | None:
    """"Basic lands **each player controls** have shroud as long as **that
    player** controls three or fewer lands." (Sheltering Prayers.)

    An anthem whose condition is asked **once per buffed permanent**: "that
    player" points back at the seat-quantifier inside the subject, so it is each
    land's own controller, and two lands on two sides of the table can answer
    differently. That is "**its** controller" with the set's member as the "it"
    — the seat word Favorable Destiny's Aura already carries — so the clause is
    lowered as exactly that, plus ``subject: "recipient"``, which is what tells
    the recompute to ask it of each permanent the buff reaches rather than once
    of the source (``static_bonuses.RECIPIENT_SUBJECT``).

    None for every other sentence, which leaves it to
    :func:`_lower_anthem_condition` and its refusals — including "that player"
    with no seat-quantifier in the subject to bind it, which still has no
    referent at all.
    """
    if not (
        isinstance(condition, ast.Controls)
        and condition.who.kind == "that_player"
        and subject.filter.controller == "any_player"
    ):
        return None
    bound = dataclasses.replace(
        condition, who=dataclasses.replace(condition.who, kind="controller")
    )
    return {
        **_lower_anthem_condition(bound, node),
        "subject": RECIPIENT_SUBJECT,
    }


def _conditional_static_effect(
    effects: tuple[ast.Statement, ...], node: ast.StaticAbilityNode,
    *, grants: dict | None = None,
) -> tuple[int, int, list[str]]:
    """The ``(power, toughness, keywords)`` a conditional static's arm carries.

    Extracted so the "Otherwise, …" arm is read by **this** function rather
    than by a second copy of it: the two arms of Phyrexian Boon are the same
    kind of thing (CR 613.1 criteria that happen to be complementary), and an
    arm admitted by laxer rules than its sibling is an arm that lowers a delta
    the refresh cannot apply.

    *grants* is where an arm's other two layers go when the caller has a
    reader for them — the colour it sets (layer 5, ``colors``) and the
    abilities it hands over as printed lines (layer 6, ``ability_lines``).
    The "Otherwise" arm passes none, so either one printed there refuses with
    the arm's ordinary reason.
    """
    power = toughness = 0
    keywords: list[str] = []
    for effect in effects:
        if grants is not None and isinstance(effect, ast.GainAbilityText):
            grants.setdefault("ability_lines", []).extend(
                _conditional_ability_lines(effect, node)
            )
            continue
        if grants is not None and isinstance(effect, ast.BecomeColor):
            if "colors" in grants or effect.duration.kind is not None:
                raise LoweringError(
                    "a conditional static sets one colour, with no duration",
                    node=node,
                )
            if effect.color not in ("W", "U", "B", "R", "G"):
                raise LoweringError(
                    f"layer 5 has no colour {effect.color!r} to set", node=node
                )
            grants["colors"] = [effect.color]
            continue
        if isinstance(effect, ast.Pump):
            if effect.per_each is not None:
                # "This creature gets +1/+1 **for each black permanent your
                # opponents control** as long as …" (Nantuko Blightcutter). A
                # counted bonus is its own channel (``dynamic_pt_bonus``),
                # which the caller gates on the condition — handed over only
                # where it is the arm's whole effect, since one instruction
                # cannot carry two deltas sized two ways.
                if grants is None or len(effects) != 1:
                    raise LoweringError(
                        "the conditional static channel carries a fixed delta",
                        node=node,
                    )
                grants["counted_pump"] = effect
                continue
            power = _signed(effect.power, effect.power_negative)
            toughness = _signed(effect.toughness, effect.toughness_negative)
            if not isinstance(power, int) or not isinstance(toughness, int):
                raise LoweringError(
                    "a variable conditional bonus has no channel", node=node
                )
        elif isinstance(effect, ast.GainKeyword):
            for keyword in effect.keywords:
                quality = _protection_grant(keyword)
                if grants is not None and quality is not None:
                    # "…this creature gets +1/+1 **and has protection from
                    # black**" (Mystic Familiar). Protection carries a quality
                    # (CR 702.16), which the one-word derived-grant channel
                    # cannot — so it rides the payload key Escaped
                    # Shapeshifter's table row already writes, read by
                    # ``_protection_qualities`` with this static's condition
                    # asked on every read. Only where the caller has that
                    # reader: the "Otherwise" arm passes no *grants* and
                    # refuses below, as it refuses a colour.
                    grants.setdefault("protection_from", []).append(quality)
                    continue
                if keyword not in grantable_keywords():
                    raise LoweringError(
                        f"the derived-grant channel gives no {keyword!r} at "
                        "layer 6",
                        node=node,
                    )
                keywords.append(keyword)
        else:
            raise LoweringError(
                "a conditional static bonus is derived by engine/static_bonuses.py",
                node=node,
            )
    return power, toughness, keywords


def _counted_conditional_bonus(
    pump: ast.Pump, condition: dict, attached: bool, node: ast.StaticAbilityNode
) -> tuple[OracleInstruction, ...]:
    """"Threshold — This creature gets +1/+1 for each black permanent your
    opponents control as long as there are seven or more cards in your
    graveyard." (Nantuko Blightcutter.)

    Two shipped halves on one line: the counted bonus Mutilate's family lowers
    to (``dynamic_pt_bonus``, a CR 613 layer-7c contribution recounted on every
    refresh) and the criteria Seton's Scout's threshold gates its fixed delta
    on. The pump is lowered by the one pump lowering, so the count is the spec
    every "for each" reads, and the condition rides beside it for
    ``_refresh_dynamic_creatures`` to ask on every refresh — false, and the
    bonus is simply not added that pass (CR 611.3a: nothing to undo).

    Held to what that reader does: a durationless bonus on this permanent or
    its host, no "unless" and no "Otherwise" arm (the counted channel has no
    complement).
    """
    if node.unless or node.otherwise is not None or pump.duration.kind is not None:
        raise LoweringError(
            "a counted conditional bonus is one durationless arm", node=node
        )
    lowered = _lower_pump(pump)
    if len(lowered) != 1 or lowered[0].kind != "dynamic_pt_bonus":
        raise LoweringError(
            "a counted conditional bonus lands on its own source or its host",
            node=node,
        )
    (bonus,) = lowered
    gate = _condition_about_the_host(condition) if attached else condition
    return (
        OracleInstruction(
            bonus.kind, bonus.value, {**bonus.payload, "condition": gate}
        ),
    )


def _protection_grant(keyword: str) -> str | None:
    """The quality word of a "protection from <quality>" keyword the protection
    reader models (``keywords.protection_quality``), or None for any other
    keyword — and for a quality nothing reads, which then refuses as an
    ungrantable keyword rather than riding a payload as no shield at all."""
    from ..keywords import protection_quality

    prefix = "protection from "
    if not keyword.startswith(prefix):
        return None
    word = keyword[len(prefix):].strip()
    return word if protection_quality(word) is not None else None


def _conditional_ability_lines(
    effect: ast.GainAbilityText, node: ast.StaticAbilityNode
) -> list[str]:
    """The printed lines *effect* hands its subject while the condition holds.

    "…this creature has "At the beginning of your upkeep, sacrifice a
    creature."" (Wayward Angel) and "…this creature gets +2/+2 **and can't
    block**" (Childhood Horror), which ``static_lines`` reads as the sentence
    it abbreviates. Both are a whole ability the subject *has* (CR 113.3), so
    both ride as the text and ``_recalculate_lord_buffs`` hands them over on
    the derived-ability channel — re-derived on every recompute, so the
    ability is gone with the seventh card (CR 611.3a) and nothing is undone.

    Each line must be one that channel can carry
    (``granted_abilities.derived_line_supported``): it compiles, and whatever
    it compiles to is found by a reader that asks the permanent's effective
    card at the moment the question arises. A line that fails is a card that
    would compile, report supported and do less than it prints.
    """
    from ..granted_abilities import bind_granter, derived_line_supported

    if effect.duration.kind is not None or effect.only_if_absent:
        raise LoweringError(
            "a conditional static's granted ability carries no duration and "
            "no 'if it doesn't have' rider",
            node=node,
        )
    attached = _is_enchanted(effect.subject)
    lines: list[str] = []
    for text in effect.abilities:
        # An Aura's quote is compiled on its *host*, where the Aura's own name
        # means nothing until it is bound to the one object granting it
        # (CR 201.5a) — the binding ``aura_grants.aura_granted_ability_lines``
        # makes for the unconditional quote, asked here with the probe id.
        probe = bind_granter(text, effect.self_name) if attached else text
        if not derived_line_supported(
            probe, None if attached else effect.self_name
        ):
            raise LoweringError(
                "the derived-ability channel cannot carry "
                + repr(" ".join(text.split())),
                node=node,
            )
        lines.append(text)
    return lines


def _lower_self_conditional_static(
    node: ast.StaticAbilityNode, effects: tuple[ast.Statement, ...]
) -> tuple[OracleInstruction, ...]:
    """"This creature <effect> as long as <condition>", with the condition read
    by the grammar's noun parser (Beasts of Bogardan) — and the same sentence
    printed about an Aura's host, "Enchanted creature gets +2/+2 as long as an
    opponent controls a black permanent" (Ice Age's five Scarabs).

    Those two differ in **which permanent the bonus lands on** and in nothing
    else: same effect, same condition, same evaluator, same seat (CR 109.5 — the
    ability is the Aura's, so its controller is who "an opponent" is measured
    against). So the subject rides the payload as ``subject: "attached"`` and
    the P/T refresh reads it, rather than the sentence getting a second
    lowering, a second condition reader and a chance to disagree about what "a
    black permanent" is.

    ``engine/static_bonuses.py`` owns the same instruction kind and the same
    evaluator, and every condition it reads is about **you** or about the
    creature itself: a land you control, a planeswalker you control, your
    graveyard, your draws, this creature being untapped. The split is that
    line — a condition about *another player's* board lowers here, everything
    else falls through to the table.

    Drawing it anywhere wider would move the cards the table already runs onto
    this path, and ``test_as_long_as_lines_stay_unlowered_and_unusable`` says
    what that costs: two mechanisms for one sentence, with nothing to say which
    of them a given printing goes through.

    The effect side is held to what the refresh consumes, and by the same
    argument the anthem lowering uses one function up — a delta or a keyword
    lowered into a payload no pass reads is a static that never applies while
    the card reports supported.
    """
    grants: dict[str, object] = {}
    power, toughness, keywords = _conditional_static_effect(
        effects, node, grants=grants
    )
    counted_pump = grants.pop("counted_pump", None)
    attached = _is_enchanted(
        getattr(effects[0], "subject", None) if effects else None
    )
    if grants and len({getattr(effect, "subject", None) for effect in effects}) != 1:
        raise LoweringError(
            "a conditional static's parts are all about one permanent", node=node
        )
    # "…**as long as it's black**" (Phyrexian Boon). The pronoun is the
    # sentence's own subject — the enchanted creature — which is a referent the
    # general condition lowering has no way to see: it resolves "it" to a
    # *chosen target*, and an "as long as" clause chooses nothing (CR 613.1), so
    # it refuses there with "'it' has no target to be a colour of here". Asked
    # here, where the subject is in hand, and answered as the
    # ``attached_matches`` payload ``conditional_static_holds`` already
    # evaluates — so the colour is read by ``subject_matches`` through the
    # layers, and an Aura on a creature something has recoloured switches arms
    # by itself.
    colour = _attached_colour_condition(node.condition) if attached else None
    # "…unless **it shares a color with the most common color** …" (Heroic
    # Defiance). The second pronoun-about-the-subject clause, unreadable by the
    # general lowering for the first one's reason: a static chooses no target.
    if colour is None and isinstance(node.condition, ast.SharesMostCommonColor):
        colour = {"kind": "shares_most_common_color"}
    condition = colour if colour is not None else _lower_anthem_condition(
        node.condition, node
    )
    # **Where the split with ``engine/static_bonuses.py`` runs.** That table
    # reads the sentence printed about "this creature" and every condition it
    # knows is about *your* board or the creature itself, so a same-subject
    # clause lowered here would be one sentence with two mechanisms and nothing
    # to say which a printing goes through — which is what
    # ``test_as_long_as_lines_stay_unlowered_and_unusable`` measures.
    #
    # An Aura's sentence is not in that table's territory at all: it matches on
    # the literal subject ``"this creature "``, so "enchanted creature has first
    # strike as long as …" (Snow Devil) is a line it cannot read and there is no
    # second mechanism to collide with. So the refusal is asked of the
    # same-subject case only.
    # "As long as there is exactly one tide counter on this creature, it gets
    # -1/-1." (Homarid.) Not in that table's territory either, and for a
    # sharper reason than the Aura's: the table has no row for a counter count
    # at all, so refusing here would leave the sentence read by nobody — the
    # "refusal can expire" failure arriving before the refusal was even
    # written. It is the *same* sentence Tidal Influence prints about a set of
    # creatures instead of about itself, and both lower to one condition
    # payload answered by one evaluator.
    #
    # The colour census (the Invasion Djinns) is a third: about the whole
    # battlefield rather than about your board or the creature, a condition
    # that table has no row for and could not write one for without a second
    # reader of the clause the two census *spells* go through the grammar for.
    # …and the census asked *of the subject* (Heroic Defiance), last below.
    #
    # A count of cards in a zone (threshold) is the fifth: "there are seven or
    # more cards in your graveyard" is about your *graveyard*, not your board,
    # and the table's only graveyard row reads a different printed sentence
    # ("<a seat> has N or more cards in their graveyard"), so no printing has
    # two readers.
    counted = condition.get("kind") in (
        "source_counter_count", "color_is_most_common", "shares_most_common_color",
        "cards_in_zones",
    )
    if not attached and not counted and condition.get("who") not in (
        "opponent", "each_opponent",
    ):
        raise LoweringError(
            # (The table has no "unless" row, so that spelling does not name it.)
            "no reader applies a self bonus while a condition about your own "
            "board is false"
            if node.unless else
            "a conditional static bonus about your own board is derived by "
            "engine/static_bonuses.py",
            node=node,
        )
    if counted_pump is not None:
        return _counted_conditional_bonus(counted_pump, condition, attached, node)
    payload: dict[str, object] = {"condition": condition}
    if node.unless:
        # "…gets +3/+3 **unless** <condition>" (Heroic Defiance). The delta
        # goes on the *complement* arm — the one "Otherwise, it gets -1/-2"
        # (Phyrexian Boon) already fills — so the criteria are asked once and
        # the answer selects the arm; the refresh reads a 0/0 arm beside a
        # complement that is not as a live effect. A keyword behind the word or
        # a printed "Otherwise" beside it refuses: the keyword pass reads no
        # complement arm, and nobody prints two claims on the false side.
        if keywords or grants or node.otherwise is not None or not (
            power or toughness
        ):
            raise LoweringError(
                "an 'unless' static carries one P/T delta on its complement "
                "arm and nothing else",
                node=node,
            )
        payload["otherwise_power"] = power
        payload["otherwise_toughness"] = toughness
    elif power or toughness:
        payload["power"] = power
        payload["toughness"] = toughness
    if keywords:
        payload["keywords"] = keywords
    # The colour and the granted lines, each under its own key and each read
    # by the pass that owns its layer: ``colors`` by the layer-5 half of
    # ``_refresh_global_statics`` (stamped with this permanent's timestamp,
    # CR 613.7a), ``ability_lines`` by ``_recalculate_lord_buffs`` beside the
    # keywords. Absent when the sentence prints neither, so every payload that
    # existed before these keys is byte-identical.
    payload.update(grants)
    if attached:
        # The bonus goes to the permanent this one is attached to, and so does
        # every "it" in the condition: "enchanted creature has first strike as
        # long as **it's** blocking" is about the creature, not about the Aura,
        # which never blocks. Both halves are read by the state mixins — the
        # P/T by ``dynamic_creatures._refresh_dynamic_creatures`` and the
        # keywords by ``lords._recalculate_lord_buffs``'s conditional-self-grant
        # step — and both read this one key.
        payload["subject"] = "attached"
        payload["condition"] = _condition_about_the_host(condition)
    if node.otherwise is not None:
        _add_otherwise_arm(payload, node, attached)
    return (OracleInstruction("conditional_static", "", payload),)


def _add_otherwise_arm(
    payload: dict, node: ast.StaticAbilityNode, attached: bool
) -> None:
    """Fold "Otherwise, it gets -1/-2." into *payload* (Phyrexian Boon).

    **One instruction, not two.** The obvious shape is a second
    ``conditional_static`` carrying the negated condition, and it is wrong twice
    over. The compiler wraps a line that lowers to several instructions in a
    ``sequence`` (``_line_instruction``), and every pass that applies a
    conditional static scans ``prog.instructions`` for that *kind* — so the
    wrapper hides both arms and the card does nothing at all while reporting
    supported. And two payloads is two conditions, asked separately, free to
    both answer True on a board where the negation and the assertion disagree.

    Asked once and answered once: the refresh evaluates the criteria and applies
    whichever arm the answer selects, so the two arms partition the board by
    construction rather than by a negation somebody has to keep exact.

    A keyword arm refuses. The delta arm is read by ``_refresh_dynamic_creatures``
    and the keyword arm would have to be read by ``_recalculate_lord_buffs``
    as well; no card in the pool prints one, and a keyword lowered into a
    payload that pass does not read is a grant that never happens — the
    unread-rider failure this whole family is arranged against.
    """
    other_effect = node.otherwise
    other_effects = (
        other_effect.effects
        if isinstance(other_effect, ast.Conjunction) else (other_effect,)
    )
    if _is_enchanted(getattr(other_effects[0], "subject", None)) != attached:
        raise LoweringError(
            "an 'otherwise' arm applies to the same permanent as the arm it "
            "complements",
            node=node,
        )
    other_power, other_toughness, other_keywords = _conditional_static_effect(
        other_effects, node
    )
    if other_keywords:
        raise LoweringError(
            "_recalculate_lord_buffs reads no 'otherwise' keyword arm",
            node=node,
        )
    if not (other_power or other_toughness):
        raise LoweringError(
            "an 'otherwise' arm with no delta is a sentence nothing applies",
            node=node,
        )
    payload["otherwise_power"] = other_power
    payload["otherwise_toughness"] = other_toughness


def _attached_colour_condition(condition) -> dict | None:
    """``as long as it's <colour>`` about an Aura's host, as a payload.

    None for anything else, so the ordinary condition lowering runs unchanged —
    this is a branch the general reader genuinely cannot take, not a shortcut
    around it.

    The colour becomes a **filter**, asked through ``subject_matches`` like
    every other printed noun-phrase narrowing in the engine, rather than a
    bespoke "is it black" test that would be a second reader free to disagree
    with the layers about what black is.
    """
    from ..subject_filters import untestable_filter_keys

    if not isinstance(condition, ast.ItIsColor):
        return None
    if condition.negated:
        # "as long as it's **not** black" has no printing in the pool and
        # ``attached_matches`` has no negation, so the word would be consumed
        # and dropped — a criteria clause reading as its own opposite. None
        # here sends the line to the general lowering, which refuses it by name.
        return None
    described = {"color_filter": condition.color}
    if untestable_filter_keys(described):
        return None
    return {"kind": "attached_matches", "filter": described}




def _condition_about_the_host(condition: dict) -> dict:
    """*condition* with every "it" pointed at the attached permanent.

    Only ``is_state`` carries such a pronoun; a ``controls`` clause names a
    *seat*, and CR 109.5 makes that the ability's controller — the Aura's —
    whichever permanent the effect lands on. So this rewrites one kind and
    walks the conjunction, rather than stamping a subject over the whole tree
    and quietly moving "you control a snow land" onto the host's controller.
    """
    if condition.get("kind") == "all_of":
        return {
            **condition,
            "conditions": [
                _condition_about_the_host(part)
                for part in condition.get("conditions") or ()
            ],
        }
    if condition.get("kind") in ("is_state", "shares_most_common_color"):
        # (Heroic Defiance's "it shares a color …" is the same pronoun: the
        # colours compared are the enchanted creature's, never the Aura's.)
        return {**condition, "subject": "attached"}
    # Two parts of a ``controls`` clause are pronouns like ``is_state``'s, and
    # only these two: "**its** controller" (``who: "controller"``) and
    # "**another** creature" (``exclude_self``, CR 109.5's "other than this
    # object"). Both are about the permanent the sentence is about — the
    # enchanted creature — so the clause is stamped for them and for nothing
    # else. Stamping every ``controls`` clause would quietly move "you control a
    # snow land" onto the host's controller, which is the seat CR 109.5 says it
    # is *not*.
    if condition.get("kind") == "controls" and (
        condition.get("who") == "controller"
        or (condition.get("filter") or {}).get("exclude_self")
    ):
        return {**condition, "subject": "attached"}
    return condition
