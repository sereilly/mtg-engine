"""What layer 6 is seeded with is what the card *states*, not what it mentions.

``layer_bridge._printed_abilities`` is the seed CR 613 layer 6 starts from: an
object's own keyword abilities, before any grant or removal. It is built from
the ingested ``keywords`` field and from the compiled program, and until
Invasion's second wave the second half read ``static_line`` instructions with a
word search. A word search has no subject. "Enchanted creature has flying" is a
sentence about the creature a Licid is attached to; the scan made the *Licid*
fly. Ten shipped cards had a keyword they do not print, on the battlefield, on
the wire and in the AI's blocks:

    Gliding Licid (flying), Corrupting Licid (fear), Enraging Licid (haste),
    Quickening Licid (first strike), Guardian Beast (indestructible),
    Rootwater Shaman (flash), Gosta Dirk (islandwalk), Lord Magnus (forestwalk
    and plainswalk), Ur-Drago (swampwalk) -- and Primal Clay, seeded with
    flying *and* defender and rescued by the entry choice removing both.

The question "does this line give **this permanent** this keyword?" already had
an owner: the compiler's line classifier. A line stating the object's own
keywords is a ``keyword_line``; one giving them on a condition is a
``conditional_static``; one giving them to a class is a ``lord_buff``. A
``static_line`` is what no instruction carries, and in both manifest roles not
one of them states its own permanent's keyword -- so the seed reads keyword
lines and nothing else.

The sweep below is the definition of done and it is read against the **printed
text**, not against the compiler, so it is not the scan agreeing with itself:
every seeded word has to be in the ingested field or be the head of a
comma-separated part of a printed line. Validated backwards on the tree before
the fix, where it names exactly the ten cards above.
"""

from __future__ import annotations

import re

from engine import Game, PlayerState, faces
from engine.card_loader import load_cards, manifest_set_paths
from engine.layer_bridge import _printed_abilities, _text_keywords_in
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card

#: Both manifest roles and every face: 4,632 objects at the time of writing.
_CARD_FLOOR = 4600
#: Seeded words the sweep judged (1,685 at the time of writing).
_SEEDED_WORD_FLOOR = 1600
#: ``static_line`` instructions in the pool (199), and the ones among them that
#: *mention* a keyword word (18) -- the lines that were findings while the scan
#: read them. A sweep that met none of these would be passing on nothing.
_STATIC_LINE_FLOOR = 190
_MENTIONING_LINE_FLOOR = 15

_REMINDER = re.compile(r"\([^)]*\)")


def _w2g5_pool() -> dict:
    cards: dict = {}
    # ``faces.compilation_units``: each single-face card, and each half of a
    # multi-face card *in its place* - the whole card has no text of its own
    # (CR 709.3a), so it is not a row here.
    for card in faces.compilation_units(
        load_cards(manifest_set_paths(include_measured=True))
    ):
        cards.setdefault(card.name, card)
    return cards


def _w2g5_stated_parts(card) -> set[str]:
    """Each comma- or semicolon-separated part of each printed line, lowered.

    The reading a player makes of a keyword line, taken off the oracle text
    itself so the sweep does not ask the compiler to mark its own work.
    """
    parts: set[str] = set()
    for line in _REMINDER.sub("", card.oracle_text or "").splitlines():
        for part in re.split(r"[,;]", line):
            parts.add(part.strip().lower())
    return parts


def _w2g5_is_stated(word: str, card, parts: set[str]) -> bool:
    if word in {keyword.lower() for keyword in card.keywords}:
        return True
    # "rampage" is stated by the part "rampage 2"; a whole part states itself.
    return any(part == word or part.startswith(word + " ") for part in parts)


def test_w2g5_every_seeded_keyword_is_one_the_card_states():
    cards = _w2g5_pool()
    assert len(cards) >= _CARD_FLOOR, len(cards)

    judged = 0
    static_lines = 0
    mentioning = 0
    unstated: list[tuple[str, str]] = []
    for name, card in sorted(cards.items()):
        parts = _w2g5_stated_parts(card)
        seeded = _printed_abilities(card)
        for word in sorted(seeded):
            judged += 1
            if not _w2g5_is_stated(word, card, parts):
                unstated.append((name, word))
        for instruction in compile_card_oracle(card).instructions:
            if instruction.kind != "static_line":
                continue
            static_lines += 1
            mentioned = _text_keywords_in(instruction.value or "")
            if not mentioned:
                continue
            mentioning += 1
            for word in sorted(mentioned & seeded):
                if not _w2g5_is_stated(word, card, parts):
                    unstated.append((name, word))

    assert judged >= _SEEDED_WORD_FLOOR, judged
    assert static_lines >= _STATIC_LINE_FLOOR, static_lines
    assert mentioning >= _MENTIONING_LINE_FLOOR, mentioning
    assert not unstated, (
        "layer 6 is seeded with a keyword the card only mentions: "
        f"{sorted(set(unstated))}"
    )


def _w2g5_on_a_battlefield(text: str, *, islands: int = 0):
    probe = Permanent(card=_mk_card(
        name="Probe Drake", type_line="Creature - Drake", oracle_text=text,
        colors=("U",), power=1, toughness=1,
    ))
    land = _mk_card(name="Island", type_line="Basic Land - Island")
    board = [probe] + [Permanent(card=land) for _ in range(islands)]
    game = Game(players=[
        PlayerState(name="P1", battlefield=board), PlayerState(name="P2"),
    ])
    game._sync_control()
    game._recompute_continuous_effects()
    assert compile_card_oracle(probe.card).supported, text
    return game, probe


def test_w2g5_the_three_owners_of_a_self_keyword_on_an_invented_card():
    """One invented creature, three printed sentences, three owners.

    The name-free form of the sweep: the answer depends on what the line *is*
    (its compiled kind), never on which sentences somebody thought to list.
    """
    # A keyword line states the object's own ability (CR 702).
    game, drake = _w2g5_on_a_battlefield("Flying")
    assert game._has_keyword(drake, "flying")

    # A sentence about the *enchanted* creature is not about this one
    # (CR 303.4m: it names whatever this permanent is attached to).
    game, drake = _w2g5_on_a_battlefield("Enchanted creature has flying.")
    assert not game._has_keyword(drake, "flying")

    # A conditional self-grant is layer 6's, with its condition enforced --
    # never the seed's, which has no condition to enforce.
    sentence = "This creature has flying as long as you control an Island."
    game, drake = _w2g5_on_a_battlefield(sentence)
    assert not game._has_keyword(drake, "flying")
    game, drake = _w2g5_on_a_battlefield(sentence, islands=1)
    assert game._has_keyword(drake, "flying")
