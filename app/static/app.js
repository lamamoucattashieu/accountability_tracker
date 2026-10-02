// UI state and rendering. Every server call goes through api.js; this file
// never uses fetch, URLs or status codes. Business rules (scoring, caps,
// streaks, settlement, vote thresholds) stay on the server: views only show
// what the API returns.

import { ApiError, auth, checkins, groups, onUnauthorized, points } from "./api.js";

const state = {
  me: null, // {id, username} of the logged-in user
  group: null, // the group being viewed
  tab: null, // which group tab is open
  names: new Map(), // user id -> username for the open group
  votes: new Map(), // check-in id -> vote result, display only: the server's 409 stays the source of truth
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

function textArea(label, attrs) {
  return el("label", { class: "field" }, el("span", { text: label }), el("textarea", attrs));
}

function select(label, attrs, options) {
  return el("label", { class: "field" }, el("span", { text: label }),
    el("select", attrs, ...options.map(({ value, text }) => el("option", { value, text }))));
}

function formatWhen(isoTime) {
  return new Date(isoTime).toLocaleString(undefined, {
    weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

// Gateway-style composition: the check-ins and goals APIs return only user_ids
// (that domain never reads auth's tables), and the members API returns names.
// The UI joins the two here, the way a gateway would after a service split.
function nameOf(userId) {
  if (state.me && userId === state.me.id) {
    return "You";
  }
  return state.names.get(userId) || "A member";
}

// "2026-09-28" -> "28 Sep". Weeks are UTC dates, so format them in UTC.
function formatDay(isoDate) {
  return new Date(`${isoDate}T00:00:00Z`).toLocaleDateString(undefined, {
    day: "numeric", month: "short", timeZone: "UTC",
  });
}

function badge(text, kind) {
  return el("span", { class: `badge badge-${kind}`, text });
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
    Object.assign(state, { me: null, group: null, tab: null, names: new Map(), votes: new Map() });
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
const groupTabs = {
  // Goals & Check-ins domain
  checkins: { label: "Check-ins", render: renderCheckins },
  goals: { label: "Goals", render: renderGoals },
  // Points & Forfeits domain
  leaderboard: { label: "Leaderboard", render: renderLeaderboard },
  forfeits: { label: "Forfeits", render: renderForfeits },
};

function refreshGroup() {
  show("group"); // re-render from fresh API data; the open tab is kept in state.tab
}

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
  panel.append(notice("Loading…"));
  groups.members(state.group.id)
    .then((members) => {
      state.names = new Map(members.map((member) => [member.id, member.username]));
      if (state.tab) {
        openTab(state.tab);
      }
    })
    .catch((error) => panel.replaceChildren(notice(errorText(error), "error")));
}

// --- Goals & Check-ins tabs ---------------------------------------------------

const CHECKIN_STATUS = {
  accepted: { text: "Counts", kind: "success" },
  rejected: { text: "Rejected by vote", kind: "danger" },
};

function renderCheckins(panel) {
  const postArea = el("div");
  const feed = el("div");
  panel.append(
    el("section", { class: "card" }, el("h3", { text: "Post a check-in" }), postArea),
    el("section", { class: "card" }, el("h3", { text: "Group feed" }), feed),
  );

  const myGoals = async () =>
    (await checkins.goals(state.group.id)).filter((goal) => goal.user_id === state.me.id);
  loadInto(postArea, myGoals, (container, goals) => {
    container.append(actionForm({
      fields: [
        select("Goal", { name: "goal", required: true },
          goals.map((goal) => ({ value: goal.id, text: goal.title }))),
        input("Photo proof", { name: "photo", type: "file", accept: "image/*", capture: "environment", required: true }),
        input("Caption (optional)", { name: "caption" }),
      ],
      submitLabel: "Post check-in",
      onSubmit: async (data) => {
        await checkins.create(data.get("goal"), data.get("photo"), data.get("caption"));
        refreshGroup();
      },
    }));
  }, "You don't have a goal yet. Add one in the Goals tab, then post your proof here.");

  loadFeed(feed);
}

function loadFeed(feed) {
  loadInto(feed, () => checkins.feed(state.group.id), (container, items) => {
    container.append(el("ul", { class: "list" }, ...items.map((item) => checkinCard(item, feed))));
  }, "No check-ins yet. Be the first to post proof!");
}

function checkinCard(item, feed) {
  const status = CHECKIN_STATUS[item.status];
  return el("li", { class: "checkin" },
    el("div", { class: "row" },
      el("strong", { text: nameOf(item.user_id) }),
      el("span", { class: "muted", text: formatWhen(item.created_at) }),
    ),
    el("p", { class: "muted", text: item.goal_title }),
    el("img", { src: item.photo_url, alt: `${nameOf(item.user_id)}'s proof for ${item.goal_title}`, loading: "lazy" }),
    item.caption ? el("p", { text: item.caption }) : null,
    el("div", { class: "row" }, badge(status.text, status.kind), voteControl(item, feed)),
  );
}

// Display-only rules: no vote button on your own check-ins, or after you voted
// this session. The server still enforces both (403 / 409) and the voting window.
function voteControl(item, feed) {
  const myVote = state.votes.get(item.id);
  if (myVote) {
    return el("span", { class: "muted", text: `You voted (${myVote.reject_votes}/${myVote.votes_needed} to reject)` });
  }
  if (item.user_id === state.me.id || item.status === "rejected") {
    return null;
  }
  const error = el("span", { class: "form-error", role: "alert" });
  const button = el("button", {
    type: "button",
    class: "danger",
    text: "Vote to reject",
    onclick: async () => {
      button.disabled = true;
      error.textContent = "";
      try {
        state.votes.set(item.id, await checkins.voteReject(item.id));
        loadFeed(feed); // show the server's new status, e.g. "Rejected by vote"
      } catch (failure) {
        error.textContent = errorText(failure);
        button.disabled = false;
      }
    },
  });
  return el("span", { class: "vote" }, button, error);
}

function renderGoals(panel) {
  const list = el("div");
  const create = actionForm({
    fields: [
      input("Goal", { name: "title", required: true, placeholder: "e.g. Gym" }),
      textArea("What counts? (optional)", { name: "description", placeholder: "e.g. at least 45 minutes" }),
      input("Times per week", { name: "times_per_week", inputmode: "numeric", required: true }),
    ],
    submitLabel: "Add goal",
    onSubmit: async (data) => {
      await checkins.createGoal(state.group.id, {
        title: data.get("title"),
        description: data.get("description"),
        timesPerWeek: Number(data.get("times_per_week")),
      });
      refreshGroup();
    },
  });
  panel.append(
    el("section", { class: "card" }, el("h3", { text: "Everyone's goals" }), list),
    el("section", { class: "card" }, el("h3", { text: "Add a goal" }), create),
  );

  loadInto(list, () => checkins.goals(state.group.id), (container, goals) => {
    container.append(el("ul", { class: "list" }, ...goals.map(goalItem)));
  }, "No goals yet. Add the first one below.");
}

function goalItem(goal) {
  const error = el("span", { class: "form-error", role: "alert" });
  const archive = goal.user_id === state.me.id
    ? el("button", {
      type: "button",
      class: "secondary",
      text: "Archive",
      onclick: async () => {
        try {
          await checkins.archiveGoal(goal.id);
          refreshGroup();
        } catch (failure) {
          error.textContent = errorText(failure);
        }
      },
    })
    : null;
  return el("li", { class: "goal" },
    el("div", { class: "row" },
      el("div", {},
        el("strong", { text: goal.title }),
        el("p", { class: "muted", text: `${nameOf(goal.user_id)} · ${goal.times_per_week}× per week` }),
      ),
      archive,
    ),
    goal.description ? el("p", { text: goal.description }) : null,
    error,
  );
}

// --- Points & Forfeits tabs -------------------------------------------------
// Scores, streaks, losers and proof status all come from the server; these
// views only display them.

function renderLeaderboard(panel) {
  const body = el("div");
  panel.append(el("section", { class: "card" }, body));
  loadInto(body, () => points.leaderboard(state.group.id), (container, board) => {
    container.append(
      el("div", { class: "row" },
        el("h3", { text: `Week of ${formatDay(board.week_start)}` }),
        board.provisional ? badge("Provisional", "warning") : badge("Final", "success"),
      ),
      board.provisional
        ? el("p", { class: "muted", text: "Votes can still change this week's ranking." })
        : null,
      el("ol", { class: "list leaderboard" }, ...board.entries.map(leaderboardRow)),
    );
  }, "");
}

function leaderboardRow(entry) {
  const isMe = entry.user_id === state.me.id;
  return el("li", { class: isMe ? "entry me" : "entry" },
    el("span", { class: "rank", text: `#${entry.rank}` }),
    el("span", { class: "entry-name", text: isMe ? `${entry.username} (you)` : entry.username }),
    entry.streak_bonus > 0 ? badge(`Streak +${entry.streak_bonus}`, "warning") : null,
    el("strong", { class: "entry-points", text: `${entry.points} pts` }),
  );
}

const OUTCOME_TEXT = {
  no_forfeit: "No forfeit was set for this week, so nobody had to do one.",
  no_loser: "Nobody lost: everyone was tied.",
};

const PROOF_STATUS = {
  pending: { text: "Proof due", kind: "info" },
  overdue: { text: "Overdue", kind: "danger" },
  submitted: { text: "Done", kind: "success" },
  late: { text: "Done late", kind: "warning" },
};

function renderForfeits(panel) {
  const current = el("div");
  const results = el("div");
  const setForfeit = actionForm({
    fields: [input("New forfeit", { name: "text", required: true, placeholder: "e.g. 50 burpees on video" })],
    submitLabel: "Set forfeit",
    onSubmit: async (data) => {
      await points.setForfeit(state.group.id, data.get("text"));
      refreshGroup();
    },
  });
  panel.append(
    el("section", { class: "card" }, el("h3", { text: "The forfeit" }), current),
    el("section", { class: "card" },
      el("h3", { text: "Change the forfeit" }),
      el("p", { class: "muted", text: "This week's forfeit is locked. A new one applies from next week." }),
      setForfeit,
    ),
    el("section", { class: "card" }, el("h3", { text: "Past weeks" }), results),
  );

  loadInto(current, () => points.forfeits(state.group.id), (container, forfeits) => {
    const thisWeek = forfeits.this_week.forfeit;
    const upcoming = forfeits.upcoming.forfeit;
    container.append(el("p", {
      class: "forfeit-text",
      text: thisWeek ? thisWeek.text : "No forfeit is locked in for this week.",
    }));
    if (upcoming && (!thisWeek || upcoming.id !== thisWeek.id)) {
      container.append(el("p", {
        class: "muted",
        text: `From ${formatDay(forfeits.upcoming.week_start)}: ${upcoming.text}`,
      }));
    }
  }, "");

  loadInto(results, () => points.settlements(state.group.id), (container, settlements) => {
    container.append(el("ul", { class: "list" }, ...settlements.map(settlementItem)));
  }, "No finished weeks yet.");
}

function settlementItem(settlement) {
  const losers = settlement.assignments.length > 0
    ? el("ul", { class: "list" }, ...settlement.assignments.map(assignmentItem))
    : el("p", { class: "muted", text: OUTCOME_TEXT[settlement.outcome] });
  return el("li", { class: "settlement" },
    el("strong", { text: `Week of ${formatDay(settlement.week_start)}` }),
    settlement.forfeit ? el("p", { class: "forfeit-text", text: settlement.forfeit }) : null,
    losers,
  );
}

function assignmentItem(assignment) {
  const status = PROOF_STATUS[assignment.status];
  const isMine = assignment.user_id === state.me.id;
  // Display-only: the upload form shows on your own assignment; the server
  // still rejects anyone else (403) and a second upload (409).
  const upload = isMine && !assignment.proof_url
    ? actionForm({
      fields: [input("Photo proof", { name: "photo", type: "file", accept: "image/*", capture: "environment", required: true })],
      submitLabel: "Upload proof",
      onSubmit: async (data) => {
        await points.uploadProof(assignment.id, data.get("photo"));
        refreshGroup();
      },
    })
    : null;
  return el("li", { class: "assignment" },
    el("div", { class: "row" },
      el("span", {}, el("strong", { text: nameOf(assignment.user_id) }), ` · ${assignment.score} pts`),
      badge(status.text, status.kind),
    ),
    el("p", { class: "muted", text: `Proof due by ${formatWhen(assignment.due_at)}` }),
    assignment.proof_url
      ? el("img", { src: assignment.proof_url, alt: `${nameOf(assignment.user_id)}'s forfeit proof`, loading: "lazy" })
      : null,
    upload,
  );
}

// --- Start -------------------------------------------------------------------

onUnauthorized(() => {
  Object.assign(state, { me: null, group: null, tab: null, names: new Map(), votes: new Map() });
  show("auth");
});

startSession().catch((error) => {
  // A 401 already showed the login view through onUnauthorized.
  if (!(error instanceof ApiError && error.status === 401)) {
    show("auth");
  }
});
