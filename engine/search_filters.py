"""What a library/graveyard search may *find* — one predicate, three callers.

CR 701.23a: what a search may find is the *effect's* restriction, not the
searching player's preference. The same test therefore has to run in the three
places that would otherwise each guess: the engine when a seat answers the
prompt, the AI when it answers for itself, and the web layer when it decides
which cards to offer. A restriction only one of them knew about would be a
search that is legal in one seat and not in another — and a picker offering a
whole library while the card reports supported is exactly the failure
``_lower_search_library`` has been refusing cards to avoid.

The lowering refuses any restriction this module cannot test, so a filter that
reaches here is always one of these.
"""

from __future__ import annotations

import re

# The ``ObjectFilter`` fields ``search_matches`` understands, and the
# comparisons it can apply. ``_lower_search_library`` builds its honoured-field
# set from the first and validates against the second, so a field added here
# without a test — or a test added without the field — cannot drift apart:
# there is one copy and the lowering imports it.
SEARCH_RESTRICTIONS = frozenset(
    {"colors", "mana_value", "named", "named_among", "subtypes"}
)
SEARCH_COMPARISONS = frozenset({"eq", "ge", "gt", "le", "lt"})

_COMPARE = {
    "eq": lambda found, wanted: found == wanted,
    "ge": lambda found, wanted: found >= wanted,
    "gt": lambda found, wanted: found > wanted,
    "le": lambda found, wanted: found <= wanted,
    "lt": lambda found, wanted: found < wanted,
}


def card_has_type(card, wanted: str) -> bool:
    """Whether *card* has the card type *wanted* (CR 205.2).

    A card has **every** type its line names, so Ornithopter is an artifact card
    *and* a creature card. ``primary_type`` picks one of them by the order of a
    list, and three readers of this one question asked it that way: a search's
    "an artifact card" found no artifact creature, a counter's "target artifact
    spell" refused one, and only the graveyard reader had it right. One
    function, so the next reader cannot make it four.

    Containment in the printed type line rather than a parse of it: a card
    outside the battlefield has no computed characteristics at all (CR 613.1),
    so the line is the whole of what there is to ask.
    """
    return str(wanted).lower() in (getattr(card, "type_line", "") or "").lower()


def card_colors(card, *, game=None, owner=None) -> frozenset[str]:
    """The colours *card* is, as symbols (CR 105.1, CR 202.2).

    The printed colours, for the same reason :func:`card_has_type` reads the
    printed type line: a card in a library or a graveyard is not a permanent and
    has no computed characteristics (CR 613.1), so the card is normally the
    whole of what there is to ask.

    **Normally.** "The same is true for spells you control and nonland cards you
    own that aren't on the battlefield" (Celestial Dawn) is a colour a card in a
    library has that is not printed on it, and ``engine/object_colors.py`` is
    the one reader of that — this function, ``_stack_item_colors`` and
    ``handlers/_common`` all ask it, so a fourth reader cannot spell it a fourth
    way. A caller with no game or no seat gets the printed answer, which is what
    every caller got before the sentence existed.

    Deliberately **not** ``commander.color_identity``: CR 903.4 folds in every
    mana symbol in the rules text and the intrinsic ability of a basic land
    type, so a Badlands is a black-red *identity* and a colourless *card*.
    "A blue instant card" asks the second question.
    """
    from .object_colors import card_colors as effective_card_colors

    return frozenset(
        str(symbol).upper()
        for symbol in effective_card_colors(game, card, owner)
    )


def name_key(text: str) -> str:
    """A card name reduced to what two spellings of it agree on.

    The grammar hands the name over as the tokenizer left it: lower-cased, with
    the punctuation of "Chandra, Flame's Catalyst" split into its own tokens and
    rendered back with spaces. The card file spells it the way Oracle does.
    Comparing letters and digits alone is what makes those the same name without
    the parser having to reproduce Oracle's punctuation — which it cannot,
    because the comma inside a legendary name is the same token as the comma
    that ends the clause.
    """
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def search_matches(card, data: dict, *, game=None, owner=None) -> bool:
    """Whether *card* is a legal find for a search armed with *data*.

    *data* is the pending choice's own data — equally, the instruction payload:
    ``card_type`` plus the ``restrictions`` the lowering was able to honour.
    Missing keys mean "unrestricted", so a search armed by an older payload
    behaves exactly as it did.

    Also the predicate the **revealed-hand picker** answers with (Duress), for
    the reason in this module's docstring: a card-level restriction that only
    one of the engine, the AI and the web layer knew about would be a choice
    that is legal in one seat and not in another. ``exclude_types`` arrived with
    that caller — "a **noncreature, nonland** card" is the same question about
    the same card, asked with the answer inverted.
    """
    # "an **artifact or enchantment** card" (Enlightened Tutor), "an **instant
    # or sorcery** card" (Mystical Tutor). A printed union is an OR, the same
    # reading `any_colors` below already gets and the same one every noun-phrase
    # matcher in this engine gives a multi-type filter — so the key takes a
    # tuple as well as a word, and one member is enough. It used to take a word
    # alone and the lowering refused a union outright, which is the safe
    # direction and cost the three tutors their cards.
    card_type = data.get("card_type", "any")
    wanted_types = (
        card_type if isinstance(card_type, (list, tuple)) else (card_type,)
    )
    if "any" not in wanted_types and not any(
        card_has_type(card, name) for name in wanted_types
    ):
        return False
    type_line = card.type_line.lower()
    if any(excluded in type_line for excluded in data.get("exclude_types") or ()):
        return False
    restrictions = data.get("restrictions") or {}
    # "a **blue** instant card" (Merchant Scroll). A search may test a colour at
    # all for the reason it may test the type line: a card's colour is its mana
    # cost's (CR 202.2), printed on it, and needs no computed characteristic
    # that a card in a library does not have (CR 613.1).
    #
    # **OR'd, and the key says so.** A multi-colour ``ObjectFilter.colors``
    # means "a green **or** white creature" everywhere else in this engine —
    # ``ObjectFilter.to_payload`` emits exactly that case as ``any_colors`` and
    # every matcher reads it with ``any(...)``. AND'ing it here would give one
    # field two meanings depending on which reader asked, which is how the two
    # come to disagree about the same card; and it would be the *narrow*
    # disagreement, so a "white or blue" tutor would quietly find only gold
    # cards. The key is spelled ``any_colors`` rather than ``colors`` so the
    # name carries the semantics it already has one module over.
    wanted_colors = restrictions.get("any_colors") or ()
    if wanted_colors:
        colors = card_colors(card, game=game, owner=owner)
        if not any(str(symbol).upper() in colors for symbol in wanted_colors):
            return False
    # "a **basic** land card" (Cultivate). A supertype is printed on the type
    # line and needs no computed characteristic to read — which is the whole
    # test for what this predicate may honour, because a card in a library has
    # none (CR 613.1).
    for supertype in restrictions.get("supertypes") or ():
        if supertype not in type_line:
            return False
    # "a **Shrine** card" (Sanctum of All). Off the printed type line for the
    # same reason a supertype is: a card in a library or a graveyard has no
    # computed characteristics (CR 613.1), so the line is the whole of what
    # there is to ask. AND'd like the supertypes above — a phrase naming two
    # subtypes wants a card that is both, and the pool prints no search that
    # names an either/or.
    for subtype in restrictions.get("subtypes") or ():
        if subtype not in type_line:
            return False
    named = restrictions.get("named")
    if named is not None and name_key(card.name) != name_key(named):
        return False
    # "a card named Alpine Watchdog **and/or** a card named Igneous Cur"
    # (Alpine Houndmaster). Each find has its own name; this is the union the
    # *picker* offers, and which name each find actually consumed is settled by
    # the find flow, which drops the name it used. Without the union the picker
    # would offer only the first name and the second find could never be made.
    among = restrictions.get("named_among")
    if among and not any(name_key(card.name) == name_key(one) for one in among):
        return False
    mana_value = restrictions.get("mana_value")
    if mana_value is not None:
        compare = _COMPARE.get(mana_value["op"])
        if compare is None or not compare(card.cmc, mana_value["value"]):
            return False
    return True


def searched_seat(data: dict, chooser_seat: int) -> int:
    """**Whose** zone a search or a graveyard pick looks in.

    Almost always the seat answering the prompt, which is why this was a
    hard-coded ``choice.player_index`` in four places — but "whose zone" and
    "who chooses" are two questions, and Reincarnation prints them as two
    players: its controller picks the card (CR 608.2c) out of the graveyard of
    the creature's *owner*. A seat spelled into the code rather than carried as
    payload is exactly the narrowing this repo keeps finding dropped, so it is
    one default in one place and every reader asks it.
    """
    return int(data.get("zone_seat", chooser_seat))


def landing_seat(data: dict, chooser_seat: int) -> int:
    """**Whose** battlefield a find that goes there enters under.

    Its own question again: "put it onto the battlefield" defaults to the
    chooser's own side, and "under the control of that creature's owner" does
    not. CR 400.7 makes it a new object either way; which seat controls it is
    what this decides.
    """
    return int(data.get("battlefield_seat", searched_seat(data, chooser_seat)))
