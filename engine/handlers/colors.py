"""The **colour** a resolving effect gives its subject (CR 105, CR 613 layer 5),
and the **text change** that rewrites a permanent's words (CR 612).

"Target spell or permanent becomes red" (the Lace cycle), "becomes the color
of your choice", "becomes white until end of turn" — of a target, a spell on
the stack, the source, an Aura's host. Every colour is written through
``engine/color_changes.py`` (``change_color``, ``recolor_spell``), which puts
the CR 613.7 timestamp inside the write.

``mark_text_modified`` sits beside them because the two are told apart by one
sentence each: Sleight of Mind rewrites a colour *word* in a permanent's text
and does not recolour it, Magical Hack rewrites a basic land type word, and
Mind Bend offers both (``engine/text_changes.py``).

The handler twin of ``engine/grammar/lowering/colors.py``. Split out of
``board_misc.py`` at the 2,000-line cap's split round.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..color_changes import change_color, recolor_spell
from ..oracle_types import (BLOCK_PAIR_SUBJECT, CHOSEN_COLOR_THIS_WAY,
                            SPELL_OR_OBJECT_TARGET, SUBJECT_FROM_TRIGGER)
from ..text_changes import LAND_TYPE_WORDS, change_color_word, change_land_word
from ._targets import (attached_host, block_pair_permanents,
                       resolve_target_permanent, resolve_target_permanents,
                       described_target_predicate)
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


# Mana symbol → the basic land type Magical Hack names. The chosen replacement
# type is passed through as the cast's "new color"; the mapping itself lives
# with the text-change API, which is what has to know the words.
_SYMBOL_TO_LAND_TYPE = LAND_TYPE_WORDS


@effect_handler("mark_text_modified")
def mark_text_modified(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    target = context.target
    card = context.card
    # The permanent the announcement named, **by id** (CR 400.7), through the
    # resolver every other targeted handler uses — "target permanent", so the
    # predicate is every permanent rather than its creature default. This read
    # the slot alone and fell back to the first permanent on that battlefield,
    # so a Sleight of Mind announced by id (which is how every target reaches
    # the engine from the wire once its slot has moved, and how a headless
    # caller names one at all) rewrote whatever stood first: aimed at a
    # Darkest Hour beside a Grizzly Bears, it "changed B text to W on Grizzly
    # Bears". The recolour handler below was moved off the slot for the same
    # reason; this one was left behind.
    target_perm = resolve_target_permanent(
        game, context, player=target, predicate=lambda p: True,
    )
    # "target **white enchantment you control that doesn't have cumulative
    # upkeep**" (Balduvian Shaman). The Lace cycle prints no narrowing at all
    # and carries no description, so this is the whole of the check for it; a
    # card that does print one is held to it here as well as at the picker, for
    # the reason the grant handlers in ``keywords.py`` state — a picker and a resolution
    # that disagree are a target the player may announce and the effect then
    # declines to affect.
    from ..subject_filters import subject_matches

    described = (instruction.payload.get("targets") or {}).get("filter") or {}
    if described and not subject_matches(
        game, target_perm, described,
        # CR 109.5: "you control" is the seat whose ability this is, and
        # `context.caster` is that seat for a spell and an activation alike.
        observer=game.seat_index(context.caster),
        source=context.source_permanent,
    ):
        game.log.append(f"{card.name}: no legal permanent to change the text of")
        return True, "resolved"
    if target_perm is not None:
        target_perm.metadata["text_modified"] = True

    mode = instruction.payload.get("mode")
    new_symbol = (context.choices.get("new_color") or "").upper()
    old_symbol = (context.choices.get("old_color") or "").upper()
    # "…**until end of turn**." (Whim of Volrath.) Absent for every card printed
    # before it, which is what "This effect lasts indefinitely" means on the
    # other three -- so the record they write is byte-identical to what it was.
    # It travels with every branch below, the vocabulary prompt included: a
    # duration dropped on the way to the record is an effect printed to end and
    # lasting the rest of the game.
    duration = instruction.payload.get("duration")

    # Magical Hack: "replacing all instances of one basic land type with
    # another". One text change (CR 612.1 / 613 layer 3), whatever the permanent
    # is: on a land the word is in the type line, so the land's subtypes and the
    # mana ability CR 305.6 gives it change; on a creature it is in the rules
    # text, so "swampwalk" becomes "islandwalk" — including inside a lord's
    # grant line. It does NOT change the permanent's color.
    # "…replacing all instances of one color word with another **or** one basic
    # land type with another." (Mind Bend.) The card offers both vocabularies
    # and its controller picks (CR 612.1) — a decision made as the spell
    # resolves, so it goes on the pending-choice queue rather than being
    # guessed here. The words themselves were already named at the cast, and
    # both readings of a mana symbol are legal: "R" is red *and* Mountain.
    if mode == "color_word_or_land_type":
        if target_perm is None:
            game.log.append(f"{card.name}: no permanent to change the text of")
            return True, "resolved"
        game.arm_text_change_vocabulary(
            game.seat_index(context.caster), target_perm,
            old_symbol, new_symbol, card.name, duration=duration,
        )
        return True, "resolved"

    if mode == "land_type":
        new_type = _SYMBOL_TO_LAND_TYPE.get(new_symbol)
        old_type = _SYMBOL_TO_LAND_TYPE.get(old_symbol)
        if old_type is None and target_perm is not None:
            # A cast that named only the replacement (a headless or AI cast, and
            # every call site before the "from" word existed): on a land the
            # word being replaced can only be the type it currently has.
            current = target_perm.basic_land_types
            old_type = current[0] if len(current) == 1 else None
        if target_perm is not None and new_type and old_type:
            # Magical Hack rewrites existing words: the old land type must
            # actually be written somewhere on the permanent. That covers a
            # printed type line ("Basic Land — Mountain"), a printed landwalk
            # (Bog Wraith's "Swampwalk") and a land word inside a granted
            # ability (Goblin King's "Other Goblins … have mountainwalk") — but
            # never grants islandwalk from nothing (White Knight). The
            # *effective* text, so a second Hack rewrites what the first wrote.
            effective = target_perm.effective_card
            written = " ".join(
                (effective.type_line, effective.oracle_text, *effective.keywords)
            ).lower()
            if old_type in written:
                change_land_word(
                    target_perm, old_type, new_type, label=card.name,
                    duration=duration,
                )
                game.log.append(
                    f"{card.name} changed {old_type} to {new_type} in {target_perm.card.name}'s text"
                )
                game._recalculate_lord_buffs()
            else:
                game.log.append(
                    f"{card.name} had no effect: {target_perm.card.name} has no"
                    f" {old_type.title()} land type in its text"
                )
        return True, "resolved"

    # Sleight of Mind: replace one color word with another in the target's text.
    # Recorded as an ordered layer-3 contribution and applied once, by
    # Permanent.effective_card. It does NOT recolor the permanent.
    if mode == "color_word":
        if target_perm is not None and change_color_word(
            target_perm, old_symbol, new_symbol, label=card.name,
            duration=duration,
        ):
            game.log.append(f"{card.name} changed {old_symbol} text to {new_symbol} on {target_perm.card.name}")
        return True, "resolved"

    game.log.append(f"{card.name} applied a text change effect")
    return True, "resolved"


@effect_handler("recolor_target_from_text")
def recolor_target_from_text(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    symbol = str(instruction.payload.get("target_color", ""))
    # "Target spell or permanent becomes [color]" — a spell on the stack is a
    # legal target (the Lace cards). Recolor it via the stack item's color
    # override — its own key, never ``new_color``: that one is what the spell
    # was announced with (a text change's word, a mana spell's colour), and one
    # key for both made every such spell the colour it announced.
    if context.stack_target is not None and symbol:
        # A phrase that names a spell *and its types* ("target instant spell
        # becomes colorless") is re-asked here (CR 608.2b), through the reader
        # the picker offered it with. The undescribed Lace union and the bare
        # "target spell" carry no type and are untouched.
        described = instruction.payload.get("targets") or {}
        if described.get("card_types") and not stack_target_still_described(
            game, described, context.stack_target
        ):
            game.log.append(f"{context.card.name}: no valid spell to recolour")
            return True, "resolved"
        recolor_spell(context.stack_target, symbol)
        game.log.append(f"{context.stack_target.card.name} (on the stack) became {symbol}")
        return True, "resolved"
    # "…that creature becomes green" on a block trigger (Aisling Leprechaun):
    # nobody targeted it, the firing bound it, and which half fired decides how
    # it is found — `block_pair_permanents` is the one reader of that.
    if instruction.payload.get(SUBJECT_FROM_TRIGGER) == BLOCK_PAIR_SUBJECT:
        # The permanent is already in hand, so the indefinite colour effect is
        # recorded on it at once — the same write `_apply_color_override` makes
        # for a targeted lace, the same layer 5 read (`engine/layer_bridge.py`),
        # and no duration: Aisling Leprechaun's reminder text says the effect
        # lasts indefinitely.
        recoloured = block_pair_permanents(game, context) if symbol else []
        for perm in recoloured:
            change_color(perm, symbol)
            game.log.append(f"{perm.card.name} became {symbol} ({context.card.name})")
        if not recoloured:
            game.log.append(f"{context.card.name}: no creature to recolour")
        return True, "resolved"
    # The Lace cycle's permanent half, resolved by id — "target permanent", so
    # the predicate is every permanent rather than the resolver's creature
    # default. The index it used to pass named a slot, and a slot is not a
    # target once anything has left the battlefield (CR 400.7).
    changed = game._apply_color_override(
        resolve_target_permanent(
            game, context, player=context.target, predicate=lambda p: True,
        ),
        symbol,
    ) if symbol else False
    game.log.append("Changed target color" if changed else "No valid permanent to recolor")
    return True, "resolved"


@effect_handler("recolor_target_chosen_color")
def recolor_target_chosen_color(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target permanent you control becomes the color of your choice."
    (Alchor's Tomb.)

    A colour *replacement* like the lace kind beside it, and indefinite like
    Aisling Leprechaun's — the difference is only where the colour comes from.
    CR 608.2d makes the choice part of the effect, so nothing in the text names
    it: the ``choose_color`` step the lowering puts in front of this one asks
    the ability's controller while the effect is applied, and the answer is
    read off this resolution's scratchpad (``CHOSEN_COLOR_THIS_WAY``) — the
    record Feat of Resistance's "protection from the color of your choice"
    reads too. An unanswered choice recolours nothing rather than defaulting to
    a colour: a permanent that became a colour nobody picked is the wrong
    colour, and doing nothing is the honest failure.

    The printed noun phrase is enforced here, not assumed. The filter travels on
    the payload and is asked through ``subject_matches`` because "you control" is
    a seat rather than a property of the card — dropping it would let the ability
    recolour an opponent's permanent, which is a restriction the picker showed
    and the resolution ignored.
    """
    from ..subject_filters import subject_matches

    described = instruction.payload.get("targets") or {}
    if described.get("kind") == "spell":
        # "{T}: Target instant or sorcery **spell** becomes the color of your
        # choice." (Vodalian Mystic.) An object on the stack rather than on the
        # battlefield, so it is the half of the context a counter reads — and
        # only that half: falling back to a permanent would recolour whatever
        # the resolver could reach for an ability that named a spell.
        return _recolor_stack_target_chosen_color(game, instruction, context)
    if (
        described.get("kind") == SPELL_OR_OBJECT_TARGET
        and context.stack_target is not None
    ):
        # "Target **spell or permanent** becomes the color of your choice until
        # end of turn." (Illusion, Blind Seer.) One target in one of two zones,
        # and which one is what the announcement named: a stack object in the
        # context is the answer "a spell", and it is the whole answer — a spell
        # that has since left is CR 608.2b's illegal target, never a reason to
        # go looking on the battlefield. That scan is what this card did while
        # the union was unread: named a Lightning Bolt, recoloured the Grizzly
        # Bears beside it.
        return _recolor_stack_target_chosen_color(game, instruction, context)
    filters = described.get("filter") or {}
    observer = game.players.index(context.caster)
    target = resolve_target_permanent(
        game, context,
        predicate=lambda perm: subject_matches(game, perm, filters, observer=observer),
        fallback_on_invalid_choice=False,
    )
    if target is None:
        game.log.append(f"{context.card.name}: no valid permanent to recolour")
        return True, "resolved"
    if instruction.payload.get("several"):
        # "Target permanent becomes the color **or colors** of your choice."
        # (Prismatic Lace.) A *set* is offered, and the one-colour step the
        # single offer is asked through names one symbol — so the question goes
        # on the standing queue, the same prompt Shyft's trigger already uses
        # one branch over. A single symbol is one legal answer to the offer and
        # not the offer itself: taking it would quietly make "or colors" mean
        # "a color" on every printing.
        # "**Your** choice" is the spell's controller (CR 109.5), never the
        # permanent's — Prismatic Lace is aimed at any permanent on the table
        # and the colour is picked by whoever cast it.
        game.arm_color_set_choice(
            observer,
            permanent=target,
            card_name=context.card.name,
            several=True,
        )
        return True, "resolved"
    symbol = game._normalize_mana_color(context.results.get(CHOSEN_COLOR_THIS_WAY))
    if symbol is None:
        game.log.append(
            f"{context.card.name}: no colour was chosen, so nothing is recoloured"
        )
        return True, "resolved"
    # "…**until end of turn**" (Distorting Lens). The turn-long layer-5 slot
    # rather than the indefinite one — layer_bridge reads both and the cleanup
    # step sweeps this one, so a permanent laced permanently earlier in the game
    # keeps its colour when the Lens wears off. Which slot is written is the
    # printed duration and nothing else, which is why the key is read here
    # rather than inferred from the card.
    change_color(target, symbol, until_eot=bool(instruction.payload.get("until_eot")))
    game.log.append(
        f"{target.card.name} became {symbol}"
        + (" until end of turn" if instruction.payload.get("until_eot") else "")
        + f" ({context.card.name})"
    )
    return True, "resolved"


def stack_target_still_described(game: Game, described: dict, item) -> bool:
    """Whether *item* is still a spell the printed phrase *described* names.

    CR 608.2b at the one place a handler can ask it: the object must still be
    on the stack, must be a spell (an ability has no card and no colour,
    CR 113.7a) and must still be one of the printed card types — through
    ``_spell_is_one_of``, the reader the stack picker offered it with, so the
    announcement and the resolution cannot name different sets.
    """
    # By identity: ``StackItem`` compares by value, and two casts of one card
    # at one target are equal.
    if item is None or not any(obj is item for obj in game.stack):
        return False
    if getattr(item, "ability_instruction", None) is not None or item.card is None:
        return False
    card_types = described.get("card_types")
    if card_types:
        from .stack import _spell_is_one_of

        return _spell_is_one_of(item.card, card_types)
    return True


def _recolor_stack_target_chosen_color(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """The spell half of ``recolor_target_chosen_color``.

    The colour is the one the ``choose_color`` step in front recorded while
    this ability resolved (CR 608.2d), and it is written to the spell's own
    colour record — the one the Lace cycle writes and ``_stack_item_colors``
    reads (``color_changes.recolor_spell``). One record, so a spell this made
    blue is blue to Blue Elemental Blast, to protection, to Jaded Response's
    "shares a color" and to the cast triggers that ask a colour.

    A replacement, not an addition (CR 105.3): the spell is the chosen colour
    and no other. With no printed duration it lasts indefinitely (CR 611.2a),
    on the spell and on the permanent the spell becomes (CR 400.7a); with
    "until end of turn" (Illusion, Blind Seer) it ends at cleanup, which a
    spell never sees and the permanent it became does.

    An unanswered choice recolours nothing, for the permanent half's reason: a
    spell that became a colour nobody picked is the wrong colour.
    """
    described = instruction.payload.get("targets") or {}
    item = context.stack_target
    name = context.card.name
    if not stack_target_still_described(game, described, item):
        game.log.append(f"{name}: no valid spell to recolour")
        return True, "resolved"
    symbol = game._normalize_mana_color(context.results.get(CHOSEN_COLOR_THIS_WAY))
    if symbol is None:
        game.log.append(f"{name}: no colour was chosen, so nothing is recoloured")
        return True, "resolved"
    until_eot = bool(instruction.payload.get("until_eot"))
    recolor_spell(item, symbol, until_eot=until_eot)
    game.log.append(
        f"{item.card.name} (on the stack) became {symbol}"
        + (" until end of turn" if until_eot else "")
        + f" ({name})"
    )
    return True, "resolved"


@effect_handler("recolor_self_chosen_color")
def recolor_self_chosen_color(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"You may have this creature become the color or colors of your choice."
    (Shyft.)

    The third subject in the chosen-colour family, and the only one on a
    *triggered* ability — but not the only one that asks: CR 608.2d puts every
    one of these choices in the resolution, so the activated two ask exactly as
    this does (Dream Coat on this same prompt, Alchor's Tomb through the
    one-colour step in front of it). Here it is the standing
    ``color_set_choice`` prompt, on the ability's controller.

    The prompt takes a **set**, because "the color **or colors**" offers one
    (CR 105.2 makes a two-coloured object one object). Layer 5 has written a
    tuple since Dream Coat; what did not exist was a way for a player to name
    more than one.
    """
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    seat = game.controller_index_of(source_permanent)
    if seat is None:
        return True, "resolved"
    game.arm_color_set_choice(
        seat,
        permanent=source_permanent,
        card_name=context.card.name,
        several=bool(instruction.payload.get("several")),
    )
    return True, "resolved"


@effect_handler("recolor_enchanted_chosen_color")
def recolor_enchanted_chosen_color(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Enchanted creature becomes the color or colors of your choice."
    (Dream Coat.)

    The sibling of ``recolor_target_chosen_color`` above, differing only in
    *which* permanent it recolours: an Aura's activated ability acts on what it
    is attached to (CR 303.4), which the activator does not choose. Read as a
    target the sentence refused and the ability compiled to nothing.

    CR 608.2d puts the colour choice in the resolution, so it is **asked
    here**, on the standing ``color_set_choice`` prompt Shyft and Prismatic
    Lace already use — the same offer on the same permanent channel, aimed at
    the Aura's host. ``several`` says the card offered a *set* (CR 105.2, "the
    color **or colors**"), which that prompt takes whole; a one-symbol answer is
    one legal answer to the offer rather than a narrowing of it.

    It used to read the answer off the activation (``choices["new_color"]``),
    which CR 602.2b does not announce: an interactive seat was never asked, a
    client that sent no colour recoloured nothing, and the player named the
    colour before the opponent could respond rather than after.
    """
    source_permanent = context.source_permanent
    if source_permanent is None:
        return False, "ability not implemented"
    # Last-known information (CR 608.2h): the ability exists independently of
    # the Aura (CR 113.7a), so a Dream Coat destroyed in response still
    # recolours the creature it was on. The live record is cleared by the
    # Aura's teardown before this runs; ``attached_host`` reads both.
    enchanted = attached_host(game, source_permanent)
    if enchanted is None:
        return False, "aura not attached to a permanent"
    # "**You**" is the ability's controller (CR 109.5) — the seat that
    # activated it — never the creature's: Dream Coat on an opponent's creature
    # is still its controller's choice.
    game.arm_color_set_choice(
        game.players.index(context.caster),
        permanent=enchanted,
        card_name=context.card.name,
        several=bool(instruction.payload.get("several")),
    )
    return True, "resolved"


@effect_handler("recolor_targets_until_eot")
def recolor_targets_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"One or more target creatures become <colour> until end of turn."
    (Dwarven Song, Heaven's Gate, Sea Kings' Blessing, Sylvan Paradise, Touch of
    Darkness.)

    A colour *replacement* like the Lace cycle above (CR 105.2: "becomes" is
    not "in addition"), but with a duration and with several targets. It writes
    the until-end-of-turn channel, which layer 5 reads beside the indefinite one
    and the cleanup step sweeps — so a creature laced permanently earlier in the
    game keeps its colour when this wears off.

    A target that is no longer legal is simply skipped (CR 608.2b); the rest of
    the effect still happens, which is what `resolve_target_permanents` gives
    without a per-slot fallback that would recolour the same creature twice.

    **A target is whatever the printed noun phrase admits.** "{T}: Target
    **permanent** becomes colorless until end of turn." (Ersatz Gnomes; Aurora
    Griffin prints it with "white".) The resolver's default is a creature, so
    an enchantment, an artifact or a land the player aimed at was dropped and
    the ability resolved as "no creature to recolour" with its cost paid.
    """
    written = _colour_to_write(game, instruction, context)
    if written is None:
        return True, "resolved"
    targets = resolve_target_permanents(
        game, context,
        predicate=described_target_predicate(game, instruction, context),
    )
    if not targets:
        game.log.append(f"{context.card.name}: nothing to recolour")
        return True, "resolved"
    for perm in targets:
        change_color(perm, written, until_eot=True)
        game.log.append(
            f"{perm.card.name} became {_colour_override_word(written)} until end "
            f"of turn ({context.card.name})"
        )
    return True, "resolved"


def _colour_override_value(printed):
    """What a "becomes <colour>" payload writes into the layer-5 channel.

    A mana symbol for a colour, and the **empty tuple** for colourless: CR 105.2c
    makes colourless the absence of colour, so the object is given no colours
    rather than a sixth one. That is why `collect_color_effects` tests the key
    against None rather than for truthiness — an empty set of colours is a real
    answer, and every writer of the channel already refuses to write a falsy
    symbol by accident.

    None when the payload names nothing at all, which is the "do nothing" the
    truthiness test used to give and the one case that is not a colour change.
    """
    from ..grammar.ast import COLORLESS

    if printed == COLORLESS:
        return ()
    symbol = str(printed or "")
    return symbol or None


def _colour_override_word(written) -> str:
    """The channel value as the log should print it."""
    return "colorless" if written == () else str(written)


def _colour_to_write(game, instruction, context):
    """The colour a turn-long recolour writes: the printed one, or the one the
    step in front of it chose.

    "…become **the color of your choice** until end of turn" (Sway of Illusion,
    Kavu Chameleon, Rainbow Crow) names its colour while the effect is applied
    (CR 608.2d), so the payload carries ``color_from`` — the scratchpad slot
    the ``choose_color`` step wrote — where a printed colour carries
    ``target_color``. An unanswered choice writes **nothing**, for
    ``recolor_target_chosen_color``'s reason: a permanent that became a colour
    nobody picked is the wrong colour.
    """
    chosen_from = instruction.payload.get("color_from")
    if chosen_from is None:
        return _colour_override_value(instruction.payload.get("target_color"))
    symbol = game._normalize_mana_color(context.results.get(str(chosen_from)))
    if symbol is None:
        game.log.append(
            f"{context.card.name}: no colour was chosen, so nothing is recoloured"
        )
    return symbol


@effect_handler("recolor_self_until_eot")
def recolor_self_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"{2}: This creature becomes colorless until end of turn." (Raging Spirit.)

    The source-subject twin of ``recolor_targets_until_eot``: same channel, same
    sweep, and no target to resolve because the sentence names none.
    """
    written = _colour_to_write(game, instruction, context)
    source = context.source_permanent
    if written is None or source is None:
        return True, "resolved"
    change_color(source, written, until_eot=True)
    game._recompute_continuous_effects()
    game.log.append(
        f"{source.card.name} became {_colour_override_word(written)} until end of turn"
    )
    return True, "resolved"
