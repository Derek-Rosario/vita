const widget = document.getElementById("assistant-widget");
const launchButton = document.getElementById("assistant-widget-launch");
const minimizeButton = document.getElementById("assistant-widget-minimize");
const widgetPanel = document.getElementById("assistant-widget-panel");
const chatLog = document.getElementById("assistant-chat-log");
const sendForm = document.getElementById("assistant-send-form");
const messageInput = document.getElementById("assistant-message");
const OPEN_STATE_KEY = "assistant-widget-open";
const SCROLL_TOP_KEY = "assistant-widget-scroll-top";
const AUTO_SCROLL_BOTTOM_THRESHOLD_PX = 96;
let shouldAutoScroll = true;

function getSavedScrollTop() {
  const raw = localStorage.getItem(SCROLL_TOP_KEY);
  if (raw === null) {
    return null;
  }
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

function saveChatScrollTop() {
  if (!chatLog) {
    return;
  }
  localStorage.setItem(SCROLL_TOP_KEY, String(chatLog.scrollTop));
}

function distanceFromBottom() {
  if (!chatLog) {
    return 0;
  }
  return chatLog.scrollHeight - chatLog.clientHeight - chatLog.scrollTop;
}

function isNearBottom() {
  return distanceFromBottom() <= AUTO_SCROLL_BOTTOM_THRESHOLD_PX;
}

function restoreChatScroll({ fallbackToLatest = true } = {}) {
  if (!chatLog) {
    return;
  }

  const savedTop = getSavedScrollTop();
  requestAnimationFrame(() => {
    if (savedTop !== null) {
      chatLog.scrollTop = savedTop;
      shouldAutoScroll = isNearBottom();
      return;
    }
    if (fallbackToLatest) {
      scrollToLatest("auto");
      saveChatScrollTop();
      shouldAutoScroll = true;
    }
  });
}

function scrollToLatest(behavior = "smooth") {
  if (!chatLog) {
    return;
  }

  chatLog.scrollTo({
    top: chatLog.scrollHeight,
    behavior
  });
}

function setWidgetOpen(open, { focusInput = false } = {}) {
  if (!widget || !launchButton) {
    return;
  }

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

  if (open) {
    restoreChatScroll();
    if (focusInput && messageInput) {
      messageInput.focus();
    }
  }
}

function openWidgetFromTrigger(trigger) {
  const focusInput = trigger.hasAttribute("data-assistant-focus-input");
  setWidgetOpen(true, { focusInput });
}

if (widget && launchButton) {
  const savedState = localStorage.getItem(OPEN_STATE_KEY);
  setWidgetOpen(savedState === "1");

  launchButton.addEventListener("click", () => {
    setWidgetOpen(!widget.classList.contains("assistant-widget--open"), {
      focusInput: true
    });
  });

  if (minimizeButton) {
    minimizeButton.addEventListener("click", () => {
      setWidgetOpen(false);
    });
  }

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-assistant-open]");
    if (!trigger) {
      return;
    }

    event.preventDefault();
    openWidgetFromTrigger(trigger);
  });

  document.body.addEventListener("assistant-widget:open", () => {
    setWidgetOpen(true, { focusInput: true });
  });
}

if (chatLog) {
  restoreChatScroll();

  chatLog.addEventListener("scroll", () => {
    saveChatScrollTop();
    shouldAutoScroll = isNearBottom();
  });

  document.body.addEventListener("htmx:afterSwap", (event) => {
    if (event.detail && event.detail.target === chatLog) {
      if (shouldAutoScroll) {
        scrollToLatest("smooth");
      }
      saveChatScrollTop();
    }
  });

  const observer = new MutationObserver((mutations) => {
    let changed = false;
    for (const mutation of mutations) {
      if (mutation.addedNodes.length > 0) {
        changed = true;
        break;
      }
      if (mutation.type === "childList" && mutation.removedNodes.length > 0) {
        changed = true;
        break;
      }
    }
    if (!changed) {
      return;
    }
    if (shouldAutoScroll) {
      scrollToLatest("smooth");
    }
    saveChatScrollTop();
  });
  observer.observe(chatLog, { childList: true, subtree: true });

  document.body.addEventListener("htmx:responseError", (event) => {
    if (event.detail && event.detail.target === chatLog) {
      if (shouldAutoScroll) {
        scrollToLatest("smooth");
      }
      saveChatScrollTop();
    }
  });

}

if (sendForm && messageInput) {
  sendForm.addEventListener("submit", () => {
    shouldAutoScroll = true;
  });

  messageInput.addEventListener("keydown", (event) => {
    const isCtrlEnter = event.key === "Enter" && (event.ctrlKey || event.metaKey);
    if (!isCtrlEnter || event.isComposing) {
      return;
    }

    event.preventDefault();
    if (!messageInput.value.trim()) {
      return;
    }

    if (typeof sendForm.requestSubmit === "function") {
      sendForm.requestSubmit();
      return;
    }

    sendForm.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });

  sendForm.addEventListener("htmx:afterRequest", (event) => {
    if (event.detail && event.detail.successful) {
      sendForm.reset();
      messageInput.focus();
      saveChatScrollTop();
    }
  });
}

if (widget && sendForm && messageInput) {
  widget.addEventListener("click", (event) => {
    const chip = event.target.closest("[data-assistant-followup]");
    if (!chip) {
      return;
    }

    event.preventDefault();
    const reply = (chip.dataset.followupReply || chip.textContent || "").trim();
    if (!reply) {
      return;
    }

    shouldAutoScroll = true;
    messageInput.value = reply;
    messageInput.dispatchEvent(new Event("input", { bubbles: true }));
    if (typeof sendForm.requestSubmit === "function") {
      sendForm.requestSubmit();
      return;
    }
    sendForm.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}
