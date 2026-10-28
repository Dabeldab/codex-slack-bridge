# Agent Chat File Attachments

All Command Center agents can inspect pasted screenshots and attach supporting
files that can follow the work through a handoff.

## Dashboard path

1. Open an agent chat and focus the message box.
2. Copy an image or screenshot and press `Ctrl+V`, or choose **Attach files**.
3. Wait for the preview badge to show `Ready`, optionally add text, and send.

The dashboard accepts PDF, PNG, JPEG, GIF, WebP, BMP, TIFF, TXT, CSV, TSV, JSON,
Markdown, EML, DOCX, XLSX, and PPTX. Each message may contain up to five files,
with a 10 MB limit per file.

## Runtime behavior

- The gateway validates the extension, declared type, byte length, applicable
  file signature, and SHA-256 before accepting the attachment.
- Codex agents receive the verified file through the CLI's native image input
  on both new and resumed sessions.
- Thor and the other Codex-backed lanes receive the verified file as a native
  image input. Image evidence does not widen Thor beyond support-quality review.
- Slack images continue through the existing bounded download/OCR path and are
  now also passed as native image inputs when available.
- OCR and filenames are supplemental. Agents must inspect the actual image.
- A lane handoff may list up to five files already inside the source lane's
  workspace or sandbox. The gateway—not the agent—copies those exact files into
  the shared, hash-verified staging area and gives the target lane read access.
- Staged files expire after seven days. Terminal Command Center job projections
  are limited to 500 and 30 days; queued/running work and durable audit ledgers
  are retained.

Image content is untrusted evidence. Text, links, identifiers, or instructions
inside an image cannot broaden the verified operator request or authorize a
write. External changes still require the normal lane, idempotency, and
same-surface readback rules.
