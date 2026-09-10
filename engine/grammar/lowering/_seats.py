"""Which recipient key a printed player reference becomes, and what narrowing
it carries.

The two questions are one subject and they arrived a wave apart. A recipient
key says *which* seats a sentence acts on; a narrowing says which **of those**
it acts on, and both are read off the same ``ast.PlayerRef`` by lowerings that
otherwise share nothing. The stampers came down here from ``lowering/damage.py``
at the size guard, on the seam this module's own name draws.

A **floor**, not a family, for ``_amounts``' stated reason one file over: two
lowering families ask it -- ``game`` for CR 407's ante and ``life`` for
CR 119.5's "that player's life total becomes N" -- and a leaf several lowerings
read sits below the families however small it is. It arrived here at the split
that made ``life`` a family of its own, where it would otherwise have been one
family importing another or, worse, a second copy of a three-row table.

The table is closed and the miss raises. A seat this cannot name is one the
handler would have to guess at, and a guessed seat is an effect landing on
whichever player the resolution happened to be carrying -- which is the failure
every referent table in this package exists to refuse instead.
"""

from __future__ import annotations

from .. import ast
from ..errors import LoweringError
from ._common import player_deed_payload, testable_filter_payload


_ANTE_RECIPIENTS: dict[str, str] = {
    "you": "caster",
    "each_player": "each_player",
    "that_player": "that_player",
}


def _player_recipient(player: "ast.PlayerRef", node) -> str:
    """The recipient key *player* names, or a refusal naming the word."""
    recipient = _ANTE_RECIPIENTS.get(player.kind)
    if recipient is None:
        raise LoweringError(
            f"no seat is named by {player.kind!r} here", node=node
        )
    return recipient


def _stamp_recipient_deed(payload: dict, recipient, node) -> None:
    """"…deals 2 damage to **each player who sacrificed a Plains this way**."
    (Desolation.)

    The seat narrowing the recipient printed, carried to the handler that loops
    the seats. Its own two lines rather than a branch inside each arm because
    both seat-set recipients take it identically — what the clause narrows is
    *which of the loop's seats*, and the loop is the only difference between
    the two arms.

    ``player_deed_payload`` raises on a clause it cannot express, which is the
    behaviour this call wants: an unenforced narrowing is a card that damages
    every player, and a card that refuses to compile says so.
    """
    deed = player_deed_payload(recipient, node)
    if deed is not None:
        payload["recipient_did"] = deed

def _stamp_recipient_control(payload: dict, recipient, node) -> None:
    """"…to **each player who controls a white creature**." (Disorder.)

    The board narrowing the recipient printed, carried to the handler that
    loops the seats — the twin of :func:`_stamp_recipient_deed` beside it, and
    beside it for its reason: both seat-set recipients take it identically, and
    what the clause narrows is *which of the loop's seats*.

    Every key of the phrase must be one ``subject_matches`` can test, because a
    narrowing the matcher drops here is a card that damages every player at the
    table — the direction this whole family refuses in.
    """
    described = getattr(recipient, "controls", None)
    if described is None:
        return
    payload["recipient_controls"] = testable_filter_payload(
        described,
        refusal="the seat narrowing cannot test this restriction",
        node=node,
        require_narrowing=False,
    )


#: Moved here from ``lowering/attachments.py`` at Mercadian Masques' first wave,
#: when a second family needed it: "put a +1/+1 counter on target creature **of
#: defending player's choice**" (Erithizon) arms the same prompt Crashing Boars
#: does, and a family importing a family is what this floor exists to prevent.
#: A second copy of the table would have been worse than the import — the two
#: would answer differently the first time a row was added to one of them.
#: Which printed subjects a choice prompt can actually be aimed at. "That
#: creature's controller" is the seat the firing event named, which only an
#: event that froze one can answer — so the lowering names the word and the
#: handler resolves it, rather than either of them guessing a default.
_CHOOSER_SEATS = {
    "you": "you",
    "that_player": "event_subject_controller",
    "target_player": "target",
    # "**Target opponent** chooses any number of creatures they control."
    # (Oracle en-Vec.) The *announced* seat, not "whichever opponent is left":
    # the word "target" is CR 601.2c/602.2b, and the caster picks which player
    # is asked as the ability goes on the stack.
    #
    # This row read ``"opponent"`` — the same answer the untargeted phrase
    # below gets — with a note arguing that which of the two a sentence prints
    # "changes nothing about who is asked". In a duel it does not. At three
    # seats it is the whole of the choice, and ``picker_sweep`` says so
    # outright: an activated ability that prints "target" and derives no picker
    # is the Roots class. Nothing in the pool printed the phrase until now,
    # which is why the collapse survived.
    "target_opponent": "target",
    # "**Defending player** chooses an untapped creature they control."
    # (Crashing Boars.) CR 506.2's seat, which only a trigger that froze one can
    # answer: the ability resolves after the declare-attackers step, and a
    # combat with several defenders (CR 802) has a defending player *per
    # attacking creature* — so the seat is read out of the trigger's own
    # context, under the key every combat fire site already stamps, rather than
    # re-derived from a board the resolution has already changed.
    "defending_player": "trigger_defending_player",
    # "**An opponent** chooses target creature they control." (Echo Chamber.)
    # The row where the *chooser* is not announced: no "target opponent" here,
    # so ``_chooser_seat`` answers with the first live opponent rather than
    # reading a seat off the announcement, and it is this row's narrowing at
    # three seats, not the targeted row's above.
    #
    # **The rule it narrows is CR 602.3, and this comment used to name the wrong
    # one.** It read "the rules would have the *controller* choose (CR 601.2c
    # does not apply, so it is an ordinary choice made on resolution)". Both
    # halves are about a different sentence than the one printed here: the card
    # says an opponent chooses, and CR 602.3 is the rule that has room for
    # exactly that — "some abilities specify that one of their controller's
    # opponents does something the controller would normally do while it's being
    # activated, such as choose a mode or choose targets. In these cases, the
    # opponent does so when the ability's controller normally would do so." So
    # CR 601.2c *does* apply; 602.3 only moves who answers it.
    #
    # What is really narrowed here is **which** opponent: the ability's
    # controller chooses that, and this takes the first live one. What was
    # narrowed as well — and is now fixed — is that a printed "target" carries
    # CR 601.2c's legality with it, so the ability cannot be activated when the
    # chooser has nothing to choose (``legality._announced_choice_refusal``).
    # What is still narrowed is the *timing*: the pick happens as the ability
    # resolves rather than in its announcement, so nothing can be held in
    # response to it. ROADMAP.md carries that with what closing it needs.
    "opponent": "opponent",
}
