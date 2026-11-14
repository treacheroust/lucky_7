#!/usr/bin/env python3
"""Monte Carlo model for Q, Stacking the Deck copy-effect density.

The model intentionally represents only the named 99-card shell: three engine
cards, the configured Q-copy effects, Sol Ring, Armillary Sphere, three utility
lands, and Mountains.  Q begins in the command zone.  Sanctum of Eternity,
High Market, Urza's Cave, and Mirrorpool replace Mountains, as do candidate
copy effects, so the current list has 87 Mountains, four utility lands, and
eight nonlands.

Goldfish policy (identical for every configuration): draw on turn one; play a
useful utility land first; deploy Sol Ring, then Q as soon as possible; use
physical copy effects cheapest-first; make Spider-Verse once it can add a Q
trigger; use granted copy effects; make only enough granted Sol Rings to unlock
the next action; use Sanctum before High Market; tutor Sanctum before Market;
and crack Sphere when hand fuel is the limiting resource. Luck Bobblehead and
Barbarian Class are never cast. Mountains supply red, utility lands and Sol
Rings supply colorless, and High Market recasts include commander tax. Copied
Q tokens create their enter trigger before the legend rule removes them.
"""

from __future__ import annotations

import argparse
import math
import random
from collections import Counter
from dataclasses import dataclass

MOUNTAIN = "Mountain"
SANCTUM = "Sanctum of Eternity"
HIGH_MARKET = "High Market"
URZAS_CAVE = "Urza's Cave"
MIRRORPOOL = "Mirrorpool"
UTILITY_LANDS = frozenset({SANCTUM, HIGH_MARKET, URZAS_CAVE, MIRRORPOOL})
LANDS = UTILITY_LANDS | {MOUNTAIN}
TARGETS = frozenset({"Luck Bobblehead", "Spider-Verse", "Barbarian Class"})
BASE_COPIES = ("Twinflame", "Molten Duplication", "Cursed Mirror")
COPY_COST = {
    "Twinflame": 2,
    "Molten Duplication": 2,
    "Heat Shimmer": 3,
    "Electroduplicate": 3,
    "Cursed Mirror": 3,
}
CONFIGURATIONS = {
    "Current": (),
    "+ Heat Shimmer": ("Heat Shimmer",),
    "+ Electroduplicate": ("Electroduplicate",),
    "+ Both": ("Heat Shimmer", "Electroduplicate"),
}


def build_deck(additions: tuple[str, ...] = ()) -> list[str]:
    nonlands = list(TARGETS) + list(BASE_COPIES) + ["Sol Ring", "Armillary Sphere"]
    nonlands.extend(additions)
    deck = nonlands + list(UTILITY_LANDS)
    deck += [MOUNTAIN] * (99 - len(deck))
    if len(deck) != 99:
        raise ValueError("every tested library must contain exactly 99 cards")
    return deck


def _bottom_priority(card: str) -> tuple[int, int]:
    """Lower values are bottomed first under the protect-engine policy."""
    if card in TARGETS:
        return (0, 0)
    if card == "Armillary Sphere":
        return (1, 0)
    if card in LANDS:
        return (2, 0)
    if card in COPY_COST:
        return (3, -COPY_COST[card])  # preserve the cheapest line
    if card == "Sol Ring":
        return (4, 0)
    return (2, 0)


def opening_hand(deck: list[str], rng: random.Random, policy: str) -> tuple[list[str], list[str]]:
    """Apply London mulligans: seven, free seven, six, then forced five."""
    attempts = (0,) if policy == "none" else (0, 0, 1, 2)
    for index, bottoms in enumerate(attempts):
        shuffled = deck.copy()
        rng.shuffle(shuffled)
        seven = shuffled[:7]
        forced = index == len(attempts) - 1
        if policy == "none" or not (TARGETS & set(seven)) or forced:
            chosen = sorted(range(7), key=lambda i: _bottom_priority(seven[i]))[:bottoms]
            bottom_set = set(chosen)
            hand = [card for i, card in enumerate(seven) if i not in bottom_set]
            library = shuffled[7:] + [seven[i] for i in chosen]
            return hand, library
    raise AssertionError("unreachable mulligan state")


@dataclass
class TrialResult:
    assembly_turn: int | None
    first_q_copy: bool
    failure: str | None


@dataclass
class ManaPool:
    total: int
    red: int

    def can_pay(self, cost: int, red_required: int = 0, colorless_required: int = 0) -> bool:
        return (
            self.total >= cost
            and self.red >= red_required
            and self.total - self.red >= colorless_required
        )

    def pay(self, cost: int, red_required: int = 0, colorless_required: int = 0) -> bool:
        if not self.can_pay(cost, red_required, colorless_required):
            return False
        generic = cost - red_required - colorless_required
        nonred = self.total - self.red - colorless_required
        red_for_generic = max(0, generic - nonred)
        self.red -= red_required + red_for_generic
        self.total -= cost
        return True


class Game:
    def __init__(self, deck: list[str], rng: random.Random, max_turn: int, mulligan: str):
        self.rng = rng
        self.max_turn = max_turn
        self.hand, self.library = opening_hand(deck, rng, mulligan)
        self.granted: set[str] = set()
        self.hit_targets: set[str] = set()
        self.lands = self.mountain_lands = self.rings = 0
        self.utility_lands: set[str] = set()
        self.mirrorpool_ready = False
        self.q_cast = self.q_on_battlefield = self.spider = False
        self.command_zone_casts = 0
        self.first_q_copy = False
        self.q_triggers = 0
        self.electro_flashback = False
        self.premature = any(card in TARGETS for card in self.hand)
        self.resource_blocked = False

    def draw(self) -> None:
        if not self.library:
            return
        card = self.library.pop(0)
        self.hand.append(card)
        if card in TARGETS:
            self.premature = True

    def q_trigger(self) -> None:
        self.q_triggers += 1
        if not self.library:
            return
        self.rng.shuffle(self.library)
        while self.library:
            card = self.library.pop(0)
            if card in LANDS:
                continue
            if self.q_triggers == 1:
                self.first_q_copy = card in COPY_COST
            self.granted.add(card)
            if card in TARGETS:
                self.hit_targets.add(card)
            return

    def _discard_fuel(self) -> bool:
        candidates = [i for i, c in enumerate(self.hand) if c not in TARGETS]
        if not candidates:
            return False
        # Spend redundant Mountains first and protect live named cards.
        index = min(candidates, key=lambda i: (self.hand[i] != MOUNTAIN, _bottom_priority(self.hand[i])))
        self.hand.pop(index)
        return True

    def _copy_q(self, from_exile: bool, spider_used: bool) -> bool:
        triggers = 1
        if from_exile and self.spider and not spider_used:
            triggers += 1
            spider_used = True
        for _ in range(triggers):
            self.q_trigger()
        return spider_used

    def _pay_copy_spell(self, card: str, mana: ManaPool, cost: int | None = None) -> tuple[bool, bool]:
        """Pay for a Q-copy spell, using Mirrorpool's spell mode when possible."""
        spell_cost = COPY_COST[card] if cost is None else cost
        can_mirror = (
            card != "Cursed Mirror"
            and MIRRORPOOL in self.utility_lands
            and self.mirrorpool_ready
            and mana.can_pay(spell_cost + 4, red_required=1, colorless_required=2)
        )
        if can_mirror:
            mana.pay(spell_cost + 4, red_required=1, colorless_required=2)
            self.utility_lands.remove(MIRRORPOOL)
            self.lands -= 1
            self.mirrorpool_ready = False
            return True, True
        return mana.pay(spell_cost, red_required=1), False

    def play_turn(self, turn: int) -> int | None:
        if MIRRORPOOL in self.utility_lands:
            self.mirrorpool_ready = True
        self.draw()
        land_order = (
            (MOUNTAIN, SANCTUM, URZAS_CAVE, HIGH_MARKET, MIRRORPOOL)
            if self.mountain_lands < 2
            else (SANCTUM, URZAS_CAVE, HIGH_MARKET, MIRRORPOOL, MOUNTAIN)
        )
        land_to_play = next((land for land in land_order if land in self.hand), None)
        if land_to_play is not None:
            self.hand.remove(land_to_play)
            self.lands += 1
            if land_to_play == MOUNTAIN:
                self.mountain_lands += 1
            else:
                self.utility_lands.add(land_to_play)
                if land_to_play == MIRRORPOOL:
                    self.mirrorpool_ready = False
        tapped_mana = 1 if MIRRORPOOL in self.utility_lands and not self.mirrorpool_ready else 0
        mana = ManaPool(self.lands + 2 * self.rings - tapped_mana, self.mountain_lands)
        spider_used = False

        if "Sol Ring" in self.hand and mana.pay(1):
            self.hand.remove("Sol Ring")
            mana.total += 2  # immediately tap the new Ring
            self.rings += 1
        if not self.q_cast and mana.pay(4, 2):
            self.q_cast = True
            self.q_on_battlefield = True
            self.command_zone_casts = 1
            self.q_trigger()
        if self.hit_targets == TARGETS:
            return turn
        if not self.q_cast:
            self.resource_blocked = True
            return None

        # Physical effects before repeatable granted effects.
        physical = sorted(
            (c for c in self.hand if c in COPY_COST),
            key=lambda c: (COPY_COST[c], c == "Cursed Mirror", c),
        )
        for card in physical:
            cost = COPY_COST[card]
            paid, mirrored = self._pay_copy_spell(card, mana)
            if not paid:
                continue
            self.hand.remove(card)
            if card == "Electroduplicate":
                self.electro_flashback = True
            spider_used = self._copy_q(False, spider_used)
            if mirrored:
                self.q_trigger()
            if self.hit_targets == TARGETS:
                return turn

        # Establish the one useful Spider-Verse before casting from exile.
        if "Spider-Verse" in self.granted and not self.spider and mana.can_pay(5, 2) and self._discard_fuel():
            mana.pay(5, 2)
            self.spider = True

        # Repeat granted copy lines while mana and discard fuel permit.
        for card in sorted(self.granted & COPY_COST.keys(), key=lambda c: (COPY_COST[c], c)):
            cost = COPY_COST[card]
            while mana.can_pay(cost, 1):
                if not self._discard_fuel():
                    self.resource_blocked = True
                    break
                paid, mirrored = self._pay_copy_spell(card, mana)
                if not paid:
                    break
                spider_used = self._copy_q(True, spider_used)
                if mirrored:
                    self.q_trigger()
                if self.hit_targets == TARGETS:
                    return turn

        # Physical Electroduplicate alone has flashback.  Use its spell line
        # before Mirrorpool's more expensive creature-copy mode.
        if self.electro_flashback and mana.can_pay(4, 1):
            paid, mirrored = self._pay_copy_spell("Electroduplicate", mana, cost=4)
            if paid:
                self.electro_flashback = False
                spider_used = self._copy_q(False, spider_used)
                if mirrored:
                    self.q_trigger()
                if self.hit_targets == TARGETS:
                    return turn

        # Mirrorpool's creature mode costs {4}{C}, tapping and sacrificing the
        # land.  The combined six-mana check requires two colorless mana: one
        # pays {C}, while the other represents Mirrorpool tapping instead of
        # producing mana.  Its Q token supplies one enter trigger.
        if (
            MIRRORPOOL in self.utility_lands
            and self.mirrorpool_ready
            and self.q_on_battlefield
            and mana.pay(6, colorless_required=2)
        ):
            self.utility_lands.remove(MIRRORPOOL)
            self.lands -= 1
            self.mirrorpool_ready = False
            self.q_trigger()
            if self.hit_targets == TARGETS:
                return turn

        # Utility lands are repeatable Q-enter lines.  The mana checks include
        # the opportunity cost of tapping the land rather than producing mana.
        # Sanctum returns Q to hand (no tax); High Market sends it to the command
        # zone (two additional mana per prior command-zone cast).
        if SANCTUM in self.utility_lands and self.q_on_battlefield and mana.pay(7, 2):
            self.q_trigger()
            if self.hit_targets == TARGETS:
                return turn
        if HIGH_MARKET in self.utility_lands and self.q_on_battlefield:
            recast_cost = 4 + 2 * self.command_zone_casts
            if mana.pay(recast_cost + 1, 2):
                self.command_zone_casts += 1
                self.q_trigger()
                if self.hit_targets == TARGETS:
                    return turn

        # Cave finds Sanctum first, then Market.  Sacrificing Cave and putting
        # the target in tapped leaves the battlefield land count unchanged; the
        # replacement contributes mana and can activate beginning next turn.
        if URZAS_CAVE in self.utility_lands and mana.can_pay(4):
            target = next(
                (land for land in (SANCTUM, HIGH_MARKET, MIRRORPOOL) if land in self.library),
                None,
            )
            if target is not None:
                mana.pay(4)
                self.library.remove(target)
                self.utility_lands.remove(URZAS_CAVE)
                self.utility_lands.add(target)
                if target == MIRRORPOOL:
                    self.mirrorpool_ready = False

        # Create only enough Sol Rings to unlock the cheapest remaining action.
        action_costs = [COPY_COST[c] for c in self.granted if c in COPY_COST]
        if "Spider-Verse" in self.granted and not self.spider:
            action_costs.append(5)
        need = min(action_costs, default=0)
        while "Sol Ring" in self.granted and need and mana.total < need and mana.can_pay(1):
            if not self._discard_fuel():
                break
            mana.pay(1)
            mana.total += 2
            self.rings += 1

        # Spend the mana just unlocked by those rings during this main phase.
        if "Spider-Verse" in self.granted and not self.spider and mana.can_pay(5, 2) and self._discard_fuel():
            mana.pay(5, 2)
            self.spider = True
        for card in sorted(self.granted & COPY_COST.keys(), key=lambda c: (COPY_COST[c], c)):
            cost = COPY_COST[card]
            while mana.can_pay(cost, 1) and self._discard_fuel():
                paid, mirrored = self._pay_copy_spell(card, mana)
                if not paid:
                    break
                spider_used = self._copy_q(True, spider_used)
                if mirrored:
                    self.q_trigger()
                if self.hit_targets == TARGETS:
                    return turn

        # Sphere is a four-mana, one-card investment returning two Mountains.
        if "Armillary Sphere" in self.hand and mana.can_pay(4) and len(self.hand) <= 1:
            available = self.library.count(MOUNTAIN)
            self.hand.remove("Armillary Sphere")
            mana.pay(4)
            for _ in range(min(2, available)):
                self.library.remove(MOUNTAIN)
                self.hand.append(MOUNTAIN)
        return None

    def run(self) -> TrialResult:
        for turn in range(1, self.max_turn + 1):
            assembled = self.play_turn(turn)
            if assembled is not None:
                return TrialResult(assembled, self.first_q_copy, None)
        if self.premature:
            failure = "premature engine draw"
        elif not self.library:
            failure = "turn limit / library exhaustion"
        elif self.resource_blocked or not self.q_cast:
            failure = "insufficient mana/fuel"
        else:
            failure = "turn limit / library exhaustion"
        return TrialResult(None, self.first_q_copy, failure)


def wilson(successes: int, trials: int) -> tuple[float, float]:
    if trials == 0:
        return (0.0, 0.0)
    z = 1.959963984540054
    p = successes / trials
    d = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / d
    radius = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / d
    return centre - radius, centre + radius


def simulate(trials: int, seed: int, max_turn: int, mulligan: str) -> dict[str, list[TrialResult]]:
    results = {}
    for offset, (name, additions) in enumerate(CONFIGURATIONS.items()):
        # Independent deterministic stream prevents configuration order effects.
        rng = random.Random(seed + offset * 1_000_003)
        deck = build_deck(additions)
        results[name] = [Game(deck, rng, max_turn, mulligan).run() for _ in range(trials)]
    return results


def _pct(n: int, d: int) -> str:
    lo, hi = wilson(n, d)
    return f"{100*n/d:.3f}% [{100*lo:.3f}, {100*hi:.3f}]"


def report(results: dict[str, list[TrialResult]], max_turn: int) -> str:
    trials = len(next(iter(results.values())))
    turns = range(4, max_turn + 1)
    lines = ["## Q copy-effect density", "", f"Trials per configuration: {trials:,}", ""]
    lines += ["| Configuration | " + " | ".join(f"T{t}" for t in turns) + " |", "|---|" + "---:|" * len(list(turns))]
    turn10_intervals = {}
    for name, runs in results.items():
        cells = []
        for turn in turns:
            n = sum(r.assembly_turn is not None and r.assembly_turn <= turn for r in runs)
            cells.append(_pct(n, trials))
            if turn == max_turn:
                turn10_intervals[name] = (n / trials, wilson(n, trials))
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += ["", "| Configuration | Median successful turn | First Q hit: copy effect | Premature draw | Mana/fuel | Limit/exhaustion |", "|---|---:|---:|---:|---:|---:|"]
    for name, runs in results.items():
        successes = sorted(r.assembly_turn for r in runs if r.assembly_turn is not None)
        median = successes[(len(successes) - 1) // 2] if successes else "—"
        failures = Counter(r.failure for r in runs)
        lines.append(
            f"| {name} | {median} | {_pct(sum(r.first_q_copy for r in runs), trials)} | "
            f"{_pct(failures['premature engine draw'], trials)} | "
            f"{_pct(failures['insufficient mana/fuel'], trials)} | "
            f"{_pct(failures['turn limit / library exhaustion'], trials)} |"
        )
    ranked = sorted(turn10_intervals, key=lambda n: turn10_intervals[n][0], reverse=True)
    best, second = ranked[:2]
    if turn10_intervals[best][1][0] > turn10_intervals[second][1][1]:
        recommendation = f"**Recommendation:** {best}, with a statistically distinguishable turn-{max_turn} result."
    else:
        recommendation = f"**Recommendation:** inconclusive; the turn-{max_turn} 95% confidence intervals for {best} and {second} overlap."
    lines += ["", recommendation]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=250_000, help="trials per configuration (default: 250000)")
    parser.add_argument("--seed", type=int, default=7, help="base PRNG seed (default: 7)")
    parser.add_argument("--max-turn", type=int, default=10, help="last simulated turn (default: 10)")
    parser.add_argument("--mulligan", choices=("protect", "none"), default="protect")
    args = parser.parse_args()
    if args.trials < 1 or args.max_turn < 4:
        parser.error("--trials must be positive and --max-turn must be at least 4")
    return args


def main() -> None:
    args = parse_args()
    print(report(simulate(args.trials, args.seed, args.max_turn, args.mulligan), args.max_turn))


if __name__ == "__main__":
    main()
