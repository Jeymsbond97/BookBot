"""Client-side fuzzy ranking helpers (rapidfuzz) on top of the DB search.

The Postgres ``search_books`` RPC already ranks results with full-text + trigram
similarity. Here we add a typo-tolerant score the bot uses to:

  * detect a near-exact title hit (so we can deliver it straight away), and
  * re-order a single page of results for a friendlier display order.

We never paginate by these scores — page boundaries always follow the stable DB
ordering — so re-ordering only ever shuffles items *within* the current page.
"""

from __future__ import annotations

from rapidfuzz import fuzz

from ..models import SearchResult

# Score (0–100) at/above which a result counts as "what the user typed".
EXACT_THRESHOLD = 90.0


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def score(query: str, result: SearchResult) -> float:
    """Best fuzzy match (0–100) of ``query`` against the result's title/author."""
    q = _norm(query)
    title = fuzz.token_set_ratio(q, _norm(result.title))
    author = fuzz.token_set_ratio(q, _norm(result.author)) if result.author else 0.0
    return max(title, author)


def best_exact(query: str, results: list[SearchResult]) -> SearchResult | None:
    """Return the single result that matches ``query`` closely, if unambiguous.

    Requires the top score to clear ``EXACT_THRESHOLD`` and to be clearly ahead
    of the runner-up, otherwise we'd rather show the list than guess.
    """
    if not results:
        return None
    ranked = sorted(results, key=lambda r: score(query, r), reverse=True)
    top = score(query, ranked[0])
    if top < EXACT_THRESHOLD:
        return None
    if len(ranked) > 1 and score(query, ranked[1]) >= top - 5:
        return None  # ambiguous — two near-equal candidates
    return ranked[0]


def rerank(query: str, results: list[SearchResult]) -> list[SearchResult]:
    """Stable-sort one page of results by descending fuzzy score."""
    return sorted(results, key=lambda r: score(query, r), reverse=True)
