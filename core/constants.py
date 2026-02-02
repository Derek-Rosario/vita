from vita.settings import env


HOME_COORDINATES = {
    "latitude": float(env("HOME_LATITUDE")),
    "longitude": float(env("HOME_LONGITUDE")),
}
