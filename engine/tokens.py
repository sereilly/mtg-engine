"""Token-card construction.

One place builds the CardDefinition for every creature token the engine
creates ("create a 1/1 colorless Insect artifact creature token named Wasp",
Arabian Nights' Rukh / Djinn tokens, …), so token-makers are one parse rule
emitting a ``create_token`` instruction — never a bespoke handler.
"""

from __future__ import annotations

from typing import Sequence

from .models import CardDefinition


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
        if part.get("component") == "token" and part.get("name") == token_name:
            card_id = part.get("id")
            if not isinstance(card_id, str) or len(card_id) < 2:
                continue
            base = f"{card_id[0]}/{card_id[1]}/{card_id}.jpg"
            return {
                size: f"https://cards.scryfall.io/{size}/front/{base}"
                for size in ("small", "normal", "large", "art_crop", "border_crop")
            }
    return None


def make_token_card(
    name: str,
    power: int,
    toughness: int,
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
    raw: dict = {
        "name": name,
        "type_line": type_line,
        "power": str(power),
        "toughness": str(toughness),
    }
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
