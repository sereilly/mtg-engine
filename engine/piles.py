"""Separating objects into two piles — CR 700.3.

One procedure, six printings (Fact or Fiction, Do or Die, Death or Glory, Bend
or Break, Fight or Flight, Stand or Fall), and the same two decisions every
time: **one player separates, another chooses a pile**. What differs is data —
what is separated, whose it is, who separates, who chooses, and what becomes of
the chosen pile and of the other — and all of it arrives on the
``separate_into_piles`` instruction's payload.

Objects in a pile do not leave their zone (CR 700.3c): nothing moves at the split. So a
pile here is a list of *positions* into a frozen item list, and the items stay
exactly where they were until a fate is carried out —

* cards revealed from a library are addressed by their position in the reveal;
* cards in a graveyard by their **index** in it, never by identity: a graveyard
  may hold several copies of one card and a deck repeats one immutable
  ``CardDefinition`` per copy, so identity cannot tell them apart;
* permanents by ``permanent_id`` (CR 400.7).

Nobody receives priority between the split and the fates (CR 608.2), so the
positions cannot go stale underneath a prompt.

**Several players' piles are one effect.** "Each player separates all nontoken
lands they control … Destroy all lands in the chosen piles. Tap all lands in
the other piles." makes one pair of piles per player and then acts on all of
them at once, so the procedure runs every split, then every choice, then the
fates — each a step of one resumable loop (``engine/resumption.py``), because
either prompt may stop to ask an interactive seat and the rest of the procedure
has to be there when the answer arrives.

The two prompts are ``pile_split`` and ``pile_choice``
(``engine/mixins/stack/choices.py`` registers them). Both are face up: every
player sees what is in each pile, which is the difference from Phyrexian
Portal's ``library_pile_split`` / ``pile_exile_choice`` pair, whose chooser may
be shown two numbers and nothing else (CR 406.3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .resumption import run_resumable
from .search_filters import card_has_type

#: The scratchpad key ``choose_opponent`` writes and "an opponent" reads here —
#: the literal ``grammar/lowering/_record_keys.CHOSEN_PLAYER`` declares, which
#: the engine side does not import from (``handlers/_common`` spells it the
#: same way and says why).
_CHOSEN_PLAYER = "chosen_player"

#: What a pile may be sent to do, by what it is a pile *of* — the closed
#: vocabulary of this module, and the only copy of it: the lowering
#: (``grammar/lowering/separations.py``) admits a printed fate only when it is
#: listed here, and every word listed is one a performer below carries out. A
#: fate admitted with no performer would be a pile the card names and nothing
#: acts on.
PILE_FATES: dict[str, frozenset[str]] = {
    "library_top": frozenset({"hand", "graveyard"}),
    "graveyard": frozenset({"exile", "battlefield"}),
    "battlefield": frozenset({"destroy", "tap", "only_attackers", "only_blockers"}),
}

#: Fates that are good for the player whose objects are in the pile. The
#: default chooser reads it: a seat choosing for itself wants the better pile
#: to meet a good fate and the worse one to meet a bad fate, and a seat
#: choosing against somebody wants the opposite.
_KIND_FATES = frozenset({"hand", "battlefield", "only_attackers", "only_blockers"})


@dataclass
class PileGroup:
    """One player's pair of piles.

    ``items`` is frozen when the group is made and never reordered; ``piles``
    holds positions into it, so the two lists partition ``range(len(items))``.
    """

    owner: int
    separator: int
    chooser: int | None
    items: list
    piles: list[list[int]] | None = None
    chosen: int | None = None


@dataclass
class PileSession:
    """Everything one ``separate_into_piles`` resolution is carrying."""

    card_name: str
    caster: int
    payload: dict
    context: Any
    groups: list[PileGroup] = field(default_factory=list)

    @property
    def what(self) -> str:
        return str(self.payload.get("what"))


# ---------------------------------------------------------------------------
# What is in a pile
# ---------------------------------------------------------------------------

def item_card(game, session: PileSession, group: PileGroup, position: int):
    """The card a pile position shows, or None if the object has gone.

    A permanent is read through ``effective_card`` — what it *is* now (CR 613),
    which is what both players are looking at.
    """
    item = group.items[position]
    if session.what == "battlefield":
        permanent = game.permanent_by_id(item)
        return permanent.effective_card if permanent is not None else None
    if session.what == "graveyard":
        graveyard = game.players[group.owner].graveyard
        return graveyard[item] if 0 <= item < len(graveyard) else None
    return item


def item_name(game, session: PileSession, group: PileGroup, position: int) -> str:
    card = item_card(game, session, group, position)
    return card.name if card is not None else "(gone)"


def item_value(game, session: PileSession, group: PileGroup, position: int) -> int:
    """How much a default seat thinks one pile item is worth.

    Deliberately coarse — one point for being a card at all, its mana value,
    and a creature's body — because it only has to rank two piles against each
    other, and every printing asks that of a set of like objects (five cards,
    a board of creatures, a board of lands).
    """
    item = group.items[position]
    if session.what == "battlefield":
        permanent = game.permanent_by_id(item)
        if permanent is None:
            return 0
        card = permanent.effective_card
        value = 1 + int(getattr(card, "cmc", 0) or 0)
        if permanent.is_creature:
            value += max(0, int(permanent.effective_power))
            value += max(0, int(permanent.effective_toughness))
        return value
    card = item_card(game, session, group, position)
    if card is None:
        return 0
    return 1 + int(getattr(card, "cmc", 0) or 0)


def pile_value(game, session: PileSession, group: PileGroup, pile: list[int]) -> int:
    return sum(item_value(game, session, group, position) for position in pile)


# ---------------------------------------------------------------------------
# The procedure
# ---------------------------------------------------------------------------

def _apnap(game, seats) -> list[int]:
    """*seats* in APNAP order (CR 101.4): the active player first, then turn
    order."""
    wanted = set(seats)
    count = len(game.players)
    start = game.active_player_index if game.active_player_index is not None else 0
    return [
        (start + offset) % count
        for offset in range(count)
        if (start + offset) % count in wanted
    ]


def _owners(game, session: PileSession) -> list[int] | None:
    """The seats whose objects are separated, or None when the word names
    nobody (and the effect ends rather than reaching the wrong board)."""
    from .handlers._common import frozen_that_player_seat

    whose = session.payload.get("whose")
    context = session.context
    live = [seat for seat, player in enumerate(game.players) if not player.lost]
    if whose == "you":
        return [session.caster]
    if whose == "target_player":
        target = context.target
        return [game.players.index(target)] if target in game.players else None
    if whose == "that_player":
        seat = frozen_that_player_seat(game, context)
        return [seat] if seat is not None else None
    if whose == "each_player":
        return _apnap(game, live)
    if whose == "each_defending_player":
        # CR 506.2 / CR 802.2: every opponent of the attacking player is a
        # defending player in the combat this is the beginning of. Asked of the
        # turn rather than of ``combat_defending_player_index``, which is not
        # settled until attackers are declared.
        if game.current_turn_phase != "combat":
            return []
        return _apnap(game, game.opponents_of(game.active_player_index))
    return None


def _items(game, session: PileSession, owner: int) -> list:
    from .subject_filters import subject_matches

    payload = session.payload
    player = game.players[owner]
    if session.what == "library_top":
        return list(player.library[: int(payload.get("count", 0))])
    described = dict(payload.get("filter") or {})
    if session.what == "graveyard":
        from .handlers._common import _card_matches_filter

        return [
            index for index, card in enumerate(player.graveyard)
            if _card_matches_filter(card, described, game=game, owner=player)
        ]
    return [
        permanent.permanent_id
        for permanent in game.controlled_by(owner)
        if subject_matches(
            game, permanent, described,
            observer=session.caster, source=session.context.source_permanent,
        )
    ]


def _named_seat(game, session: PileSession, word: str, owner: int) -> int | None:
    """The seat a separator/chooser word names for *owner*'s piles, or None
    when it is still to be picked (``owner_opponent`` at a table of three or
    more) or names nobody."""
    if word == "you":
        return session.caster
    if word == "owner":
        return owner
    if word == "an_opponent":
        chosen = (session.context.results or {}).get(_CHOSEN_PLAYER)
        return chosen if isinstance(chosen, int) else None
    if word == "owner_opponent":
        opponents = game.opponents_of(owner)
        return opponents[0] if len(opponents) == 1 else None
    return None


def begin_separation(game, instruction, context) -> None:
    """Run CR 700.3's procedure for one ``separate_into_piles`` instruction.

    **The last thing its caller does** — it is a resumable loop, and work
    written after it would not run when a step stops to ask.
    """
    payload = dict(instruction.payload)
    card_name = context.card.name if context.card is not None else ""
    session = PileSession(
        card_name=card_name,
        caster=game.players.index(context.caster),
        payload=payload,
        context=context,
    )
    owners = _owners(game, session)
    if owners is None:
        game.log.append(f"{card_name}: no player whose objects to separate")
        return
    for owner in owners:
        separator = _named_seat(game, session, str(payload.get("separator")), owner)
        if separator is None:
            game.log.append(f"{card_name}: nobody to separate the piles")
            return
        chooser = _named_seat(game, session, str(payload.get("chooser")), owner)
        if chooser is None and payload.get("chooser") != "owner_opponent":
            game.log.append(f"{card_name}: nobody to choose a pile")
            return
        if chooser is None and not game.opponents_of(owner):
            game.log.append(f"{card_name}: nobody to choose a pile")
            return
        session.groups.append(
            PileGroup(
                owner=owner, separator=separator, chooser=chooser,
                items=_items(game, session, owner),
            )
        )
    if session.what == "library_top":
        for group in session.groups:
            names = [card.name for card in group.items]
            if names:
                game.record_reveal(group.owner, names)
                game.log.append(
                    f"{game.players[group.owner].name} reveals " + ", ".join(names)
                )
            else:
                game.log.append(
                    f"{game.players[group.owner].name} has no cards to reveal"
                )
    steps: list = []
    # CR 101.4: every split first, in APNAP order (the groups already are),
    # then who chooses, then every choice — a chooser sees finished piles.
    steps.extend(("split", group) for group in session.groups)
    steps.extend(("name_chooser", group) for group in session.groups)
    steps.extend(("read_chooser", group) for group in session.groups)
    steps.extend(("choose", group) for group in session.groups)
    steps.append(("fates", None))

    def step(entry) -> None:
        action, group = entry
        if action == "split":
            _ask_split(game, session, group)
        elif action == "name_chooser":
            _ask_who_chooses(game, session, group)
        elif action == "read_chooser":
            _read_who_chooses(game, session, group)
        elif action == "choose":
            _ask_choice(game, session, group)
        else:
            _carry_out_fates(game, session)

    run_resumable(game, steps, step)


def _ask_split(game, session: PileSession, group: PileGroup) -> None:
    if not group.items:
        # CR 700.3d: a pile may be empty, and with nothing to separate both
        # are. Nobody is asked a question with one answer.
        group.piles = [[], []]
        game.log.append(
            f"{session.card_name}: {game.players[group.owner].name} has "
            "nothing to separate"
        )
        return
    game.arm_pending_choice(
        "pile_split", group.separator,
        card_name=session.card_name,
        owner_index=group.owner,
        _session=session, _group=group,
    )


def _chooser_key(group: PileGroup) -> str:
    return f"pile_chooser_for_seat_{group.owner}"


def _ask_who_chooses(game, session: PileSession, group: PileGroup) -> None:
    """"…chosen by **one of their opponents of their choice**." (Bend or Break.)

    The owner's pick, and a prompt only where there is more than one opponent
    to pick between — the existing ``player_choice`` prompt, which records the
    seat under the key the next step reads.
    """
    if group.chooser is not None:
        return
    opponents = game.opponents_of(group.owner)
    session.context.results[_chooser_key(group)] = opponents[0] if opponents else None
    if len(opponents) > 1:
        game.arm_player_choice(
            group.owner,
            card_name=session.card_name,
            prompt="Choose an opponent to choose between your piles.",
            result_key=_chooser_key(group),
            seats=opponents,
            context=session.context,
        )


def _read_who_chooses(game, session: PileSession, group: PileGroup) -> None:
    if group.chooser is None:
        chosen = session.context.results.get(_chooser_key(group))
        group.chooser = chosen if isinstance(chosen, int) else None


def _ask_choice(game, session: PileSession, group: PileGroup) -> None:
    if group.piles is None:
        group.piles = [list(range(len(group.items))), []]
    if group.chooser is None or not group.items:
        # Two empty piles (or nobody left to choose): the first is as chosen
        # as either.
        group.chosen = 0
        return
    game.arm_pending_choice(
        "pile_choice", group.chooser,
        card_name=session.card_name,
        owner_index=group.owner,
        _session=session, _group=group,
    )


# ---------------------------------------------------------------------------
# The two answers
# ---------------------------------------------------------------------------

def resolve_pile_split(game, choice, first_pile) -> bool:
    """Record the division. *first_pile* is the positions that go into the
    first pile; everything else is the second. Either may be empty (CR 700.3d)."""
    session: PileSession = choice.data["_session"]
    group: PileGroup = choice.data["_group"]
    try:
        positions = [int(position) for position in (first_pile or [])]
    except (TypeError, ValueError):
        return False
    if len(set(positions)) != len(positions):
        return False
    if any(not 0 <= position < len(group.items) for position in positions):
        return False
    chosen = set(positions)
    group.piles = [
        [position for position in range(len(group.items)) if position in chosen],
        [position for position in range(len(group.items)) if position not in chosen],
    ]
    game.discard_pending_choice(choice)
    game.log.append(
        f"{game.players[choice.player_index].name} separates "
        + _describe_piles(game, session, group)
    )
    return True


def _describe_piles(game, session: PileSession, group: PileGroup) -> str:
    def describe(pile: list[int]) -> str:
        names = [item_name(game, session, group, position) for position in pile]
        return "[" + ", ".join(names) + "]" if names else "[nothing]"

    first, second = group.piles
    return f"{describe(first)} and {describe(second)}"


def default_pile_split(game, choice) -> None:
    """The stated policy: **the most even split by value.**

    Every printing sets the separator against the chooser — an opponent
    separates what you will take one pile of, you separate what an opponent
    will destroy one pile of — so the chooser will take whichever pile suits
    them, and the separator's best answer is the division that leaves the two
    as close as possible. Greedy largest-first, which is exact for the sets
    these cards meet (a handful of objects) and never worse than splitting by
    position.
    """
    session: PileSession = choice.data["_session"]
    group: PileGroup = choice.data["_group"]
    ranked = sorted(
        range(len(group.items)),
        key=lambda position: (-item_value(game, session, group, position), position),
    )
    piles: list[list[int]] = [[], []]
    totals = [0, 0]
    for position in ranked:
        lighter = 0 if totals[0] <= totals[1] else 1
        piles[lighter].append(position)
        totals[lighter] += item_value(game, session, group, position)
    if not resolve_pile_split(game, choice, piles[0]):
        game.discard_pending_choice(choice)


def resolve_pile_choice(game, choice, pile_index) -> bool:
    session: PileSession = choice.data["_session"]
    group: PileGroup = choice.data["_group"]
    if pile_index not in (0, 1) or isinstance(pile_index, bool):
        return False
    group.chosen = int(pile_index)
    game.discard_pending_choice(choice)
    names = [
        item_name(game, session, group, position)
        for position in group.piles[group.chosen]
    ]
    game.log.append(
        f"{game.players[choice.player_index].name} chooses the pile of "
        + ("[" + ", ".join(names) + "]" if names else "[nothing]")
    )
    return True


def default_pile_choice(game, choice) -> None:
    """The stated policy: **read the piles.**

    A seat choosing for the player the piles belong to gives the more valuable
    pile the kinder fate; a seat choosing against them gives it the harsher
    one. On a tie, the first pile.
    """
    session: PileSession = choice.data["_session"]
    group: PileGroup = choice.data["_group"]
    values = [pile_value(game, session, group, pile) for pile in group.piles]
    kind = str(session.payload.get("chosen")) in _KIND_FATES
    friendly = choice.player_index == group.owner
    wants_bigger = kind == friendly
    if values[0] == values[1]:
        pick = 0
    elif wants_bigger:
        pick = 0 if values[0] > values[1] else 1
    else:
        pick = 0 if values[0] < values[1] else 1
    if not resolve_pile_choice(game, choice, pick):
        game.discard_pending_choice(choice)


# ---------------------------------------------------------------------------
# What becomes of each pile
# ---------------------------------------------------------------------------

def _carry_out_fates(game, session: PileSession) -> None:
    """Act on every group's two piles — the chosen fate over all the chosen
    piles, then the other fate over all the others, which is the order the
    sentences are printed in (CR 608.2c)."""
    payload = session.payload
    for group in session.groups:
        if group.piles is None:
            group.piles = [list(range(len(group.items))), []]
        if group.chosen is None:
            group.chosen = 0
    performer = _PERFORMERS[session.what]
    performer(game, session, str(payload.get("chosen")), payload.get("other"))


def _library_fates(game, session: PileSession, chosen_fate: str, other_fate) -> None:
    for group in session.groups:
        player = game.players[group.owner]
        count = len(group.items)
        # The revealed cards are still the top of the library — nothing has had
        # a chance to move them — and they are taken off it by *position*, the
        # only address that tells two copies of one card apart.
        if count == 0 or any(
            position >= len(player.library)
            or player.library[position] is not group.items[position]
            for position in range(count)
        ):
            if count:
                game.log.append(f"{session.card_name}: the revealed cards have moved")
            continue
        del player.library[:count]
        for index, pile in enumerate(group.piles):
            fate = chosen_fate if index == group.chosen else other_fate
            for position in pile:
                card = group.items[position]
                if fate == "hand":
                    game.put_card_into_hand(player, card)
                elif fate == "graveyard":
                    game.put_card_into_graveyard(player, card, from_zone="library")
            if pile:
                game.log.append(
                    f"{player.name} puts "
                    + ", ".join(group.items[position].name for position in pile)
                    + (" into their hand" if fate == "hand" else " into their graveyard")
                )


def _graveyard_fates(game, session: PileSession, chosen_fate: str, other_fate) -> None:
    for group in session.groups:
        player = game.players[group.owner]
        fate_of: dict[int, str] = {}
        for index, pile in enumerate(group.piles):
            fate = chosen_fate if index == group.chosen else other_fate
            for position in pile:
                fate_of[group.items[position]] = fate
        exiled: list[str] = []
        returned: list[str] = []
        # Highest index first: taking a card out renumbers everything above
        # it and nothing below, and a creature that arrives and puts something
        # into this graveyard appends to the end.
        for index in sorted(fate_of, reverse=True):
            if not 0 <= index < len(player.graveyard):
                continue
            fate = fate_of[index]
            card = player.graveyard[index]
            if fate == "exile":
                del player.graveyard[index]
                player.exile.append(card)
                exiled.append(card.name)
            elif fate == "battlefield":
                # "Return the other to the battlefield" — under its owner's
                # control, which for a card in your own graveyard is you.
                arrived = game._reanimate_creature_to_battlefield(
                    player, target_permanent_index=index,
                    card_type=_arriving_type(card),
                )
                if arrived is not None:
                    returned.append(card.name)
        if exiled:
            game.log.append(f"{session.card_name} exiled " + ", ".join(exiled))
        if returned:
            game.log.append(
                f"{session.card_name} returned " + ", ".join(returned)
                + " to the battlefield"
            )


def _arriving_type(card) -> str:
    """A type the reanimation seam will find on *card*.

    The seam re-asks "is this still a <type> card" as it takes the card out,
    and the piles were made of whatever the printed phrase named — creature
    cards on the one card that prints this — so the question is asked with a
    type the card has.
    """
    for card_type in ("creature", "artifact", "enchantment", "land", "planeswalker"):
        if card_has_type(card, card_type):
            return card_type
    return "creature"


def _battlefield_fates(game, session: PileSession, chosen_fate: str, other_fate) -> None:
    payload = session.payload

    def permanents(*, chosen: bool) -> list:
        found = []
        for group in session.groups:
            for index, pile in enumerate(group.piles):
                if (index == group.chosen) != chosen:
                    continue
                for position in pile:
                    permanent = game.permanent_by_id(group.items[position])
                    if permanent is not None:
                        found.append(permanent)
        return found

    for fate, members in (
        (chosen_fate, permanents(chosen=True)),
        (other_fate, permanents(chosen=False)),
    ):
        if fate == "destroy":
            destroyed: list = []
            for permanent in members:
                seat = game.controller_index_of(permanent)
                if seat is None:
                    continue
                destroyed.extend(game._destroy_swept_permanents(
                    game.players[seat],
                    lambda candidate, target=permanent: candidate is target,
                    allow_regeneration=not payload.get("no_regeneration"),
                ))
            game.log.append(
                f"{session.card_name} destroyed "
                + (", ".join(p.card.name for p in destroyed) or "nothing")
            )
        elif fate == "tap":
            tapped = [p.card.name for p in members if game.become_tapped(p)]
            game.log.append(
                f"{session.card_name} tapped " + (", ".join(tapped) or "nothing")
            )
        elif fate in ("only_attackers", "only_blockers"):
            # "**Only** creatures in the pile of their choice can attack this
            # turn." A restriction on everything *outside* the pile, so it is
            # state on the game with the pile as its exception list — a
            # creature that arrives after the split is in neither pile and is
            # restricted too (CR 611.2c). One entry per player whose creatures
            # were separated, scoped to that player's creatures.
            restrictions = (
                game.attack_restrictions_until_eot if fate == "only_attackers"
                else game.blocking_restrictions_until_eot
            )
            for group in session.groups:
                allowed = [
                    group.items[position] for position in group.piles[group.chosen]
                ]
                restrictions.append({
                    "filter": dict(payload.get("filter") or {}),
                    "source_name": session.card_name,
                    "controller_seat": group.owner,
                    "except_permanent_ids": allowed,
                    "remaining_turns": 1,
                })
                names = [
                    permanent.card.name
                    for permanent in map(game.permanent_by_id, allowed)
                    if permanent is not None
                ]
                game.log.append(
                    f"{session.card_name}: only "
                    + (", ".join(names) or "no creatures")
                    + f" can {'attack' if fate == 'only_attackers' else 'block'}"
                    f" for {game.players[group.owner].name} this turn"
                )


_PERFORMERS = {
    "library_top": _library_fates,
    "graveyard": _graveyard_fates,
    "battlefield": _battlefield_fates,
}
