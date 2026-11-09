"""``ActivatedAbilityCost``: what an activated ability costs (CR 602.1a, CR 118).

The record ``activation_costs.parse_activated_ability_cost`` reads off the text
left of an ability's activation colon, and the one the activation path charges:
the mana symbols and {T}, a loyalty symbol (CR 606.4), and every prose payment
beside them. One field per kind of payment, each defaulting to "no such cost",
so a new kind of cost is a field here and its reader in ``activation_costs``.

Split out of ``engine/oracle_types.py`` at the size band (round kg3), where it
was the largest single definition and the part that grows with every new kind
of cost. Like that module it imports nothing from the engine, so anything may
import it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActivatedAbilityCost:
    mana: dict[str, int]
    requires_tap: bool = False
    # Jandor's Ring: "{2}, {T}, Discard the last card you drew this turn: Draw a
    # card." A non-mana additional cost — the ability can't be activated unless
    # that card is still in hand, and activating discards it.
    discard_last_drawn: bool = False
    # Ring of Ma'rûf: "{5}, {T}, Exile this artifact: ..." — activating exiles
    # the source permanent as part of the cost.
    exile_self: bool = False
    # Black Lotus / Bottle of Suleiman: "…, Sacrifice this artifact: …" —
    # activating sacrifices the source permanent as part of the cost, so the
    # ability still resolves after it has left the battlefield (CR 603.6).
    sacrifice_self: bool = False
    # Cycle of Life: "Return this enchantment to its owner's hand: …" — the two
    # above one zone over (CR 118.3). Its own field rather than a value on
    # theirs because *where the source goes* is the whole difference: an exiled
    # source is gone for the game and a returned one can be cast again, which is
    # what the card is for. Like both of them, the ability resolves with its
    # source already gone (CR 603.6).
    return_self_to_hand: bool = False
    # Hobblefiend: "{1}, Sacrifice another creature: …" — a *chosen* permanent
    # rather than the source. The whole printed noun phrase is payload, so one
    # field covers every card printed this way, "a creature **with defender**"
    # (Portcullis Vine) included. None means "no such cost", never "any
    # permanent": an empty filter would let the charger eat a land, and it is
    # also the answer for a phrase the charger cannot test — the grammar refuses
    # such a line, and this reader must not disagree by charging the wider cost.
    sacrifice_filter: dict | None = None
    #: How many of them. "Sacrifice **a** creature" (Hobblefiend) is one;
    #: "Sacrifice this artifact **and any number of** creatures you control"
    #: (Sword of the Ages) is a set whose size the payer chooses, announced on
    #: activation. Beside the filter for the reason ``remove_counter_count`` is
    #: beside its kind: only a fixed count can make an ability unpayable, and
    #: "any number" never can, since zero is a number (CR 601.2h).
    sacrifice_count: "int | str" = 1
    #: City of Shadows: "{T}, Exile **a creature you control**: ..." /
    #: Necropolis: "Exile **a creature card from your graveyard**: ..." - a
    #: *chosen* object rather than the source, which is what ``exile_self``
    #: above names. Its own field for the reason ``sacrifice_filter`` is one
    #: beside ``sacrifice_self``: a chosen payment needs a picker, a
    #: payability check and a record of what it ate, and the source needs
    #: none of the three. None means "no such cost", never "anything": an
    #: empty filter would let the charger eat a land.
    exile_filter: dict | None = None
    #: Which zone that payment comes out of - ``"battlefield"`` (a permanent
    #: the payer controls), ``"graveyard"`` (a card in the payer's own) or
    #: ``"hand"`` (Cadaverous Bloom's "Exile a card from your hand"). Beside
    #: the filter rather than inside it because the three enumerate different
    #: kinds of object, and a matcher for one cannot answer about the others
    #: (CR 613.1: a card in a zone has no computed characteristics at all).
    exile_zone: str = "battlefield"
    #: Whose zone that payment comes out of: ``"you"`` (the payer's own pile,
    #: Necropolis) or ``None`` for **any one player's** ("from a graveyard" /
    #: "from a single graveyard", Night Soil). Beside ``exile_zone`` rather
    #: than folded into it because they answer different questions — which zone
    #: and whose — and a charger that read one as the other would enumerate the
    #: wrong pile and pay nothing while the ability still resolved.
    exile_zone_owner: str | None = "you"
    #: How many objects that payment eats. "Exile **two** creature cards"
    #: (Night Soil); one everywhere else. Beside the filter for the reason
    #: ``sacrifice_count`` is: only a count can make the cost unpayable, and
    #: one card is no more a payment of a two-card cost than none is
    #: (CR 601.2h).
    #:
    #: ``"any"`` is "Exile **any number of** cards from your graveyard"
    #: (Painbringer): the payer names the set as the ability is activated
    #: (CR 601.2b) and naming none is a legal payment, the reading
    #: ``sacrifice_count`` gives Sword of the Ages' identical words one field
    #: up. Charged only out of the payer's own graveyard — the one zone with a
    #: channel that names several cards (``cost_graveyard_indices``).
    exile_count: "int | str" = 1
    #: "…from **a single** graveyard" (Night Soil). Every card must come out of
    #: the *same* pile. Its own flag rather than a narrowing of the filter,
    #: because the filter is asked of one card at a time and cannot say it —
    #: and dropped, the cost would be payable with one card from each of two
    #: graveyards, which is strictly cheaper than the card prints.
    exile_same_zone: bool = False
    # Seasoned Hallowblade: "Discard a card: …" — N cards the payer chooses,
    # where `discard_last_drawn` above names its card by history and leaves the
    # payer no choice at all. Two fields because they are two costs: a card
    # could print both.
    discard_cards: int = 0
    # Sanctum of Shattered Heights: "Discard a land card or Shrine card: …" —
    # what the discarded card must be, one payload per printed alternative, OR'd.
    # A tuple because the "or" unions two *different* characteristics and a
    # single filter AND's its keys; empty is the unrestricted "Discard a card",
    # which `discard_cards` above already says exists. A phrase the card matcher
    # cannot test never reaches here — the grammar refuses the line and
    # `_chargeable_discard_filters` refuses to read one, the same pairing
    # `sacrifice_filter` describes.
    discard_filters: tuple[dict, ...] = ()
    #: "Discard a card at random" (Coral Helm). The payer picks nothing; the
    #: activation path draws the card from the hand with the module RNG, so a
    #: seeded run reproduces it.
    discard_at_random: bool = False
    # Subira: "Discard your hand: …" — every card, chosen by nobody. Its own
    # field rather than a large ``discard_cards``, because the payability check
    # is the opposite: a count can be unpayable for want of cards, and this one
    # never is.
    discard_whole_hand: bool = False
    # Waker of Waves: "{1}{U}, **Discard this card**: …". The card discards
    # *itself* to pay, which is also what says the ability functions from the
    # hand at all (CR 113.6 — an ability works only from the battlefield unless
    # something says otherwise, and a cost the card can only pay from hand says
    # exactly that). Its own field rather than a `discard_cards=1` with a
    # self-filter: the payer chooses nothing, and the ability is unactivatable
    # from anywhere else.
    discard_self: bool = False
    # Mazemind Tome: "Put a **page** counter on this artifact". A cost that adds
    # an inert marker (CR 122.1) — never unpayable, and read by nothing but the
    # card's own state trigger. The counter's printed word, or None.
    put_counter: str | None = None
    # Scavenging Ghoul: "**Remove a corpse counter from this creature**:
    # Regenerate this creature." The mirror of ``put_counter`` and the half that
    # *can* be unpayable — CR 602.1a makes a counter removal an activation cost
    # like any other, so an ability whose source has none may not be activated.
    #
    # The counter's printed word, exactly as ``put_counter`` carries it, because
    # the kinds are open (CR 122.1): "corpse", "matrix", "dream". This was a
    # substring test for one of those words inside the activation path, so an
    # ability granted with any other counter's name — Life Matrix grants one —
    # was activated for free and could be activated forever.
    remove_counter: str | None = None
    #: How many of them. The Mana Batteries print "Remove **any number of**
    #: charge counters from this artifact", where Scavenging Ghoul prints "a".
    #: An int is a fixed count; ``"any"`` is the payer's choice, announced on
    #: activation the way an X is (CR 601.2b), and what the effect then reads
    #: back is how many actually came off.
    #:
    #: Beside ``remove_counter`` rather than folded into it, because the two
    #: answer different questions and only one of them can be unpayable: a fixed
    #: count needs at least that many on the permanent, while "any number" is
    #: payable with none at all (CR 601.2h — zero is a number).
    remove_counter_count: "int | str" = 1
    # Shacklegeist: "Tap two untapped Spirits you control: …" — N permanents the
    # payer taps, named by the printed noun phrase. Distinct from
    # ``requires_tap``, which taps the *source* and is the {T} symbol: this taps
    # other permanents and the source is not among them unless the phrase names
    # it. None means "no such cost", never "any permanent", for the reason
    # ``sacrifice_filter`` gives.
    tap_filter: dict | None = None
    tap_count: int = 0
    # Quirion Ranger: "Return a Forest you control to its owner's hand: …";
    # Flooded Shoreline: "{U}{U}, Return **two** Islands you control to their
    # owner's hand: …". The same shape as the tap cost above one zone over
    # (CR 118.3): N permanents the payer picks off their own battlefield, named
    # by the printed noun phrase, and the source is not among them unless the
    # phrase names it.
    #
    # Its own pair rather than a value on ``return_self_to_hand``, for the
    # reason that flag is its own field beside ``sacrifice_self``: *which*
    # permanent goes is the whole difference. The self-return is a fact about
    # the source and needs no picker; this one has to be paid out of a set, can
    # be unpayable (CR 601.2h), and the payer chooses.
    #
    # None means "no such cost", never "any permanent", for the reason
    # ``sacrifice_filter`` gives: an empty filter would let the charger take a
    # land where the card named a Forest, and None is also the answer for a
    # phrase the charger cannot test.
    return_to_hand_filter: dict | None = None
    return_to_hand_count: int = 0
    # Tavern Swindler: "{T}, Pay 3 life: …" — a life payment as an activation
    # cost (CR 118.3b, 119.4). A count rather than a flag, because the amount is
    # printed; 0 is the honest "no such cost", since CR 119.4b makes paying 0
    # life always legal and therefore never a restriction on activating.
    pay_life: int = 0
    #: "Pay 3 life **for each velocity counter on this enchantment**"
    #: (Tornado). The counter's printed kind, when ``pay_life`` above is a
    #: *rate* rather than the amount owed. CR 601.2f computes a cost as the
    #: ability is activated, and this multiplier lives on the ability's own
    #: source — so the number is read there, at the two sites that check and
    #: charge the payment, and never here.
    #:
    #: Its own field rather than a computed ``pay_life``, because a reader that
    #: has not learned the word charges the printed rate — which for Tornado's
    #: first activation is *more* than the card asks, and never less. A cost
    #: charged too low is a free ability; too high is a refused one, and only
    #: the first is silent.
    pay_life_per_counter: str | None = None
    #: "**Pay half your life, rounded up**" (Lurking Evil). The amount is a
    #: fraction of the payer's own life total rather than a printed number, so
    #: it is computed at activation (CR 601.2f) by the same two sites
    #: ``pay_life_per_counter`` above is — the payability gate and the payment
    #: — and never here. CR 107.2's rounding is the card's own word.
    #:
    #: Its own flag rather than a value of ``pay_life``, for that field's
    #: reason exactly: a reader that has not learned the word charges the
    #: printed number, and ``pay_life`` stays 0 while this is set, so such a
    #: reader charges *nothing* — a free ability. The flag is what makes the
    #: cost visible to `activation_life_cost`, which is the one function that
    #: answers "how much, right now".
    pay_life_half_rounded_up: bool = False
    #: "**Pay {1} for each +1/+1 counter on this creature**" (Skeleton
    #: Scavengers). The counter whose count multiplies
    #: :attr:`mana_per_counter_cost` below, on the ability's **own source** --
    #: the same restriction ``pay_life_per_counter`` states one field up, and
    #: for its reason: a counter on anything else is a board read the charger
    #: does not have in hand.
    #:
    #: Its own pair of fields rather than more of ``mana``, because those pips
    #: are the whole cost and these are a *rate*. Folded in, Skeleton
    #: Scavengers would regenerate for {1} however large it has grown, which is
    #: a strictly cheaper card -- and a cost charged too low is a free ability
    #: where one charged too high is a refused one, so only the first is
    #: silent.
    mana_per_counter: str | None = None
    #: What **one** counter costs, as a symbol dict like :attr:`mana`.
    mana_per_counter_cost: dict[str, int] | None = None
    #: "Pay 2 life **or {2}**" (Tidal Control). The mana that may be paid
    #: *instead of* ``pay_life`` above, as a symbol dict like ``mana``.
    #: CR 601.2h: the payer chooses between the printed alternatives as the
    #: ability is activated.
    #:
    #: Separate from ``mana`` for the reason the AST field it comes from is
    #: separate: folded in, the two halves of an "or" are charged *together*,
    #: which is what the prose reader below did until this field existed —
    #: Tidal Control asked for two life **and** {2}.
    alternative_mana: dict[str, int] | None = None
    # CR 606.4: a loyalty ability's cost is putting on or removing loyalty
    # counters. ``loyalty`` is the signed delta ("+1" → 1, "−2" → -2, "0" → 0);
    # ``loyalty_x_sign`` is set instead for a variable cost ("−X" → -1), whose
    # magnitude is the X the player announces on activation. ``None``/``None``
    # means the ability is not a loyalty ability at all — 0 is a real cost
    # (CR 606.5), so it cannot double as the "absent" value.
    loyalty: int | None = None
    loyalty_x_sign: int | None = None
    #: Earthlore: "**Tap enchanted land**: Target blocking creature gets +1/+2
    #: until end of turn." An Aura whose cost taps the permanent it is attached
    #: to — the host, never the Aura itself, which is what ``requires_tap``'s
    #: ``{T}`` means and why this is a separate field rather than that flag.
    #: A pre-symbol templating of the same payment: nothing else can pay it, so
    #: there is no picker and no filter, only the attachment record.
    #:
    #: Last in the field order deliberately: ``parse_activated_ability_cost``
    #: builds this with six positional arguments, so a field inserted among
    #: them silently rebinds one of the six.
    tap_attached: bool = False
    #: Merseine: "**Pay enchanted creature's mana cost**: Remove a net counter
    #: from this Aura." A mana cost read off the *host*, which the ``mana``
    #: dict above cannot carry: that dict is fixed when the card compiles, and
    #: this number is whatever the enchanted permanent's printed cost happens
    #: to be at the moment of activation (CR 202.1, CR 601.2f-h). So the flag
    #: says *where the cost comes from* and the activation path builds the
    #: symbols; an ability with this set and no host is unpayable rather than
    #: free.
    #:
    #: After ``tap_attached`` for that field's stated reason: the six
    #: positional arguments ``parse_activated_ability_cost`` passes are at the
    #: front, so a field inserted among them silently rebinds one of them.
    mana_from_attached: bool = False
    #: Royal Herbalist: "{2}, **Exile the top card of your library**: You gain 1
    #: life." How many cards off the top the activation eats — 0 is the honest
    #: "no such cost", since exiling zero cards is no payment at all.
    #:
    #: An ``int`` rather than a filter beside ``exile_filter``, because nothing
    #: is chosen and nothing is tested: the cards are named by *position*, so
    #: there is no picker to offer from and no characteristic to match. And a
    #: separate field rather than a widening of ``exile_zone``, because that one
    #: says which pile a *chosen* object comes out of and every reader of it
    #: enumerates candidates — a library has none to enumerate.
    #:
    #: CR 118.3 makes it unpayable with too few cards, which is what stops this
    #: being a cost that silently costs nothing on an empty library.
    #:
    #: After ``mana_from_attached`` for that field's stated reason: the six
    #: positional arguments ``parse_activated_ability_cost`` passes are at the
    #: front, so a field inserted among them silently rebinds one of them.
    exile_top_of_library: int = 0
    #: "**Put a card from your hand on top of your library**:" (Hidden Retreat).
    #: How many cards the payer moves from hand to the top of their library.
    #: Beside ``discard_cards`` rather than folded into it: a discard is
    #: CR 701.9's graveyard, and this card's payment stays in the library where
    #: it can be drawn again — the whole reason the ability is repeatable.
    hand_to_library_top: int = 0
    #: Wandering Mage: "{B}, **Put a -1/-1 counter on a creature you control**:
    #: …". Which permanent the ``put_counter`` above goes on, when the card
    #: names one instead of the source. ``None`` is the source — Mazemind Tome's
    #: reading and every printing before this one — never "any permanent", for
    #: ``sacrifice_filter``'s reason: an empty filter would let the payment land
    #: anywhere.
    #:
    #: Beside ``put_counter`` rather than folded into it because they answer
    #: different questions, and only this one can make the ability *unpayable*:
    #: CR 601.2h refuses an activation whose cost cannot be paid, and a payer
    #: with no creature has nowhere to put the counter. The cost that adds a
    #: marker to the source can never fail; this one can.
    #:
    #: After ``exile_top_of_library`` for that field's stated reason: the six
    #: positional arguments ``parse_activated_ability_cost`` passes are at the
    #: front, so a field inserted among them silently rebinds one of them.
    put_counter_filter: dict | None = None
    #: Viscerid Drone: "{T}, **Sacrifice a creature and a Swamp**: …". The
    #: *second* object a conjoined sacrifice names. Its own field rather than a
    #: list widening ``sacrifice_filter``, for that field's own stated reason
    #: one direction over: the two are different costs — two noun phrases, each
    #: paid by its own permanent — and every existing reader of
    #: ``sacrifice_filter`` asks it about one object. A list there would be
    #: handed to those readers as if it were a filter.
    #:
    #: Both must be payable or neither is paid (CR 601.2h), and the two
    #: permanents must be distinct: one creature Swamp would otherwise pay a
    #: cost the card prints as two cards.
    #:
    #: After ``put_counter_filter`` for that field's stated reason: the six
    #: positional arguments ``parse_activated_ability_cost`` passes are at the
    #: front, so a field inserted among them silently rebinds one of them.
    sacrifice_also_filter: dict | None = None
    #: Benthic Explorers: "{T}, **Untap a tapped land an opponent controls**:
    #: …". The printed noun phrase of a cost that *unt*aps, and the first cost
    #: in this dataclass paid with a permanent the payer does not control
    #: (CR 602.1a: a cost is any action). Its own field rather than a direction
    #: flag on ``tap_filter``: that one enumerates the payer's own untapped
    #: permanents and this one enumerates somebody else's tapped ones, so a
    #: shared field would be read by the wrong enumerator on whichever card was
    #: written second.
    #:
    #: ``None`` means "no such cost", never "any permanent", for
    #: ``sacrifice_filter``'s reason: an empty filter would let the charger
    #: untap anything at all, and an *un*payable cost read as payable is an
    #: ability activated for free.
    #:
    #: After ``sacrifice_also_filter`` for that field's stated reason: the six
    #: positional arguments ``parse_activated_ability_cost`` passes are at the
    #: front, so a field inserted among them silently rebinds one of them.
    untap_filter: dict | None = None
    #: Alms, Nature's Kiss: "{1}, **Exile the top card of your graveyard**: …";
    #: Necratog, Zombie Scavengers: "**Exile the top creature card of your
    #: graveyard**: …". Cards named by their **position** in an ordered zone
    #: (CR 404.1, CR 404.2) rather than chosen, which is what makes this a separate field
    #: from ``exile_filter`` beside it and not a value of ``exile_zone``: every
    #: reader of that pair enumerates candidates and lets the payer pick, and
    #: here there is exactly one answer and nothing to offer.
    #:
    #: It is also separate from ``exile_top_of_library`` — an ``int``, because
    #: that payment is unnarrowed and taken off the top blind. This one
    #: **scans** the pile for the printed characteristic, so it carries the
    #: whole payload ``grammar.graveyard_position_payload_for`` builds:
    #: ``count``, ``position``, ``owner`` and an optional ``filter``. A charger
    #: that read the library form's absent filter as "no narrowing" is one word
    #: away from reading this one's the same way, which would let a Necratog
    #: eat a land.
    #:
    #: CR 118.3 makes it unpayable when the scan finds fewer than ``count``
    #: cards, which is what stops it costing nothing on a pile with no creature
    #: card in it. ``None`` is the honest "no such cost".
    #:
    #: After ``untap_filter`` for that field's stated reason: the six positional
    #: arguments ``parse_activated_ability_cost`` passes are at the front, so a
    #: field inserted among them silently rebinds one of them.
    exile_graveyard_position: dict | None = None
    #: Betrothed of Fire: "**Sacrifice enchanted creature**: Creatures you
    #: control get +2/+0 until end of turn." The *host*, which neither
    #: ``sacrifice_self`` nor ``sacrifice_filter`` can say: the first is the
    #: Aura, and the second is a permanent the payer picks out of everything
    #: matching a noun phrase. Read as either, the printed cost is wrong in a
    #: direction — the Aura eats itself, or it eats any creature on the board
    #: while the enchanted one lives.
    #:
    #: :attr:`tap_attached`'s shape one payment over (CR 303.4m says
    #: "enchanted [object]" names whatever the permanent is attached to and
    #: CR 301.5f says the same of "equipped", so both words are read):
    #: nothing is chosen, there is no picker and no filter, and the attachment
    #: record is the whole answer. The two ways it can fail — no host, or a
    #: host that has left — refuse the activation with nothing paid
    #: (CR 602.2b) rather than charging the Aura instead.
    #:
    #: Last for ``exile_graveyard_position``'s stated reason: the six
    #: positional arguments ``parse_activated_ability_cost`` passes are at the
    #: front, so a field inserted among them silently rebinds one of them.
    sacrifice_attached: bool = False
    #: "{2}, {T}, **Choose flying, first strike, trample, or shadow**: …"
    #: (Phyrexian Splicer.) A clause in the activation cost that spends nothing
    #: and decides a word (CR 602.1a puts it in the cost, CR 601.2b announces
    #: it). The options are the printed ones, because a choice the sentence did
    #: not offer is not a choice.
    #:
    #: Empty for every other ability, so nothing that reads a cost changes: the
    #: activation path asks for a word only when there is a list to pick from.
    #:
    #: Last for ``sacrifice_attached``'s stated reason — the positional
    #: arguments ``parse_activated_ability_cost`` passes are at the front, so a
    #: field inserted among them silently rebinds one of them.
    chosen_keyword_options: tuple[str, ...] = ()
    #: Spike Rogue: "{2}, **Remove a +1/+1 counter from a creature you
    #: control**: …". Which permanent the ``remove_counter`` above comes off,
    #: when the card names one instead of the source. ``None`` is the source —
    #: Scavenging Ghoul's reading and every printing before this one — never
    #: "any permanent", for ``sacrifice_filter``'s reason: an empty filter would
    #: let the payment come off anything at all.
    #:
    #: The exact mirror of ``put_counter_filter``, and beside ``remove_counter``
    #: for that pair's reason: they answer different questions, and this one
    #: alone decides *which* permanents can pay — a payer whose only creature
    #: with a counter on it is an opponent's cannot pay at all (CR 601.2h).
    #:
    #: Last for ``chosen_keyword_options``' stated reason — the positional
    #: arguments ``parse_activated_ability_cost`` passes are at the front, so a
    #: field inserted among them silently rebinds one of them.
    remove_counter_filter: dict | None = None
    #: Millikin: "{T}, **Mill a card**: Add {C}." How many cards the payer puts
    #: from the top of their library into their graveyard (CR 701.17a) to pay.
    #: An ``int`` for ``exile_top_of_library``'s reason: CR 701.17b makes the
    #: cost unpayable from a library holding fewer cards, and that has to be
    #: counted before the ability is activated. Zero is "no such cost".
    #:
    #: Paid **last** (CR 601.2h pays a cost that moves objects from the library
    #: to a public zone after every other cost), and what it put in the
    #: graveyard is recorded as ``milled_for_cost`` for a sentence that names
    #: "the milled card" (Charmed Pendant).
    #:
    #: Last for ``remove_counter_filter``'s stated reason — the positional
    #: arguments ``parse_activated_ability_cost`` passes are at the front.
    mill_cards: int = 0
    #: Battlefield Scrounger: "**Put three cards from your graveyard on the
    #: bottom of your library**: …". How many cards the payer picks out of
    #: their own pile (named on ``cost_graveyard_indices``); zero is "no such
    #: cost". Not a value of ``exile_zone``: every reader of that field reads an
    #: *exile* (``exiled_for_cost``, the client's verb, CR 605.1a), and this
    #: moves cards **to a library**. CR 118.3 makes it unpayable from a pile
    #: holding fewer cards. Last for ``mill_cards``' stated reason.
    graveyard_to_library_bottom: int = 0
    #: "**{3}, {T} or {U}, {T}**: Return target creature to its owner's hand
    #: …" (Crystal Shard and the four other Mirrodin Shards). The *other*
    #: printed activation costs, each a symbol dict like :attr:`mana`, that the
    #: activator may pay **instead of** it — one ability with a choice of
    #: costs (the 2004-10-04 ruling: "You can pay either of the two costs (but
    #: not both at the same time) to activate the ability"), announced as the
    #: ability is activated (CR 602.2b through CR 601.2b) and charged by
    #: ``Game.activation_mana_charge`` for the one chosen
    #: (``engine/activation_cost_alternatives.py``).
    #:
    #: Only the mana differs: the reader admits an "or" whose halves print the
    #: same non-mana costs, which every field above already says once.
    #: Empty for every other ability. Separate from :attr:`alternative_mana`,
    #: which is a mana payment offered instead of a *life* payment ("Pay 2
    #: life or {2}") and is folded into the price beside :attr:`mana`; these
    #: replace :attr:`mana` whole. Last for ``mill_cards``' stated reason.
    mana_alternatives: tuple[dict[str, int], ...] = ()

    @property
    def is_loyalty(self) -> bool:
        """Whether this is a loyalty-ability cost (CR 606.2)."""
        return self.loyalty is not None or self.loyalty_x_sign is not None
