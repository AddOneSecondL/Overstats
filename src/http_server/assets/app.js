(function () {
  "use strict";

  const bootstrap = window.__OVERSTATS_UI_BOOTSTRAP__ || {};
  const modules = Array.isArray(bootstrap.modules) ? bootstrap.modules : [];
  const moduleMap = new Map(modules.map((item) => [item.id, item]));

  const MATCH_DETAIL_MODULE_ID = "dashen-match-detail";
  const SAMEPLAY_DETAIL_MODULE_ID = "dashen-sameplay-detail";

  const state = {
    activeModuleId: bootstrap.default_module_id || (modules[0] && modules[0].id) || "",
    mode: "json",
    rawDirty: false,
    imageObjectUrl: "",
    replyObjectUrls: [],
  };

  const elements = {
    moduleNav: document.getElementById("moduleNav"),
    moduleTitle: document.getElementById("moduleTitle"),
    moduleDescription: document.getElementById("moduleDescription"),
    activeEndpoint: document.getElementById("activeEndpoint"),
    modeSelect: document.getElementById("modeSelect"),
    targetTypeField: document.getElementById("targetTypeField"),
    targetValueField: document.getElementById("targetValueField"),
    targetTypeSelect: document.getElementById("targetTypeSelect"),
    targetValueInput: document.getElementById("targetValueInput"),
    dynamicFields: document.getElementById("dynamicFields"),
    payloadEditor: document.getElementById("payloadEditor"),
    requestForm: document.getElementById("requestForm"),
    submitButton: document.getElementById("submitButton"),
    resetJsonButton: document.getElementById("resetJsonButton"),
    requestStatus: document.getElementById("requestStatus"),
    responseMeta: document.getElementById("responseMeta"),
    jsonPreview: document.getElementById("jsonPreview"),
    imagePreview: document.getElementById("imagePreview"),
    imagePlaceholder: document.getElementById("imagePlaceholder"),
    replyPreview: document.getElementById("replyPreview"),
    replyPlaceholder: document.getElementById("replyPlaceholder"),
    replyMeta: document.getElementById("replyMeta"),
  };

  function getActiveModule() {
    return moduleMap.get(state.activeModuleId) || modules[0] || null;
  }

  function isReplyBundleModule(module) {
    return Boolean(
      module && (module.id === MATCH_DETAIL_MODULE_ID || module.id === SAMEPLAY_DETAIL_MODULE_ID)
    );
  }

  function getEffectiveEndpoint(module) {
    if (!module) {
      return "";
    }
    if (isReplyBundleModule(module)) {
      return module.json_endpoint;
    }
    return state.mode === "image" ? module.image_endpoint : module.json_endpoint;
  }

  function formatJson(value) {
    return JSON.stringify(value, null, 2);
  }

  function setStatus(message) {
    elements.requestStatus.textContent = message;
  }

  function setResponseMeta(message) {
    elements.responseMeta.textContent = message;
  }

  function setReplyMeta(message) {
    elements.replyMeta.textContent = message;
  }

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function revokeUrl(url) {
    if (!url) {
      return;
    }
    try {
      URL.revokeObjectURL(url);
    } catch (_error) {
      // Ignore invalid blob URLs.
    }
  }

  function clearImagePreview() {
    revokeUrl(state.imageObjectUrl);
    state.imageObjectUrl = "";
    elements.imagePreview.src = "";
    elements.imagePreview.classList.add("hidden");
    elements.imagePlaceholder.classList.remove("hidden");
  }

  function clearReplyPreview() {
    state.replyObjectUrls.forEach(revokeUrl);
    state.replyObjectUrls = [];
    elements.replyPreview.innerHTML = "";
    elements.replyPreview.classList.add("hidden");
    elements.replyPlaceholder.classList.remove("hidden");
    setReplyMeta("Available for reply bundle modules");
  }

  function showImagePreview(blob) {
    clearImagePreview();
    state.imageObjectUrl = URL.createObjectURL(blob);
    elements.imagePreview.src = state.imageObjectUrl;
    elements.imagePreview.classList.remove("hidden");
    elements.imagePlaceholder.classList.add("hidden");
  }

  function sanitizePreviewData(value, key) {
    if (Array.isArray(value)) {
      return value.map((item) => sanitizePreviewData(item, ""));
    }
    if (value && typeof value === "object") {
      const output = {};
      Object.keys(value).forEach((childKey) => {
        output[childKey] = sanitizePreviewData(value[childKey], childKey);
      });
      return output;
    }
    if (typeof value === "string" && key === "base64") {
      return "[base64 image omitted: " + value.length + " chars]";
    }
    return value;
  }

  function base64ToBlob(base64Text, mediaType) {
    const binary = window.atob(String(base64Text || ""));
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return new Blob([bytes], {
      type: mediaType || "application/octet-stream",
    });
  }

  function extractFirstImageReply(replies) {
    if (!Array.isArray(replies)) {
      return null;
    }
    return replies.find((reply) => reply && reply.type === "image" && reply.base64) || null;
  }

  function showReplyImagePreview(reply) {
    if (!reply || reply.type !== "image") {
      clearImagePreview();
      return;
    }
    try {
      const blob = base64ToBlob(reply.base64, reply.media_type);
      showImagePreview(blob);
    } catch (_error) {
      clearImagePreview();
    }
  }

  function getReplyTitle(reply, imageIndex, imageTotal, textIndex) {
    if (!reply || typeof reply !== "object") {
      return "Reply";
    }
    if (reply.type === "image") {
      if (imageIndex === 0) {
        return "Main Panel";
      }
      if (imageTotal >= 3 && imageIndex === 1) {
        return "Detailed Info";
      }
      if (imageTotal >= 3 && imageIndex === 2) {
        return "AI Summary";
      }
      if (imageTotal === 2 && imageIndex === 1) {
        return "Detailed Info";
      }
      return "Extra Image " + (imageIndex + 1);
    }
    if (reply.type === "text") {
      return textIndex === 0 ? "Text Note" : "Extra Note " + (textIndex + 1);
    }
    if (reply.type === "meta") {
      return "Context";
    }
    return "Reply";
  }

  function renderReplyPreview(replies) {
    clearReplyPreview();
    if (!Array.isArray(replies) || !replies.length) {
      return;
    }

    const displayReplies = replies.filter((reply) => reply && (reply.type === "image" || reply.type === "text"));
    const imageReplies = displayReplies.filter((reply) => reply.type === "image");
    if (!displayReplies.length) {
      setReplyMeta("Replies were returned, but nothing displayable was found.");
      return;
    }

    let imageIndex = 0;
    let textIndex = 0;

    displayReplies.forEach((reply) => {
      const card = document.createElement("article");
      card.className = "reply-item";

      const head = document.createElement("div");
      head.className = "reply-item-head";

      const title = document.createElement("strong");
      title.className = "reply-item-title";
      title.textContent = getReplyTitle(reply, imageIndex, imageReplies.length, textIndex);
      head.appendChild(title);

      const badge = document.createElement("span");
      badge.className = "reply-item-badge";
      badge.textContent = reply.type === "image" ? (reply.media_type || "image") : "text";
      head.appendChild(badge);

      card.appendChild(head);

      if (reply.type === "image") {
        try {
          const blob = base64ToBlob(reply.base64, reply.media_type);
          const imageUrl = URL.createObjectURL(blob);
          state.replyObjectUrls.push(imageUrl);

          const image = document.createElement("img");
          image.className = "reply-image";
          image.src = imageUrl;
          image.alt = title.textContent;
          card.appendChild(image);
        } catch (error) {
          const failure = document.createElement("pre");
          failure.className = "reply-text";
          failure.textContent = "Failed to decode image reply: " + String(error && error.message ? error.message : error);
          card.appendChild(failure);
        }
        imageIndex += 1;
      } else if (reply.type === "text") {
        const text = document.createElement("pre");
        text.className = "reply-text";
        text.textContent = String(reply.data || "");
        card.appendChild(text);
        textIndex += 1;
      }

      elements.replyPreview.appendChild(card);
    });

    elements.replyPreview.classList.remove("hidden");
    elements.replyPlaceholder.classList.add("hidden");
    setReplyMeta("Expanded " + displayReplies.length + " replies");
  }

  function renderModuleNav() {
    elements.moduleNav.innerHTML = "";
    modules.forEach((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "module-button" + (item.id === state.activeModuleId ? " is-active" : "");
      button.innerHTML = "<strong>" + escapeHtml(item.title) + "</strong><span>" + escapeHtml(item.description) + "</span>";
      button.addEventListener("click", function () {
        if (state.activeModuleId === item.id) {
          return;
        }
        state.activeModuleId = item.id;
        state.rawDirty = false;
        clearImagePreview();
        clearReplyPreview();
        render();
      });
      elements.moduleNav.appendChild(button);
    });
  }

  function renderDynamicFields() {
    const activeModule = getActiveModule();
    elements.dynamicFields.innerHTML = "";
    if (!activeModule) {
      return;
    }

    activeModule.fields.forEach((field) => {
      const label = document.createElement("label");
      label.className = "field";

      const title = document.createElement("span");
      title.textContent = field.label;
      label.appendChild(title);

      let control;
      if (field.control_type === "checkbox") {
        control = document.createElement("input");
        control.type = "checkbox";
        control.checked = Boolean(field.default);
      } else if (field.control_type === "select") {
        control = document.createElement("select");
        field.options.forEach((option) => {
          const optionNode = document.createElement("option");
          optionNode.value = option.value;
          optionNode.textContent = option.label;
          if (option.value === field.default) {
            optionNode.selected = true;
          }
          control.appendChild(optionNode);
        });
      } else {
        control = document.createElement("input");
        control.type = field.control_type === "number" ? "number" : "text";
        control.placeholder = field.placeholder || "";
        control.value = field.default === null || field.default === undefined ? "" : String(field.default);
      }

      control.dataset.fieldId = field.id;
      control.dataset.payloadKey = field.payload_key;
      control.addEventListener("input", onBaseFieldChanged);
      control.addEventListener("change", onBaseFieldChanged);
      label.appendChild(control);

      if (field.help_text) {
        const hint = document.createElement("small");
        hint.textContent = field.help_text;
        label.appendChild(hint);
      }

      elements.dynamicFields.appendChild(label);
    });
  }

  function updateTargetVisibility() {
    const activeModule = getActiveModule();
    const visible = Boolean(activeModule && activeModule.requires_target);
    elements.targetTypeField.classList.toggle("hidden", !visible);
    elements.targetValueField.classList.toggle("hidden", !visible);
  }

  function updateModuleHeader() {
    const activeModule = getActiveModule();
    if (!activeModule) {
      elements.moduleTitle.textContent = "Module Not Found";
      elements.moduleDescription.textContent = "";
      elements.activeEndpoint.textContent = "";
      return;
    }
    elements.moduleTitle.textContent = activeModule.title;
    elements.moduleDescription.textContent = activeModule.description;
    elements.activeEndpoint.textContent = getEffectiveEndpoint(activeModule);
  }

  function collectDynamicPayload() {
    const payload = {};
    const controls = elements.dynamicFields.querySelectorAll("[data-field-id]");
    controls.forEach((control) => {
      const payloadKey = control.dataset.payloadKey;
      if (!payloadKey) {
        return;
      }
      if (control.type === "checkbox") {
        payload[payloadKey] = Boolean(control.checked);
        return;
      }
      const rawValue = String(control.value || "").trim();
      if (!rawValue) {
        return;
      }
      payload[payloadKey] = rawValue;
    });
    return payload;
  }

  function normalizeTargetValue(value) {
    return String(value || "").replace(/＃/g, "#").trim();
  }

  function buildBasePayload() {
    const activeModule = getActiveModule();
    const payload = collectDynamicPayload();
    if (activeModule && activeModule.requires_target) {
      const targetKey = elements.targetTypeSelect.value || activeModule.default_target_key || "bnet_id";
      const targetValue = normalizeTargetValue(elements.targetValueInput.value);
      if (targetValue) {
        payload[targetKey] = targetValue;
      }
    }
    return payload;
  }

  function syncRawPayload(force) {
    if (state.rawDirty && !force) {
      return;
    }
    elements.payloadEditor.value = formatJson(buildBasePayload());
    state.rawDirty = false;
  }

  function onBaseFieldChanged() {
    updateModuleHeader();
    syncRawPayload(false);
  }

  function render() {
    renderModuleNav();
    renderDynamicFields();
    updateTargetVisibility();
    updateModuleHeader();
    syncRawPayload(true);
  }

  async function sendRequest(event) {
    event.preventDefault();
    const activeModule = getActiveModule();
    if (!activeModule) {
      setStatus("No module available");
      return;
    }

    const basePayload = buildBasePayload();
    let overlayPayload = {};
    const rawText = String(elements.payloadEditor.value || "").trim();
    if (rawText) {
      try {
        overlayPayload = JSON.parse(rawText);
      } catch (error) {
        setStatus("Raw JSON parse failed");
        elements.jsonPreview.textContent = formatJson({
          ok: false,
          error: "invalid_local_json",
          message: String(error && error.message ? error.message : error),
        });
        clearImagePreview();
        clearReplyPreview();
        return;
      }
    }

    const payload = Object.assign({}, basePayload, overlayPayload);
    const endpoint = getEffectiveEndpoint(activeModule);

    setStatus("Request in progress...");
    setResponseMeta("Requesting " + endpoint);
    elements.submitButton.disabled = true;

    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json; charset=utf-8",
        },
        body: JSON.stringify(payload),
      });
      const contentType = String(response.headers.get("Content-Type") || "").toLowerCase();
      setResponseMeta(response.status + " | " + contentType);

      if (contentType.startsWith("image/")) {
        const blob = await response.blob();
        showImagePreview(blob);
        clearReplyPreview();
        if (response.ok) {
          setStatus("Image request succeeded");
        } else {
          setStatus("Image response returned an error status");
        }
        return;
      }

      const textBody = await response.text();
      let parsedBody = null;
      try {
        parsedBody = textBody ? JSON.parse(textBody) : null;
      } catch (_error) {
        parsedBody = {
          raw_text: textBody,
        };
      }

      elements.jsonPreview.textContent = formatJson(sanitizePreviewData(parsedBody, ""));

      if (parsedBody && Array.isArray(parsedBody.replies)) {
        renderReplyPreview(parsedBody.replies);
        if (state.mode === "image" && isReplyBundleModule(activeModule)) {
          showReplyImagePreview(extractFirstImageReply(parsedBody.replies));
        } else {
          clearImagePreview();
        }
      } else {
        clearReplyPreview();
        clearImagePreview();
      }

      if (response.ok) {
        if (isReplyBundleModule(activeModule)) {
          setStatus("Reply bundle loaded");
        } else {
          setStatus("JSON request succeeded");
        }
      } else {
        setStatus("Request failed, error JSON shown");
      }
    } catch (error) {
      clearImagePreview();
      clearReplyPreview();
      elements.jsonPreview.textContent = formatJson({
        ok: false,
        error: "network_error",
        message: String(error && error.message ? error.message : error),
      });
      setResponseMeta("Network error");
      setStatus("Request failed");
    } finally {
      elements.submitButton.disabled = false;
    }
  }

  elements.modeSelect.addEventListener("change", function () {
    state.mode = elements.modeSelect.value || "json";
    updateModuleHeader();
  });
  elements.targetTypeSelect.addEventListener("change", onBaseFieldChanged);
  elements.targetValueInput.addEventListener("input", onBaseFieldChanged);
  elements.payloadEditor.addEventListener("input", function () {
    state.rawDirty = true;
  });
  elements.resetJsonButton.addEventListener("click", function () {
    syncRawPayload(true);
    setStatus("JSON reset from form");
  });
  elements.requestForm.addEventListener("submit", sendRequest);

  render();
})();
