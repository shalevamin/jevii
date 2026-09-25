(() => {
  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

  const state = {
    messages: [
      {
        role: "assistant",
        content:
          "Hi — I'm jevii on your Mac. I can see the screen, click, type, and open apps like a human operator. Connect a provider to get started.",
      },
    ],
    doctor: null,
    keys: null,
    oauth: { chatgpt: {}, claude: {}, grok: {} },
    local: {},
    telegram: {},
    skippedConnect: false,
    skippedTypesafe: false,
    pollTimers: {},
  };

  function anyBackend() {
    const k = state.keys || {};
    const o = state.oauth || {};
    const l = state.local || {};
    if (k.any_provider || k.openai || k.anthropic || k.xai) return true;
    if (o.chatgpt?.connected || o.claude?.connected || o.grok?.connected) return true;
    if (l.ollama?.reachable || l.lmstudio?.reachable) return true;
    return false;
  }

  function setView(name) {
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
    $$(".rail-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
    if (name === "permissions" || name === "settings") refreshDoctor();
  }

  $$(".rail-btn").forEach((btn) =>
    btn.addEventListener("click", () => setView(btn.dataset.view))
  );

  function renderMessages() {
    const box = $("#messages");
    box.innerHTML = "";
    state.messages.forEach((m) => {
      const div = document.createElement("div");
      div.className = `bubble ${m.role}${m.error ? " error" : ""}`;
      div.textContent = m.content;
      box.appendChild(div);
    });
    box.scrollTop = box.scrollHeight;
  }

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    let data = null;
    try {
      data = await res.json();
    } catch {
      data = { ok: false, error: `HTTP ${res.status}` };
    }
    return { res, data };
  }

  function badge(el, ok, softLabel) {
    if (!el) return;
    if (softLabel) {
      el.textContent = softLabel;
      el.className = "badge soft";
      return;
    }
    el.textContent = ok ? "granted" : "needed";
    el.className = `badge ${ok ? "ok" : "bad"}`;
  }

  function setMsg(el, text, ok) {
    if (!el) return;
    if (!text) {
      el.hidden = true;
      el.textContent = "";
      return;
    }
    el.hidden = false;
    el.textContent = text;
    el.className = `hint ${el.id === "modalKeyMsg" ? "modal-msg" : ""} ${ok ? "ok" : "bad"}`.trim();
  }

  function updateKeyBadges(keys) {
    state.keys = keys || {};
    ["openai", "anthropic", "xai", "typesafe"].forEach((k) => {
      $$(`[data-badge="${k}"]`).forEach((el) => {
        const present = !!keys?.[k];
        el.textContent = present ? "present" : "missing";
        el.className = `badge ${present ? "ok" : "bad"}`;
      });
    });
    updateKeyBanner();
  }

  function hasTypesafe() {
    return !!state.keys?.typesafe;
  }

  function updateKeyBanner() {
    const banner = $("#keyBanner");
    if (!banner) return;
    banner.hidden = anyBackend();
  }

  function oauthCardHtml(id, title, note, extra = "") {
    const st = state.oauth?.[id] || {};
    const connected = !!st.connected;
    return `
      <article class="oauth-card" data-oauth="${id}">
        <div class="provider-card-head">
          <h4>${title}</h4>
          <span class="badge ${connected ? "ok" : "bad"}" data-oauth-badge="${id}">${connected ? "Connected" : "Not connected"}</span>
        </div>
        <p class="hint">${note}</p>
        <div class="provider-card-actions">
          <button type="button" class="primary oauth-connect-btn" data-oauth="${id}">${connected ? "Reconnect" : "Connect " + title.replace(/^Sign in with /, "")}</button>
          ${connected ? `<button type="button" class="ghost oauth-logout-btn" data-oauth="${id}">Disconnect</button>` : ""}
          ${extra}
        </div>
        <div class="oauth-fallback" data-oauth-fallback="${id}" hidden>
          <label class="field-label">Paste redirect URL / code (fallback)</label>
          <input class="key-input oauth-paste" data-oauth="${id}" placeholder="http://localhost… or code#state" />
          <button type="button" class="ghost oauth-complete-btn" data-oauth="${id}">Submit code</button>
        </div>
        <div class="oauth-device" data-oauth-device="${id}" hidden></div>
        <p class="hint oauth-msg" data-oauth-msg="${id}" hidden></p>
      </article>`;
  }

  function renderOauthCards() {
    const chatgptNote =
      "Uses official ChatGPT/Codex OAuth (same path as OpenClaw/Hermes). Counts against ChatGPT plan Codex quota, not Platform API billing.";
    const claudeNote =
      "Works like OpenClaw/Hermes Claude login. Anthropic may route third-party OAuth to extra-usage / policy limits; API key remains the reliable fallback. Claude Pro alone may not work; Max + eligible credits is typical.";
    const grokNote =
      "Needs eligible SuperGrok / X Premium+. xAI may 403 some tiers — then fall back to XAI_API_KEY. Device-code login (no localhost callback).";
    const claudeExtra = state.oauth?.claude?.claude_code_available
      ? `<button type="button" class="ghost" id="btnImportClaudeCode">Use Claude Code login</button>`
      : "";
    const html =
      oauthCardHtml("chatgpt", "Sign in with ChatGPT", chatgptNote) +
      oauthCardHtml("claude", "Sign in with Claude", claudeNote, claudeExtra) +
      oauthCardHtml("grok", "Sign in with Grok", grokNote);
    ["#modalOauthCards", "#settingsOauthCards"].forEach((sel) => {
      const el = $(sel);
      if (el) el.innerHTML = html;
    });
    $("#btnImportClaudeCode")?.addEventListener("click", importClaudeCode);
  }

  function showConnectModal() {
    const modal = $("#connectModal");
    if (!modal) return;
    renderOauthCards();
    modal.hidden = false;
    document.body.style.overflow = "hidden";
  }

  function hideConnectModal() {
    const modal = $("#connectModal");
    if (!modal) return;
    modal.hidden = true;
    document.body.style.overflow = "";
  }

  function keyMsgEl(provider, root) {
    if (provider === "typesafe") {
      if (root?.closest?.("#wizardTypesafe") || root?.closest?.("#view-permissions")) {
        return $("#wizardTypesafeMsg");
      }
      return $("#settingsTypesafeMsg") || $("#settingsKeyMsg");
    }
    if (root?.closest?.("#connectModal")) return $("#modalKeyMsg");
    return $("#settingsKeyMsg");
  }

  async function saveKey(provider, root) {
    const input =
      root?.querySelector?.(`.key-input[data-provider="${provider}"]`) ||
      document.querySelector(`.key-input[data-provider="${provider}"]`);
    const value = (input?.value || "").trim();
    const msgEl = keyMsgEl(provider, root);
    if (!value) {
      setMsg(msgEl, "Enter a key before saving.", false);
      return false;
    }
    const btn = root?.querySelector?.(`.save-key-btn[data-provider="${provider}"]`);
    if (btn) btn.disabled = true;
    try {
      const { res, data } = await api("/api/keys/save", {
        method: "POST",
        body: JSON.stringify({ provider, key: value }),
      });
      if (!res.ok || !data.ok) {
        const err = data.detail || data.error || "Save failed";
        setMsg(msgEl, typeof err === "string" ? err : JSON.stringify(err), false);
        return false;
      }
      if (input) input.value = "";
      updateKeyBadges(data.keys || {});
      if (provider === "typesafe") {
        setMsg(msgEl, "TypeSafe key saved (separate from chat).", true);
        await refreshDoctor();
        return true;
      }
      setMsg(msgEl, `Saved ${provider} key.`, true);
      hideConnectModal();
      state.skippedConnect = false;
      await refreshDoctor();
      return true;
    } catch (err) {
      setMsg(msgEl, String(err), false);
      return false;
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  document.addEventListener("click", (e) => {
    const btn = e.target.closest?.(".save-key-btn");
    if (btn) {
      saveKey(btn.dataset.provider, btn.closest(".provider-card"));
      return;
    }
    const connectBtn = e.target.closest?.(".oauth-connect-btn");
    if (connectBtn) {
      startOauth(connectBtn.dataset.oauth);
      return;
    }
    const logoutBtn = e.target.closest?.(".oauth-logout-btn");
    if (logoutBtn) {
      logoutOauth(logoutBtn.dataset.oauth);
      return;
    }
    const completeBtn = e.target.closest?.(".oauth-complete-btn");
    if (completeBtn) {
      completeOauth(completeBtn.dataset.oauth);
      return;
    }
  });

  const oauthApi = {
    chatgpt: {
      start: "/api/oauth/openai/start",
      status: "/api/oauth/openai/status",
      complete: "/api/oauth/openai/complete",
      logout: "/api/oauth/openai/logout",
    },
    claude: {
      start: "/api/oauth/anthropic/start",
      status: "/api/oauth/anthropic/status",
      complete: "/api/oauth/anthropic/complete",
      logout: "/api/oauth/anthropic/logout",
    },
    grok: {
      start: "/api/oauth/xai/start",
      status: "/api/oauth/xai/status",
      logout: "/api/oauth/xai/logout",
    },
  };

  function oauthMsg(id, text, ok) {
    $$(`[data-oauth-msg="${id}"]`).forEach((el) => setMsg(el, text, ok));
  }

  async function startOauth(id) {
    const cfg = oauthApi[id];
    if (!cfg) return;
    oauthMsg(id, "Starting sign-in…", true);
    try {
      const { data } = await api(cfg.start, { method: "POST", body: "{}" });
      if (!data.ok) {
        oauthMsg(id, data.error || "Could not start OAuth", false);
        return;
      }
      if (id === "grok") {
        const url = data.verification_url || "";
        const code = data.user_code || "";
        $$(`[data-oauth-device="${id}"]`).forEach((el) => {
          el.hidden = false;
          el.innerHTML = `<p class="hint">Open <a href="${url}" target="_blank" rel="noopener">${url}</a> and enter code <strong>${code}</strong> if asked. Waiting for approval…</p>`;
        });
        oauthMsg(id, "Waiting for browser approval…", true);
      } else {
        $$(`[data-oauth-fallback="${id}"]`).forEach((el) => {
          el.hidden = false;
        });
        oauthMsg(id, "Browser opened. Complete login, or paste the redirect URL below.", true);
      }
      startPolling(id);
    } catch (err) {
      oauthMsg(id, String(err), false);
    }
  }

  function startPolling(id) {
    stopPolling(id);
    const cfg = oauthApi[id];
    let n = 0;
    state.pollTimers[id] = setInterval(async () => {
      n += 1;
      if (n > 100) {
        stopPolling(id);
        oauthMsg(id, "Timed out waiting for sign-in. Try again or paste the code.", false);
        return;
      }
      try {
        const { data } = await api(cfg.status);
        if (data.connected) {
          stopPolling(id);
          state.oauth[id] = data;
          renderOauthCards();
          oauthMsg(id, "Connected.", true);
          hideConnectModal();
          updateKeyBanner();
          refreshDoctor();
          return;
        }
        if (data.error && !data.pending) {
          stopPolling(id);
          oauthMsg(id, data.error, false);
        }
      } catch {
        /* ignore transient */
      }
    }, 1500);
  }

  function stopPolling(id) {
    if (state.pollTimers[id]) {
      clearInterval(state.pollTimers[id]);
      delete state.pollTimers[id];
    }
  }

  async function completeOauth(id) {
    const cfg = oauthApi[id];
    if (!cfg?.complete) return;
    const input = document.querySelector(`.oauth-paste[data-oauth="${id}"]`);
    const raw = (input?.value || "").trim();
    if (!raw) {
      oauthMsg(id, "Paste the redirect URL or code first.", false);
      return;
    }
    const { data } = await api(cfg.complete, {
      method: "POST",
      body: JSON.stringify({ code_or_url: raw }),
    });
    if (data.ok && data.connected) {
      stopPolling(id);
      state.oauth[id] = data;
      renderOauthCards();
      oauthMsg(id, "Connected.", true);
      hideConnectModal();
      refreshDoctor();
    } else {
      oauthMsg(id, data.error || "Could not complete login", false);
    }
  }

  async function logoutOauth(id) {
    const cfg = oauthApi[id];
    if (!cfg) return;
    await api(cfg.logout, { method: "POST", body: "{}" });
    stopPolling(id);
    state.oauth[id] = { connected: false };
    renderOauthCards();
    updateKeyBanner();
    refreshDoctor();
  }

  async function importClaudeCode() {
    const { data } = await api("/api/oauth/anthropic/import-claude-code", {
      method: "POST",
      body: "{}",
    });
    if (data.ok) {
      state.oauth.claude = { connected: true };
      renderOauthCards();
      oauthMsg("claude", "Imported Claude Code login.", true);
      hideConnectModal();
      refreshDoctor();
    } else {
      oauthMsg("claude", data.error || "Import failed", false);
    }
  }

  $("#btnSkipConnect")?.addEventListener("click", () => {
    state.skippedConnect = true;
    hideConnectModal();
    updateKeyBanner();
  });
  $("#btnConnectBanner")?.addEventListener("click", () => showConnectModal());

  async function refreshDoctor() {
    const { data } = await api("/api/doctor");
    state.doctor = data;
    state.oauth = data?.oauth || state.oauth;
    state.local = data?.local || {};
    state.telegram = data?.telegram || {};
    const ax = !!data?.permissions?.accessibility;
    const sr = !!data?.permissions?.screen_recording;
    badge($("#badge-accessibility"), ax);
    badge($("#badge-screen_recording"), sr);
    badge($("#badge-full_disk"), null, "optional");
    const rail = $("#railStatus");
    rail.className = `rail-status ${data?.ok || data?.any_chat_backend ? "ok" : "bad"}`;
    const bin = data?.enable_binary || "jevii Python";
    if ($("#binHint1")) $("#binHint1").textContent = bin;
    if ($("#processHint")) $("#processHint").textContent = data?.process_hint || "";
    updateKeyBadges(data?.keys || {});
    const cdp = data?.cdp;
    if ($("#cdpStatus")) {
      $("#cdpStatus").textContent = cdp?.ok
        ? `CDP ready on port ${cdp.port}`
        : `CDP not ready (${cdp?.error || "offline"})`;
    }
    // local badges
    const o = state.local.ollama || {};
    const l = state.local.lmstudio || {};
    if ($("#badge-ollama")) {
      $("#badge-ollama").textContent = o.reachable ? "online" : "offline";
      $("#badge-ollama").className = `badge ${o.reachable ? "ok" : "bad"}`;
    }
    if ($("#badge-lmstudio")) {
      $("#badge-lmstudio").textContent = l.reachable ? "online" : "offline";
      $("#badge-lmstudio").className = `badge ${l.reachable ? "ok" : "bad"}`;
    }
    if ($("#ollamaModels")) {
      $("#ollamaModels").textContent = o.reachable
        ? `Models: ${(o.models || []).slice(0, 8).join(", ") || "(none)"}`
        : o.error || "Ollama offline";
    }
    if ($("#lmstudioModels")) {
      $("#lmstudioModels").textContent = l.reachable
        ? `Models: ${(l.models || []).slice(0, 8).join(", ") || "(none)"}`
        : l.error || "LM Studio offline";
    }
    // telegram
    const tg = state.telegram;
    if ($("#badge-telegram")) {
      const label = tg.running ? "running" : tg.configured ? "configured" : "not set";
      $("#badge-telegram").textContent = label;
      $("#badge-telegram").className = `badge ${tg.running || tg.configured ? "ok" : "bad"}`;
    }
    renderOauthCards();
    updateKeyBanner();
    return data;
  }

  $$(".open-settings").forEach((btn) =>
    btn.addEventListener("click", async () => {
      await api("/api/settings/open", {
        method: "POST",
        body: JSON.stringify({ pane: btn.dataset.pane || btn.dataset.pane }),
      });
    })
  );
  $("#btnOpenAll")?.addEventListener("click", async () => {
    await api("/api/settings/open-all", { method: "POST", body: "{}" });
  });
  $("#btnRefreshDoctor")?.addEventListener("click", refreshDoctor);
  $("#btnDoctorMini")?.addEventListener("click", () => setView("permissions"));

  // Local model save/probe
  async function saveLocal(provider) {
    const base = $(provider === "ollama" ? "#ollamaBase" : "#lmstudioBase")?.value;
    const model = $(provider === "ollama" ? "#ollamaModel" : "#lmstudioModel")?.value;
    await api("/api/local/settings", {
      method: "POST",
      body: JSON.stringify({ provider, base_url: base, model }),
    });
    await refreshDoctor();
  }
  $("#btnSaveOllama")?.addEventListener("click", () => saveLocal("ollama"));
  $("#btnSaveLmstudio")?.addEventListener("click", () => saveLocal("lmstudio"));
  $("#btnProbeOllama")?.addEventListener("click", async () => {
    const { data } = await api("/api/local/probe/ollama", { method: "POST", body: "{}" });
    state.local.ollama = data;
    await refreshDoctor();
  });
  $("#btnProbeLmstudio")?.addEventListener("click", async () => {
    const { data } = await api("/api/local/probe/lmstudio", { method: "POST", body: "{}" });
    state.local.lmstudio = data;
    await refreshDoctor();
  });

  // Telegram
  function tgMsg(text, ok) {
    setMsg($("#tgMsg"), text, ok);
  }
  $("#btnTgSave")?.addEventListener("click", async () => {
    const token = $("#tgToken")?.value || "";
    const allowed = $("#tgAllowed")?.value || "";
    const { data } = await api("/api/telegram/config", {
      method: "POST",
      body: JSON.stringify({ token, allowed_chat_ids: allowed }),
    });
    if (data.ok) {
      if ($("#tgToken")) $("#tgToken").value = "";
      tgMsg("Token saved.", true);
      refreshDoctor();
    } else {
      tgMsg(data.error || "Save failed", false);
    }
  });
  $("#btnTgStart")?.addEventListener("click", async () => {
    const { data } = await api("/api/telegram/start", { method: "POST", body: "{}" });
    tgMsg(data.ok ? "Bridge started." : data.error || "Start failed", !!data.ok);
    refreshDoctor();
  });
  $("#btnTgStop")?.addEventListener("click", async () => {
    await api("/api/telegram/stop", { method: "POST", body: "{}" });
    tgMsg("Bridge stopped.", true);
    refreshDoctor();
  });

  const input = $("#input");
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 140) + "px";
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      $("#composer").requestSubmit();
    }
  });

  $("#composer").addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    if (!anyBackend()) {
      showConnectModal();
      return;
    }
    input.value = "";
    input.style.height = "auto";
    state.messages.push({ role: "user", content: text });
    renderMessages();
    const sendBtn = $("#sendBtn");
    sendBtn.disabled = true;
    const provider = $("#providerSelect").value;
    // System prompt is built server-side: operator capability + SOUL.md + MEMORY.md.
    const payloadMessages = state.messages
      .filter((m) => m.role === "user" || m.role === "assistant")
      .map(({ role, content }) => ({ role, content }));
    try {
      const { data } = await api("/api/chat", {
        method: "POST",
        body: JSON.stringify({ provider, messages: payloadMessages }),
      });
      if (data.ok) {
        state.messages.push({ role: "assistant", content: data.content || "(empty reply)" });
      } else {
        if (data.need_key || data.need_oauth) showConnectModal();
        state.messages.push({
          role: "assistant",
          error: true,
          content: data.error || "Chat failed",
        });
      }
    } catch (err) {
      state.messages.push({ role: "assistant", error: true, content: String(err) });
    } finally {
      sendBtn.disabled = false;
      renderMessages();
    }
  });

  $("#btnEnsureCdp")?.addEventListener("click", async () => {
    const { data } = await api("/api/browser/ensure", { method: "POST", body: "{}" });
    $("#cdpOut").textContent = JSON.stringify(data, null, 2);
    refreshDoctor();
  });
  $("#btnListTabs")?.addEventListener("click", async () => {
    const { data } = await api("/api/browser/tabs");
    $("#cdpOut").textContent = JSON.stringify(data, null, 2);
  });
  $("#btnShot")?.addEventListener("click", async () => {
    const { data } = await api("/api/desktop/screenshot", { method: "POST", body: "{}" });
    $("#deskOut").textContent = JSON.stringify(
      { ok: data.ok, bytes: data.bytes, error: data.error, via: data.via },
      null,
      2
    );
    const img = $("#shotPreview");
    if (data.ok && data.b64) {
      img.src = `data:${data.mime};base64,${data.b64}`;
      img.hidden = false;
    }
  });
  $("#btnGoalDry")?.addEventListener("click", async () => {
    const { data } = await api("/api/desktop/goal", {
      method: "POST",
      body: JSON.stringify({ goal: "press 1", app: "Calculator", dry_run: true, max_steps: 1 }),
    });
    $("#deskOut").textContent = JSON.stringify(
      { ok: data.ok, exit_code: data.exit_code, stdout: data.stdout, stderr: data.stderr, error: data.error },
      null,
      2
    );
  });

  // Load local settings into inputs
  api("/api/local/settings").then(({ data }) => {
    if (data?.ollama) {
      if ($("#ollamaBase")) $("#ollamaBase").value = data.ollama.base_url || "";
      if ($("#ollamaModel")) $("#ollamaModel").value = data.ollama.model || "";
    }
    if (data?.lmstudio) {
      if ($("#lmstudioBase")) $("#lmstudioBase").value = data.lmstudio.base_url || "";
      if ($("#lmstudioModel")) $("#lmstudioModel").value = data.lmstudio.model || "";
    }
  });

  renderMessages();
  renderOauthCards();
  // Deep-link: ?view=permissions|settings|chat for demos / onboarding tours
  (() => {
    try {
      const v = new URLSearchParams(location.search).get("view");
      if (v && ["chat", "permissions", "settings"].includes(v)) setView(v);
    } catch (_) {}
  })();
  refreshDoctor().then(() => {
    // TypeSafe onboarding is separate from chat Connect.
    if (!hasTypesafe() && !state.skippedTypesafe) {
      setView("permissions");
      const step = $("#wizardTypesafe");
      if (step) step.scrollIntoView({ behavior: "smooth", block: "center" });
    } else if (!anyBackend() && !state.skippedConnect) {
      showConnectModal();
    }
  });
})();
