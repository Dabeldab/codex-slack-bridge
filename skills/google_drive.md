# Google Drive

<!-- AgentChat/coding_agent 2026-07-08T16:12:51Z -->
<!-- AgentChat/coding_agent 2026-07-10T17:30:00-04:00 -->

Use a connected Google Drive app/MCP tool or a registered typed broker operation
for Drive, Docs, Sheets, and Slides discovery or downloads. Local wrappers,
Google ADC, OAuth client files, and reauthentication commands are operator-only;
never inspect or invoke them from an agent process.

Rules:

- A verified request for a Drive write authorizes that exact workflow. Stay
  read-only when the request asks only to inspect, search, export, or summarize.
- Export files into the active agent sandbox or desktop handoff directory, not
  random repo folders.
- For Google Docs, use `--format txt`, `docx`, `pdf`, or `html`.
- For Google Sheets, use `--format xlsx`, `csv`, or `pdf`.
- For Google Slides, use `--format pptx`, `pdf`, or `txt`.
- For non-Google files, use `--format raw`.
- If no connected app or typed broker operation is available, report Google
  Drive as unavailable. Do not search for a credential or suggest a credential
  path. Reauthentication is an operator-only maintenance task.
