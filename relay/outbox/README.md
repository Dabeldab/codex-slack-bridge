# Relay outbox

GitHub Actions writes one `<task_id>.json` receipt here after a relay request
reaches a terminal Command Center state, times out, or fails before dispatch.

The outbox is the durable return channel for ChatGPT and human operators. It is
not an authority source: editing an outbox receipt never queues agent work.
