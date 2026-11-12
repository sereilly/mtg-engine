"""Engine object to client JSON, one function per kind of object.

The leaves of the state payload: cards, permanents, counters, modal modes,
stack items. Characteristics are read through the engine's layer accessors
rather than off the printed card, so a granted keyword or a switched P/T shows
up here the way the rules say it should.

A player — one seat's zones, as one viewer is shown them — is built out of
these leaves in :mod:`web.player_view`, the layer above. Assembling a *whole*
state payload lives in :mod:`web.state_view`, further up — it needs the
pregame, turn-step and combat modules, which need these leaves.
"""

from __future__ import annotations

import re

from engine import Game
from engine.activation_permissions import card_widens_activation
from engine.color_changes import spell_color_change
from engine.divided_damage import DIVIDED_TARGETS, divided_entry
from engine.entry_choices import chosen_as_entered
from engine.face_down import face_up_morph_cost, hidden_card_of, is_face_down
from engine.faces import combined_oracle_text, face_cards, is_face, whole_card
from engine.game_types import single_slot, target_ids, target_slots
from engine.granted_abilities import GRANTER_PHRASE_HEAD, GRANTER_PHRASE_TAIL
from engine.models import Permanent
from engine.layer_bridge import displayed_type_line
from engine.mana_combination import cast_split_offer
from engine.mana_payment import taps_for_payment
from engine.object_colors import card_colors
from engine.line_classification import LOYALTY_ANY_TIME_STATIC
from engine.oracle import compile_card_oracle
from engine.keywords import abilities_lost_at, derived_ability_lines
from engine.targeting import derive_cast_spec
from engine.target_roles import recorded_role_seats
from engine.text_changes import changed_words, spell_text_card

from .offers import _offered_mana, cast_mana_offer, cast_x_payable, tap_mana_split, text_change_offer
from .runtime import CARD_BY_NAME


# Keywords surfaced on battlefield cards and the card preview. Order here is the
# order they render in. Passed through the engine's keyword logic so granted
# keywords (auras, "until end of turn" pumps) appear and removed ones disappear.
_DISPLAY_KEYWORDS = (
    "Flying", "First Strike", "Double Strike", "Trample", "Deathtouch",
    "Reach", "Vigilance", "Haste", "Defender", "Banding", "Fear",
    "Lifelink", "Shroud", "Protection", "Rampage", "Flanking",
    "Plainswalk", "Islandwalk", "Swampwalk", "Mountainwalk", "Forestwalk",
    # Flash is deliberately absent: it is a permission about casting from
    # hand (CR 702.8b), not a battlefield ability worth a badge.
    "Menace", "Hexproof", "Prowess",
    "Shadow", "Phasing", "Desertwalk",
    # CR 702.39: an attack trigger, line-derived so a granted one (Hunter
    # Sliver) folds in too — the badge says the creature can drag a blocker
    # in, which nothing else on the permanent shows once the reminder is gone.
    "Provoke",
)

#: The implemented keywords this row deliberately does **not** badge, each with
#: the reason. Named rather than merely absent, because the list above is
#: hand-ordered and went stale the moment a keyword was added: shadow shipped
#: with 25 creatures whose whole evasion the player could not see, and phasing
#: and desertwalk had been missing since Mirage and Arabian Nights.
#: `tests/ui/test_serialization_keywords.py` holds the two sets together, so an
#: implemented keyword must be badged or excused here.
_NOT_BADGED = {
    # A permission about casting from hand, not a battlefield ability.
    "flash",
    # Appended separately below, because it is derived from the layer rather
    # than read off the keyword.
    "indestructible",
    # The generic name of the family whose five members are badged above; no
    # card prints the bare word.
    "landwalk",
    # Parameterised the way protection is ("bands with other Legends"), so a
    # bare badge would say less than the card does. Spelled out in the oracle
    # text the client already shows.
    "bands with other",
}

#: The badged keywords CR defines over a **permanent**, not over a creature.
#: Phasing is CR 702.26, shroud CR 702.18a, hexproof CR 702.11a and protection
#: CR 702.16a, and every one of those sentences says "permanent or player" or
#: "permanent" — so an artifact, a land or an enchantment can carry them and a
#: player looking at the card has to be told.
#:
#: This set is the answer to a question `_NONCREATURE_KEYWORDS` used to answer
#: by being one hand-written entry long. It said "Phasing" because Teferi's Isle
#: was the card that had asked, and the three beside it went unbadged: **Nine
#: Lives**, whose entire protective text is "Hexproof", reached the client with
#: no badge at all, and a Mox under **Hanna's Custody** ("All artifacts have
#: shroud") reached it the same way — the engine holding both shields at every
#: seam it owns. That is Yavimaya Scion's defect one card type over.
_ANY_PERMANENT_KEYWORDS = frozenset({"Phasing", "Shroud", "Hexproof", "Protection"})

#: The badges a **noncreature** permanent can carry, in the render order above.
#: Derived rather than written out, so a keyword added to ``_DISPLAY_KEYWORDS``
#: cannot be badged on creatures and silently missed everywhere else — which is
#: how the single-entry version went stale. Indestructible is appended
#: separately (it is derived from the layer, not read off the keyword) and
#: Protection is spelled out with its qualities below, so it is filtered out of
#: the plain list on both paths.
_NONCREATURE_KEYWORDS = tuple(kw for kw in _DISPLAY_KEYWORDS if kw in _ANY_PERMANENT_KEYWORDS)

# Color symbol → display word, for spelling out protection qualities on the card.
_SYMBOL_TO_COLOR_WORD = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}


def _effective_keywords(perm: Permanent, game: Game) -> list[str]:
    """The keywords a permanent currently has, reflecting grants and removals.

    Each candidate is resolved through ``game._has_keyword`` so aura-granted and
    "until end of turn" keywords show up, and Layer 6 removal effects (e.g.
    Earthbind stripping Flying) take it back off.

    The combat keywords are creature-only, but Indestructible is not: Guardian
    Beast grants it to noncreature artifacts and Consecrate Land to a land, and
    a player can't see that it applies unless the card says so. **Phasing is the
    second of those** (CR 702.26 is about a permanent, not a creature) — Teferi's
    Isle is a land and phases, and the badge said nothing about it from Mirage
    until Tempest's promotion smoke test asked. Shroud, hexproof and protection
    are the rest of that family (:data:`_ANY_PERMANENT_KEYWORDS`), and they were
    added by asking the CR what each keyword is *about* rather than by waiting
    for the next card to be found unbadged.

    Whether the permanent *is* a creature is asked of the layers rather than of
    the printed type line: an animated land is a creature and its keywords are
    real (Stalking Stones becomes a 3/3 that is still a land). Reading
    ``card.type_line`` here was the second answer to a question
    ``engine/continuous.py`` already owns — the class
    ``tests/engine/test_layer_reads.py`` guards, which scans ``engine/`` and so
    never saw this one.

    "Protection" is spelled out with the quality it's from (e.g. "Protection
    from white") so the player can see which color the permanent is protected
    against, not just that it has protection.
    """
    # One list and one set of appends for both shapes. It used to be two
    # branches with an early return, and the early return is what hid the
    # protection block below from every noncreature permanent.
    candidates = _DISPLAY_KEYWORDS if game._is_creature(perm) else _NONCREATURE_KEYWORDS
    keywords = [
        kw for kw in candidates
        if kw != "Protection" and game._has_keyword(perm, kw)
    ]
    if game._is_indestructible(perm):
        keywords.append("Indestructible")
    # Protection is driven by the effective protected **qualities** (CR 702.16)
    # rather than by the printed keyword, so one granted by another card (the
    # Ward cycle) shows up and is spelled out — "Protection from white".
    #
    # Qualities, not colours, and that is the whole of this paragraph's history.
    # This read was `_protection_colors`, the deliberate colour *slice* of the
    # accessor below it, and it was right for as long as every protection in the
    # pool was from a colour. Urza's Legacy printed two from a **card type** and
    # the wire went silent about both: Angelic Curator reached the client
    # showing only "Flying", and Yavimaya Scion — a 2/2 whose entire text is
    # "Protection from artifacts" — reached it carrying **no badge at all**,
    # while the engine had the shield right at every seam it owns.
    #
    # Found at Urza's Legacy's Phase 5, which is the step whose whole job is to
    # read what the *wire* carries for one card of the set's new mechanic rather
    # than what the engine computes. It is the fourth `web/` site of this class
    # after `serialization`'s type-line read (Tempest), `is_aura` (Stronghold)
    # and the blocker/Balance reads (Exodus).
    #
    # Reached for **every** permanent, not only a creature: CR 702.16a is about
    # a permanent, so a protection granted to an artifact or a land has to be
    # spelled out too. It sat inside the creature branch until 6ED's wave, one
    # early return away from the noncreature path.
    words = sorted(
        _protection_quality_word(kind, value)
        for kind, value in game._protection_qualities(perm)
    )
    if words:
        keywords.append("Protection from " + " and ".join(words))
    return keywords


def _protection_quality_word(kind: str, value: str) -> str:
    """One protection quality, spelled the way the card prints it.

    `keywords.protection_quality` canonicalizes to the *singular* because the
    catalogs it matches against store singulars, and every card prints the
    plural — "protection from artifact**s**". The badge is read by a player
    beside the card, so it says what the card says.
    """
    if kind == "color":
        return _SYMBOL_TO_COLOR_WORD.get(value, value)
    if kind == "multicolored":
        return "multicolored"
    if kind == "spell_type":
        # "protection from **instant spells**" (Devoted Caretaker): the type
        # narrowed to spells, spelled as printed. Falling through to the rule
        # below would badge it "instants", which is a wider protection.
        return f"{value} spells"
    # A card type or a creature subtype: printed plural, stored singular. The
    # supertyped form ("legendary creature", Tsabo Tavoc) ends in that same
    # noun, so the one rule spells it too — "legendary creatures".
    return value if value.endswith("s") else value + "s"


def _printed_stat(card, key: str) -> int | None:
    """The card's printed (base) power/toughness as an int, or None when the
    value is variable (`*`) or absent — the UI uses it to decide whether the
    current value is buffed (green) or reduced (red)."""
    raw_value = card.raw.get(key) if isinstance(card.raw, dict) else None
    if raw_value is None:
        return None
    text = str(raw_value)
    return int(text) if text.isdigit() else None


def _card_image_uris(card) -> tuple[str | None, str | None, str | None]:
    """The (normal, large, art_crop) Scryfall image URIs from the card's raw
    payload. ``art_crop`` is the borderless art-only crop the Arena-style board
    renderer uses as the card face."""
    image_uris = card.raw.get("image_uris") if isinstance(card.raw, dict) else None
    if not isinstance(image_uris, dict):
        return None, None, None
    return image_uris.get("normal"), image_uris.get("large"), image_uris.get("art_crop")


def _card_preview(card) -> dict:
    """The base card-preview dict shared by every card serialization: identity,
    rules text, and art. Callers extend it with context-specific fields."""
    image_uri, large_image_uri, art_crop = _card_image_uris(card)
    preview = {
        "name": card.name,
        "type": card.type_line,
        # Every face's text for a split card (CR 709.4c), whose own text box is
        # empty: a preview that showed the top-level field would draw a card
        # with two spells on it as a blank one. A single-face card's own text.
        "oracle_text": combined_oracle_text(card),
        "image_uri": image_uri,
        "large_image_uri": large_image_uri,
        "art_crop": art_crop,
        "colors": list(card.colors),
    }
    faces = face_cards(card)
    if faces:
        # CR 709.1: the halves, each as the card it is on the stack. Present
        # only on a multi-face card, so its absence is "this card has one face"
        # for every client reading it. The cast-ready shape (target spec,
        # modes, taxed cost) is `_serialize_card`'s, which overwrites this for
        # the viewer's own cards; here it is what a preview needs to *show*.
        preview["layout"] = card.layout
        preview["faces"] = [
            {
                "name": face.name,
                "type": face.type_line,
                "oracle_text": face.oracle_text,
                "mana_cost": face.mana_cost,
                "colors": list(face.colors),
            }
            for face in faces
        ]
    if is_face(card):
        # A half on the stack (CR 709.3b): its own name and characteristics,
        # and the card it is half of, so a client can say which card this is.
        preview["face_of"] = whole_card(card).name
    return preview


def hidden_card_view(obj) -> dict | None:
    """What a face-down permanent or spell is, as the **one** seat CR 708.5
    lets look at it sees it — its controller: "At any time, you may look at a
    face-down spell you control on the stack or a face-down permanent you
    control … You can't look at … face-down spells or permanents controlled
    by another player."

    The card it hides as a preview (name, text, type, art), its printed power
    and toughness, and its morph cost when it prints one (what turning it
    face up would cost, CR 702.37e). None for a face-up object. **Attached
    only to the controller's own payload** — by
    ``player_view._serialize_player`` for a permanent and by the state view
    for a spell — and never by the shared serializers, which emit the
    face-down 2/2 for every viewer
    (``tests/ui/test_ons_w1g1_face_down_hidden_census.py``).
    """
    real = hidden_card_of(obj)
    if real is None:
        return None
    view = _card_preview(real)
    view["mana_cost"] = real.mana_cost
    view["power"] = _printed_stat(real, "power")
    view["toughness"] = _printed_stat(real, "toughness")
    # What turning it face up would cost (CR 702.37e: "what the permanent's
    # morph cost would be if it were face up") — a copy effect on it counts
    # (CR 708.10), so a face-down Clone of a morph creature shows that cost.
    printed = face_up_morph_cost(obj)
    if printed is not None:
        view["morph_cost"] = printed
    return view


def _shield_source_payload(source_name: str | None) -> dict | None:
    """A card-preview payload for the effect that granted a damage-prevention
    shield, so the UI can show its art when the shield badge is hovered. Returns
    None when there is no recorded source."""
    if not source_name:
        return None
    card = CARD_BY_NAME.get(source_name.casefold())
    if card is None:
        return {"name": source_name}
    return _card_preview(card)


def _text_change_replacements(perm: Permanent) -> list[dict]:
    """Word-level oracle-text edits applied to this permanent by a text-changing
    spell, as ``{"from": old_word, "to": new_word}`` entries. The UI renders the
    old word struck through and the new word in gold.

    Derived from the layer-3 contributions (``engine/text_changes.py``), so it
    covers Sleight of Mind's colour word and Magical Hack's basic land type
    together and reports the *net* edit — two changes that chain (black -> red,
    then red -> green) are the one edit a player actually sees. The compound
    forms ("mountainwalk", "Mountains") follow from the bare word and are not
    listed separately.
    """
    return changed_words(perm)


#: "…unattach **the permanent with id 7 that granted this ability**: …" — the
#: words ``granted_abilities.bind_granter`` writes for a granter's name once its
#: quoted ability is the host's own text (CR 201.5a: the name means that one
#: object), spelled from the engine's own constants.
_GRANTER_REFERENCE = re.compile(
    r"\b" + r"\s+".join(GRANTER_PHRASE_HEAD) + r"\s+(\d+)\s+"
    + r"\s+".join(GRANTER_PHRASE_TAIL) + r"\b",
    re.IGNORECASE,
)


def _granter_names(game: Game, text: str) -> str:
    """*text* with each bound granter reference said as the granter's name.

    The binding is how the engine tells two Heartseekers on one creature
    apart, and it reached the player verbatim: the host's ability menu and its
    preview read "{t}, unattach the permanent with id 7 that granted this
    ability: destroy target creature." The printed card says the name, and the
    id is the engine's handle, never a player's — so the payload says the name
    of the permanent with that id (the line count, which ability indices
    follow, is unchanged). A granter no longer on the battlefield is said as
    the relation without its id.
    """
    if not text or "granted this ability" not in text.lower():
        return text

    def name(match: re.Match) -> str:
        granter = game.permanent_by_id(int(match.group(1)))
        if granter is None:
            return "the permanent that granted this ability"
        return granter.effective_card.name

    return _GRANTER_REFERENCE.sub(name, text)


def _serialize_permanent(perm: Permanent, game: Game) -> dict:
    image_uri, large_image_uri, art_crop = _card_image_uris(perm.card)
    # A Clone keeps its own art — the physical card is a Clone. A token that is
    # a copy (Sublime Epiphany, the Debug Menu's "Create a copy") has no card
    # and so no art of its own; the copied card's is the only face it can wear.
    if image_uri is None and large_image_uri is None and perm.copied_from is not None:
        image_uri, large_image_uri, art_crop = _card_image_uris(perm.effective_card)

    # Resolve aura attachment. Both addresses go on the wire: the ``id`` is the
    # stable one and the ``index`` is what the canvas has always drawn its
    # attachment lines from. Migrating the client is a separate step from
    # emitting the field it needs, so the index stays until it has.
    attached_to = perm.metadata.get("attached_to")
    attached_to_index: int | None = None
    attached_to_seat: int | None = None
    attached_to_id: int | None = None
    if attached_to is not None:
        attached_to_seat = game.controller_index_of(attached_to)
        if attached_to_seat is not None:
            attached_to_index = game.battlefield_index_of(attached_to)
            attached_to_id = game.permanent_id_of(attached_to)

    # Planeswalker loyalty state the UI's loyalty-ability menu gates on. The
    # loyalty *counters* already ride along in ``counters``; these are the two
    # halves of CR 606.3 a client cannot see — whether this permanent has
    # already used a loyalty ability this turn, and whether the card widens the
    # sorcery-speed window itself ("You may activate loyalty abilities of ~ on
    # any player's turn any time you could cast an instant", Teferi, Master of
    # Time). Read from the same metadata key and the same canonical static line
    # the activation gate reads, so the greyed-out button and the engine's
    # refusal cannot disagree.
    is_planeswalker = perm.has_type("planeswalker")
    loyalty_any_time = is_planeswalker and (
        LOYALTY_ANY_TIME_STATIC
        in compile_card_oracle(perm.effective_card).static_lines
    )

    # A color override (Thoughtlace/Lifelace) replaces the printed colors
    # entirely; a copied color (Clone) replaces them too, while Vesuvan
    # Doppelganger's "doesn't copy that creature's color" keeps its own blue.
    # game._effective_colors honors all three.
    effective_colors = sorted(game._effective_colors(perm))

    payload = {
        # Stable identity (CR 400.7), unique across every seat and unchanged for
        # as long as this permanent is on the battlefield. The client's handle on
        # a card: an *index* into this array is only valid until the next poll,
        # because anything leaving the battlefield renumbers the rest, and the
        # canvas holds addresses across polls (selection, hover, the attacker it
        # is dragging an arrow from). A permanent that leaves and returns is a
        # new object and gets a new id, so a held id can never quietly start
        # naming something else.
        "id": perm.permanent_id,
        # CR 707.2: a copy's name is a copiable value, so it is the copied
        # object's — Sculpting Steel copying Iron Myr *is* an Iron Myr, and
        # every seat reads its name plate, its preview and the prompts that
        # offer it so. Off ``effective_card``, as the mana cost, the P/T and
        # the text below already were; this read the printed card.
        "name": perm.effective_card.name,
        # …and the card it is printed on, which the art (above) stays — the
        # physical card a zone change carries away (the copy effect ends as
        # it leaves, CR 400.7). What the client matches a card *across zones*
        # by (a bounced copy is a Sculpting Steel in hand) and what a pasted
        # raw state rebuilds (``debug_actions._card_for_raw_permanent``). The
        # same as ``name`` for anything that is not a copy; a face-down
        # permanent's is the blank's (CR 708.2a), never the card it hides.
        "printed_name": perm.card.name,
        # CR 708: this permanent is face down. Public — every player sees a
        # face-down card on the table — and the whole of what anyone but its
        # controller learns: every other field here is the face-down 2/2's
        # (CR 708.2a), because the permanent's card *is* that blank
        # (``engine/face_down.py``). The controller's own view adds
        # ``hidden_card`` (CR 708.5, ``player_view._serialize_player``).
        "face_down": is_face_down(perm),
        # CR 903.3: this permanent is the designated commander card itself —
        # never a token copy or another same-name card. Drawn as a crown badge
        # and named in the card preview.
        "is_commander": game.is_commander_permanent(perm),
        # Effective type line so a copy shows its copied types (a Copy Artifact
        # copying a Mox reads "Artifact Enchantment", not just "Enchantment"),
        # with the whole of layer 4 folded in: a permanent returned "as a
        # non-Aura enchantment" (Takklemaggot) must not still read "Aura", an
        # Evil Presence'd Forest must read Swamp, and a creature wearing Demonic
        # Embrace must show the Demon type it was granted. Every one of those is
        # the screen disagreeing with what the rules queries answer.
        "type": displayed_type_line(perm),
        "tapped": perm.tapped,
        "colors": effective_colors,
        # True for printed creatures and for animated lands (Kormus Bell / Living
        # Lands) so the UI shows their P/T and lets them be declared as attackers.
        "is_creature": game._is_creature(perm),
        "power": perm.effective_power,
        "toughness": perm.effective_toughness,
        # CR 707.2: a copy's mana cost and its printed power/toughness are
        # *copiable values*, so they come off the effective card the way the
        # oracle text below already does. Reading ``perm.card`` here made a
        # Clone-as-Grizzly-Bears report ``{3}{U}`` for its cost and a base P/T
        # of 0/0 against a current 2/2 — so the canvas painted a vanilla Bear's
        # P/T green, as though something had pumped it, and the preview showed
        # the wrong cost. The art deliberately stays the Clone's (below); a
        # characteristic does not.
        "base_power": _printed_stat(perm.effective_card, "power"),
        "base_toughness": _printed_stat(perm.effective_card, "toughness"),
        "mana_cost": perm.effective_card.mana_cost,
        # A copy (Clone / Vesuvan Doppelganger) shows — and the UI activates —
        # the copied card's abilities, so its text is the effective text, with
        # a granted ability's granter said by name (``_granter_names``).
        "oracle_text": _granter_names(game, perm.effective_card.oracle_text),
        # Word-level edits from a text-changing spell (Sleight of Mind / Magical
        # Hack) so the UI can strike the old word and show the new word in gold.
        "text_changes": _text_change_replacements(perm),
        # CR 602.1a's exceptions: True when some seat other than the controller
        # may activate one of this permanent's abilities ("Any player may
        # activate this ability", "Only your opponents may activate this
        # ability"). Served rather than re-derived in the client, which tested
        # for one of the spellings as a substring of the oracle text and so did
        # not know about the others.
        "activatable_by_other_seats": card_widens_activation(perm.effective_card),
        "keywords": _effective_keywords(perm, game),
        # True when this creature may block more than one attacker at once
        # (Two-Headed Giant of Foriys, or Blaze of Glory's "block any number"),
        # so the UI lets the player assign it to several attackers.
        "can_block_multiple": game._is_creature(perm) and game._max_blocks_for(perm) > 1,
        "image_uri": image_uri,
        "large_image_uri": large_image_uri,
        "art_crop": art_crop,
        "attacking": perm.attacking,
        # True when this creature can't be blocked by any creature (Dwarven
        # Warriors' granted "can't be blocked this turn", or inherent unblockable
        # text) — the UI tags it and renders it translucent.
        "unblockable": game.is_unblockable(perm),
        "defending_player_index": perm.defending_player_index,
        "blocked": perm.blocked,
        "blocking_attacker_controller": perm.blocking_attacker_controller,
        "blocking_attacker_index": perm.blocking_attacker_index,
        "damage_marked": perm.damage_marked,
        "regeneration_shield": perm.regeneration_shield,
        # Disintegrate / Hurr Jackal style riders: the UI badges the permanent as
        # unregeneratable and strikes through any regeneration shield it holds,
        # since that shield can no longer save it.
        "cant_be_regenerated": bool(perm.metadata.get("cant_be_regenerated_this_turn", False)),
        # "Prevent the next N damage" shield on this creature, with the granting
        # card's preview payload for the hover tooltip.
        "damage_prevention_pool": perm.damage_prevention_pool,
        "shield_source": _shield_source_payload(perm.damage_prevention_source),
        "summoning_sick": game._is_summoning_sick(perm),
        "is_token": bool(perm.metadata.get("is_token", False)),
        # The basic land type(s) an effect has given this land, when they are
        # not the printed ones — derived through layer 4 rather than read off a
        # stored value, so a layer-3 text change (Magical Hack) badges the same
        # way a layer-4 replacement (Evil Presence, a mire counter) does.
        "land_type_override": " ".join(perm.changed_land_types) or None,
        "mire_counter": bool(perm.metadata.get("mire_counter", False)),
        # Both flags go through the engine's own predicates rather than reading
        # the metadata flag directly: Guardian Beast grants them continuously to
        # the noncreature artifacts their controller owns while it's untapped,
        # computing them per query without ever writing metadata.
        "cant_be_enchanted_by_auras": game._cant_be_enchanted(perm),
        "is_indestructible": game._is_indestructible(perm),
        # Asked of ``displayed_type_line`` — the same layer-aware answer the
        # ``"type"`` field above already sends — rather than of the *printed*
        # type line. This is the second site of the class Tempest's smoke test
        # found in ``_effective_keywords`` and fixed at one site only, and
        # Stronghold is the set that collects on it: a **Licid** activates
        # "becomes an Aura enchantment with enchant creature", which is a
        # CR 613 layer-4 type change, so nothing on the card moves and both
        # ``perm.card.type_line`` and ``effective_card.type_line`` still read
        # "Creature — Licid". The engine had it right at every other seam
        # (``is_creature`` False, ``has_type("enchantment")`` True, the
        # attachment recorded); the client alone was told the thing attached to
        # its Grizzly Bears was not an Aura.
        "is_aura": "aura" in displayed_type_line(perm).lower(),
        "attached_to_index": attached_to_index,
        "attached_to_id": attached_to_id,
        "attached_to_seat": attached_to_seat,
        "produced_mana": list(_offered_mana(game, perm)),
        # The open colours a tap of this land also sets off, as one split of
        # its controller's (Dawn's Reflection's "additional two mana in any
        # combination of colors"): `{count, colors, source}`, answered on the tap
        # action's `mana_combination`; None for every other permanent
        # (``offers.tap_mana_split``).
        "tap_mana_split": tap_mana_split(game, perm),
        # Whether tapping this land part-way through a payment makes mana —
        # the tap seam's own answer (``mana_payment.taps_for_payment``), which
        # the engine's planner and the AI's already ask. The client's auto-tap
        # plans from ``produced_mana`` above, which is what to *offer* when the
        # land is activated and says nothing about whether a "tap" may be sent
        # for it: Rhystic Cave offers all five colours and needs priority and
        # the table's consent, and a depletion land's mana costs a counter.
        "taps_for_mana": bool(perm.has_type("land") and taps_for_payment(perm)),
        # A color-changing effect (e.g. Lifelace: "Target ... becomes green.")
        # records the new color so the UI can label the recolored permanent.
        "color_override": perm.metadata.get("color_override"),
        # …and a colour the *layers* give with no such record behind it:
        # Repentant Vampire's threshold ("is white"), Darkest Hour, Shifting
        # Sky, Alloy Golem. ``colors`` above already says what the permanent
        # is; this says that it is not what its card (as copied, CR 707.2)
        # prints, which is the one thing a player looking at the art cannot
        # see. ``color_override`` is None for all of these - it is one
        # effect's own slot - so a client reading it alone signalled nothing.
        "color_changed": effective_colors != sorted(perm.effective_card.colors),
        # Corpse counters (Scavenging Ghoul) so the canvas can render them. Folded
        # into a generic ``counters`` map so future counter types render for free.
        "corpse_counters": int(perm.metadata.get("corpse_counters", 0)),
        "counters": _serialize_counters(perm),
        # Ability *lines* granted by another permanent's static ability
        # (Zombie Master's '{B}: Regenerate this permanent.', Tempest's
        # Slivers), which the printed oracle text doesn't show — the UI needs
        # these to offer activation. Read off the derived layer-6 channel
        # `_recalculate_lord_buffs` writes; the literal that stood here was the
        # third copy of one card's quoted text, so a lord granting anything else
        # showed the player nothing.
        # …the ones it still has: a lord older than a "loses all abilities"
        # effect on this permanent grants it nothing (CR 613.7).
        "granted_abilities": [
            _granter_names(game, line)
            for line in derived_ability_lines(perm, after=abilities_lost_at(perm))
        ],
        # Why this permanent has **no** activated ability to offer although
        # its text prints some — "loses all abilities", or a land whose type
        # was set (CR 305.7) — or None. The client builds its ability menu
        # from the oracle text above, which an effect like that does not
        # rewrite, so without this it offered every printed ability and each
        # one was a 400 (``Game.lost_abilities_refusal``, the engine's own
        # reason, read by the menu's one reader of that text).
        "abilities_lost": game.lost_abilities_refusal(perm),
        # What this permanent chose **as it entered** (CR 614.1c), as
        # ``[{"label": "Chosen color", "value": "green"}, …]``: the opponent a
        # Black Vise watches, the colour a Ward protects from, the name a
        # Meddling Mage or a Runed Halo forbids. Every one of them is the whole
        # of what the card *does*, and none of them was on the wire — the
        # engine wrote the record and read it at every seam it owns, and a
        # player facing an opponent's Voice of All learned its colour by having
        # a spell fizzle. The fifth ``web/`` site of the display-list class
        # (shadow, protection from a card type, ``is_aura``, the noncreature
        # badges), and derived for that reason: read off
        # ``entry_choices.ENTRY_CHOICES``, the engine's own table of what an
        # entry records, never off a list of keys kept here. Public by rule —
        # these choices are made in the open as the permanent enters — so every
        # viewer is sent them.
        "entry_choices": chosen_as_entered(game, perm),
        # Name of the creature this permanent is a copy of (Clone / Vesuvan
        # Doppelganger), so the UI can badge the copy.
        "copied_from": perm.copied_from,
        "is_planeswalker": is_planeswalker,
        "loyalty_ability_used_this_turn": bool(
            is_planeswalker
            and perm.metadata.get("loyalty_ability_used_turn") == game.turn
        ),
        "loyalty_any_time": loyalty_any_time,
    }
    # CR 508.1h / 509.1d: what declaring this creature costs in permanents its
    # controller picks — Leviathan's two Islands, Hollow Warrior's creature to
    # tap — so the client can ask *which* before it sends the declaration.
    # Only while that declaration is open, and only when there is something to
    # say, so every other permanent's payload is unchanged.
    declaration_costs = _declaration_costs(perm, game)
    if declaration_costs:
        payload["declaration_costs"] = declaration_costs
    return payload


def _declaration_costs(perm: Permanent, game: Game) -> dict:
    """``{"attack": [...]}`` / ``{"block": [...]}`` from
    ``Game.declaration_cost_choices``, for the declaration currently open."""
    if game.current_turn_phase != "combat" or not game._is_creature(perm):
        return {}
    seat = game.controller_index_of(perm)
    if (
        game.current_step == "declare_attackers"
        and not game.combat_attackers_locked
        and seat == game.active_player_index
    ):
        choices = game.declaration_cost_choices(perm, "attack")
        return {"attack": choices} if choices else {}
    if (
        game.current_step == "declare_blockers"
        and not game.combat_blockers_locked
        and seat is not None
        and seat != game.active_player_index
    ):
        choices = game.declaration_cost_choices(perm, "block")
        return {"block": choices} if choices else {}
    return {}


# Counter metadata keys whose bare name doesn't read as the counter's kind
# (``plus_counters`` is the +1/+1 counter, ``plus_1_0`` Instill Energy's +1/+0).
_COUNTER_KIND_LABELS = {
    "plus": "+1/+1",
    "minus": "-1/-1",
    "plus_1_0": "+1/+0",
}


def _serialize_counters(perm) -> dict:
    """A kind->count map of every counter on this permanent.

    Counters live in permanent metadata under ``<kind>_counters`` (corpse,
    vitality, wind, lore, plus/minus, …), so sweeping that suffix means a new
    counter-placing card renders on the card face and in the hover preview for
    free — no per-counter entry here. ``mire_counter`` is the one boolean-shaped
    counter (a land has it or doesn't) and is reported as a count of 1.
    """
    counters: dict[str, int] = {}
    for key, value in perm.metadata.items():
        if not key.endswith("_counters"):
            continue
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        kind = key[: -len("_counters")]
        counters[_COUNTER_KIND_LABELS.get(kind, kind)] = count
    if perm.metadata.get("mire_counter"):
        counters["mire"] = 1
    return counters


def mode_target_kind(card, mode_index: int) -> str:
    """The client target-prompt kind of one mode of a modal spell.

    **The kind of the spec the engine's own cast gate derives for that mode**
    (``targeting.derive_cast_spec(mode_index=)``), and nothing else. This was a
    table of its own — keyed by instruction kind, four kinds long, with a
    fall-through that answered "player" — so a mode whose kind it did not name
    was sent to the life pills: 21 of the pool's 47 modes that target one
    permanent asked the caster for a *player* (Chaos Charm's "deals 1 damage to
    target creature", Treva's Charm's "exile target attacking creature"), nine
    more highlighted permanents their mode cannot target (the table knew the
    head noun and not "nonblack", "nonbasic" or "Aura"), Darigaaz's Charm's
    graveyard return asked for a player, and a mode that targets nothing ("You
    gain 5 life", "Create three 1/1 Saproling tokens") asked for one too.
    A second derivation of what a mode targets cannot agree with the first for
    long, and the engine's gate reading the first is what would have turned
    that disagreement into a cast the browser offers and the engine refuses.
    """
    spec = derive_cast_spec(card, compile_card_oracle(card), mode_index=mode_index)
    return spec["kind"] if spec is not None else "none"


def _serialize_modes(card, game: Game | None = None, caster_index: int | None = None) -> list[dict]:
    """Selectable modes of a "Choose one —" modal spell, or [] when not modal.

    When ``game``/``caster_index`` are supplied (the viewer's own hand), each mode
    also carries ``target_spec`` — the **whole** cast spec that mode would have
    as a spell of its own (``Game.cast_target_spec(mode_index=)``: kind, flags,
    roles, the several-target count, and the legal targets enumerated through
    the cast gate's own per-candidate probe for that mode). ``valid_targets``
    is that spec's list, kept at the top level for the readers that predate the
    spec. So what a mode highlights is what CR 601.2c will let it name."""
    program = compile_card_oracle(card)
    if not program.modes:
        return []
    modes = []
    for index, mode in enumerate(program.modes):
        kind = mode_target_kind(card, index)
        entry = {
            "index": index,
            "label": mode.label,
            "supported": mode.supported,
            "target_kind": kind,
        }
        if game is not None and caster_index is not None and kind not in ("none",):
            spec = game.cast_target_spec(caster_index, card, mode_index=index)
            entry["target_spec"] = spec
            entry["valid_targets"] = spec.get("valid_targets") or []
        else:
            entry["valid_targets"] = []
        if game is not None and caster_index is not None and program.mode_chooser is None:
            # CR 601.2c: a mode whose mandatory target has nothing to name
            # cannot be announced, so the prompt says so on the button instead
            # of taking the click and having the cast refused. The engine's
            # answer, the one the castable highlight is built from.
            refusal = game.mode_announcement_refusal(caster_index, card, index)
            entry["announceable"] = refusal is None
        modes.append(entry)
    return modes


def _cast_price(card, game, caster_index, from_zone: str) -> tuple[str, bool, bool, str]:
    """``(the cost the UI shows, increased?, reduced?, the cost before the
    modifiers)`` for a cast of *card* by *caster_index* out of *from_zone* —
    the mana the payment will ask for before X is announced, written as the
    card prints a cost, and the cost the increases and reductions were applied
    to (the printed one, or the alternative cost a permission charges).

    CR 601.2f over the mana cost the cast is charged: the card's own
    (``cost_modifiers.cast_mana_charge``), or, for a graveyard copy this seat
    may cast only by paying an alternative cost (flashback, CR 118.9b,
    702.34a), that cost with every increase and reduction in force
    (``Game.alternative_cost_mana``, CR 118.9d). This folded in the
    **increases** alone (``spell_cost_tax``), so a reduction was paid and never
    shown: Goblin Brigand read ``{1}{R}`` under Goblin Warchief while the
    payment asked for ``{R}``; Edgewalker's coloured-only discount, a
    Medallion's, Krosan Drover's and a card's own were the same blind spot
    (SCG Phase 5, C3). A flashback cost read Catalyst Stone's reduction and
    a generic tax but not a coloured one (Derelor) or a board's reduction.

    The printed cost is passed through unchanged when nothing in force moves
    it, and an ``{X}`` stays where it is printed (it is announced later). A
    multi-face card as a whole is not a spell (CR 709.3) and a land is not
    cast (CR 305.1): each is shown as printed.
    """
    printed = card.mana_cost or ""
    if game is None or caster_index is None or card.primary_type == "land" or face_cards(card):
        return printed, False, False, printed
    from engine.cost_modifiers import cast_mana_charge
    from engine.mana_payment import mana_cost_label

    charged_printed = printed
    owed = None
    if from_zone == "graveyard":
        from engine.cast_permissions import permission_for

        permission = permission_for(game, caster_index, card, from_zone)
        if permission is not None and (permission.cost is not None or permission.free):
            charged_printed = (permission.cost.mana if permission.cost is not None else None) or ""
            owed = game.alternative_cost_mana(caster_index, card, permission.cost)
    if owed is None:
        owed = cast_mana_charge(game, caster_index, card)
    x_symbols = charged_printed.count("{X}")
    base = game._parse_mana_cost(charged_printed, x_value=0)
    keys = set(base) | set(owed)
    if all(int(base.get(k, 0)) == int(owed.get(k, 0)) for k in keys):
        return charged_printed, False, False, charged_printed
    increased = any(int(owed.get(k, 0)) > int(base.get(k, 0)) for k in keys)
    reduced = any(int(owed.get(k, 0)) < int(base.get(k, 0)) for k in keys)
    label = "{X}" * x_symbols + (mana_cost_label(owed) if any(owed.values()) else "")
    return label or "{0}", increased, reduced, charged_printed or "{0}"


def _serialize_card(
    card,
    game: Game | None = None,
    caster_index: int | None = None,
    *,
    from_zone: str = "hand",
    hand_index: int | None = None,
    owner_seat: int | None = None,
) -> dict:
    # *owner_seat* is whose card this is when it is **not** being prepared
    # for casting (no *caster_index*: another seat's graveyard, a revealed
    # hand, the library top, the ante): it colours the card as its owner's
    # statics leave it (CR 613.1e — under that owner's Celestial Dawn a
    # nonland card off the battlefield is white) and touches nothing else, so
    # no target spec, tax or zone cost is computed for a card nobody is
    # casting from here.
    # Cost increasers (Gloom) are applied at payment time by the engine; reflect
    # them in the cost the UI shows and auto-taps for, so the pay-mana prompt
    # matches what the player actually pays. ``printed_mana_cost`` keeps the
    # unmodified printed value for reference.
    # Never on a multi-face card as a whole: it is not a spell (CR 709.3), its
    # `mana_cost` is two costs spelled side by side, and folding a tax into
    # that string added it to whichever half printed a generic symbol —
    # Stand // Deliver read `{W}{5}{U}` under Gloom, the white half's tax on
    # the blue half's cost. Each face below is taxed as the spell it is.
    # CR 118.9b, CR 702.34a: a copy in a graveyard that this seat may cast only
    # by paying an alternative cost — its flashback cost — is charged *that*,
    # and "the cost the UI shows and auto-taps for" is what this field is. The
    # client reads it for three things, and the printed cost is wrong for each:
    # which lands the insufficient-mana prompt taps (Firebolt's {R} where the
    # cast charges {4}{R}, so the retry was refused again), what the prompt
    # says the cast costs, and whether to ask for an X (an X spell flashed back
    # for a cost with no X in it has X = 0, CR 107.3b). The increases **and the
    # reductions** in force are folded in (``_cast_price``).
    effective_cost, increased, reduced, before = _cast_price(card, game, caster_index, from_zone)
    serialized = _card_preview(card)
    serialized.update({
        "mana_cost": effective_cost,
        "printed_mana_cost": card.mana_cost,
        "effective_mana_cost": effective_cost,
        "cost_increased": increased,
        # The other direction (a Warchief, a Medallion, Edgewalker): the
        # badge is cheaper than the card prints.
        "cost_reduced": reduced,
        # What those two compare against: the cost the increases and
        # reductions in force were applied to — the printed one, or the
        # alternative cost a permission charges (a flashback cost). The badge
        # is coloured by the two flags and the preview says "{R}, reduced
        # from {2}{R}", so a reduced badge no longer reads like a printed one.
        "cost_before_modifiers": before,
        # The card's colours as its seat's statics leave them (CR 613.1e):
        # under its owner's Celestial Dawn a nonland card off the battlefield
        # is white, and the hand drew it in its printed colours. A preview
        # with no seat keeps the printed ones (``_card_preview``).
        "colors": list(card_colors(
            game, card, caster_index if caster_index is not None else owner_seat,
        )),
        "modes": _serialize_modes(card, game, caster_index),
        # "Choose one **or more** —" (Sublime Epiphany, CR 700.2d). Sent
        # alongside the modes because the mode list alone cannot say it: a
        # client reading five modes has no way to know whether it may offer two
        # of them, and guessing from the label text would be the substring match
        # the compiler stopped making.
        "modes_at_least": compile_card_oracle(card).modes_at_least,
    })
    # The viewer's own hand cards carry a backend-computed target spec (kind +
    # enumerated legal targets) so the UI never re-derives targeting from text.
    # ``from_zone`` is which zone this copy would be cast from, because a
    # printed additional cost may name one: Demonic Embrace's discard is a
    # graveyard price, so the copy in hand and the copy in the graveyard are two
    # different prompts for one card.
    if game is not None and caster_index is not None:
        # ``hand_index`` is which copy this is, and it matters to exactly one
        # part of the spec: CR 601.2a puts the spell on the stack before its
        # costs are paid, so it cannot be the card exiled to pay its own
        # alternative cost — while a *second copy* in hand legitimately can.
        # A deck repeats one immutable definition per copy, so the position is
        # the only thing that tells them apart.
        serialized["target_spec"] = game.cast_target_spec(
            caster_index, card, from_zone=from_zone, spell_hand_index=hand_index,
        )
        # The split the spell's mana is made in, chosen with the cast
        # (``mana_combination.cast_split_offer``) — absent for every card that
        # makes none.
        combination = cast_split_offer(game, caster_index, card)
        if combination is not None:
            serialized["mana_combination"] = combination
        # What the spell's own resolution adds and whether the cast names its
        # colour (``offers.cast_mana_offer``), and a text change's words
        # (``offers.text_change_offer``) — each absent for every card whose
        # cast announces neither.
        cast_mana = cast_mana_offer(card)
        if cast_mana is not None:
            serialized["cast_mana"] = cast_mana
        text_change = text_change_offer(game, card)
        if text_change is not None:
            serialized["text_change"] = text_change
        # How large an X the pool, and the board, pay for a cast from the
        # hand (``offers.cast_x_payable``) — the X prompt's range.
        if from_zone == "hand":
            x_payable = cast_x_payable(game, caster_index, card)
            if x_payable is not None:
                serialized["x_payable"] = x_payable
    faces = face_cards(card)
    if faces:
        # CR 709.3: the player chooses a half *before* anything else about the
        # cast is decided, and CR 709.3a evaluates only that half. So each face
        # is serialized as the card it would be on the stack — the full shape a
        # single-face hand card has, target spec and all — and the client's
        # cast flow carries on with the chosen face in the card's place. Its
        # `name` is what the cast action sends as `card_name`.
        serialized["faces"] = [
            _serialize_card(
                face, game, caster_index, from_zone=from_zone, hand_index=hand_index,
                owner_seat=owner_seat,
            )
            for face in faces
        ]
    return serialized


def _serialize_card_summary(card, game: Game | None = None, owner_seat: int | None = None) -> dict:
    """A card as a list shows it — a prompt's cards, the catalog. With *game*
    and *owner_seat* its colours are its owner's statics' answer
    (``object_colors.card_colors``: Celestial Dawn's white); without them,
    printed, as a card nobody owns yet (the catalog) has to be."""
    serialized = _card_preview(card)
    if owner_seat is not None:
        serialized["colors"] = list(card_colors(game, card, owner_seat))
    serialized.update({
        "mana_cost": card.mana_cost,
        "modes": _serialize_modes(card),
        "modes_at_least": compile_card_oracle(card).modes_at_least,
    })
    return serialized


def _serialize_permanent_summary(perm: Permanent, game: Game) -> dict:
    """A card summary for a permanent **on the battlefield**.

    The same shape :func:`_serialize_card_summary` produces for a card in a hand
    or a library, with the characteristics CR 613 can move answered by the
    layers instead of by the printer. A list that *selects* through
    ``game._is_creature`` and then *describes* through ``card.type_line`` is the
    seven-site class this repo keeps finding, one call deep: the Raging River
    division and the Camouflage piles both offer exactly the creatures the rules
    say they should and then drew a Kormus Bell'd Swamp as "Basic Land —
    Swamp".

    Name and art stay the printed ones, for the reason
    :func:`_serialize_permanent` keeps them: the physical card is a Clone, and
    the name is what the action API addresses the permanent by.
    """
    summary = _serialize_card_summary(perm.card)
    summary.update({
        "type": displayed_type_line(perm),
        "oracle_text": _granter_names(game, perm.effective_card.oracle_text),
        "colors": sorted(game._effective_colors(perm)),
        # CR 707.2: a copiable value (see ``_serialize_permanent``).
        "mana_cost": perm.effective_card.mana_cost,
    })
    return summary


# A stack item's own text targets a player (rather than merely naming one as the
# affected/controlling seat) — the gate for turning a bare target_player_index
# into a player-targeting arrow.
_TARGETS_PLAYER_RE = re.compile(r"target (?:player|opponent)|any target")


def _targeted_permanents_now(item, game: Game) -> "list[tuple[int, int, Permanent]] | None":
    """``(seat, index, permanent)`` for each permanent *item* targets that is
    still on the battlefield, read through its id (``StackItem.
    target_permanent_id``, CR 400.7); None when the item carries no id and
    only its announced slot says what it targets."""
    ids = [pid for pid in target_ids(item.target_permanent_id) if isinstance(pid, int)]
    if not ids:
        return None
    placed = []
    for pid in ids:
        perm = game.permanent_by_id(pid)
        if perm is None:
            continue
        owner = game.controller_index_of(perm)
        index = game.battlefield_index_of(perm)
        if isinstance(owner, int) and isinstance(index, int):
            placed.append((owner, index, perm))
    return placed


def _stack_item_targets(item, game: Game) -> list[dict]:
    """Every target a stack item chose, normalized for the UI's hover arrows.

    One entry per target: ``{"kind": "permanent", "seat", "index"}``,
    ``{"kind": "player", "seat"}``, ``{"kind": "graveyard", "seat", "index"}``,
    or ``{"kind": "stack", "index"}`` (an index into this same serialized,
    top-first stack). The engine records targets in several shapes — a divided
    cross-seat list, a direct stack-item reference, one or many battlefield
    indices under a controlling seat — so this flattens all of them into the
    single list the canvas draws arrows to."""
    players = game.players
    targets: list[dict] = []

    # Fireball & co: the full cross-seat list, which takes precedence over the
    # single-target fields (see StackItem.choices["divided_targets"]).
    divided = item.choices.get(DIVIDED_TARGETS)
    if divided:
        for seat, idx, _share in (divided_entry(entry) for entry in divided):
            if not 0 <= seat < len(players):
                continue
            if idx is None:
                targets.append({"kind": "player", "seat": seat})
            elif 0 <= idx < len(players[seat].battlefield):
                targets.append({"kind": "permanent", "seat": seat, "index": idx})
        return targets

    # Counterspell / Fork: a spell on the stack, held by identity. The serialized
    # stack is reversed (top first), so flip the depth into that index space.
    if item.target_stack_item is not None:
        for depth, other in enumerate(game.stack):
            if other is item.target_stack_item:
                targets.append({"kind": "stack", "index": len(game.stack) - 1 - depth})
                break
        return targets

    # Several **players**, each its own target ("…target player controls …
    # another target player controls", Cultural Exchange). The announcement
    # recorded a seat per role (``target_roles.ROLE_SEATS``) and the scalar read
    # below is only the first of them, so without this the table was shown a
    # spell aimed at one player while it was aimed at two. A slot CR 608.2b
    # blanked is ``None`` and draws no arrow.
    named_seats = [
        named for named in (recorded_role_seats(item) or ())
        if isinstance(named, int) and 0 <= named < len(players)
    ]
    if named_seats:
        return [{"kind": "player", "seat": named} for named in named_seats]

    seat = item.target_player_index
    if seat is None or not 0 <= seat < len(players):
        return targets

    # A graveyard target, read off the identity the stack stamped rather than
    # re-derived from the card. Three things follow from that and none of them
    # did before: an *ability*'s graveyard target gets an arrow at all
    # (`cast_target_kind` is the spell-side question and was asked with
    # `not is_ability`), a *mode*'s does (Return to Nature's third), and the
    # arrow follows the card as the pile shifts underneath it.
    stamped = item.target_graveyard_card
    if stamped is not None:
        for stamp in (stamped if isinstance(stamped, list) else [stamped]):
            index = game.graveyard_index_of(stamp)
            if index is not None:
                targets.append({"kind": "graveyard", "seat": stamp.seat, "index": index})
        return targets

    # **The permanents it targets, where they are now**, by id. The stored
    # index is the slot each one held as the object was announced, and nothing
    # renumbers it: a target that left (Chain of Vapor's own bounce, held on
    # the stack by its "may sacrifice a land" offer; a Shock's creature
    # sacrificed in response) left its slot to whatever moved into it, and the
    # arrow and ``target_permanent_name`` pointed at that permanent instead.
    # The ids also say which board each target is on ("For each opponent, gain
    # control of target permanent that player controls", Blatant Thievery). A
    # target no longer on the battlefield draws no arrow.
    placed = _targeted_permanents_now(item, game)
    if placed is not None:
        return [{"kind": "permanent", "seat": owner, "index": index} for owner, index, _perm in placed]

    indices = target_slots(item.target_permanent_index)
    if indices:
        for idx in indices:
            if isinstance(idx, int) and 0 <= idx < len(players[seat].battlefield):
                targets.append({"kind": "permanent", "seat": seat, "index": idx})
        return targets

    # No permanent chosen: the seat is a real target only if the text says so —
    # otherwise it is just the affected/controlling player the effect resolves on.
    text = (item.ability_text or spell_text_card(item).oracle_text or "").lower()
    if _TARGETS_PLAYER_RE.search(text):
        targets.append({"kind": "player", "seat": seat})
    return targets


def _serialize_stack_item(item, game: Game) -> dict:
    target_name = None
    if item.target_player_index is not None and 0 <= item.target_player_index < len(game.players):
        if item.card.primary_type in ("instant", "sorcery"):
            target_name = game.players[item.target_player_index].name
    item_type = "ability" if item.is_ability else "spell"
    # CR 113.3c, read off how the object reached the stack
    # (``StackItem.ability_kind``) — never off the effect label, whose
    # ``triggered_`` prefix every `upkeep_effect` trigger lacks and every
    # `triggered_counter` activation carries.
    is_triggered = item.ability_kind == "triggered"
    # An ability is named by its source as it is now (CR 707.2): a Clone
    # copying Prodigal Sorcerer activates a *Prodigal Sorcerer's* ability. The
    # stack object keeps the printed card for its art, as the permanent does.
    source_name = (
        item.source_permanent.effective_card.name
        if item.is_ability and item.source_permanent is not None
        else item.card.name
    )
    label = item.card.name if item_type == "spell" else f"{source_name} ability"

    target_permanent_name = None
    target_permanent_seat = None
    # The wire's slot field: one slot bare, several as a list — read off the
    # holder's one shape (``game_types.target_slots``) by how many it holds.
    slots = target_slots(item.target_permanent_index)
    several = len(slots) > 1
    target_permanent_index = slots if several else single_slot(slots)
    placed = _targeted_permanents_now(item, game)
    if placed is not None:
        # By id, for the reason ``_stack_item_targets`` gives: the stored slot
        # names whatever moved into it once the target left.
        if several:
            target_permanent_index = [index for _owner, index, _perm in placed]
        else:
            target_permanent_index = placed[0][1] if placed else None
        if placed and not several:
            target_permanent_seat, _index, first = placed[0]
            target_permanent_name = first.effective_card.name
    elif single_slot(slots) is not None and item.target_player_index is not None:
        p_idx = item.target_player_index
        slot = single_slot(slots)
        if 0 <= p_idx < len(game.players):
            bf = game.players[p_idx].battlefield
            if 0 <= slot < len(bf):
                target_permanent_name = bf[slot].effective_card.name
                target_permanent_seat = p_idx

    source_permanent_seat = None
    source_permanent_index = None
    if item.source_permanent is not None:
        for seat_idx, player in enumerate(game.players):
            for perm_idx, perm in enumerate(player.battlefield):
                if perm is item.source_permanent:
                    source_permanent_seat = seat_idx
                    source_permanent_index = perm_idx
                    break
            if source_permanent_index is not None:
                break

    # A Lace card (Lifelace, Chaoslace, …) that targeted this spell on the stack
    # recolored it, recorded on the stack item by
    # ``color_changes.recolor_spell`` (the effective color the engine
    # reads via _stack_item_colors). Surface it as color_override so the canvas
    # badges the floating stack card exactly like a recolored permanent, and
    # swap the displayed colors to match "becomes [color]".
    #
    # Read through the engine's reader rather than off the item's key: the
    # record is two stamped slots now (an indefinite lace, a Blind Seer's
    # "until end of turn"), and which of them the spell *is* is CR 613.7's
    # answer, not the first key found. The wire keeps the one symbol the canvas
    # badges from — "C", the swatch it already has, for a spell an effect made
    # colourless (Ersatz Gnomes), and the first of several.
    serialized_card = _serialize_card(item.card)
    # A text change on the spell (CR 612), in a permanent's ``text_changes`` shape.
    spell_edits = changed_words(item)
    if spell_edits:
        serialized_card["text_changes"] = spell_edits
    # The spell's colours as the engine reads them (``_stack_item_colors``):
    # a Lace's recolour, else its controller's Celestial Dawn ("the same is
    # true for spells you control"), else the printed ones.
    serialized_card["colors"] = list(game._stack_item_colors(item))
    override = spell_color_change(item)
    recolored = None
    if override is not None:
        recolored = override[0] if override else "C"
        serialized_card["color_override"] = recolored
        serialized_card["colors"] = list(override)

    return {
        "type": item_type,
        "is_triggered": is_triggered,
        "label": label,
        "card": serialized_card,
        "color_override": recolored,
        "caster_index": item.caster_index,
        "caster_name": game.players[item.caster_index].name,
        "target_player_index": item.target_player_index,
        "target_player_name": target_name,
        # Derived rather than stored: it was a second copy of the target's name
        # sitting beside the reference it came from.
        "target_stack_name": (
            item.target_stack_item.card.name if item.target_stack_item is not None else None
        ),
        "target_permanent_index": target_permanent_index,
        "target_permanent_name": target_permanent_name,
        "target_permanent_seat": target_permanent_seat,
        "targets": _stack_item_targets(item, game),
        "source_permanent_seat": source_permanent_seat,
        "source_permanent_index": source_permanent_index,
        "ability_text": item.ability_text,
        "x_value": item.x_value,
        # Its instructions have run; it is on the stack only because a prompt
        # it armed is still owed (CR 608.2). The client can say "resolving"
        # rather than drawing an object that looks like it has yet to resolve.
        "resolution_held": item.resolution_held,
    }
