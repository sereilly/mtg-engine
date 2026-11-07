"""What one of a viewer's objects offers **right now**, as the engine answers
it: the mana a permanent's tap names (:func:`_offered_mana`), what each mana
ability adds and whether it asks a colour (:func:`_ability_mana`,
:func:`_decided_ability_mana` where the board or a record decides it,
:func:`_ability_mana_payload`), why each ability would be refused before
anything is chosen (:func:`_ability_denial`), the two words an ability's text
change announces (:func:`ability_text_change_offer`) — and, for a card the
viewer may cast, what its cast announces: the colour of the mana the spell
adds (:func:`cast_mana_offer`), a text change's two words
(:func:`text_change_offer`) and how large an X it can pay for
(:func:`cast_x_payable`, :func:`ability_x_payable`).

CLAUDE.md's "what a card can do right now is sent, not re-derived by the
client": these are the readers behind those payload keys. Split out of
``serialization.py`` (the engine-object-to-JSON layer, which calls them) as it
neared its 2,000-line cap — code motion, the bodies unchanged — so the next
answer the client stops re-deriving has a home by subject.
"""

from __future__ import annotations

from engine import Game
from engine.activation_prohibitions import activation_prohibition
from engine.ai_text_changes import ability_text_change_mode, announced_text_change_mode
from engine.board_payment import board_can_pay, tap_alone_symbols
from engine.cost_modifiers import cast_mana_charge
from engine.cost_x_definitions import cost_x_is_defined
from engine.mana_could_produce import ability_colors_on_offer, types_that_land_could_produce
from engine.models import Permanent
from engine.noted_mana import noted_mana
from engine.oracle import compile_card_oracle
from engine.oracle_types import x_spend_colors_from_text
from engine.restricted_mana import ACTIVATE, CAST, PaymentPurpose
from engine.text_changes import TEXT_CHANGE_MODE_KINDS, current_text_card, words_written


def _offered_mana(game: Game, perm: Permanent) -> tuple[str, ...]:
    """The symbols the client offers when this permanent is tapped for mana.

    The permanent's own answer, except where tapping a land lets the tapper
    name a colour the printed summary does not list: a seat-wide swap ("…it
    produces one mana of **a color of your choice** instead of any other type
    and amount", Harvest Mage) or a granted ability ("Lands you control have
    "{T}: Add two mana of **any one color**."", Overlaid Terrain). The client
    prompts for a colour only when a land offers two or more, so a Forest that
    answered "G" here would never be asked — the seam would get the default
    request and the choice the card prints would be one no human could make.

    Read off the planner's hook (``Game._land_payment_colors``), so the client
    and the payment planner cannot disagree. Only a *choice* is taken from it:
    a fixed swap (Deep Water) answers one symbol, which the seam decides
    whatever is requested, and is left showing what it always showed.
    """
    own = tuple(perm.effective_produced_mana)
    if perm.has_type("land"):
        # A land whose colours the board defines (Reflecting Pool, Meteor
        # Crater) is offered as exactly what it makes here, even when that is
        # one colour or none: its printed summary is all five, and a picker
        # built from it asks for colours the engine will not produce.
        narrowed = game.narrowed_land_mana_colors(perm)
        if narrowed is not None:
            return narrowed
        # …and a land a tap makes only a *gained* type's mana from (a
        # depletion land under Blanket of Night) is offered as that: its
        # summary also lists what its own, priced, ability makes, and a
        # picker built from it asks for a colour the tap will not produce.
        gained_only = game._tap_alone_makes_only_gained_mana(perm)
        if gained_only:
            return gained_only
        payable = tuple(game._land_payment_colors(perm))
        if len(payable) > 1 and set(payable) != set(own):
            return payable
        # …and a land with mana abilities of its own is offered as what **a
        # tap alone** makes of it (CR 605: each mana ability is its own). The
        # summary lists every symbol any ability of the land makes: a School
        # of the Unseen ("{T}: Add {C}." / "{2}, {T}: Add one mana of any
        # color.") was shown as five colours, the click that named one made
        # {C}, and the client's own auto-tap planned it for a pip it could
        # not pay. The priced ability is still on the land's ability list, to
        # be activated for what it costs. In the summary's own order, so a
        # land every one of whose abilities is the tap alone (a painland) is
        # shown exactly as it was.
        tapped_for = tap_alone_symbols(game, perm)
        if tapped_for:
            kept = tuple(symbol for symbol in own if symbol in tapped_for)
            return kept + tuple(symbol for symbol in tapped_for if symbol not in kept)
    return own


#: Payload keys of an add-mana step that change *how much* it makes or what the
#: mana may pay for, never *which symbols* it can be asked for.
_MANA_AMOUNT_KEYS = frozenset({
    "per_each", "per_each_counter_removed", "per_each_counter_on_source",
    "pips_amount", "spend_only", "x_from_count", "any_color_count", "oracle_text",
})


def _effect_steps(instruction) -> list:
    """*instruction*'s own steps, a ``sequence`` opened up."""
    if instruction is None:
        return []
    if instruction.kind == "sequence":
        return [
            leaf
            for step in (instruction.payload or {}).get("steps") or ()
            if hasattr(step, "kind")
            for leaf in _effect_steps(step)
        ]
    return [instruction]


def _ability_mana(instruction) -> dict | None:
    """What one activation of a mana ability adds, as its own payload states
    it: ``{"symbols": […], "choice": bool}``, or None where the payload alone
    does not say.

    ``choice`` is the question the client has to ask. "{1}, {T}: Add {R}{G}."
    (Mossfire Valley) and "{T}: Add {C}{C}." make a **fixed** output — every
    symbol, whichever is named — and "{T}: Add {R} or {G}." makes **one of**
    its symbols. The permanent's ``produced_mana`` cannot tell those apart: it
    is a summary of everything the permanent can make, so a filter land and a
    dual land read the same there, and the client opened a colour fan for an
    ability with nothing to choose and then sent an answer the engine ignored.

    Riders that change the amount or restrict the spend are read through; a
    shape whose symbols the board or a record decides (``any_color_from``,
    ``from_noted`` …) is None here, and :func:`_decided_ability_mana` answers
    it with the board. A split the seat chooses ("in any combination of")
    carries a ``combination`` entry of its own: ``{"symbols": […], "count":
    N}``.
    """
    adders = [step for step in _effect_steps(instruction) if step.kind == "add_mana_from_text"]
    if not adders:
        return None
    symbols: list[str] = []
    choice = False
    for step in adders:
        payload = step.payload or {}
        shape = set(payload) - _MANA_AMOUNT_KEYS
        if shape == {"pips"}:
            found = [str(symbol) for symbol, _count in payload["pips"]]
        elif shape == {"pips_choice"} and len(adders) == 1:
            found = [str(symbol) for symbol, _count in payload["pips_choice"]]
            choice = len(set(found)) >= 2
        elif shape == {"any_color"} and payload.get("any_color") and len(adders) == 1:
            found = ["W", "U", "B", "R", "G"]
            choice = True
        elif (
            shape == {"combination", "combination_count"}
            and len(adders) == 1
            and isinstance(payload["combination_count"], int)
        ):
            # "Add three mana in any combination of {R} and/or {G}" (Goblin
            # Clearcutter): a **split**, which a colour fan cannot ask for —
            # so the entry says how many and of which, and the activate action
            # takes the answer as ``mana_combination`` ({symbol: count}).
            # ``choice`` stays true for a client that knows only the fan: one
            # colour named is every unit that colour, a legal split.
            found = [str(symbol) for symbol in payload["combination"]]
            return {
                "symbols": found, "choice": True,
                "combination": {"symbols": found, "count": int(payload["combination_count"])},
            }
        else:
            return None
        symbols.extend(symbol for symbol in found if symbol not in symbols)
    return {"symbols": symbols, "choice": choice} if symbols else None


#: CR 105.1's colours in WUBRG order, then colourless (CR 106.1b's sixth
#: type): the order a stated symbol list is sent in.
_SYMBOL_ORDER: tuple[str, ...] = ("W", "U", "B", "R", "G", "C")


def _ordered(symbols) -> list[str]:
    found = {str(symbol).upper() for symbol in symbols}
    return [symbol for symbol in _SYMBOL_ORDER if symbol in found]


def _every_step(instruction) -> tuple:
    """*instruction* and every step inside it, at any depth — an offer's
    branches included ("…unless any player pays {1}", Rhystic Cave)."""
    from engine.mana_payment import _every_nested_step

    if instruction is None:
        return ()
    return (instruction, *_every_nested_step(instruction))


def _decided_ability_mana(game: Game, perm: Permanent, instruction) -> dict | None:
    """What one activation of a mana ability adds where the ability's own
    payload does not say — the board, a record or the cost decides it — in
    :func:`_ability_mana`'s shape, or None for an ability with no add-mana
    step at all.

    The handler's own readings (``handlers/mana.add_mana_from_text``), so the
    client asks exactly the question the resolution answers:

    * a "could produce" clause or a colour "of a permanent you control"
      (Fellwar Stone, Quirion Explorer, Harvester Druid, Star Compass,
      Reflecting Pool, Meteor Crater): ``mana_could_produce.
      ability_colors_on_offer``, CR 106.7's fixpoint over this board — the
      set the resolution re-checks a named colour against. Empty is a real
      answer: the ability adds nothing here;
    * "Choose a color. Add one mana of that color" with nothing narrowing
      the choice (Rhystic Cave): the five colours, named with the activation
      (CR 605.3b, ``handlers/value_choices.choose_color``);
    * a colour recorded as the permanent entered ("Add one mana of the chosen
      color", Sol Grail, Quirion Elves) or noted by an earlier activation
      (Jeweled Amulet, Ice Cauldron): that record, nothing to ask;
    * the symbols of a card the cost mills (Charmed Pendant): unknown until
      the cost is paid, nothing to ask;
    * "…of any type **that land** could produce" (Benthic Explorers,
      Squandered Resources): per land the cost could name, by id
      (``symbols_by_cost``), what that land could produce — the cost is
      chosen first, so the question is that land's (``symbols`` is their
      union, for a client that has not chosen yet);
    * "Add {U} or {C}{U}" (Adarkar Unicorn, Cadaverous Bloom): the written-out
      quantities to choose between (``alternatives``, each ``{symbol:
      count}``), answered on the activate action's ``mana_combination``.

    Before this the client was told nothing for these, and fell back to the
    card's text ("one mana of any color" — all five for a Fellwar Stone whose
    opponent had two colours of land) or to the permanent's summary — a fan of
    five for Sol Grail, Jeweled Amulet and Charmed Pendant, whose answers the
    engine never read, and a fan of {B} and {G} for Cadaverous Bloom whose
    {G} made {B}{B}.
    """
    steps = _every_step(instruction)
    adders = [step for step in steps if step.kind == "add_mana_from_text"]
    if not adders:
        return None
    offered = ability_colors_on_offer(game, perm, instruction)
    if offered is not None:
        return {"symbols": list(offered), "choice": len(offered) >= 2}
    if len(adders) != 1:
        return None
    payload = adders[0].payload or {}
    if payload.get("color_from") and any(
        step.kind == "choose_color"
        and not (step.payload or {}).get("among")
        and not (step.payload or {}).get("chooser")
        for step in steps
    ):
        return {"symbols": ["W", "U", "B", "R", "G"], "choice": True}
    if payload.get("from_chosen_color"):
        chosen = (perm.metadata or {}).get("chosen_color")
        return {"symbols": _ordered([chosen] if chosen else ()), "choice": False}
    if payload.get("from_noted"):
        return {"symbols": _ordered(noted_mana(perm)), "choice": False}
    if payload.get("colored_symbols_of_record"):
        return {"symbols": [], "choice": False}
    if payload.get("any_type_from") is not None:
        by_cost = {
            str(land.permanent_id): list(types)
            for land in game.all_permanents()
            if land.has_type("land") and (types := types_that_land_could_produce(land))
        }
        union = _ordered(symbol for types in by_cost.values() for symbol in types)
        return {"symbols": union, "choice": len(union) >= 2, "symbols_by_cost": by_cost}
    alternatives = payload.get("pips_alternatives")
    if alternatives:
        stated = [
            {str(symbol).upper(): int(count) for symbol, count in alternative}
            for alternative in alternatives
        ]
        return {
            "symbols": _ordered(symbol for alternative in stated for symbol in alternative),
            "choice": len(stated) >= 2,
            "alternatives": stated,
        }
    return None


def _ability_mana_entry(game: Game, perm: Permanent, ability) -> dict | None:
    """One ``ability_mana`` entry: the payload's answer (:func:`_ability_mana`),
    else the board's (:func:`_decided_ability_mana`), else — for an add-mana
    step neither reads — the permanent's own summary, so that None means only
    "this ability adds no mana" and a client can rely on it."""
    instruction = getattr(ability, "instruction", None)
    stated = _ability_mana(instruction)
    if stated is not None:
        return stated
    decided = _decided_ability_mana(game, perm, instruction)
    if decided is not None:
        return decided
    if not any(step.kind == "add_mana_from_text" for step in _every_step(instruction)):
        return None
    summary = _ordered(_offered_mana(game, perm))
    return {"symbols": summary, "choice": len(summary) >= 2}


def _ability_mana_payload(game: Game, perm: Permanent, usable) -> list | None:
    """``ability_mana`` for one of the viewer's permanents: one entry per
    usable ability, indexed like the ``ability_index`` the activate action
    takes (so a one-ability permanent's is entry 0) — what that ability adds
    and whether activating it asks (:func:`_ability_mana_entry`), or None for
    an ability that adds no mana. The field is left off when no ability adds
    any, and when the board has changed what a land offers
    (:func:`_offered_mana`'s swap or narrowing): there the summary is the
    answer and an ability's printed symbols are not.
    """
    if not usable:
        return None
    if perm.has_type("land") and set(_offered_mana(game, perm)) != set(perm.effective_produced_mana):
        return None
    entries = [_ability_mana_entry(game, perm, ability) for ability in usable]
    return entries if any(entry is not None for entry in entries) else None


def _ability_denial(game: Game, seat: int, perm, ability) -> str | None:
    """Why *ability* of *perm* would be refused if *seat* activated it now,
    before anything is chosen or paid — the activation path's own sentence —
    or None.

    The path's checks in its order (``_activation_window``), each the
    predicate the path asks: a loyalty ability's window (CR 606.3, 606.6,
    ``Game.loyalty_activation_refusal``), the prohibition table (CR 602.5,
    ``activation_prohibition``), a targeting ban (Peace Talks), an owner-only
    line, the per-turn cap, the {T} symbol's two refusals (CR 302.6 / 602.5a
    and 107.5, ``Game.tap_symbol_refusal``), and a cost paid in something
    other than mana that the board cannot pay (CR 601.2h,
    ``Game.unpayable_activation_cost``, with no X announced — the smallest X,
    so nothing payable is denied). The client kept a copy of several: the six
    "Activate only …" windows read off the ability's text
    (``activationTimingDisabledReason``), Library of Alexandria's hand size,
    Jandor's Ring's last-drawn card, the loyalty rules, and the {T} symbol
    read off the *first* ability's printed cost (``abilityCostRequiresTap``).
    Not here: what depends on a choice still to be made (a target, an X —
    "X can't be 0").
    """
    details = game.loyalty_activation_refusal(seat, perm, ability)
    if details is not None:
        return details
    found = activation_prohibition(game, seat, perm, ability)
    if found is not None:
        return found.details
    for refusal in (
        game.targeting_ban_activation_refusal(perm, ability),
        game.owner_only_activation_refusal(seat, perm, ability),
        game.activation_limit_refusal(seat, perm, ability),
        game.tap_symbol_refusal(perm, ability),
    ):
        if refusal is not None:
            return refusal
    return game.unpayable_activation_cost(seat, perm, ability)


def cast_mana_offer(card) -> dict | None:
    """What *card*'s own resolution adds, as a spell — ``{"symbols": […],
    "choice": bool}`` (:func:`_ability_mana`'s reading of its steps) — or None.

    The colour of "Add X mana of any one color" (Metamorphosis, Traitorous
    Greed) is announced with the cast (the cast path carries it as
    ``new_color``), so the client asks it while casting when ``choice`` is
    set. Only an instant or a sorcery: a permanent spell's resolution puts
    the permanent onto the battlefield (CR 608.3) and adds nothing — an
    "enters" trigger's mana (Quirion Sentinel), a triggered ability's (Carpet
    of Flowers, Sanctum of Fruitful Harvest) or a mana ability's are chosen
    as *that* ability resolves. The client read "any one color" anywhere in
    the card's text outside an activated line, so casting any of those five
    asked a colour the engine never read.
    """
    if card.primary_type not in ("instant", "sorcery"):
        return None
    for instruction in compile_card_oracle(card).instructions:
        found = _ability_mana(instruction)
        if found is not None:
            return found
    return None


def text_change_offer(game: Game, card) -> dict | None:
    """The two words a text change cast announces (CR 612): which
    vocabularies it names them from, and — per object it could be aimed at —
    the words that object's text writes now, the ones there are to replace.

    ``{"mode": …, "words": {permanent id: [symbol, …]}, "stack_words":
    {top-first stack index: [symbol, …]}}``, each word a mana symbol (W is
    white and Plains), objects writing none left out — or None for a card
    whose cast announces no words (``ai_text_changes.
    announced_text_change_mode``: Artificial Evolution's are chosen as it
    resolves; Balduvian Shaman's change is an activated ability, not its
    cast).

    The words are ``text_changes.words_written`` over what the object says
    now (``current_text_card``: a second change rewrites what the first
    wrote, a face-down object writes nothing), the reading the resolution's
    "had no effect" and its vocabulary question ask. The client read the
    card's text for "basic land type" to pick a vocabulary — so Mind Bend,
    Crystal Spray and Whim of Volrath, which offer both, offered land types
    alone and refused a target writing only a colour word — and read the
    target's text for land words by substring.
    """
    mode = announced_text_change_mode(card)
    if mode is None:
        return None
    return _text_change_words(game, mode)


def ability_text_change_offer(game: Game, ability) -> dict | None:
    """:func:`text_change_offer` for one **activated ability** whose
    activation announces the two words (CR 612 through CR 602.2b:
    "{T}: Change the text of target white enchantment you control … by
    replacing all instances of one color word with another", Balduvian
    Shaman) — ``ai_text_changes.ability_text_change_mode``, the reading the
    AI's activation names its words by — or None for every other ability.

    Sent as ``ability_text_change``, indexed like ``ability_index``; the
    activate action takes the words on ``old_color`` / ``mana_color``. The
    client asked none, so from a browser the Shaman's ability resolved with
    no words and changed nothing.
    """
    mode = ability_text_change_mode(getattr(ability, "instruction", None))
    if mode is None:
        return None
    return _text_change_words(game, mode)


def _text_change_words(game: Game, mode: str) -> dict:
    """``{"mode", "words", "stack_words"}`` for a text change of *mode*: per
    permanent (by id) and per spell (by top-first stack index), the words of
    the mode's vocabularies its text writes now."""
    kinds = TEXT_CHANGE_MODE_KINDS[mode]

    def written(holder) -> list[str]:
        text_card = current_text_card(holder)
        found: list[str] = []
        for kind in kinds:
            found.extend(symbol for symbol in words_written(text_card, kind) if symbol not in found)
        return sorted(found, key="WUBRG".index)

    words = {
        str(permanent.permanent_id): found
        for permanent in game.all_permanents()
        if (found := written(permanent))
    }
    stack_words = {
        str(position): found
        for position, item in enumerate(reversed(game.stack))
        if (found := written(item))
    }
    return {"mode": mode, "words": words, "stack_words": stack_words}


#: The largest X the X prompt offers (:func:`x_payable`): no board in the pool
#: pays more, and each step is one matching.
_X_CEILING = 30


def _largest_payable_x(
    game: Game, seat: int, prices, purpose, *, pool_only: bool, known: int = 0,
) -> int:
    """The largest X for which some price ``prices(X)`` yields is payable —
    from the pool alone, or with every source *seat* could tap — or 0.
    *known* is an X already known to be payable (the pool's, for the board's
    search: what the pool pays the board pays), searched up from."""
    best = known
    for x in range(known + 1 if known else 0, _X_CEILING + 1):
        if not any(
            board_can_pay(
                game, seat, required, purpose=purpose, nonland_sources=True,
                pool_only=pool_only,
            )
            for required in prices(x)
        ):
            break
        best = x
    return best


def _x_payable_by(game: Game, seat: int, prices, purpose, colors) -> dict:
    """``{"pool", "board", "colors"}`` for one X announcement (see
    :func:`cast_x_payable`)."""
    if not game.enforce_mana_costs:
        return {"pool": _X_CEILING, "board": _X_CEILING, "colors": list(colors)}
    pool = _largest_payable_x(game, seat, prices, purpose, pool_only=True)
    board = _largest_payable_x(game, seat, prices, purpose, pool_only=False, known=pool)
    return {"pool": pool, "board": board, "colors": list(colors)}


def cast_x_payable(game: Game, seat: int, card) -> dict | None:
    """How large an X *seat* can pay for casting *card* from its hand now —
    ``{"pool": n, "board": m, "colors": [...]}`` — or None for a card whose
    mana cost has no {X}.

    ``pool`` is what the mana already in the pool pays; ``board`` adds what
    the seat could tap (its lands and every other tap-alone source,
    ``board_payment.board_can_pay``'s player's reading — what the auto-tap
    would tap for it). The price at each X is the one the cast charges
    (``cost_modifiers.cast_mana_charge``: the increases and reductions in
    force, a coloured pip a tax adds), with X split the ways "Spend only
    black and/or red mana on X" lets it be (``colors``,
    ``Game._x_color_allocations``). The client priced X itself
    (``getMaxAffordableX``): the printed cost against the pool, one X colour
    read off the text, no tax, no reduction, no spending permission. Before
    any per-target tax or optional cost the cast announces, which the client
    subtracts as it learns them.
    """
    if "{X}" not in (card.mana_cost or "").upper():
        return None
    colors = x_spend_colors_from_text(card.oracle_text or "")
    purpose = PaymentPurpose(CAST, card=card)

    def prices(x: int):
        return [
            cast_mana_charge(game, seat, card, x_value=x, x_allocation=allocation)
            for allocation in game._x_color_allocations(colors, x)
        ]

    return _x_payable_by(game, seat, prices, purpose, colors)


def zone_x_payable(game: Game, seat: int, spell, permission) -> dict | None:
    """:func:`cast_x_payable` for a cast out of a graveyard or an exile under
    *permission* (``state_view._zone_cast_options``' ways): an alternative
    cost with an {X} in its mana (Flaming Gambit's "Flashback {X}{R}{R}")
    priced by ``Game.alternative_cost_mana`` at each X, an unpriced
    permission by the card's own mana cost — or None where the way prints no
    {X}, or waives the cost (CR 107.3b: X is 0)."""
    if permission.free:
        return None
    if permission.cost is None:
        return cast_x_payable(game, seat, spell)
    if "{X}" not in (permission.cost.mana or "").upper():
        return None
    colors = x_spend_colors_from_text(spell.oracle_text or "")
    purpose = PaymentPurpose(CAST, card=spell)

    def prices(x: int):
        return [
            game.alternative_cost_mana(
                seat, spell, permission.cost, x_value=x, x_allocation=allocation,
            )
            for allocation in game._x_color_allocations(colors, x)
        ]

    return _x_payable_by(game, seat, prices, purpose, colors)


def ability_x_payable(game: Game, seat: int, perm: Permanent, ability) -> dict | None:
    """:func:`cast_x_payable` for one activated ability whose cost prints
    {X} — priced by the activation path's own ``Game.activation_mana_charge``
    (a tax, a reduction, "Spend only red mana on X") — or None for an ability
    whose cost has none, or whose X the card defines or the cost spends in
    something other than mana (counters, CR 606.6's loyalty)."""
    line = (getattr(ability, "source_line", None) or "").lower()
    # The cost clause's own {X} (the activation path's reading), and not one
    # the card defines (Voodoo Doll's pin counters, CR 601.2b).
    if "{x}" not in line.split(":", 1)[0] or cost_x_is_defined(ability.source_line or ""):
        return None
    colors = x_spend_colors_from_text(getattr(ability, "source_line", None) or "")
    purpose = PaymentPurpose(ACTIVATE, source=perm)
    priced: dict[int, list] = {}

    def prices(x: int):
        if x not in priced:
            charge = game.activation_mana_charge(seat, perm, ability, x_value=x)
            priced[x] = [] if isinstance(charge, str) else [charge[0]]
        return priced[x]

    if not prices(0):
        return None
    return _x_payable_by(game, seat, prices, purpose, colors)
