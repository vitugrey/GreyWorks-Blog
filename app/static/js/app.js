(() => {
  "use strict";

  const VIEW_STORAGE_KEY = "gw_blog_view_mode";

  function applyViewMode(mode, persist) {
    const resolved = mode === "lista" ? "lista" : "grade";
    const collections = document.querySelectorAll(".posts-collection");
    collections.forEach((el) => {
      el.classList.toggle("is-list", resolved === "lista");
      el.classList.toggle("is-grid", resolved === "grade");
    });

    const buttons = document.querySelectorAll("[data-view-toggle]");
    buttons.forEach((btn) => {
      const active = btn.getAttribute("data-view-toggle") === resolved;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });

    if (persist) {
      try {
        window.localStorage.setItem(VIEW_STORAGE_KEY, resolved);
      } catch (_err) {
        // Ignore storage errors in restricted browser modes
      }
      const url = new URL(window.location.href);
      url.searchParams.set("view", resolved);
      window.history.replaceState({}, "", url.toString());
    }
  }

  function initViewToggle() {
    const buttons = document.querySelectorAll("[data-view-toggle]");
    if (!buttons.length) return;

    const url = new URL(window.location.href);
    const queryView = url.searchParams.get("view");
    if (queryView === "lista" || queryView === "grade") {
      applyViewMode(queryView, false);
    } else {
      try {
        const saved = window.localStorage.getItem(VIEW_STORAGE_KEY);
        if (saved === "lista" || saved === "grade") {
          applyViewMode(saved, false);
        }
      } catch (_err) {
        // Ignore storage errors
      }
    }

    buttons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const targetMode = btn.getAttribute("data-view-toggle");
        applyViewMode(targetMode, true);
      });
    });
  }

  function initMobileMenu() {
    const toggle = document.getElementById("mobile-menu-toggle");
    const panel = document.getElementById("nav-collapse");
    if (!toggle || !panel) return;

    toggle.addEventListener("click", () => {
      const open = panel.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  function initSearchShortcut() {
    const input = document.getElementById("navbar-search-input");
    if (!input) return;

    document.addEventListener("keydown", (event) => {
      const tag = event.target && event.target.tagName ? event.target.tagName.toLowerCase() : "";
      if (tag === "input" || tag === "textarea" || tag === "select") {
        if (event.key === "Escape" && event.target === input) {
          input.blur();
        }
        return;
      }
      if (event.key === "/") {
        event.preventDefault();
        input.focus();
        input.select();
      }
    });
  }

  function initReadingProgress() {
    const bar = document.getElementById("reading-progress");
    const article = document.getElementById("article-content");
    if (!bar || !article) return;

    const update = () => {
      const rect = article.getBoundingClientRect();
      const total = Math.max(1, article.offsetHeight - window.innerHeight * 0.6);
      const passed = Math.min(Math.max(0, -rect.top), total);
      const pct = Math.min(100, Math.max(0, (passed / total) * 100));
      bar.style.width = `${pct.toFixed(1)}%`;
    };

    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update, { passive: true });
    update();
  }

  function initCopyCodeButtons() {
    const blocks = document.querySelectorAll(".prose pre");
    blocks.forEach((pre) => {
      const wrapper = document.createElement("div");
      wrapper.className = "code-block-wrap";
      pre.parentNode.insertBefore(wrapper, pre);
      wrapper.appendChild(pre);

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "copy-code-btn";
      btn.textContent = "Copiar";
      btn.addEventListener("click", async () => {
        const text = pre.textContent || "";
        try {
          await navigator.clipboard.writeText(text);
          btn.textContent = "Copiado";
          window.setTimeout(() => {
            btn.textContent = "Copiar";
          }, 1600);
        } catch (_err) {
          btn.textContent = "Erro";
          window.setTimeout(() => {
            btn.textContent = "Copiar";
          }, 1600);
        }
      });
      wrapper.appendChild(btn);
    });
  }

  function initDeleteModal() {
    const dialog = document.getElementById("delete-confirm-dialog");
    const titleSlot = document.getElementById("delete-dialog-title");
    const cancelBtn = document.getElementById("delete-dialog-cancel");
    const confirmBtn = document.getElementById("delete-dialog-confirm");
    if (!dialog || !titleSlot || !cancelBtn || !confirmBtn) return;

    let activeForm = null;

    document.querySelectorAll("[data-delete-trigger]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const formId = btn.getAttribute("data-form-id");
        const postTitle = btn.getAttribute("data-post-title") || "este artigo";
        activeForm = formId ? document.getElementById(formId) : null;
        titleSlot.textContent = postTitle;
        if (typeof dialog.showModal === "function") {
          dialog.showModal();
        }
      });
    });

    cancelBtn.addEventListener("click", () => {
      activeForm = null;
      dialog.close();
    });

    confirmBtn.addEventListener("click", () => {
      if (activeForm) {
        activeForm.submit();
      }
      dialog.close();
    });
  }

  function initImageUploader() {
    const button = document.getElementById("editor-image-btn");
    const fileInput = document.getElementById("editor-image-input");
    const textarea = document.getElementById("post-content");
    const statusEl = document.getElementById("editor-image-status");
    if (!button || !fileInput || !textarea || !statusEl) return;

    button.addEventListener("click", () => {
      fileInput.click();
    });

    fileInput.addEventListener("change", async () => {
      const file = fileInput.files && fileInput.files[0];
      if (!file) return;

      const csrfToken = fileInput.getAttribute("data-csrf-token") || "";
      const formData = new FormData();
      formData.append("image", file);
      formData.append("alt", file.name.replace(/\.[^.]+$/, ""));
      formData.append("csrf_token", csrfToken);

      button.disabled = true;
      statusEl.textContent = "Enviando imagem...";
      statusEl.classList.remove("is-error");

      try {
        const resp = await fetch("/admin/media/upload", {
          method: "POST",
          body: formData,
          credentials: "same-origin",
        });
        const data = await resp.json();
        if (!resp.ok) {
          throw new Error(data.detail || "Falha ao enviar imagem.");
        }

        const snippet = `\n${data.markdown}\n`;
        const start = textarea.selectionStart ?? textarea.value.length;
        const end = textarea.selectionEnd ?? textarea.value.length;
        textarea.value =
          textarea.value.slice(0, start) + snippet + textarea.value.slice(end);
        const cursor = start + snippet.length;
        textarea.focus();
        textarea.setSelectionRange(cursor, cursor);
        statusEl.textContent = "Imagem inserida!";
      } catch (err) {
        statusEl.textContent = err instanceof Error ? err.message : "Erro no upload.";
        statusEl.classList.add("is-error");
      } finally {
        button.disabled = false;
        fileInput.value = "";
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initViewToggle();
    initMobileMenu();
    initSearchShortcut();
    initReadingProgress();
    initCopyCodeButtons();
    initDeleteModal();
    initImageUploader();
  });
})();
