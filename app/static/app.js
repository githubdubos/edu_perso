(() => {
  const form = document.getElementById("ticket-form");
  const titleInput = document.getElementById("title");
  const descriptionInput = document.getElementById("description");
  const submitBtn = document.getElementById("submit-btn");
  const feedback = document.getElementById("feedback");

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

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearFeedback();

    const title = titleInput.value.trim();
    const description = descriptionInput.value.trim();

    if (!title) {
      showFeedback("error", "Please enter a ticket title.");
      titleInput.focus();
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = "Creating…";

    try {
      const response = await fetch("/api/tickets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, description }),
      });

      let payload = {};
      try {
        payload = await response.json();
      } catch {
        payload = {};
      }

      if (!response.ok) {
        let detail = payload.detail || payload.error;
        if (Array.isArray(detail)) {
          detail = detail
            .map((item) => (typeof item === "string" ? item : item.msg || JSON.stringify(item)))
            .join("; ");
        }
        showFeedback(
          "error",
          escapeHtml(String(detail || `Request failed (${response.status}).`))
        );
        return;
      }

      const key = payload.key || "ticket";
      const url = payload.url;
      const link = url
        ? `<a href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(key)}</a>`
        : escapeHtml(key);

      showFeedback("success", `Ticket created: ${link}`);
      titleInput.value = "";
      descriptionInput.value = "";
      titleInput.focus();
    } catch (err) {
      showFeedback(
        "error",
        `Network error: ${escapeHtml(err.message || String(err))}`
      );
    } finally {
      submitBtn.disabled = false;
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
