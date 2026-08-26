"""Engine object to client JSON, one function per kind of object.

The leaves of the state payload: cards, permanents, counters, modal modes,
stack items, emblems, a player. Characteristics are read through the engine's
layer accessors rather than off the printed card, so a granted keyword or a
switched P/T shows up here the way the rules say it should.

Assembling a *whole* state payload lives in :mod:`web.state_view`, one layer up
— it needs the pregame, turn-step and combat modules, which need these leaves.
"""

from __future__ import annotations

import re

from engine import Game
from engine.activation_permissions import card_widens_activation
from engine.legality import cast_target_kind
from engine.models import Permanent, PlayerState
from engine.library_top import top_is_public
from engine.oracle import LOYALTY_ANY_TIME_STATIC, compile_card_oracle
from engine.hand_locks import locked_hand_indices
from engine.revealed_hands import hand_revealed_to
from engine.subject_filters import filter_head_noun
from engine.targeting import bounce_subject_filter, usable_activated_abilities
from engine.text_changes import changed_words

from .runtime import CARD_BY_NAME
from .seats import _player_has_lost


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
)

# Color symbol → display word, for spelling out protection qualities on the card.
_SYMBOL_TO_COLOR_WORD = {"W": "white", "U": "blue", "B": "black", "R": "red", "G": "green"}


def _effective_keywords(perm: Permanent, game: Game) -> list[str]:
    """The keywords a permanent currently has, reflecting grants and removals.

    Each candidate is resolved through ``game._has_keyword`` so aura-granted and
    "until end of turn" keywords show up, and Layer 6 removal effects (e.g.
    Earthbind stripping Flying) take it back off.

    The combat keywords are creature-only, but Indestructible is not: Guardian
    Beast grants it to noncreature artifacts and Consecrate Land to a land, and
    a player can't see that it applies unless the card says so.

    "Protection" is spelled out with the quality it's from (e.g. "Protection
    from white") so the player can see which color the permanent is protected
    against, not just that it has protection.
    """
    if "creature" not in perm.card.type_line.lower():
        return ["Indestructible"] if game._is_indestructible(perm) else []
    keywords = [kw for kw in _DISPLAY_KEYWORDS if game._has_keyword(perm, kw)]
    if game._is_indestructible(perm):
        keywords.append("Indestructible")
    # Protection is driven by the effective protected colors (CR 702.16) rather
    # than the printed keyword, so a quality granted by another card (e.g. White
    # Ward) shows up and is spelled out — "Protection from white".
    colors = sorted(game._protection_colors(perm))
    if colors:
        words = [_SYMBOL_TO_COLOR_WORD.get(symbol, symbol) for symbol in colors]
        label = "Protection from " + " and ".join(words)
        keywords = [kw for kw in keywords if kw != "Protection"]
        keywords.append(label)
    else:
        keywords = [kw for kw in keywords if kw != "Protection"]
    return keywords


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
    return {
        "name": card.name,
        "type": card.type_line,
        "oracle_text": card.oracle_text,
        "image_uri": image_uri,
        "large_image_uri": large_image_uri,
        "art_crop": art_crop,
        "colors": list(card.colors),
    }


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

    return {
        # Stable identity (CR 400.7), unique across every seat and unchanged for
        # as long as this permanent is on the battlefield. The client's handle on
        # a card: an *index* into this array is only valid until the next poll,
        # because anything leaving the battlefield renumbers the rest, and the
        # canvas holds addresses across polls (selection, hover, the attacker it
        # is dragging an arrow from). A permanent that leaves and returns is a
        # new object and gets a new id, so a held id can never quietly start
        # naming something else.
        "id": perm.permanent_id,
        "name": perm.card.name,
        # CR 903.3: this permanent is the designated commander card itself —
        # never a token copy or another same-name card. Drawn as a crown badge
        # and named in the card preview.
        "is_commander": game.is_commander_permanent(perm),
        # Effective type line so a copy shows its copied types (a Copy Artifact
        # copying a Mox reads "Artifact Enchantment", not just "Enchantment").
        "type": perm.effective_card.type_line,
        "tapped": perm.tapped,
        "colors": effective_colors,
        # True for printed creatures and for animated lands (Kormus Bell / Living
        # Lands) so the UI shows their P/T and lets them be declared as attackers.
        "is_creature": game._is_creature(perm),
        "power": perm.effective_power,
        "toughness": perm.effective_toughness,
        "base_power": _printed_stat(perm.card, "power"),
        "base_toughness": _printed_stat(perm.card, "toughness"),
        "mana_cost": perm.card.mana_cost,
        # A copy (Clone / Vesuvan Doppelganger) shows — and the UI activates —
        # the copied card's abilities, so its text is the effective text.
        "oracle_text": perm.effective_card.oracle_text,
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
        "is_aura": "aura" in perm.card.type_line.lower(),
        "attached_to_index": attached_to_index,
        "attached_to_id": attached_to_id,
        "attached_to_seat": attached_to_seat,
        "produced_mana": list(perm.effective_produced_mana),
        # A color-changing effect (e.g. Lifelace: "Target ... becomes green.")
        # records the new color so the UI can label the recolored permanent.
        "color_override": perm.metadata.get("color_override"),
        # Corpse counters (Scavenging Ghoul) so the canvas can render them. Folded
        # into a generic ``counters`` map so future counter types render for free.
        "corpse_counters": int(perm.metadata.get("corpse_counters", 0)),
        "counters": _serialize_counters(perm),
        # Activated abilities granted by another permanent's static ability
        # (Zombie Master's '{B}: Regenerate this permanent.'), which the printed
        # oracle text doesn't show — the UI needs these to offer activation.
        "granted_abilities": (
            ["{B}: Regenerate this permanent."]
            if perm.metadata.get("granted_regen_ability")
            else []
        ),
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


# Maps an effect instruction kind to the client target-prompt kind a modal mode
# uses, so the UI can route the right targeting flow after a mode is chosen.
_MODE_TARGET_KIND_OVERRIDES = {
    "counter_top_stack_spell": "stack",
    "copy_top_stack_spell": "stack",
}


def _mode_target_kind(instruction) -> str:
    """The client targeting kind for one modal mode's instruction."""
    if instruction is None:
        return "none"
    kind = instruction.kind
    if kind in _MODE_TARGET_KIND_OVERRIDES:
        return _MODE_TARGET_KIND_OVERRIDES[kind]
    if kind == "destroy_target_permanent":
        type_filter = instruction.payload.get("type_filter")
        if type_filter == "creature":
            return "creature"
        if type_filter == "artifact":
            return "artifact"
        return "permanent"
    if kind == "bounce_target_creature":
        # "…or return target Island to its owner's hand" (Active Volcano,
        # Flash Flood). The printed noun is payload, so the picker's kind is
        # read off the filter the lowering carried rather than off the
        # instruction's name — which says "creature" and would have sent a
        # Mountain-bouncing mode to the fall-through below and offered the
        # caster a *player*.
        return filter_head_noun(bounce_subject_filter(instruction.payload))
    if kind == "grant_prevention_shield":
        # "...dealt to you this turn" goes to the controller (no target choice);
        # "...dealt to any target" lets the caster shield a creature or a player.
        if instruction.payload.get("to_self") or instruction.payload.get("protection_kind"):
            return "none"
        return "any"
    # Life gain / loss, draws, discards, etc. all designate a target player.
    return "player"


def _mode_target_flags(instruction) -> dict:
    """Extra target filters for a modal mode (e.g. a colour-restricted destroy),
    passed to the legality enumerator so each mode highlights the right targets."""
    if instruction is not None and instruction.kind == "destroy_target_permanent":
        color_filter = instruction.payload.get("color_filter")
        if color_filter:
            return {"color_filter": color_filter}
    if instruction is not None and instruction.kind == "bounce_target_creature":
        # Everything the noun said past its head word — "Island", "nonland" —
        # travels as the enumerator's own ``filter``, which it tests with the
        # same ``subject_matches`` the cast gate and the handler ask. Without it
        # the mode would highlight every permanent and then refuse the cast on
        # all but one of them.
        described = bounce_subject_filter(instruction.payload)
        if described:
            return {"filter": described}
    return {}


def _serialize_modes(card, game: Game | None = None, caster_index: int | None = None) -> list[dict]:
    """Selectable modes of a "Choose one —" modal spell, or [] when not modal.

    When ``game``/``caster_index`` are supplied (the viewer's own hand), each mode
    also carries the backend-computed ``valid_targets`` for its target kind so the
    UI can highlight legal targets after a mode is chosen."""
    program = compile_card_oracle(card)
    if not program.modes:
        return []
    modes = []
    for index, mode in enumerate(program.modes):
        kind = _mode_target_kind(mode.instruction)
        entry = {
            "index": index,
            "label": mode.label,
            "supported": mode.supported,
            "target_kind": kind,
        }
        if game is not None and caster_index is not None and kind not in ("none",):
            entry["valid_targets"] = game.enumerate_targets_for_kind(
                caster_index, card, kind, **_mode_target_flags(mode.instruction)
            )
        else:
            entry["valid_targets"] = []
        modes.append(entry)
    return modes


def _apply_generic_tax_to_cost(cost_text: str, tax: int) -> str:
    """Fold ``tax`` extra generic mana into a printed cost string (e.g. Gloom's
    +{3} on white spells: '{W}' -> '{3}{W}', '{3}{R}' -> '{6}{R}')."""
    if tax <= 0:
        return cost_text
    tokens = re.findall(r"\{([^}]+)\}", cost_text or "")
    generic_idx = next((i for i, t in enumerate(tokens) if t.isdigit()), None)
    if generic_idx is not None:
        tokens[generic_idx] = str(int(tokens[generic_idx]) + tax)
    else:
        tokens = [str(tax)] + tokens
    return "".join("{" + t + "}" for t in tokens)


def _gloom_white_tax(card, game: Game | None) -> int:
    """The extra generic mana Gloom adds to a white spell's cost (0 otherwise)."""
    if game is None or "W" not in card.colors:
        return 0
    has_gloom = any(perm.card.name == "Gloom" for perm in game.all_permanents())
    return 3 if has_gloom else 0


def _serialize_card(card, game: Game | None = None, caster_index: int | None = None) -> dict:
    # Cost increasers (Gloom) are applied at payment time by the engine; reflect
    # them in the cost the UI shows and auto-taps for, so the pay-mana prompt
    # matches what the player actually pays. ``printed_mana_cost`` keeps the
    # unmodified printed value for reference.
    tax = _gloom_white_tax(card, game)
    effective_cost = _apply_generic_tax_to_cost(card.mana_cost, tax)
    serialized = _card_preview(card)
    serialized.update({
        "mana_cost": effective_cost,
        "printed_mana_cost": card.mana_cost,
        "effective_mana_cost": effective_cost,
        "cost_increased": tax > 0,
        "colors": list(card.colors),
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
    if game is not None and caster_index is not None:
        serialized["target_spec"] = game.cast_target_spec(caster_index, card)
    return serialized


def _serialize_card_summary(card) -> dict:
    serialized = _card_preview(card)
    serialized.update({
        "mana_cost": card.mana_cost,
        "modes": _serialize_modes(card),
        "modes_at_least": compile_card_oracle(card).modes_at_least,
    })
    return serialized


def _serialize_mana_pool(player: PlayerState) -> dict:
    mana = dict(player.mana_pool)
    for symbol in ("W", "U", "B", "R", "G", "C"):
        mana.setdefault(symbol, 0)
    return mana


# A stack item's own text targets a player (rather than merely naming one as the
# affected/controlling seat) — the gate for turning a bare target_player_index
# into a player-targeting arrow.
_TARGETS_PLAYER_RE = re.compile(r"target (?:player|opponent)|any target")


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
    divided = item.choices.get("divided_targets")
    if divided:
        for seat, idx in divided:
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

    raw = item.target_permanent_index
    indices = raw if isinstance(raw, list) else ([raw] if isinstance(raw, int) else [])
    if indices:
        for idx in indices:
            if isinstance(idx, int) and 0 <= idx < len(players[seat].battlefield):
                targets.append({"kind": "permanent", "seat": seat, "index": idx})
        return targets

    # No permanent chosen: the seat is a real target only if the text says so —
    # otherwise it is just the affected/controlling player the effect resolves on.
    text = (item.ability_text or item.card.oracle_text or "").lower()
    if _TARGETS_PLAYER_RE.search(text):
        targets.append({"kind": "player", "seat": seat})
    return targets


def _serialize_stack_item(item, game: Game) -> dict:
    target_name = None
    if item.target_player_index is not None and 0 <= item.target_player_index < len(game.players):
        if item.card.primary_type in ("instant", "sorcery"):
            target_name = game.players[item.target_player_index].name
    item_type = "ability" if (item.ability_instruction is not None or item.hook_key is not None) else "spell"
    is_triggered = bool(item.ability_effect_kind and item.ability_effect_kind.startswith("triggered_"))
    label = item.card.name if item_type == "spell" else f"{item.card.name} ability"

    target_permanent_name = None
    target_permanent_seat = None
    if isinstance(item.target_permanent_index, int) and item.target_player_index is not None:
        p_idx = item.target_player_index
        if 0 <= p_idx < len(game.players):
            bf = game.players[p_idx].battlefield
            if 0 <= item.target_permanent_index < len(bf):
                target_permanent_name = bf[item.target_permanent_index].card.name
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
    # recolored it, recorded on the stack item as ``choices["new_color"]`` (the effective
    # color the engine reads via _stack_item_colors). Surface it as color_override
    # so the canvas badges the floating stack card exactly like a recolored
    # permanent, and swap the displayed colors to match "becomes [color]".
    serialized_card = _serialize_card(item.card)
    new_color = item.choices.get("new_color")
    if new_color:
        serialized_card["color_override"] = new_color
        serialized_card["colors"] = [new_color]

    return {
        "type": item_type,
        "is_triggered": is_triggered,
        "label": label,
        "card": serialized_card,
        "color_override": new_color,
        "caster_index": item.caster_index,
        "caster_name": game.players[item.caster_index].name,
        "target_player_index": item.target_player_index,
        "target_player_name": target_name,
        # Derived rather than stored: it was a second copy of the target's name
        # sitting beside the reference it came from.
        "target_stack_name": (
            item.target_stack_item.card.name if item.target_stack_item is not None else None
        ),
        "target_permanent_index": item.target_permanent_index,
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


def _serialize_emblems(player: PlayerState) -> list[dict]:
    """Player-owned, non-card activated abilities granted until end of turn.

    Currently only Guardian Angel's "pay {1}: prevent the next 1 damage" emblem.
    Each emblem renders as a card-like token (with the source card's art) the
    controller can click to activate; the rich card fields drive the hover
    preview. `index` matches the engine list position used by activate_emblem."""
    emblems: list[dict] = []
    entries = player.prevent_one_damage_emblems
    if entries:
        source = CARD_BY_NAME.get("guardian angel")
        image_uri, large_image_uri, _art_crop = _card_image_uris(source) if source else (None, None, None)
        # The granted ability's reminder text — {1} renders as the mana symbol in
        # the preview, and names the fixed target ("that permanent or player").
        ability_text = (
            "Pay {1} any time you could cast an instant: Prevent the next 1 damage "
            "that would be dealt to that permanent or player this turn."
        )
        for index in range(len(entries)):
            emblems.append({
                "kind": "prevent_one_damage",
                "index": index,
                "label": "Pay {1}: prevent next 1",
                "name": "Guardian Angel",
                "source": "Guardian Angel",
                "type": "Emblem — Guardian Angel",
                "oracle_text": ability_text,
                "image_uri": image_uri,
                "large_image_uri": large_image_uri,
            })
    # Channel: "Until end of turn, any time you could activate a mana ability, you
    # may pay 1 life. If you do, add {C}." A synthetic emblem the controller clicks
    # to spend life for colorless mana while the effect is active.
    if player.channel_active_until_eot:
        source = CARD_BY_NAME.get("channel")
        image_uri, large_image_uri, _art_crop = _card_image_uris(source) if source else (None, None, None)
        emblems.append({
            "kind": "channel",
            "index": -1,  # not an activate_emblem index; the client uses channel_mana
            "label": "Pay 1 life: add {C}",
            "name": "Channel",
            "source": "Channel",
            "type": "Emblem — Channel",
            "oracle_text": (
                "Until end of turn, any time you could activate a mana ability, you "
                "may pay 1 life. If you do, add {C}."
            ),
            "image_uri": image_uri,
            "large_image_uri": large_image_uri,
        })
    # CR 114 emblems proper (planeswalker ultimates): passive triggered
    # abilities in the command zone. No `index` for activate_emblem — nothing
    # to click; the entry is informational, in the same card-like shape.
    for emblem in getattr(player, "emblems", ()):
        source = CARD_BY_NAME.get(str(emblem.get("source_name", "")).lower())
        image_uri, large_image_uri, _art_crop = _card_image_uris(source) if source else (None, None, None)
        emblems.append({
            "kind": "emblem",
            "index": -1,
            "label": emblem.get("name", "Emblem"),
            "name": emblem.get("name", "Emblem"),
            "source": emblem.get("source_name", ""),
            "type": "Emblem",
            "oracle_text": emblem.get("oracle_text", ""),
            "image_uri": image_uri,
            "large_image_uri": large_image_uri,
        })
    return emblems


def _hand_revealed_to_viewer(game: Game, viewer_seat: int | None, seat: int) -> bool:
    """Whether an in-progress effect reveals *seat*'s hand to *viewer_seat*:
    a pending hand reveal (Glasses of Urza) whose viewer is this seat, or a
    pending Word of Command whose caster is this seat. While one is active the
    target's hand serializes face-up for that viewer only.

    A *standing* effect can reveal it too — "Players play with their hands
    revealed." (Revelation, CR 701.20a) — derived from the battlefield by
    ``engine/revealed_zones.py``, so it starts and stops with the permanent."""
    if viewer_seat is None:
        return False
    if hand_revealed_to(game, seat, viewer_seat):
        return True
    reveal = game.pending_hand_reveal
    if (
        reveal is not None
        and reveal.get("viewer_index") == viewer_seat
        and reveal.get("target_index") == seat
    ):
        return True
    woc = game.pending_word_of_command
    if (
        woc is not None
        and woc.get("caster_index") == viewer_seat
        and woc.get("target_index") == seat
    ):
        return True
    return False


def _serialize_player(
    player: PlayerState,
    viewer_seat: int | None,
    seat: int,
    game: Game,
    playable_hand_indices: list[int] | None = None,
    playable_command_indices: list[int] | None = None,
) -> dict:
    if viewer_seat == seat:
        hand = [_serialize_card(card, game, seat) for card in player.hand]
    elif _hand_revealed_to_viewer(game, viewer_seat, seat):
        # An active reveal (Glasses of Urza's look, Word of Command's forced-play
        # choice) lets the viewer see this player's actual cards, so the opponent
        # hand fan renders real card faces instead of card backs.
        hand = [_serialize_card(card) for card in player.hand]
    else:
        # A hidden hand can still hold a face-up card: "that player plays with
        # that card revealed in their hand" (Firestorm Phoenix, CR 701.20a).
        # Per position rather than per hand, because the reveal is about one
        # card — the rest of the hand stays a hidden zone.
        revealed = locked_hand_indices(game, seat)
        hand = [
            _serialize_card(card) if index in revealed else "<hidden>"
            for index, card in enumerate(player.hand)
        ]

    permanents = list(game.controlled_by(seat))
    battlefield = [_serialize_permanent(perm, game) for perm in permanents]
    # The viewer's own permanents carry the target spec for their activated ability
    # (kind + legal targets) so the UI can drive activation targeting from backend
    # data rather than parsing the ability text client-side.
    if viewer_seat == seat:
        for idx, (perm, perm_dict) in enumerate(zip(permanents, battlefield)):
            perm_dict["target_spec"] = game.activation_target_spec(seat, idx)
            # Multi-ability permanents whose abilities target differently
            # (Pyramids): one spec per usable ability, indexed like the
            # ability_index the activate action takes.
            usable = usable_activated_abilities(compile_card_oracle(perm.effective_card))
            if len(usable) > 1:
                perm_dict["ability_target_specs"] = [
                    game.activation_target_spec(seat, idx, ability_index=k)
                    for k in range(len(usable))
                ]

    def _crowned(entries: list, cards) -> list:
        # CR 903.3: mark the designated commander card, wherever its zone
        # payload is visible. Identity-keyed, so a same-name card or a token
        # copy's card is never marked. Hidden hands are strings and skipped.
        for payload, card in zip(entries, cards):
            if isinstance(payload, dict) and game.is_commander_card(seat, card):
                payload["is_commander"] = True
        return entries

    return {
        "name": player.name,
        "life": player.life,
        # Eliminated but the game continues (Free-For-All): the client drops
        # this seat into spectator mode and skips it in targeting helpers.
        "lost": _player_has_lost(game, seat),
        # Damage-prevention shield protecting the player directly (Conservator,
        # Circle of Protection, Healing Salve's "to any target" mode, …).
        "damage_prevention_pool": player.damage_prevention_pool,
        "shield_source": _shield_source_payload(player.damage_prevention_source),
        # Color a Circle of Protection shield is set against (e.g. "R").
        "shield_color": player.damage_prevention_color,
        # Channel emblem: while active the player may pay life for {C} this turn.
        "channel_active": player.channel_active_until_eot,
        "hand": _crowned(hand, player.hand),
        "hand_count": len(player.hand),
        # Jandor's Ring: whether a card drawn this turn is still in hand, i.e.
        # whether its "Discard the last card you drew this turn" cost is payable.
        "has_last_drawn_card": player.last_card_drawn_this_turn() is not None,
        "deck": {"count": len(player.library)},
        "library_count": len(player.library),
        # A revealed top card of the library — "Players play with the top card
        # of their libraries revealed." (Field of Dreams, CR 401.5) or this
        # player's own "Play with the top card of your library revealed."
        # (Conspicuous Snoop). Revealed is revealed to everyone (CR 701.20a),
        # the owner included — playing this way shows them a card they could
        # not otherwise see — so the card face rides the payload for every
        # viewer while a source stands, and is absent otherwise.
        "library_top": (
            _serialize_card(player.library[0])
            if player.library and top_is_public(game, seat)
            else None
        ),
        # The viewer's own graveyard/exile carry the same target specs a hand
        # card does, because a cast permission (engine/cast_permissions.py) can
        # make one castable — and the cast prompts read the spec off the card.
        "graveyard": _crowned([
            _serialize_card(card, game, seat) if viewer_seat == seat else _serialize_card(card)
            for card in player.graveyard
        ], player.graveyard),
        "exile": _crowned([
            _serialize_card(card, game, seat) if viewer_seat == seat else _serialize_card(card)
            for card in player.exile
        ], player.exile),
        # The ante zone (CR 407) — public, like exile. Empty unless an ante card
        # (Contract from Below, Demonic Attorney, Jeweled Bird) has resolved.
        "ante": [_serialize_card(card) for card in player.ante],
        # The command zone (CR 408), public like the ante zone: CR 903.6 puts a
        # commander there *face up*. Serialized with the viewer's seat when it
        # is their own, because a commander in it is castable (CR 903.8) and the
        # cast prompt reads its target spec off the card exactly as a hand
        # card's. Empty outside a Commander game.
        "command_zone": _crowned([
            _serialize_card(card, game, seat) if viewer_seat == seat else _serialize_card(card)
            for card in player.command_zone
        ], player.command_zone),
        # CR 903.8: what each commander in that zone would cost extra to cast
        # right now, keyed by name, so the client can show the tax without
        # re-deriving "each previous time".
        "commander_tax": {
            card.name: game.commander_tax(seat, card) for card in player.command_zone
        },
        # CR 903.10a: combat damage this player has taken from each commander,
        # as a list so the client need not parse a tuple key. ``seat`` is the
        # commander's owner and ``name`` the commander.
        "commander_damage": [
            {"seat": owner, "name": name, "damage": dealt}
            for (owner, name), dealt in sorted(player.commander_damage_taken.items())
        ],
        # Cards owned from outside the game (CR 100.4). Private, like the hand:
        # only their owner sees what's in it, everyone sees the count.
        "sideboard": (
            [_serialize_card(card) for card in player.sideboard] if viewer_seat == seat else []
        ),
        "sideboard_count": len(player.sideboard),
        "battlefield": battlefield,
        "emblems": _serialize_emblems(player),
        "mana_pool": _serialize_mana_pool(player),
        # "Spend this mana only to…" (CR 106.6). Each restriction keeps its own
        # bucket so the UI can show it as a distinct, labelled tracker instead
        # of folding it into the ordinary pool — which would overstate what is
        # spendable. ``creature_only_mana`` is the first of these and keeps its
        # own key because the client already reads it by name.
        "creature_only_mana": {sym: n for sym, n in player.creature_only_mana.items() if n > 0},
        "restricted_mana": {
            key: {sym: n for sym, n in bucket.items() if n > 0}
            for key, bucket in (player.restricted_mana or {}).items()
            if any(n > 0 for n in bucket.values())
        },
        "playable_hand_indices": playable_hand_indices if viewer_seat == seat else [],
        # The same answer for the viewer's own command zone (CR 903.8): which
        # commanders they could cast right now, so the board highlights one the
        # way it highlights a castable card in hand. Distinct from
        # `castable_from_zones`, which says the zone is open at all.
        "playable_command_indices": playable_command_indices if viewer_seat == seat else [],
    }
