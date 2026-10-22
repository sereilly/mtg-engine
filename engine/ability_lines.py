"""One printed line read as an ability: triggered, activated or modal.

The compiler's line loops hand a line here once it is not a keyword line:
:func:`_parse_triggered_ability` takes the condition from
``engine/trigger_conditions.py`` and the effect from the front ends
(``engine/front_ends.py``); :func:`_parse_activated_ability` takes the cost
from ``engine/activation_costs.py``. A modal head is read with the bulleted
run below it (CR 700.2) — a spell's modes (:func:`_modal_options`) or a
triggered ability's (:func:`_modal_trigger_ability`); an activated ability's
has already been rewritten into one line per bullet
(``line_rewrites.expand_modal_activated_lines``, which asks
:func:`_modal_head` and :func:`_bullets_after` here).

And the clause an ability or a spell **creates** rather than is: a delayed
triggered ability (CR 603.7), "whenever ... this turn, ...", read by
:func:`_parse_delayed_attack_trigger` so its inner effect waits for the event
instead of running on resolution. The loyalty path, the activated path and a
spell's own line all ask it, and :func:`_split_trailing_delayed_trigger` keeps
a spell line that ends in one a single resolution.

Split out of ``engine/oracle.py`` at the 2,000-line cap.
"""

from __future__ import annotations

import re

from .oracle_types import (ModalOption, OracleInstruction,
                           ParsedActivatedAbility, ParsedTriggeredAbility,
                           X_FROM_COUNT)
from .effect_labels import triggered_label
from .modal_triggers import (MODAL_HEAD_KEY, MODAL_INSTRUCTION_KIND,
                             modal_trigger_mode_is_derivable,
                             modal_trigger_targeting_refusal)
from .grammar import ast as grammar_ast, compile_line as compile_grammar_line
from .grammar.lowering._events import OPPONENT_CHOSE_MODE
from .grammar.postmodifiers import COST_TAPPED_REFERENT
from .line_normalization import _WHITESPACE_RE, normalize_creature_line
from .trigger_conditions import (_extract_if_condition,
                                 trigger_condition_of_line)
from .activation_costs import (activation_colon_index,
                               parse_activated_ability_cost)
from .front_ends import _line_instruction, _reading


def _reads_as_registry_line(line: str, card_name: str | None) -> bool:
    """Whether the grammar reads *line* as a line a text-keyed registry runs.

    Asked of the grammar rather than of a list of the registries' phrases, for
    the reason every gate in this engine is asked that way: a second copy of
    which sentences ``engine/grammar/registries.py`` claims would go stale the
    first time one is added.
    """
    compiled = compile_grammar_line(line, card_name=card_name)
    return (
        compiled.parse_error is None
        and isinstance(compiled.node, grammar_ast.RegistryLine)
    )


def _parse_triggered_ability(line: str, card_name: str | None = None) -> ParsedTriggeredAbility | None:
    """Parse a single oracle text line as a triggered ability.

    Returns None if the line doesn't start with a trigger word at all,
    so the caller can try other parsers. Returns a ParsedTriggeredAbility
    with supported=False if the trigger prefix is recognized but the
    condition or effect is not.
    """
    condition, remainder = trigger_condition_of_line(line, card_name)
    if condition is None:
        return None  # not a triggered ability line
    if _reads_as_registry_line(line, card_name):
        # A line a **text-keyed registry already runs** is not an unimplemented
        # trigger, however clearly its first clause reads as a condition
        # (`engine/grammar/registries.py`; CLAUDE.md's "zero instructions is
        # the correct lowering, not a gap").
        #
        # Fastbond is the card: "Whenever you play a land, if it wasn't the
        # first land you played this turn, this enchantment deals 1 damage to
        # you" is carried out by `engine/land_play_allowance.py`'s
        # `damage_per_extra_land` off the land-drop path. Before a `land_played`
        # row existed nothing here matched the sentence and the registry had it
        # to itself; the moment one did, the card grew a triggered ability with
        # no instruction — reported by `--hollow-lines` and, worse, offered to
        # `engine/events.collect`, which does not ask whether a trigger has one.
        #
        # This is the **grammar before the derivation tables** ordering read one
        # front end over: a production that claims a line takes it from the
        # table, and a table that claims a line takes it from this one.
        return None

    # Strip leading colon/comma that sometimes follows the condition clause
    remainder = remainder.lstrip(": ")

    # Extract any trailing "if ..." guard on the effect. The clause it strips is
    # no longer read on its own: the front ends take the whole line, so the
    # guard's only job now is the payload key attached below.
    if_kind, _clean_effect = _extract_if_condition(remainder)

    instruction, effect_kind = _reading(
        _line_instruction(line, card_name, condition_kind=condition.kind)
    )

    if instruction is not None and if_kind is not None:
        # Attach the if-condition into the instruction payload
        instruction = OracleInstruction(
            instruction.kind,
            instruction.value,
            {**instruction.payload, "if_condition": if_kind},
        )

    supported = instruction is not None
    return ParsedTriggeredAbility(
        source_line=line,
        condition=condition,
        instruction=instruction,
        supported=supported,
        effect_kind=effect_kind if supported else "unsupported",
    )


def _modal_head(line: str, wrapper: type) -> "grammar_ast.ModalNode | None":
    """The modal head *line* is, read through the grammar — or None.

    *wrapper* is the ability-line node the head has to sit inside, and it is
    what tells a spell's mode list apart from an activated ability's:
    ``SpellEffectLine`` for the bare "Choose one —" a spell announces on the
    stack (CR 601.2b), ``ActivatedAbilityNode`` for the "{2}: Choose one —"
    :func:`expand_modal_activated_lines` rewrites. A head behind a *trigger*
    matches neither and is claimed by nothing here, which is right: its modes
    are chosen when the ability goes on the stack (CR 700.2b), not when the card
    is cast.

    **One reader.** Two substring matchers used to answer this — ``choose
    one\\b`` anywhere in the card's text for a spell, a mana-symbols-then-``choose
    one`` regex per line for an ability — and between them they got the count
    wrong (``choose one`` matches inside "Choose one **or more**", so Sublime
    Epiphany read as a one-mode spell), missed every count but one, and asked
    the question of the whole card rather than of a line. The grammar parses the
    count and the lowering refuses what the engine cannot carry out, so a head
    it declines is one this must not act on either — which is exactly what
    checking ``lowering_error`` says.
    """
    compiled = compile_grammar_line(line)
    if compiled.lowering_error is not None:
        return None
    node = compiled.node
    if not isinstance(node, wrapper):
        return None
    statement = getattr(node, "statement", None)
    return statement if isinstance(statement, grammar_ast.ModalNode) else None


def _mode_reading(
    label: str, card_name: str | None, *, event: str | None = None,
) -> tuple[OracleInstruction, str] | None:
    """A modal bullet's ``(instruction, effect_kind)``, or None.

    ``effect_kind`` is "spell_pattern" for every bullet the front ends claim,
    not the grammar's category label. A mode is one alternative of a spell, and
    the label is what ``SimulationResult`` and the support report bucket the
    *card* by — so it names the reading's shape, exactly as it did when the
    legacy registry produced it.

    *event* is the head's own contribution to what the bullet means: under
    "**An opponent** chooses one —" (CR 700.2e) the mode's "that player" names
    the chooser, a seat the sentence cannot see from inside the bullet. See
    ``lowering/_events.OPPONENT_CHOSE_MODE``.
    """
    found = _line_instruction(label, card_name, event=event)
    if found is None:
        return None
    return found[0], "spell_pattern"


def _bullets_after(lines: list[str], index: int) -> list[str]:
    """The run of bulleted lines immediately below *index* — a head's modes.

    Stops at the first line that is not a bullet, which is what makes this
    *grouping* rather than a scan: the old version partitioned the card's whole
    text at the first "•" and split the remainder, so a bullet list anywhere on
    the card belonged to any "choose one" anywhere else on it.

    Fewer than two is not a mode list. CR 700.2 defines a modal spell as having
    "two or more options in a bulleted list", so a lone bullet under a head is
    text this does not understand, and returning it as a one-mode spell would be
    a guess wearing the shape of a reading.
    """
    bullets: list[str] = []
    for raw in lines[index + 1:]:
        line = raw.strip()
        if not line.startswith("•"):
            break
        bullets.append(_WHITESPACE_RE.sub(" ", line.lstrip("•").strip()).strip())
    return bullets if len(bullets) >= 2 else []


def _modal_options(oracle_text: str, card_name: str | None) -> tuple[ModalOption, ...]:
    """The bullets of a "Choose one —" spell, one :class:`ModalOption` each.

    Grouping a head with the bullets below it is line classification, which is
    this module's job; *reading* each of those lines is the grammar's, on both
    halves — the head through :func:`_modal_head`, each bullet's effect through
    the same front ends an ordinary line goes to (:func:`_line_instruction`). A
    mode is supported exactly when its own clause is, which is why a card with
    one readable mode and one unreadable one still resolves the readable one.

    Modal **activated** abilities never reach here: ``expand_modal_activated_lines``
    has already rewritten them into one ordinary ability line per bullet, so a
    bullet arriving here is always one alternative of a spell. A modal
    **triggered** ability does reach here and is not claimed, because its head
    parses as a ``TriggeredAbilityNode`` rather than a spell's effect line —
    where the old whole-text substring test would have turned its modes into
    cast-time ones.
    """
    if "choose" not in oracle_text.lower() or "•" not in oracle_text:
        # A pre-filter, not a second reading: both are necessary for the grammar
        # to return a head at all, so this can only skip work, never an answer.
        return ()

    lines = oracle_text.splitlines()
    # "**An opponent** chooses one —": the head is what makes the bullets'
    # "that player" mean the chooser, so the mode's lowering is told which
    # position it occupies. Computed once for the card rather than per bullet.
    mode_event = (
        OPPONENT_CHOSE_MODE if _modal_chooser(oracle_text) is not None else None
    )
    for index, raw in enumerate(lines):
        if _modal_head(raw.strip(), grammar_ast.SpellEffectLine) is None:
            continue
        bullets = _bullets_after(lines, index)
        if not bullets:
            continue
        options: list[ModalOption] = []
        for label in bullets:
            instruction, effect_kind = _reading(
                _mode_reading(label, card_name, event=mode_event)
            )
            # The original casing is kept for the UI's mode picker.
            options.append(
                ModalOption(label.rstrip("."), instruction, effect_kind, instruction is not None)
            )
        return tuple(options)
    return ()


def modal_head_line(line: str) -> bool:
    """Whether *line* is a modal head — the sentence a bulleted mode list hangs
    under (CR 700.2).

    Public because ``scripts/parse_coverage.py`` asks, and it has to ask the
    same reader this module dispatches on. It used to test the substring
    ``startswith("choose one")``, which is a second reading of the line and went
    stale the moment a head printed its chooser: "**An opponent** chooses one —"
    (CR 700.2e) compiled, carried its modes and reported its own head as text
    nothing parses.

    Both wrappers, because a head is printed bare on a spell and after a trigger
    condition, and the claim is about the *sentence* either way.
    """
    return (
        _modal_head(line, grammar_ast.SpellEffectLine) is not None
        or _modal_head(line, grammar_ast.TriggeredAbilityNode) is not None
    )


def _modal_chooser(oracle_text: str) -> str | None:
    """Who picks the mode, when the head names somebody other than the spell's
    controller — "**An opponent** chooses one —" (CR 700.2e).

    Read through the same :func:`_modal_head` the mode list and the bound are,
    for that pair's reason: three answers taken from three readings of one line
    are three answers free to disagree about which head they came from.

    None for every other modal card, which is CR 700.2a's ordinary case and the
    one the cast path already carries.
    """
    if "choose" not in oracle_text.lower() or "•" not in oracle_text:
        return None
    lines = oracle_text.splitlines()
    for index, raw in enumerate(lines):
        head = _modal_head(raw.strip(), grammar_ast.SpellEffectLine)
        if head is None or not _bullets_after(lines, index):
            continue
        return head.chooser.kind if head.chooser is not None else None
    return None


def _modal_at_least(oracle_text: str) -> bool:
    """Whether the head above the bullets is "Choose one **or more** —".

    Read through the same :func:`_modal_head` the mode list is, so the bound and
    the modes cannot disagree about which head they came from — the failure the
    substring matcher had, where "choose one" matched inside "choose one or
    more" and the card read as a one-mode spell.
    """
    if "choose" not in oracle_text.lower() or "•" not in oracle_text:
        return False
    lines = oracle_text.splitlines()
    for index, raw in enumerate(lines):
        head = _modal_head(raw.strip(), grammar_ast.SpellEffectLine)
        if head is None or not _bullets_after(lines, index):
            continue
        return bool(head.at_least)
    return False


def _modal_trigger_ability(
    lines: list[str], index: int, card_name: str | None,
) -> tuple[ParsedTriggeredAbility, int] | str | None:
    """The modal triggered ability whose head sits at *index*, with how many
    bullet lines it consumed — or a refusal reason, or None.

    "When this creature enters, choose one —" plus the bullets below it
    (Trufflesnout; Elder Gargaroth's attacks-or-blocks). The head's condition
    and each bullet are read by the same front ends any other line goes to;
    the grouping alone is this module's job, exactly as it is for a modal
    spell. The assembled instruction is one ``choose_one`` carrying every
    mode, because a triggered ability triggers *once* and the controller picks
    a mode when it goes on the stack (CR 700.2b) — expanding to one trigger
    per bullet, the way modal activated abilities are rewritten, would fire
    them all.

    Returns None when the line is not a modal trigger head at all (an
    ordinary line, or a head whose count the engine cannot carry — "choose
    one or more" fails `_modal_head`'s lowering check and stays refused). A
    *recognized* head with an unreadable condition or a dead mode returns the
    refusal reason instead: the all-of gate round 20 established for modal
    spells, because a mode list with a dead entry is a card that offers a
    choice and then declines to perform it.
    """
    head = lines[index].strip()
    if _modal_head(head, grammar_ast.TriggeredAbilityNode) is None:
        return None
    bullets = _bullets_after(lines, index)
    if not bullets:
        return None
    trig = _parse_triggered_ability(head, card_name)
    if trig is None:
        return f"unsupported modal trigger condition: {head!r}"
    modes: list[dict] = []
    for label in bullets:
        found = _line_instruction(label, card_name)
        if found is None:
            return f"unsupported mode of a triggered ability: {label!r}"
        instruction = found[0]
        mode = {"label": label.rstrip("."), "instruction": instruction}
        if not modal_trigger_mode_is_derivable(mode):
            # The mode targets, and nothing can say what it targets — so the
            # picker would offer it with no candidates and CR 700.2b would then
            # make it permanently unchoosable. A card that prints two modes and
            # can only ever take one of them is worse than an unsupported one,
            # which is at least visible in the backlog.
            return f"a mode of a triggered ability targets undescribably: {label!r}"
        modes.append(mode)
    inline_refusal = modal_trigger_targeting_refusal(trig.condition.kind, tuple(modes))
    if inline_refusal is not None:
        return inline_refusal
    # Marked modal (CR 700.2): the bulleted head is the only form that chooses
    # as the ability goes on the stack. An "A or B" the grammar lowers onto the
    # same kind carries no mark and chooses at resolution (CR 608.2d) — see
    # ``modal_triggers.MODAL_HEAD_KEY``.
    choose = OracleInstruction(
        MODAL_INSTRUCTION_KIND, "", {"modes": tuple(modes), MODAL_HEAD_KEY: True}
    )
    return (
        ParsedTriggeredAbility(
            source_line=" ".join([head] + [f"• {b}" for b in bullets]),
            condition=trig.condition,
            instruction=choose,
            supported=True,
            effect_kind=triggered_label("choose_one", trig.condition.kind),
        ),
        len(bullets),
    )


def _parse_activated_ability(line: str, card_name: str | None = None) -> ParsedActivatedAbility | None:
    normalized = normalize_creature_line(line)
    # Not "is there a colon", but "is there an *activation* colon": one inside
    # quotation marks belongs to an ability the line grants, not to one the
    # permanent has. See :func:`activation_colon_index`.
    colon = activation_colon_index(normalized)
    if colon is None:
        return None

    effect_text = normalized[colon + 1:].strip()
    # "…: Until end of turn, whenever <subject> <event>, <effect>." (Subira.)
    # A delayed triggered ability created on resolution (CR 603.7), read here
    # for the same reason the loyalty path reads it: handed to the grammar, the
    # clause classifies as a triggered ability *of the permanent* and its inner
    # effect runs at once — a draw now instead of a draw when a creature
    # connects.
    delayed = _parse_delayed_attack_trigger(line.split(":", 1)[1].strip(), card_name)
    if delayed is not None:
        return ParsedActivatedAbility(
            source_line=line,
            normalized_effect=effect_text,
            supported=True,
            cost=parse_activated_ability_cost(line, card_name),
            effect_kind="activated_delayed_trigger",
            instruction=delayed,
        )
    instruction, effect_kind = _reading(
        _line_instruction(line, card_name, activated=True)
    )
    cost = parse_activated_ability_cost(line, card_name)
    # "Tap enchanted creature: Target creature **other than the creature tapped
    # this way** …" (Veteran's Voice). The grammar resolved that pronoun to the
    # attached host, because a target filter is tested before the cost is paid
    # (CR 601.2h) and the cost-tap record is still empty then. That resolution is
    # true exactly while the cost is the one that taps the host — a claim about
    # the *cost*, which no target filter can see and which is checked here,
    # where both halves of the line are in hand.
    #
    # An ability printing the phrase with any other cost is refused rather than
    # read as excluding the host: the referent would be a permanent this
    # ability's cost never touched, and the card would target a set it does not
    # print.
    #
    # Only the *exclusion* reads the phrase that way. "…+X/+0, where X is **the
    # power of the creature tapped this way**" (Keldon Battlewagon) names the
    # same object through the cost-tap record at resolution, after CR 601.2h
    # has filled it, so any tap cost answers it and this gate is not its gate.
    if f"other than {COST_TAPPED_REFERENT}" in effect_text and not cost.tap_attached:
        instruction, effect_kind = None, "unsupported"
    instruction = _with_stated_zone(instruction, line, card_name)
    supported = instruction is not None
    return ParsedActivatedAbility(
        source_line=line,
        normalized_effect=effect_text,
        supported=supported,
        cost=cost,
        effect_kind=effect_kind,
        instruction=instruction,
    )


def _with_stated_zone(
    instruction: OracleInstruction | None,
    line: str,
    card_name: str | None,
) -> OracleInstruction | None:
    """*instruction* carrying the zone its own "Activate only ..." clause states
    (CR 113.6b), if one does.

    "Activate only if this card is in your graveyard" (Carrionette) is a
    restriction *and* a statement of where the ability functions, and it is the
    only place that card says so: the effect behind it — "Exile this card and
    target creature ..." — names no zone at all, so the two derivations that
    already produce ``functions_from`` cannot see it. ``lowering/_bound_returns``
    reads a printed "from your graveyard" in the effect and ``lower.py`` reads
    an intervening-if; this reads the CR 602.5 clause, and all three write the
    same key, because ``activate_from_graveyard`` and ``engine/events.py`` ask
    one question of it.

    Here rather than in the grammar for the reason the grammar hands the clause
    back untouched: the restriction is consumed by a production that lowers to
    nothing and is *enforced* off the raw line, so this is the one place both
    the compiled instruction and the printed sentence are in hand.

    An instruction that already carries the key is left alone — a card whose
    effect names its zone has said so once and does not need it said twice, and
    overwriting would let a restriction contradict the effect it is a tail of.
    """
    # Both imported inside the function: ``engine/events.py`` imports
    # ``trigger_utils``, which imports this module, so naming the key at
    # module scope is a cycle. The *spelling* is still the one this engine
    # has — the constant is imported rather than repeated, which is the
    # whole of what one spelling means here.
    from .activation_restrictions import restriction_functions_from
    from .events import FUNCTIONS_FROM

    if instruction is None or instruction.payload.get(FUNCTIONS_FROM):
        return instruction
    zone = restriction_functions_from(line, card_name)
    if not zone:
        return instruction
    return OracleInstruction(
        instruction.kind, instruction.value,
        {**instruction.payload, FUNCTIONS_FROM: zone},
    )


# A loyalty ability whose whole effect is a delayed triggered ability created
# on resolution (CR 603.7): "Whenever [one or more] [nontoken] creature(s)
# attack(s) this turn, <effect>." (Basri Ket's −2, Basri, Devoted Paladin's −1.)
# "…**this combat**" (Melee) is the same shape over a shorter window, and
# "attacks and isn't blocked" the same shape over a later moment of the same
# step. Both are payload: the event comes from `_DELAYED_EVENT_PHRASES` and the
# duration from `_DELAYED_DURATIONS`, so neither is a second regex. The event
# alternation is ordered — "attacks and isn't blocked" before the bare
# "attacks" it begins with — for the reason the narrowed pattern below states.
_DELAYED_ATTACK_RE = re.compile(
    r"^whenever (?:(?P<batch>one or more )|an? )?(?P<nontoken>nontoken )?creatures? "
    r"(?P<event>attacks and isn't blocked|attacks?|blocks?) "
    r"(?P<duration>this turn|this combat), (?P<effect>.+)$"
)

#: Which delayed-trigger lifetime each printed window names (CR 603.7b's
#: "stated duration"). Data rather than a branch, so a card printing the other
#: window is a row: `engine/delayed_triggers.py` holds both sweeps.
_DELAYED_DURATIONS: dict[str, str] = {
    "this turn": "end_of_turn",
    "this combat": "end_of_combat",
}

# The same delayed trigger with its duration printed *first* and its subject
# narrowed: "Until end of turn, whenever a creature you control with power 2 or
# less attacks, draw a card." (Subira, Tulzidi Caravanner.) The subject is a
# printed noun phrase, delimited here and read by the noun parser — the
# ``_subject`` convention this file already uses — so a card narrowing by a
# different tribe, keyword or stat needs no code.
_DELAYED_ATTACK_UNTIL_RE = re.compile(
    r"^until end of turn, whenever (?P<attacker_subject>.+?) "
    r"(?P<event>attacks and isn't blocked|attacks"
    r"|deals combat damage to a player), (?P<effect>.+)$"
)

# The same delayed trigger over a **cast** rather than a combat event: "Until
# end of turn, whenever you cast a black spell, put a +1/+1 counter on this
# creature." (Mountain Titan.) Its own row rather than a widened alternation in
# the one above, because the shape is different in the place that matters — the
# noun phrase there describes the *attacking permanent* and here it describes
# the **spell**, which is a card on the stack with no computed characteristics
# at all (CR 613.1). Two objects, two matchers, so two rows.
#
# The phrase is delimited as a `_subject` group and read by the same noun parser
# every other one is, so a card printed "an artifact spell" needs no code.
_DELAYED_CAST_UNTIL_RE = re.compile(
    r"^until end of turn, whenever you cast (?P<cast_subject>an? .+? spell), "
    r"(?P<effect>.+)$"
)


#: Which delayed-trigger event each printed phrase names. A phrase whose event
#: has no fire site has nowhere to be announced, so the clause refuses rather
#: than arming a trigger nothing will ever look at — the dispatcher question
#: round 93 wrote down, asked at the moment the trigger is *created* instead of
#: at the moment it should have fired. Which events *have* a fire site is
#: ``engine/delayed_triggers.DELAYED_EVENTS``, not a second list here.
_DELAYED_EVENT_PHRASES: dict[str, str] = {
    "attack": "creatures_attack",
    "attacks": "creatures_attack",
    # "Whenever a creature **blocks** this turn, …" (Battle Cry). One word of
    # the sentence differs, so it is a row here rather than a second regex —
    # the shape, the duration and the repetition are the attack form's.
    "block": "creature_blocks",
    "blocks": "creature_blocks",
    "deals combat damage to a player": "creature_deals_combat_damage_to_player",
    # "…**attacks and isn't blocked**" (Gaze of Pain). Read before the bare
    # "attacks" it begins with — the alternation in the pattern above is
    # ordered, and the short spelling matching first would leave "and isn't
    # blocked" in front of the comma and fail the line. Which is the safe
    # failure, and is why the ordering is the whole of the difference here.
    "attacks and isn't blocked": "creature_attacks_unblocked",
}


def _parse_delayed_attack_trigger(
    effect_clause: str, card_name: str | None
) -> OracleInstruction | None:
    """The ``create_delayed_trigger`` instruction for a delayed attack-trigger
    clause, or None when the clause is not one — including when its inner
    effect fails to parse, so the card refuses rather than arming a trigger
    that fires into nothing."""
    normalized = normalize_creature_line(effect_clause)
    cast = _DELAYED_CAST_UNTIL_RE.match(normalized)
    if cast is not None:
        from .grammar import subject_filter_payload
        from .subject_filters import card_only_filter

        # ``zone`` is carried by the **event**, not by the filter: "a black
        # **spell**" narrows to the stack and ``you_cast_spell`` fires nowhere
        # else, so the restriction is enforced by which trigger this is. It has
        # to be named rather than left in, because the delayed trigger's matcher
        # answers about a *card* and has no zone to test — a key it cannot
        # answer is one it silently ignores, which is the failure the gate below
        # exists to prevent. Named here rather than widened into
        # ``CARD_ONLY_FILTER_KEYS``, where for a discard or a graveyard count the
        # same key would name a restriction nothing carries out.
        described = subject_filter_payload(
            cast.group("cast_subject"), carried_separately=frozenset({"zone"})
        )
        # A spell is a card on the stack, so only what is *printed* on it is
        # testable — `card_only_filter` is the list of exactly which keys that
        # comes to, and anything wider refuses rather than arming a trigger that
        # fires on a strictly larger set than the card prints.
        if described is None or card_only_filter(described) is None:
            return None
        inner = _line_instruction(cast.group("effect"), card_name, activated=True)
        if inner is None:
            return None
        return OracleInstruction(
            "create_delayed_trigger",
            "",
            {
                "event": "you_cast_spell",
                "subject_filter": described,
                "instruction": inner[0],
                # "Until end of turn, **whenever** …" — CR 603.7b's stated
                # duration, so it fires every time for as long as it lasts.
                "once": False,
                "duration": "end_of_turn",
            },
        )
    narrowed = _DELAYED_ATTACK_UNTIL_RE.match(normalized)
    if narrowed is not None:
        from .grammar import subject_filter_payload

        described = subject_filter_payload(narrowed.group("attacker_subject"))
        if described is None:
            # A phrase the matcher cannot test would arm a trigger firing on a
            # strictly larger set than the card prints — the same refusal every
            # other narrowed condition makes.
            return None
        inner = _line_instruction(narrowed.group("effect"), card_name, activated=True)
        if inner is None:
            return None
        return OracleInstruction(
            "create_delayed_trigger",
            "",
            {
                "event": _DELAYED_EVENT_PHRASES[narrowed.group("event")],
                "batch": False,
                "nontoken": False,
                "subject_filter": described,
                "instruction": inner[0],
                # "Until end of turn, **whenever** …" — CR 603.7b's "unless
                # it's stated otherwise": this one fires every time its event
                # happens for as long as it lasts.
                "once": False,
                "duration": "end_of_turn",
            },
        )
    match = _DELAYED_ATTACK_RE.match(normalized)
    if match is None:
        return None
    event = _DELAYED_EVENT_PHRASES[match.group("event")]
    batch = bool(match.group("batch"))
    if batch and event != "creatures_attack":
        # "One or more creatures" is CR 508.1's declaration read as one event,
        # which is what the attack fire site announces. The block fire site
        # announces one creature at a time (CR 509.1g), so an entry armed as a
        # batch would fire per blocker with a count nobody set. No card prints
        # it; refusing is what keeps that true rather than assumed.
        return None
    inner = _line_instruction(match.group("effect"), card_name, activated=True)
    if inner is None:
        return None
    return OracleInstruction(
        "create_delayed_trigger",
        "",
        {
            "event": event,
            "batch": batch,
            "nontoken": bool(match.group("nontoken")),
            "instruction": inner[0],
            "once": False,
            "duration": _DELAYED_DURATIONS[match.group("duration")],
        },
    )



#: Where a sentence ends, for :func:`_split_trailing_delayed_trigger`. A period
#: and a space, which is how every printed paragraph in the pool joins two
#: sentences — deliberately not a general sentence splitter, because the only
#: thing this needs to find is a boundary the delayed-trigger table can be
#: offered the right-hand side of, and an offer that is wrong simply does not
#: match.
_SENTENCE_BREAK = ". "


def _split_trailing_delayed_trigger(
    line: str, card_name: str | None
) -> OracleInstruction | None:
    """One ``sequence`` for a spell line whose **last** sentence creates a
    delayed triggered ability (CR 603.7), or None when it is not that shape.

    "**Mill four cards.** Whenever a creature attacks this turn, it gets +1/+0
    until end of turn for each creature card put into your graveyard this way."
    (Song of Blood.)

    A sequence rather than two lines, and that is the whole reason this is here
    rather than in ``expand_static_then_trigger_lines``. That rewrite is gated
    on its first sentence being a *static ability the engine implements in
    full*, and its own docstring names this card as the reason: split into two
    lines, the trigger would be an ability of the card instead of something the
    **resolution** creates, and the mill in front of it — whose record the
    trigger reads — would not have happened yet. Here the two sentences stay one
    resolution, in printed order, exactly as ``Choose target Wall creature.
    Whenever that creature is dealt damage…`` (Glyph of Life) already does one
    layer down in the grammar.

    The head is compiled through the ordinary spell-line front end, so it is a
    sentence that already worked or the split does not happen.

    **The producer gate lives here**, because this is the one place both halves
    are in hand: the delayed clause is compiled on its own and cannot see what
    precedes it, so a "this way" count inside it would silently read an empty
    record. Refusing returns None, which leaves the card unsupported naming the
    line — the loud direction.
    """
    at = line.find(_SENTENCE_BREAK)
    while at != -1:
        head, tail = line[:at + 1].strip(), line[at + len(_SENTENCE_BREAK):].strip()
        delayed = _parse_delayed_attack_trigger(tail, card_name)
        if delayed is not None:
            found = _line_instruction(head, card_name, spell_line_only=True)
            if found is not None and _records_the_delay_reads(found[0], delayed):
                return OracleInstruction(
                    "sequence", "", {"steps": (found[0], delayed)}
                )
        at = line.find(_SENTENCE_BREAK, at + 1)
    return None


def _records_the_delay_reads(head: OracleInstruction, delayed: OracleInstruction) -> bool:
    """Whether *head* records every scratchpad key the delayed ability's own
    effect counts.

    CR 608.2h: what a delayed ability refers to is frozen when it is created —
    ``handlers/delayed.create_delayed_trigger`` copies the whole resolution
    scratchpad into the entry — so the number is right *if and only if* a step
    in front of it actually wrote the record. With no producer the count is a
    silent zero, which on Song of Blood is a delayed ability that pumps nothing
    while the card reports supported.

    Asked through ``produced_keys``, the one declaration of what a step of each
    kind records, so a new producer is covered the day it is declared rather
    than the day someone remembers this function.
    """
    from .grammar.lowering._records import produced_keys

    wanted = _recorded_card_keys(delayed)
    if not wanted:
        return True
    return wanted <= produced_keys(head)


def _recorded_card_keys(instruction: OracleInstruction) -> frozenset[str]:
    """Every ``recorded_cards`` key *instruction* and its nested steps count.

    A walk rather than a single payload read: the delayed ability carries its
    effect inside its own payload, and that effect may itself be a sequence.
    """
    keys: set[str] = set()
    spec = instruction.payload.get(X_FROM_COUNT)
    if isinstance(spec, dict) and spec.get("recorded_cards"):
        keys.add(str(spec["recorded_cards"]))
    for value in instruction.payload.values():
        if isinstance(value, OracleInstruction):
            keys |= _recorded_card_keys(value)
        elif isinstance(value, tuple):
            for item in value:
                if isinstance(item, OracleInstruction):
                    keys |= _recorded_card_keys(item)
    return frozenset(keys)
