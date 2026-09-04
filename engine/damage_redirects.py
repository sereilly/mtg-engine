"""Damage *redirected* rather than prevented (CR 614.9), as state.

A prevention shield removes damage; a redirection effect moves it. The
difference is not cosmetic and it is not a detail of one card: the damage is
still dealt, in full, by the same source — so lifelink still gains from it
(CR 120.3f), "whenever ~ deals damage" still triggers on it, and the dealt-damage
records still see it. A redirect written as a shield plus a second damage event
would get every one of those numbers wrong in the same direction.

This module is what a redirect **is**; ``engine/replacements.py`` registers what
one **does** — the same split ``engine/shields.py`` and ``engine/prevention.py``
have, and for the same reason. Two card-specific redirects predate it (Jade
Monolith's ``redirect_damage_to_player`` metadata pair and Personal
Incarnation's charge counter), each a field named after the card that writes it;
this is the general record a new redirection card arms instead of a new field.

A redirect is a small closed set of facts, none of them a card name:

- **whose damage it catches** — the record lives on the recipient it watches,
  which CR 615.1's sibling wording makes a player *or* a permanent, so both
  models carry one exactly as they carry shields.
- **what it answers to** — ``source``: the one object whose damage moves
  (Shimian Night Stalker's targeted attacker, Nova Pentacle's "source of your
  choice"), or ``None`` for every source (Veteran Bodyguard's shape).
- **who takes it instead** — ``new_recipient``, again a player or a permanent.
- **how many times** — ``uses``: ``None`` for "all damage … this turn", 1 for
  "the next time …".
- **how long** — ``lifetime``, so the turn-step sweeps stay one generic call.

**Purity.** :func:`applicable_redirect` computes and :func:`DamageRedirect.spend`
mutates, because CR 616.1 counts the effects contending over an event before any
of them runs (see ``engine/effect_ordering.py``). A record that answered "do I
apply?" by spending itself would be used up on effects the player was only asked
about.

**CR 614.9 is a liveness rule, not a bookkeeping one.** If the object the damage
would move to has left the battlefield or stopped being a creature (or a
planeswalker, or a battle), or the player it would move to has left the game,
*the effect does nothing* — the damage is dealt to its original recipient as
though the redirect were not there. That is why the predicate asks
:func:`live_recipient` rather than merely whether a record exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .shields import END_OF_COMBAT, END_OF_TURN  # noqa: F401  (one duration vocabulary)


@dataclass
class DamageRedirect:
    """One CR 614.9 redirection sitting on the recipient whose damage it moves.

    new_recipient -- the player or permanent that takes the damage instead
    source        -- the one source whose damage this moves; None = any source
    uses          -- instances it can still move; None = every one, while it lasts
    lifetime      -- END_OF_COMBAT or END_OF_TURN
    source_name   -- the card that armed it, for the log
    """

    new_recipient: Any
    source: Any | None = None
    uses: int | None = None
    lifetime: str = END_OF_TURN
    source_name: str | None = None
    #: The printed noun phrase this record watches, as a filter payload, when it
    #: watches a **class** of recipients rather than the object it hangs off —
    #: "if damage would be dealt to **any creature**" (Blood of the Martyr). A
    #: class has no object to hang a record off, so such a record lives on the
    #: seat that *takes* the damage and is reached through
    #: :func:`class_redirects`; ``None`` is every other record, which is found by
    #: its recipient and answers to nothing else.
    recipients: dict | None = None
    #: CR 614's "you **may** have that damage dealt to you instead". The
    #: interceptor offers a ``ReplacementChoice`` rather than moving the damage,
    #: and the chooser is ``new_recipient``'s seat — the player whose card this
    #: is, not the one whose creature was about to be damaged.
    optional: bool = False
    #: The printed noun phrase naming the **sources** whose damage moves, as a
    #: filter payload — "…by **unblocked creatures** this turn" (Kjeldoran Royal
    #: Guard). ``source`` above is one chosen object matched by identity; this
    #: is a class, re-asked of each source when the damage would be dealt, so a
    #: creature that becomes unblocked after the ability resolved is covered and
    #: one that becomes blocked is not (CR 614.9 fixes nothing at arming time).
    #: ``None`` is every other record, which answers to ``source`` alone.
    sources: dict | None = None
    #: "All **combat** damage that would be dealt to you…". The printed word is
    #: a property of the *event* rather than of either end of it, which is why
    #: it is a flag here and a parameter of :func:`applicable_redirect` rather
    #: than something either matcher above could answer.
    combat_only: bool = False
    #: True while this record is being applied. A redirect deals the damage on
    #: to its new recipient as a fresh event, and that event runs the whole
    #: contention set again — so a pair of records pointing at each other would
    #: otherwise recurse forever. Set by the interceptor around the hand-off and
    #: read by the predicate, which stays pure: reading a flag is not spending.
    applying: bool = False
    #: "**The next 1 damage** that would be dealt to target white creature this
    #: turn is dealt to this creature instead." (Daughter of Autumn; Hazduhr the
    #: Abbot prints ``X``.) The points this record can still move — the exact
    #: twin of ``Shield.amount``, and spent the way CR 615.7 spends a numeric
    #: shield: each 1 damage moved reduces it by 1, and once it reaches 0 what
    #: is left of the event is dealt to the original recipient normally.
    #:
    #: ``None`` is every other record in the pool — "**all** damage that would
    #: be dealt …", which moves the whole event however large it is. The
    #: difference is not bookkeeping: a 1-point record read as a blanket one
    #: would move a Fireball's twelve.
    amount: int | None = None
    #: "The next time a source of your choice would deal damage this turn, that
    #: damage is dealt to that source's controller instead." (Reflect Damage.)
    #: The one printed shape that names **neither** end of the event: not the
    #: recipient it protects — it moves whatever the chosen source deals, to
    #: whoever would have taken it — and not the new recipient either, which is
    #: read off the source when the damage would be dealt.
    #:
    #: A record with no recipient has nothing of its own to hang off, exactly as
    #: a class-scoped one does not, so it lives on the seat that armed it and is
    #: reached by :func:`source_keyed_redirects` scanning every player. It is
    #: found by its ``source`` and by nothing else, which is why ``source`` is
    #: required alongside it — with neither a recipient nor a source it would
    #: move every point of damage in the game.
    any_recipient: bool = False
    #: "…is dealt to **that source's controller** instead." Who takes it cannot
    #: be known when the record is armed: CR 109.5's controller of a source is a
    #: live question, and a permanent can change hands between the arming and
    #: the damage. So the seat is derived at fire time from the damage's own
    #: source (``damage_events.damage_source_seat``, the one answer every event
    #: already carries) rather than frozen into ``new_recipient``.
    to_source_controller: bool = False

    @property
    def spent(self) -> bool:
        """Used up, so it no longer exists to be applied."""
        return (self.uses is not None and self.uses <= 0) or (
            self.amount is not None and self.amount <= 0
        )

    def moves(self, amount: int) -> int:
        """Points this record would take out of an event of *amount*.

        Pure — the half CR 616.1's applicability predicate is allowed to call,
        for the reason ``Shield.would_prevent`` is (see
        ``engine/effect_ordering.py``). A record with no pool moves the whole
        event, which is what every "all damage …" printing means.
        """
        if self.amount is None:
            return max(0, amount)
        return max(0, min(self.amount, amount))

    def spend(self, moved: int = 0) -> None:
        """Charge one instance, and *moved* points, against the record.

        The mutating half. Both counters are charged rather than one or the
        other, because ``uses`` and ``amount`` answer different printed
        sentences — "the next **time**" against "the next **N damage**" — and a
        record that carried both would have to satisfy both to keep applying.
        """
        if self.uses is not None:
            self.uses -= 1
        if self.amount is not None:
            self.amount -= moved


# ---------------------------------------------------------------------------
# The collection
# ---------------------------------------------------------------------------

#: Where the list hangs off a recipient. An attribute rather than a dataclass
#: field for the reason ``engine/shields.py`` uses one: a ``PlayerState`` and a
#: ``Permanent`` both carry it without either learning what a redirect is.
_REDIRECTS_ATTR = "_damage_redirects"


def redirects_on(recipient) -> list[DamageRedirect]:
    """The redirects watching *recipient*, created on first use."""
    records = getattr(recipient, _REDIRECTS_ATTR, None)
    if records is None:
        records = []
        setattr(recipient, _REDIRECTS_ATTR, records)
    return records


def add_redirect(recipient, redirect: DamageRedirect) -> DamageRedirect:
    """Put *redirect* on *recipient* and return it."""
    redirects_on(recipient).append(redirect)
    return redirect


def drop_spent(recipient) -> None:
    """Forget records that have been used up, so nothing reports a redirect that
    no longer exists."""
    records = redirects_on(recipient)
    records[:] = [r for r in records if not r.spent]


def clear_redirects(recipient, lifetime: str | None = None) -> None:
    """Expire records whose duration has run out.

    *lifetime* None clears every record (the cleanup step); naming one clears
    only records of that duration (the end of combat step) — the same shape as
    ``shields.clear_shields``, so a turn-step sweep stays one call.
    """
    records = redirects_on(recipient)
    records[:] = [r for r in records if lifetime is not None and r.lifetime != lifetime]


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def _is_permanent(obj) -> bool:
    """Duck-typed, so this module keeps importing nothing from the engine."""
    return getattr(obj, "permanent_id", None) is not None


def source_matches(chosen, source) -> bool:
    """Whether an incoming damage *source* is the one this record named.

    ``None`` matches any source: "all damage that would be dealt to you by
    unblocked creatures" names a class, not an object.

    **A chosen permanent matches by identity and nothing else.** ``Permanent``
    is a plain dataclass and two copies of one card share a single
    ``CardDefinition``, so comparing cards would move the damage of a *second*
    Serra Angel the player never pointed at — the same look-alike bug the
    control seam bans ``list.index`` for. A chosen *spell* has only its card to
    be known by (CR 109.5: a spell's source is the card as printed), so that
    comparison stays card-identity, and it is exactly why a spell cannot be
    told apart from a second copy of itself in the same deck.
    """
    if chosen is None:
        return True
    if source is None:
        return False
    if chosen is source:
        return True
    if _is_permanent(chosen) or _is_permanent(source):
        return False
    return getattr(chosen, "card", chosen) is getattr(source, "card", source)


def live_recipient(game, redirect: DamageRedirect, source=None):
    """The object *redirect* would move damage to, or None when CR 614.9 says
    the effect does nothing.

    A permanent must still be on the battlefield and still be one of the things
    damage can be redirected to; a player must still be in the game.

    *source* is the damage's own source, and only one record reads it: "…is
    dealt to **that source's controller** instead" (Reflect Damage) names a
    seat that has no value until there is an event to ask about. Derived
    through ``damage_events.damage_source_seat``, which is the answer
    ``deal_damage`` already puts on every event — a second derivation here
    would be a second answer to "who dealt this?".
    """
    if redirect.to_source_controller:
        from .damage_events import damage_source_seat

        seat = damage_source_seat(game, source)
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            return None
        player = game.players[seat]
        return None if getattr(player, "lost", False) else player
    target = redirect.new_recipient
    if target is None:
        return None
    if _is_permanent(target):
        if not game.is_on_battlefield(target):
            return None
        if not (target.is_creature or target.has_type("planeswalker") or target.has_type("battle")):
            return None
        return target
    return None if getattr(target, "lost", False) else target


def source_keyed_redirects(game) -> list[DamageRedirect]:
    """Every record that watches a **source** and no recipient at all.

    Reflect Damage — "The next time a source of your choice would deal damage
    this turn, that damage is dealt to that source's controller instead" — is
    the one printed shape with neither end of the event named, so nothing it
    protects can hold its record. It lives on the seat that armed it, which is
    the same home a class-scoped record uses (:func:`class_redirects`) and for
    the same reason: the objects it covers include ones that do not exist yet.

    Unlike that one it is found for **any** recipient, a player included, so it
    is its own scan rather than a widening of that function — which asks a noun
    phrase about a permanent and would answer True for every key it could not
    test if handed a player.

    Turn order from the active player is not asked for here: the scan is over
    the seats in table order, and ``applicable_redirect`` takes the first record
    whose source matches. Two such records over one event is a shape no card in
    the pool prints; when one does, it wants CR 616.1e's choice put to the
    affected player rather than this order reused.
    """
    return [
        record
        for player in game.players
        for record in redirects_on(player)
        if record.any_recipient
    ]


def resolving_object_redirects(game) -> list[DamageRedirect]:
    """The redirects hanging off the stack object whose instructions are running.

    Reverberation — "All damage that would be dealt this turn by target sorcery
    spell is dealt to that spell's controller instead" — is a redirect with no
    protected recipient at all: it moves whatever that *one spell* would deal, to
    whoever is damaged. So its record hangs off the spell, which is the same rule
    every other record follows (it lives on the object it watches), and it is
    reached through ``Game.resolving_items`` rather than by matching the damage's
    source.

    **That is the only way a spell can be recognised.** A spell's damage source
    is its printed ``CardDefinition`` (CR 109.5) — one object per *card*, handed
    out once per copy by the deck builder — so a record matching on the source
    would move a second copy's damage too, on a card that named one. A
    ``StackItem`` is one object per cast, and this seam is where it is knowable.

    Empty while a resolution waits on a prompt, so damage dealt after a
    CR 616.1e question was asked mid-resolution is outside this. The direction is
    the safe one — the damage lands where it would have without the redirect —
    and it is stated rather than hidden.
    """
    items = getattr(game, "resolving_items", None) or ()
    return redirects_on(items[-1]) if items else []


def class_redirects(game, recipient) -> list[DamageRedirect]:
    """The class-scoped records that watch *recipient*, oldest first.

    A record normally lives on the recipient it watches, which is what makes it
    findable at all. "If damage would be dealt to **any creature**" watches a
    printed noun phrase instead, and a phrase is not an object — the creatures
    it covers include ones that have not entered the battlefield yet, so there
    is nothing to hang it on and nothing to update when one arrives. So it lives
    on the seat that takes the damage instead, in the same collection, and is
    matched by asking the noun phrase about each damaged permanent.

    That also keeps the sweeps and the lifetimes exactly as they were: the
    cleanup step already calls :func:`clear_redirects` on every player.

    Only a permanent can be watched this way. Every printed class in this
    family names permanents ("any creature"), and a filter payload is a question
    about a permanent — asking it of a ``PlayerState`` would answer True for the
    empty filter and move every point of damage in the game.
    """
    if not _is_permanent(recipient):
        return []
    # Late, and inside the function, for the reason `_is_permanent` is duck
    # typed: this module is what a redirect *is*, and the matcher is a question
    # about the engine's objects. Importing it at module scope would put the
    # whole game model behind a file that otherwise needs none of it.
    from .subject_filters import subject_matches

    found: list[DamageRedirect] = []
    for player in game.players:
        for record in redirects_on(player):
            if record.recipients is None:
                continue
            if subject_matches(game, recipient, record.recipients):
                found.append(record)
    return found


def source_class_matches(game, redirect: DamageRedirect, source) -> bool:
    """Whether an incoming damage *source* is in the class this record watches.

    ``sources`` None is every source, exactly as :func:`source_matches`'s None
    is — a record that names no class narrows by nothing.

    Only a permanent can answer a printed noun phrase: a spell's source is its
    ``CardDefinition`` (CR 109.5), which has no battlefield state for the filter
    to read, and handing one to the matcher would answer True for every key it
    could not test. So a non-permanent source is outside every class-scoped
    record rather than inside all of them — the narrow direction, and the one a
    dropped narrowing would get wrong.
    """
    if redirect.sources is None:
        return True
    if not _is_permanent(source):
        return False
    from .subject_filters import subject_matches

    return subject_matches(game, source, redirect.sources)


def applicable_redirect(
    game, recipient, source, combat: bool = False
) -> DamageRedirect | None:
    """The record that would move this damage, or None. Pure.

    Oldest first, which is the order they were armed in: with two records
    watching one recipient CR 616.1 would let the affected player choose, and
    the *default* choice this makes is the earlier one. A second contending
    redirect on one recipient does not occur in this pool; when one does, it
    wants an order of its own in ``engine/replacements.py`` rather than a
    second reading here.

    *combat* is the event's own CR 510.2 flag, and the one fact about a damage
    event neither matcher above can be asked for — a record printed "all combat
    damage" declines every other kind rather than having the word dropped.
    """
    own = [
        r for r in redirects_on(recipient)
        if r.recipients is None and not r.any_recipient
    ]
    for redirect in (
        own + class_redirects(game, recipient) + resolving_object_redirects(game)
        + source_keyed_redirects(game)
    ):
        if redirect.spent or redirect.applying:
            continue
        if redirect.combat_only and not combat:
            continue
        if not source_matches(redirect.source, source):
            continue
        if not source_class_matches(game, redirect, source):
            continue
        if live_recipient(game, redirect, source) is None:
            continue
        # A record that would move the damage to the player it is already
        # being dealt to moves nothing (CR 614.9's effect "does nothing" when
        # its recipient is not there; here it *is* there and is the same
        # object). Left in, Reflect Damage aimed at a source whose controller
        # is the damaged player would re-run the event onto that same player —
        # `applying` stops the recursion, but the record would be spent on a
        # redirect that changed nothing.
        if live_recipient(game, redirect, source) is recipient:
            continue
        return redirect
    return None
