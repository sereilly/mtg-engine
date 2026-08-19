"""What a library/graveyard search may *find* — one predicate, three callers.

CR 701.19a: what a search may find is the *effect's* restriction, not the
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
SEARCH_RESTRICTIONS = frozenset({"mana_value", "named", "subtypes"})
SEARCH_COMPARISONS = frozenset({"eq", "ge", "gt", "le", "lt"})

_COMPARE = {
    "eq": lambda found, wanted: found == wanted,
    "ge": lambda found, wanted: found >= wanted,
    "gt": lambda found, wanted: found > wanted,
    "le": lambda found, wanted: found <= wanted,
    "lt": lambda found, wanted: found < wanted,
}


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


def search_matches(card, data: dict) -> bool:
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
    card_type = data.get("card_type", "any")
    if card_type != "any" and card.primary_type != card_type:
        return False
    type_line = card.type_line.lower()
    if any(excluded in type_line for excluded in data.get("exclude_types") or ()):
        return False
    restrictions = data.get("restrictions") or {}
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
    mana_value = restrictions.get("mana_value")
    if mana_value is not None:
        compare = _COMPARE.get(mana_value["op"])
        if compare is None or not compare(card.cmc, mana_value["value"]):
            return False
    return True
