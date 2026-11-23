const state = {
  user: null,
  categories: [],
  levels: [],
  activeCategory: "All",
  songs: [],
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function escapeHtml(str) {
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatBytes(bytes) {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

async function api(url, options = {}) {
  const res = await fetch(url, { credentials: "same-origin", ...options });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || data.detail || `Request failed (${res.status})`);
  }
  return data;
}

// ---- Auth & Bootstrap ----

async function bootstrap() {
  const data = await api("/api/me");
  state.categories = data.meta?.categories || [];
  state.levels = data.meta?.levels || [];
  state.user = data.user;

  populateCategorySelect();
  renderCategoryPills();

  if (state.user) {
    showApp();
  } else {
    showLogin();
  }
}

function showLogin() {
  $("#login-screen").classList.remove("hidden");
  $("#app-shell").classList.add("hidden");
}

function showApp() {
  $("#login-screen").classList.add("hidden");
  $("#app-shell").classList.remove("hidden");

  $("#user-fullname").textContent = state.user.full_name;
  const badge = $("#user-badge");
  badge.textContent =
    state.user.role === "teacher" ? "Teacher" : `Student • ${state.user.level}`;
  badge.className =
    state.user.role === "teacher" ? "badge badge-primary" : "badge badge-accent";

  const isTeacher = state.user.role === "teacher";
  $$(".teacher-only").forEach((el) => {
    el.classList.toggle("hidden", !isTeacher);
  });

  switchTab("songs");
}

function switchTab(tabName) {
  $$(".nav-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tabName);
  });
  $$(".tab-panel").forEach((panel) => {
    panel.classList.toggle("hidden", panel.id !== `tab-${tabName}`);
  });

  if (tabName === "songs") loadSongs();
  if (tabName === "schedule") loadSchedule();
  if (tabName === "updates") loadUpdates();
  if (tabName === "students" && state.user?.role === "teacher") loadUsers();
}

// ---- Login Events ----

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const errBox = $("#login-error");
  errBox.classList.add("hidden");
  try {
    const data = await api("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: $("#login-username").value.trim(),
        password: $("#login-password").value,
      }),
    });
    state.user = data.user;
    showApp();
  } catch (err) {
    errBox.textContent = err.message;
    errBox.classList.remove("hidden");
  }
});

$$(".btn-chip[data-user]").forEach((btn) => {
  btn.addEventListener("click", () => {
    $("#login-username").value = btn.dataset.user;
    $("#login-password").value = btn.dataset.pass;
  });
});

$("#logout-btn").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" });
  state.user = null;
  showLogin();
});

$$(".nav-tab").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

// ---- Song Library ----

function populateCategorySelect() {
  const sel = $("#upload-category");
  sel.innerHTML = state.categories
    .map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`)
    .join("");
}

function renderCategoryPills() {
  const all = ["All", ...state.categories];
  $("#category-pills").innerHTML = all
    .map(
      (cat) => `
      <button type="button" class="cat-pill ${state.activeCategory === cat ? "active" : ""}" data-cat="${escapeHtml(cat)}">
        ${escapeHtml(cat)}
      </button>`
    )
    .join("");

  $$(".cat-pill").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.activeCategory = btn.dataset.cat;
      renderCategoryPills();
      loadSongs();
    });
  });
}

async function loadSongs() {
  const params = new URLSearchParams();
  if (state.activeCategory && state.activeCategory !== "All") {
    params.set("category", state.activeCategory);
  }
  const level = $("#song-level-filter").value;
  if (level && level !== "All") {
    params.set("level", level);
  }
  const q = $("#song-search").value.trim();
  if (q) {
    params.set("q", q);
  }

  const data = await api(`/api/songs?${params.toString()}`);
  state.songs = data.songs || [];
  renderSongs();
}

function renderSongs() {
  const grid = $("#songs-grid");
  if (!state.songs.length) {
    grid.innerHTML = `<div class="card"><p class="muted">No songs match your current filter.</p></div>`;
    return;
  }

  grid.innerHTML = state.songs
    .map((song) => {
      const files = song.files || [];
      const hasLyrics = Boolean(song.lyrics_text) || files.some((f) => f.component_type === "lyrics");
      const hasFullAudio = files.some((f) => f.component_type === "full_audio");
      const hasThalamVideo = files.some((f) => f.component_type === "thalam_video");
      const mpCount = files.filter((f) => f.component_type === "multipart_audio").length;

      const metaParts = [
        song.ragam ? `Ragam: ${song.ragam}` : "",
        song.thalam ? `Thalam: ${song.thalam}` : "",
        song.composer ? `Composer: ${song.composer}` : "",
      ].filter(Boolean);

      return `
        <article class="card song-card" data-song-id="${song.id}">
          <div>
            <div>
              <span class="badge badge-accent">${escapeHtml(song.category)}</span>
              <span class="badge">${escapeHtml(song.target_level)}</span>
            </div>
            <h3>${escapeHtml(song.title)}</h3>
            <p class="song-meta">${escapeHtml(metaParts.join(" • ") || "Classical Lesson")}</p>
          </div>
          <div class="comp-indicators">
            <span class="comp-tag ${hasLyrics ? "present" : ""}">Lyrics</span>
            <span class="comp-tag ${hasFullAudio ? "present" : ""}">Full Audio</span>
            <span class="comp-tag ${hasThalamVideo ? "present" : ""}">Thalam Video</span>
            <span class="comp-tag ${mpCount ? "present" : ""}">Multi-Part${mpCount ? ` (${mpCount})` : ""}</span>
          </div>
        </article>`;
    })
    .join("");

  $$(".song-card").forEach((card) => {
    card.addEventListener("click", () => openSongModal(Number(card.dataset.songId)));
  });
}

$("#song-search").addEventListener("input", () => loadSongs());
$("#song-level-filter").addEventListener("change", () => loadSongs());

// ---- Song Detail Modal ----

async function openSongModal(songId) {
  const data = await api(`/api/songs/${songId}`);
  const song = data.song;
  const files = song.files || [];

  $("#modal-category").textContent = song.category;
  $("#modal-level").textContent = song.target_level;
  $("#modal-title").textContent = song.title;

  const metaParts = [
    song.ragam ? `Ragam: ${song.ragam}` : "",
    song.thalam ? `Thalam: ${song.thalam}` : "",
    song.composer ? `Composer: ${song.composer}` : "",
    `Uploaded by ${song.teacher_name}`,
  ].filter(Boolean);
  $("#modal-meta").textContent = metaParts.join(" • ");

  const lyricsFiles = files.filter((f) => f.component_type === "lyrics");
  const fullAudioFiles = files.filter((f) => f.component_type === "full_audio");
  const thalamVideos = files.filter((f) => f.component_type === "thalam_video");
  const multipartFiles = files.filter((f) => f.component_type === "multipart_audio");

  const sections = [];

  if (song.notes) {
    sections.push(`
      <div class="detail-section">
        <h4>Teacher Notes</h4>
        <p>${escapeHtml(song.notes)}</p>
      </div>
    `);
  }

  sections.push(`
    <div class="detail-section">
      <h4>1. Lyrics</h4>
      ${song.lyrics_text ? `<pre class="lyrics-pre">${escapeHtml(song.lyrics_text)}</pre>` : ""}
      ${lyricsFiles
        .map(
          (f) => `
          <div class="media-item">
            <div class="media-row-top">
              <span>${escapeHtml(f.original_filename)} (${formatBytes(f.size_bytes)})</span>
              <div>
                <a class="btn btn-secondary btn-sm" href="/api/files/${f.id}" target="_blank" rel="noopener">View</a>
                <a class="btn btn-primary btn-sm" href="/api/files/${f.id}?download=1">Download</a>
              </div>
            </div>
          </div>`
        )
        .join("")}
      ${!song.lyrics_text && !lyricsFiles.length ? `<p class="muted">No lyrics uploaded yet.</p>` : ""}
    </div>
  `);

  sections.push(`
    <div class="detail-section">
      <h4>2. Full Audio Recording</h4>
      ${
        fullAudioFiles.length
          ? fullAudioFiles
              .map(
                (f) => `
                <div class="media-item">
                  <div class="media-row-top">
                    <span>${escapeHtml(f.original_filename)} (${formatBytes(f.size_bytes)})</span>
                    <a class="btn btn-primary btn-sm" href="/api/files/${f.id}?download=1">Download Audio</a>
                  </div>
                  <audio controls preload="metadata" src="/api/files/${f.id}"></audio>
                </div>`
              )
              .join("")
          : `<p class="muted">No full audio recording uploaded yet.</p>`
      }
    </div>
  `);

  sections.push(`
    <div class="detail-section">
      <h4>3. Video Recording of Thalam</h4>
      ${
        thalamVideos.length
          ? thalamVideos
              .map(
                (f) => `
                <div class="media-item">
                  <div class="media-row-top">
                    <span>${escapeHtml(f.original_filename)} (${formatBytes(f.size_bytes)})</span>
                    <a class="btn btn-primary btn-sm" href="/api/files/${f.id}?download=1">Download Video</a>
                  </div>
                  <video controls preload="metadata" src="/api/files/${f.id}"></video>
                </div>`
              )
              .join("")
          : `<p class="muted">No thalam video uploaded yet.</p>`
      }
    </div>
  `);

  sections.push(`
    <div class="detail-section">
      <h4>4. Multi-Part Audio Recordings</h4>
      ${
        multipartFiles.length
          ? `<div class="stack">` +
            multipartFiles
              .map(
                (f) => `
                <div class="media-item">
                  <div class="media-row-top">
                    <strong>${escapeHtml(f.part_label || f.original_filename)}</strong>
                    <a class="btn btn-primary btn-sm" href="/api/files/${f.id}?download=1">Download</a>
                  </div>
                  <span class="muted small-text">${escapeHtml(f.original_filename)} (${formatBytes(f.size_bytes)})</span>
                  <audio controls preload="metadata" src="/api/files/${f.id}"></audio>
                </div>`
              )
              .join("") +
            `</div>`
          : `<p class="muted">No multi-part audio clips uploaded yet.</p>`
      }
    </div>
  `);

  if (state.user?.role === "teacher") {
    sections.push(`
      <div>
        <button type="button" id="delete-song-btn" class="btn btn-danger btn-sm">Delete Song</button>
      </div>
    `);
  }

  $("#modal-body").innerHTML = sections.join("");
  $("#song-modal").classList.remove("hidden");

  const delBtn = $("#delete-song-btn");
  if (delBtn) {
    delBtn.addEventListener("click", async () => {
      if (!confirm(`Delete "${song.title}" and all its files?`)) return;
      await api(`/api/songs/${song.id}`, { method: "DELETE" });
      closeSongModal();
      loadSongs();
    });
  }
}

function closeSongModal() {
  $("#song-modal").classList.add("hidden");
  $("#modal-body").innerHTML = "";
}

$("#modal-close").addEventListener("click", closeSongModal);
$("#modal-backdrop").addEventListener("click", closeSongModal);

// ---- Upload Song (Teacher) ----

function addMultipartRow(defaultLabel = "") {
  const container = $("#multipart-rows");
  const row = document.createElement("div");
  row.className = "multipart-row";
  row.innerHTML = `
    <input type="text" name="multipart_label" placeholder="Part label (e.g. Pallavi, Part 1)" value="${escapeHtml(defaultLabel)}" />
    <input type="file" name="multipart_audio" accept="audio/*" />
    <button type="button" class="btn btn-ghost btn-sm remove-part-btn">Remove</button>
  `;
  row.querySelector(".remove-part-btn").addEventListener("click", () => row.remove());
  container.appendChild(row);
}

$("#add-multipart-btn").addEventListener("click", () => addMultipartRow());
addMultipartRow("Pallavi");
addMultipartRow("Anupallavi");

$("#upload-song-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const statusEl = $("#upload-status");
  statusEl.className = "status-banner";
  statusEl.textContent = "Uploading song and files...";
  statusEl.classList.remove("hidden");

  try {
    const formData = new FormData(e.target);
    await api("/api/songs", { method: "POST", body: formData });
    statusEl.textContent = "Song published successfully!";
    e.target.reset();
    $("#multipart-rows").innerHTML = "";
    addMultipartRow("Pallavi");
    addMultipartRow("Anupallavi");
  } catch (err) {
    statusEl.className = "error-banner";
    statusEl.textContent = err.message;
  }
});

// ---- Class Schedule ----

async function loadSchedule() {
  const data = await api("/api/schedule");
  const entries = data.schedule || [];
  const list = $("#schedule-list");
  if (!entries.length) {
    list.innerHTML = `<div class="card"><p class="muted">No classes scheduled yet.</p></div>`;
    return;
  }
  const isTeacher = state.user?.role === "teacher";
  list.innerHTML = entries
    .map(
      (item) => `
      <div class="card">
        <div class="list-card-row">
          <div>
            <span class="badge badge-accent">${escapeHtml(item.target_level)}</span>
            <h3 style="margin:0.4rem 0 0.2rem; color:var(--primary);">${escapeHtml(item.title)}</h3>
            <p class="muted"><strong>${escapeHtml(item.day_or_date)}</strong> • ${escapeHtml(item.time_slot)}${item.location_or_link ? ` • ${escapeHtml(item.location_or_link)}` : ""}</p>
            ${item.notes ? `<p style="margin:0.5rem 0 0;">${escapeHtml(item.notes)}</p>` : ""}
          </div>
          ${
            isTeacher
              ? `<button type="button" class="btn btn-danger btn-sm" data-del-sched="${item.id}">Remove</button>`
              : ""
          }
        </div>
      </div>`
    )
    .join("");

  $$("[data-del-sched]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await api(`/api/schedule/${btn.dataset.delSched}`, { method: "DELETE" });
      loadSchedule();
    });
  });
}

$("#schedule-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const payload = Object.fromEntries(fd.entries());
  await api("/api/schedule", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  e.target.reset();
  loadSchedule();
});

// ---- Class Updates ----

async function loadUpdates() {
  const data = await api("/api/updates");
  const updates = data.updates || [];
  const list = $("#updates-list");
  if (!updates.length) {
    list.innerHTML = `<div class="card"><p class="muted">No class updates posted yet.</p></div>`;
    return;
  }
  const isTeacher = state.user?.role === "teacher";
  list.innerHTML = updates
    .map(
      (u) => `
      <div class="card">
        <div class="list-card-row">
          <div style="flex:1;">
            <div>
              <span class="badge badge-accent">${escapeHtml(u.target_level)}</span>
              <span class="muted small-text" style="margin-left:0.4rem;">${formatDate(u.created_at)} • ${escapeHtml(u.author_name)}</span>
            </div>
            <h3 style="margin:0.4rem 0 0.25rem; color:var(--primary);">${escapeHtml(u.title)}</h3>
            <p style="margin:0; white-space:pre-wrap;">${escapeHtml(u.message)}</p>
            ${
              u.attachment_original_name
                ? `<div style="margin-top:0.75rem;">
                     <a class="btn btn-secondary btn-sm" href="/api/updates/${u.id}/attachment?download=1">
                       Download Attachment: ${escapeHtml(u.attachment_original_name)}
                     </a>
                   </div>`
                : ""
            }
          </div>
          ${
            isTeacher
              ? `<button type="button" class="btn btn-danger btn-sm" data-del-update="${u.id}">Delete</button>`
              : ""
          }
        </div>
      </div>`
    )
    .join("");

  $$("[data-del-update]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await api(`/api/updates/${btn.dataset.delUpdate}`, { method: "DELETE" });
      loadUpdates();
    });
  });
}

$("#update-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  await api("/api/updates", { method: "POST", body: fd });
  e.target.reset();
  loadUpdates();
});

// ---- Students & Access (Teacher) ----

$("#new-user-role").addEventListener("change", (e) => {
  $("#new-user-level-wrap").classList.toggle("hidden", e.target.value === "teacher");
});

async function loadUsers() {
  const data = await api("/api/users");
  const users = data.users || [];
  $("#users-list").innerHTML = users
    .map(
      (u) => `
      <div class="card">
        <div class="list-card-row">
          <div>
            <strong>${escapeHtml(u.full_name)}</strong>
            <span class="muted small-text">(@${escapeHtml(u.username)})</span>
            <div style="margin-top:0.3rem;">
              <span class="badge ${u.role === "teacher" ? "badge-primary" : "badge-accent"}">
                ${u.role === "teacher" ? "Teacher" : `Student • ${escapeHtml(u.level)}`}
              </span>
            </div>
          </div>
          ${
            u.id !== state.user.id
              ? `<button type="button" class="btn btn-danger btn-sm" data-del-user="${u.id}">Remove</button>`
              : ""
          }
        </div>
      </div>`
    )
    .join("");

  $$("[data-del-user]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await api(`/api/users/${btn.dataset.delUser}`, { method: "DELETE" });
      loadUsers();
    });
  });
}

$("#user-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const payload = Object.fromEntries(fd.entries());
  await api("/api/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  e.target.reset();
  $("#new-user-level-wrap").classList.remove("hidden");
  loadUsers();
});

bootstrap();

