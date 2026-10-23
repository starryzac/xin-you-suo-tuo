"""Filterable handover list."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from battery_handover_demo.database import SessionLocal  # noqa: E402
from battery_handover_demo.ui_helpers import (  # noqa: E402
    accessible_handovers,
    prepare_page,
    render_actor_selector,
    rows_to_dataframe,
)


prepare_page("Battery List")
st.title("Battery List")
st.caption("Filter handover records without collapsing the three independent status tracks.")

with SessionLocal() as session:
    actor = render_actor_selector(session)
    handovers = accessible_handovers(session, actor)

    filter_columns = st.columns(3)
    physical_filter = filter_columns[0].selectbox(
        "Physical status",
        ["ALL"] + sorted({item.physical_status.value for item in handovers}),
    )
    evidence_filter = filter_columns[1].selectbox(
        "Evidence status",
        ["ALL"] + sorted({item.evidence_status.value for item in handovers}),
    )
    completeness_filter = filter_columns[2].selectbox(
        "Completeness",
        ["ALL"] + sorted({item.completeness_status.value for item in handovers}),
    )

    filtered = [
        item
        for item in handovers
        if (physical_filter == "ALL" or item.physical_status.value == physical_filter)
        and (evidence_filter == "ALL" or item.evidence_status.value == evidence_filter)
        and (
            completeness_filter == "ALL"
            or item.completeness_status.value == completeness_filter
        )
    ]

    rows = rows_to_dataframe(
        {
            "Battery ID": item.battery.battery_id,
            "Current holder": item.battery.current_holder,
            "Sender": item.sender_org,
            "Receiver": item.receiver_org,
            "Physical status": item.physical_status,
            "Evidence status": item.evidence_status,
            "Completeness": item.completeness_status,
        }
        for item in filtered
    )
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
        selected_id = st.selectbox(
            "Select a record",
            options=[item.id for item in filtered],
            format_func=lambda handover_id: next(
                item.battery.battery_id for item in filtered if item.id == handover_id
            ),
        )
        if st.button("Open Battery Detail", type="primary"):
            st.session_state["selected_handover_id"] = selected_id
            st.switch_page("pages/2_Battery_Detail.py")
    else:
        st.info("No handover matches the selected filters.")
