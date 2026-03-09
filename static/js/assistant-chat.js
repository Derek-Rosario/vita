const widget = document.getElementById("assistant-widget");
const launchButton = document.getElementById("assistant-widget-launch");
const minimizeButton = document.getElementById("assistant-widget-minimize");
const widgetPanel = document.getElementById("assistant-widget-panel");
const chatLog = document.getElementById("assistant-chat-log");
const sendForm = document.getElementById("assistant-send-form");
const messageInput = document.getElementById("assistant-message");

const OPEN_STATE_KEY = "assistant-widget-open";

function setWidgetOpen(open) {
  if (!widget || !launchButton) return;
  if (widgetPanel) {
    widgetPanel.hidden = !open;
    widgetPanel.style.display = open ? "flex" : "none";
    widgetPanel.style.flexDirection = "column";
  }
  widget.dataset.open = open ? "true" : "false";
  widget.classList.toggle("assistant-widget--open", open);
  launchButton.setAttribute("aria-expanded", open ? "true" : "false");
  launchButton.textContent = open ? "Hide assistant" : "Assistant";
  localStorage.setItem(OPEN_STATE_KEY, open ? "1" : "0");
  if (open && chatLog) {
    chatLog.scrollTop = chatLog.scrollHeight;
  }
}

if (widget && launchButton) {
  setWidgetOpen(localStorage.getItem(OPEN_STATE_KEY) === "1");
  launchButton.addEventListener("click", () =>
    setWidgetOpen(!widget.classList.contains("assistant-widget--open"))
  );
  if (minimizeButton) {
    minimizeButton.addEventListener("click", () => setWidgetOpen(false));
  }
}

if (chatLog) {
  new MutationObserver(() => {
    chatLog.scrollTop = chatLog.scrollHeight;
  }).observe(chatLog, { childList: true, subtree: true });
}

if (sendForm && messageInput) {
  sendForm.addEventListener("htmx:afterRequest", (event) => {
    if (event.detail?.successful) {
      sendForm.reset();
      messageInput.focus();
    }
  });

  messageInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.isComposing) {
      event.preventDefault();
      if (messageInput.value.trim()) {
        if (typeof sendForm.requestSubmit === "function") {
          sendForm.requestSubmit();
        } else {
          sendForm.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
        }
      }
    }
  });
}

if (chatLog && sendForm && messageInput) {
  chatLog.addEventListener("click", (event) => {
    const chip = event.target.closest("[data-assistant-followup]");
    if (!chip) return;
    event.preventDefault();
    const reply = (chip.dataset.followupReply || chip.textContent || "").trim();
    if (!reply) return;
    messageInput.value = reply;
    if (typeof sendForm.requestSubmit === "function") {
      sendForm.requestSubmit();
    } else {
      sendForm.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    }
  });
}
