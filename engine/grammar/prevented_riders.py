"""CR 615.5's additional effect — the sentence printed beside a prevention.

"Some prevention effects also include an additional effect, which may refer to
the amount of damage that was prevented." One production and one closed table:
"You gain life equal to the damage prevented this way" (Reverse Damage), "Exile
cards from the top of your library equal to the damage prevented this way"
(Bone Mask), "For each 1 damage prevented this way, put a +1/+1 counter on that
creature" (Temper), and Honorable Passage's reflecting rider.

**A floor rather than a family**, because two ``effects/`` families read it and
``effects/`` has no shared module of its own: ``effects/prevention.py`` calls it
from the counted shield (Temper's leading spelling) and
``effects/damage_instances.py`` from the chosen-source one (Reverse Damage's
trailing one). Leaving it in either would make the other import a family, which
is the coupling ``tests/engine/test_grammar_layering.py`` exists to forbid — and
what the coupling would buy is worse than the import. This is deliberately
**one** reader of one printed clause: two productions would make which riders a
card may carry depend on which shield printed them, and the module it moved out
of says so twice.

**Not ``records``, and the reason is a cycle rather than a taxonomy.** The
subject fits at first reading — "the damage prevented this way" names a record,
and ``records._parse_for_each_this_way`` already reads Temper's leading half —
but every production in that module answers "how many?" with an ``Amount``,
where this one returns a whole rider node. And the mechanical half is decisive:
``amounts.py`` imports ``records`` at module level, so reading
``amounts.accept_counter_kind`` from inside ``records`` would close exactly the
import cycle that module's split was taken to remove.

Above ``records`` and ``readers``, which it reads and which never read it back,
and below every family that calls it.
"""

from . import ast
from .amounts import accept_counter_kind
from .readers import accept_source_reference
from .records import _parse_for_each_this_way
from .stream import TokenStream
from .vocabulary import COLOR_WORDS


#: CR 615.5's additional effect, keyed by the verb that opens it. A closed table
#: rather than a nested statement parse, for the reason
#: ``ast.PreventDamage.prevented_rider`` gives: the rider's quantity does not
#: exist until the shield has absorbed something, so it runs from the
#: interceptor rather than as a lowered step — and the interceptor is what the
#: name selects. A card printing a third rider adds a row here, a shield kind
#: and the code behind it, and is refused until it does.
#: Each row is the rider's name, the sentence as printed **after the
#: prevention** (which then spells its amount "equal to the damage prevented
#: this way"), and the sentence as printed **after a condition** — where the
#: condition already said which damage this is about, so the amount is the
#: pronoun "that much". ``None`` for a rider no card prints conditionally.
_PREVENTED_THIS_WAY_RIDERS: tuple[
    tuple[str, tuple[str, ...], "tuple[str, ...] | None"], ...
] = (
    ("gain_life", ("you", "gain", "life"), ("you", "gain", "that", "much", "life")),
    (
        "exile_from_library",
        ("exile", "cards", "from", "the", "top", "of", "your", "library"),
        None,
    ),
)


def _parse_prevented_this_way_rider(stream: TokenStream) -> "ast.PreventedRider | None":
    """``. <effect> equal to the damage prevented this way.`` — the sentence a
    shield's own card prints after the prevention (CR 615.5).

    "You gain life equal to the damage prevented this way" (Reverse Damage) and
    "Exile cards from the top of your library equal to the damage prevented this
    way" (Bone Mask). One production, because everything from "equal to" onward
    is the same clause and the amount is the same number — what the two cards do
    with it is the row above.

    Temper prints the quantity in **front** of the verb instead: "For each 1
    damage prevented this way, put a +1/+1 counter on that creature." Read here
    rather than by a reader of its own, because it is the same clause about the
    same record — a second production would make which riders a card can carry
    depend on which of the two printed orders it used. Its counter kind is
    payload (CR 122.1), which is why it is a branch and not a row of the fixed
    word table above.

    Read here rather than as a sentence of its own for
    :func:`_parse_instead_rider`'s reason one screen up: it refers to an amount
    that does not exist yet, so a statement layer that split them would run it
    over zero.

    Refuses with the cursor untouched, so a prevention followed by any other
    sentence keeps the reading it has.
    """
    mark = stream.mark()
    if not stream.accept_punct("."):
        return None
    # "**For each 1 damage prevented this way,** put a +1/+1 counter on that
    # creature." (Temper.) ``records._parse_for_each_this_way`` is the same
    # reader Sacred Boon's *trailing* clause goes through, so "damage prevented
    # this way" names the same record from either printed position. "That
    # creature" is the shielded one and is not read as a noun phrase: the
    # interceptor holds the recipient it just absorbed for, so there is nothing
    # to resolve and any other subject is a sentence this does not implement.
    #
    # Tried first, and it refuses without consuming, so every other rider keeps
    # the reading it has.
    counted = _parse_for_each_this_way(stream)
    if counted is not None and counted.source == "prevention_shield":
        if stream.accept_punct(",") and stream.accept_phrase("put", "a"):
            token = accept_counter_kind(stream)
            if token is not None and stream.accept_word("counter") and (
                stream.accept_phrase("on", "that", "creature")
            ):
                stream.accept_punct(".")
                return ast.PreventedRider("put_counter", counter=str(token.text))
    stream.reset(mark)
    stream.accept_punct(".")
    # "**If damage from a black source is prevented this way,** you gain that
    # much life." (Shadowbane.) The same rider with a condition in front of it
    # and the quantity spelled "that much" instead of repeating the clause —
    # one production, because everything it decides is the same: what happens
    # after the prevention, and how big it is.
    colours: tuple[str, ...] = ()
    conditional = False
    condition_mark = stream.mark()
    # "**Whenever** damage from a black or red source is prevented this way
    # **this turn**, you gain that much life." (Samite Ministration.) The
    # condition below with the two words a shield that lasts all turn prints
    # around it — see ``ast.PreventedRider.repeating``. One reader for both
    # openers, because everything behind them is the same clause.
    repeating = False
    if stream.accept_phrase("whenever", "damage", "from"):
        repeating = True
    if repeating or stream.accept_phrase("if", "damage", "from"):
        stream.accept_word("a", "an")
        token = stream.peek()
        word = str(token.text).lower() if token is not None else ""
        while word in COLOR_WORDS:
            colours += (COLOR_WORDS[word],)
            stream.advance()
            if not stream.accept_word("or"):
                break
            token = stream.peek()
            word = str(token.text).lower() if token is not None else ""
        if not colours or not stream.accept_phrase(
            "source", "is", "prevented", "this", "way"
        ):
            stream.reset(mark)
            return None
        # The two words travel together: "whenever … this turn" is the blanket's
        # spelling and "if …" the one-shot's, and a sentence mixing them is not
        # one this reads — so the opener without its window, or the window
        # without its opener, refuses rather than being read as the other.
        if stream.accept_phrase("this", "turn") != repeating:
            stream.reset(mark)
            return None
        stream.accept_punct(",")
        conditional = True
    else:
        stream.reset(condition_mark)
    # "…, **~ deals that much damage to the source's controller.**" (Honorable
    # Passage.) A row of the table above would have to spell its subject as a
    # word run, and this rider's subject is the *card itself* — one SELF token
    # the lexer built out of the printed name, which no run of words can match.
    # So it is a branch rather than a row, tried before the table because the
    # table's rows all open with a different word and nothing here can shadow
    # them.
    #
    # Only the conditional spelling: the unconditional one ("~ deals damage
    # equal to the damage prevented this way to …") is printed by no card in
    # the pool, and a row admitted for it would be a claim nothing checks.
    if conditional and not repeating:
        reflect_mark = stream.mark()
        if accept_source_reference(stream) and stream.accept_phrase(
            "deals", "that", "much", "damage", "to", "the", "source", "'s",
            "controller",
        ):
            stream.accept_punct(".")
            return ast.PreventedRider("damage_source_controller", colours)
        stream.reset(reflect_mark)
    for name, printed, after_condition in _PREVENTED_THIS_WAY_RIDERS:
        if conditional:
            # The condition already said which damage the rider is about, so the
            # amount is the pronoun rather than a repeat of the clause. One
            # spelling per row, never both: a sentence readable two ways is a
            # sentence whose reading depends on which branch was tried first.
            if after_condition is not None and stream.accept_phrase(*after_condition):
                stream.accept_punct(".")
                return ast.PreventedRider(name, colours, repeating=repeating)
            continue
        if stream.accept_phrase(*printed):
            if stream.accept_phrase(
                "equal", "to", "the", "damage", "prevented", "this", "way"
            ):
                stream.accept_punct(".")
                return ast.PreventedRider(name)
            stream.reset(mark)
            return None
    stream.reset(mark)
    return None
