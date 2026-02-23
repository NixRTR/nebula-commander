(function () {
  const base = window.location.origin;

  function apiGet(path) {
    return fetch(base + path).then((r) => {
      if (!r.ok) throw new Error(r.statusText);
      return r.json();
    });
  }

  function apiPost(path, body) {
    return fetch(base + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => {
      return (r.json ? r.json() : Promise.resolve({})).then((data) => {
        if (!r.ok) throw Object.assign(new Error(data.error || r.statusText), { data });
        return data;
      });
    });
  }

  function showMsg(elId, text, isError) {
    const el = document.getElementById(elId);
    if (!el) return;
    el.textContent = text;
    el.className = "msg " + (isError ? "error" : "success");
    el.style.display = text ? "block" : "none";
  }

  function loadSettings() {
    return apiGet("/api/settings").then((data) => {
      document.getElementById("server").value = data.server || "https://";
      document.getElementById("output_dir").value = data.output_dir || "";
      document.getElementById("interval").value = data.interval || 60;
      document.getElementById("nebula_path").value = data.nebula_path || "";
      document.getElementById("autostart").checked = !!data.autostart;
      var startupSection = document.getElementById("section-startup");
      if (startupSection) startupSection.style.display = (data.platform === "win32") ? "" : "none";

      const enrolled = !!data.enrolled;
      const badge = document.getElementById("enrolled-badge");
      const link = document.getElementById("link-nebula-commander");
      if (enrolled) {
        badge.style.display = "inline-block";
        badge.textContent = "Enrolled";
        badge.className = "badge success";
        if (data.server && data.server !== "https://") {
          link.href = data.server;
          link.style.display = "inline";
        }
      } else {
        badge.style.display = "none";
        link.style.display = "none";
      }
      return data;
    });
  }

  function loadStatus() {
    return apiGet("/api/status").then((data) => {
      const el = document.getElementById("poll-status");
      if (el) el.textContent = "Status: " + (data.message || data.status || "–");
      return data;
    }).catch(() => {
      const el = document.getElementById("poll-status");
      if (el) el.textContent = "Status: –";
    });
  }

  document.getElementById("btn-enroll").addEventListener("click", function () {
    const server = document.getElementById("server").value.trim();
    const code = document.getElementById("code").value.trim().toUpperCase();
    showMsg("enroll-msg", "");
    if (!server) {
      showMsg("enroll-msg", "Enter server URL.", true);
      return;
    }
    if (!code) {
      showMsg("enroll-msg", "Enter enrollment code.", true);
      return;
    }
    apiPost("/api/enroll", { server, code })
      .then(() => {
        showMsg("enroll-msg", "Enrolled successfully.", false);
        document.getElementById("code").value = "";
        loadSettings();
      })
      .catch((e) => {
        showMsg("enroll-msg", e.data?.error || e.message || "Enroll failed.", true);
      });
  });

  document.getElementById("btn-save-settings").addEventListener("click", function () {
    const server = document.getElementById("server").value.trim() || "https://";
    const output_dir = document.getElementById("output_dir").value.trim();
    const interval = Math.max(10, Math.min(3600, parseInt(document.getElementById("interval").value, 10) || 60));
    const nebula_path = document.getElementById("nebula_path").value.trim();
    showMsg("settings-msg", "");
    apiPost("/api/settings", { server, output_dir, interval, nebula_path })
      .then(() => {
        showMsg("settings-msg", "Settings saved.", false);
        loadSettings();
      })
      .catch((e) => {
        showMsg("settings-msg", e.data?.error || e.message || "Save failed.", true);
      });
  });

  document.getElementById("autostart").addEventListener("change", function () {
    const enabled = this.checked;
    showMsg("autostart-msg", "");
    apiPost("/api/autostart", { enabled })
      .then((data) => {
        showMsg("autostart-msg", data.message || (enabled ? "Start at login enabled." : "Start at login disabled."), false);
      })
      .catch((e) => {
        showMsg("autostart-msg", e.data?.error || e.message || "Failed.", true);
      });
  });

  loadSettings().then(loadStatus);
  setInterval(loadStatus, 5000);
})();
