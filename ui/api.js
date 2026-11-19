// Facade over fetch: the only module that knows URLs, HTTP methods and status
// codes. Views call intention-revealing functions and get data back, or an
// ApiError with a message they can show as-is.
//
// There are two services: checkins (auth, groups, goals, check-ins) and points
// (leaderboard, forfeits). Their base URLs come from config.js, never from code.
//
// Authentication is a signed token from /auth/login, sent as
// "Authorization: Bearer <token>" on every request. It isn't a cookie, because
// the UI and the services are on different sites, where browsers block cookies.
// The token lives in localStorage, so JavaScript can read it: never putting user
// content into the page as HTML (views use textContent only) is what keeps an
// injected script from stealing it.

const config = window.APP_CONFIG || {};
const BASE_URLS = {
  checkins: (config.checkinsUrl || "").replace(/\/$/, ""),
  points: (config.pointsUrl || "").replace(/\/$/, ""),
};

// kind: "http" (the service answered with an error), "unavailable" (the
// service couldn't be reached at all), or "starting" (it is still waking up).
export class ApiError extends Error {
  constructor(status, message, kind = "http") {
    super(message);
    this.status = status;
    this.kind = kind;
  }
}

// A cold start on Azure: the first request after idle waits ~30 s, then gets a
// plain-text 503 ("App port is not ready") from the platform, not from our code.
// Retried with growing gaps for about a minute, the time a paused database
// takes to resume. Safe even for POSTs: that 503 means the app never saw them.
const STARTUP_RETRY_DELAYS_MS = [2000, 4000, 8000, 15000, 30000];

let handleStartingUp = () => {};

/** Register what to show while a service is waking up: handler(true) on start, handler(false) when done. */
export function onStartingUp(handler) {
  handleStartingUp = handler;
}

function isPlatformStartup(response, isJson) {
  return response.status === 503 && !isJson; // our own 503s always carry JSON {"detail": ...}
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Paths compared or reused in more than one place are named once here.
const PATHS = {
  login: "/auth/login",
};

const TOKEN_KEY = "lockin.token";

// localStorage can be missing or blocked (private windows, strict settings):
// the app then still works, the login just doesn't survive a reload.
let memoryToken = null;

function readToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || memoryToken;
  } catch {
    return memoryToken;
  }
}

function saveToken(token) {
  memoryToken = token;
  try {
    if (token) {
      localStorage.setItem(TOKEN_KEY, token);
    } else {
      localStorage.removeItem(TOKEN_KEY);
    }
  } catch {
    // memoryToken still holds it for this page
  }
}

let handleUnauthorized = () => {};

/** Register what to do when the session is missing or expired (401). */
export function onUnauthorized(handler) {
  handleUnauthorized = handler;
}

function messageFrom(body, status) {
  const detail = body && body.detail;
  if (typeof detail === "string") {
    return detail; // our domain errors: {"detail": "goal is archived"}
  }
  if (Array.isArray(detail) && detail.length > 0) {
    return detail.map((problem) => problem.msg).join("; "); // FastAPI 422 validation errors
  }
  return `Request failed (${status})`;
}

function authHeaders() {
  const token = readToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

const UNREACHABLE = {
  checkins: "Can't reach goals & check-ins right now. The scoreboard still works; try again in a bit.",
  points: "Can't reach the scoreboard right now. Goals and check-ins still work; try again in a bit.",
};

/** fetch, retrying while the service is waking up from a cold start. */
async function fetchWakingUp(service, url, options) {
  for (let attempt = 0; ; attempt += 1) {
    let response;
    try {
      response = await fetch(url, options);
    } catch {
      throw new ApiError(0, UNREACHABLE[service], "unavailable");
    }
    const isJson = (response.headers.get("content-type") || "").includes("application/json");
    if (!isPlatformStartup(response, isJson)) {
      if (attempt > 0) handleStartingUp(false);
      return { response, isJson };
    }
    if (attempt === STARTUP_RETRY_DELAYS_MS.length) {
      handleStartingUp(false);
      throw new ApiError(503, "Still starting up. Give it a moment, then try again.", "starting");
    }
    handleStartingUp(true);
    await sleep(STARTUP_RETRY_DELAYS_MS[attempt]);
  }
}

async function request(service, method, path, { json, form } = {}) {
  const options = { method, credentials: "omit", headers: authHeaders() };
  if (json !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(json);
  }
  if (form !== undefined) {
    options.body = form; // the browser sets the multipart boundary itself
  }

  const { response, isJson } = await fetchWakingUp(service, BASE_URLS[service] + path, options);
  const body = isJson ? await response.json() : null;
  if (!response.ok) {
    // A wrong password is also a 401, but that's an error to show, not a logout.
    if (response.status === 401 && path !== PATHS.login) {
      saveToken(null);
      handleUnauthorized();
    }
    throw new ApiError(response.status, messageFrom(body, response.status));
  }
  return body;
}

function photoForm(photo, extra = {}) {
  const form = new FormData();
  form.append("photo", photo);
  for (const [name, value] of Object.entries(extra)) {
    if (value) {
      form.append(name, value);
    }
  }
  return form;
}

// --- Auth & groups (in the checkins service) ---

/**
 * A photo behind the membership check, as a local object URL for an <img>.
 * An <img src> can't send the Authorization header, so the photo is fetched
 * here and handed to the page as a blob.
 */
export async function photoUrl(service, path) {
  const url = BASE_URLS[service] + path;
  const { response } = await fetchWakingUp(service, url, { credentials: "omit", headers: authHeaders() });
  if (!response.ok) {
    throw new ApiError(response.status, `Photo unavailable (${response.status})`);
  }
  return URL.createObjectURL(await response.blob());
}

async function startSession(path, username, password) {
  const body = await request("checkins", "POST", path, { json: { username, password } });
  saveToken(body.token);
  return body;
}

export const auth = {
  me: () => request("checkins", "GET", "/auth/me"),
  register: (username, password) => startSession("/auth/register", username, password),
  login: (username, password) => startSession(PATHS.login, username, password),
  logout: async () => {
    try {
      await request("checkins", "POST", "/auth/logout");
    } finally {
      saveToken(null); // logged out here even if the server couldn't be reached
    }
  },
};

export const groups = {
  list: () => request("checkins", "GET", "/groups"),
  create: (name) => request("checkins", "POST", "/groups", { json: { name } }),
  join: (inviteCode) => request("checkins", "POST", "/groups/join", { json: { invite_code: inviteCode } }),
  members: (groupId) => request("checkins", "GET", `/groups/${groupId}/members`),
};

// --- Goals & Check-ins domain ---

export const checkins = {
  goals: (groupId) => request("checkins", "GET", `/groups/${groupId}/goals`),
  createGoal: (groupId, { title, description, timesPerWeek }) =>
    request("checkins", "POST", `/groups/${groupId}/goals`, {
      json: { title, description, times_per_week: timesPerWeek },
    }),
  archiveGoal: (goalId) => request("checkins", "POST", `/goals/${goalId}/archive`),
  feed: (groupId) => request("checkins", "GET", `/groups/${groupId}/checkins`),
  create: (goalId, photo, caption) =>
    request("checkins", "POST", `/goals/${goalId}/checkins`, { form: photoForm(photo, { caption }) }),
  voteReject: (checkinId) => request("checkins", "POST", `/checkins/${checkinId}/votes`),
  comments: (checkinId) => request("checkins", "GET", `/checkins/${checkinId}/comments`),
  addComment: (checkinId, text) =>
    request("checkins", "POST", `/checkins/${checkinId}/comments`, { json: { text } }),
  progress: (groupId) => request("checkins", "GET", `/groups/${groupId}/progress`),
  nudge: (groupId, memberId, message) =>
    request("checkins", "POST", `/groups/${groupId}/members/${memberId}/nudges`, { json: { message } }),
  nudgesForMe: (groupId) => request("checkins", "GET", `/groups/${groupId}/nudges`),
};

// --- Points & Forfeits (the points service) ---

export const points = {
  leaderboard: (groupId) => request("points", "GET", `/groups/${groupId}/leaderboard`),
  forfeits: (groupId) => request("points", "GET", `/groups/${groupId}/forfeits`),
  setForfeit: (groupId, text) => request("points", "POST", `/groups/${groupId}/forfeits`, { json: { text } }),
  settlements: (groupId) => request("points", "GET", `/groups/${groupId}/settlements`),
  uploadProof: (assignmentId, photo) =>
    request("points", "POST", `/forfeit-assignments/${assignmentId}/proof`, { form: photoForm(photo) }),
};
