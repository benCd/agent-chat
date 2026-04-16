/* agent-chat web GUI — client-side logic */
"use strict";

// ── State ───────────────────────────────────────────────────────────────────

const state = {
  currentChannel: "general",
  channels: [],
  agents: [],
  messages: [],       // all messages seen so far
  messageIds: new Set(),
  eventSource: null,
};

// ── DOM refs ────────────────────────────────────────────────────────────────

const $ = (sel) => document.querySelector(sel);
const channelList   = $("#channel-list");
const messagesDiv   = $("#messages");
const messageForm   = $("#message-form");
const messageInput  = $("#message-input");
const sendBtn       = $("#send-btn");
const senderInput   = $("#sender-id");
const isQuestionChk = $("#is-question");
const agentsList    = $("#agents-list");
const sessionBadge  = $("#session-name");
const currentChHdr  = $("#current-channel");
const statusDot     = $("#connection-status");
const agentModal    = $("#agent-modal");
const modalClose    = $("#modal-close");

// ── Boot ────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", async () => {
  await loadSession();
  await loadChannels();
  await loadMessages();
  connectSSE();
  bindEvents();
});

// ── API helpers ─────────────────────────────────────────────────────────────

async function api(path, opts = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", ...opts.headers },
    ...opts,
  });
  if (!res.ok) throw new Error(`API ${path}: ${res.status}`);
  return res.json();
}

// ── Data loading ────────────────────────────────────────────────────────────

async function loadSession() {
  const s = await api("/session");
  sessionBadge.textContent = s.name;
  document.title = `agent-chat · ${s.name}`;
}

async function loadChannels() {
  state.channels = await api("/channels");
  renderChannels();
}

async function loadMessages() {
  const msgs = await api("/messages/all");
  for (const m of msgs) {
    if (!state.messageIds.has(m.id)) {
      state.messages.push(m);
      state.messageIds.add(m.id);
    }
  }
  renderMessages();
  scrollToBottom();
}

// ── SSE ─────────────────────────────────────────────────────────────────────

function connectSSE() {
  if (state.eventSource) state.eventSource.close();

  const es = new EventSource("/api/events");
  state.eventSource = es;

  es.addEventListener("message", (e) => {
    const msg = JSON.parse(e.data);
    if (!state.messageIds.has(msg.id)) {
      state.messages.push(msg);
      state.messageIds.add(msg.id);
      renderMessages();
      scrollToBottom();

      // Auto-discover new channels
      if (!state.channels.find((c) => c.name === msg.channel)) {
        loadChannels();
      }
    }
  });

  es.addEventListener("agents", (e) => {
    state.agents = JSON.parse(e.data);
    renderAgents();
  });

  es.onopen = () => {
    statusDot.className = "status-dot connected";
    statusDot.title = "Connected";
  };

  es.onerror = () => {
    statusDot.className = "status-dot disconnected";
    statusDot.title = "Disconnected — reconnecting…";
  };
}

// ── Event binding ───────────────────────────────────────────────────────────

function bindEvents() {
  messageForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const content = messageInput.value.trim();
    if (!content) return;

    const sender = senderInput.value.trim() || "human";
    sendBtn.disabled = true;

    try {
      await api("/messages", {
        method: "POST",
        body: JSON.stringify({
          sender_id: sender,
          content,
          channel: state.currentChannel,
          sender_type: "human",
          is_question: isQuestionChk.checked,
        }),
      });
      messageInput.value = "";
      messageInput.style.height = "auto";
      isQuestionChk.checked = false;
    } catch (err) {
      console.error("Failed to send:", err);
    } finally {
      sendBtn.disabled = false;
      messageInput.focus();
    }
  });

  // Auto-resize textarea
  messageInput.addEventListener("input", () => {
    messageInput.style.height = "auto";
    messageInput.style.height = Math.min(messageInput.scrollHeight, 200) + "px";
  });

  // Send on Enter (Shift+Enter for newline)
  messageInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      messageForm.dispatchEvent(new Event("submit"));
    }
  });

  modalClose.addEventListener("click", () => agentModal.close());
  agentModal.addEventListener("click", (e) => {
    if (e.target === agentModal) agentModal.close();
  });
}

// ── Rendering ───────────────────────────────────────────────────────────────

function renderChannels() {
  channelList.innerHTML = "";
  for (const ch of state.channels) {
    const li = document.createElement("li");
    li.textContent = ch.name;
    if (ch.name === state.currentChannel) li.classList.add("active");
    li.addEventListener("click", () => switchChannel(ch.name));
    channelList.appendChild(li);
  }
}

function switchChannel(name) {
  state.currentChannel = name;
  currentChHdr.textContent = `#${name}`;
  renderChannels();
  renderMessages();
  scrollToBottom();
}

function renderMessages() {
  const filtered = state.messages.filter(
    (m) => m.channel === state.currentChannel
  );

  messagesDiv.innerHTML = "";

  for (const msg of filtered) {
    const div = document.createElement("div");
    div.className = "message";
    div.dataset.id = msg.id;

    const header = document.createElement("div");
    header.className = "message-header";

    const sender = document.createElement("span");
    sender.className = `message-sender ${msg.sender_type}`;
    sender.textContent = msg.sender_id;
    header.appendChild(sender);

    const time = document.createElement("span");
    time.className = "message-time";
    time.textContent = formatTime(msg.timestamp);
    header.appendChild(time);

    if (msg.is_question) {
      const badge = document.createElement("span");
      badge.className = "message-badge question";
      badge.textContent = "question";
      header.appendChild(badge);
    }

    if (msg.parent_id) {
      const badge = document.createElement("span");
      badge.className = "message-badge reply";
      badge.textContent = "reply";
      header.appendChild(badge);
    }

    div.appendChild(header);

    const content = document.createElement("div");
    content.className = "message-content";
    content.innerHTML = renderMarkdown(msg.content);
    div.appendChild(content);

    messagesDiv.appendChild(div);
  }
}

function renderAgents() {
  agentsList.innerHTML = "";

  if (state.agents.length === 0) {
    agentsList.innerHTML = '<div class="agent-meta" style="padding: 0 16px;">No agents connected</div>';
    return;
  }

  for (const agent of state.agents) {
    const card = document.createElement("div");
    card.className = "agent-card";

    const name = document.createElement("div");
    name.className = "agent-name";

    const dot = document.createElement("span");
    dot.className = `agent-status-dot ${agent.status}`;
    name.appendChild(dot);

    const nameText = document.createTextNode(agent.display_name);
    name.appendChild(nameText);
    card.appendChild(name);

    if (agent.current_task) {
      const meta = document.createElement("div");
      meta.className = "agent-meta";
      meta.textContent = agent.current_task;
      card.appendChild(meta);
    }

    const statusMeta = document.createElement("div");
    statusMeta.className = "agent-meta";
    statusMeta.textContent = `${agent.status}${agent.model ? " · " + agent.model : ""}`;
    card.appendChild(statusMeta);

    card.addEventListener("click", () => showAgentModal(agent));
    agentsList.appendChild(card);
  }
}

function showAgentModal(agent) {
  $("#modal-agent-name").textContent = agent.display_name;
  const dl = $("#modal-agent-details");
  dl.innerHTML = "";

  const fields = [
    ["ID", agent.id],
    ["Status", agent.status],
    ["Model", agent.model || "—"],
    ["Current Task", agent.current_task || "—"],
    ["Registered", formatTime(agent.registered_at)],
    ["Last Seen", formatTime(agent.last_seen)],
  ];

  for (const [label, value] of fields) {
    const dt = document.createElement("dt");
    dt.textContent = label;
    dl.appendChild(dt);
    const dd = document.createElement("dd");
    dd.textContent = value;
    dl.appendChild(dd);
  }

  agentModal.showModal();
}

// ── Utilities ───────────────────────────────────────────────────────────────

function scrollToBottom() {
  requestAnimationFrame(() => {
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
  });
}

function formatTime(isoStr) {
  if (!isoStr) return "";
  const d = new Date(isoStr);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/**
 * Minimal markdown renderer — handles code blocks, inline code, bold, italic.
 * For a production app you'd use a library like marked.js.
 */
function renderMarkdown(text) {
  if (!text) return "";

  // Escape HTML
  let html = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // Fenced code blocks
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_m, _lang, code) => {
    return `<pre><code>${code.trim()}</code></pre>`;
  });

  // Inline code
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

  // Bold
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

  // Italic
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");

  return html;
}
