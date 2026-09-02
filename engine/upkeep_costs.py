"""The cost half of a pay-or-consequence upkeep obligation.

Every prompt in ``engine/phases/upkeep_step.py`` — cumulative upkeep, Cyclone's
longhand of it, Erosion's "unless you pay {U}", Nafs Asp's payment before the
draw step — asks one player for one cost and does something to them if they
decline. :class:`UpkeepCost` is that cost, and it is a leaf module rather than
part of ``cumulative_upkeep.py`` because the keyword is only the loudest of
those callers: Nafs Asp importing a module named for a keyword it does not have
would be the wrong shape, and the type is what `draw_step.py` and the web
prompt now hold.

**A cost is not a mana cost.** CR 702.24a admits *any* cost after the keyword,
and Ice Age uses the licence: "—Pay 2 life" (Glacial Chasm), "—Pay {B} and 1
life" (Infernal Darkness), "—Sacrifice a land" (Polar Kraken). The field names
are ``cast_costs.AdditionalCost``'s deliberately — CR 601.2b's additional cost,
CR 602.2b's activation cost and this one are the same act, and a cost this
engine can collect should not be described three ways.

**The phrase reader consumes all of it or refuses it**, which is the grammar's
own hard invariant carried into a derivation table. Not a precaution: the cost
used to go straight to ``mana_cost_from_symbols``, which *scans* for symbols and
ignores everything else by design, so "pay {B} and 1 life" came back ``{B}`` and
Infernal Darkness shipped supported with half its upkeep silently free. A phrase
this cannot express in full returns None, which costs its card support rather
than costing the card its cost.
"""

from __future__ import annotations

import re

from dataclasses import dataclass, field

from .mana_payment import mana_cost_from_symbols, mana_cost_label


@dataclass(frozen=True)
class UpkeepCost:
    """One upkeep cost, at the multiple the upkeep asking for it wants.

    Not "the printed cost" and not "what is owed" — either, depending which side
    of ``cumulative_upkeep.scaled_cost`` the holder is on. One type for both,
    because the arithmetic is the only difference between them and a separate
    "printed" type would be a second vocabulary for one thing.

    ``sacrifice`` is the noun phrase a sacrifice must match, in the payload
    vocabulary ``cast_costs.AdditionalCost.sacrifice_filter`` and the
    forced-sacrifice prompt already use. ``None`` means "no sacrifice", never
    "anything": an empty filter would let the payment be any permanent at all.
    """

    mana: dict[str, int] = field(default_factory=dict)
    life: int = 0
    sacrifice: dict | None = None
    sacrifices: int = 0
    #: "Cumulative upkeep—**Exile the top card of your library**." (Thought
    #: Lash.) How many cards off the top the payment eats; 0 is "no such cost".
    #: The activation cost of the same printed words is
    #: ``ActivatedAbilityCost.exile_top_of_library`` and is an int for the same
    #: reason: nothing is chosen and nothing is tested, so there is no filter
    #: and no picker — only a count, and CR 118.3 makes a library holding fewer
    #: cards unable to pay it.
    exile_top_of_library: int = 0
    #: "Cumulative upkeep—**Have an opponent create a 1/1 red Survivor creature
    #: token**." (Varchild's War-Riders.) CR 702.24a's licence taken as far as
    #: it goes: a cost whose payer spends *nothing at all* and whose whole
    #: content is something an opponent does. It is a cost anyway — declining it
    #: still sacrifices the permanent — and the payload is the ``create_token``
    #: instruction the grammar lowers the printed sentence to, so the token this
    #: pays with is built by the one token maker in the engine rather than by a
    #: second reading of "1/1 red Survivor creature token".
    #:
    #: Paired with a count for the reason ``sacrifice``/``sacrifices`` are: the
    #: escalation multiplies how many, never what each one is.
    opponent_token: dict | None = None
    opponent_tokens: int = 0

    def _paid_terms(self) -> list[str]:
        """The parts of the cost a player *pays*, as printed: "{1}{B}", "3
        life". Not the sacrifice, which is a thing they do rather than a thing
        they hand over — see :meth:`pay_label`."""
        terms: list[str] = []
        if self.mana:
            terms.append(mana_cost_label(self.mana))
        if self.life:
            terms.append(f"{self.life} life")
        return terms

    def _sacrifice_term(self) -> str:
        from .subject_filters import filter_head_noun

        if not self.sacrifices:
            return ""
        noun = filter_head_noun(self.sacrifice)
        if self.sacrifices == 1:
            return f"sacrifice a {noun}"
        return f"sacrifice {self.sacrifices} {noun}s"

    def _library_exile_term(self) -> str:
        """"exile the top card of your library" — beside the sacrifice above and
        for its reason: a card taken off a library is a thing the payer *does*,
        not a thing they hand over, so "Pay exile the top card" is not a
        sentence."""
        if not self.exile_top_of_library:
            return ""
        if self.exile_top_of_library == 1:
            return "exile the top card of your library"
        return (
            f"exile the top {self.exile_top_of_library} cards of your library"
        )

    def _opponent_token_term(self) -> str:
        """"have an opponent create a 1/1 red Survivor creature token" — beside
        the two above and for their reason: nothing is handed over, so it can
        only be written as the thing the payer causes to happen."""
        if not self.opponent_tokens:
            return ""
        name = str((self.opponent_token or {}).get("name") or "token")
        if self.opponent_tokens == 1:
            return f"have an opponent create a {name}"
        return f"have an opponent create {self.opponent_tokens} {name}s"

    def _action_terms(self) -> list[str]:
        return [
            term
            for term in (
                self._sacrifice_term(),
                self._library_exile_term(),
                self._opponent_token_term(),
            )
            if term
        ]

    def describe(self) -> str:
        """The cost as a player reads it, for a "Cost:" line and a log line."""
        parts = self._paid_terms() + self._action_terms()
        return " and ".join(parts) or mana_cost_label({})

    def pay_label(self) -> str:
        """The same cost as the imperative on the button that performs it.

        A separate rendering rather than "Pay " glued to :meth:`describe`,
        because a sacrifice is not something a player hands over: "Pay
        sacrifice a land" is not a sentence, and the cost is the only thing
        that knows which parts it has.
        """
        parts: list[str] = []
        paid = self._paid_terms()
        if paid:
            parts.append("Pay " + " and ".join(paid))
        parts.extend(self._action_terms())
        label = " and ".join(parts) or f"Pay {mana_cost_label({})}"
        return label[0].upper() + label[1:]

    def payload(self) -> dict:
        """The cost as an ``OracleInstruction`` payload — and as the prompt
        carries it over the wire — writing only the parts that are asked for.

        So an ordinary mana upkeep's payload is exactly what it was before a
        cost was more than mana, and :func:`cost_from_payload` reads back what
        an older instruction wrote.
        """
        out: dict = {"mana": dict(self.mana)}
        if self.life:
            out["life"] = self.life
        if self.sacrifices:
            out["sacrifice"] = dict(self.sacrifice or {})
            out["sacrifices"] = self.sacrifices
        if self.exile_top_of_library:
            out["exile_top_of_library"] = self.exile_top_of_library
        if self.opponent_tokens:
            out["opponent_token"] = dict(self.opponent_token or {})
            out["opponent_tokens"] = self.opponent_tokens
        return out


def cost_from_payload(payload: dict) -> UpkeepCost:
    """The cost an instruction payload — or a prompt's ``cost`` key — names.

    The inverse of :meth:`UpkeepCost.payload`, and the *only* reader of those
    keys. A handler reaching for ``payload["mana"]`` itself would be a second
    reading, and one that cannot see the keys added when a cost stopped being
    only mana — which is how a life rider gets dropped twice.
    """
    return UpkeepCost(
        mana=dict(payload.get("mana") or {}),
        life=int(payload.get("life") or 0),
        sacrifice=payload.get("sacrifice"),
        sacrifices=int(payload.get("sacrifices") or 0),
        exile_top_of_library=int(payload.get("exile_top_of_library") or 0),
        opponent_token=payload.get("opponent_token"),
        opponent_tokens=int(payload.get("opponent_tokens") or 0),
    )


def cost_prompt_fields(cost: UpkeepCost) -> dict:
    """The keys a pay-or-consequence prompt carries a cost on: the payload the
    affordability pass reads back, and the two renderings the prompt shows.

    One place, because the prompt dicts are built by four different collectors
    (upkeep triggers, Paralyze-style Auras, Farmstead-style grants, Nafs Asp's
    draw-step obligation) and read back by two — the state view's affordability
    pass and the action that performs the payment. A collector spelling the
    keys itself is how one of them ends up carrying a cost the others cannot
    read.
    """
    return {
        "cost": cost.payload(),
        "cost_label": cost.describe(),
        "cost_pay_label": cost.pay_label(),
    }


#: A run of printed mana symbols and nothing else. The anchors are the whole
#: point: ``mana_cost_from_symbols`` scans, so a phrase has to be known to be
#: all symbols *before* it is handed over — see the module docstring.
_MANA_RUN = re.compile(r"^(?:\{[^}]*\})+$")

#: "2 life", one term of a payment.
_LIFE_TERM = re.compile(r"^(\d+) life$")

#: "sacrifice a land" — CR 702.24a's other Ice Age shape.
_SACRIFICE_PHRASE = re.compile(r"^sacrifice (?P<phrase>.+)$")

#: "exile the top card of your library" — CR 702.24a's Alliances shape (Thought
#: Lash). The count is delimited here and read by the number table, so a card
#: printing any other number is the same cost with different data. Read against
#: the same words `grammar/costs._accept_exile_top_of_library` admits, because
#: an upkeep and an activation printing one phrase must charge one thing.
_LIBRARY_EXILE_PHRASE = re.compile(
    r"^exile the top (?:(?P<count>\w+) cards|card) of your library$"
)


#: "have an opponent create a 1/1 red Survivor creature token" — CR 702.24a's
#: Alliances shape (Varchild's War-Riders). The clause after the wrapper is an
#: ordinary printed effect sentence and is read by **the grammar**, never by a
#: pattern here: "1/1 red Survivor creature token" already has one reader in
#: this engine, and a second one would be free to disagree with it about what a
#: Survivor is.
_OPPONENT_ACTION_PHRASE = re.compile(r"^have an opponent (?P<clause>.+)$")


def _opponent_token_cost(clause: str) -> UpkeepCost | None:
    """The cost "have an opponent <clause>" names, or None.

    Only a token creation today, and the narrowing is deliberate: what the
    payment does is *execute the lowered instruction*, so a clause lowering to
    anything the payment path has not been shown to be safe for — a draw, a
    sacrifice, a search — would be run against an opponent's seat by a function
    that never considered it. A wider clause refuses here and costs its card
    support, which is the loud direction.
    """
    from .grammar import compile_line

    compiled = compile_line(clause[0].upper() + clause[1:] + ".")
    if not compiled.usable or len(compiled.instructions) != 1:
        return None
    instruction = compiled.instructions[0]
    if instruction.kind != "create_token":
        return None
    payload = dict(instruction.payload)
    # The count is the cost's, because it is what escalates. A payload naming
    # its own recipient or reading its count off the board is a sentence this
    # wrapper cannot re-aim, so it refuses rather than paying something else.
    count = payload.pop("count", 1)
    if not isinstance(count, int) or count < 1:
        return None
    if payload.keys() & {"recipient", "recipient_players", "power_from", "toughness_from"}:
        return None
    return UpkeepCost(opponent_token=payload, opponent_tokens=count)


def upkeep_cost_from_phrase(phrase: str) -> UpkeepCost | None:
    """The cost a printed cost phrase names, or None when this engine cannot
    collect all of it.

    The whole phrase or nothing. "Pay X life" and "Pay {B}, discard a card" are
    both None today, and either refuses its card rather than shrinking its
    upkeep.
    """
    text = phrase.strip().rstrip(".").strip()
    if not text:
        return None
    opponent_action = _OPPONENT_ACTION_PHRASE.match(text)
    if opponent_action is not None:
        return _opponent_token_cost(opponent_action.group("clause"))
    library_exile = _LIBRARY_EXILE_PHRASE.match(text)
    if library_exile is not None:
        word = library_exile.group("count")
        if word is None:
            return UpkeepCost(exile_top_of_library=1)
        from .oracle_types import _NUMBER_WORDS

        count = int(word) if word.isdigit() else _NUMBER_WORDS.get(word, 0)
        return UpkeepCost(exile_top_of_library=count) if count >= 2 else None
    sacrifice = _SACRIFICE_PHRASE.match(text)
    if sacrifice is not None:
        described = _sacrifice_filter(sacrifice.group("phrase"))
        if described is None:
            return None
        return UpkeepCost(sacrifice=described, sacrifices=1)
    if text.startswith("pay "):
        text = text[len("pay "):]
    mana: dict[str, int] = {}
    life = 0
    for term in text.split(" and "):
        term = term.strip()
        if _MANA_RUN.match(term):
            symbols = mana_cost_from_symbols(term)
            if symbols is None:
                return None
            for symbol, amount in symbols.items():
                mana[symbol] = mana.get(symbol, 0) + amount
            continue
        life_term = _LIFE_TERM.match(term)
        if life_term is None:
            return None
        life += int(life_term.group(1))
    if not mana and not life:
        return None
    return UpkeepCost(mana=mana, life=life)


def _sacrifice_filter(phrase: str) -> dict | None:
    """What "Sacrifice <noun phrase>" may be paid with, or None when the payment
    path cannot collect it.

    The compiler's own reader, imported where it is called because the compiler
    reaches this module through ``cumulative_upkeep`` — ``engine/auras.py``
    reaches back into ``oracle`` the same way and for the same reason. Asking it
    rather than re-deriving the filter is what keeps this cost and an activation
    cost printing the same noun phrase from admitting different permanents.
    """
    from .oracle import _chargeable_sacrifice_filter

    return _chargeable_sacrifice_filter(phrase)


__all__ = [
    "UpkeepCost",
    "cost_from_payload",
    "cost_prompt_fields",
    "upkeep_cost_from_phrase",
]
