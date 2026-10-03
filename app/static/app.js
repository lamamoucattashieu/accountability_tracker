// UI state and rendering. Every server call goes through api.js; this file
// never uses fetch, URLs or status codes. Business rules (scoring, caps,
// streaks, settlement, vote thresholds) stay on the server: views only show
// what the API returns.

import { ApiError, auth, checkins, groups, onUnauthorized, points } from "./api.js";

const state = {
  me: null, // {id, username} of the logged-in user
  group: null, // the group (crew) being viewed
  tab: "home", // which section of the group is open
  names: new Map(), // user id -> username for the open group
  votes: new Map(), // check-in id -> vote result, display only: the server's 409 stays the source of truth
  feedFilter: "all", // "all" or "wins" (accepted check-ins only); a display filter
  focusPost: false, // the camera button asks the home page to jump to the post form
};

const viewRoot = document.getElementById("view");
const userBar = document.getElementById("user-bar");
const topNav = document.getElementById("top-nav");
const bottomNav = document.getElementById("bottom-nav");

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

// Line icons, drawn from fixed path data with createElementNS (no markup strings).
const ICON_PATHS = {
  home: ["M3 10.5 12 3l9 7.5V21h-6v-6H9v6H3z"],
  feed: ["M13 2 3 14h9l-1 8 10-12h-9l1-8z"],
  crew: ["M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2", "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
    "M22 21v-2a4 4 0 0 0-3-3.87", "M16 3.13a4 4 0 0 1 0 7.75"],
  stats: ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z", "M12 18a6 6 0 1 0 0-12 6 6 0 0 0 0 12z",
    "M12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4z"],
  camera: ["M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z",
    "M12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z"],
  flame: ["M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.07-2.14-.22-4.05 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.15.43-2.29 1-3a2.5 2.5 0 0 0 2.5 2.5z"],
  plus: ["M12 5v14", "M5 12h14"],
  trophy: ["M8 21h8", "M12 17v4", "M7 4h10v5a5 5 0 0 1-10 0V4z", "M17 5h3v2a3 3 0 0 1-3 3",
    "M7 5H4v2a3 3 0 0 0 3 3"],
  check: ["M20 6 9 17l-5-5"],
  invite: ["M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2", "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
    "M19 8v6", "M22 11h-6"],
  reject: ["M18 6 6 18", "M6 6l12 12"],
};

function icon(name) {
  const svgNs = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNs, "svg");
  for (const [key, value] of Object.entries({
    viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "2",
    "stroke-linecap": "round", "stroke-linejoin": "round", class: "icon", "aria-hidden": "true",
  })) {
    svg.setAttribute(key, value);
  }
  for (const d of ICON_PATHS[name]) {
    const path = document.createElementNS(svgNs, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
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

function eyebrow(text, { live = false } = {}) {
  return el("p", { class: "eyebrow" }, live ? el("span", { class: "live-dot" }) : null, text);
}

// "okay, what are we " + underlined("doing") + " this week?"
function headline(before, underlined, after, tag = "h1") {
  return el(tag, { class: "headline" }, before, el("span", { class: "underline", text: underlined }), after);
}

function badge(text, kind) {
  return el("span", { class: `badge badge-${kind}`, text });
}

function formatWhen(isoTime) {
  return new Date(isoTime).toLocaleString(undefined, {
    weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

// "2026-09-28" -> "28 Sep". Weeks are UTC dates, so format them in UTC.
function formatDay(isoDate) {
  return new Date(`${isoDate}T00:00:00Z`).toLocaleDateString(undefined, {
    day: "numeric", month: "short", timeZone: "UTC",
  });
}

function timeAgo(isoTime) {
  const seconds = Math.max(0, (Date.now() - new Date(isoTime).getTime()) / 1000);
  const units = [["d", 86400], ["h", 3600], ["m", 60]];
  for (const [suffix, size] of units) {
    if (seconds >= size) {
      return `${Math.floor(seconds / size)}${suffix}`;
    }
  }
  return "now";
}

// Time until the end of the week the server reports (its week_start + 7 days).
function timeLeftInWeek(weekStart) {
  const end = new Date(`${weekStart}T00:00:00Z`).getTime() + 7 * 24 * 3600 * 1000;
  const hours = Math.max(0, Math.floor((end - Date.now()) / 3600000));
  return `${Math.floor(hours / 24)}d ${String(hours % 24).padStart(2, "0")}h left`;
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
function actionForm({ fields, submitLabel, submitIcon, onSubmit, extraActions = [] }) {
  const error = el("p", { class: "form-error", role: "alert" });
  const button = el("button", { type: "submit" }, submitIcon ? icon(submitIcon) : null, submitLabel);
  const form = el("form", {}, ...fields, el("div", { class: "form-actions" }, button, ...extraActions), error);
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

// --- People ------------------------------------------------------------------

// Gateway-style composition: the check-ins and goals APIs return only user_ids
// (that domain never reads auth's tables), and the members API returns names.
// The UI joins the two here, the way a gateway would after a service split.
function usernameOf(userId) {
  return state.names.get(userId) || "member";
}

function nameOf(userId) {
  return state.me && userId === state.me.id ? "You" : usernameOf(userId);
}

const AVATAR_COLORS = ["coral", "purple", "yellow", "lime"];

function initials(username) {
  return username.slice(0, 2).toUpperCase();
}

function avatar(userId, username = usernameOf(userId)) {
  const color = AVATAR_COLORS[userId % AVATAR_COLORS.length];
  return el("span", { class: `avatar avatar-${color}`, "aria-hidden": "true", text: initials(username) });
}

// --- Views and navigation ----------------------------------------------------

// View map: adding a screen means adding an entry, not another if/else branch.
const views = {
  auth: renderAuth,
  groups: renderGroups,
  group: renderGroup,
};

// Sections inside a crew, keyed by name. Home and Feed are the Goals & Check-ins
// domain; Crew and Stats are the Points & Forfeits domain.
const groupTabs = {
  home: { label: "home", icon: "home", render: renderHome },
  feed: { label: "feed", icon: "feed", render: renderFeed },
  crew: { label: "crew", icon: "crew", render: renderCrew },
  stats: { label: "stats", icon: "stats", render: renderStats },
};

function show(name) {
  renderUserBar();
  renderNav(name === "group");
  viewRoot.replaceChildren();
  views[name](viewRoot);
}

function openTab(name) {
  state.tab = name;
  show("group");
  window.scrollTo(0, 0);
}

function refreshGroup() {
  show("group"); // re-render from fresh API data; the open tab is kept in state.tab
}

function goPost() {
  state.focusPost = true;
  openTab("home");
}

function renderNav(inGroup) {
  topNav.replaceChildren();
  bottomNav.replaceChildren();
  bottomNav.hidden = !inGroup;
  document.body.classList.toggle("has-bottom-nav", inGroup);
  if (!inGroup) {
    return;
  }
  const navButton = (name, withIcon) => el("button", {
    type: "button",
    "aria-current": state.tab === name ? "page" : "false",
    onclick: () => openTab(name),
  }, withIcon ? icon(groupTabs[name].icon) : null, groupTabs[name].label);

  topNav.append(...Object.keys(groupTabs).map((name) => navButton(name, false)));
  const names = Object.keys(groupTabs);
  bottomNav.append(
    ...names.slice(0, 2).map((name) => navButton(name, true)),
    el("button", { type: "button", class: "camera-button", "aria-label": "Post proof", onclick: goPost }, icon("camera")),
    ...names.slice(2).map((name) => navButton(name, true)),
  );
}

function renderUserBar() {
  userBar.replaceChildren();
  if (!state.me) {
    return;
  }
  const menu = el("div", { class: "menu", id: "user-menu", hidden: true },
    el("p", { text: `@${state.me.username}` }),
    state.group ? el("button", { type: "button", class: "light small", text: "switch crew", onclick: switchCrew }) : null,
    el("button", { type: "button", class: "outline small", text: "log out", onclick: logOut }),
  );
  const button = el("button", {
    type: "button",
    class: "avatar-button",
    "aria-label": "Account menu",
    "aria-haspopup": "true",
    "aria-expanded": "false",
    "aria-controls": "user-menu",
    text: initials(state.me.username),
    onclick: () => {
      menu.hidden = !menu.hidden;
      button.setAttribute("aria-expanded", String(!menu.hidden));
    },
  });
  userBar.append(button, menu);
}

function switchCrew() {
  state.group = null;
  show("groups");
}

function resetState() {
  Object.assign(state, {
    me: null, group: null, tab: "home", names: new Map(), votes: new Map(), feedFilter: "all", focusPost: false,
  });
}

async function startSession() {
  state.me = await auth.me();
  show("groups");
}

async function logOut() {
  try {
    await auth.logout();
  } finally {
    resetState();
    show("auth");
  }
}

// --- Auth and crew picker ----------------------------------------------------

function renderAuth(root) {
  const credentials = () => [
    input("Username", { name: "username", autocomplete: "username", required: true }),
    input("Password", { name: "password", type: "password", required: true }),
  ];
  const login = actionForm({
    fields: credentials(),
    submitLabel: "log in",
    onSubmit: async (data) => {
      await auth.login(data.get("username"), data.get("password"));
      await startSession();
    },
  });
  const register = actionForm({
    fields: credentials(),
    submitLabel: "create account",
    onSubmit: async (data) => {
      await auth.register(data.get("username"), data.get("password"));
      await startSession();
    },
  });
  root.append(
    el("div", { class: "page-head" },
      eyebrow("No ghosting your goals"),
      headline("lock in with ", "your people", "."),
      el("p", { class: "lede", text: "Set weekly goals with friends, post photo proof, and the week's lowest scorer does the forfeit everyone agreed on." }),
    ),
    el("div", { class: "split" },
      el("section", { class: "card" }, el("h2", { text: "welcome back" }), login),
      el("section", { class: "card card-yellow" }, el("h2", { text: "new here?" }), register),
    ),
  );
}

function renderGroups(root) {
  const list = el("div");
  loadInto(list, groups.list, (container, myGroups) => {
    container.append(el("ul", { class: "list" }, ...myGroups.map((group) =>
      el("li", {},
        el("button", { type: "button", class: "group-card", onclick: () => openGroup(group) },
          el("span", { class: "person" },
            el("span", { class: `avatar avatar-${AVATAR_COLORS[group.id % AVATAR_COLORS.length]}`, text: initials(group.name) }),
            el("span", { class: "person-name", text: group.name }),
          ),
          el("span", { class: "code", text: group.invite_code }),
        ),
      ),
    )));
  }, "No crew yet. Start one, or join with a friend's invite code.");

  const create = actionForm({
    fields: [input("Crew name", { name: "name", required: true, placeholder: "e.g. gym gremlins" })],
    submitLabel: "start crew",
    onSubmit: async (data) => openGroup(await groups.create(data.get("name"))),
  });
  const join = actionForm({
    fields: [input("Invite code", { name: "invite_code", required: true, autocapitalize: "characters" })],
    submitLabel: "join crew",
    onSubmit: async (data) => openGroup(await groups.join(data.get("invite_code"))),
  });

  root.append(
    el("div", { class: "page-head" },
      eyebrow("Pick your crew"),
      headline("where are we ", "locking in", "?"),
    ),
    list,
    el("div", { class: "split" },
      el("section", { class: "card card-purple" }, el("h2", { text: "start a crew" }), create),
      el("section", { class: "card card-lime" }, el("h2", { text: "join your friends" }), join),
    ),
  );
}

function openGroup(group) {
  state.group = group;
  state.tab = "home";
  show("group");
}

function renderGroup(root) {
  root.append(notice("Loading your crew…"));
  groups.members(state.group.id)
    .then((members) => {
      state.names = new Map(members.map((member) => [member.id, member.username]));
      root.replaceChildren();
      groupTabs[state.tab].render(root);
    })
    .catch((error) => root.replaceChildren(notice(errorText(error), "error")));
}

// --- Home: post proof and your goals (Goals & Check-ins) ---------------------

function renderHome(root) {
  const weekday = new Date().toLocaleDateString(undefined, { weekday: "long" });
  const board = points.leaderboard(state.group.id); // shared by the pills and the countdown
  const pills = el("div", { class: "cluster" });
  const countdown = el("span", { class: "countdown" });
  const postArea = el("div");
  const goals = el("div");

  loadInto(pills, () => board, (container, data) => {
    countdown.textContent = timeLeftInWeek(data.week_start);
    const mine = data.entries.find((entry) => entry.user_id === state.me.id);
    container.append(
      el("span", { class: "pill pill-yellow" }, icon("flame"), `${mine.points} pts this week`,
        el("span", { class: "muted", text: mine.points ? "don't fumble" : "the week is young" })),
      mine.streak_bonus > 0 ? el("span", { class: "pill pill-lime", text: `streak +${mine.streak_bonus}` }) : null,
      el("span", { class: "pill pill-white", text: `#${mine.rank} in ${state.group.name}` }),
    );
  }, "");

  root.append(
    el("div", { class: "page-head" },
      eyebrow(`${weekday}, the plot continues`, { live: true }),
      headline("okay, what are we ", "doing", " this week?"),
    ),
    pills,
    el("section", { class: "card card-purple", id: "post-proof" },
      el("span", { class: "ring", "aria-hidden": "true" }),
      el("div", { class: "row" },
        el("span", { class: "chip" }, el("span", { class: "chip-dot" }), "weekly check-in"),
        countdown,
      ),
      eyebrow("This week's reality check"),
      el("h2", { text: "be so for real… did you do the thing?" }),
      el("p", { class: "muted", text: "Post your proof. Your crew can smell a camera-roll screenshot from a mile away." }),
      postArea,
    ),
    el("section", { class: "section" },
      el("div", { class: "section-head" },
        el("div", {}, eyebrow("Your promises"), el("h2", { text: "This week's non-negotiables" })),
      ),
      goals,
    ),
  );

  const goalsRequest = myGoals(); // one request shared by the post form and the list
  loadPostForm(postArea, goalsRequest);
  loadMyGoals(goals, goalsRequest);
}

const myGoals = async () =>
  (await checkins.goals(state.group.id)).filter((goal) => goal.user_id === state.me.id);

function loadPostForm(postArea, goalsRequest) {
  loadInto(postArea, () => goalsRequest, (container, goals) => {
    container.append(actionForm({
      fields: [
        select("Which promise?", { name: "goal", required: true },
          goals.map((goal) => ({ value: goal.id, text: goal.title }))),
        input("Photo proof", { name: "photo", type: "file", accept: "image/*", capture: "environment", required: true }),
        input("Caption (optional)", { name: "caption", placeholder: "e.g. 5.2K before my brain could negotiate" }),
      ],
      submitLabel: "post proof",
      submitIcon: "camera",
      onSubmit: async (data) => {
        await checkins.create(data.get("goal"), data.get("photo"), data.get("caption"));
        openTab("feed");
      },
    }));
    if (state.focusPost) {
      state.focusPost = false;
      container.scrollIntoView({ behavior: "smooth", block: "center" });
      container.querySelector("select").focus();
    }
  }, "Make a promise first (add a goal below), then post your proof here.");
}

const GOAL_TAG_COLORS = ["lime", "purple", "coral", "yellow"];

function loadMyGoals(container, goalsRequest) {
  const addForm = actionForm({
    fields: [
      input("The promise", { name: "title", required: true, placeholder: "e.g. Gym before 6" }),
      textArea("What counts? (optional)", { name: "description", placeholder: "e.g. Leg day. No mysterious calendar conflicts." }),
      input("Times per week", { name: "times_per_week", inputmode: "numeric", required: true }),
    ],
    submitLabel: "lock it in",
    onSubmit: async (data) => {
      await checkins.createGoal(state.group.id, {
        title: data.get("title"),
        description: data.get("description"),
        timesPerWeek: Number(data.get("times_per_week")),
      });
      refreshGroup();
    },
  });
  const addCard = el("section", { class: "card", hidden: true }, el("h3", { text: "add a promise" }), addForm);
  const addButton = el("button", {
    type: "button",
    class: "dashed",
    onclick: () => {
      addCard.hidden = !addCard.hidden;
      if (!addCard.hidden) {
        addCard.querySelector("input").focus();
      }
    },
  }, icon("plus"), "add one more (dangerous)");

  const list = el("div");
  container.append(list, addButton, addCard);
  loadInto(list, () => goalsRequest, (target, goals) => {
    target.append(el("ul", { class: "list" }, ...goals.map(goalCard)));
  }, "No promises yet. Add your first one.");
}

function goalCard(goal, index) {
  const error = el("p", { class: "form-error", role: "alert" });
  const color = GOAL_TAG_COLORS[index % GOAL_TAG_COLORS.length];
  return el("li", { class: "goal-card" },
    el("span", { class: "goal-tag", style: `background: var(--${color})`, text: `${goal.times_per_week}×/WK` }),
    el("div", { class: "goal-text" },
      el("span", { class: "goal-title", text: goal.title }),
      goal.description ? el("span", { class: "muted", text: goal.description }) : null,
      error,
    ),
    el("button", {
      type: "button",
      class: "outline small",
      text: "archive",
      onclick: async () => {
        try {
          await checkins.archiveGoal(goal.id);
          refreshGroup();
        } catch (failure) {
          error.textContent = errorText(failure);
        }
      },
    }),
  );
}

// --- Feed: everyone's check-ins and reject votes (Goals & Check-ins) ----------

const CHECKIN_STICKER = {
  accepted: { text: "verified sweat", kind: "" },
  rejected: { text: "rejected by the crew", kind: "sticker-danger" },
};

const FEED_FILTERS = {
  all: { label: "all", keep: () => true, empty: "No proof yet. Be the first to post!" },
  wins: { label: "wins", keep: (item) => item.status === "accepted", empty: "No wins yet this time." },
};

function renderFeed(root) {
  const feed = el("div");
  const toggle = el("div", { class: "segmented", role: "group", "aria-label": "Filter the feed" },
    ...Object.entries(FEED_FILTERS).map(([name, filter]) => el("button", {
      type: "button",
      "aria-pressed": String(state.feedFilter === name),
      text: filter.label,
      onclick: () => {
        state.feedFilter = name;
        refreshGroup();
      },
    })));
  root.append(
    el("div", { class: "section-head" },
      el("div", { class: "page-head" }, eyebrow("Live from the group chat"), el("h1", { class: "headline", text: "The accountability feed" })),
      toggle,
    ),
    feed,
  );
  loadFeed(feed);
}

function loadFeed(feed) {
  const filter = FEED_FILTERS[state.feedFilter];
  loadInto(feed, async () => (await checkins.feed(state.group.id)).filter(filter.keep), (container, items) => {
    container.append(el("ul", { class: "list" }, ...items.map((item) => postCard(item, feed))));
  }, filter.empty);
}

function postCard(item, feed) {
  const sticker = CHECKIN_STICKER[item.status];
  return el("li", { class: "post" },
    el("div", { class: "person" },
      avatar(item.user_id),
      el("div", { class: "person-text" },
        el("span", {}, el("span", { class: "person-name", text: nameOf(item.user_id) }),
          el("span", { class: "muted", text: ` · ${timeAgo(item.created_at)}` })),
        el("span", { class: "muted", text: item.goal_title }),
      ),
    ),
    el("div", { class: "photo-frame" },
      el("img", { src: item.photo_url, alt: `${nameOf(item.user_id)}'s proof for ${item.goal_title}`, loading: "lazy" }),
      el("span", { class: `sticker ${sticker.kind}`, text: sticker.text }),
      item.caption ? el("span", { class: "caption-bubble", text: item.caption }) : null,
    ),
    el("div", { class: "row" },
      voteControl(item, feed),
      el("span", { class: "muted", text: formatWhen(item.created_at) }),
    ),
  );
}

// Display-only rules: no vote button on your own check-ins, or after you voted
// this session. The server still enforces both (403 / 409) and the voting window.
function voteControl(item, feed) {
  const myVote = state.votes.get(item.id);
  if (myVote) {
    return el("span", { class: "badge badge-info", text: `you voted · ${myVote.reject_votes}/${myVote.votes_needed} to reject` });
  }
  if (item.user_id === state.me.id || item.status === "rejected") {
    return el("span");
  }
  const error = el("span", { class: "form-error", role: "alert" });
  const button = el("button", {
    type: "button",
    class: "light small",
    onclick: async () => {
      button.disabled = true;
      error.textContent = "";
      try {
        state.votes.set(item.id, await checkins.voteReject(item.id));
        loadFeed(feed); // show the server's new status, e.g. rejected by the crew
      } catch (failure) {
        error.textContent = errorText(failure);
        button.disabled = false;
      }
    },
  }, icon("reject"), "call cap");
  return el("span", { class: "vote" }, button, error);
}

// --- Crew: the forfeit and your people (Points & Forfeits) --------------------

function renderCrew(root) {
  const inviteStatus = el("span", { class: "muted", role: "status" });
  const invite = el("button", {
    type: "button",
    onclick: async () => {
      try {
        await navigator.clipboard.writeText(state.group.invite_code);
        inviteStatus.textContent = `Invite code ${state.group.invite_code} copied.`;
      } catch {
        inviteStatus.textContent = `Invite code: ${state.group.invite_code}`;
      }
    },
  }, icon("invite"), "invite a real one");

  const forfeit = el("div");
  const people = el("div");
  root.append(
    el("div", { class: "page-head" },
      eyebrow("Mutual surveillance, but cute"),
      headline("Your ", "lock-in", " crew."),
      el("p", { class: "lede", text: "The people who know “I got busy” is sometimes just code for “I opened TikTok.”" }),
      el("div", { class: "page-action cluster" }, invite, inviteStatus),
    ),
    forfeit,
    el("section", { class: "section" },
      el("div", { class: "section-head" },
        el("div", {}, eyebrow("Currently in the trenches"), el("h2", { text: "Your people" })),
        el("span", { class: "muted", text: `${state.names.size} in ${state.group.name}` }),
      ),
      people,
    ),
  );

  loadInto(forfeit, () => points.forfeits(state.group.id), renderForfeitCard, "");
  loadInto(people, () => points.leaderboard(state.group.id), (container, board) => {
    container.append(el("ul", { class: "list" }, ...board.entries.map(memberCard)));
  }, "");
}

function renderForfeitCard(container, forfeits) {
  const thisWeek = forfeits.this_week.forfeit;
  const upcoming = forfeits.upcoming.forfeit;
  const setForfeit = actionForm({
    fields: [input("Set next week's forfeit", { name: "text", required: true, placeholder: "e.g. last place renames the group chat" })],
    submitLabel: "set forfeit",
    onSubmit: async (data) => {
      await points.setForfeit(state.group.id, data.get("text"));
      refreshGroup();
    },
  });
  container.append(el("section", { class: "card card-yellow" },
    el("div", { class: "split" },
      el("div", { class: "section" },
        eyebrow(`This week's forfeit · locked since ${formatDay(forfeits.this_week.week_start)}`),
        el("p", { class: "card-big-text", text: thisWeek ? thisWeek.text : "no forfeit locked in" }),
        el("p", { class: "muted", text: "Lowest score when the week settles does it. Proof required, no take-backs." }),
      ),
      el("div", { class: "inset" },
        el("p", { class: "eyebrow", text: `Up next · from ${formatDay(forfeits.upcoming.week_start)}` }),
        el("p", { class: "goal-title", text: upcoming ? upcoming.text : "nothing set yet" }),
        setForfeit,
      ),
    ),
  ));
}

function memberCard(entry) {
  const isMe = entry.user_id === state.me.id;
  return el("li", { class: isMe ? "member-card me" : "member-card" },
    el("div", { class: "person" },
      avatar(entry.user_id, entry.username),
      el("div", { class: "person-text" },
        el("span", { class: "person-name", text: isMe ? `${entry.username} (you)` : entry.username }),
        el("span", { class: "muted", text: `@${entry.username} · #${entry.rank} this week` }),
      ),
    ),
    el("div", { class: "member-points" },
      el("div", { text: `${entry.points} pts` }),
      entry.streak_bonus > 0 ? badge(`streak +${entry.streak_bonus}`, "warning") : null,
    ),
  );
}

// --- Stats: this week's numbers and past forfeits (Points & Forfeits) ----------

const PROOF_STATUS = {
  pending: { text: "proof due", kind: "info" },
  overdue: { text: "overdue", kind: "danger" },
  submitted: { text: "done", kind: "success" },
  late: { text: "done late", kind: "warning" },
};

const OUTCOME_TEXT = {
  no_forfeit: "No forfeit was set, so nobody had to do one.",
  no_loser: "Nobody lost: everyone was tied.",
};

function renderStats(root) {
  const weekPill = el("span", { class: "pill pill-white page-action" });
  const numbers = el("div");
  const receipts = el("div");
  root.append(
    el("div", { class: "page-head" },
      eyebrow("Receipts from your locked-in era"),
      headline("The numbers don't ", "lie", "."),
      el("p", { class: "lede", text: "No vague self-improvement energy. Just cold, hard evidence that you showed up." }),
      weekPill,
    ),
    numbers,
    el("section", { class: "section" },
      el("div", {}, eyebrow("Past weeks"), el("h2", { text: "The receipts" })),
      receipts,
    ),
  );

  loadInto(numbers, () => points.leaderboard(state.group.id), (container, board) => {
    weekPill.textContent = `week of ${formatDay(board.week_start)}`;
    const mine = board.entries.find((entry) => entry.user_id === state.me.id);
    container.append(
      el("div", { class: "stat-grid" },
        statCard("lime", "stats", "Points this week", mine.points, "pts", "Straight from the scoreboard."),
        statCard("purple", "flame", "Streak bonus", `+${mine.streak_bonus}`, "pts",
          mine.streak_bonus ? "Kept a promise two weeks running." : "Hit a goal two weeks in a row to start one."),
        statCard("coral", "check", "Your rank", `#${mine.rank}`, `/${board.entries.length}`,
          board.provisional ? "Provisional: votes can still shuffle this." : "Final. It's in the books."),
      ),
      standingsCard(board),
    );
  }, "");

  loadInto(receipts, () => points.settlements(state.group.id), (container, settlements) => {
    container.append(el("div", { class: "split" }, ...settlements.map(settlementCard)));
  }, "No finished weeks yet. The first receipt lands after this week settles.");
}

function statCard(color, iconName, label, value, unit, caption) {
  return el("section", { class: `card card-${color}` },
    el("span", { class: "stat-icon" }, icon(iconName)),
    el("p", { class: "eyebrow", style: "color: var(--ink)", text: label }),
    el("p", { class: "stat-number" }, String(value), el("small", { text: unit })),
    el("p", { class: "muted", text: caption }),
  );
}

function standingsCard(board) {
  const most = Math.max(1, ...board.entries.map((entry) => entry.points));
  return el("section", { class: "card" },
    el("div", { class: "row" },
      el("div", {}, eyebrow("This week, so far"), el("h2", { text: "Standings" })),
      board.provisional ? badge("provisional", "warning") : badge("final", "success"),
    ),
    el("div", { class: "bars" }, ...board.entries.map((entry) => el("div", { class: "bar" },
      el("span", { class: "muted", text: `${entry.points} pts` }),
      el("div", { class: "bar-track" },
        el("div", {
          class: entry.user_id === state.me.id ? "bar-fill me" : "bar-fill",
          style: `height: ${Math.round((entry.points / most) * 100)}%`,
        })),
      el("span", { class: "bar-label", text: entry.user_id === state.me.id ? "you" : entry.username }),
    ))),
  );
}

function settlementCard(settlement) {
  const assigned = settlement.assignments.length > 0;
  return el("section", { class: assigned ? "card card-yellow" : "card" },
    el("div", { class: "row" },
      el("div", {}, eyebrow(`Week of ${formatDay(settlement.week_start)}`),
        el("h3", { text: settlement.forfeit || "no forfeit" })),
      el("span", { class: "sticker sticker-white", text: assigned ? "unlocked" : "settled" }),
    ),
    assigned
      ? el("ul", { class: "list" }, ...settlement.assignments.map(assignmentItem))
      : el("p", { class: "muted", text: OUTCOME_TEXT[settlement.outcome] }),
  );
}

function assignmentItem(assignment) {
  const status = PROOF_STATUS[assignment.status];
  const isMine = assignment.user_id === state.me.id;
  // Display-only: the upload form shows on your own assignment; the server
  // still rejects anyone else (403) and a second upload (409).
  const upload = isMine && !assignment.proof_url
    ? actionForm({
      fields: [input("Proof you did it", { name: "photo", type: "file", accept: "image/*", capture: "environment", required: true })],
      submitLabel: "upload proof",
      submitIcon: "camera",
      onSubmit: async (data) => {
        await points.uploadProof(assignment.id, data.get("photo"));
        refreshGroup();
      },
    })
    : null;
  return el("li", { class: "receipt" },
    el("div", { class: "row" },
      el("div", { class: "person" },
        avatar(assignment.user_id),
        el("div", { class: "person-text" },
          el("span", { class: "person-name", text: nameOf(assignment.user_id) }),
          el("span", { class: "muted", text: `${assignment.score} pts · due ${formatWhen(assignment.due_at)}` }),
        ),
      ),
      badge(status.text, status.kind),
    ),
    assignment.proof_url
      ? el("img", { src: assignment.proof_url, alt: `${nameOf(assignment.user_id)}'s forfeit proof`, loading: "lazy" })
      : null,
    upload,
  );
}

// --- Start -------------------------------------------------------------------

onUnauthorized(() => {
  resetState();
  show("auth");
});

startSession().catch((error) => {
  // A 401 already showed the login view through onUnauthorized.
  if (!(error instanceof ApiError && error.status === 401)) {
    show("auth");
  }
});
