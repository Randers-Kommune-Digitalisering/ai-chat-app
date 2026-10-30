# Backend contract baseline

This records the observable Flask behavior before the backend is split into
modules. It is a compatibility baseline for structural refactors, not a new API
design or a promise to preserve every current behavior indefinitely. Unless a
change is explicitly scoped and reviewed, keep the routes, JSON field names,
HTTP status codes, SSE events, and portal integration compatible.

Run the regression baseline from the repository root with `pytest`. Endpoint
characterization lives in `flask/tests/*endpoint_test.py` and `conf_test.py`;
provider citations and stream interpretation are covered in
`flask/tests/azure_openai2_references_test.py` and
`flask/tests/azure_openai2_chat_test.py`. Tests mock Azure, database, and mail;
they are not live integration tests.

## Public HTTP surface

| Route | Input | Observable output |
| --- | --- | --- |
| `GET /api/config` | None | `200` JSON with `assistantName`, `assistantNameId`, `assistantType`, `isAgent`, `predefinedQuestions`, `description`, `showAssistantToggle`, `altToggleLabel`, `altAlertMsg`, `altAlertType`, `agentFileSizeLimit`, `conversationLoadCutoffDate`. |
| `POST /api/chat/messages` | JSON `messages` (full history of `{role, content, files?}`), optional `conversation_id`; optional `X-User-Email`. Files use `{name, content}` with base64 content. | `200` JSON `{success: true, response, references, conversation_id, title}` on model success. Empty history is `400`; model errors use `{success: false, message}` and the provider status when available (otherwise `500`), or `503` on an exception. |
| `POST /api/threads` | No body required. | `200` JSON `{success: true, message, thread_id}`; `503` JSON `{success: false, message}` on client exception. |
| `POST /api/threads/<thread_id>/messages` | JSON `message`, optional `files`, `use_alt`, `conversation_id`; optional `X-User-Email`. | `200` JSON `{success: true, response, references, conversation_id, title}` on model success. Missing message/invalid conversation ID is `400`; oversized file is `413`. Model errors use the provider status (otherwise `500`); exceptions return `503`. |
| `POST /api/threads/<thread_id>/messages/stream` | Same Agent message shape. | Successful preflight returns `200 text/event-stream` with `start`, zero or more `status` and `delta`, then `end` (or `error`). Preflight rejects invalid input as JSON (`400` for missing/too-long message or invalid ID; `413` for oversized file). |
| `POST /api/conversations/load` | `Authorization: Bearer <RS256 permit>`; body `permit` is also accepted for local debugging. | `200` JSON `{success: true, conversation}` with messages/attachments/references; invalid permit `401`, missing conversation `404`, DB disabled `503`, internal failure `500`, each as `{success: false, message}`. The request's `X-User-Email` is ignored here. |
| `POST /api/filter` | JSON `content`. | `200` JSON `{success: true, filtered_content}`; empty content `400`; filter exception `500`. |
| `POST /api/feedback` | JSON `feedback`, `response_index`, `chat_history`. | `200` JSON `{success: true, data}`; missing fields `400`; mail failure `500`. |
| `POST /api/feedback/like` | No required body fields. | `200` JSON `{success: true}` and increments the like counter. |
| `GET /healthz`, `GET /metrics` | None. | Health JSON and Prometheus text respectively; metric names and labels are described in the README. |

In both modes, a successful model answer can still return `success: true` when
database persistence is unavailable or a write fails. A newly created
conversation ID/title may then be absent. Existing endpoint tests capture this
behavior; changing it requires a separate product and API decision.

## Agent stream framing

Events are UTF-8 SSE blocks: `event: <name>\ndata: <JSON>\n\n`. The response
sets `Cache-Control: no-cache` and `X-Accel-Buffering: no`.

| Event | JSON fields |
| --- | --- |
| `start` | `thread_id`, `conversation_id` (may be `null`) |
| `status` | `status`, `message` |
| `delta` | `text` |
| `end` | `success`, `response`, `references`, `conversation_id`, `title` |
| `error` | `message`, `status` (e.g. `502` for an empty answer, `503` for a stream exception) |

After the SSE response begins, failures are `error` events on an HTTP `200`
stream, not new HTTP error responses. `references` is delivered in the final
`end` payload, not a separate client-facing references event. With DB enabled,
the final `conversation_id` can differ from the initial `start` value. A
successful response is formed by joining text deltas and stripping leading and
trailing whitespace. The endpoint and citation tests protect these shapes;
they do not prescribe the internals of the Foundry SDK.

## Behavioral boundaries for the refactor

- Chat sends full history, and uploaded documents are extracted into context.
  Agent sends one message to a Foundry conversation and can upload files; only
  Agent exposes the streaming route and alternate-assistant selection.
- The server redacts message text before passing it to the provider. Citation
  payloads must remain usable by the frontend; native and reconstructed AI
  Search references have dedicated provider tests.
- New conversations may receive an automatically generated title when DB
  persistence is available. The current fallback and timeout behavior has
  endpoint tests and should not change during file moves.
- When the DB is used, Agent attachments are metadata-only by default; Chat
  attachments may contain base64 content. Do not widen stored data as a side
  effect of reorganizing code.

## Existing behavior requiring a separate decision

These are observations, **not** recommended long-term contracts. Message-write
routes accept a caller-supplied `X-User-Email` and `conversation_id`, while the
repository's write lookup checks ID but not ownership. Permit verification is
currently confined to conversation loading. Identity/ownership must be fixed
with a deliberate authorization and migration plan, not implicitly preserved
or silently changed in a structural PR. Likewise, review retention of stored
attachments and feedback history, and the existing success-on-persistence-
failure policy, before changing those behaviors.