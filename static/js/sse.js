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
    document.body.dispatchEvent(new CustomEvent("task-updated", {
        detail: e.data
    }));
  },
  false
);

es.addEventListener(
  "stream-reset",
  function (e) {
    // ... client fell behind, reinitialize ...
  },
  false
);
