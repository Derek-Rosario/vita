document.addEventListener("DOMContentLoaded", function () {
  const csrftoken = document.body.dataset.csrftoken;
  const watchID = navigator.geolocation.watchPosition((position) => {
    console.log(position);

    fetch("/update-geolocation/", {
      method: "POST",
      body: new URLSearchParams({
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        accuracy: position.coords.accuracy,
      }),
      headers: {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "X-CSRFToken": csrftoken,
      },
    }).catch(console.error);
  });
});
