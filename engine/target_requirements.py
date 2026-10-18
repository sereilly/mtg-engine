"""Text-keyed **requirements** on what a player choosing targets must choose
(CR 601.2c, CR 602.2b).

"While an opponent is choosing targets as part of casting a spell they control
or activating an ability they control, that player must choose at least one
Flagbearer on the battlefield if able." (Standard Bearer, Coalition Honor
Guard, Coalition Flag.)

The third file of a family, and the pair beside it is worth stating:
``target_restrictions.py`` is what a **spell** prints about its own targeting,
``target_immunity.py`` is what a **permanent** prints about being aimed at, and
this is what a permanent prints about what *somebody else's* announcement has
to include. The first two take a candidate out of a list. This one cannot be
written that way, and that is the whole design:

* it is a rule about the **announcement**, not about any one target. With one
  slot the two coincide — the legal list shrinks to the Flagbearers in it —
  and with two they do not: "two target creatures" may name a Flagbearer and
  anything else. So the *offer* is narrowed only where the announcement has
  one slot, and what is enforced is a refusal over everything the announcement
  named (:func:`announcement_refusal`);
* it binds **only while targets are being chosen for a cast or an
  activation**. A triggered ability "doesn't have to target a Flagbearer", nor
  does a copy choosing new targets or a spell whose targets are changed
  (rulings, 2016-06-08) — and a target chosen legally stays legal when a
  Flagbearer arrives afterwards (CR 608.2b re-asks what the *spell* printed,
  not what a permanent demanded of the announcement). So the rule is asked at
  the two announcement paths and by the two pickers in front of them, and
  never inside ``_enumerate_targets``, which is also the list the resolution,
  the retarget and every trigger read.

**"If able" is the picker's own list.** A Flagbearer the announcement could
not legally have named — protection from the spell, shroud, the wrong type, a
graveyard or a stack target, a spell whose only targets are players — is not
in the offer, so it binds nothing. The requirement gives no permission to
target what could not be targeted. "Any player's Flagbearer may be targeted"
(ruling): the requirement names a Flagbearer *on the battlefield*, so the
chooser's own Flagbearer satisfies it.

**Whose opponents** is CR 109.5's "you" of the permanent printing the line:
the Flagbearer's controller, or the Aura's (Coalition Flag is an "enchant
creature you control"). The line is read off ``effective_card``, so a
Flagbearer that has lost its abilities demands nothing while still being a
Flagbearer another one's requirement can be satisfied with — the type is
layer 4's (``subject_matches``), the requirement is the ability's.

**What the printed noun is, is payload.** Every printing says "Flagbearer";
the phrase goes through the grammar's noun parser and ``subject_matches``
exactly as ``cast_restrictions.cast_condition_line`` reads its board, so a
card printing "at least one Wall" needs no code. Where two *different* nouns
are in force at once the announcement must include a permanent answering
either — no pair of printed cards produces that board, and the rules give no
order to obey two such requirements in.

**One reading this file takes that the three rulings do not settle**: an
announcement that names **no** target for "up to one target creature" while a
Flagbearer could have been named is refused. The card says "must choose at
least one Flagbearer … if able" and a player who may name one target is able
to. The other reading (CR 601.2c: a player first announces *how many* targets,
and zero leaves nothing to choose) is one condition in
:func:`announcement_refusal` away.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .game import Game

#: The claim name the support gate and the parse census record this table by.
CLAIM = "target_requirements"

_MUST_CHOOSE = re.compile(
    r"^while an opponent is choosing targets as part of casting a spell they "
    r"control or activating an ability they control, that player must choose "
    r"at least one (?P<subject>.+) on the battlefield if able$",
    re.IGNORECASE,
)


@lru_cache(maxsize=None)
def must_choose_line(line: str) -> "tuple[dict, str] | None":
    """``(filter payload, the printed noun)`` for a line that makes an
    opponent's announcement include one of something, or None.

    Anchored whole: a line that says more than this is a rule this module does
    not carry out. A noun ``subject_matches`` cannot test is refused rather
    than approximated — a requirement admitted with a noun nothing answers is
    a card that enters play and demands nothing. Callers must not mutate the
    payload; it is the cached one.
    """
    from .grammar.errors import GrammarError
    from .grammar.lexer import tokenize
    from .grammar.nouns import parse_object_filter
    from .grammar.stream import TokenStream
    from .subject_filters import OBJECT_ONLY_FILTER_KEYS, untestable_filter_keys

    text = " ".join((line or "").strip().rstrip(".").split())
    match = _MUST_CHOOSE.match(text.replace("’", "'"))
    if match is None:
        return None
    # The noun as printed, for the refusal a player reads ("Flagbearer"); the
    # parser reads it lowercased like every other line.
    noun = match.group("subject")
    stream = TokenStream(tokenize(noun.lower()).tokens)
    try:
        described = parse_object_filter(stream)
    except GrammarError:
        return None
    if not stream.exhausted:
        return None
    payload = described.to_payload()
    # Object-only keys: the noun is asked about a permanent on anybody's
    # battlefield with no seat to be "yours" and no source to be "another".
    if not payload or untestable_filter_keys(payload, allowed=OBJECT_ONLY_FILTER_KEYS):
        return None
    return payload, noun


def must_choose_claims_line(line: str) -> bool:
    """Whether this table implements *line* in full — the support gate's and
    the grammar registry's question."""
    return must_choose_line(line) is not None


def cast_is_bound(card) -> bool:
    """Whether casting *card* chooses targets at all (CR 115.1a/b): an instant,
    a sorcery or an Aura. Any other permanent spell targets nothing as it is
    cast — the picker this engine runs in front of one is its *entry
    trigger's* (a standing convention), and a triggered ability "doesn't have
    to target a Flagbearer" (ruling, 2016-06-08).
    """
    if card.primary_type in ("instant", "sorcery"):
        return True
    return "aura" in (card.type_line or "").lower()


def requirements_binding(game: "Game", chooser: int) -> "list[tuple[dict, str, str]]":
    """``(filter payload, noun, source name)`` for every requirement in force
    on *chooser*'s announcements: one per permanent printing the line whose
    controller *chooser* is an opponent of.

    The effective card (CR 707.2 / 613.1f), so a copy of a Flagbearer demands
    and one that lost its abilities does not.
    """
    found: list[tuple[dict, str, str]] = []
    for seat, permanent in game.permanents_with_controller():
        if seat == chooser or chooser not in game.opponents_of(seat):
            continue
        card = permanent.effective_card
        text = card.oracle_text or ""
        if "must choose at least one" not in text:
            continue
        for line in text.splitlines():
            read = must_choose_line(line)
            if read is not None:
                found.append((read[0], read[1], card.name))
    return found


#: Spec kinds that describe no CR 115.1 target on the battlefield or no target
#: at all — the picker in front of them is a mode, a face, a card in hand.
_NO_OBJECT_OFFER_KINDS = frozenset({None, "none", "modal", "faces", "hand_card"})

#: Spec flags under which the picker is not a target: CR 609.7a's chosen
#: source and Clone's optional copy (``stack_targets._UNTARGETED_SPEC_FLAGS``).
_UNTARGETED_SPEC_FLAGS = ("source_of_choice", "optional")


def _offers_targets(spec: dict | None) -> bool:
    """Whether *spec*'s picker chooses **targets** (CR 601.2c) rather than a
    cost (CR 601.2b), a source or a copy."""
    from .targeting import spec_is_a_cost

    if not spec or spec.get("kind") in _NO_OBJECT_OFFER_KINDS:
        return False
    if spec_is_a_cost(spec):
        return False
    maximum = spec.get("max_targets")
    if isinstance(maximum, int) and not isinstance(maximum, bool) and maximum <= 0:
        # "X target creatures" at an X of zero: CR 601.2b fixed the number of
        # targets before any is chosen, and with none to choose nobody is
        # able to choose a Flagbearer.
        return False
    return not any(spec.get(flag) for flag in _UNTARGETED_SPEC_FLAGS)


def _offered_permanents(game: "Game", entries, found: dict | None = None) -> dict:
    """``permanent_id -> (entry, permanent)`` for every battlefield permanent
    anywhere in an offer. A roles offer nests each later role under ``next``,
    and every node of that tree is part of some complete announcement
    (``_role_target_walk`` drops a choice that leaves a later role empty), so
    all of it is walked."""
    found = {} if found is None else found
    for entry in entries or ():
        if entry.get("kind") == "permanent":
            permanent = game.permanent_at(entry.get("seat"), entry.get("index"))
            if permanent is not None:
                found.setdefault(permanent.permanent_id, (entry, permanent))
        if entry.get("next"):
            _offered_permanents(game, entry["next"], found)
    return found


def one_slot(spec: dict) -> bool:
    """Whether *spec* announces exactly one target slot — the shape in which
    "at least one of the targets" and "the target" are the same statement."""
    from .targeting import ROLES_TARGET_KIND

    if spec.get("kind") in (ROLES_TARGET_KIND, "divided"):
        return False
    if spec.get("x_targets") or spec.get("unbounded_targets"):
        return False
    maximum = spec.get("max_targets")
    return not (isinstance(maximum, int) and maximum > 1)


def required_among(
    game: "Game", chooser: int, spec: dict | None, binding=None,
) -> "list[tuple[dict, object]]":
    """The ``(entry, permanent)`` pairs of *spec*'s offer that a requirement
    in force names — what *chooser* is **able** to choose. Empty when nothing
    binds this announcement.

    *spec* carries its un-narrowed ``valid_targets`` (the legal list for each
    slot). *binding* is :func:`requirements_binding`'s answer where the caller
    already holds it.
    """
    from .subject_filters import subject_matches

    if not _offers_targets(spec):
        return []
    if binding is None:
        binding = requirements_binding(game, chooser)
    if not binding:
        return []
    offered = _offered_permanents(game, spec.get("valid_targets"))
    found = [
        (entry, permanent)
        for entry, permanent in offered.values()
        if any(
            subject_matches(game, permanent, described, observer=chooser)
            for described, _noun, _source in binding
        )
    ]
    if found and spec.get("same_controller"):
        # "Choose two target creatures **controlled by the same opponent**"
        # (Retribution). A relation between the targets: a Flagbearer whose
        # controller has no second legal creature is in no complete
        # announcement, so nobody is able to choose it.
        wanted = spec.get("max_targets")
        wanted = wanted if isinstance(wanted, int) and wanted > 1 else 2
        per_seat: dict = {}
        for entry, _permanent in offered.values():
            per_seat[entry.get("seat")] = per_seat.get(entry.get("seat"), 0) + 1
        found = [
            (entry, permanent) for entry, permanent in found
            if per_seat.get(entry.get("seat"), 0) >= wanted
        ]
    return found


def narrow_offer(game: "Game", chooser: int, spec: dict) -> dict:
    """*spec* as *chooser*'s picker presents it under the requirements in
    force (mutated and returned).

    ``required_targets`` names what at least one chosen target must be, for
    every shape. With **one slot** the legal list *is* that set, so
    ``valid_targets`` is narrowed to it; with several, the list stays whole —
    the other slots are free — and the announcement gate refuses a choice that
    includes none. Unchanged, and carrying neither key, wherever nothing binds.
    """
    binding = requirements_binding(game, chooser)
    if not binding:
        return spec
    required = required_among(game, chooser, spec, binding)
    if not required:
        return spec
    spec["required_targets"] = [
        {
            "kind": "permanent",
            "seat": entry.get("seat"),
            "index": entry.get("index"),
            "id": permanent.permanent_id,
            "name": permanent.card.name,
        }
        for entry, permanent in required
    ]
    spec["target_requirement"] = _label(binding)
    if one_slot(spec):
        chosen = {permanent.permanent_id for _entry, permanent in required}
        spec["valid_targets"] = [
            entry for entry in spec.get("valid_targets") or ()
            if entry.get("kind") == "permanent"
            and (permanent := game.permanent_at(entry.get("seat"), entry.get("index")))
            is not None
            and permanent.permanent_id in chosen
        ]
    return spec


def _label(binding) -> str:
    nouns = sorted({noun for _described, noun, _source in binding})
    sources = sorted({source for _described, _noun, source in binding})
    return (
        f"at least one {' or '.join(nouns)} must be chosen as a target if able "
        f"({', '.join(sources)})"
    )


def announcement_refusal(
    game: "Game", chooser: int, name: str, specs, named_ids,
) -> str | None:
    """Why an announcement naming the permanents *named_ids* is not one
    *chooser* may make, or None.

    *specs* is the un-narrowed offer of every part of the announcement (one
    per announced mode; one for everything else). The whole rule: if any slot
    of any of them could have named a required permanent, at least one named
    target is one. Naming nothing at all does not escape it (see the module
    docstring for the reading).
    """
    binding = requirements_binding(game, chooser)
    if not binding:
        return None
    able: set = set()
    for spec in specs:
        able.update(
            permanent.permanent_id
            for _entry, permanent in required_among(game, chooser, spec, binding)
        )
    if not able or able & {pid for pid in named_ids if isinstance(pid, int)}:
        return None
    return f"{name}: {_label(binding)} (CR 601.2c)"


__all__ = [
    "CLAIM",
    "announcement_refusal",
    "cast_is_bound",
    "must_choose_claims_line",
    "must_choose_line",
    "narrow_offer",
    "one_slot",
    "required_among",
    "requirements_binding",
]
