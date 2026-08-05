(() => {
  const form = document.getElementById("ticket-form");
  const intentInput = document.getElementById("intent");
  const titleInput = document.getElementById("title");
  const descriptionInput = document.getElementById("description");
  const parentKeyInput = document.getElementById("parent-key");
  const teamInput = document.getElementById("team");
  const submitBtn = document.getElementById("submit-btn");
  const suggestBtn = document.getElementById("suggest-btn");
  const feedback = document.getElementById("feedback");

  /** Jira issue key shape, e.g. ATL-25692 or PROJ2-1 */
  const PARENT_KEY_PATTERN = /^[A-Za-z][A-Za-z0-9]+-\d+$/;

  // Prefill Team (and Parent) from server env defaults when available.
  fetch("/api/health")
    .then((response) => (response.ok ? response.json() : null))
    .then((payload) => {
      if (!payload) {
        return;
      }
      if (payload.team_name && teamInput && !teamInput.dataset.userEdited) {
        teamInput.value = payload.team_name;
      }
      if (payload.parent_key && parentKeyInput && !parentKeyInput.value.trim()) {
        parentKeyInput.value = payload.parent_key;
      }
    })
    .catch(() => {
      /* keep HTML defaults */
    });

  if (teamInput) {
    teamInput.addEventListener("input", () => {
      teamInput.dataset.userEdited = "1";
    });
  }

  function showFeedback(type, html) {
    feedback.hidden = false;
    feedback.className = `feedback ${type}`;
    feedback.innerHTML = html;
  }

  function clearFeedback() {
    feedback.hidden = true;
    feedback.className = "feedback";
    feedback.textContent = "";
  }

  async function copyTextToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const helper = document.createElement("textarea");
    helper.value = text;
    helper.setAttribute("readonly", "");
    helper.style.position = "fixed";
    helper.style.left = "-9999px";
    document.body.appendChild(helper);
    helper.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(helper);
    if (!ok) {
      throw new Error("Clipboard copy failed");
    }
  }

  feedback.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy-url]");
    if (!button || !feedback.contains(button)) {
      return;
    }

    const url = button.getAttribute("data-copy-url") || "";
    if (!url) {
      return;
    }

    const label = button.querySelector(".copy-label") || button;
    const previous = label.textContent;
    try {
      await copyTextToClipboard(url);
      label.textContent = "Copied";
      button.classList.add("is-copied");
      window.setTimeout(() => {
        label.textContent = previous;
        button.classList.remove("is-copied");
      }, 1600);
    } catch {
      label.textContent = "Copy failed";
      window.setTimeout(() => {
        label.textContent = previous;
      }, 1600);
    }
  });

  function detailFromPayload(payload, fallback) {
    let detail = payload.detail || payload.error;
    if (Array.isArray(detail)) {
      detail = detail
        .map((item) => (typeof item === "string" ? item : item.msg || JSON.stringify(item)))
        .join("; ");
    }
    return String(detail || fallback);
  }

  function validateParentKey(value) {
    const key = value.trim();
    if (!key) {
      return { ok: true, value: "" };
    }
    if (!PARENT_KEY_PATTERN.test(key)) {
      return {
        ok: false,
        error:
          "Parent issue must look like PROJECT-123 (letters/digits, hyphen, then digits).",
      };
    }
    return { ok: true, value: key.toUpperCase() };
  }

  suggestBtn.addEventListener("click", async () => {
    clearFeedback();

    let intent = intentInput.value.trim();
    if (!intent) {
      // Fall back to existing title/description as the sketch
      const title = titleInput.value.trim();
      const description = descriptionInput.value.trim();
      intent = [title, description].filter(Boolean).join("\n\n");
    }

    if (!intent) {
      showFeedback("error", "Enter an intent sketch (or a title) before suggesting.");
      intentInput.focus();
      return;
    }

    suggestBtn.disabled = true;
    submitBtn.disabled = true;
    suggestBtn.textContent = "Suggesting…";

    try {
      const response = await fetch("/api/suggest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ intent }),
      });

      let payload = {};
      try {
        payload = await response.json();
      } catch {
        payload = {};
      }

      if (!response.ok) {
        showFeedback(
          "error",
          escapeHtml(detailFromPayload(payload, `Suggest failed (${response.status}).`))
        );
        return;
      }

      if (payload.title) {
        titleInput.value = payload.title;
      }
      if (typeof payload.description === "string") {
        descriptionInput.value = payload.description;
      }

      const samples = Number(payload.samples_used) || 0;
      const parent = payload.parent_key
        ? ` under ${escapeHtml(payload.parent_key)}`
        : "";
      showFeedback(
        "success",
        `Suggestion ready (inspired by ${samples} sample ticket${
          samples === 1 ? "" : "s"
        }${parent}). Review the fields, then create when ready.`
      );
      titleInput.focus();
    } catch (err) {
      showFeedback(
        "error",
        `Network error: ${escapeHtml(err.message || String(err))}`
      );
    } finally {
      suggestBtn.disabled = false;
      submitBtn.disabled = false;
      suggestBtn.textContent = "Suggest with AI";
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearFeedback();

    const title = titleInput.value.trim();
    const description = descriptionInput.value.trim();
    const team = teamInput.value.trim();
    const parentCheck = validateParentKey(parentKeyInput.value);

    if (!title) {
      showFeedback("error", "Please enter a ticket title.");
      titleInput.focus();
      return;
    }

    if (!parentCheck.ok) {
      showFeedback("error", escapeHtml(parentCheck.error));
      parentKeyInput.focus();
      return;
    }

    if (parentCheck.value) {
      parentKeyInput.value = parentCheck.value;
    }

    submitBtn.disabled = true;
    suggestBtn.disabled = true;
    submitBtn.textContent = "Creating…";

    try {
      const response = await fetch("/api/tickets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          description,
          parent_key: parentCheck.value || null,
          team: team || null,
        }),
      });

      let payload = {};
      try {
        payload = await response.json();
      } catch {
        payload = {};
      }

      if (!response.ok) {
        showFeedback(
          "error",
          escapeHtml(detailFromPayload(payload, `Request failed (${response.status}).`))
        );
        return;
      }

      const key = payload.key || "ticket";
      const url = payload.url;
      let html = `Ticket created: ${escapeHtml(key)}`;

      if (url) {
        const safeUrl = escapeAttr(url);
        html = `
          <p class="feedback-title">
            Ticket created:
            <a href="${safeUrl}" target="_blank" rel="noopener noreferrer">${escapeHtml(key)}</a>
          </p>
          <div class="ticket-link-row">
            <input
              class="ticket-url-input"
              type="text"
              readonly
              value="${safeUrl}"
              aria-label="Ticket URL"
            />
            <button type="button" class="btn-secondary copy-link-btn" data-copy-url="${safeUrl}">
              <span class="copy-label">Copy link</span>
            </button>
          </div>
        `;
      }

      showFeedback("success", html);
      intentInput.value = "";
      titleInput.value = "";
      descriptionInput.value = "";

      const urlInput = feedback.querySelector(".ticket-url-input");
      if (urlInput) {
        urlInput.focus();
        urlInput.select();
      } else {
        titleInput.focus();
      }
    } catch (err) {
      showFeedback(
        "error",
        `Network error: ${escapeHtml(err.message || String(err))}`
      );
    } finally {
      submitBtn.disabled = false;
      suggestBtn.disabled = false;
      submitBtn.textContent = "Create ticket";
    }
  });

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function escapeAttr(value) {
    return escapeHtml(value).replaceAll("'", "&#39;");
  }
})();
