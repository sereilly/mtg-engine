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
    #: True while this record is being applied. A redirect deals the damage on
    #: to its new recipient as a fresh event, and that event runs the whole
    #: contention set again — so a pair of records pointing at each other would
    #: otherwise recurse forever. Set by the interceptor around the hand-off and
    #: read by the predicate, which stays pure: reading a flag is not spending.
    applying: bool = False

    @property
    def spent(self) -> bool:
        """Used up, so it no longer exists to be applied."""
        return self.uses is not None and self.uses <= 0

    def spend(self) -> None:
        """Charge one instance against the record. The mutating half."""
        if self.uses is not None:
            self.uses -= 1


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


def live_recipient(game, redirect: DamageRedirect):
    """The object *redirect* would move damage to, or None when CR 614.9 says
    the effect does nothing.

    A permanent must still be on the battlefield and still be one of the things
    damage can be redirected to; a player must still be in the game.
    """
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


def applicable_redirect(game, recipient, source) -> DamageRedirect | None:
    """The record that would move this damage, or None. Pure.

    Oldest first, which is the order they were armed in: with two records
    watching one recipient CR 616.1 would let the affected player choose, and
    the *default* choice this makes is the earlier one. A second contending
    redirect on one recipient does not occur in this pool; when one does, it
    wants an order of its own in ``engine/replacements.py`` rather than a
    second reading here.
    """
    for redirect in list(redirects_on(recipient)) + resolving_object_redirects(game):
        if redirect.spent or redirect.applying:
            continue
        if not source_matches(redirect.source, source):
            continue
        if live_recipient(game, redirect) is None:
            continue
        return redirect
    return None
