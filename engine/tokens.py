"""Token-card construction.

One place builds the CardDefinition for every creature token the engine
creates ("create a 1/1 colorless Insect artifact creature token named Wasp",
Arabian Nights' Rukh / Djinn tokens, …), so token-makers are one parse rule
emitting a ``create_token`` instruction — never a bespoke handler.
"""

from __future__ import annotations

from typing import Sequence

from .models import CardDefinition

# CR 111.7's flag, stamped into ``CardDefinition.raw`` rather than kept on the
# Permanent: a bounced or tucked token has no permanent left to ask, and the
# card is the only thing that arrives at the zone seam.
TOKEN_CARD_KEY = "is_token_card"

#: The resolution-scratchpad key a token maker writes the created token's
#: ``permanent_id`` under, and every "that token" back-reference reads back
#: ("Create Stangg Twin, a … token. **Exile that token** when …").
#:
#: Here rather than beside either reader because it has three: the lowering
#: gates the phrase on a token maker having produced it, the ``create_token``
#: handler writes it, and the handlers behind "exile that token" and "when that
#: token leaves the battlefield" read it. Three copies of a string is how they
#: come apart, and a token is a new object with a fresh id (CR 400.7), so there
#: is nothing about the token itself a later sentence could look it up by.
CREATED_TOKEN_RESULT_KEY = "created_token_permanent_id"

#: The metadata key a token maker stamps on the token it made, naming the
#: permanent that made it by ``permanent_id``.
#:
#: The *durable* half of the back-reference above: the scratchpad key answers
#: "which token did this resolution make" and dies with the resolution, while
#: this one answers "which permanent made this token" and lives as long as the
#: token does. Dance of Many needs the second — its "exile the token" and "when
#: the token leaves the battlefield" are separate abilities of the same
#: enchantment, fired turns after the resolution that created the token — and
#: Tetravus's "tokens created with this creature" is the same question asked of
#: several. By id rather than by identity because a permanent that leaves and
#: returns is a new object (CR 400.7) and its old tokens were not created with
#: *it*.
CREATED_WITH_PERMANENT_ID = "created_with_permanent_id"


def tokens_created_with(game, source) -> list:
    """The permanents on the battlefield *source* created, oldest first.

    The one reader of :data:`CREATED_WITH_PERMANENT_ID`, here rather than in
    either handler that asks because two of them do — Tetravus's counted exile
    and Dance of Many's "the token" — and they live in different modules.

    Ordered by id so "the token" is a stable answer rather than whatever the
    battlefield scan reached first, and read through the control seam because
    a raw battlefield walk is a second opinion about who controls what.
    """
    if source is None:
        return []
    return sorted(
        (
            perm for perm in game.all_permanents()
            if perm.metadata.get(CREATED_WITH_PERMANENT_ID) == source.permanent_id
        ),
        key=lambda perm: perm.permanent_id,
    )


def is_token_card(card: CardDefinition) -> bool:
    """Whether *card* is a token's stand-in card (CR 111.7).

    ``Permanent.metadata["is_token"]`` answers the same question while the
    token is on the battlefield; this answers it once the permanent is gone,
    which is what the hand/library seams have to test.
    """
    raw = getattr(card, "raw", None)
    return bool(raw.get(TOKEN_CARD_KEY, False)) if isinstance(raw, dict) else False


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


def token_line_supported(line: str) -> bool:
    """Whether the compiler implements *line* as a token's printed ability.

    Asked by building a throwaway token card and compiling it, rather than by
    handing the line to ``compile_line``: several of the abilities a token can
    carry are implemented by *text-keyed registries* — a combat restriction, an
    untap modifier — which produce no instruction at all and which
    ``compile_line`` therefore refuses. The support gate reads the same card the
    battlefield will, so what is admitted here is exactly what will work.
    """
    from .oracle import compile_card_oracle

    probe = make_token_card("Probe", 1, 1, "Creature — Probe", oracle_text=line)
    return compile_card_oracle(probe).supported


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
    raw: dict = {"name": name, "type_line": type_line, TOKEN_CARD_KEY: True}
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
