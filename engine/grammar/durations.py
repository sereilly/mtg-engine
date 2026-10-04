"""How long an effect lasts: the printed duration phrases, and their one reader.

CR 611.2a's question — a continuous effect "lasts as long as stated by the
spell or ability creating it", and one that states nothing lasts for the rest
of the game. `_DURATIONS` is every wording the pool states one in, each mapped
to a kind a lowering either has a sweep for or refuses by name, and
`_parse_duration` is the engine's only reader of the table: an absent phrase is
the kindless `ast.Duration()`, never a guessed "until end of turn".

Pre-split out of `phrases` at the Phase 0 before Invasion, when that module sat
38 lines under the thousand-line guard with every group's work about to reach
it — the shared-module case SET_PLAYBOOK.md says to pre-split rather than to
brief. The seam is one `phrases` had already been cut along three times: its
docstring opened by listing the word tables it held, "trigger events,
durations, counter kinds, board counts, zone names", and the trigger events
(`trigger_tables`), the board counts (`where_x`) and the counter kinds (a rule
in `engine/pt.py` now, not a table) had each left along that list. This was
the last table of any size on it, and it is the half that grows with the pool:
a set that prints a new window adds a row here and a paragraph saying which
moment it is, where the fragment productions left behind gain one only when a
second family asks for it.

A table plus a reader rather than a branch inside every production that prints
a duration, for the reason `phrases` gave while it held this: a table is a
thing a new card is added to, a branch is a thing that has to be found first.
**Order is part of the data.** `_parse_duration` takes the first row that
matches, so a phrase that is another's prefix ("this turn and next turn"
before "this turn") must sit above it; the rows say so where it matters.

Below `phrases`, which reads `_parse_duration` for two fragments of its own and
does **not** re-export it: every caller imports from here, because a re-export
is a hop nobody can grep for. It reads `ast`, the token stream and one name out
of `engine/turn_state.py`, and no other grammar module, so nothing can reach
back through it.

No mirror name to reuse. A duration has no lowering module of its own — each
family maps the kinds it has a sweep for (`lowering/keywords.py`,
`lowering/_counted_pumps.py`, `lowering/base_pt.py`, `lowering/phasing.py`) and
refuses the rest by name — and `ast.Duration` sits in `ast/_core.py` with the
rest of the shared vocabulary. The nearest word is `engine/event_durations.py`,
the sweep for the one row here that ends on an event instead of at a step: it
is keyed by this table's kinds, the same subject from the other end.
"""

from ..turn_state import THAT_PLAYERS_NEXT_TURN
from . import ast
from .stream import TokenStream


_DURATIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # "for as long as this artifact remains tapped" (Ashnod's Battle Gear,
    # Tawnos's Weaponry). A *linked* duration: it ends when the source untaps
    # or leaves, so nothing schedules its removal — the effect is contributed
    # while the condition holds and simply stops being contributed when it does
    # not, which is CR 611.3b's "removal is the absence of a contribution".
    # The noun is any permanent word, because the card printing it says what it
    # is and the duration does not care.
    ("while_source_tapped",
     ("for", "as", "long", "as", "this", "artifact", "remains", "tapped")),
    ("while_source_tapped",
     ("for", "as", "long", "as", "this", "creature", "remains", "tapped")),
    ("while_source_tapped",
     ("for", "as", "long", "as", "this", "permanent", "remains", "tapped")),
    # "for as long as this creature remains **on the battlefield**" (Stromgald
    # Spy). The other linked duration, and linked the same way: nothing
    # schedules its removal, because the effect is contributed while the source
    # is in the scan and simply stops being contributed when it is not
    # (CR 611.2b, and CR 400.7 makes a returning permanent a new object that
    # contributes nothing). Its own kind rather than the tapped one's: an
    # opponent who taps the source breaks that link and not this one.
    #
    # The value has been in the grammar since Scarwood Bandits, read inline by
    # the control-change production because it was the only sentence printing
    # the words. A second sentence now prints them, which is what moves the
    # phrase into the one duration table — and the entry makes it available to
    # every production, which is safe because a lowering handed a duration it
    # has no sweep for refuses by name rather than dropping the words.
    ("while_source_on_battlefield",
     ("for", "as", "long", "as", "this", "artifact", "remains", "on", "the",
      "battlefield")),
    ("while_source_on_battlefield",
     ("for", "as", "long", "as", "this", "creature", "remains", "on", "the",
      "battlefield")),
    ("while_source_on_battlefield",
     ("for", "as", "long", "as", "this", "permanent", "remains", "on", "the",
      "battlefield")),
    ("until_end_of_turn", ("until", "end", "of", "turn")),
    ("until_end_of_combat", ("until", "end", "of", "combat")),
    ("until_your_next_turn", ("until", "your", "next", "turn")),
    # "Until your next upkeep" (Xenic Poltergeist). Longer than its own prefix
    # is not the issue here — "until your next turn" and "until your next
    # upkeep" diverge at the last word — but they are different moments (CR 500:
    # the upkeep step is inside the turn), so they are different kinds and the
    # one nothing implements must not fall back to the one that is close.
    ("until_your_next_upkeep", ("until", "your", "next", "upkeep")),
    # "Until **the beginning of** your next upkeep" (Elkin Bottle). The same
    # moment spelled out, so the same kind: CR 500's upkeep step begins once,
    # and a second kind would be a second name for one instant. Longest-match
    # is not at risk against the entry below it — "beginning" and "end" diverge
    # on the third word.
    ("until_your_next_upkeep",
     ("until", "the", "beginning", "of", "your", "next", "upkeep")),
    # "Until the end of your next upkeep" (Halfdane). A step *later* than the
    # entry above: "until your next upkeep" ends as that upkeep begins, this
    # one ends as it ends — which is the whole trick of the card printing it,
    # whose own upkeep trigger re-applies the effect before the old one runs
    # out. Different moments, so different kinds, for the reason the comment
    # above gives about turns and upkeeps.
    ("until_end_of_your_next_upkeep",
     ("until", "the", "end", "of", "your", "next", "upkeep")),
    # "…until **its controller's next untap step**." (Orcish Farmer.) A moment
    # in someone else's turn, which is what separates it from every entry above:
    # the four "your next …" kinds all name a step of the seat the effect
    # belongs to, and this one names a step of whoever controls the *object*.
    # Read before "this turn" only by being longer; they share no prefix.
    # The possessive is two tokens: the lexer splits "controller's" into the
    # noun and the clitic, which is what `_parse_doesnt_untap_next_step` spells
    # out one family over.
    ("until_controllers_next_untap_step",
     ("until", "its", "controller", "'s", "next", "untap", "step")),
    # "**This turn and next turn**, creatures can't attack, and …" (Peace
    # Talks.) A duration spanning two turns, and its own kind rather than
    # "this turn" with a number beside it: every sweep in this engine ends an
    # effect at a cleanup step, and what this phrase says is *survive one of
    # them*. Reading it as "this turn" would end the effect a whole turn early
    # — the half of the card the opponent is paying for.
    #
    # Before "this turn", which is its own prefix: ``_parse_duration`` takes
    # the first row that matches, so the longer phrase has to be tried first or
    # the sentence would read as the shorter one and leave "and next turn"
    # unconsumed.
    ("this_turn_and_next_turn", ("this", "turn", "and", "next", "turn")),
    ("this_turn", ("this", "turn")),
    # "…until the end of **that** turn" (Giant Slug). Which turn "that" names
    # is not in the sentence: it comes from the delay the sentence sits inside
    # ("at the beginning of your next upkeep, …"). So it is its own kind, and
    # ``delayed.resolve_that_turn`` is the one place that turns it into an
    # ordinary end of turn — inside a delay, where "that turn" is the turn the
    # ability resolves in. Outside one nothing lowers it, which is the honest
    # answer: the phrase names a turn the reader cannot identify.
    ("until_end_of_that_turn", ("until", "the", "end", "of", "that", "turn")),
    # "…**until a player casts a creature spell**." (Soul Sculptor.) The first
    # duration in the pool that ends on an **event** rather than at a moment in
    # the turn structure (CR 611.2a's "as long as stated"), and the only entry
    # in this table whose
    # sweep is not a turn step: `engine/event_durations.py` hangs it off the
    # cast announcement, and a lowering handed this word refuses unless the
    # channel it would write has that sweep.
    #
    # No prefix relation with anything above it — every other "until" entry
    # diverges by the second word — so its position here is only where the
    # other spelled-out windows are.
    ("until_a_player_casts_a_creature_spell",
     ("until", "a", "player", "casts", "a", "creature", "spell")),
    # "**During that player's next turn,** the chosen creatures attack if able,
    # and other creatures can't attack." (Oracle en-Vec.) A window that opens on
    # a turn nobody is taking yet, and the only entry in this table printed in
    # the *leading* position on every card that has it — ``statements`` names
    # the opening word so the probe is reached, and ``_distribute_duration``
    # hands it to each effect behind the comma.
    #
    # "That player" is a seat an earlier sentence of the same effect recorded,
    # so the phrase names a turn the parser cannot identify and the *lowering*
    # is where it becomes one — exactly as ``until_end_of_that_turn`` above
    # names a turn only a delay can resolve. The name is
    # ``turn_state.THAT_PLAYERS_NEXT_TURN``, which the handlers read back.
    (THAT_PLAYERS_NEXT_TURN,
     ("during", "that", "player", "'s", "next", "turn")),
)


def _parse_duration(stream: TokenStream) -> ast.Duration:
    """Parse a trailing duration clause. Absent wording means permanent — one
    node replacing the fifteen places the legacy rules re-literalled these."""
    for kind, phrase in _DURATIONS:
        if stream.accept_phrase(*phrase):
            return ast.Duration(kind)
    return ast.Duration()
