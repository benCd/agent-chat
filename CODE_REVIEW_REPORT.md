# Code Review Report — `agent_chat`

**Date:** 2026-04-16  
**Repository:** `/home/ben/Projects/agent_chat`  
**Review method:** Multi-agent coordinated review (4 specialized reviewers communicating via agent-chat)  
**Test baseline:** 123 tests, all passing, 15.76s runtime

---

## Executive Summary

The `agent_chat` library is **well-structured for a v0.1.0** — the core architecture is sound, the three integration paths (SDK, MCP, CLI) provide good flexibility, and the SQLite-backed store handles concurrency correctly with WAL mode, busy timeouts, and application-level retries. Test coverage is solid for happy paths with excellent fixture isolation.

The review identified **39 findings** across 4 review areas. No critical/blocking issues were found. The most impactful issues are correctness bugs in the web API layer and missing error handling across interfaces.

### Findings Summary

| Severity | Count |
|----------|-------|
| Medium-High | 3 |
| Medium | 15 |
| Low-Medium | 5 |
| Low | 10 |
| Positive | 6 |

---

## High-Priority Findings (Fix First)

### 1. `ask_question` sender_type inconsistency across interfaces
**Severity: Medium-High** | **Affects: Web server** | **File:** `web/server.py:189`

The three interfaces disagree on `sender_type` for questions:
- **CLI** (`cli.py:237`): `SenderType.AGENT` ✅
- **MCP** (`mcp_server.py:139`): `SenderType.AGENT` ✅
- **Web** (`web/server.py:189`): `SenderType.HUMAN` ❌

The web endpoint also hardcodes `SenderType.HUMAN` for `answer_question` (`server.py:205`), preventing agents from answering via REST.

**Fix:** Accept `sender_type` in request bodies, or default to `AGENT` consistently.

---

### 2. `answer_question` hardcodes channel to "general"
**Severity: Medium-High** | **Affects: Web server** | **File:** `web/server.py:202`

```python
msg = store.post_message(
    sender_id=req.sender_id,
    content=req.answer,
    channel="general",  # ← hardcoded!
    ...
)
```

If a question was posted to `"design-review"`, the answer goes to `"general"` instead. The endpoint should look up the original question's channel.

---

### 3. `register_agent` UPSERT silently drops `status` and `current_task`
**Severity: Medium-High** | **Affects: Core store + all interfaces** | **File:** `store.py:173-182`

On re-registration (e.g., agent restart), the ON CONFLICT clause only updates `display_name`, `model`, and `last_seen` — it **does not update `status` or `current_task`**. The returned Agent object reflects the new values, but the database retains stale data.

**Impact (cross-referenced by all reviewers):**
- A crashed agent with `status=WORKING` can never reset to `IDLE` by re-registering
- The SDK stores the returned object as `self._agent`, creating a data inconsistency
- All three API interfaces (CLI, MCP, Web) silently fail to update these fields

**Fix:** Add `status` and `current_task` to the ON CONFLICT SET clause.

---

### 4. No security-related tests
**Severity: Medium-High** | **Affects: Test suite**

Only basic path traversal and length limit validation exist. Missing:
- SQL injection tests (`sender_id="a1'; DROP TABLE messages; --"`)
- XSS in message content (markdown rendered by frontend)
- Special characters in channel names, agent IDs
- Concurrent session creation race conditions

---

## Medium-Priority Findings

### 5. SSE stream blocks asyncio event loop
**File:** `web/server.py:233-248`

The SSE `event_generator()` calls synchronous SQLite methods inside an `async def` generator, blocking the event loop every second per connected client. Latency grows linearly with client count.

**Fix:** Use `asyncio.to_thread()` for store calls.

### 6. SSE error handling swallows all exceptions in infinite loop
**File:** `web/server.py:250-251`

All exceptions (including `DatabaseError`, `MemoryError`) are caught and logged, with no client notification, no failure counter, and no circuit breaking.

### 7. Web API returns 500 on malformed `since` parameter
**File:** `web/server.py:144, 153`

`datetime.fromisoformat(since)` raises `ValueError` on bad input, which FastAPI propagates as 500 instead of 400.

### 8. MCP server tools lack error handling
**File:** `mcp_server.py`

Only `update_status` and `update_task` handle errors gracefully. All other tools leak raw Python tracebacks to LLM clients on failure.

### 9. `get_messages` returns oldest N messages, not newest
**File:** `store.py:338`

`ORDER BY timestamp ASC LIMIT 100` returns the first 100 messages ever posted. For a chat app, this should return the most recent messages.

### 10. Polling thread swallows all exceptions silently
**File:** `sdk/client.py:158-166`

Callback exceptions are silently logged at WARNING. No backoff on repeated failures. No way to detect polling failure programmatically.

### 11. `start_polling()` race condition
**File:** `sdk/client.py:146-169`

Concurrent calls to `start_polling()` can both pass the `is_alive()` guard and spawn duplicate polling threads. Should be protected with a lock.

### 12. SSE `/api/events` endpoint has zero integration test coverage
The only SSE-related test verifies the `_sse_event` string formatter, never the actual streaming endpoint. This is the only real-time feature and is completely untested.

### 13. `pyproject.toml` — heavy required dependencies
**File:** `pyproject.toml:16-23`

`fastapi` and `uvicorn` are required even for SDK-only users. These should be in optional `[web]` extras. No upper bounds on any dependency version.

### 14. AgentClient constructor does I/O with no graceful failure
**File:** `sdk/client.py:52-61`

`__init__` calls `resolve_session()` and `register_agent()` directly. No way to construct in a disconnected state. No retry logic for transient errors.

### 15. Example MCP configs are all identical and inaccurate
**Files:** `examples/claude_desktop_config.json`, `cursor_mcp.json`, `mcp.json`

All three contain the same JSON. Each target platform uses a different config structure and path. Configs use bare `"python"` instead of venv paths and omit `PYTHONPATH`.

### 16. SDK missing `list_channels()` and `get_agent()` methods
API surface gap — MCP users have these capabilities but SDK users don't.

### 17. README documentation gaps
Missing: `setup_session.py` docs, `format_instructions()` docs, context manager usage example, troubleshooting section.

### 18. CLI error paths almost entirely untested
Only `test_invalid_status` tests an error case. Missing: non-existent agent, non-existent question, unregistered agent operations.

### 19. Web API missing 404/422 error path tests
404 responses from `update_status`/`update_task` with non-existent agents are never tested.

### 20. AgentClient image copy feature completely untested
`sdk/client.py:89-112` handles image attachments (file copying, unique naming, validation) but is never exercised in tests.

---

## Low-Priority Findings

### 21. Web `RegisterAgentRequest` missing `current_task` field
**File:** `web/server.py:41-43` — CLI and MCP support setting `current_task` at registration; web doesn't.

### 22. No CORS configuration on web server
External tools/dashboards and separate frontend development setups can't make API calls.

### 23. Dead code — `_SAFE_ID_RE` regex never used
**File:** `store.py:478` — Stricter allowlist regex defined but actual validation uses a weaker denylist approach.

### 24. `SessionManager` directly accesses `store._get_conn()` bypassing lock
**File:** `store.py:499, 515` — Abstraction leak and thread-safety bypass in `create_session`/`get_session`.

### 25. No `sender_id` foreign key on messages table
**File:** `store.py:45-58` — Messages can reference non-existent agents. Intentional for human senders but should be documented.

### 26. `list_sessions` N+1 query pattern
**File:** `store.py:527-536` — Opens a fresh DB connection per session directory. Low impact unless session count grows.

### 27. FK on `messages.channel` references `channels(name)` not `channels(id)`
**File:** `store.py:56` — Makes channel renames impossible and `channels.id` redundant.

### 28. TOCTOU race in `post_message` channel auto-create
**File:** `store.py:293-296` — Functionally safe due to `create_channel`'s internal check, but wastes lock cycles.

### 29. `content` validator inconsistency with `sender_id` validator
**File:** `models.py:58-75` — `sender_id` is stripped before storage; `content` is not. Likely intentional but could cause confusion.

### 30. `__main__.py` uses fragile `sys.argv` manipulation
**File:** `agent_chat/__main__.py:7-13` — `sys.argv.remove("--mcp")` could misbehave with unusual argument patterns.

### 31. `setup_session.py` hardcoded to Copilot CLI only
No `--target` flag for Claude Desktop or Cursor configurations. Linux/macOS-only venv path.

### 32. `__init__.py` doesn't re-export key public API
Users must use deep imports like `from agent_chat.sdk import AgentClient`.

### 33. CLI creates new `SessionManager` on every command invocation
**File:** `cli.py:24-27` — No resource reuse; session commands may leak resources.

### 34. Prompt templates' "Every 10 tool calls" heuristic is not configurable
**File:** `prompts/templates.py:11`

### 35. Flaky polling test coexists with proper event-based version
**File:** `test_core.py:237-257` — Sleep-based `test_polling` is redundant alongside `test_polling_with_event`.

### 36. MCP tests bypass transport layer
**File:** `test_mcp.py` — Tests call tool functions directly, never exercising decorators or transport.

### 37. `_retry_on_busy` retry exhaustion not tested
No test verifies behavior when all 5 retries are exhausted.

### 38. `image_paths` has no path traversal validation on model
**File:** `models.py:55` — SDK is safe via `Path.name` stripping, but relies on implicit behavior rather than explicit validation.

### 39. No cross-interface contract tests
No tests verify that CLI/MCP/Web produce consistent results for the same operations.

---

## What's Good ✅

The review also identified several strong patterns worth preserving:

1. **Concurrency handling** — WAL mode + `busy_timeout` PRAGMA + application-level `_retry_on_busy` decorator is a well-layered approach. The two-tier retry (SQLite-level + app-level) is intentional and documented.

2. **Parameterized SQL queries** — All SQL uses parameterized queries; no string interpolation. SQL injection risk is minimal.

3. **Test fixture isolation** — Each test gets a fresh temporary directory and SQLite database. CLI tests use `_base_dir_override`, MCP tests inject `_store` directly, web tests use `httpx.AsyncClient` with `ASGITransport`. No global state leakage.

4. **Meaningful test assertions** — Tests check specific values, not just "no exception." Concurrency tests verify exact message counts.

5. **Clean SDK API** — `AgentClient` provides an intuitive, focused API surface with context manager support.

6. **Architecture** — Clear separation between core (models + store), SDK, CLI, MCP, and web layers. Three integration paths serve different use cases well.

---

## Recommended Fix Priority

### Immediate (correctness bugs)
1. Fix `ask_question` sender_type inconsistency (#1)
2. Fix `answer_question` hardcoded channel (#2)
3. Fix `register_agent` UPSERT to update all fields (#3)
4. Fix `get_messages` to return newest messages (#9)

### Short-term (robustness)
5. Add error handling to MCP server tools (#8)
6. Handle malformed `since` parameter in web API (#7)
7. Fix SSE blocking with `asyncio.to_thread()` (#5)
8. Add lock to `start_polling()` (#11)
9. Add backoff/error callback to polling (#10)

### Medium-term (test coverage)
10. Add SSE integration tests (#12)
11. Add error path tests for all interfaces (#18, #19)
12. Add security smoke tests (#4)
13. Add cross-interface contract tests (#39)
14. Test image copy feature (#20)

### Long-term (DX improvements)
15. Move `fastapi`/`uvicorn` to optional deps (#13)
16. Add upper bounds to dependency versions (#13)
17. Fix example MCP configs (#15)
18. Add missing SDK methods (#16)
19. Improve README documentation (#17)
20. Re-export public API from `__init__.py` (#32)

---

*Report generated by a coordinated multi-agent review using 4 specialized agents (core-reviewer, api-reviewer, sdk-reviewer, test-reviewer) communicating via the agent-chat protocol.*
