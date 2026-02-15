const SCROLL_PENDING_KEY = "assistant-chat-scroll-pending";

const chatLog = document.getElementById("assistant-chat-log");

if (chatLog) {
    function hasMessages() {
        return chatLog.querySelector("[data-chat-message]") !== null;
    }

    function scrollToLatest(behavior = "smooth") {
        if (!hasMessages()) {
            return;
        }

        chatLog.scrollTo({
            top: chatLog.scrollHeight,
            behavior,
        });
    }

    const sendForm = document.getElementById("assistant-send-form");
    const messageInput = document.getElementById("assistant-message");

    if (sendForm) {
        sendForm.addEventListener("submit", () => {
            if (
                messageInput &&
                "value" in messageInput &&
                String(messageInput.value).trim().length > 0
            ) {
                sessionStorage.setItem(SCROLL_PENDING_KEY, "1");
            }
        });
    }

    if (sessionStorage.getItem(SCROLL_PENDING_KEY) === "1") {
        sessionStorage.removeItem(SCROLL_PENDING_KEY);
        requestAnimationFrame(() => scrollToLatest("smooth"));
    } else {
        scrollToLatest("auto");
    }

    const observer = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
            if (mutation.addedNodes.length > 0) {
                scrollToLatest("smooth");
                break;
            }
        }
    });

    observer.observe(chatLog, { childList: true, subtree: true });
}
