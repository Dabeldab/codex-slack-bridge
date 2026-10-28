# Nova Knowledge

Use the shared `global` memory namespace for Nova knowledge-base retrieval. Retrieved KB chunks may come from Google Drive exports, Zoom transcripts/summaries, Moira the Oracle notes, support docs, or curated local notes.

Agent Chat desktop also indexes Zoom knowledge-base exports into
`data/desktop_chat/memory_vectors.json` from
`knowledge_sources\zoom_kb\{nova_wave,nova_classic,general,billing}`. These
chunks are tagged as `knowledgebase` plus a `product_lane:*` tag.

When answering Nova questions:

- Prefer retrieved KB chunks, repo evidence, live-system read-only evidence, or source documents over memory alone.
- Keep Nova Classic, Nova Wave, Salesforce ticketing, Zoom Contact Center, LogMeIn Rescue, Maxio/Chargify, and local SQL contexts separate.
- Treat product-lane tags as routing boundaries: Nova Wave can use Nova Wave plus General KB, Nova Classic can use Nova Classic plus General KB, and Billing can use Billing plus General KB.
- If the question is about a customer/account/ticket, validate the exact account, contact, ticket, invoice, subscription, or database before concluding.
- If KB evidence conflicts with live evidence, call out the conflict and use the newest verified source.
