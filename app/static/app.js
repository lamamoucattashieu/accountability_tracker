// UI state and rendering. Every server call goes through api.js; this file
// never uses fetch, URLs or status codes. Business rules (scoring, caps,
// streaks, settlement, vote thresholds) stay on the server: views only show
// what the API returns.

import { ApiError, auth, groups, onUnauthorized } from "./api.js";

const state = {
  me: null, // {id, username} of the logged-in user
  group: null, // the group being viewed
  tab: null, // which group tab is open
};

const viewRoot = document.getElementById("view");
const userBar = document.getElementById("user-bar");

// --- DOM helpers -------------------------------------------------------------

// The only way this file builds DOM. Text is always set through textContent or
// text nodes, never innerHTML, so user content (names, captions, forfeits)
// can't inject HTML or scripts.
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "text") {
      node.textContent = value;
    } else if (key.startsWith("on")) {
      node.addEventListener(key.slice(2), value);
    } else if (value === true) {
      node.setAttribute(key, "");
    } else if (value !== false && value !== null && value !== undefined) {
      node.setAttribute(key, value);
    }
  }
  node.append(...children.filter((child) => child !== null && child !== undefined));
  return node;
}

function notice(text, kind = "info") {
  const role = kind === "error" ? "alert" : "status";
  return el("p", { class: `notice notice-${kind}`, role, text });
}

function errorText(error) {
  return error instanceof ApiError ? error.message : "Something went wrong. Please try again.";
}

function input(label, attrs) {
  return el("label", { class: "field" }, el("span", { text: label }), el("input", attrs));
}

// Loading, empty and error states in one place, so every list behaves the same.
async function loadInto(container, fetchData, render, emptyText) {
  container.replaceChildren(notice("Loading…"));
  try {
    const data = await fetchData();
    container.replaceChildren();
    if (Array.isArray(data) && data.length === 0) {
      container.append(notice(emptyText));
    } else {
      render(container, data);
    }
  } catch (error) {
    container.replaceChildren(notice(errorText(error), "error"));
  }
}

// A form whose submit button is disabled while the request runs and which
// shows the API's error message under the fields.
function actionForm({ fields, submitLabel, onSubmit }) {
  const error = el("p", { class: "form-error", role: "alert" });
  const button = el("button", { type: "submit", text: submitLabel });
  const form = el("form", {}, ...fields, button, error);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.textContent = "";
    button.disabled = true;
    try {
      await onSubmit(new FormData(form), form);
    } catch (failure) {
      error.textContent = errorText(failure);
    } finally {
      button.disabled = false;
    }
  });
  return form;
}

// --- Views -------------------------------------------------------------------

// View map: adding a screen means adding an entry, not another if/else branch.
const views = {
  auth: renderAuth,
  groups: renderGroups,
  group: renderGroup,
};

function show(name) {
  renderUserBar();
  viewRoot.replaceChildren();
  views[name](viewRoot);
}

function renderUserBar() {
  userBar.replaceChildren();
  if (!state.me) {
    return;
  }
  userBar.append(
    el("span", { text: `Hi, ${state.me.username}` }),
    el("button", { type: "button", text: "Log out", onclick: logOut }),
  );
}

async function startSession() {
  state.me = await auth.me();
  show("groups");
}

async function logOut() {
  try {
    await auth.logout();
  } finally {
    Object.assign(state, { me: null, group: null, tab: null });
    show("auth");
  }
}

function renderAuth(root) {
  const credentials = () => [
    input("Username", { name: "username", autocomplete: "username", required: true }),
    input("Password", { name: "password", type: "password", required: true }),
  ];
  const login = actionForm({
    fields: credentials(),
    submitLabel: "Log in",
    onSubmit: async (data) => {
      await auth.login(data.get("username"), data.get("password"));
      await startSession();
    },
  });
  const register = actionForm({
    fields: credentials(),
    submitLabel: "Create account",
    onSubmit: async (data) => {
      await auth.register(data.get("username"), data.get("password"));
      await startSession();
    },
  });
  root.append(
    el("section", { class: "card" },
      el("h2", { text: "Hold each other to it" }),
      el("p", { class: "muted", text: "Set weekly goals with friends, post photo proof, and the week's lowest scorer does the forfeit." }),
    ),
    el("div", { class: "stack stack-2" },
      el("section", { class: "card" }, el("h2", { text: "Log in" }), login),
      el("section", { class: "card" }, el("h2", { text: "New here?" }), register),
    ),
  );
}

function renderGroups(root) {
  const list = el("div");
  loadInto(list, groups.list, (container, myGroups) => {
    container.append(el("ul", { class: "list" }, ...myGroups.map((group) =>
      el("li", {},
        el("button", { type: "button", class: "group-button", onclick: () => openGroup(group) },
          el("span", { text: group.name }),
          el("span", { class: "code", text: group.invite_code }),
        ),
      ),
    )));
  }, "You're not in a group yet. Create one, or join with a friend's invite code.");

  const create = actionForm({
    fields: [input("Group name", { name: "name", required: true })],
    submitLabel: "Create group",
    onSubmit: async (data) => openGroup(await groups.create(data.get("name"))),
  });
  const join = actionForm({
    fields: [input("Invite code", { name: "invite_code", required: true, autocapitalize: "characters" })],
    submitLabel: "Join group",
    onSubmit: async (data) => openGroup(await groups.join(data.get("invite_code"))),
  });

  root.append(
    el("section", { class: "card" }, el("h2", { text: "Your groups" }), list),
    el("div", { class: "stack stack-2" },
      el("section", { class: "card" }, el("h2", { text: "Start a group" }), create),
      el("section", { class: "card" }, el("h2", { text: "Join friends" }), join),
    ),
  );
}

function openGroup(group) {
  state.group = group;
  state.tab = Object.keys(groupTabs)[0] || null;
  show("group");
}

// Tabs inside a group, keyed by name. Each domain adds its own tabs here.
const groupTabs = {};

function renderGroup(root) {
  const panel = el("div", { class: "tab-panel" });
  const nav = el("nav", { class: "tabs", "aria-label": "Group sections" });

  function openTab(name) {
    state.tab = name;
    for (const button of nav.children) {
      button.setAttribute("aria-current", button.dataset.tab === name ? "page" : "false");
    }
    panel.replaceChildren();
    groupTabs[name].render(panel);
  }

  for (const [name, tab] of Object.entries(groupTabs)) {
    nav.append(el("button", {
      type: "button", class: "tab", "data-tab": name, text: tab.label, onclick: () => openTab(name),
    }));
  }

  root.append(
    el("section", { class: "card group-header" },
      el("button", { type: "button", class: "secondary", text: "← Groups", onclick: () => show("groups") }),
      el("h2", { text: state.group.name }),
      el("p", { class: "muted" }, "Invite code: ", el("span", { class: "code", text: state.group.invite_code })),
    ),
    nav,
    panel,
  );
  if (state.tab) {
    openTab(state.tab);
  }
}

// --- Start -------------------------------------------------------------------

onUnauthorized(() => {
  Object.assign(state, { me: null, group: null, tab: null });
  show("auth");
});

startSession().catch((error) => {
  // A 401 already showed the login view through onUnauthorized.
  if (!(error instanceof ApiError && error.status === 401)) {
    show("auth");
  }
});
