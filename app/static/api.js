// Facade over fetch: the only module that knows URLs, HTTP methods and status
// codes. Views call intention-revealing functions and get data back, or an
// ApiError with a message they can show as-is.
//
// Authentication is a signed token from /auth/login, sent as
// "Authorization: Bearer <token>" on every request. It isn't a cookie, because
// the UI and the services are on different sites, where browsers block cookies.
// The token lives in localStorage, so JavaScript can read it: never putting user
// content into the page as HTML (views use textContent only) is what keeps an
// injected script from stealing it.

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

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

async function request(method, path, { json, form } = {}) {
  const options = { method, credentials: "omit", headers: authHeaders() };
  if (json !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(json);
  }
  if (form !== undefined) {
    options.body = form; // the browser sets the multipart boundary itself
  }

  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new ApiError(0, "Can't reach the server. Check your connection and try again.");
  }

  const isJson = (response.headers.get("content-type") || "").includes("application/json");
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

// --- Auth & groups (shared, not a domain) ---

/**
 * A photo behind the membership check, as a local object URL for an <img>.
 * An <img src> can't send the Authorization header, so the photo is fetched
 * here and handed to the page as a blob.
 */
export async function photoUrl(path) {
  const response = await fetch(path, { credentials: "omit", headers: authHeaders() });
  if (!response.ok) {
    throw new ApiError(response.status, `Photo unavailable (${response.status})`);
  }
  return URL.createObjectURL(await response.blob());
}

async function startSession(path, username, password) {
  const body = await request("POST", path, { json: { username, password } });
  saveToken(body.token);
  return body;
}

export const auth = {
  me: () => request("GET", "/auth/me"),
  register: (username, password) => startSession("/auth/register", username, password),
  login: (username, password) => startSession(PATHS.login, username, password),
  logout: async () => {
    try {
      await request("POST", "/auth/logout");
    } finally {
      saveToken(null); // logged out here even if the server couldn't be reached
    }
  },
};

export const groups = {
  list: () => request("GET", "/groups"),
  create: (name) => request("POST", "/groups", { json: { name } }),
  join: (inviteCode) => request("POST", "/groups/join", { json: { invite_code: inviteCode } }),
  members: (groupId) => request("GET", `/groups/${groupId}/members`),
};

// --- Goals & Check-ins domain ---

export const checkins = {
  goals: (groupId) => request("GET", `/groups/${groupId}/goals`),
  createGoal: (groupId, { title, description, timesPerWeek }) =>
    request("POST", `/groups/${groupId}/goals`, {
      json: { title, description, times_per_week: timesPerWeek },
    }),
  archiveGoal: (goalId) => request("POST", `/goals/${goalId}/archive`),
  feed: (groupId) => request("GET", `/groups/${groupId}/checkins`),
  create: (goalId, photo, caption) =>
    request("POST", `/goals/${goalId}/checkins`, { form: photoForm(photo, { caption }) }),
  voteReject: (checkinId) => request("POST", `/checkins/${checkinId}/votes`),
  comments: (checkinId) => request("GET", `/checkins/${checkinId}/comments`),
  addComment: (checkinId, text) =>
    request("POST", `/checkins/${checkinId}/comments`, { json: { text } }),
  progress: (groupId) => request("GET", `/groups/${groupId}/progress`),
  nudge: (groupId, memberId, message) =>
    request("POST", `/groups/${groupId}/members/${memberId}/nudges`, { json: { message } }),
  nudgesForMe: (groupId) => request("GET", `/groups/${groupId}/nudges`),
};

// --- Points & Forfeits domain ---

export const points = {
  leaderboard: (groupId) => request("GET", `/groups/${groupId}/leaderboard`),
  forfeits: (groupId) => request("GET", `/groups/${groupId}/forfeits`),
  setForfeit: (groupId, text) => request("POST", `/groups/${groupId}/forfeits`, { json: { text } }),
  settlements: (groupId) => request("GET", `/groups/${groupId}/settlements`),
  uploadProof: (assignmentId, photo) =>
    request("POST", `/forfeit-assignments/${assignmentId}/proof`, { form: photoForm(photo) }),
};
