"""Which sentences of a printed ability are "Activate only …" restrictions,
one per rule (CR 602.5).

The clause is the *tail* of an ability line ("{1}{B}, {T}: Each opponent loses
2 life. Activate only if …"), a sentence may conjoin several rules ("…during
combat and only if defending player controls a snow land"), and a card may name
itself inside one ("…only if Hakim isn't enchanted"). :func:`_clauses` turns a
line into the list of single rules, :func:`_conjuncts` splits one sentence, and
:data:`_SELF_SUBJECT` is what a self-reference is collapsed to.

One reader with four askers, which is why it is a module of its own: the
restriction table's gate and enforcement (``engine/activation_restrictions.py``),
the activation caps (``engine/activation_tallies.py``), the support gate in
``engine/oracle.py`` and the grammar's rebuilt sentence
(``engine/grammar/activation_instructions.py``). A second splitter for any of
them would be free to disagree about where one rule stops.
"""

from __future__ import annotations

import re


#: Where one printed sentence stops being one restriction. "Activate only during
#: combat **and only** if defending player controls a snow land" and "Activate
#: only during the declare blockers step**, only** if at least one creature is
#: blocking this creature**, and only** once each turn" are lists, joined the
#: three ways English joins them. The lookahead is what keeps the comma in
#: "Activate only during an opponent's turn, before attackers are declared" from
#: being a separator: only a comma or "and" *followed by another "only"* opens a
#: new conjunct.
_CONJUNCTION = re.compile(r",?\s+and\s+(?=only\b)|,\s+(?=only\b)")


def _conjuncts(clause: str) -> list[str]:
    """One printed restriction sentence as the restrictions it conjoins.

    CR 602.5 puts no limit on how many restrictions a clause states, and the
    cards print them as one sentence: every conjunct is a rule of its own, and
    the activation is legal only when all of them are.

    This replaced an optional ``(?: and only once each turn)?`` tail on three
    rows -- one row per *pairing*, which is quadratic in the clauses that exist
    and left "Activate only if you have at least 7 life more than your starting
    life total and only as a sorcery" as a single row reading two rules under
    one name. A conjunct that no row reads leaves the whole clause unreadable,
    so a card cannot be admitted with half its sentence enforced.

    The verb travels to the tail: the conjuncts after the first are printed
    without it ("…and only if…"), and every pattern here is anchored on the
    sentence as it would be printed alone.

    **Punctuation is normalised here because two callers spell it differently.**
    `_clauses` splits the printed text and keeps "step, only"; the grammar
    rebuilds the sentence by joining its tokens and produces "step , only", the
    comma having been a token of its own. The rows are written the printed way,
    so a clause with a comma in it matched from one caller and not the other --
    latent until now only because Nettling Imp, the single shipped card printing
    one, is unsupported for reasons three sentences earlier.
    """
    cleaned = re.sub(r"\s+([,;])", r"\1", " ".join((clause or "").split()))
    parts = [part for part in _CONJUNCTION.split(cleaned) if part]
    if len(parts) < 2:
        return [cleaned] if cleaned else []
    verb = "activate " if parts[0].startswith("activate ") else ""
    return [parts[0]] + [verb + part for part in parts[1:]]


#: What a card naming itself inside a restriction clause is rewritten to.
#: "Activate only if **Hakim** isn't enchanted" and "…if **this creature** isn't
#: enchanted" are one sentence about one object (CR 201.5), so they are one row
#: here — the alternative is a row per printed name, which is a hook wearing a
#: regex. The noun is deliberately the generic one: every row that reads a
#: self-reference matches ``this [a-z]+``, because which noun a card calls
#: itself by says nothing about the rule.
_SELF_SUBJECT = "this permanent"


def _clauses(text: str, card_name: str | None = None) -> list[str]:
    """Every printed "Activate only ..." restriction in *text*, one per rule.

    Sentences rather than lines: the clause is the tail of an ability line
    ("{1}{B}, {T}: Each opponent loses 2 life. Activate only if ..."), so a
    line-level reader would never see it on its own.

    *card_name* collapses the card's own name to :data:`_SELF_SUBJECT` first.
    A card may refer to itself by name (CR 201.5) inside one of these clauses,
    and without the collapse the row would have to be written round the name —
    so the clause read as unknown, and the whole ability line was refused by the
    grammar's full-consumption invariant. Optional because the two callers that
    have no card in hand (a bare sentence from a test, the grammar's own
    reconstruction, which renders the SELF token itself) are asking about a
    sentence rather than about a card.
    """
    if card_name:
        from .self_reference import _collapse_self_references

        # Lowercased **before** the collapse, not after: the name forms
        # ``_self_name_forms`` produces are lowercase and the match is
        # case-sensitive, so a card's printed capital "Hakim" went straight
        # through and the clause reached the rows with the name still in it —
        # a restriction silently not enforced, which is the restriction
        # table's own failure mode. Every clause returned here is lowercased
        # anyway.
        text = _collapse_self_references(
            (text or "").lower(), card_name, _SELF_SUBJECT
        )
    found: list[str] = []
    for raw_line in (text or "").splitlines():
        for sentence in raw_line.split("."):
            # Quotation marks are stripped with the whitespace, because a
            # sentence boundary can fall immediately after a closing quote:
            # "…gains "Remove a matrix counter from this creature: Regenerate
            # this creature." **Activate only during your upkeep.**" (Life
            # Matrix) prints its full stop *inside* the quotes, so the split
            # leaves the next sentence starting with the quote character. Left
            # in, the clause matched nothing and the timing went unenforced --
            # which is ``activation_restrictions``' own opening paragraph, in the one shape
            # anchoring the pattern cannot catch.
            cleaned = sentence.strip().strip('"“”').strip().lower()
            # "Any player may activate this ability **but** only during any
            # upkeep step." (Armageddon Clock.) The permission and the timing
            # share a sentence, joined by "but"; the tail is the restriction and
            # the head is a different rule, checked elsewhere. Split rather than
            # matched loosely, so the clause is still anchored at both ends.
            if " but only " in cleaned:
                # …and the verb travels to the tail, exactly as `_conjuncts`
                # moves it across an "and". Every row of the table is anchored on the
                # clause **as it would be printed alone** ("activate only as a
                # sorcery"), and the split leaves the tail without its verb —
                # so rebuilding it verbless collected only the clauses whose row
                # happened to also admit that spelling. `only during any upkeep
                # step` is one, because Armageddon Clock's row was widened to
                # take both, and the collector below carries a matching special
                # case for it; every other tail fell out of this list entirely
                # and its restriction was **never enforced**. Scandalmonger's
                # "…but only as a sorcery" is the first card in the pool to
                # print a different tail.
                cleaned = "activate only " + cleaned.split(" but only ", 1)[1].strip()
            # "**Only** during any upkeep step" (Armageddon Clock) drops the
            # verb; every other printed clause keeps it. Both spellings are the
            # same kind of sentence, so both are collected.
            # By the **verb**, not by "activate only": "Activate no more than
            # twice each turn" (Vampire Bats) is the same kind of sentence and
            # the prefix test did not collect it, so neither the support gate
            # nor `activation_denial` ever saw it. Collecting it is what lets a
            # printed clause with no row in the table refuse its card instead of being
            # dropped.
            if cleaned.startswith("activate ") or cleaned.startswith("only during"):
                # Split here rather than at each of the three call sites: the
                # gate, the enforcement and the per-turn cap all want the same
                # list, and a sentence conjoining two rules is two entries in it.
                found.extend(_conjuncts(cleaned))
    return found
