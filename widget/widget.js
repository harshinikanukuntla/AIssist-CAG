/**
 * AIssist-CAG embeddable chat widget.
 *
 * Framework-agnostic: a single <script> include works on any site
 * (static HTML, Next.js, WordPress, Squarespace embed blocks, etc.)
 * since it's a self-contained IIFE with no external dependencies and
 * injects its own styles — no separate CSS file to wire up.
 *
 * Usage:
 *   <script
 *     src="https://your-cdn-or-host/widget.js"
 *     data-backend-url="https://api.yourportfolio.com"
 *     data-assistant-name="Portfolio Assistant"
 *     data-accent-color="#4f46e5"
 *   ></script>
 *
 * Or configure via a global before the script tag:
 *   <script>window.AISSIST_CONFIG = { backendUrl: "...", assistantName: "..." };</script>
 */
(function () {
  "use strict";

  var currentScript = document.currentScript;

  function readConfig() {
    var fromGlobal = window.AISSIST_CONFIG || {};
    var ds = (currentScript && currentScript.dataset) || {};
    return {
      backendUrl: (fromGlobal.backendUrl || ds.backendUrl || "http://localhost:8000").replace(/\/$/, ""),
      assistantName: fromGlobal.assistantName || ds.assistantName || "Portfolio Assistant",
      accentColor: fromGlobal.accentColor || ds.accentColor || "#4f46e5",
      greeting:
        fromGlobal.greeting ||
        ds.greeting ||
        "Hi! Ask me anything about my resume, skills, or projects.",
      position: fromGlobal.position || ds.position || "bottom-right",
    };
  }

  var config = readConfig();
  var SESSION_STORAGE_KEY = "aissist-cag-session-id";

  function getSessionId() {
    try {
      var existing = window.localStorage.getItem(SESSION_STORAGE_KEY);
      if (existing) return existing;
      var fresh = (crypto.randomUUID && crypto.randomUUID()) || String(Date.now()) + Math.random();
      window.localStorage.setItem(SESSION_STORAGE_KEY, fresh);
      return fresh;
    } catch (e) {
      // localStorage unavailable (e.g. private browsing) — fall back to an
      // in-memory session id that just won't persist across page loads.
      return String(Date.now()) + Math.random();
    }
  }

  var sessionId = getSessionId();

  // Generous margin over the backend's own default LLM_TIMEOUT_SECONDS
  // (20s), so a slow-but-legitimately-completing request isn't cut off
  // client-side before the backend's own timeout would have fired.
  var REQUEST_TIMEOUT_MS = 30000;

  var styleEl = document.createElement("style");
  styleEl.textContent =
    "" +
    ".aissist-bubble{position:fixed;" +
    (config.position === "bottom-left" ? "left:20px;" : "right:20px;") +
    "bottom:20px;width:56px;height:56px;border-radius:50%;background:" +
    config.accentColor +
    ";color:#fff;border:none;box-shadow:0 4px 14px rgba(0,0,0,.25);cursor:pointer;" +
    "font-size:24px;z-index:999999;display:flex;align-items:center;justify-content:center;}" +
    ".aissist-panel{position:fixed;" +
    (config.position === "bottom-left" ? "left:20px;" : "right:20px;") +
    "bottom:88px;width:340px;max-width:90vw;height:460px;max-height:70vh;background:#fff;" +
    "border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.25);display:none;flex-direction:column;" +
    "overflow:hidden;z-index:999999;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}" +
    ".aissist-panel.open{display:flex;}" +
    ".aissist-header{background:" +
    config.accentColor +
    ";color:#fff;padding:12px 16px;font-weight:600;display:flex;justify-content:space-between;align-items:center;}" +
    ".aissist-close{background:none;border:none;color:#fff;font-size:18px;cursor:pointer;line-height:1;}" +
    ".aissist-messages{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px;background:#f7f7f8;}" +
    ".aissist-msg{max-width:85%;padding:8px 12px;border-radius:10px;font-size:14px;line-height:1.4;white-space:pre-wrap;}" +
    ".aissist-msg.user{align-self:flex-end;background:" +
    config.accentColor +
    ";color:#fff;}" +
    ".aissist-msg.assistant{align-self:flex-start;background:#e9e9ec;color:#111;}" +
    ".aissist-msg.pending{opacity:.6;font-style:italic;}" +
    ".aissist-inputrow{display:flex;border-top:1px solid #e5e5e5;padding:8px;gap:6px;}" +
    ".aissist-input{flex:1;border:1px solid #ddd;border-radius:8px;padding:8px 10px;font-size:14px;resize:none;font-family:inherit;}" +
    ".aissist-send{background:" +
    config.accentColor +
    ";color:#fff;border:none;border-radius:8px;padding:0 14px;cursor:pointer;font-size:14px;}" +
    ".aissist-send:disabled{opacity:.5;cursor:default;}";
  document.head.appendChild(styleEl);

  var bubble = document.createElement("button");
  bubble.className = "aissist-bubble";
  bubble.setAttribute("aria-label", "Open chat with " + config.assistantName);
  bubble.textContent = "💬";

  var panel = document.createElement("div");
  panel.className = "aissist-panel";
  panel.innerHTML =
    '<div class="aissist-header"><span></span><button class="aissist-close" aria-label="Close">✕</button></div>' +
    '<div class="aissist-messages"></div>' +
    '<div class="aissist-inputrow">' +
    '<textarea class="aissist-input" rows="1" placeholder="Type a question..."></textarea>' +
    '<button class="aissist-send">Send</button>' +
    "</div>";
  panel.querySelector(".aissist-header span").textContent = config.assistantName;

  document.body.appendChild(bubble);
  document.body.appendChild(panel);

  var messagesEl = panel.querySelector(".aissist-messages");
  var inputEl = panel.querySelector(".aissist-input");
  var sendBtn = panel.querySelector(".aissist-send");
  var closeBtn = panel.querySelector(".aissist-close");

  var greeted = false;
  var isSending = false;

  function addMessage(role, text) {
    var el = document.createElement("div");
    el.className = "aissist-msg " + role;
    el.textContent = text;
    messagesEl.appendChild(el);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return el;
  }

  function togglePanel() {
    var isOpen = panel.classList.toggle("open");
    if (isOpen && !greeted) {
      addMessage("assistant", config.greeting);
      greeted = true;
    }
  }

  bubble.addEventListener("click", togglePanel);
  closeBtn.addEventListener("click", togglePanel);

  async function sendMessage() {
    // Guards against a fast double-Enter or Enter-then-click firing two
    // concurrent requests — disabling the button alone doesn't stop the
    // textarea's keydown handler from calling this again before the first
    // request's disabled state has visibly taken effect.
    if (isSending) return;

    var text = inputEl.value.trim();
    if (!text) return;

    isSending = true;
    inputEl.value = "";
    sendBtn.disabled = true;
    addMessage("user", text);
    var pending = addMessage("assistant", "Thinking...");
    pending.classList.add("pending");

    var controller = new AbortController();
    var timeoutId = setTimeout(function () {
      controller.abort();
    }, REQUEST_TIMEOUT_MS);

    try {
      var res = await fetch(config.backendUrl + "/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message: text }),
        signal: controller.signal,
      });
      var data = await res.json();
      pending.remove();
      if (!res.ok) {
        addMessage("assistant", data.detail || "Something went wrong. Please try again.");
      } else {
        addMessage("assistant", data.reply);
      }
    } catch (err) {
      pending.remove();
      addMessage(
        "assistant",
        err.name === "AbortError"
          ? "That's taking too long to respond. Please try again."
          : "I couldn't reach the server. Please try again shortly."
      );
    } finally {
      clearTimeout(timeoutId);
      isSending = false;
      sendBtn.disabled = false;
      inputEl.focus();
    }
  }

  sendBtn.addEventListener("click", sendMessage);
  inputEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
})();
