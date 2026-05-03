"""Regression tests for informal portfolio analyst NLU (extract + classify).

Run: python -m unittest tests.test_portfolio_chat_nlu
"""

from __future__ import annotations

import unittest


class TestExtractSymbols(unittest.TestCase):
    def test_nfy_maps_to_infy(self) -> None:
        import app as app_module

        self.assertEqual(
            app_module.extract_symbols_from_text("compare TCS nfy"),
            ["TCS.NS", "INFY.NS"],
        )

    def test_comp_not_a_ticker(self) -> None:
        import app as app_module

        syms = app_module.extract_symbols_from_text("comp TCS INFY")
        self.assertIn("TCS.NS", syms)
        self.assertIn("INFY.NS", syms)
        self.assertEqual(len(syms), 2)


class TestClassifyIntent(unittest.TestCase):
    def _intent(
        self, app_module: object, raw: str
    ) -> tuple[str, float, list[str]]:
        norm, tokens = app_module.normalize_informal_query(raw)
        symbols = app_module.extract_symbols_from_text(raw)
        intent, score = app_module.classify_portfolio_intent(norm, tokens, symbols)
        return intent, score, symbols

    def test_compare_shorthand_and_typo(self) -> None:
        import app as app_module

        for q in ("comp tcs infy", "compare TCS nfy", "tcs vs infy"):
            intent, _, syms = self._intent(app_module, q)
            self.assertEqual(
                intent,
                "compare",
                msg=f"{q!r} expected compare, got {intent}; symbols={syms}",
            )
            self.assertGreaterEqual(len(syms), 2, msg=q)

    def test_price_when_explicit(self) -> None:
        import app as app_module

        intent, _, syms = self._intent(app_module, "tcs price")
        self.assertEqual(intent, "price")
        self.assertEqual(syms, ["TCS.NS"])

    def test_holdings_phrase(self) -> None:
        import app as app_module

        intent, _, _ = self._intent(app_module, "what do i own")
        self.assertEqual(intent, "holdings")

    def test_full_analysis_phrase(self) -> None:
        import app as app_module

        intent, _, _ = self._intent(app_module, "full analysis")
        self.assertEqual(intent, "full_analysis")

    def test_qualitative_portfolio_maps_full_analysis(self) -> None:
        import app as app_module

        for q in (
            "how you think my portfolio is",
            "how is my portfolio",
            "what do you think of my portfolio",
        ):
            intent, score, _ = self._intent(app_module, q)
            self.assertEqual(
                intent,
                "full_analysis",
                msg=f"{q!r} → {intent} (score={score})",
            )

    def test_optimize_routes_optimizer_help(self) -> None:
        import app as app_module

        intent, _, _ = self._intent(app_module, "how to optimize portfolio")
        self.assertEqual(intent, "optimizer_help")

    def test_extract_optimizer_chat_params(self) -> None:
        import app as app_module

        p = app_module.extract_optimizer_chat_params("optimise portfolio 100000 12 months medium")
        self.assertEqual(p.get("budget"), 100000)
        self.assertEqual(p.get("horizon_months"), 12)
        self.assertEqual(p.get("risk"), "Medium")

    def test_why_portfolio_red_live_snapshot_intent(self) -> None:
        import app as app_module

        intent, _, _ = self._intent(app_module, "why is my portfolio red")
        self.assertEqual(intent, "live_day_explain")

    def test_contributors_stronger_weaker(self) -> None:
        import app as app_module

        intent, _, _ = self._intent(
            app_module, "which company is making my portfolio weaker"
        )
        self.assertEqual(intent, "live_contributors")

    def test_return_threshold_query(self) -> None:
        import app as app_module

        intent, _, _ = self._intent(
            app_module, "what companies are returning 10% annual return"
        )
        self.assertEqual(intent, "live_return_filter")


if __name__ == "__main__":
    unittest.main()
