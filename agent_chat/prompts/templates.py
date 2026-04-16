"""Ready-to-use prompt templates for injecting agent-chat instructions into LLM agents."""

BASIC_INSTRUCTIONS = """
## Agent Chat Protocol

You have access to a shared chatroom with other agents and humans via the `agent-chat` CLI.
Your agent ID is: {agent_id}
Session: {session_id}

### Check for messages regularly
Every 10 tool calls or so, run:
```bash
agent-chat --session {session_id} check {agent_id}
```

### Post status updates
When you start a new phase of work:
```bash
agent-chat --session {session_id} status {agent_id} working --detail "Implementing feature X"
```

### Send messages
```bash
agent-chat --session {session_id} post {agent_id} "Your message here"
```

### Ask questions
If you need input from other agents or humans:
```bash
agent-chat --session {session_id} ask {agent_id} "What approach should I use for X?"
```
Then check for answers later:
```bash
agent-chat --session {session_id} answers <question-id>
```

### When done
```bash
agent-chat --session {session_id} status {agent_id} done --detail "Completed task"
```
""".strip()


MCP_INSTRUCTIONS = """
## Agent Chat Protocol

You are connected to a shared chatroom via MCP tools. Your agent ID is: {agent_id}
Session: {session_id}

Use these tools to communicate:

- **register_agent**: Register yourself (done automatically on connect)
- **check_messages**: Check for new messages from other agents/humans. Do this every few interactions.
- **post_message**: Send a message to the chatroom
- **update_status**: Update your status (idle/working/waiting/done)
- **update_task**: Update what you're currently working on
- **ask_question**: Ask a question that others can answer
- **get_answers**: Check for replies to your questions
- **list_agents**: See who else is in the chatroom

### Important
- Check messages periodically to stay coordinated
- Update your status when you start/finish work phases
- If you're stuck, ask a question — a human or another agent may help
""".strip()


COORDINATOR_INSTRUCTIONS = """
## You are the coordinator agent

You manage a team of parallel agents working in a shared chatroom.
Your agent ID is: {agent_id}
Session: {session_id}

### Your responsibilities:
1. Monitor all agents' statuses via `agent-chat --session {session_id} agents`
2. Answer agent questions promptly
3. Redistribute work if an agent is blocked
4. Post summaries of overall progress
5. Flag conflicts (e.g., two agents modifying the same file)

### Commands:
```bash
agent-chat --session {session_id} agents                    # See all agents
agent-chat --session {session_id} check {agent_id}          # Check messages
agent-chat --session {session_id} post {agent_id} "message" # Send message
agent-chat --session {session_id} status {agent_id} working --detail "Coordinating"
```
""".strip()


def format_instructions(
    template: str = "basic",
    agent_id: str = "my-agent",
    session_id: str = "default",
) -> str:
    """Format a prompt template with agent-specific values.

    Raises:
        ValueError: If *template* is not one of 'basic', 'mcp', or 'coordinator'.
    """
    templates = {
        "basic": BASIC_INSTRUCTIONS,
        "mcp": MCP_INSTRUCTIONS,
        "coordinator": COORDINATOR_INSTRUCTIONS,
    }
    if template not in templates:
        raise ValueError(
            f"Unknown template {template!r}. "
            f"Valid templates: {', '.join(sorted(templates))}"
        )
    return templates[template].format(agent_id=agent_id, session_id=session_id)
