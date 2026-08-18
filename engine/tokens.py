"""Token-card construction.

One place builds the CardDefinition for every creature token the engine
creates ("create a 1/1 colorless Insect artifact creature token named Wasp",
Arabian Nights' Rukh / Djinn tokens, …), so token-makers are one parse rule
emitting a ``create_token`` instruction — never a bespoke handler.
"""

from __future__ import annotations

from typing import Sequence

from .models import CardDefinition


def default_token_name(subtypes: Sequence[str]) -> str:
    """CR 111.4: an unnamed token's name is its subtype(s) plus "Token".

    "Create two 2/1 red Dwarf Berserker creature tokens" makes tokens named
    "Dwarf Berserker Token". The one naming rule for every token maker — the
    grammar's ``create_token`` lowering and the card hooks alike — so
    "creatures named …" effects read one spelling.
    """
    words = [part.capitalize() for subtype in subtypes for part in subtype.split()]
    return " ".join(words + ["Token"])


def token_image_uris(source_card: CardDefinition, token_name: str) -> dict[str, str] | None:
    """Resolve a token's Scryfall image URLs from its creating card's ``all_parts``.

    Scryfall image URLs are derivable from a card's id, so we only need the id
    that ``all_parts`` records for the token component — no network call. Returns
    None when the source card has no matching token part (e.g. minimal raw data).
    """
    raw = source_card.raw
    if not isinstance(raw, dict):
        return None
    for part in raw.get("all_parts") or ():
        if not isinstance(part, dict):
            continue
        # Scryfall names its token cards without the word "Token" ("Bird",
        # "Soldier"), while CR 111.4 names an unnamed token *with* it — so a
        # CR-named token finds its art by the suffix-stripped spelling too.
        part_name = part.get("name")
        if part.get("component") == "token" and part_name in (
            token_name,
            token_name.removesuffix(" Token"),
        ):
            card_id = part.get("id")
            if not isinstance(card_id, str) or len(card_id) < 2:
                continue
            base = f"{card_id[0]}/{card_id[1]}/{card_id}.jpg"
            return {
                size: f"https://cards.scryfall.io/{size}/front/{base}"
                for size in ("small", "normal", "large", "art_crop", "border_crop")
            }
    return None


#: Tokens Magic prints by name alone (CR 111.10). The card says "create a
#: Treasure token" and nothing else, because the characteristics are the
#: *token's* and not the card's — so they live here, once, rather than being
#: transcribed onto every card that makes one.
#:
#: Only Treasure so far, which is what the pool prints. A predefined token is a
#: standing definition, not a template with parameters, so each new one is an
#: entry and never a branch.
PREDEFINED_TOKENS: dict[str, dict] = {
    "treasure": {
        "name": "Treasure Token",
        "type_line": "Artifact — Treasure",
        "oracle_text": "{T}, Sacrifice this token: Add one mana of any color.",
        "colors": (),
    },
}


def make_token_card(
    name: str,
    power: int | None,
    toughness: int | None,
    type_line: str,
    *,
    colors: Sequence[str] = (),
    keywords: Sequence[str] = (),
    oracle_text: str | None = None,
    image_source: CardDefinition | None = None,
) -> CardDefinition:
    """A CardDefinition for a creature token.

    ``oracle_text`` defaults to the keyword list (so compiled programs grant
    the keywords). ``image_source`` is the card that created the token — its
    Scryfall ``all_parts`` data supplies the token art when available.
    """
    colors = tuple(colors)
    keywords = tuple(keywords)
    if oracle_text is None:
        oracle_text = "\n".join(keywords)
    raw: dict = {"name": name, "type_line": type_line}
    # A noncreature token (a Treasure) has no printed P/T at all, and "0" is not
    # the same answer as "none": stamped as 0/0 it would be a creature card with
    # lethal toughness the moment anything animated it, and CR 208.1 gives P/T
    # only to creatures in the first place.
    if power is not None:
        raw["power"] = str(power)
    if toughness is not None:
        raw["toughness"] = str(toughness)
    if image_source is not None:
        image_uris = token_image_uris(image_source, name)
        if image_uris is not None:
            raw["image_uris"] = image_uris
    return CardDefinition(
        name=name,
        mana_cost="",
        cmc=0.0,
        type_line=type_line,
        oracle_text=oracle_text,
        colors=colors,
        color_identity=colors,
        keywords=keywords,
        produced_mana=(),
        raw=raw,
    )
