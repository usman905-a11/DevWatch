# Google Antigravity Agent Activity Streaming Investigation

**Investigation date:** 2026-11-12  
**Target:** Locally installed Google Antigravity IDE on Windows  
**Scope:** Observable behavior only. No authentication bypass, production-data modification, or proprietary implementation claim.

## Executive summary

The observable system is a **local brokered agent-state architecture using gRPC-Web server streaming over HTTP**:

```text
Agent execution services
        |
        v
Local Antigravity hub (agy.exe)
        |
        | gRPC-Web HTTP POST streams
        v
Electron renderer/frontend
        |
        v
Reactive conversation/activity state
        |
        v
Activity and conversation UI

Durable trajectory/state storage:
  SQLite conversation databases + protobuf-backed artifacts
```

The evidence does **not** establish the exact proprietary internal architecture of
the agent runtime, cloud services, broker implementation, or complete protobuf
definitions. It establishes the observable client, local hub, transport, state
model, persistence structures, and frontend stream-consumer behavior.

## Investigation methodology

1. Located the installed application, running processes, local hub, logs, and state directories.
2. Performed bounded static inspection of the installed desktop application.
3. Loaded the local hub in an isolated Chromium observation and captured HTTP traffic.
4. Inspected the served frontend bundle without executing modified code.
5. Inspected recent Antigravity logs.
6. Inspected a conversation SQLite database schema and bounded step metadata.
7. Attempted an owned Electron runtime observation. It failed because the target
   closed during provider hook setup; it was not retried.

## Target and runtime observations

### Confirmed

- Antigravity is an Electron-style desktop application.
- The main process and multiple renderer, GPU, crashpad, and utility processes
  were present.
- The installed executable was:

  `D:\softwares\Antigravity ide\Antigravity IDE\Antigravity IDE.exe`

- The local agent/language-service hub was:

  `C:\Users\HP\.gemini\bin\agy.exe --hub --hub-port=62028 ...`

- The hub discovery file reported:

  - HTTP port: `62028`
  - HTTPS/gRPC port: `62030`
  - language-server version: `2.31.0`

- The hub log reported:

  `Serving UI bundle from embedded assets`

- Relevant local state directories included:

  - `%USERPROFILE%\.gemini\antigravity\conversations`
  - `%USERPROFILE%\.gemini\antigravity\brain`
  - `%USERPROFILE%\.gemini\antigravity\daemon`
  - `%USERPROFILE%\.gemini\antigravity\log`
  - `%APPDATA%\Antigravity IDE`

### Evidence

- [Recent Antigravity hub log](C:/Users/HP/.gemini/antigravity/log/cli-20261112_211235.log)
- [Hub discovery file](C:/Users/HP/.gemini/antigravity/daemon/hub_62028.json)
- REA desktop inspection Evidence:
  `ev_c09e1b591a848d3df483a5c367bc7b86da63a61dbd5e1e2072eafc058ba7f944`

## Streaming mechanism

### Direct observations

The hub frontend made local HTTP `POST` requests to endpoints including:

```text
http://127.0.0.1:62028/exa.language_server_pb.LanguageServerService/JetboxSubscribeToState
http://127.0.0.1:62028/exa.language_server_pb.LanguageServerService/JetboxSubscribeToSummaries
```

Observed request/response characteristics:

- `content-type: application/grpc-web+json`
- `x-grpc-web` header
- CSRF header
- `transfer-encoding` on responses
- subscription requests remained unfinished when the observation ended

The captured browser observation saw no WebSocket connection and no SSE
`EventSource` request. This supports gRPC-Web over long-lived HTTP streaming.
The bounded observation does not prove that no other transport is used elsewhere.

### Transport conclusion

**High confidence:** Antigravity's observable activity/state subscription uses
gRPC-Web server-streaming semantics over HTTP.

It is not best described as a WebSocket event bus or ordinary polling API.

### Network evidence

- Browser capture Evidence:
  `ev_35da2baab6242f396a7f58a1c0c33a0772e0f1455b12ab57f406aa7e4ac439fd`
- Transaction view Evidence:
  `ev_eaa089fbb5d1c1589f80b23600907b70bb06e80b0ea7c1728c208fbfe12ffb89`

## Frontend stream consumer

The served `main.js` bundle contained the following implementation markers:

- `consumeAgentStateStream`
- `streamAgentStateUpdates`
- `createAgentStateSession`
- `createAgentStateProviderForConvo`
- `onSubscriberIdChanged`
- `onAuthError`
- `onNotFoundError`
- `onError`
- `disableRehydration`
- `trajectoryVerbosity`

The stream consumer:

1. Creates a request containing a conversation ID.
2. Receives state updates incrementally.
3. Applies each update to an accumulated state object.
4. Publishes state changes to listeners.
5. Tracks a subscriber ID.
6. Supports page requests for older step ranges.
7. Handles authentication, missing conversations, errors, and retries.

The bundle includes a one-second retry delay and a bounded repeated-error path.
This is frontend implementation evidence, not a guarantee of all backend retry
behavior.

## Activity and state taxonomy

The frontend bundle exposes these state/update families:

| Category | Observed representation | Streaming characteristic |
|---|---|---|
| Conversation identity | `conversationId`, trajectory identifiers | State metadata |
| Execution status | `IDLE`, `RUNNING`, `CANCELING` | Incremental state |
| Agent state | `AgentStateUpdate`, `CascadeState` | Incremental update |
| Trajectory | `TrajectoryUpdate` | Incremental update |
| Steps | `StepsUpdate`, `CortexStepUpdate` | Incremental/pageable |
| Turns | `TurnsUpdate`, turn headers/summaries | Incremental/state |
| Planner output | `CORTEX_STEP_TYPE_PLANNER_RESPONSE` | Step record |
| Generic activity | `CORTEX_STEP_TYPE_GENERIC` | Step record |
| User input | `CORTEX_STEP_TYPE_USER_INPUT` | Step record |
| System message | `CORTEX_STEP_TYPE_SYSTEM_MESSAGE` | Step record |
| Generator metadata | `GeneratorMetadatasUpdate` | Incremental metadata |
| Executor metadata | `ExecutorMetadatasUpdate` | Incremental metadata |
| Background work | `BackgroundTasksUpdate` | Incremental state |
| Pending messages | `PendingAgentMessagesUpdate` | Incremental state |
| Artifacts | `ArtifactSnapshotsUpdate` | Incremental state |
| File diffs | `TrajectoryFileDiffsUpdate` | Incremental state |
| Cost/credits | cost and consumed-credit schemas | Incremental metadata |
| Tool lifecycle hooks | `PRE_TOOL_USE`, `POST_TOOL_USE` | Lifecycle markers |
| Invocation lifecycle | `PRE_INVOCATION`, `POST_INVOCATION`, `STOP` | Lifecycle markers |

The exact numeric protobuf enum mapping for every step type was not recovered.
The names above are directly present in the shipped bundle or runtime logs.

## Tool activity evidence

The recent hub log recorded persisted trajectory statistics containing:

- `step_tool_count_manage_task`
- `step_tool_count_read_file`
- `step_tool_count_run_command`
- `step_tool_count_write_file`
- planner response step counts
- generic step counts
- user input step counts
- system message step counts
- render metadata sizes
- executor metadata sizes
- trajectory length and total step count

This confirms that tool activity is represented as structured trajectory/step
state rather than only as a display-only text log.

Example observed log statistics included:

```text
step_tool_count_manage_task: 4
step_tool_count_read_file: 4
step_tool_count_run_command: 14
step_tool_count_write_file: 1
step_type_count_CORTEX_STEP_TYPE_GENERIC: 23
step_type_count_CORTEX_STEP_TYPE_PLANNER_RESPONSE: 24
step_type_count_CORTEX_STEP_TYPE_SYSTEM_MESSAGE: 1
step_type_count_CORTEX_STEP_TYPE_USER_INPUT: 2
trajectory_verbosity: CLIENT_TRAJECTORY_VERBOSITY_PROD_UI
```

These are aggregate statistics for a stored trajectory, not a complete raw
event trace.

## Event lifecycle reconstruction

```text
1. User input or agent execution begins
          |
          v
2. Agent runtime creates/updates a conversation trajectory
          |
          v
3. Local hub exposes state through gRPC-Web stream
          |
          v
4. Renderer subscribes by conversation ID
          |
          v
5. Stream delivers AgentStateUpdate / trajectory / step updates
          |
          +--> status changes: RUNNING, CANCELING, IDLE
          +--> planner/generator metadata
          +--> generic/tool step data
          +--> executor metadata and render information
          +--> artifacts, diffs, background tasks
          |
          v
6. Frontend merges update into conversation state
          |
          v
7. React/reactive subscribers re-render activity UI
          |
          v
8. State and trajectory are persisted locally
          |
          v
9. Subscriber reconnects/rehydrates/page-loads as needed
```

## Persistence model

### Conversation trajectory database

[Observed conversation database](C:/Users/HP/.gemini/antigravity/conversations/4da90430-2a9b-4b43-bcf1-ea3b62e87443.db)

The `steps` table contains:

```text
idx
step_type
status
has_subtrajectory
metadata
error_details
permissions
task_details
render_info
step_payload
step_format
```

Additional tables store:

- trajectory metadata
- generator metadata
- executor metadata
- parent references
- trajectory metadata blobs
- battle-mode information

The inspected database contained 76 stored steps. Most had a generic step
type value, with planner/user/system values also present. The numeric values
were not mapped to every symbolic enum name.

### Conversation summary database

[Observed summary database](C:/Users/HP/.gemini/antigravity/conversation_summaries.db)

The summary store contains fields for:

- conversation ID
- title and preview
- step count
- last modified time
- status
- agent name
- parent conversation
- nesting depth
- killed/not-fully-idle flags
- last user input time and step index
- raw summary
- group ID

This supports persistence of conversation history and activity summaries beyond
the lifetime of one renderer subscription.

### Persistence conclusion

**High confidence:** activity state is durably represented as trajectories and
step records, not held only in transient UI memory.

Whether every in-progress stream chunk is synchronously persisted before being
sent to the renderer remains unknown.

## Concurrency and ordering

### Confirmed

- The frontend tracks state by conversation/trajectory identity.
- Subagent and nested conversation identifiers are present in the bundle.
- Step pages can be requested by bounds.
- Updates are applied incrementally to an accumulated state.
- Subscriber identity is tracked.

### Unknown

- Whether concurrent tool events receive a global sequence number.
- Whether ordering is guaranteed per conversation, per tool, or only by receipt.
- Whether parallel tools are multiplexed into one stream or represented as
  independent sub-trajectories.
- How out-of-order updates are reconciled.

The browser capture's event order is provider receipt order and must not be
treated as proof of backend causality.

## Frontend rendering lifecycle

### Evidence-backed reconstruction

```text
gRPC-Web response
      |
      v
protobuf/JSON decoding
      |
      v
AgentStateUpdate application
      |
      v
conversation-scoped provider/store
      |
      v
React subscribers
      |
      v
conversation activity, planner, tool, artifact, status, and summary views
```

The exact React component names and the final visual grouping rules were not
reliably extracted. The bundle does show conversation-scoped providers,
subagent state, activity-state accessors, trajectory state, and render-info
storage.

## Confirmed architecture versus inference

### Confirmed

- Electron desktop application.
- Local `agy.exe` hub.
- Local HTTP/gRPC-Web endpoints.
- Long-lived subscription requests.
- Agent state and summary subscriptions.
- Structured trajectory and step persistence.
- Conversation-scoped frontend state providers.
- Retry/error/auth/not-found handling in stream consumption.

### Strong inference

- The local hub acts as a broker/facade between the Electron renderer and
  agent execution services.
- The frontend renders from a normalized reactive state model rather than
  directly from raw transport frames.
- Activity history can be rehydrated from durable trajectory storage.

### Unknown

- Exact cloud-to-hub transport.
- Exact agent worker/service topology.
- Internal queue or broker implementation.
- Complete protobuf schemas and field names.
- Exact UI component mapping.
- Exact concurrent-tool ordering guarantees.
- Whether other activity transports exist in additional surfaces.

## Confidence ledger

| Finding | Confidence | Basis |
|---|---:|---|
| Local Antigravity hub exists | High | Process tree, hub log, discovery file |
| UI uses gRPC-Web | High | Captured headers, content types, endpoint paths |
| State subscriptions are long-lived streams | High | Unfinished subscription requests |
| Agent state is trajectory-oriented | High | Bundle schemas, logs, SQLite schema |
| Tool activity is structured | High | Tool counters, step payload columns, tool lifecycle enums |
| UI uses conversation-scoped reactive state | Medium-high | Bundle stream/provider implementation |
| Activity persists locally | High | SQLite/protobuf-backed stores |
| Exact backend topology | Low | Not directly observable |
| Exact event ordering under concurrency | Low | No controlled concurrent run captured |
| Exact visual component mapping | Medium-low | Static bundle markers only |

## Limitations

- The application is proprietary; source-level internal implementation was not
  available.
- Static directory inspection was partial.
- Browser network capture observed startup/subscription traffic rather than a
  newly triggered controlled agent prompt.
- Captured gRPC-Web payloads were mostly encoded or empty startup frames; exact
  activity payload fields were not decoded.
- The owned Electron runtime probe failed during startup because the target
  page closed while the provider hook was being installed. It returned a
  `hook_conflict`/closed-target diagnostic and was not retried.
- Local databases may be actively changing; inspection is a bounded offline
  snapshot and does not establish an atomic live snapshot.
- No production application data was modified.

## Recommended follow-up experiments

1. Capture a fresh agent run with an approved local runtime observation method.
2. Record a minimal prompt that produces one planner response, one tool call,
   one tool result, and one final response.
3. Capture the gRPC-Web response bytes and decode the protobuf/JSON envelope.
4. Compare stream frames with SQLite step insertion timing.
5. Trigger two independent tools and compare step IDs, timestamps, and stream
   order.
6. Disconnect/reconnect the renderer during execution and observe rehydration.
7. Restart the conversation UI and compare summary/trajectory reconstruction.
8. Map symbolic step enums and protobuf fields from an authorized descriptor
   set or additional shipped bundle evidence.

## Final conclusion

The strongest evidence-based description is:

> **Antigravity uses a local Electron frontend connected to an `agy.exe` hub
> through gRPC-Web server-streaming HTTP subscriptions. The hub exposes
> conversation-scoped agent state and summaries. The frontend incrementally
> merges trajectory, step, tool, metadata, artifact, and status updates into
> reactive state, while conversation trajectories and step payloads are
> persisted locally in SQLite/protobuf-backed storage.**

This describes the observable architecture. It is not a claim about the exact
proprietary internal implementation behind the hub or agent runtime.
