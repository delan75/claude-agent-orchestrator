/**
 * Claude Computer Use Agent — Frontend Application
 * Manages sessions, chat with SSE streaming, and desktop viewer.
 */

// ─── State ───
const API_BASE = window.location.origin;
let currentSessionId = null;
let eventSource = null;
let sessions = [];

// ─── Init ───
document.addEventListener('DOMContentLoaded', () => {
    loadApiKey();
    loadSessions();
    autoResizeTextarea();

    // Check VNC iframe status
    const vncFrame = document.getElementById('vnc-frame');
    vncFrame.addEventListener('load', () => {
        document.getElementById('vnc-status').textContent = 'Connected';
    });
    vncFrame.addEventListener('error', () => {
        document.getElementById('vnc-status').textContent = 'Disconnected';
    });
});

// ─── API Helpers ───
async function api(method, path, body = null) {
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json' },
    };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(`${API_BASE}${path}`, opts);
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'API error');
    }
    if (res.status === 204) return null;
    return res.json();
}

// ─── API Key ───
function saveApiKey(value) {
    localStorage.setItem('anthropic_api_key', value);
}

function loadApiKey() {
    const key = localStorage.getItem('anthropic_api_key') || '';
    document.getElementById('api-key-input').value = key;
}

function getApiKey() {
    return document.getElementById('api-key-input').value.trim();
}

// ─── Sessions ───
async function loadSessions() {
    try {
        sessions = await api('GET', '/api/sessions');
        renderSessionList();
    } catch (e) {
        console.error('Failed to load sessions:', e);
    }
}

function renderSessionList() {
    const list = document.getElementById('session-list');
    if (sessions.length === 0) {
        list.innerHTML = `<div style="padding: 20px; text-align: center; color: var(--text-muted); font-size: 13px;">
            No sessions yet.<br>Create one to get started.
        </div>`;
        return;
    }
    list.innerHTML = sessions.map(s => `
        <div class="session-item ${s.id === currentSessionId ? 'active' : ''}"
             onclick="selectSession('${s.id}')">
            <div class="session-icon ${s.status}"></div>
            <div class="session-info">
                <div class="session-name">${escapeHtml(s.name)}</div>
                <div class="session-meta">${s.message_count} msgs · ${formatTime(s.created_at)}</div>
            </div>
            <button class="delete-btn" onclick="event.stopPropagation(); deleteSession('${s.id}')" title="Delete">✕</button>
        </div>
    `).join('');
}

async function createSession() {
    const model = document.getElementById('model-select').value;
    try {
        const session = await api('POST', '/api/sessions', {
            name: `Session ${sessions.length + 1}`,
            model: model,
            provider: 'anthropic',
            system_prompt: '',
        });
        sessions.unshift(session);
        renderSessionList();
        selectSession(session.id);
    } catch (e) {
        alert('Failed to create session: ' + e.message);
    }
}

async function selectSession(sessionId) {
    // Close existing SSE connection
    closeEventStream();

    currentSessionId = sessionId;
    renderSessionList();

    try {
        const detail = await api('GET', `/api/sessions/${sessionId}`);
        const session = detail.session;

        // Update header
        document.getElementById('session-title').textContent = session.name;
        updateStatusBadge(session.status);

        // Render messages
        const chatMessages = document.getElementById('chat-messages');
        chatMessages.innerHTML = '';
        document.getElementById('empty-state')?.remove();

        for (const msg of detail.messages) {
            renderMessage(msg.role, msg.content);
        }
        scrollToBottom();

        // Enable input
        document.getElementById('send-btn').disabled = false;

        // Connect SSE
        connectEventStream(sessionId);

    } catch (e) {
        console.error('Failed to load session:', e);
    }
}

async function deleteSession(sessionId) {
    if (!confirm('Delete this session and all its messages?')) return;
    try {
        await api('DELETE', `/api/sessions/${sessionId}`);
        sessions = sessions.filter(s => s.id !== sessionId);
        if (currentSessionId === sessionId) {
            currentSessionId = null;
            document.getElementById('session-title').textContent = 'Select or create a session';
            document.getElementById('chat-messages').innerHTML = `
                <div class="empty-state" id="empty-state">
                    <div class="empty-icon">🖥️</div>
                    <h2>Claude Computer Use</h2>
                    <p>Create a new session and send a message to start the agent.</p>
                </div>`;
            document.getElementById('send-btn').disabled = true;
            closeEventStream();
        }
        renderSessionList();
    } catch (e) {
        alert('Failed to delete session: ' + e.message);
    }
}

// ─── Messaging ───
async function sendMessage() {
    const input = document.getElementById('chat-input');
    const content = input.value.trim();
    if (!content || !currentSessionId) return;

    const apiKey = getApiKey();
    if (!apiKey) {
        alert('Please enter your Anthropic API key in the sidebar.');
        document.getElementById('api-key-input').focus();
        return;
    }

    // Render user message immediately
    renderMessage('user', [{ type: 'text', text: content }]);
    scrollToBottom();
    input.value = '';
    input.style.height = '42px';

    // Show stop button
    document.getElementById('btn-stop').style.display = '';
    updateStatusBadge('running');

    // Connect SSE if not already connected
    connectEventStream(currentSessionId);

    try {
        const res = await fetch(`${API_BASE}/api/sessions/${currentSessionId}/message`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-API-Key': apiKey,
            },
            body: JSON.stringify({ content }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            renderError(err.detail || 'Failed to send message');
        }
    } catch (e) {
        renderError('Network error: ' + e.message);
    }
}

async function stopSession() {
    if (!currentSessionId) return;
    try {
        await api('POST', `/api/sessions/${currentSessionId}/stop`);
    } catch (e) {
        console.error('Failed to stop session:', e);
    }
}

// ─── SSE Event Stream ───
function connectEventStream(sessionId) {
    closeEventStream();

    eventSource = new EventSource(`${API_BASE}/api/sessions/${sessionId}/events`);

    eventSource.addEventListener('text', (e) => {
        try {
            const data = JSON.parse(e.data);
            appendAssistantText(data.text || '');
        } catch { }
    });

    eventSource.addEventListener('tool_use', (e) => {
        try {
            const data = JSON.parse(e.data);
            renderToolUse(data.name, data.input);
        } catch { }
    });

    eventSource.addEventListener('tool_result', (e) => {
        try {
            const data = JSON.parse(e.data);
            renderToolResult(data);
        } catch { }
    });

    eventSource.addEventListener('thinking', (e) => {
        try {
            const data = JSON.parse(e.data);
            renderThinking(data.thinking || '');
        } catch { }
    });

    eventSource.addEventListener('error', (e) => {
        try {
            const data = JSON.parse(e.data);
            renderError(data.message || 'Unknown error');
        } catch { }
    });

    eventSource.addEventListener('status', (e) => {
        try {
            const data = JSON.parse(e.data);
            updateStatusBadge(data.status);
            if (data.status !== 'running') {
                document.getElementById('btn-stop').style.display = 'none';
            }
        } catch { }
    });

    eventSource.addEventListener('done', () => {
        document.getElementById('btn-stop').style.display = 'none';
        // Reload session list to update message counts
        loadSessions();
    });

    eventSource.addEventListener('keepalive', () => { /* noop */ });

    eventSource.onerror = () => {
        // EventSource auto-reconnects, but log it
        console.warn('SSE connection error, reconnecting...');
    };
}

function closeEventStream() {
    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }
}

// ─── Message Rendering ───
let currentAssistantBubble = null;

function renderMessage(role, content) {
    currentAssistantBubble = null;
    const container = document.getElementById('chat-messages');

    if (typeof content === 'string') {
        const div = createMessageDiv(role, content);
        container.appendChild(div);
        return;
    }

    if (Array.isArray(content)) {
        for (const block of content) {
            if (typeof block === 'string') {
                const div = createMessageDiv(role, block);
                container.appendChild(div);
            } else if (block.type === 'text') {
                const div = createMessageDiv(role, block.text || '');
                container.appendChild(div);
            } else if (block.type === 'tool_use') {
                renderToolUse(block.name, block.input);
            } else if (block.type === 'tool_result') {
                // Tool results contain nested content
                if (Array.isArray(block.content)) {
                    for (const inner of block.content) {
                        if (inner.type === 'text') {
                            const div = createMessageDiv('tool', inner.text || '');
                            container.appendChild(div);
                        } else if (inner.type === 'image') {
                            renderScreenshot(inner.source?.data || '');
                        }
                    }
                } else if (typeof block.content === 'string') {
                    const div = createMessageDiv('tool', block.content);
                    container.appendChild(div);
                }
            }
        }
    }
}

function createMessageDiv(role, text) {
    const div = document.createElement('div');
    div.className = `message ${role}`;
    const label = role === 'user' ? 'You' : role === 'assistant' ? 'Claude' : 'Tool';
    div.innerHTML = `
        <div class="message-label">${label}</div>
        <div class="message-bubble">${escapeHtml(text)}</div>
    `;
    return div;
}

function appendAssistantText(text) {
    const container = document.getElementById('chat-messages');
    if (!currentAssistantBubble) {
        const div = document.createElement('div');
        div.className = 'message assistant';
        div.innerHTML = `
            <div class="message-label">Claude</div>
            <div class="message-bubble"></div>
        `;
        container.appendChild(div);
        currentAssistantBubble = div.querySelector('.message-bubble');
    }
    currentAssistantBubble.textContent += text;
    scrollToBottom();
}

function renderToolUse(name, input) {
    currentAssistantBubble = null;
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'message tool';
    const inputStr = typeof input === 'string' ? input : JSON.stringify(input, null, 2);
    div.innerHTML = `
        <div class="message-label">Tool Call</div>
        <div class="message-bubble">
            <div class="tool-name">🔧 ${escapeHtml(name)}</div>
            <div class="code-block"><code>${escapeHtml(inputStr)}</code></div>
        </div>
    `;
    container.appendChild(div);
    scrollToBottom();
}

function renderToolResult(data) {
    currentAssistantBubble = null;
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'message tool';

    let html = '<div class="message-label">Tool Result</div><div class="message-bubble">';

    if (data.output) {
        html += `<div class="code-block"><code>${escapeHtml(data.output)}</code></div>`;
    }
    if (data.error) {
        html += `<div class="error-text">${escapeHtml(data.error)}</div>`;
    }
    if (data.screenshot) {
        html += `<img class="screenshot-img" src="data:image/png;base64,${data.screenshot}" alt="Screenshot" onclick="openScreenshot(this.src)">`;
    }
    html += '</div>';
    div.innerHTML = html;
    container.appendChild(div);
    scrollToBottom();
}

function renderThinking(text) {
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'message assistant';
    div.innerHTML = `
        <div class="message-label">Thinking</div>
        <div class="thinking-block">${escapeHtml(text)}</div>
    `;
    container.appendChild(div);
    scrollToBottom();
}

function renderError(message) {
    currentAssistantBubble = null;
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'message assistant';
    div.innerHTML = `<div class="error-text">⚠️ ${escapeHtml(message)}</div>`;
    container.appendChild(div);
    scrollToBottom();
}

function renderScreenshot(base64Data) {
    const container = document.getElementById('chat-messages');
    const div = document.createElement('div');
    div.className = 'message tool';
    div.innerHTML = `
        <div class="message-bubble">
            <img class="screenshot-img" src="data:image/png;base64,${base64Data}" alt="Screenshot" onclick="openScreenshot(this.src)">
        </div>
    `;
    container.appendChild(div);
    scrollToBottom();
}

function openScreenshot(src) {
    window.open(src, '_blank');
}

// ─── Status ───
function updateStatusBadge(status) {
    const badge = document.getElementById('status-badge');
    badge.className = `status-badge ${status}`;
    const labels = {
        created: 'Ready',
        running: '● Running',
        idle: 'Idle',
        error: 'Error',
        stopped: 'Stopped',
    };
    badge.textContent = labels[status] || status;

    // Update sidebar session icon too
    const s = sessions.find(s => s.id === currentSessionId);
    if (s) {
        s.status = status;
        renderSessionList();
    }
}

// ─── Utilities ───
function scrollToBottom() {
    const el = document.getElementById('chat-messages');
    el.scrollTop = el.scrollHeight;
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function formatTime(isoStr) {
    const d = new Date(isoStr);
    const now = new Date();
    const diff = now - d;
    if (diff < 60000) return 'just now';
    if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
    if (diff < 86400000) return Math.floor(diff / 3600000) + 'h ago';
    return d.toLocaleDateString();
}

function handleInputKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
}

function autoResizeTextarea() {
    const textarea = document.getElementById('chat-input');
    textarea.addEventListener('input', () => {
        textarea.style.height = '42px';
        textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
    });
}
