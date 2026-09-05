"""Riders: a sentence that modifies the one before it.

A rider is not a step of its own. "If you do, …" branches the decision the
previous sentence offered; "Its controller creates a token" names the permanent
that sentence exiled; "…and it can't be regenerated" narrows the damage it
dealt. Every one of them reads a referent the previous step bound, which is why
they are read by the sentence loop rather than by ``parse_statement``: on their
own they name nothing.

Split out of ``parser.py`` when that file crossed 1,000 lines again. A family
rather than an arbitrary cut — this is the whole of what "a sentence about the
previous sentence" means, and the loop that drives them stays behind in
``parser.py`` with the line-level productions it belongs to.
"""

from __future__ import annotations

import dataclasses
from dataclasses import replace

from ..oracle_types import LAST_TARGET_CONTROLLER
from . import ast
from .amounts import parse_amount
from .errors import GrammarError
from .lexer import PT
from .nouns import parse_object_filter
from .effects import _parse_create_token, parse_source_damage_lock
from .rebinding import statement_bound_target as _statement_bound_target
from .phrases import _accept_number
from .statements import _parse_condition, parse_statement
from .stream import TokenStream
from .vocabulary import CARD_TYPES


# Sentinel: the rider was folded into the previous step, nothing to append.


def _parse_exile_instead_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> bool:
    """``If that spell would be put into your graveyard, exile it instead.``
    after a cast-permission sentence (Chandra, Flame's Catalyst's −2).

    Folded onto the permission rather than parsed as a step, because it is a
    property of the cast the permission allows — the engine stamps it onto the
    stack object at cast time — and as a standalone sentence "that spell"
    would dangle with nothing binding it.
    """
    last = steps[-1] if steps else None
    if not isinstance(last, ast.CastPermission) or last.what != "target_card":
        return False
    mark = stream.mark()
    if not stream.accept_phrase(
        "if", "that", "spell", "would", "be", "put", "into", "your", "graveyard"
    ):
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    if not stream.accept_phrase("exile", "it", "instead"):
        stream.reset(mark)
        return False
    steps[-1] = replace(last, exile_instead=True)
    return True


def _accept_removed_permanents_controller(stream: TokenStream) -> bool:
    """The possessive naming the controller of the permanent the sentence in
    front of this one removed — ``that creature's controller`` or ``its
    controller`` — consumed, or False with the cursor untouched.

    **One reader, because it was two.** Transmogrify prints "that creature's
    controller" and Polymorph prints "its controller" for the same seat, and the
    reveal rider below reads both; the token rider above read only the second,
    so Ovinomancer's "That creature's controller creates a 0/1 green Sheep
    creature token" refused a phrase the module three functions down already
    knew. A fork in a *fragment* is only ever found by whoever extends it, which
    is what makes the extension the moment to collapse it.

    Neither spelling is a difference in what the card does, so normalising at
    one end would be the same card twice.
    """
    return bool(
        stream.accept_phrase("that", "creature", "'s", "controller")
        or stream.accept_phrase("its", "controller")
    )


def _parse_its_controller_creates_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """``Its controller creates a <token>.`` after a sentence that chose a
    target (Angelic Ascension, Secure the Scene — both after an exile), and
    ``That creature's controller creates a <token>.`` after a destroy
    (Ovinomancer).

    Both possessives name the previous sentence's chosen permanent, which is
    gone by the time the token arrives — so the token rides the controller that
    step recorded, and the lowering demands that producer. Parsed as its own
    sentence, either phrase would name nobody at all.
    """
    if not steps or _statement_bound_target(steps[-1]) is None:
        return None
    mark = stream.mark()
    if not _accept_removed_permanents_controller(stream):
        return None
    if not stream.at_word("creates"):
        stream.reset(mark)
        return None
    try:
        token = _parse_create_token(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    assert isinstance(token, ast.CreateToken)
    return replace(token, recipient=LAST_TARGET_CONTROLLER)


def _parse_that_controller_reveals_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """``That creature's controller reveals cards from the top of their library
    until they reveal a creature card. That player puts that card onto the
    battlefield, then shuffles the rest into their library.`` (Transmogrify.)

    ``Its controller reveals cards from the top of their library until they
    reveal a creature card. The player puts that card onto the battlefield,
    then shuffles all other cards revealed this way into their library.``
    (Polymorph, behind a destroy rather than an exile.)

    The same shape as the "its controller creates a token" rider beside it, and
    for the same reason: "that creature" names the permanent the previous
    sentence removed, which is gone by the time this runs, so the library read
    rides the controller that step recorded. Parsed as its own sentence it names
    nobody.

    All three sentences are consumed here. They describe one procedure over one
    revealed pile — "that card" is what the reveal stopped on and "the rest" is
    exactly what it turned over first — so parsed apart the last two would
    dangle referents nothing binds.

    **Three phrases have two printed spellings each**, and each pair is read
    rather than normalized at one end: the possessive that names the removed
    permanent (``_accept_removed_permanents_controller``), the article in front
    of the seat
    ("that player" / "the player") and the words for the cards the reveal
    turned over first ("the rest" / "all other cards revealed this way"). None
    of the three is a difference in what the card does — Polymorph and
    Transmogrify are the same procedure — so a second production for them
    would be the same card twice.
    """
    if not steps or _statement_bound_target(steps[-1]) is None:
        return None
    mark = stream.mark()
    if not _accept_removed_permanents_controller(stream):
        return None
    if not stream.accept_phrase(
        "reveals", "cards", "from", "the", "top", "of", "their", "library",
        "until", "they", "reveal",
    ):
        stream.reset(mark)
        return None
    try:
        stream.accept_word("a", "an")
        filt = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return None
    if not filt.is_card:
        stream.reset(mark)
        return None
    stream.accept_punct(".")
    # Every word of the destination and of what happens to the rest. A card
    # that milled the pile instead of shuffling it back is a different card, and
    # the difference does not show until this sentence.
    if not (
        stream.accept_phrase(
            "that", "player", "puts", "that", "card", "onto", "the", "battlefield",
        )
        or stream.accept_phrase(
            "the", "player", "puts", "that", "card", "onto", "the", "battlefield",
        )
    ):
        stream.reset(mark)
        return None
    stream.accept_punct(",")
    if not stream.accept_word("then"):
        stream.reset(mark)
        return None
    if not stream.accept_word("shuffles"):
        stream.reset(mark)
        return None
    if not (
        stream.accept_phrase("the", "rest")
        or stream.accept_phrase("all", "other", "cards", "revealed", "this", "way")
    ):
        stream.reset(mark)
        return None
    if not stream.accept_phrase("into", "their", "library"):
        stream.reset(mark)
        return None
    return ast.RevealUntil(LAST_TARGET_CONTROLLER, filt)


def _parse_conditional_instead_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> bool:
    """``You gain 4 life. If a creature died this turn, you gain 8 life
    instead.`` (Life Goes On.) ``{T}: Add {C}. If you control an Urza's
    Power-Plant and an Urza's Tower, add {C}{C} instead.`` (Urza's Mine.)

    The second sentence *replaces* the first when its condition holds, so the
    pair folds into one ``Conditional`` — then the bigger gain, otherwise the
    printed base. Parsed apart, the two sentences would gain 12 life on a
    death; the "instead" is the whole content of the sentence, so it is
    required, and only a same-shaped statement may replace the last step.
    """
    # The statement kinds this rider can replace. `AddMana` joins `GainLife`
    # for the Antiquities land cycle — "{T}: Add {C}. If you control an Urza's
    # Power-Plant and an Urza's Tower, add {C}{C} instead." — which is the same
    # sentence pair with a different verb. `DealDamage` joins them for
    # Gangrenous Zombies — "…deals 1 damage to each creature and each player.
    # If you control a snow Swamp, this creature deals 2 damage to each
    # creature and each player instead." — which is the same pair again. The
    # replacement must be the *same* kind as what it replaces (checked below),
    # so widening the set cannot let one kind silently stand in for another.
    _REPLACEABLE = (ast.GainLife, ast.AddMana, ast.DealDamage)

    last = steps[-1] if steps else None
    if not isinstance(last, _REPLACEABLE):
        return False
    mark = stream.mark()
    if not stream.accept_word("if"):
        return False
    try:
        condition = _parse_condition(stream)
    except GrammarError:
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    try:
        replacement = parse_statement(stream)
    except GrammarError:
        stream.reset(mark)
        return False
    if type(replacement) is not type(last) or not stream.accept_word("instead"):
        stream.reset(mark)
        return False
    steps[-1] = ast.Conditional(condition, then=replacement, otherwise=last)
    return True


def _parse_who_cant_rider(
    stream: TokenStream, steps: list[ast.Statement]
) -> ast.Statement | None:
    """``Each opponent who can't loses N life.`` after an each-player discard
    (Liliana, Waker of the Dead). The loss applies only to opponents who could
    not perform the previous sentence's action, so it is recorded as a
    back-reference the lowering turns into a reader of that step's result."""
    last = steps[-1] if steps else None
    if not (isinstance(last, ast.Discard) and last.player.kind == "each_player"):
        return None
    mark = stream.mark()
    if not (
        stream.accept_word("each")
        and stream.accept_word("opponent")
        and stream.accept_phrase("who", "can't")
    ):
        stream.reset(mark)
        return None
    try:
        stream.expect_word("loses", "lose")
        amount = parse_amount(stream)
        stream.expect_word("life")
    except GrammarError:
        stream.reset(mark)
        return None
    return ast.LoseLife(ast.PlayerRef("each_opponent"), amount, who_could_not="discard")


def _attach_spend_only(stream: TokenStream, steps: list[ast.Statement]) -> bool:
    """Fold "Spend this mana only to …" into the mana production before it.

    A rider and not a step: the sentence adds nothing to the game, it says what
    the *previous* sentence's mana may pay for (CR 106.6). Parsed as its own
    step it would be an effect nothing performs, and the mana would go into the
    unrestricted pool with the restriction reported as understood.

    Which restrictions exist is `engine/restricted_mana.py`'s question, asked
    through its own matcher over the sentence's printed text — the delegation
    round 85 established for a registry-claimed sentence, and for its reason: a
    copy of the phrase here would be free to drift from the predicate that
    enforces it, and mana spent more freely than the card allows is the
    direction that drift goes.
    """
    from ..restricted_mana import mana_restriction_for

    if not isinstance(steps[-1], ast.AddMana):
        return False
    mark = stream.mark()
    start = stream.pos
    while not stream.exhausted and not stream.at_punct(".", ";"):
        stream.advance()
    sentence = stream.text_between(start, stream.pos)
    restriction = mana_restriction_for(sentence)
    if restriction is None:
        stream.reset(mark)
        return False
    steps[-1] = dataclasses.replace(steps[-1], spend_only=restriction.key)
    return True


def _attach_unpaid_penalty(statement: ast.Statement, penalty: str) -> ast.Statement:
    """Fold "If that player doesn't, …" into the "unless … pays" it belongs to.

    Raises when there is no such effect to attach to. A penalty for declining a
    cost that was never offered is not something the grammar can place, and
    consuming the sentence anyway is precisely the dropped-rider bug the
    full-consumption invariant exists to prevent.
    """
    if isinstance(statement, ast.CounterSpell) and statement.unless_pays is not None:
        return ast.CounterSpell(statement.subject, statement.unless_pays, penalty)
    raise GrammarError("an unpaid-cost penalty with no cost to decline")


def _attach_destroyed_this_way(stream: TokenStream, steps: list[ast.Statement]) -> bool:
    """Fold "If this creature is destroyed this way, it deals N damage to you."
    into the destroy-unless-pay before it (Cosmic Horror).

    A rider rather than a step, and for the reason the whole family exists: on
    its own the sentence names nothing. "Destroyed **this way**" is a question
    about what the previous sentence did — a regenerated or indestructible
    creature was not destroyed and takes no damage (CR 701.8c) — and the only
    thing that can answer it is whatever performed the destruction.

    Attaches only to a node that can carry it. A card printing this after
    something else is saying something the grammar cannot place, and consuming
    the sentence anyway is the dropped-rider bug the full-consumption invariant
    exists to prevent — so the near-miss rewinds and the line fails loudly.
    """
    last = steps[-1] if steps else None
    if not isinstance(last, ast.DestroyUnlessPay):
        return False
    mark = stream.mark()
    if not stream.accept_phrase("if", "this"):
        stream.reset(mark)
        return False
    # The noun repeats the subject's own type and carries nothing.
    if stream.peek_word() is None:
        stream.reset(mark)
        return False
    stream.advance()
    if not stream.accept_phrase("is", "destroyed", "this", "way"):
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    if not stream.accept_phrase("it", "deals"):
        stream.reset(mark)
        return False
    # `parse_amount`, not the number-word table: the damage is printed as a
    # digit ("7"), which is a number *token* and not a word.
    amount = parse_amount(stream)
    if not isinstance(amount, ast.Fixed) or not stream.accept_phrase(
        "damage", "to", "you"
    ):
        stream.reset(mark)
        return False
    steps[-1] = dataclasses.replace(last, damage_if_destroyed=amount.value)
    return True


def _attach_no_regeneration(stream: TokenStream, steps: list[ast.Statement]) -> bool:
    """Fold "A creature destroyed this way can't be regenerated." into the
    destroy the sentence before it performed (Soul Rend).

    CR 701.19c's rider, which ``_parse_destroy`` already reads when it trails
    the verb directly ("Destroy target creature. It can't be regenerated.").
    Soul Rend prints a **condition** between them — "Destroy target creature
    **if it's white**" — and the sentence layer folds that into a
    ``Conditional`` *after* the destroy production has finished, so by the time
    the rider is printed there is a wrapper in the way and the destroy
    production's own probe has long since rewound.

    So this reaches through the wrapper, and only through one it can name.
    The alternative is what Soul Rend had: the whole line refuses, a
    ``spell_pattern`` whitelist marker claims the card anyway, and it resolves
    doing nothing but drawing the cantrip it also prints.

    The same reader the destroy production uses
    (``_accept_destroyed_this_way_no_regen``), so the two spellings of the
    sentence stay one rule — a second copy here is the two-readings shape this
    grammar keeps removing.
    """
    from .effects.destruction import _accept_destroyed_this_way_no_regen

    last = steps[-1] if steps else None
    if last is None:
        return False
    mark = stream.mark()
    if not _accept_destroyed_this_way_no_regen(stream):
        stream.reset(mark)
        return False
    folded = _with_no_regeneration(last)
    if folded is None:
        # Nothing here destroys anything, so the sentence says something this
        # cannot place — rewound rather than consumed, which is the
        # full-consumption invariant refusing the line loudly instead of
        # dropping a rider.
        stream.reset(mark)
        return False
    steps[-1] = folded
    return True


def _with_no_regeneration(statement: ast.Statement) -> "ast.Statement | None":
    """*statement* with its destruction marked unregenerable, or None.

    Reaches into a ``Conditional``'s arms because that is the only wrapper a
    printed card puts between the verb and this rider — "Destroy target
    creature **if it's white**" — and into both of them, because a card
    printing an "otherwise, destroy …" arm means the rider about either.
    Anything else answers None and the caller rewinds.
    """
    if isinstance(statement, ast.Destroy):
        return dataclasses.replace(statement, no_regen=True)
    if isinstance(statement, ast.OneOf):
        # "Destroy all green creatures **or** all white creatures. They can't
        # be regenerated." (Reign of Terror.) The rider is printed once and is
        # about whichever half the player takes, so it is folded into *every*
        # option that can carry it rather than into the last one parsed — a
        # mode left unmarked would let the creatures it destroys regenerate,
        # which is the half of the card nothing would report.
        folded = tuple(
            _with_no_regeneration(option) or option for option in statement.options
        )
        if folded == statement.options:
            # No option destroys anything, so the rider names nothing here —
            # None rather than a rewrite, and the caller rewinds.
            return None
        return dataclasses.replace(statement, options=folded)
    if isinstance(statement, ast.Conditional):
        then = _with_no_regeneration(statement.then)
        otherwise = (
            _with_no_regeneration(statement.otherwise)
            if statement.otherwise is not None else None
        )
        if then is None and otherwise is None:
            return None
        return dataclasses.replace(
            statement,
            then=then if then is not None else statement.then,
            otherwise=(
                otherwise if otherwise is not None else statement.otherwise
            ),
        )
    return None


def _attach_tap_when_control_lost(
    stream: TokenStream, steps: list[ast.Statement]
) -> bool:
    """Fold "When you lose control of the creature, tap it." into the
    :class:`~engine.grammar.ast.GainControl` before it (Ray of Command; Magus of
    the Unseen prints "…of the artifact").

    CR 603.7: a delayed triggered ability created by the resolution, watching
    the very control change the sentence in front of it made. A rider rather
    than a step for the reason every rider here is one — on its own it names no
    object: "the creature" is the one the previous sentence took, and parsed
    alone the pronoun would dangle.

    The repeated noun is **consumed against the card types**, not skipped. A
    sentence naming something the control change never touched would otherwise
    be read as this one and arm a trigger on the wrong object; the closed set is
    what makes that fail loudly instead.
    """
    # The **control change**, wherever in the effect it sits — not `steps[-1]`.
    # Both cards print a sentence between the two ("That creature gains haste
    # until end of turn"), and the first sentence is itself a conjunction, so
    # the change is nested one level down. A rider that read only the last
    # top-level step refused both cards that print it.
    if not any(_finds_gain_control(step) for step in steps):
        return False
    mark = stream.mark()
    if not stream.accept_phrase("when", "you", "lose", "control", "of", "the"):
        stream.reset(mark)
        return False
    noun = stream.peek_word()
    if noun is None or noun not in CARD_TYPES:
        stream.reset(mark)
        return False
    stream.advance()
    stream.accept_punct(",")
    if not stream.accept_phrase("tap", "it"):
        stream.reset(mark)
        return False
    for index, step in enumerate(steps):
        rewritten = _marks_control_change_watched(step)
        if rewritten is not step:
            steps[index] = rewritten
    return True


def _finds_gain_control(node) -> bool:
    """Whether *node* contains a :class:`~engine.grammar.ast.GainControl`."""
    return _marks_control_change_watched(node) is not node


def _marks_control_change_watched(node):
    """*node* with every ``GainControl`` in it marked ``tap_when_lost``.

    A structural walk rather than a per-shape probe, for the reason
    ``rebinding._walk_specs`` is one: the change can be a step, a conjunct or a
    branch, and a list of the shapes it has been seen in goes stale the way
    every fire-site list in this engine has.
    """
    if isinstance(node, ast.GainControl):
        return dataclasses.replace(node, tap_when_lost=True)
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        changes = {
            field.name: rewritten
            for field in dataclasses.fields(node)
            for rewritten in (_marks_control_change_watched(getattr(node, field.name)),)
            if rewritten is not getattr(node, field.name)
        }
        return dataclasses.replace(node, **changes) if changes else node
    if isinstance(node, (tuple, list)):
        walked = [_marks_control_change_watched(item) for item in node]
        if all(a is b for a, b in zip(walked, node)):
            return node
        return type(node)(walked)
    return node


def _attach_exchanged_this_way(stream: TokenStream, steps: list[ast.Statement]) -> bool:
    """Fold "If those permanents are exchanged this way, destroy all Auras
    attached to them." into the :class:`~engine.grammar.ast.ExchangeControl`
    before it (Gauntlets of Chaos).

    The same argument as ``_attach_destroyed_this_way`` beside it: "exchanged
    **this way**" is a question about what the previous sentence did, and
    "them" names the two permanents it named. Parsed as its own step the
    sentence would have no permanents at all and would destroy every Aura on
    the board — which is exactly the sweep-lost-its-narrowing shape, so the
    near-miss rewinds and the line refuses rather than being consumed.
    """
    last = steps[-1] if steps else None
    if not isinstance(last, ast.ExchangeControl):
        return False
    mark = stream.mark()
    if not stream.accept_phrase(
        "if", "those", "permanents", "are", "exchanged", "this", "way"
    ):
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "destroy", "all", "auras", "attached", "to", "them"
    ):
        stream.reset(mark)
        return False
    steps[-1] = dataclasses.replace(last, destroy_attached_auras=True)
    return True


def _attach_source_damage_lock(
    stream: TokenStream, steps: list[ast.Statement]
) -> bool:
    """Fold "If <the source> would deal damage to a creature, that damage can't
    be prevented or dealt instead to another permanent or player." into the
    damage sentence before it (Lava Burst).

    A rider rather than a step: the sentence deals no damage and destroys
    nothing, it says which effects may modify the damage the sentence in front
    of it deals. Parsed as a step it would name no event at all.

    Whippoorwill prints the *other* sentence about the same two registries —
    "Damage that would be dealt to that creature this turn can't be …" — and
    that one is a step, because it arms a marker on a creature that outlives the
    resolution. Keeping them apart is the whole reason this is not the same
    production: read as Whippoorwill's, Lava Burst would lock every later
    source's damage to the same creature for the turn.
    """
    if not steps:
        return False
    mark = stream.mark()
    if not parse_source_damage_lock(stream):
        return False
    try:
        steps[-1] = _attach_riders(
            steps[-1], ast.DamageRiders(unpreventable_to_creature=True)
        )
    except GrammarError:
        stream.reset(mark)
        return False
    return True


def _attach_riders(statement: ast.Statement, riders: ast.DamageRiders) -> ast.Statement:
    """Fold damage riders into the most recent DealDamage of *statement*."""
    if isinstance(statement, ast.DealDamage):
        merged = ast.DamageRiders(
            no_regen=statement.riders.no_regen or riders.no_regen,
            exile_if_dies=statement.riders.exile_if_dies or riders.exile_if_dies,
            divided=statement.riders.divided,
            divided_evenly=statement.riders.divided_evenly,
            rounding=statement.riders.rounding,
            unpreventable_to_creature=(
                statement.riders.unpreventable_to_creature
                or riders.unpreventable_to_creature
            ),
        )
        return ast.DealDamage(
            statement.source, statement.amount, statement.recipients, merged, statement.chooser
        )
    if isinstance(statement, ast.Sequence) and statement.steps:
        steps = list(statement.steps)
        steps[-1] = _attach_riders(steps[-1], riders)
        return ast.Sequence(tuple(steps))
    if isinstance(statement, ast.Conjunction) and statement.effects:
        effects = list(statement.effects)
        effects[0] = _attach_riders(effects[0], riders)
        return ast.Conjunction(tuple(effects))
    raise GrammarError("damage rider with no damage effect to attach to")


# What "The new target must be a <noun>." may bound the choice to. A closed set
# for the reason every other table in this grammar is closed: the sentence is
# not decoration, it is the *only* thing narrowing a choice made at resolution,
# and a noun nothing offers would be consumed here and then ignored there —
# a retarget free to aim at anything the spell could originally have chosen.
_NEW_TARGET_NOUNS = frozenset({"player"})


def _attach_new_target_bound(
    stream: TokenStream, steps: list[ast.Statement]
) -> bool:
    """Fold "The new target must be a player." into the retarget before it.

    (Reflecting Mirror.) A rider rather than a step, and a rider rather than a
    field the production reads for itself: it is a whole printed sentence about
    the sentence in front of it, exactly like the counter cap below — the
    previous sentence chose the spell, this one bounds what may replace what
    that spell chose.

    The noun is checked against ``_NEW_TARGET_NOUNS``, not merely consumed. A
    bound the resolution cannot offer has to leave the line refused, because
    consuming it would admit the card with the sentence dropped.
    """
    last = steps[-1] if steps else None
    if not isinstance(last, ast.ChangeTarget):
        return False
    mark = stream.mark()
    if not stream.accept_phrase("the", "new", "target", "must", "be"):
        stream.reset(mark)
        return False
    stream.accept_word("a", "an")
    noun = stream.peek_word()
    if noun not in _NEW_TARGET_NOUNS:
        stream.reset(mark)
        return False
    stream.advance()
    steps[-1] = dataclasses.replace(last, new_target=noun)
    return True


def _attach_counter_cap(stream: TokenStream, steps: list[ast.Statement]) -> bool:
    """Fold "This ability can't cause the total number of <kind> counters on
    this <noun> to be greater than N." into the placement before it.

    The counter kind is checked against the placement's own, not just consumed:
    a card capping a *different* counter than the one it just placed is saying
    something this rider cannot express, and matching it anyway would cap the
    wrong pile.
    """
    last = steps[-1] if steps else None
    if not isinstance(last, ast.PutCounter):
        return False
    mark = stream.mark()
    if not stream.accept_phrase(
        "this", "ability", "can't", "cause", "the", "total", "number", "of"
    ):
        stream.reset(mark)
        return False
    token = stream.peek()
    if token is None or token.kind != PT or token.text != last.counter:
        stream.reset(mark)
        return False
    stream.advance()
    if not stream.accept_word("counters"):
        stream.reset(mark)
        return False
    if not stream.accept_phrase("on", "this"):
        stream.reset(mark)
        return False
    # The noun is **required**, not merely accepted. Optional, the rider still
    # matched with the word deleted — which the parse-coverage deletion probe
    # reported as a silently ignored word, and it was right: "on this to be
    # greater than four" is not a sentence, and a rule that accepts it is a
    # rule that would accept a cap on some other permanent's counters too.
    if not stream.accept_word(
        "creature", "artifact", "enchantment", "land", "permanent"
    ):
        stream.reset(mark)
        return False
    if not stream.accept_phrase("to", "be", "greater", "than"):
        stream.reset(mark)
        return False
    cap = _accept_number(stream)
    if cap is None:
        stream.reset(mark)
        return False
    steps[-1] = dataclasses.replace(last, cap=cap)
    return True


def _attach_unaffected_when_cost_paid(
    stream: TokenStream, steps: list[ast.Statement]
) -> bool:
    """Fold "If this spell's additional cost was paid, this effect doesn't
    affect combat damage that would be dealt by red creatures." into the
    prevention before it (Undergrowth).

    A rider rather than a step, and for the reason the whole family exists: on
    its own the sentence names nothing. "**This** effect" is the prevention the
    previous sentence created, and the only thing that can be narrowed is that
    prevention — a second statement would be a second effect, and two blanket
    preventions both applying is the card doing nothing it prints.

    Attaches only to a prevention that has not already been narrowed. A card
    printing this twice is saying something the grammar cannot place, and
    consuming the sentence anyway is the dropped-rider bug the full-consumption
    invariant exists to prevent — so the near-miss rewinds and the line fails
    loudly.
    """
    last = steps[-1] if steps else None
    if not isinstance(last, ast.PreventDamage):
        return False
    if last.unaffected_if_cost_paid is not None:
        return False
    mark = stream.mark()
    if not stream.accept_phrase(
        "if", "this", "spell", "'s", "additional", "cost", "was", "paid"
    ):
        stream.reset(mark)
        return False
    stream.accept_punct(",")
    if not stream.accept_phrase(
        "this", "effect", "doesn't", "affect", "combat", "damage",
        "that", "would", "be", "dealt", "by",
    ):
        stream.reset(mark)
        return False
    try:
        excluded = parse_object_filter(stream)
    except GrammarError:
        stream.reset(mark)
        return False
    steps[-1] = replace(last, unaffected_if_cost_paid=excluded)
    return True
