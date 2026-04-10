"""Streamlit observability suite for auditing the Cerebro memory vault (read-only).

This module is intentionally UI-centric: all vault access uses
:class:`~cerebro.storage.MemoryBank` read APIs only—no commits, deletes, or
distillation triggers. New analytical views can register in ``VIEW_REGISTRY``.
"""

from __future__ import annotations

import asyncio
import html
from typing import Any, Callable, Dict, List

import pandas as pd
import streamlit as st

from cerebro.storage import MemoryBank

# -----------------------------------------------------------------------------
# Constants & registry (extensibility hook for future views, e.g. 3D vector map)
# -----------------------------------------------------------------------------

REDACTION_TOKENS: tuple[str, ...] = (
    "[EMAIL_REDACTED]",
    "[API_KEY_REDACTED]",
    "[IP_REDACTED]",
    "[CARD_REDACTED]",
)

VIEW_REGISTRY: Dict[str, Callable[..., None]] = {}


def register_view(name: str, renderer: Callable[..., None]) -> None:
    """Register a named dashboard section for dynamic menu expansion.

    Args:
        name: Stable key shown in navigation (e.g. ``"semantic_explorer"``).
        renderer: Zero-argument callable that renders Streamlit widgets.

    Returns:
        None.

    Raises:
        None.
    """
    VIEW_REGISTRY[name] = renderer


def apply_graphite_dark_theme() -> None:
    """Apply a Graphite-style dark palette via injected CSS.

    Streamlit does not expose a full theme API for all widgets; this sets base
    surfaces and typography to match infrastructure monitoring tools.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    st.markdown(
        """
        <style>
            .stApp {
                background-color: #1a1a1c;
                color: #d4d4d8;
            }
            [data-testid="stHeader"] {
                background-color: #252528;
                border-bottom: 1px solid #3f3f46;
            }
            [data-testid="stSidebar"] {
                background-color: #222226;
                border-right: 1px solid #3f3f46;
            }
            div[data-testid="stMetricValue"] {
                color: #f4f4f5;
            }
            .block-container {
                padding-top: 1.5rem;
            }
            h1, h2, h3 {
                color: #e4e4e7 !important;
                font-weight: 600;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _run_async(coro: Any) -> Any:
    """Run a coroutine inside Streamlit's synchronous script context.

    Args:
        coro: Awaiting object produced by an async ``MemoryBank`` method.

    Returns:
        Coroutine result.

    Raises:
        RuntimeError: If no event loop policy allows execution.
    """
    return asyncio.run(coro)


@st.cache_data(ttl=20, show_spinner=False)
def _load_vault_snapshot(db_path: str) -> List[Dict[str, Any]]:
    """Load and cache a read-only vault snapshot keyed by ``db_path``.

    Args:
        db_path: Persistent Chroma path passed to :class:`MemoryBank`.

    Returns:
        Serialized-friendly list of vault row dicts.

    Raises:
        RuntimeError: Propagated from the storage layer on read failure.
    """

    async def _snap() -> List[Dict[str, Any]]:
        bank = MemoryBank(db_path=db_path)
        return await bank.snapshot_vault_readonly()

    return _run_async(_snap())


def _records_by_category(
    rows: List[Dict[str, Any]], category: str
) -> List[Dict[str, Any]]:
    """Filter snapshot rows by metadata ``category``.

    Args:
        rows: Output of :meth:`MemoryBank.snapshot_vault_readonly`.
        category: Metadata lane (e.g. ``habit``, ``conversation``).

    Returns:
        Matching subset.

    Raises:
        None.
    """
    out: List[Dict[str, Any]] = []
    for r in rows:
        meta = r.get("metadata") or {}
        if meta.get("category") == category:
            out.append(r)
    return out


def _count_redactions(rows: List[Dict[str, Any]], category: str) -> int:
    """Count rows in ``category`` whose document contains any redaction token.

    Args:
        rows: Full vault snapshot.
        category: Metadata lane to scan (typically ``conversation``).

    Returns:
        Number of documents containing at least one known redaction marker.

    Raises:
        None.
    """
    n = 0
    for r in _records_by_category(rows, category):
        doc = str(r.get("document") or "")
        if any(tok in doc for tok in REDACTION_TOKENS):
            n += 1
    return n


def _distillation_ratio_metrics(
    habit_rows: List[Dict[str, Any]],
) -> tuple[int, int, float]:
    """Compute master-habit proxy counts for the metrics bar.

    Treats habit rows with ``strength >= 2`` as reinforced / consolidation-heavy
    ("master signal") versus the total habit row count.

    Args:
        habit_rows: Habit-lane records from the vault snapshot.

    Returns:
        Tuple of ``(master_like_count, total_habits, ratio)`` where ``ratio`` is
        in ``[0, 1]`` or ``0.0`` when there are no habits.

    Raises:
        None.
    """
    total = len(habit_rows)
    if total == 0:
        return 0, 0, 0.0
    masters = 0
    for r in habit_rows:
        meta = r.get("metadata") or {}
        try:
            s = int(float(meta.get("strength", 1)))
        except (TypeError, ValueError):
            s = 1
        if s >= 2:
            masters += 1
    return masters, total, masters / float(total)


def render_metrics_bar(rows: List[Dict[str, Any]]) -> None:
    """Render aggregate KPIs: volume, distillation proxy, redaction coverage.

    Args:
        rows: Full vault snapshot.

    Returns:
        None.

    Raises:
        None.
    """
    habits = _records_by_category(rows, "habit")
    masters, htot, ratio = _distillation_ratio_metrics(habits)
    redacted = _count_redactions(rows, "conversation")
    convo_n = len(_records_by_category(rows, "conversation"))

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Total memories", len(rows))
    with c2:
        st.metric(
            "Distillation ratio",
            f"{ratio:.0%}" if htot else "n/a",
            help="Reinforced habits (strength ≥ 2) / total habit rows — proxy for consolidation signal.",
        )
    with c3:
        st.metric(
            "Active redactions",
            redacted,
            help=f"Conversation documents containing any of: {', '.join(REDACTION_TOKENS)}",
        )
    st.caption(
        f"Habit rows: {htot} · Reinforced (≥2): {masters} · Conversation rows: {convo_n}"
    )


def render_habit_leaderboard(habit_rows: List[Dict[str, Any]]) -> None:
    """Render a searchable habit table sorted by strength with gradient styling.

    Args:
        habit_rows: Habit-lane records.

    Returns:
        None.

    Raises:
        None.
    """
    st.subheader("Habit leaderboard")
    if not habit_rows:
        st.info("No habit records in this vault.")
        return

    rows_out: List[Dict[str, Any]] = []
    for r in habit_rows:
        meta = r.get("metadata") or {}
        try:
            strength = int(float(meta.get("strength", 1)))
        except (TypeError, ValueError):
            strength = 1
        doc = str(r.get("document") or "")
        rows_out.append(
            {
                "id": r.get("id", ""),
                "strength": strength,
                "document": doc[:500] + ("…" if len(doc) > 500 else ""),
            }
        )
    df = pd.DataFrame(rows_out).sort_values("strength", ascending=False)
    q = st.text_input("Search habits", "", key="habit_search")
    if q.strip():
        mask = df["document"].str.lower().str.contains(q.strip().lower(), na=False)
        df = df[mask]

    styled = df.style.background_gradient(
        subset=["strength"],
        cmap="YlOrRd",
        low=0.15,
        high=0.85,
    ).format({"strength": "{:d}"})
    st.dataframe(styled, width="stretch", hide_index=True)


def _highlight_redactions_html(text: str) -> str:
    """Escape user content and wrap known redaction tokens in a red span.

    Args:
        text: Raw vault document (already scrubbed in production).

    Returns:
        HTML-safe string for ``st.markdown(..., unsafe_allow_html=True)``.

    Raises:
        None.
    """
    escaped = html.escape(text)
    for tok in REDACTION_TOKENS:
        etok = html.escape(tok)
        escaped = escaped.replace(
            etok,
            f'<span style="color:#ff5555;font-weight:600;">{etok}</span>',
        )
    return escaped


def render_security_audit(rows: List[Dict[str, Any]]) -> None:
    """Render conversation-lane documents with redaction token highlighting.

    Args:
        rows: Full vault snapshot.

    Returns:
        None.

    Raises:
        None.
    """
    st.subheader("Security audit — conversation lane")
    convos = _records_by_category(rows, "conversation")
    if not convos:
        st.info("No conversation records.")
        return

    for i, r in enumerate(convos):
        rid = r.get("id", i)
        doc = str(r.get("document") or "")
        with st.expander(f"Conversation `{rid}`", expanded=False):
            st.markdown(
                f'<div style="font-family:monospace;font-size:0.9rem;'
                f'background:#252528;padding:12px;border-radius:6px;'
                f'border:1px solid #3f3f46;">{_highlight_redactions_html(doc)}</div>',
                unsafe_allow_html=True,
            )


def render_semantic_explorer(db_path: str) -> None:
    """Run weighted semantic retrieval and show similarity vs. recency decomposition.

    Args:
        db_path: Chroma persistence path for :class:`MemoryBank`.

    Returns:
        None.

    Raises:
        None.
    """
    st.subheader("Semantic explorer")
    st.caption(
        "Uses the same Temporal Decay ranking as ``MemoryBank.retrieve_weighted``; "
        "similarity and recency weights are exposed via ``retrieve_weighted_with_scores``."
    )
    query = st.text_input("Search query", "", key="semantic_q")
    n = st.slider("Top K", 1, 20, 5)
    if not query.strip():
        st.caption("Enter a query to run semantic retrieval (read-only).")
        return

    async def _q() -> List[Dict[str, Any]]:
        bank = MemoryBank(db_path=db_path)
        return await bank.retrieve_weighted_with_scores(query.strip(), n_results=n)

    try:
        scored = _run_async(_q())
    except Exception as exc:
        st.error(f"Retrieval failed: {exc!r}")
        return

    if not scored:
        st.warning("No results.")
        return

    out = []
    for i, row in enumerate(scored, start=1):
        meta = row.get("metadata") or {}
        cat = meta.get("category", "—")
        doc = str(row.get("document") or "")
        out.append(
            {
                "rank": i,
                "category": cat,
                "similarity": row.get("similarity"),
                "recency_weight": row.get("recency_weight"),
                "final_score": row.get("final_score"),
                "distance": row.get("distance"),
                "preview": doc[:280] + ("…" if len(doc) > 280 else ""),
            }
        )
    st.dataframe(pd.DataFrame(out), width="stretch", hide_index=True)


def render_registered_views() -> None:
    """Render any optional views registered in ``VIEW_REGISTRY`` (extension hook).

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    if not VIEW_REGISTRY:
        return
    st.divider()
    st.subheader("Extension views")
    for name, fn in sorted(VIEW_REGISTRY.items()):
        with st.expander(name.replace("_", " ").title()):
            fn()


def main() -> None:
    """Streamlit entrypoint: layout shell and compose dashboard sections.

    Args:
        None.

    Returns:
        None.

    Raises:
        None.
    """
    st.set_page_config(
        page_title="Cerebro Observability",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_graphite_dark_theme()

    st.title("Cerebro observability suite")
    st.caption("Read-only vault inspection · no writes or deletes from this UI")

    with st.sidebar:
        st.header("Connection")
        db_path = st.text_input("Vault path", value="./cerebro_vault")
        refresh = st.button("Refresh snapshot")

    if refresh:
        _load_vault_snapshot.clear()

    try:
        rows = _load_vault_snapshot(db_path)
    except Exception as exc:
        st.error(f"Failed to load vault: {exc!r}")
        return

    habits = _records_by_category(rows, "habit")

    render_metrics_bar(rows)
    st.divider()
    render_habit_leaderboard(habits)
    st.divider()
    render_security_audit(rows)
    st.divider()
    render_semantic_explorer(db_path)
    render_registered_views()


if __name__ == "__main__":
    main()
