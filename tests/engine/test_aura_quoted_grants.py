"""Every ability an Aura grants in quotes has to be one the compiler reads.

``engine/auras.py`` claims ``<attached> <noun> has "<anything>"`` as an
implemented continuous effect, and the claim asks nothing of the quote: the
words are folded onto the host by ``Permanent.effective_card`` and the host's
own compile is what turns them into an ability — or does not. So an Aura whose
quote the grammar refuses is reported **supported**, attaches, and grants a
sentence no step ever acts on. No instrument sees it: the Aura's program is
clean, ``--hollow-lines`` reads parts and the Aura has none, ``parse_coverage``
takes the claim at its word, and the unreadable line is on a *different
permanent* from the card that printed it.

Invasion's Essence Leak found it, by printing the same quote Urza's Saga's
Pendrell Flux had shipped with for nine sets — "At the beginning of your upkeep,
sacrifice this creature unless you pay its mana cost." — which refused in the
parser asking for a "reduced by" the card never prints. Pendrell Flux was an
Aura that did nothing at all.

This is the census that would have said so. It is validated backwards: on the
tree before that fix it named Pendrell Flux as well as Archery Training.

**The gate is closed now** (Invasion wave 2). ``auras.aura_effect_claim`` asks
``quoted_grant_readable`` before it claims a quoted grant, so an Aura whose
quote does not compile is *unsupported* rather than excused here, and the
``KNOWN_UNREAD`` ratchet this file carried for one card is gone with the card:
Archery Training's quote names the Aura from inside the host's ability, and
``granted_abilities.bind_granter`` now says which object that name means
(CR 201.5a). The census stays, because it asks the question from outside the
gate — a claim arriving by some other reader would be found here and nowhere
else — and the tests under it hold the gate itself.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.auras import (attach_aura, aura_granted_ability_lines,
                          aura_quoted_grants, quoted_grant_readable)
from engine.card_loader import load_cards, manifest_set_paths
from engine.granted_abilities import (bind_granter, granted_ability_supported,
                                      granter_phrase)
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card

#: How many quoted grants the pool held when this was written. A floor, because
#: a census that examined nothing passes for the same reason as one that found
#: nothing.
EXAMINED_FLOOR = 20


def _census() -> tuple[int, set[str]]:
    """``(grants examined, supported Auras with a quote the compiler refuses)``.

    Both manifest roles: a measured set is exactly where the next printing of
    an already-shipped quote arrives, which is how this one was found.
    """
    examined = 0
    unread: set[str] = set()
    seen: set[str] = set()
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            key = card.oracle_id or card.name
            if key in seen:
                continue
            seen.add(key)
            # The quotes **as printed**, not the list the host is handed: that
            # one holds only what compiles, so a census over it would always
            # be told nothing was unread.
            for quote in aura_quoted_grants(card.oracle_text or ""):
                examined += 1
                if not compile_card_oracle(card).supported:
                    continue
                if not quoted_grant_readable(quote, card.name):
                    unread.add(card.name)
    return examined, unread


def test_every_supported_auras_quoted_grant_compiles_on_its_host():
    examined, unread = _census()
    assert examined >= EXAMINED_FLOOR, (
        f"the census examined {examined} quoted grants; it found "
        f"{EXAMINED_FLOOR} when written, so the reader it is built on moved"
    )
    assert not unread, (
        "these Auras report supported and grant a quoted ability the compiler "
        f"cannot read, so the host gains nothing: {sorted(unread)}"
    )


def test_the_census_reads_a_quote_the_way_the_host_will():
    """The probe is the question the game asks — one printed sentence compiled
    on a card that says nothing else — so it must answer yes for a quote a host
    demonstrably runs and no for one it demonstrably cannot.
    """
    assert granted_ability_supported(
        "At the beginning of your upkeep, sacrifice this creature unless you "
        "pay its mana cost."
    )
    assert granted_ability_supported(
        "At the beginning of your upkeep, sacrifice this creature unless you "
        "pay {2}."
    )
    archery = (
        "{T}: This creature deals X damage to target attacking or blocking "
        "creature, where X is the number of arrow counters on Archery Training."
    )
    # A foreign proper noun on the host, exactly as before…
    assert not granted_ability_supported(archery)
    # …and an ability once the name is the object it stood for (CR 201.5a).
    bound = bind_granter(archery, "Archery Training", 7)
    assert granter_phrase(7) in bound and "Archery Training" not in bound
    assert granted_ability_supported(bound)
    assert quoted_grant_readable(archery, "Archery Training")
    # The relation is read whole: a different name is still nobody's.
    assert not quoted_grant_readable(archery, "Fire Whip")


_W2G5_UNREADABLE = (
    'Enchanted creature has "{T}: This creature deals X damage to any target, '
    'where X is the number of moons the wizard has counted."'
)


def _w2g5_aura(name: str, effect: str):
    return _mk_card(
        name=name, type_line="Enchantment - Aura",
        oracle_text=f"Enchant creature\n{effect}", colors=("W",),
    )


def test_w2g5_an_aura_whose_quote_does_not_compile_is_unsupported():
    """The gate, on invented cards so no name is in it.

    The same Aura with a quote the grammar reads is supported and with one it
    refuses is not — where the claim row used to admit both, asking nothing of
    what stood between the quotes.
    """
    readable = _w2g5_aura(
        "Probe Sling",
        'Enchanted creature has "{T}: This creature deals 1 damage to any target."',
    )
    unreadable = _w2g5_aura("Probe Almanac", _W2G5_UNREADABLE)

    assert compile_card_oracle(readable).supported
    program = compile_card_oracle(unreadable)
    assert not program.supported
    assert "moons the wizard" in (program.reason or "")


def test_w2g5_an_unreadable_quote_is_never_folded_onto_the_host():
    """Why the fold asks too, and not only the gate.

    A host's rules text is compiled as one card. Before this, one line the
    compiler refused made the *creature* unsupported and silenced every ability
    it printed: a Prodigal Sorcerer wearing the then-unread Archery Training
    could not ping. An unsupported Aura can still reach a battlefield (a test,
    the Debug Menu, a text change), so the host is protected where the text is
    assembled.
    """
    pinger = Permanent(card=_mk_card(
        name="Probe Pinger", type_line="Creature - Human Wizard",
        oracle_text="{T}: This creature deals 1 damage to any target.",
        colors=("U",), power=1, toughness=1,
    ))
    almanac = Permanent(card=_w2g5_aura("Probe Almanac", _W2G5_UNREADABLE))
    game = Game(players=[
        PlayerState(name="P1", battlefield=[pinger, almanac]), PlayerState(name="P2"),
    ])
    attach_aura(almanac, pinger)
    game._recompute_continuous_effects()

    assert aura_quoted_grants(almanac.card.oracle_text)
    assert aura_granted_ability_lines(almanac.card.oracle_text) == ()
    host = compile_card_oracle(pinger.effective_card)
    assert host.supported
    assert len(host.activated_abilities) == 1
