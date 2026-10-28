# Knowledge Sources

Put exported knowledge-base files here before running the ingester.

Good inputs:

- Google Drive exports from Moira the Oracle or Nova knowledge-base docs.
- Zoom meeting transcripts, AI summaries, Zoom AI Studio knowledge-base exports,
  or docs.
- Markdown, text, CSV/TSV, JSON, HTML, DOCX, VTT, SRT, and optionally PDF files.

For Zoom knowledge-base exports used by Agent Chat ticket resolution, keep
sources separated by product lane:

```text
knowledge_sources/
  zoom_kb/
    nova_wave/
    nova_classic/
    general/
    billing/
```

Index these files into Agent Chat desktop vector memory with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\ingest-desktop-knowledge.ps1
```

The desktop ingester writes chunks into
`data/desktop_chat/memory_vectors.json` with `knowledgebase` and
`product_lane:nova_wave`, `product_lane:nova_classic`,
`product_lane:general`, or `product_lane:billing` tags. During chat, Agent Chat
uses the same vector retrieval path as normal desktop memory. Nova Wave tickets
retrieve Nova Wave plus General KB chunks, Nova Classic retrieves Nova Classic
plus General, and Billing retrieves Billing plus General.

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\ingest-knowledge.ps1
```

By default, chunks are stored in the shared `global` memory namespace with `nova`, `moira`, and `oracle` tags, so all agents can retrieve them.
