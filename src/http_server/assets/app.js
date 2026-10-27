(function () {
  "use strict";

  const bootstrap = window.__OVERSTATS_UI_BOOTSTRAP__ || {};
  const modules = Array.isArray(bootstrap.modules) ? bootstrap.modules : [];
  const moduleMap = new Map(modules.map((item) => [item.id, item]));

  const MATCH_DETAIL_MODULE_ID = "dashen-match-detail";
  const SAMEPLAY_DETAIL_MODULE_ID = "dashen-sameplay-detail";
  const OW_GUESS_MODULE_ID = "ow-guess";
  const REPLY_BUNDLE_MODULE_IDS = new Set([
    MATCH_DETAIL_MODULE_ID,
    SAMEPLAY_DETAIL_MODULE_ID,
    OW_GUESS_MODULE_ID,
    "patch-notes",
  ]);

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
    patchNavigation: document.getElementById("patchNavigation"),
    imagePlaceholder: document.getElementById("imagePlaceholder"),
    replyPreview: document.getElementById("replyPreview"),
    replyPlaceholder: document.getElementById("replyPlaceholder"),
    replyMeta: document.getElementById("replyMeta"),
  };

  function getActiveModule() {
    return moduleMap.get(state.activeModuleId) || modules[0] || null;
  }

  function isReplyBundleModule(module) {
    return Boolean(module && REPLY_BUNDLE_MODULE_IDS.has(module.id));
  }

  function getEffectiveEndpoint(module) {
    if (!module) {
      return "";
    }
    if (module.id === "patch-notes") return "/api/v2/patch-notes/replies";
    if (isReplyBundleModule(module)) {
      return module.json_endpoint;
    }
    if (state.mode === "image" && module.image_endpoint) {
      return module.image_endpoint;
    }
    return module.json_endpoint;
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
    setReplyMeta("Available for OW guess and other reply bundle modules");
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

  function getReplyTitle(reply, module, imageIndex, imageTotal, textIndex, audioIndex) {
    if (!reply || typeof reply !== "object") {
      return "Reply";
    }
    const isOWGuessModule = Boolean(module && module.id === OW_GUESS_MODULE_ID);
    if (reply.type === "image") {
      if (isOWGuessModule) {
        return imageIndex === 0 ? "Question Image" : "Extra Image " + (imageIndex + 1);
      }
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
      if (isOWGuessModule) {
        return textIndex === 0 ? "Question Prompt" : "Extra Prompt " + (textIndex + 1);
      }
      return textIndex === 0 ? "Text Note" : "Extra Note " + (textIndex + 1);
    }
    if (reply.type === "audio") {
      if (isOWGuessModule) {
        return audioIndex === 0 ? "Question Audio" : "Extra Audio " + (audioIndex + 1);
      }
      return audioIndex === 0 ? "Audio Reply" : "Extra Audio " + (audioIndex + 1);
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

    const activeModule = getActiveModule();
    const displayReplies = replies.filter(
      (reply) => reply && (reply.type === "image" || reply.type === "text" || reply.type === "audio")
    );
    const imageReplies = displayReplies.filter((reply) => reply.type === "image");
    if (!displayReplies.length) {
      setReplyMeta("Replies were returned, but nothing displayable was found.");
      return;
    }

    let imageIndex = 0;
    let textIndex = 0;
    let audioIndex = 0;

    displayReplies.forEach((reply) => {
      const card = document.createElement("article");
      card.className = "reply-item";

      const head = document.createElement("div");
      head.className = "reply-item-head";

      const title = document.createElement("strong");
      title.className = "reply-item-title";
      title.textContent = getReplyTitle(reply, activeModule, imageIndex, imageReplies.length, textIndex, audioIndex);
      head.appendChild(title);

      const badge = document.createElement("span");
      badge.className = "reply-item-badge";
      if (reply.type === "image") {
        badge.textContent = reply.media_type || "image";
      } else if (reply.type === "audio") {
        badge.textContent = reply.media_type || "audio";
      } else {
        badge.textContent = "text";
      }
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
      } else if (reply.type === "audio") {
        try {
          const blob = base64ToBlob(reply.base64, reply.media_type);
          const audioUrl = URL.createObjectURL(blob);
          state.replyObjectUrls.push(audioUrl);

          const audio = document.createElement("audio");
          audio.className = "reply-audio";
          audio.controls = true;
          audio.preload = "metadata";
          audio.src = audioUrl;
          card.appendChild(audio);
        } catch (error) {
          const failure = document.createElement("pre");
          failure.className = "reply-text";
          failure.textContent = "Failed to decode audio reply: " + String(error && error.message ? error.message : error);
          card.appendChild(failure);
        }
        audioIndex += 1;
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
      } else if (field.control_type === "textarea") {
        control = document.createElement("textarea");
        control.rows = 5;
        control.maxLength = 32768;
        control.placeholder = field.placeholder || "";
        control.value = String(field.default || "");
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
        control.type = field.control_type === "number" ? "number" : (field.control_type === "password" ? "password" : "text");
        if (field.control_type === "password") control.autocomplete = "off";
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

  function collectDynamicPayload(includeSensitive = true) {
    const payload = {};
    const controls = elements.dynamicFields.querySelectorAll("[data-field-id]");
    controls.forEach((control) => {
      const payloadKey = control.dataset.payloadKey;
      if (!payloadKey) {
        return;
      }
      if (!includeSensitive && control.type === "password") {
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

  function buildBasePayload(includeSensitive = true) {
    const activeModule = getActiveModule();
    const payload = collectDynamicPayload(includeSensitive);
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
    // Keep credentials only in their password controls. Omit them instead of inserting
    // a masked placeholder, which the editable JSON overlay could send as a credential.
    elements.payloadEditor.value = formatJson(buildBasePayload(false));
    state.rawDirty = false;
  }

  function onBaseFieldChanged() {
    updateModuleHeader();
    syncRawPayload(false);
  }

  function renderPatchNavigation(reader) {
    const nav = elements.patchNavigation;
    nav.replaceChildren();
    nav.classList.toggle("hidden", !reader);
    if (!reader) return;
    const navigate = (request) => {
      if (!request || elements.submitButton.disabled) return;
      const payload = Object.assign({section: "", hero: "", page: 1}, request);
      elements.dynamicFields.querySelectorAll("[data-payload-key]").forEach((control) => {
        if (Object.prototype.hasOwnProperty.call(payload, control.dataset.payloadKey)) {
          control.value = payload[control.dataset.payloadKey];
        }
      });
      elements.payloadEditor.value = formatJson(payload);
      state.rawDirty = true;
      sendRequest({preventDefault() {}});
    };
    const status = document.createElement("span");
    status.textContent = (reader.view === "overview" ? "总览" : "正文") + " · " + reader.page + " / " + reader.page_count;
    nav.appendChild(status);
    [["总览", reader.overview_request], ["完整正文", reader.detail_request],
      ["上一页", reader.previous_request], ["下一页", reader.next_request]].forEach(([title, request]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = title;
      button.disabled = !request;
      button.addEventListener("click", () => navigate(request));
      nav.appendChild(button);
    });
    const select = document.createElement("select");
    const placeholder = document.createElement("option");
    placeholder.textContent = "跳转章节";
    placeholder.value = "";
    select.appendChild(placeholder);
    (reader.sections || []).forEach((section, index) => {
      const option = document.createElement("option");
      option.value = String(index);
      option.textContent = section.id + " · " + section.title;
      select.appendChild(option);
    });
    select.addEventListener("change", () => {
      if (select.value !== "") navigate(reader.sections[Number(select.value)].request);
    });
    nav.appendChild(select);
  }

  function render() {
    renderPatchNavigation(null);
    renderModuleNav();
    renderDynamicFields();
    updateTargetVisibility();
    updateModuleHeader();
    syncRawPayload(true);
  }

  async function sendRequest(event) {
    event.preventDefault();
    if (elements.submitButton.disabled) return;
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
    renderPatchNavigation(null);

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
      if (activeModule.id === "patch-notes" && response.ok) renderPatchNavigation(parsedBody.reader);

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
