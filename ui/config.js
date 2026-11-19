// Where the two services are. The UI never hardcodes them anywhere else.
//
// This file holds the local defaults (both services started with
// `python main.py` in their folders). The deploy pipeline replaces it with
// one holding the Azure URLs (A2 spec 1a), so the same UI files run anywhere.
window.APP_CONFIG = {
  checkinsUrl: "http://localhost:8000",
  pointsUrl: "http://localhost:8001",
};
