/**
 * Retro Controller Card — Custom Lovelace card for the Retro Gaming integration.
 * Shows adapter status, profile selector, and quick-switch buttons.
 *
 * Bundled with custom_components/retro/ and auto-registered on setup.
 */

class RetroControllerCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement("retro-controller-card-editor");
  }

  static getStubConfig() {
    return { entity: "", title: "" };
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    this._render();
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error("Please define a profile select entity (select.retro_*_profile)");
    }
    this._config = config;
    this._entityId = config.entity;

    // Derive related entities from the profile entity
    // select.retro_<name>_profile -> sensor.retro_<name>_status, etc.
    const match = this._entityId.match(/^select\.retro_(.+)_profile$/);
    this._adapterName = match ? match[1] : "unknown";
    this._statusEntity = `sensor.retro_${this._adapterName}_status`;
    this._firmwareEntity = `sensor.retro_${this._adapterName}_firmware`;
    this._backupEntity = `button.retro_${this._adapterName}_backup`;
    this._refreshEntity = `button.retro_${this._adapterName}_refresh`;
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

    const currentProfile = profileState.state;
    const options = profileState.attributes.options || [];
    const status = statusState ? statusState.state : "unknown";
    const firmware = fwState ? fwState.state : "?";
    const connected = status === "connected";
    const title = this._config.title || `${this._adapterName.toUpperCase()} Adapter`;

    const profileIcons = {
      default: "mdi:gamepad",
      goldeneye: "mdi:pistol",
      goldeneye_solitaire: "mdi:pistol",
      mario_kart: "mdi:go-kart",
      smash_bros: "mdi:boxing-glove",
      zelda: "mdi:sword",
      perfect_dark: "mdi:pistol",
    };

    const profileButtons = options
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
            <span class="value">${currentProfile.replace(/_/g, " ")}</span>
          </div>

          <div class="profile-grid">
            ${profileButtons}
          </div>

          <div class="actions">
            <button class="action-btn" data-action="backup">
              <ha-icon icon="mdi:content-save"></ha-icon> Backup
            </button>
            <button class="action-btn" data-action="refresh">
              <ha-icon icon="mdi:refresh"></ha-icon> Refresh
            </button>
          </div>
        </div>
      </ha-card>

      <style>
        .retro-card {
          padding: 16px;
          font-family: var(--paper-font-body1_-_font-family, 'Roboto', sans-serif);
        }
        .header {
          margin-bottom: 16px;
        }
        .title-row {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 8px;
        }
        .title-row .title {
          font-size: 1.2em;
          font-weight: 500;
        }
        .title-row ha-icon {
          color: var(--primary-color);
        }
        .status-row {
          display: flex;
          align-items: center;
          gap: 12px;
          font-size: 0.85em;
        }
        .status-badge {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          padding: 2px 8px;
          border-radius: 12px;
          font-weight: 500;
          text-transform: capitalize;
        }
        .status-badge ha-icon {
          --mdc-icon-size: 14px;
        }
        .status-badge.connected {
          background: rgba(76, 175, 80, 0.15);
          color: var(--label-badge-green, #4caf50);
        }
        .status-badge.disconnected {
          background: rgba(244, 67, 54, 0.15);
          color: var(--label-badge-red, #f44336);
        }
        .firmware {
          color: var(--secondary-text-color);
        }
        .current-profile {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 8px 12px;
          background: var(--card-background-color, var(--primary-background-color));
          border: 1px solid var(--divider-color);
          border-radius: 8px;
          margin-bottom: 16px;
        }
        .current-profile .label {
          font-size: 0.85em;
          color: var(--secondary-text-color);
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        .current-profile .value {
          font-weight: 500;
          text-transform: capitalize;
          color: var(--primary-color);
        }
        .profile-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
          gap: 8px;
          margin-bottom: 16px;
        }
        .profile-btn {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 4px;
          padding: 12px 8px;
          border: 1px solid var(--divider-color);
          border-radius: 8px;
          background: var(--card-background-color, var(--primary-background-color));
          cursor: pointer;
          transition: all 0.2s;
          color: var(--primary-text-color);
          font-size: 0.8em;
        }
        .profile-btn:hover {
          border-color: var(--primary-color);
          background: rgba(var(--rgb-primary-color), 0.05);
        }
        .profile-btn.active {
          border-color: var(--primary-color);
          background: rgba(var(--rgb-primary-color), 0.12);
          font-weight: 600;
        }
        .profile-btn ha-icon {
          --mdc-icon-size: 24px;
          color: var(--primary-color);
        }
        .actions {
          display: flex;
          gap: 8px;
        }
        .action-btn {
          flex: 1;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 6px;
          padding: 8px;
          border: 1px solid var(--divider-color);
          border-radius: 8px;
          background: var(--card-background-color, var(--primary-background-color));
          cursor: pointer;
          color: var(--primary-text-color);
          font-size: 0.85em;
          transition: background 0.2s;
        }
        .action-btn:hover {
          background: rgba(var(--rgb-primary-color), 0.05);
        }
        .action-btn ha-icon {
          --mdc-icon-size: 18px;
        }
        .warning {
          padding: 16px;
          color: var(--error-color, #db4437);
        }
      </style>
    `;

    // Bind click handlers
    this.querySelectorAll(".profile-btn").forEach((btn) => {
      btn.addEventListener("click", () => this._selectProfile(btn.dataset.profile));
    });
    this.querySelectorAll(".action-btn").forEach((btn) => {
      btn.addEventListener("click", () => this._pressButton(btn.dataset.action));
    });
  }

  _selectProfile(profile) {
    this._hass.callService("select", "select_option", {
      entity_id: this._entityId,
      option: profile,
    });
  }

  _pressButton(action) {
    const entity =
      action === "backup" ? this._backupEntity : this._refreshEntity;
    this._hass.callService("button", "press", { entity_id: entity });
  }

  getCardSize() {
    return 4;
  }
}

// Simple editor for the card
class RetroControllerCardEditor extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
  }

  setConfig(config) {
    this._config = config;
    this._render();
  }

  _render() {
    this.innerHTML = `
      <div style="padding: 16px;">
        <ha-textfield
          label="Profile Select Entity (select.retro_*_profile)"
          value="${this._config.entity || ""}"
          style="width: 100%"
        ></ha-textfield>
        <ha-textfield
          label="Title (optional)"
          value="${this._config.title || ""}"
          style="width: 100%; margin-top: 8px;"
        ></ha-textfield>
      </div>
    `;

    this.querySelectorAll("ha-textfield").forEach((field) => {
      field.addEventListener("change", (e) => {
        const key = e.target.label.includes("Entity") ? "entity" : "title";
        this._config = { ...this._config, [key]: e.target.value };
        this.dispatchEvent(
          new CustomEvent("config-changed", { detail: { config: this._config } })
        );
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
  description: "Adapter status, profile switching, and quick actions for retro gaming adapters.",
  preview: true,
});
