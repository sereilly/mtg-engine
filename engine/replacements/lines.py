"""Which printed lines this package implements, for the two readers that ask.

``replacement_claims_line`` is how the grammar's parse claim
(``engine/grammar/registries.py``) and the support gate
(``engine/derived_static_claims.py``) learn that a line is a CR 614 replacement
the engine carries out in full: an interceptor produces no instruction, so a
permanent whose only ability is one would otherwise claim nothing and report
unsupported however well the interceptor works.

The oracle phrases the interceptors self-select on are named constants rather
than inline literals for exactly this reader: it needs the *exact* string. A
copy here would be free to drift, and a drifted copy would claim a line nothing
implements — the silence the grammar's full-consumption invariant exists to
remove. So every phrase and every shape matcher below is imported from the
module whose interceptor reads it.

One table, ``REPLACEMENT_LINES``, in one module: split out of
``replacements.py`` at the 2,000-line cap's split round together with the
reader over it, because it imports from every interceptor module and none of
them may import it back.
"""

from __future__ import annotations

from .damage import (DAMAGE_LIFE_FLOOR_TEXT, any_source_damage_cap,
                     damage_life_floor_condition, damage_multiplier_line,
                     source_damage_cap, source_damage_delta)
from .damage_substitutions import (DAMAGE_BECOMES_GRAVEYARD_EXILE_TEXT,
                                   DAMAGE_BECOMES_LIBRARY_EXILE_TEXT,
                                   damage_becomes_counters,
                                   damage_to_you_becomes_counters)
from .draws import (DISCARD_INSTEAD_OF_DRAW_TEXT, DOUBLE_DRAW_TEXT,
                    LIFE_GAIN_TO_DRAW_TEXT,
                    RETURN_FROM_GRAVEYARD_INSTEAD_OF_DRAW_TEXT, SKIP_DRAW_TEXT,
                    draw_becomes_counter)
from .permanents import (EXILE_UNCAST_CREATURE_TEXT, EXTRA_PLUS1_COUNTER_TEXT,
                         LANDS_CANT_ENTER_TEXT, LAND_EQUILIBRIUM_TEXT,
                         counters_instead_of_untap)
from .redirects import (chosen_color_spell_redirect,
                        redirect_to_self_source_class)
from .revealed_draws import (REVEALED_DRAW_TAXED_TEXT,
                             REVEAL_DRAW_UNLESS_PAID_TEXT,
                             REVEAL_TOP_INSTEAD_OF_DRAW_TEXT,
                             REVEAL_UNTIL_KIND_TEXT)
from .zone_changes import (RETURN_TO_HAND_INSTEAD_TEXT,
                           TOP_OF_LIBRARY_DISCARD_TEXT,
                           TOP_OF_LIBRARY_INSTEAD_OF_DYING,
                           discard_to_battlefield, graveyard_exile_scope,
                           graveyard_shuffle_subject)


#: Each entry is ``(the phrase an interceptor of this package self-selects on, the
#: trailing clause that same interceptor also performs)``. The tail is spelled
#: out in full rather than left as an open-ended "and whatever follows" — it is
#: the one place an entry could otherwise claim text nothing implements.
#:
#: **Both readers ask here rather than keeping their own copy.**
#: ``engine/grammar/registries.py`` asks to account for the line's *parse*:
#: nothing the grammar could lower would run these, because the interceptor
#: already does, from the card's text, on every relevant event.
#: The support gates (``static_line_support``, ``derived_static_claims``)
#: ask to account for the card's *support* — and until this round they did
#: not. They asked the other six
#: text-keyed tables (untap restrictions, land plays, global statics, draw-step
#: bonuses, cost modifiers, entry effects) and not the CR 614 one, so a
#: permanent whose *only* ability is a replacement effect produced no
#: instruction, claimed nothing, and reported unsupported however well the
#: interceptor worked. Every card in the pool that reaches an interceptor here
#: happened to print a second, readable line — Lich, Ali from Cairo, Library of
#: Leng, Conclave Mentor all do — so the gap had no card behind it until Fiery
#: Emancipation, whose whole text is one replacement.
#:
#: A list in either caller would be free to drift from the interceptors. Here it
#: cannot: the phrases *are* the constants the interceptors probe for.
REPLACEMENT_LINES: tuple[tuple[str, str], ...] = (
    # _draw_instead_of_life_gain (Lich): the phrase is the whole line.
    (LIFE_GAIN_TO_DRAW_TEXT, ""),
    # _floor_life_at_one (Ali from Cairo): the phrase is the whole line.
    # Worship prints the same sentence behind "if you control a creature," and
    # is matched by shape below rather than listed here, because the condition
    # is payload.
    (DAMAGE_LIFE_FLOOR_TEXT, ""),
    # _top_of_library_instead_of_graveyard (Library of Leng). The constant the
    # interceptor probes for stops at "...on top of your library instead"; the
    # ReplacementChoice it raises offers exactly the two destinations the tail
    # names ("top of library", "graveyard"), so the interceptor implements the
    # tail as well.
    (TOP_OF_LIBRARY_DISCARD_TEXT, " of into your graveyard"),
    # _one_more_plus1_counter (Conclave Mentor): the phrase is the whole line,
    # matched against the counter-placing seam in mixins/effects.py.
    (EXTRA_PLUS1_COUNTER_TEXT, ""),
    # _damage_becomes_library_exile (Crumbling Sanctuary): the phrase is the
    # whole line, and the interceptor performs the whole of it — the exile, and
    # the damage not being dealt.
    (DAMAGE_BECOMES_LIBRARY_EXILE_TEXT, ""),
    # _draw_two_cards_instead (Teferi's Ageless Insight): the phrase is the whole
    # line, rider included — the exemption is implemented, not ignored, so the
    # claim covers the words that state it.
    (DOUBLE_DRAW_TEXT, ""),
    # _exile_instead_of_entering (Containment Priest): the phrase is the whole
    # line, and every clause of it — nontoken, creature, not cast — is a clause
    # of the applicability predicate rather than an approximation of one.
    (EXILE_UNCAST_CREATURE_TEXT, ""),
    # _discard_instead_of_drawing (Chains of Mephistopheles): the constant is
    # all three printed sentences, because the interceptor performs all three —
    # the discard, the draw behind a discard that happened, and the mill behind
    # one that could not. A claim stopping at the first sentence would be a
    # rider claimed and not executed.
    (DISCARD_INSTEAD_OF_DRAW_TEXT, ""),
    # _top_of_library_instead_of_dying (Gravebane Zombie): the phrase is the
    # whole line, and the interceptor performs the whole of it — one destination
    # and no rider.
    (TOP_OF_LIBRARY_INSTEAD_OF_DYING, ""),
    # _return_to_hand_instead_of_dying (Firestorm Phoenix): the constant is both
    # printed sentences, because the interceptor performs both — the return and
    # the reveal-and-lock rider behind it (engine/hand_locks.py). A claim
    # stopping at the first sentence would admit the card with half its text
    # doing nothing.
    (RETURN_TO_HAND_INSTEAD_TEXT, ""),
    # _reveal_top_instead_of_drawing (Enduring Renewal): the constant is all
    # three printed sentences, because the interceptor performs all three — the
    # reveal, the graveyard for a creature card and the draw for anything else.
    (REVEAL_TOP_INSTEAD_OF_DRAW_TEXT, ""),
    # _reveal_until_kind_instead_of_drawing (Abundance): the constant is both
    # printed sentences, because the interceptor performs both — the choice and
    # the reveal-until, and the two destinations the second sentence names. A
    # claim stopping at the first would admit a card that reveals its library
    # and then puts nothing anywhere.
    (REVEAL_UNTIL_KIND_TEXT, ""),
    # _revealed_draw_taxed (Breathstealer's Crypt): the constant is both printed
    # sentences, because the interceptor performs both — the draw-and-reveal and
    # the pay-or-discard offer behind a creature card. A claim stopping at the
    # first sentence would admit a card whose whole effect is the second.
    (REVEALED_DRAW_TAXED_TEXT, ""),
    # _reveal_draw_unless_paid (Zur's Weirding): the constant is all four
    # printed sentences, because the interceptor performs all four — the reveal,
    # the offer to every other player in turn order, the graveyard behind a
    # payment and the draw behind none.
    (REVEAL_DRAW_UNLESS_PAID_TEXT, ""),
    # _lands_cannot_enter (Worms of the Earth): the phrase is the whole line,
    # and every land entering from anywhere is refused — the interceptor tests
    # the type through layer 4 rather than the printed one, so the claim covers
    # exactly what the sentence says.
    (LANDS_CANT_ENTER_TEXT, ""),
    # _sacrifice_after_entering (Land Equilibrium): the constant is the whole
    # sentence, "then sacrifices a land of their choice" included — the entry
    # is let through and the sacrifice is armed once the land is on the
    # battlefield, which is what "then" says.
    (LAND_EQUILIBRIUM_TEXT, ""),
    # _return_from_graveyard_instead_of_drawing (Forbidden Crypt): the constant
    # is both printed sentences, because the interceptor performs both — the
    # return, and CR 104.3e behind a graveyard with nothing in it. A claim
    # stopping at the first sentence would admit the card with the clause that
    # makes it a real card doing nothing.
    (RETURN_FROM_GRAVEYARD_INSTEAD_OF_DRAW_TEXT, ""),
    # _skip_instead_of_drawing (Obstinate Familiar): the phrase is the whole
    # line. The offer and both of its answers are the interceptor's.
    (SKIP_DRAW_TEXT, ""),
    # _damage_becomes_graveyard_exile (Nefarious Lich): the constant is both
    # printed sentences, because the interceptor performs both — the exile,
    # and CR 104.3e behind a graveyard that cannot pay.
    (DAMAGE_BECOMES_GRAVEYARD_EXILE_TEXT, ""),
)


def replacement_claims_line(line: str) -> bool:
    """Whether one printed line is, in full, a replacement effect implemented
    in this package.

    The reduction matches what the interceptors really see: they probe the
    card's lowercased oracle text, and a line differs from it only by its
    trailing full stop.
    """
    normalized = line.strip().lower().rstrip(".")
    if any(normalized == phrase + tail for phrase, tail in REPLACEMENT_LINES):
        return True
    # "**If you control a creature,** damage that would reduce your life total
    # to less than 1 reduces it to 1 instead." (Worship.) Matched by shape
    # rather than listed as a constant, because the condition is payload — and
    # asked of the same reader the interceptor uses, so a noun phrase it cannot
    # read leaves the line unclaimed rather than admitted with the condition
    # silently dropped.
    if damage_life_floor_condition(normalized) is not None:
        return True
    # "As long as this creature is untapped, all damage … is dealt to this
    # creature instead" (Veteran Bodyguard, Martyrs of Korlis). Matched by
    # shape rather than listed as a constant, because the source class is
    # payload — and asked of the same reader the interceptor uses, so a class
    # it cannot answer leaves the line unclaimed rather than admitted with the
    # redirect silently not firing.
    if redirect_to_self_source_class(normalized) is not None:
        return True
    # "If a source [you control] would deal damage to a permanent or player, it
    # deals double/triple that damage to that permanent or player instead."
    # (Furnace of Rath, Fiery Emancipation.) Matched by shape rather than listed
    # as a constant, because the factor and the narrowing are payload — and this
    # is the entry that made the support gate's omission of this whole table
    # visible, since Fiery Emancipation prints nothing else.
    if damage_multiplier_line(normalized) is not None:
        return True
    # "If a permanent with a wind counter on it would untap during its
    # controller's untap step, remove all wind counters from it instead."
    # (Freyalise's Winds), matched by shape because the counter word is payload.
    if counters_instead_of_untap(normalized) is not None:
        return True
    # "If you would draw a card, you may put a study counter on this enchantment
    # instead." (Pursuit of Knowledge.) Matched by shape because the counter
    # word and the card's own noun are payload - through the same reader the
    # interceptor self-selects on, so a wording it cannot read leaves the line
    # unclaimed rather than admitted with the substitution silently absent.
    if draw_becomes_counter(normalized) is not None:
        return True
    # "If damage would be dealt to this creature, put that many -1/-1 counters
    # on it instead." (Lichenthrope), matched by shape because the counter kind
    # is payload — Phytohydra prints the same sentence with +1/+1 — and asked
    # of the same reader the interceptor uses, so a kind it cannot read leaves
    # the line unclaimed rather than admitted with no counters arriving.
    if damage_becomes_counters(normalized) is not None:
        return True
    # "If damage would be dealt to you, put that many delay counters on this
    # enchantment instead." (Delaying Shield), the same arrangement: the
    # counter word and the card's own noun are payload.
    if damage_to_you_becomes_counters(normalized) is not None:
        return True
    # "If an instant or sorcery source would deal 3 or more damage to you…"
    # (Forethought Amulet), the same arrangement for the same reason.
    if source_damage_cap(normalized) is not None:
        return True
    # "If an instant or sorcery spell of the chosen color would deal damage to
    # you, it deals that damage to its controller instead." (Harsh Judgment.)
    # The same arrangement again: the spell types are payload, and the reader
    # asked is the one ``damage_redirects`` derives the redirect from.
    if chosen_color_spell_redirect(normalized) is not None:
        return True
    # "If a source would deal 4 or more damage to a permanent or player, that
    # source deals 3 damage to that permanent or player instead." (Divine
    # Presence.) The same cap with neither narrowing, claimed through the
    # reader the same interceptor asks.
    if any_source_damage_cap(normalized) is not None:
        return True
    # "If a spell would deal damage to a permanent or player, it deals that much
    # damage minus 1 …" (Benevolent Unicorn) / "…plus 1…" for a red spell
    # (Sulfuric Vapors), the same arrangement again — the source class, the
    # direction and the number of points are payload.
    if source_damage_delta(normalized) is not None:
        return True
    # "If a land is tapped for mana, it produces {B} instead of any other
    # type." (Infernal Darkness, Ritual of Subdual.) "If tapped for mana,
    # Plains produce {R}, …" (Naked Singularity, Reality Twist.) Matched by
    # shape for the reason the three above are: the land type and the symbol
    # are payload, and how many clauses the sentence lists is what separates
    # the two cards printing the second spelling. Asked of the same reader
    # ``_substitute_land_mana`` reaches, so a clause it cannot read leaves the
    # line unclaimed rather than admitted with the substitution not firing.
    # "If a card would be put into your graveyard from anywhere, exile that card
    # instead." (Forbidden Crypt.) Matched by shape for the reason the four
    # above are: whose graveyard is payload, and it is asked of the same reader
    # the interceptor uses, so a scope word it cannot answer leaves the line
    # unclaimed rather than admitted with nothing exiled.
    if graveyard_exile_scope(normalized) is not None:
        return True
    # "If a spell or ability an opponent controls causes you to discard this
    # card, put it onto the battlefield with two +1/+1 counters on it instead of
    # putting it into your graveyard." (Dodecapod.) Matched by shape because
    # the counters are payload — and absent on the cards that print the
    # sentence without them — through the reader the interceptor itself asks.
    if discard_to_battlefield(normalized) is not None:
        return True
    # "If Legacy Weapon would be put into a graveyard from anywhere, reveal
    # Legacy Weapon and shuffle it into its owner's library instead." Matched by
    # shape because the subject is the card's own name, asked of the reader the
    # interceptor self-selects on.
    if graveyard_shuffle_subject(normalized) is not None:
        return True
    from ..land_mana_swaps import substitution_line

    return substitution_line(normalized) is not None
