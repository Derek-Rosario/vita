const chatLog = document.getElementById("assistant-chat-log");
const sendForm = document.getElementById("assistant-send-form");
const messageInput = document.getElementById("assistant-message");

function scrollToLatest(behavior = "smooth") {
    if (!chatLog) {
        return;
    }

    chatLog.scrollTo({
        top: chatLog.scrollHeight,
        behavior,
    });
}

if (chatLog) {
    scrollToLatest("auto");

    document.body.addEventListener("htmx:afterSwap", (event) => {
        if (event.detail && event.detail.target === chatLog) {
            scrollToLatest("smooth");
        }
    });

    const observer = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
            if (mutation.addedNodes.length > 0) {
                scrollToLatest("smooth");
                break;
            }
            if (mutation.type === "childList" && mutation.removedNodes.length > 0) {
                scrollToLatest("smooth");
                break;
            }
        }
    });
    observer.observe(chatLog, { childList: true, subtree: true });

    document.body.addEventListener("htmx:responseError", (event) => {
        if (event.detail && event.detail.target === chatLog) {
            scrollToLatest("smooth");
        }
    });
}

if (sendForm && messageInput) {
    sendForm.addEventListener("htmx:afterRequest", (event) => {
        if (event.detail && event.detail.successful) {
            sendForm.reset();
            messageInput.focus();
        }
    });
}
