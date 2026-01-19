const es = new ReconnectingEventSource("/events/");

es.addEventListener(
  "open",
  function (e) {
    console.log("Event stream opened.");
  },
  false
);

console.log("Connecting to event stream...");
es.addEventListener(
  "task-updated",
  function (e) {
    const event = new CustomEvent("task-updated", {
      detail: JSON.parse(e.data)
    });
    console.log(event)
    document.body.dispatchEvent(event);
  },
  false
);

document.addEventListener("task-updated", function (e) {
  console.log("Task updated event received:", e.detail);
}, false);

es.addEventListener(
  "stream-reset",
  function (e) {
    // ... client fell behind, reinitialize ...
  },
  false
);
