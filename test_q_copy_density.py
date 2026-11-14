import random
import unittest

import q_copy_density as q


class DeckTests(unittest.TestCase):
    def test_configurations_are_99_and_replace_mountains(self):
        for additions in q.CONFIGURATIONS.values():
            deck = q.build_deck(additions)
            self.assertEqual(99, len(deck))
            self.assertEqual(87 - len(additions), deck.count(q.MOUNTAIN))
            self.assertIn("Sol Ring", deck)
            self.assertIn("Armillary Sphere", deck)
            self.assertTrue(q.UTILITY_LANDS <= set(deck))

    def test_repeatable_seed(self):
        a = q.simulate(50, 123, 10, "protect")
        b = q.simulate(50, 123, 10, "protect")
        self.assertEqual(a, b)


class MechanicsTests(unittest.TestCase):
    def game(self, library):
        game = q.Game.__new__(q.Game)
        game.rng = random.Random(1)
        game.max_turn = 10
        game.hand = []
        game.library = list(library)
        game.granted = set()
        game.hit_targets = set()
        game.lands = game.mountain_lands = game.rings = 0
        game.utility_lands = set()
        game.mirrorpool_ready = False
        game.q_cast = game.q_on_battlefield = game.spider = False
        game.command_zone_casts = 0
        game.first_q_copy = False
        game.q_triggers = 0
        game.electro_flashback = False
        game.premature = game.resource_blocked = False
        return game

    def test_q_reveal_exiles_lands_and_hits_engine(self):
        game = self.game([q.MOUNTAIN, q.MOUNTAIN, "Luck Bobblehead"])
        game.rng = type("NoShuffle", (), {"shuffle": lambda self, cards: None})()
        game.q_trigger()
        self.assertEqual({"Luck Bobblehead"}, game.hit_targets)
        self.assertEqual([], game.library)

    def test_q_exhausted_library(self):
        game = self.game([])
        game.q_trigger()
        self.assertEqual(set(), game.granted)

    def test_copy_costs_and_physical_only_flashback(self):
        self.assertEqual(2, q.COPY_COST["Twinflame"])
        self.assertEqual(2, q.COPY_COST["Molten Duplication"])
        self.assertEqual(3, q.COPY_COST["Cursed Mirror"])
        self.assertEqual(3, q.COPY_COST["Electroduplicate"])
        game = self.game(["Luck Bobblehead"])
        game.q_cast, game.lands = True, 3
        game.mountain_lands = 3
        game.hand = ["Electroduplicate"]
        game.play_turn(5)
        self.assertTrue(game.electro_flashback)
        game2 = self.game(["Luck Bobblehead"])
        game2.q_cast, game2.lands = True, 3
        game2.mountain_lands = 3
        game2.granted = {"Electroduplicate"}
        game2.hand = [q.MOUNTAIN]
        game2.play_turn(5)
        self.assertFalse(game2.electro_flashback)

    def test_spider_copies_only_first_exile_cast(self):
        game = self.game(["Luck Bobblehead", "Barbarian Class", "Armillary Sphere"])
        game.spider = True
        used = game._copy_q(True, False)
        self.assertTrue(used)
        self.assertEqual(2, game.q_triggers)
        game._copy_q(True, used)
        self.assertEqual(3, game.q_triggers)

    def test_drawn_target_is_premature_not_success(self):
        game = self.game(["Luck Bobblehead"])
        game.draw()
        self.assertTrue(game.premature)
        self.assertNotIn("Luck Bobblehead", game.hit_targets)

    def test_sol_ring_accelerates_q(self):
        game = self.game([q.MOUNTAIN])
        game.hand = [q.MOUNTAIN, "Sol Ring"]
        game.lands = 2
        game.mountain_lands = 2
        game.play_turn(3)
        self.assertTrue(game.q_cast)

    def test_q_requires_two_red_sources(self):
        game = self.game([q.MOUNTAIN])
        game.hand = [q.MOUNTAIN]
        game.lands = 3
        game.utility_lands = set(q.UTILITY_LANDS)
        game.play_turn(4)
        self.assertFalse(game.q_cast)

    def test_sphere_net_hand_gain(self):
        game = self.game([q.MOUNTAIN] * 4)
        game.q_cast, game.lands = True, 4
        game.mountain_lands = 4
        game.hand = ["Armillary Sphere"]
        game.play_turn(5)
        self.assertEqual(2, game.hand.count(q.MOUNTAIN))

    def test_deterministic_three_hit_fixture(self):
        game = self.game(list(q.TARGETS))
        for _ in range(3):
            game.q_trigger()
        self.assertEqual(q.TARGETS, game.hit_targets)

    def test_insufficient_fuel_fixture(self):
        game = self.game([q.MOUNTAIN] * 20)
        game.q_cast = True
        game.granted = {"Twinflame"}
        game.lands = 10
        game.mountain_lands = 10
        result = game.run()
        self.assertIsNone(result.assembly_turn)
        self.assertEqual("insufficient mana/fuel", result.failure)

    def test_sanctum_recasts_from_hand_without_tax(self):
        game = self.game(["Luck Bobblehead"])
        game.q_cast = game.q_on_battlefield = True
        game.command_zone_casts = 1
        game.utility_lands = {q.SANCTUM}
        game.lands = 7
        game.mountain_lands = 6
        game.play_turn(6)
        self.assertEqual(1, game.q_triggers)
        self.assertEqual(1, game.command_zone_casts)

    def test_high_market_recast_increases_commander_tax(self):
        game = self.game(["Luck Bobblehead"])
        game.q_cast = game.q_on_battlefield = True
        game.command_zone_casts = 1
        game.utility_lands = {q.HIGH_MARKET}
        game.lands = 7
        game.mountain_lands = 6
        game.play_turn(6)
        self.assertEqual(1, game.q_triggers)
        self.assertEqual(2, game.command_zone_casts)

    def test_urzas_cave_finds_sanctum_tapped(self):
        game = self.game([q.MOUNTAIN, q.SANCTUM, q.HIGH_MARKET])
        game.q_cast = game.q_on_battlefield = True
        game.utility_lands = {q.URZAS_CAVE}
        game.lands = 4
        game.mountain_lands = 3
        game.play_turn(5)
        self.assertNotIn(q.URZAS_CAVE, game.utility_lands)
        self.assertIn(q.SANCTUM, game.utility_lands)
        self.assertNotIn(q.SANCTUM, game.library)

    def test_mirrorpool_enters_tapped_then_copies_q(self):
        game = self.game([q.MOUNTAIN])
        game.q_cast = game.q_on_battlefield = True
        game.utility_lands = {q.MIRRORPOOL, q.HIGH_MARKET}
        game.mirrorpool_ready = False
        game.lands = 6
        game.mountain_lands = 4
        game.play_turn(7)
        self.assertEqual(1, game.q_triggers)
        self.assertNotIn(q.MIRRORPOOL, game.utility_lands)
        self.assertEqual(6, game.lands)  # played a Mountain, then sacrificed Mirrorpool

    def test_mirrorpool_needs_another_colorless_mana(self):
        game = self.game([q.MOUNTAIN])
        game.q_cast = game.q_on_battlefield = True
        game.utility_lands = {q.MIRRORPOOL}
        game.mirrorpool_ready = True
        game.lands = 6
        game.mountain_lands = 5
        game.play_turn(7)
        self.assertEqual(0, game.q_triggers)
        self.assertIn(q.MIRRORPOOL, game.utility_lands)

    def test_mirrorpool_copies_copy_sorcery_but_not_cursed_mirror(self):
        game = self.game([])
        game.utility_lands = {q.MIRRORPOOL, q.HIGH_MARKET}
        game.mirrorpool_ready = True
        game.lands = 7
        game.mountain_lands = 5
        mana = q.ManaPool(7, 5)
        paid, mirrored = game._pay_copy_spell("Twinflame", mana)
        self.assertTrue(paid)
        self.assertTrue(mirrored)
        self.assertNotIn(q.MIRRORPOOL, game.utility_lands)

        game2 = self.game([])
        game2.utility_lands = {q.MIRRORPOOL, q.HIGH_MARKET}
        game2.mirrorpool_ready = True
        game2.lands = 7
        game2.mountain_lands = 5
        paid, mirrored = game2._pay_copy_spell("Cursed Mirror", q.ManaPool(7, 5))
        self.assertTrue(paid)
        self.assertFalse(mirrored)


if __name__ == "__main__":
    unittest.main()
