// Facade over fetch: the only module that knows URLs, HTTP methods and status
// codes. Views call intention-revealing functions and get data back, or an
// ApiError with a message they can show as-is.
//
// Authentication is the httponly session cookie set by /auth/login. JavaScript
// can't read it (so XSS can't steal it); same-origin requests send it
// automatically. All URLs are relative, so this works wherever the app is hosted.

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

async function request(method, path, { json, form } = {}) {
  const options = { method, credentials: "same-origin", headers: {} };
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

export const auth = {
  me: () => request("GET", "/auth/me"),
  register: (username, password) =>
    request("POST", "/auth/register", { json: { username, password } }),
  login: (username, password) =>
    request("POST", PATHS.login, { json: { username, password } }),
  logout: () => request("POST", "/auth/logout"),
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
