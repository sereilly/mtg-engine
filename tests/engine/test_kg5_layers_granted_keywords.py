"""A keyword granted as a line is the keyword (CR 613.1f, layer 6).

"That enchantment gains "Cumulative upkeep {1}."" (Balduvian Shaman.) What a
quoted grant gives is a line, folded into the permanent's text
(``keywords.GRANTED_ABILITY_LINES``, ``Permanent.effective_card``), and the
compiler makes the ability out of it — the enchantment pays the upkeep. But
layer 6's *word* set is seeded from that same text
(``printed_characteristics._printed_abilities_cached``) by a fixed substring
list (``_TEXT_KEYWORDS``) and otherwise only from the ingested ``keywords``
field, which a granted line has no part in. So the Circle had the ability and
not the keyword: ``has_keyword("cumulative upkeep")`` was False, and the
Shaman's own "that doesn't have cumulative upkeep" kept offering it.

The seed was blind in a second place the census found: only the **creature**
front end emits ``keyword_line`` instructions. The non-creature one claims a
keyword line and emits nothing, so an enchantment's or an artifact's keywords
came from the field alone — 15 non-creature cards printing Flash, Katabatic
Winds' phasing — and anything granted to one came from nowhere.

The seed now reads every line the keyword-line classifier admits, through the
rewrite every reader of a card's lines starts from, and names each part
through the reader that admitted it (``keyword_lines.keyword_part_ability``).

Backwards on the base (59f133e63): the parity census names 250 cards (morph
94, cumulative upkeep 57, shadow 24, flash 15, shroud 15, storm 12, madness 10,
amplify 9, lifelink 8, hexproof 4, phasing 2); the granted-line census names
all six cumulative-upkeep grants; the Shaman offers the Circle again. With the
ingested field the seed of every one of 6,424 compilation units is unchanged
(the field already named every word the text now gives back).
"""

from __future__ import annotations

import re

from engine import Game, PlayerState, faces
from engine.card_loader import load_cards, manifest_set_paths
from engine.grammar.vocabulary import KEYWORD_ABILITIES
from engine.keyword_lines import _is_supported_keyword_line
from engine.keywords import grant_ability_line
from engine.line_normalization import normalize_creature_line
from engine.line_rewrites import expand_card_lines
from engine.models import Permanent
from engine.printed_characteristics import _printed_abilities_cached
from tests.helpers import _mk_card, settle

_REMINDER = re.compile(r"\([^)]*\)")

#: Compilation units over both manifest roles (6,424 at the time of writing).
_UNIT_FLOOR = 6000
#: (card, keyword) pairs the parity census judged (1,365 at the time of
#: writing) — a census that judged nothing would pass on nothing.
_JUDGED_FLOOR = 1300
#: Distinct quoted keyword lines the pool grants: four cumulative-upkeep lines
#: (six cards) and two "bands with other" lines (six cards).
_GRANTED_LINE_FLOOR = 6

#: Keywords named by their **quality**, not by a word: the seed reads each
#: with the reader that enforces it (``_protection_qualities``, the
#: hexproof-from split, ``banding.band_quality``), and the ingested field's
#: family word ("Protection", "Hexproof") is not the ability the part states.
_QUALITY_NAMED = ("protection from", "hexproof from", "bands with other")


def _units():
    return faces.compilation_units(
        load_cards(manifest_set_paths(include_measured=True))
    )


def _heads(word: str, part: str) -> bool:
    """Whether *part* of a keyword line states the keyword *word*: the whole
    part, or the word followed by its argument (a number, a cost)."""
    if part == word:
        return True
    return part.startswith(word) and part[len(word):len(word) + 1] in (" ", "{", "—", "-")


def _stated_parts(card) -> list[str]:
    """Each part of each keyword line *card* states, as the classifier admits
    the line."""
    parts: list[str] = []
    for line in expand_card_lines(card):
        if not line.strip() or not _is_supported_keyword_line(line):
            continue
        parts.extend(
            part.strip() for part in normalize_creature_line(line).split(",")
            if part.strip()
        )
    return parts


def test_kg5_layers_a_keyword_line_reads_as_its_keyword_without_the_ingested_field():
    """The parity census: the seed of a card's *text* alone holds every
    keyword its keyword lines state that the ingested field names.

    Text alone is what a granted line is — so a keyword the seed knows only
    from the field is a keyword no grant of its line gives.
    """
    units = _units()
    assert len(units) >= _UNIT_FLOOR, len(units)
    judged = 0
    unread: dict[str, list[str]] = {}
    for card in units:
        field = {word.lower() for word in card.keywords}
        parts = [
            part for part in _stated_parts(card)
            if not part.startswith(_QUALITY_NAMED)
        ]
        stated = {word for word in field for part in parts if _heads(word, part)}
        if not stated:
            continue
        bare = _printed_abilities_cached(card.name, card.type_line, card.oracle_text, ())
        for word in sorted(stated):
            judged += 1
            if word not in bare:
                unread.setdefault(word, []).append(faces.unit_label(card))
    assert judged >= _JUDGED_FLOOR, judged
    assert not unread, {word: names[:5] + [f"({len(names)})"] for word, names in unread.items()}


def _catalog_keyword(part: str) -> str | None:
    """The CR 702 keyword a keyword-line *part* states, read off Scryfall's
    catalog (``data/vocabulary/keyword_abilities.json``) — the longest
    catalog name heading the part, independent of the engine's readers."""
    if part.startswith("bands with other "):
        # CR 702.22b builds this ability's name out of its printed quality,
        # which no catalog of words can hold.
        return part
    found = [word for word in KEYWORD_ABILITIES if _heads(word, part)]
    return max(found, key=len) if found else None


def _probe_board(type_line: str, colors=("W",)):
    probe = Permanent(card=_mk_card(
        name="Probe Object", type_line=type_line, oracle_text="", colors=colors,
        power=2 if "Creature" in type_line else None,
        toughness=2 if "Creature" in type_line else None,
    ))
    game = Game(players=[PlayerState(name="P1", battlefield=[probe]), PlayerState(name="P2")])
    game._sync_control()
    game._recompute_continuous_effects()
    return game, probe


def test_kg5_layers_every_quoted_keyword_line_the_pool_grants_is_had_as_the_keyword():
    """Every quoted line in the pool that is a keyword line, granted on the
    channel the quoted grants use, is had as each keyword it states — on a
    creature and on an enchantment, the two front ends."""
    granted: dict[str, list[str]] = {}
    for card in _units():
        text = _REMINDER.sub("", card.oracle_text or "")
        for quoted in re.finditer(r'"([^"]+)"', text):
            # "…loses all "bands with other" abilities" (Hazduhr's kin) names
            # a family it takes away; nothing is granted.
            if re.search(r"\blose(s)?\b[^.\"]*$", text[:quoted.start()]):
                continue
            line = quoted.group(1).strip()
            if _is_supported_keyword_line(line):
                granted.setdefault(line.rstrip("."), []).append(card.name)
    assert len(granted) >= _GRANTED_LINE_FLOOR, sorted(granted)
    missing = []
    for line, granters in sorted(granted.items()):
        keywords = [
            _catalog_keyword(part.strip())
            for part in normalize_creature_line(line).split(",") if part.strip()
        ]
        assert all(keywords), (line, keywords)
        for type_line in ("Creature - Probe", "Enchantment"):
            game, probe = _probe_board(type_line)
            assert not any(game._has_keyword(probe, word) for word in keywords), line
            grant_ability_line(probe, line)
            game._recompute_continuous_effects()
            for word in keywords:
                if not game._has_keyword(probe, word):
                    missing.append((line, type_line, word, granters[:3]))
    assert not missing, missing


# --- the board the Known-gaps entry names ----------------------------------


def _shaman_table(set_pool, *shamans):
    ice = set_pool("ICE")
    lea = set_pool("LEA")
    game = Game(players=[
        PlayerState("A", library=[lea["Forest"]] * 10),
        PlayerState("B", library=[lea["Forest"]] * 10),
    ])
    game.enforce_mana_costs = False
    placed = []
    for card in (*[ice["Balduvian Shaman"]] * shamans[0],
                 lea["Circle of Protection: Red"], lea["Circle of Protection: White"]):
        permanent = Permanent(card=card)
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        placed.append(permanent)
    game._sync_control()
    return game, placed


def _offered(game, shaman) -> list[str]:
    index = next(
        i for i, perm in enumerate(game.players[0].battlefield) if perm is shaman
    )
    spec = game.activation_target_spec(0, index)
    return sorted(target["name"] for target in spec["valid_targets"])


def test_kg5_layers_balduvian_shaman_does_not_retarget_what_it_gave_cumulative_upkeep(set_pool):
    game, (shaman, red, black) = _shaman_table(set_pool, 1)
    assert _offered(game, shaman) == ["Circle of Protection: Red", "Circle of Protection: White"]

    result = game.activate_permanent_ability(
        0, "Balduvian Shaman", target_permanent_ids=[red.permanent_id],
        old_color="R", mana_color="G",
    )
    assert result.supported, result.details
    settle(game)
    assert "green source" in red.effective_card.oracle_text
    assert 'Circle of Protection: Red gains "Cumulative upkeep {1}"' in " ".join(game.log)
    assert red.has_keyword("cumulative upkeep")
    assert not black.has_keyword("cumulative upkeep")

    # Untapped again: the Circle now has cumulative upkeep, so "target white
    # enchantment you control that doesn't have cumulative upkeep" is the
    # other Circle alone, and the activation aimed at the first is refused
    # before anything is paid (CR 601.2c / 602.2b).
    shaman.tapped = False
    assert _offered(game, shaman) == ["Circle of Protection: White"]
    again = game.activate_permanent_ability(
        0, "Balduvian Shaman", target_permanent_ids=[red.permanent_id],
        old_color="G", mana_color="U",
    )
    assert not again.supported
    assert not shaman.tapped
    assert "green source" in red.effective_card.oracle_text

    # …and the granted keyword is the ability as well as the word: the next
    # upkeep puts an age counter on the Circle and charges it.
    game.start_turn(1)
    settle(game)
    game.start_turn(0)
    settle(game)
    assert "Circle of Protection: Red gains an age counter (1 total)" in game.log


def test_kg5_layers_a_second_shaman_resolving_finds_its_target_illegal(set_pool):
    """Two Shamans aimed at one Circle: the first gives it cumulative upkeep,
    so the second's target is illegal as it resolves (CR 608.2b) and the
    ability does nothing — no second text change, no second grant."""
    game, (first, second, red, black) = _shaman_table(set_pool, 2)
    for shaman, new in ((first, "G"), (second, "U")):
        index = next(i for i, p in enumerate(game.players[0].battlefield) if p is shaman)
        # Left on the stack, both announced while the Circle has no upkeep.
        result = game.queue_permanent_ability(
            0, "Balduvian Shaman", target_permanent_ids=[red.permanent_id],
            old_color="R" if new == "G" else "G", mana_color=new,
            permanent_index=index,
        )
        assert result.supported, result.details
    assert len(game.stack) == 2
    settle(game)
    grants = [line for line in game.log if 'gains "Cumulative upkeep {1}"' in line]
    assert len(grants) == 1, grants
    assert red.has_keyword("cumulative upkeep")


# --- the other channels a line is granted on ---------------------------------


def test_kg5_layers_each_channel_granting_the_line_grants_the_keyword(set_pool):
    """The pool grants "Cumulative upkeep" on four more channels: a lord
    (Breath of Dreams), an Aura (Mana Chains), a reanimation's rider (Dreams
    of the Dead) and a token's printed text (Splintering Wind). Each is had as
    the keyword, and the lord's ends with the lord."""
    ice, wth, all_ = set_pool("ICE"), set_pool("WTH"), set_pool("ALL")
    lea = set_pool("LEA")
    game = Game(players=[
        PlayerState("A", library=[lea["Forest"]] * 10,
                    graveyard=[lea["Savannah Lions"]],
                    hand=[wth["Mana Chains"]]),
        PlayerState("B", library=[lea["Forest"]] * 10),
    ])
    game.enforce_mana_costs = False

    def _place(card):
        permanent = Permanent(card=card)
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanent.metadata["summoning_sickness_turn"] = -99
        game._sync_control()
        return permanent

    bears = _place(lea["Grizzly Bears"])
    ogre = _place(lea["Hill Giant"])
    breath = _place(ice["Breath of Dreams"])
    game._recompute_continuous_effects()
    assert bears.has_keyword("cumulative upkeep")  # green: the lord's line
    assert not ogre.has_keyword("cumulative upkeep")

    assert game.queue_from_hand(
        0, "Mana Chains", target_permanent_ids=[ogre.permanent_id]
    ).supported
    settle(game)
    assert ogre.has_keyword("cumulative upkeep")  # the Aura's line

    _place(ice["Dreams of the Dead"])
    assert game.players[0].graveyard[0].name == "Savannah Lions"
    assert game.activate_permanent_ability(
        0, "Dreams of the Dead", target_graveyard_indices=[0],  # the graveyard's slot
    ).supported
    settle(game)
    returned = next(p for p in game.controlled_by(0) if p.card.name == "Savannah Lions")
    assert returned.has_keyword("cumulative upkeep")  # the reanimation's rider

    _place(all_["Splintering Wind"])
    assert game.activate_permanent_ability(
        0, "Splintering Wind", target_permanent_ids=[bears.permanent_id],
    ).supported
    settle(game)
    splinter = next(p for p in game.controlled_by(0) if p.metadata.get("is_token"))
    assert splinter.has_keyword("cumulative upkeep")  # the token's text
    assert splinter.has_keyword("flying")

    game.remove_from_battlefield(breath)
    game._recompute_continuous_effects()
    assert not bears.has_keyword("cumulative upkeep")
