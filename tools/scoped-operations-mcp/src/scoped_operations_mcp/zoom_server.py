from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .zoom_client import ScopedZoomClient


ALLOWED_LANES = frozenset(
    {
        "direct_codex",
        "billing_agent",
        "coding_agent",
        "tickets_agent",
        "claude_agent",
    }
)
OVERVIEW_MAINTAINERS = frozenset({"direct_codex", "coding_agent", "claude_agent"})
SUPPORT_METRICS_LANES = frozenset(ALLOWED_LANES)
READ = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
GUARDED_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)


def build_mcp(lane: str, client: ScopedZoomClient) -> FastMCP:
    clean_lane = str(lane or "").strip()
    if clean_lane not in ALLOWED_LANES:
        raise RuntimeError("Zoom scoped MCP requires a fixed operational agent lane")
    quality_lane = clean_lane == "claude_agent"
    instructions = (
        "This broker exposes typed Zoom operations without arbitrary API access. An explicit "
        "operator request may resolve one unique Zoom contact by exact email address or unique "
        "full name and send one journaled message with provider readback; custom email domains "
        "are allowed. The pre-existing configured:julio and configured:wiko automation remains "
        "separate and unchanged. Bounded Team Chat history and Zoom Docs archives are transient "
        "evidence. The Ghost Busters Chat Overview is one fixed public operational document: it "
        "must never include personal, customer, credential, one-on-one, HR, or performance data. "
        "Thor reads fixed-roster support quality evidence and may maintain only that fixed overview."
    )
    mcp = FastMCP(
        f"Zoom Scoped Operations ({clean_lane})",
        instructions=instructions,
        json_response=True,
        stateless_http=True,
    )

    @mcp.tool(annotations=READ)
    def zoom_capabilities() -> dict[str, Any]:
        """Report this lane's typed Zoom capabilities without exposing credentials."""
        base = client.quality_capabilities() if quality_lane else client.capabilities()
        return {
            **base,
            "lane": clean_lane,
            "explicitOperatorRecipientMessaging": True,
            "customEmailDomainsAllowed": True,
            "zoomChatHistoryRead": True,
            "zoomDocsArchiveRead": True,
            "ghostbustersOverviewRead": True,
            "ghostbustersOverviewUpdate": clean_lane in OVERVIEW_MAINTAINERS,
            "legacyJulioWikoFlowUnchanged": True,
        }

    @mcp.tool(annotations=READ)
    def zoom_operator_team_chat_recipient_resolve(
        exact_recipient: str,
    ) -> dict[str, Any]:
        """Resolve one unique Zoom contact by exact email address or unique full name."""
        return client.operator_team_chat_recipient_resolve(
            exact_recipient=exact_recipient,
        )

    @mcp.tool(annotations=GUARDED_WRITE)
    def zoom_operator_team_chat_send(
        exact_recipient: str,
        message: str,
        authorization_context: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Send one explicitly requested Zoom message and verify provider readback."""
        return client.operator_team_chat_send(
            exact_recipient=exact_recipient,
            message=message,
            authorization_context=authorization_context,
            idempotency_key=idempotency_key,
            sender_lane=clean_lane,
        )

    @mcp.tool(annotations=READ)
    def zoom_team_chat_channels(max_channels: int = 100) -> dict[str, Any]:
        """List bounded channels visible to the authenticated Zoom user."""
        return client.team_chat_channels(max_channels=max_channels)

    @mcp.tool(annotations=READ)
    def zoom_team_chat_history(
        channel_id: str,
        start_utc: str,
        end_utc: str,
        max_messages: int = 200,
    ) -> dict[str, Any]:
        """Read bounded history from one channel already visible to the Zoom user."""
        return client.team_chat_history(
            channel_id=channel_id,
            start_utc=start_utc,
            end_utc=end_utc,
            max_messages=max_messages,
        )

    @mcp.tool(annotations=READ)
    def zoom_docs_archives(
        start_utc: str,
        end_utc: str,
        product: str = "",
        max_records: int = 200,
    ) -> dict[str, Any]:
        """List bounded Zoom Docs, My Notes, and meeting-summary archives."""
        return client.docs_archives(
            start_utc=start_utc,
            end_utc=end_utc,
            product=product,
            max_records=max_records,
        )

    @mcp.tool(annotations=READ)
    def zoom_docs_archive_content(
        file_id: str,
        start_utc: str,
        end_utc: str,
        max_chars: int = 120_000,
    ) -> dict[str, Any]:
        """Read one archive that was validated inside the bounded archive inventory."""
        return client.docs_archive_content(
            file_id=file_id,
            start_utc=start_utc,
            end_utc=end_utc,
            max_chars=max_chars,
        )

    @mcp.tool(annotations=READ)
    def zoom_ghostbusters_overview_read() -> dict[str, Any]:
        """Read the fixed public Ghost Busters Chat Overview document."""
        return client.ghostbusters_overview_read()

    if clean_lane in OVERVIEW_MAINTAINERS:

        @mcp.tool(annotations=GUARDED_WRITE)
        def zoom_ghostbusters_overview_update(
            markdown: str,
            source_date: str,
            source_summary: str,
            authorization_context: str,
            idempotency_key: str,
        ) -> dict[str, Any]:
            """Replace only the fixed public overview after privacy and readback checks."""
            return client.ghostbusters_overview_update(
                markdown=markdown,
                source_date=source_date,
                source_summary=source_summary,
                authorization_context=authorization_context,
                idempotency_key=idempotency_key,
                sender_lane=clean_lane,
            )

    if clean_lane in SUPPORT_METRICS_LANES:

        @mcp.tool(annotations=READ)
        def zoom_support_queue_metrics(
            start_utc: str,
            end_utc: str,
            queue_hint: str = "All queues / fixed Total Calls report roster",
        ) -> dict[str, Any]:
            """Read unique calls, chat sessions, directions, and per-agent counts."""
            return client.weekly_support_metrics(
                start_utc=start_utc,
                end_utc=end_utc,
                queue_hint=queue_hint,
            )

    if quality_lane:

        @mcp.tool(annotations=READ)
        def zoom_health() -> dict[str, Any]:
            """Verify Thor's fixed-roster voice and performance reads."""
            return client.quality_health()

        @mcp.tool(annotations=READ)
        def zoom_quality_voice_engagements(
            start_utc: str,
            end_utc: str,
            max_engagements: int = 200,
        ) -> dict[str, Any]:
            """List bounded fixed-roster voice engagement evidence."""
            return client.quality_voice_engagements(
                start_utc=start_utc,
                end_utc=end_utc,
                max_engagements=max_engagements,
            )

        @mcp.tool(annotations=READ)
        def zoom_quality_agent_performance(
            start_utc: str,
            end_utc: str,
        ) -> dict[str, Any]:
            """Read bounded agent-performance evidence for the fixed support roster."""
            return client.quality_agent_performance(
                start_utc=start_utc,
                end_utc=end_utc,
            )

        @mcp.tool(annotations=READ)
        def zoom_quality_engagement_recordings(
            engagement_id: str,
            start_utc: str,
            end_utc: str,
        ) -> dict[str, Any]:
            """List sanitized recordings for one validated voice engagement."""
            return client.quality_engagement_recordings(
                engagement_id=engagement_id,
                start_utc=start_utc,
                end_utc=end_utc,
            )

        @mcp.tool(annotations=READ)
        def zoom_quality_transcript(
            engagement_id: str,
            recording_id: str,
            start_utc: str,
            end_utc: str,
            max_chars: int = 120_000,
        ) -> dict[str, Any]:
            """Read one transient transcript selected from validated Zoom metadata."""
            return client.quality_transcript(
                engagement_id=engagement_id,
                recording_id=recording_id,
                start_utc=start_utc,
                end_utc=end_utc,
                max_chars=max_chars,
            )

        return mcp

    @mcp.tool(annotations=READ)
    def zoom_health() -> dict[str, Any]:
        """Verify legacy Zoom auth and bounded metric readiness without sending."""
        return client.health()

    @mcp.tool(annotations=READ)
    def zoom_team_chat_recipient_resolve(exact_recipient: str) -> dict[str, Any]:
        """Resolve only configured:julio or configured:wiko for an automated flow."""
        return client.team_chat_recipient_resolve(exact_recipient=exact_recipient)

    @mcp.tool(annotations=GUARDED_WRITE)
    def zoom_team_chat_send(
        exact_recipient: str,
        message: str,
        authorization_context: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Run the unchanged configured Julio/Wiko automation send."""
        return client.team_chat_send(
            exact_recipient=exact_recipient,
            message=message,
            authorization_context=authorization_context,
            idempotency_key=idempotency_key,
            sender_lane=clean_lane,
        )

    if clean_lane in {"coding_agent", "tickets_agent"}:

        @mcp.tool(annotations=READ)
        def zoom_support_chat_snapshot(since_hours: int = 24) -> dict[str, Any]:
            """Read bounded ZVA and Contact Center support-chat state."""
            return client.support_chat_snapshot(since_hours=since_hours)

    if clean_lane == "tickets_agent":

        @mcp.tool(annotations=READ)
        def zoom_weekly_support_metrics(
            start_utc: str,
            end_utc: str,
            queue_hint: str = "All queues / fixed Total Calls report roster",
        ) -> dict[str, Any]:
            """Read fixed-roster calls and chats; never treat all-channel total as calls."""
            return client.weekly_support_metrics(
                start_utc=start_utc,
                end_utc=end_utc,
                queue_hint=queue_hint,
            )

        @mcp.tool(annotations=GUARDED_WRITE)
        def zoom_weekly_yaron_report_send(
            start_utc: str,
            end_utc: str,
            ticket_total: int,
            idempotency_key: str,
            queue_hint: str = "All queues / fixed Total Calls report roster",
        ) -> dict[str, Any]:
            """Send only total calls and total tickets to exact Yaron Bachar."""
            return client.weekly_yaron_report_send(
                start_utc=start_utc,
                end_utc=end_utc,
                ticket_total=ticket_total,
                idempotency_key=idempotency_key,
                queue_hint=queue_hint,
            )

    return mcp


def main() -> None:
    lane = os.getenv("SCOPED_AGENT_LANE", "").strip()
    build_mcp(lane, ScopedZoomClient()).run(transport="stdio")


if __name__ == "__main__":
    main()
