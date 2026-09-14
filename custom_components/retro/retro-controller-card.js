/**
 * Retro Controller Card — Custom Lovelace card for the Retro Gaming integration.
 * Shows adapter status, profile selector, quick-switch buttons, and mapping viewer/editor.
 *
 * Bundled with custom_components/retro/ and auto-registered on setup.
 */

// Source controller button name maps (BlueRetro generic IDs 0-29)
const SRC_CONTROLLERS = {
  ps5: {
    label: "PS5 DualSense",
    names: {
      0: "Left Stick X", 1: "Left Stick Y", 2: "Right Stick X", 3: "Right Stick Y",
      4: "L Stick X→Btn", 5: "L Stick Y→Btn", 6: "R Stick X→Btn", 7: "R Stick Y→Btn",
      8: "D-pad Left", 9: "D-pad Right", 10: "D-pad Down", 11: "D-pad Up",
      12: "L3 Left", 13: "L3 Right", 14: "L3 Down", 15: "L3 Up",
      16: "Square", 17: "Circle", 18: "Cross", 19: "Triangle",
      20: "Start", 21: "Select", 24: "L2", 25: "L1", 28: "R2", 29: "R1",
    },
  },
  xbox: {
    label: "Xbox Controller",
    names: {
      0: "Left Stick X", 1: "Left Stick Y", 2: "Right Stick X", 3: "Right Stick Y",
      4: "L Stick X→Btn", 5: "L Stick Y→Btn", 6: "R Stick X→Btn", 7: "R Stick Y→Btn",
      8: "D-pad Left", 9: "D-pad Right", 10: "D-pad Down", 11: "D-pad Up",
      12: "L3 Left", 13: "L3 Right", 14: "L3 Down", 15: "L3 Up",
      16: "X", 17: "B", 18: "A", 19: "Y",
      20: "Menu", 21: "View", 24: "LT", 25: "LB", 28: "RT", 29: "RB",
    },
  },
  switch_pro: {
    label: "Switch Pro",
    names: {
      0: "Left Stick X", 1: "Left Stick Y", 2: "Right Stick X", 3: "Right Stick Y",
      4: "L Stick X→Btn", 5: "L Stick Y→Btn", 6: "R Stick X→Btn", 7: "R Stick Y→Btn",
      8: "D-pad Left", 9: "D-pad Right", 10: "D-pad Down", 11: "D-pad Up",
      12: "L3 Left", 13: "L3 Right", 14: "L3 Down", 15: "L3 Up",
      16: "Y", 17: "A", 18: "B", 19: "X",
      20: "+", 21: "-", 24: "ZL", 25: "L", 28: "ZR", 29: "R",
    },
  },
};

// N64 destination button names for dropdown editor
const DST_BUTTONS_N64 = [
  { id: 0, name: "Stick X" }, { id: 1, name: "Stick Y" },
  { id: 2, name: "Stick X (alt)" }, { id: 3, name: "Stick Y (alt)" },
  { id: 8, name: "D-pad Left" }, { id: 9, name: "D-pad Right" },
  { id: 10, name: "D-pad Down" }, { id: 11, name: "D-pad Up" },
  { id: 12, name: "C-Left" }, { id: 13, name: "C-Right" },
  { id: 14, name: "C-Down" }, { id: 15, name: "C-Up" },
  { id: 16, name: "B" }, { id: 18, name: "A" },
  { id: 20, name: "Start" }, { id: 24, name: "Z" },
  { id: 25, name: "L" }, { id: 29, name: "R" },
];

class RetroControllerCard extends HTMLElement {
  static getStubConfig() {
    return { entity: "", title: "", entry_id: "" };
  }

  // HA 2026.6+ validates custom card keys; undeclared fields show "Configuration error".
  static getConfigForm() {
    return {
      schema: [
        {
          name: "entity",
          required: true,
          selector: { entity: { domain: "select" } },
        },
        { name: "title", selector: { text: {} } },
        { name: "entry_id", selector: { text: {} } },
      ],
      assertConfig: (config) => {
        if (config.entity && typeof config.entity !== "string") {
          throw new Error("entity must be a string");
        }
      },
    };
  }

  get hass() {
    return this._hass;
  }

  // hui-card (2026.6+) assigns these; define setters so assignment never throws.
  set preview(_val) {}
  set layout(_val) {}

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    // Skip re-render while editing to prevent dropdowns from closing
    if (this._editMode || this.querySelector("select:focus")) return;
    try {
      this._render();
    } catch (err) {
      console.error("retro-controller-card render failed", err);
      this._renderError(err);
    }
  }

  setConfig(config) {
    this._config = config || {};
    if (!this._config.entity) {
      this._renderError(new Error("Please define a profile select entity (select.*_profile)"));
      return;
    }
    this._entityId = config.entity;

    // Derive related entities: select.<base>_profile -> sensor.<base>_status, etc.
    const match = this._entityId.match(/^select\.(.+)_profile$/);
    this._baseName = match ? match[1] : "unknown";
    this._statusEntity = `sensor.${this._baseName}_status`;
    this._firmwareEntity = `sensor.${this._baseName}_firmware`;
    this._backupEntity = `button.${this._baseName}_backup_config`;
    this._refreshEntity = `button.${this._baseName}_refresh`;
    this._saveProfileEntity = `button.${this._baseName}_save_profile`;
    this._factoryResetEntity = `button.${this._baseName}_factory_reset`;
    this._showMappings = false;
    this._editMode = false;
    this._pendingEdits = {};
    this._srcController = "ps5"; // default source controller for label display
  }

  _renderError(err) {
    const msg = err?.message || String(err);
    this.innerHTML = `<ha-card><div class="warning">Retro card error: ${msg}</div></ha-card>`;
  }

  _render() {
    if (!this._hass || !this._config) return;

    const profileState = this._hass.states[this._entityId];
    const statusState = this._hass.states[this._statusEntity];
    const fwState = this._hass.states[this._firmwareEntity];

    if (!profileState) {
      this.innerHTML = `<ha-card><div class="warning">Entity not found: ${this._entityId}</div></ha-card>`;
      return;
    }

    const currentProfile = profileState.state || "unknown";
    const rawOptions = profileState.attributes?.options;
    const options = Array.isArray(rawOptions) ? rawOptions : [];
    const status = statusState ? statusState.state : "unknown";
    const firmware = fwState ? fwState.state : "?";
    const connected = status === "connected";
    const title = this._config.title || `${this._baseName.replace(/_/g, " ").toUpperCase()} Adapter`;
    const rawMappings = statusState?.attributes?.mappings;
    const mappings = Array.isArray(rawMappings) ? rawMappings : [];

    const profileIcons = {
      default: "mdi:gamepad",
      goldeneye: "mdi:pistol",
      goldeneye_solitaire: "mdi:pistol",
      mario_kart: "mdi:go-kart",
      smash_bros: "mdi:boxing-glove",
      zelda: "mdi:sword",
      perfect_dark: "mdi:pistol",
    };

    // Only show built-in profiles as big buttons (not custom ones)
    const builtInProfiles = options.filter((opt) => !opt.endsWith("(custom)"));
    const isCustomActive = currentProfile.endsWith("(custom)") || !builtInProfiles.includes(currentProfile);
    const displayProfile = isCustomActive ? "Manual" : currentProfile.replace(/_/g, " ");

    const profileButtons = builtInProfiles
      .map((opt) => {
        const icon = profileIcons[opt] || "mdi:gamepad-variant";
        const active = opt === currentProfile;
        const label = opt.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
        return `
          <button class="profile-btn ${active ? "active" : ""}" data-profile="${opt}">
            <ha-icon icon="${icon}"></ha-icon>
            <span>${label}</span>
          </button>`;
      })
      .join("");

    // Profile select dropdown (all profiles including custom)
    const customProfiles = options.filter((opt) => opt.endsWith("(custom)"));
    const profileSelectOpts = options.map((opt) => {
      const label = opt.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
      return `<option value="${opt}" ${opt === currentProfile ? "selected" : ""}>${label}</option>`;
    }).join("");
    const hasCustomSelected = currentProfile.endsWith("(custom)");

    // Mapping table section
    const srcNames = SRC_CONTROLLERS[this._srcController]?.names || SRC_CONTROLLERS.ps5.names;
    const srcLabel = SRC_CONTROLLERS[this._srcController]?.label || "PS5";
    let mappingHtml = "";
    if (this._showMappings && mappings.length > 0) {
      const rows = mappings.map((m, idx) => {
        const pendingDst = this._pendingEdits[idx];
        const currentDst = pendingDst !== undefined ? pendingDst : m.dst;
        const changed = pendingDst !== undefined && pendingDst !== m.dst;
        const dstLabel = DST_BUTTONS_N64.find(b => b.id === currentDst);
        const dstName = dstLabel ? dstLabel.name : `Btn ${currentDst}`;
        // Use client-side source name based on picker (overrides backend's src_name)
        const srcName = srcNames[m.src] || `Btn ${m.src}`;

        if (this._editMode) {
          const opts = DST_BUTTONS_N64.map(o =>
            `<option value="${o.id}" ${o.id === currentDst ? "selected" : ""}>${o.name}</option>`
          ).join("");
          return `<tr class="${changed ? "changed" : ""}">
            <td class="src">${srcName}</td>
            <td class="arrow">\u2192</td>
            <td class="dst"><select data-idx="${idx}">${opts}</select></td>
            <td class="dz">${m.deadzone}</td>
          </tr>`;
        }
        return `<tr>
          <td class="src">${srcName}</td>
          <td class="arrow">\u2192</td>
          <td class="dst">${dstName}</td>
          <td class="dz">${m.deadzone}</td>
        </tr>`;
      }).join("");

      // Source controller picker options
      const srcPickerOpts = Object.entries(SRC_CONTROLLERS).map(([key, val]) =>
        `<option value="${key}" ${key === this._srcController ? "selected" : ""}>${val.label}</option>`
      ).join("");

      const hasPending = Object.keys(this._pendingEdits).length > 0;
      mappingHtml = `
        <div class="mapping-section">
          <div class="mapping-header">
            <span>Button Mappings (${mappings.length})</span>
            <div class="mapping-actions">
              ${this._editMode && hasPending
                ? '<button class="map-action-btn apply-btn" data-action="apply-edits"><ha-icon icon="mdi:check"></ha-icon> Apply</button>'
                : ""}
              <button class="map-action-btn" data-action="toggle-edit">
                <ha-icon icon="${this._editMode ? "mdi:close" : "mdi:pencil"}"></ha-icon>
                ${this._editMode ? "Cancel" : "Edit"}
              </button>
            </div>
          </div>
          <div class="src-picker-row">
            <label>Source Controller:</label>
            <select class="src-picker">${srcPickerOpts}</select>
          </div>
          <table class="mapping-table">
            <thead><tr><th>${srcLabel}</th><th></th><th>N64 Output</th><th>DZ</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>`;
    } else if (this._showMappings) {
      mappingHtml = `<div class="mapping-section"><p style="color:var(--secondary-text-color);text-align:center;">No mapping data — press Refresh while connected.</p></div>`;
    }

    this.innerHTML = `
      <ha-card>
        <div class="retro-card">
          <div class="header">
            <div class="title-row">
              <ha-icon icon="mdi:gamepad-variant"></ha-icon>
              <span class="title">${title}</span>
            </div>
            <div class="status-row">
              <span class="status-badge ${connected ? "connected" : "disconnected"}">
                <ha-icon icon="${connected ? "mdi:bluetooth-connect" : "mdi:bluetooth-off"}"></ha-icon>
                ${status}
              </span>
              <span class="firmware">FW: ${firmware}</span>
            </div>
          </div>

          <div class="current-profile">
            <span class="label">Active Profile</span>
            <span class="value${isCustomActive ? " manual" : ""}">${displayProfile}</span>
          </div>

          <div class="profile-grid">
            ${profileButtons}
          </div>

          <div class="profile-select-row">
            <label>Switch Profile:</label>
            <select class="profile-select">${profileSelectOpts}</select>
            ${hasCustomSelected ? '<button class="delete-profile-btn" title="Delete this custom profile"><ha-icon icon="mdi:delete"></ha-icon></button>' : ""}
          </div>

          <div class="actions">
            <button class="action-btn" data-action="backup">
              <ha-icon icon="mdi:content-save"></ha-icon> Backup
            </button>
            <button class="action-btn" data-action="save-profile">
              <ha-icon icon="mdi:content-save-plus"></ha-icon> Save Profile
            </button>
            <button class="action-btn" data-action="refresh">
              <ha-icon icon="mdi:refresh"></ha-icon> Refresh
            </button>
          </div>
          <div class="actions" style="margin-top:4px;">
            <button class="action-btn" data-action="factory-reset">
              <ha-icon icon="mdi:restart"></ha-icon> Factory Reset
            </button>
            <button class="action-btn" data-action="toggle-mappings">
              <ha-icon icon="${this._showMappings ? "mdi:chevron-up" : "mdi:chevron-down"}"></ha-icon>
              ${this._showMappings ? "Hide" : "Show"} Mappings
            </button>
          </div>

          ${mappingHtml}
        </div>
      </ha-card>

      <style>
        .retro-card { padding: 16px; font-family: var(--paper-font-body1_-_font-family, 'Roboto', sans-serif); }
        .header { margin-bottom: 16px; }
        .title-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
        .title-row .title { font-size: 1.2em; font-weight: 500; }
        .title-row ha-icon { color: var(--primary-color); }
        .status-row { display: flex; align-items: center; gap: 12px; font-size: 0.85em; }
        .status-badge {
          display: inline-flex; align-items: center; gap: 4px;
          padding: 2px 8px; border-radius: 12px; font-weight: 500; text-transform: capitalize;
        }
        .status-badge ha-icon { --mdc-icon-size: 14px; }
        .status-badge.connected { background: rgba(76,175,80,0.15); color: var(--label-badge-green,#4caf50); }
        .status-badge.disconnected { background: rgba(244,67,54,0.15); color: var(--label-badge-red,#f44336); }
        .firmware { color: var(--secondary-text-color); }
        .current-profile {
          display: flex; justify-content: space-between; align-items: center;
          padding: 8px 12px; background: var(--card-background-color, var(--primary-background-color));
          border: 1px solid var(--divider-color); border-radius: 8px; margin-bottom: 16px;
        }
        .current-profile .label { font-size: 0.85em; color: var(--secondary-text-color); text-transform: uppercase; letter-spacing: 0.5px; }
        .current-profile .value { font-weight: 500; text-transform: capitalize; color: var(--primary-color); }
        .current-profile .value.manual { color: var(--secondary-text-color); font-style: italic; }
        .profile-grid { display: grid; grid-template-columns: repeat(auto-fill,minmax(120px,1fr)); gap: 8px; margin-bottom: 12px; }
        .profile-select-row {
          display: flex; align-items: center; gap: 8px; margin-bottom: 16px; font-size: 0.85em;
        }
        .profile-select-row label { color: var(--secondary-text-color); white-space: nowrap; }
        .profile-select-row .profile-select {
          flex: 1; background: var(--card-background-color); color: var(--primary-text-color);
          border: 1px solid var(--divider-color); border-radius: 4px; padding: 6px 8px;
          font-size: 1em;
        }
        .delete-profile-btn {
          background: none; border: 1px solid var(--error-color, #db4437); border-radius: 4px;
          color: var(--error-color, #db4437); cursor: pointer; padding: 4px 6px;
          display: flex; align-items: center;
        }
        .delete-profile-btn:hover { background: rgba(219,68,55,0.1); }
        .delete-profile-btn ha-icon { --mdc-icon-size: 18px; }
        .profile-btn {
          display: flex; flex-direction: column; align-items: center; gap: 4px;
          padding: 12px 8px; border: 1px solid var(--divider-color); border-radius: 8px;
          background: var(--card-background-color, var(--primary-background-color));
          cursor: pointer; transition: all 0.2s; color: var(--primary-text-color); font-size: 0.8em;
        }
        .profile-btn:hover { border-color: var(--primary-color); background: rgba(var(--rgb-primary-color),0.05); }
        .profile-btn.active { border-color: var(--primary-color); background: rgba(var(--rgb-primary-color),0.12); font-weight: 600; }
        .profile-btn ha-icon { --mdc-icon-size: 24px; color: var(--primary-color); }
        .actions { display: flex; gap: 8px; }
        .action-btn {
          flex: 1; display: flex; align-items: center; justify-content: center; gap: 6px;
          padding: 8px; border: 1px solid var(--divider-color); border-radius: 8px;
          background: var(--card-background-color, var(--primary-background-color));
          cursor: pointer; color: var(--primary-text-color); font-size: 0.85em; transition: background 0.2s;
        }
        .action-btn:hover { background: rgba(var(--rgb-primary-color),0.05); }
        .action-btn ha-icon { --mdc-icon-size: 18px; }
        .warning { padding: 16px; color: var(--error-color,#db4437); }

        .mapping-section { margin-top: 16px; }
        .mapping-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-weight: 500; }
        .mapping-actions { display: flex; gap: 4px; }
        .map-action-btn {
          display: inline-flex; align-items: center; gap: 4px;
          padding: 4px 10px; border: 1px solid var(--divider-color); border-radius: 6px;
          background: var(--card-background-color); cursor: pointer; color: var(--primary-text-color); font-size: 0.8em;
        }
        .map-action-btn:hover { background: rgba(var(--rgb-primary-color),0.08); }
        .map-action-btn ha-icon { --mdc-icon-size: 16px; }
        .apply-btn { border-color: var(--label-badge-green,#4caf50); color: var(--label-badge-green,#4caf50); }
        .mapping-table { width: 100%; border-collapse: collapse; font-size: 0.85em; }
        .mapping-table th {
          text-align: left; padding: 4px 8px; border-bottom: 2px solid var(--divider-color);
          color: var(--secondary-text-color); font-size: 0.85em; text-transform: uppercase;
        }
        .mapping-table td { padding: 4px 8px; border-bottom: 1px solid var(--divider-color); }
        .mapping-table .src { color: var(--primary-text-color); }
        .mapping-table .arrow { color: var(--secondary-text-color); text-align: center; width: 24px; }
        .mapping-table .dst { color: var(--primary-color); font-weight: 500; }
        .mapping-table .dz { color: var(--secondary-text-color); text-align: right; width: 40px; }
        .mapping-table tr.changed td { background: rgba(255,193,7,0.1); }
        .mapping-table select {
          background: var(--card-background-color); color: var(--primary-text-color);
          border: 1px solid var(--divider-color); border-radius: 4px; padding: 2px 4px;
          font-size: 0.95em; width: 100%;
        }
        .src-picker-row {
          display: flex; align-items: center; gap: 8px; margin-bottom: 8px; font-size: 0.85em;
        }
        .src-picker-row label { color: var(--secondary-text-color); }
        .src-picker-row .src-picker {
          background: var(--card-background-color); color: var(--primary-text-color);
          border: 1px solid var(--divider-color); border-radius: 4px; padding: 4px 8px;
          font-size: 1em;
        }
      </style>
    `;

    // Bind click handlers
    this.querySelectorAll(".profile-btn").forEach((btn) => {
      btn.addEventListener("click", () => this._selectProfile(btn.dataset.profile));
    });
    this.querySelectorAll(".action-btn").forEach((btn) => {
      btn.addEventListener("click", () => this._handleAction(btn.dataset.action));
    });
    this.querySelectorAll(".map-action-btn").forEach((btn) => {
      btn.addEventListener("click", () => this._handleMapAction(btn.dataset.action));
    });
    this.querySelectorAll(".mapping-table select").forEach((sel) => {
      sel.addEventListener("change", (e) => {
        this._pendingEdits[parseInt(e.target.dataset.idx)] = parseInt(e.target.value);
        // Mark row as changed without re-rendering (preserves dropdown focus)
        const row = e.target.closest("tr");
        if (row) row.classList.add("changed");
        // Show/hide apply button
        const applyBtn = this.querySelector('.apply-btn');
        if (!applyBtn && Object.keys(this._pendingEdits).length > 0) {
          const actionsDiv = this.querySelector('.mapping-actions');
          if (actionsDiv) {
            const btn = document.createElement('button');
            btn.className = 'map-action-btn apply-btn';
            btn.dataset.action = 'apply-edits';
            btn.innerHTML = '<ha-icon icon="mdi:check"></ha-icon> Apply';
            btn.addEventListener("click", () => this._handleMapAction("apply-edits"));
            actionsDiv.insertBefore(btn, actionsDiv.firstChild);
          }
        }
      });
    });

    // Source controller picker
    const srcPicker = this.querySelector(".src-picker");
    if (srcPicker) {
      srcPicker.addEventListener("change", (e) => {
        this._srcController = e.target.value;
        this._render();
      });
    }

    // Profile select dropdown
    const profileSelect = this.querySelector(".profile-select");
    if (profileSelect) {
      profileSelect.addEventListener("change", (e) => {
        this._selectProfile(e.target.value);
      });
    }

    // Delete custom profile button
    const deleteBtn = this.querySelector(".delete-profile-btn");
    if (deleteBtn) {
      deleteBtn.addEventListener("click", () => this._deleteCurrentProfile());
    }
  }

  _selectProfile(profile) {
    this._hass.callService("select", "select_option", {
      entity_id: this._entityId,
      option: profile,
    });
  }

  _deleteCurrentProfile() {
    const entryId = this._config.entry_id;
    if (!entryId) {
      alert("Config entry ID not set — edit the card config to add entry_id.");
      return;
    }
    const profileState = this._hass.states[this._entityId];
    const current = profileState?.state;
    if (!current || !current.endsWith("(custom)")) return;

    // Convert display name back to storage key: "manual (custom)" → "custom_manual"
    const baseName = current.replace(/ \(custom\)$/, "").replace(/ /g, "_");
    const storageName = `custom_${baseName}`;

    if (!confirm(`Delete custom profile "${current}"?`)) return;

    this._hass.callService("retro", "delete_profile", {
      config_entry_id: entryId,
      name: storageName,
    });
    // Force re-render after backend updates the entity state
    setTimeout(() => this._render(), 1500);
  }

  _handleAction(action) {
    if (action === "toggle-mappings") {
      this._showMappings = !this._showMappings;
      this._editMode = false;
      this._pendingEdits = {};
      this._render();
      return;
    }
    if (action === "factory-reset") {
      if (!confirm("Factory reset will erase all mappings and restore identity passthrough. Continue?")) return;
    }
    const entityMap = {
      backup: this._backupEntity,
      refresh: this._refreshEntity,
      "save-profile": this._saveProfileEntity,
      "factory-reset": this._factoryResetEntity,
    };
    const entity = entityMap[action];
    if (entity) {
      this._hass.callService("button", "press", { entity_id: entity });
      // Force re-render after state-changing actions to update dropdown
      if (action === "save-profile" || action === "factory-reset") {
        setTimeout(() => this._render(), 3000);
      }
    }
  }

  _handleMapAction(action) {
    if (action === "toggle-edit") {
      this._editMode = !this._editMode;
      this._pendingEdits = {};
      this._render();
      return;
    }
    if (action === "apply-edits") {
      this._applyMappingEdits();
    }
  }

  _applyMappingEdits() {
    const entryId = this._config.entry_id;
    if (!entryId) {
      alert("Config entry ID not set — edit the card config to add entry_id.");
      return;
    }
    const statusState = this._hass.states[this._statusEntity];
    const rawMappings = statusState?.attributes?.mappings;
    const mappings = Array.isArray(rawMappings) ? rawMappings : [];
    if (mappings.length === 0) return;

    const newMappings = mappings.map((m, idx) => {
      const dst = this._pendingEdits[idx] !== undefined ? this._pendingEdits[idx] : m.dst;
      return {
        src_btn: m.src,
        dst_btn: dst,
        dst_id: 0,
        perc_max: m.max || 100,
        perc_threshold: 50,
        perc_deadzone: m.deadzone || 15,
        turbo: 0,
        algo: 0,
      };
    });

    this._hass.callService("retro", "set_mapping", {
      config_entry_id: entryId,
      mappings: newMappings,
    });

    this._editMode = false;
    this._pendingEdits = {};
    setTimeout(() => {
      this._hass.callService("button", "press", { entity_id: this._refreshEntity });
    }, 5000);
  }

  getCardSize() {
    return this._showMappings ? 10 : 4;
  }

  getGridOptions() {
    return {
      columns: 6,
      rows: this._showMappings ? 10 : 4,
      min_columns: 6,
      min_rows: 4,
    };
  }
}

// Card editor
class RetroControllerCardEditor extends HTMLElement {
  set hass(hass) { this._hass = hass; }

  setConfig(config) {
    this._config = config;
    this._render();
  }

  _render() {
    this.innerHTML = `
      <div style="padding:16px;">
        <ha-textfield label="Profile Select Entity" value="${this._config.entity || ""}" style="width:100%"></ha-textfield>
        <ha-textfield label="Title (optional)" value="${this._config.title || ""}" style="width:100%;margin-top:8px;"></ha-textfield>
        <ha-textfield label="Config Entry ID (for editing)" value="${this._config.entry_id || ""}" style="width:100%;margin-top:8px;"></ha-textfield>
      </div>
    `;
    this.querySelectorAll("ha-textfield").forEach((field) => {
      field.addEventListener("change", (e) => {
        const lbl = e.target.label.toLowerCase();
        let key = "entity";
        if (lbl.includes("title")) key = "title";
        else if (lbl.includes("entry")) key = "entry_id";
        this._config = { ...this._config, [key]: e.target.value };
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config } }));
      });
    });
  }
}

customElements.define("retro-controller-card", RetroControllerCard);
customElements.define("retro-controller-card-editor", RetroControllerCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "retro-controller-card",
  name: "Retro Controller Card",
  description: "Adapter status, profile switching, mapping viewer/editor, and quick actions for retro gaming adapters.",
  preview: true,
});
