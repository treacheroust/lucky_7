#!/usr/bin/env python3

import argparse
import random


def roll_highest(extra_dice: int, bobbleheads: int) -> list[int]:
    """Return the highest roll for each bobblehead."""
    results = []

    for _ in range(bobbleheads):
        rolls = [random.randint(1, 6) for _ in range(extra_dice)]
        results.append(max(rolls))

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Roll several d6s, keep the highest, and repeat."
    )
    parser.add_argument("extra_dice", type=int, help="d6s rolled each time")
    parser.add_argument("bobbleheads", type=int, help="number of repetitions")
    args = parser.parse_args()

    if args.extra_dice < 1 or args.bobbleheads < 1:
        parser.error("extra_dice and bobbleheads must both be at least 1")

    results = roll_highest(args.extra_dice, args.bobbleheads)
    print(f"Kept rolls: {results} | Number of 6s: {results.count(6)}")
    print("Total:", sum(results))


if __name__ == "__main__":
    main()
