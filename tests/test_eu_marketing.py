import unittest

from agency_guardrails.rules.eu_marketing import find_prices, format_amount, parse_amount

from tests.helpers import run_rule, temp_tree

EUR = "\N{EURO SIGN}"


def ids(findings):
    return [f.rule_id for f in findings]


class ConditionalFreeTest(unittest.TestCase):
    RULE = "GR-EU-001"

    def test_flags_free_with_monthly_fee(self):
        text = "Get a free website. You only pay 15 euro per month for hosting.\n"
        found = run_rule(self.RULE, text)
        self.assertEqual(len(found), 1)
        self.assertIn("conditional free claim", found[0].message)
        self.assertEqual((found[0].line, found[0].column), (1, 7))

    def test_flags_free_next_to_a_price(self):
        found = run_rule(self.RULE, "<p>Free setup, then %s29.</p>" % EUR, path="p.html")
        self.assertEqual(ids(found), [self.RULE])

    def test_condition_in_other_paragraph_is_not_linked(self):
        text = "Our audit is free.\n\nSeparately, hosting plans start at 25 euro per month.\n"
        self.assertEqual(run_rule(self.RULE, text), [])

    def test_allowed_phrases_and_suffixes(self):
        text = (
            "Feel free to call. This is free software. Gluten-free bread on our plan for the week, "
            "subscription not needed.\n"
        )
        self.assertEqual(run_rule(self.RULE, text), [])

    def test_unconditional_is_opt_in(self):
        text = "A free checklist for bakers.\n"
        self.assertEqual(run_rule(self.RULE, text), [])
        found = run_rule(self.RULE, text, options={"flag_unconditional": True})
        self.assertEqual([f.severity for f in found], ["warn"])

    def test_code_and_urls_are_not_prose(self):
        text = "See https://example.org/free-plan-per-month and `free_tier = monthly`.\n"
        self.assertEqual(run_rule(self.RULE, text), [])


class PriceWithoutVatTest(unittest.TestCase):
    RULE = "GR-EU-002"

    def test_flags_bare_price_with_suggestion(self):
        found = run_rule(self.RULE, "Hosting costs %s15 per month.\n" % EUR)
        self.assertEqual(len(found), 1)
        self.assertIn("Price %s15 has no VAT-inclusive figure next to it; at 24%% VAT show %s18.60 incl. VAT" % (EUR, EUR), found[0].message)

    def test_vat_rate_is_configurable(self):
        found = run_rule(self.RULE, "Only 100 EUR.\n", options={"vat_rate": 0.2})
        self.assertIn("at 20% VAT show 120 EUR incl. VAT", found[0].message)

    def test_flags_net_only_price(self):
        found = run_rule(self.RULE, "From 25 euro excl. VAT.\n")
        self.assertIn("is marked as excluding VAT", found[0].message)

    def test_inclusive_figure_passes(self):
        text = "15 euro per month (18.60 euro incl. VAT), then 25 euro (31 euro incl. VAT).\n"
        self.assertEqual(run_rule(self.RULE, text), [])
        self.assertEqual(run_rule(self.RULE, "Price: %s49 VAT included.\n" % EUR), [])

    def test_mismatched_inclusive_figure(self):
        text = "%s100 excl. VAT (%s119 incl. VAT).\n" % (EUR, EUR)
        found = run_rule(self.RULE, text)
        self.assertEqual(len(found), 1)
        self.assertIn("does not match 24%% VAT (expected %s124 incl. VAT)" % EUR, found[0].message)

    def test_html_entity_price(self):
        found = run_rule(self.RULE, "<td>&euro;15</td>", path="t.html")
        self.assertEqual(ids(found), [self.RULE])

    def test_parse_amounts(self):
        self.assertEqual(parse_amount("15"), 15.0)
        self.assertEqual(parse_amount("15,50"), 15.5)
        self.assertEqual(parse_amount("1.200,50"), 1200.5)
        self.assertEqual(parse_amount("1,200.50"), 1200.5)
        self.assertEqual(parse_amount("1,200"), 1200.0)
        self.assertEqual(format_amount(18.6), "18.60")
        self.assertEqual(format_amount(31.0), "31")
        self.assertEqual([p[3] for p in find_prices("EUR 5 and 7 euros", ["EUR", "euros"])], [5.0, 7.0])


class UptimeGuaranteeTest(unittest.TestCase):
    RULE = "GR-EU-003"

    def test_flags_each_kind(self):
        text = (
            "99.9% uptime.\n\nResults guaranteed.\n\n24/7 support.\n\nRound-the-clock care.\n\n"
            "Service credits apply.\n\nZero downtime.\n"
        )
        found = run_rule(self.RULE, text)
        self.assertEqual([f.line for f in found], [1, 3, 5, 7, 9, 11])

    def test_negated_guarantee_passes(self):
        text = "We do not guarantee rankings. No agency can guarantee results.\n"
        self.assertEqual(run_rule(self.RULE, text), [])

    def test_honest_copy_passes(self):
        text = "We monitor your site and reply within one business day. Opening hours 9 to 5, 24 7 days.\n"
        self.assertEqual(run_rule(self.RULE, text), [])

    def test_allowed_phrase(self):
        text = "Read about the Guarantee Bakery case.\n"
        self.assertEqual(len(run_rule(self.RULE, text)), 1)
        self.assertEqual(run_rule(self.RULE, text, options={"allowed_phrases": ["Guarantee Bakery"]}), [])


class ConsentTest(unittest.TestCase):
    RULE = "GR-EU-004"
    OPTS = {"watch_names": ["Acme Bakery", "Northwind Fitness"]}

    def test_nothing_watched_nothing_flagged(self):
        self.assertEqual(run_rule(self.RULE, "Acme Bakery loves us.\n"), [])

    def test_flags_unapproved_names_and_logos(self):
        files = {"consent/approved.txt": "# name | date | evidence\nAcme Bakery | 2026-01-10 | signed email\n"}
        with temp_tree(files) as root:
            text = (
                "Acme Bakery and northwind  fitness trust us.\n"
                "<img src=\"/logos/northwind-fitness.svg\" alt=\"Client logo\">\n"
            )
            found = run_rule(self.RULE, text, path="page.md", options=self.OPTS, root=root)
            self.assertEqual([(f.line, f.match) for f in found], [(1, "Northwind Fitness"), (2, "Northwind Fitness")])
            self.assertIn("no consent record in consent/approved.txt", found[0].message)

    def test_missing_registry_means_nothing_approved(self):
        with temp_tree({}) as root:
            found = run_rule(self.RULE, "Acme Bakery\n", options=self.OPTS, root=root)
            self.assertEqual(len(found), 1)

    def test_word_boundaries(self):
        with temp_tree({}) as root:
            self.assertEqual(run_rule(self.RULE, "Acme Bakeryland\n", options=self.OPTS, root=root), [])


if __name__ == "__main__":
    unittest.main()
