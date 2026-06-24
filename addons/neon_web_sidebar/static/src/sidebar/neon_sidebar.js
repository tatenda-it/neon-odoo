/** @odoo-module **/

/**
 * Neon Web Sidebar -- a persistent Zoho-style left module rail.
 *
 * COEXISTENCE CONTRACT (do not break -- see docs/ui_sidebar_nav_discovery):
 * web_responsive owns the navbar/WebClient.prototype/NavBar-template surface.
 * This module sits ONLY on the seam web_responsive never touches:
 *   - registers an OWL component in the `main_components` registry (a sibling
 *     INSIDE the WebClient layout, NOT via NavBar);
 *   - reads the app tree READ-ONLY via useService("menu") (getApps /
 *     getCurrentApp / selectMenu) -- the same service web_responsive's AppsMenu
 *     consumes, so no shared mutable state;
 *   - drives visibility + content-offset purely off a NEON-SCOPED body class
 *     (o_neon_sidebar_open) in our own SCSS namespace.
 * It does NOT patch WebClient.prototype, does NOT t-inherit web.NavBar.*,
 * does NOT add to NavBar.components, and does NOT touch o_apps_menu_opened /
 * .o_main_navbar / .o_grid_apps_menu.
 */
import { Component, reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { useState } from "@odoo/owl";

const LS_KEY = "neon_web_sidebar.open";
const BODY_CLASS = "o_neon_sidebar_open";

// ---------------------------------------------------------------------------
// Shared reactive state service -- the rail (main_component) and the systray
// toggle both read/flip the same open/closed flag. Persisted per-user-per-
// browser in localStorage; default OPEN (Robin wants it on for the session,
// each user can hide it). Toggling also flips the neon-scoped body class that
// our SCSS keys off (so show/hide + content-offset is CSS, not re-render).
// ---------------------------------------------------------------------------
export const neonSidebarService = {
    start() {
        const stored = localStorage.getItem(LS_KEY);
        const state = reactive({ open: stored === null ? true : stored === "1" });
        const applyBodyClass = () => {
            document.body.classList.toggle(BODY_CLASS, state.open);
        };
        applyBodyClass();
        return {
            state,
            toggle() {
                state.open = !state.open;
                localStorage.setItem(LS_KEY, state.open ? "1" : "0");
                applyBodyClass();
            },
        };
    },
};
registry.category("services").add("neon_web_sidebar", neonSidebarService);

// ---------------------------------------------------------------------------
// The rail. Always rendered (visibility is CSS via the body class); re-renders
// on app change so the active app stays highlighted.
// ---------------------------------------------------------------------------
export class NeonSidebar extends Component {
    static template = "neon_web_sidebar.NeonSidebar";
    static props = {};

    setup() {
        this.menuService = useService("menu");
        // exact event the stock navbar uses to re-render on app switch.
        useBus(this.env.bus, "MENUS:APP-CHANGED", () => this.render());
    }

    get apps() {
        return this.menuService.getApps();
    }

    isActive(app) {
        const cur = this.menuService.getCurrentApp();
        return Boolean(cur && cur.id === app.id);
    }

    /** A usable <img> src from the app's web icon, or false -> initial fallback. */
    appIcon(app) {
        const data = app.webIconData;
        if (data) {
            return data.startsWith("data:") ? data : "data:image/png;base64," + data;
        }
        return false;
    }

    appInitial(app) {
        return (app.name || "?").trim().charAt(0).toUpperCase();
    }

    onAppClick(app) {
        this.menuService.selectMenu(app);
    }
}
registry.category("main_components").add("NeonSidebar", { Component: NeonSidebar });

// ---------------------------------------------------------------------------
// Systray toggle -- a unique key + sequence (web_responsive's AppMenuTheme is
// at sequence 100; we use a distinct one). Flips the shared open flag.
// ---------------------------------------------------------------------------
export class NeonSidebarToggle extends Component {
    static template = "neon_web_sidebar.Toggle";
    static props = {};

    setup() {
        this.sidebar = useService("neon_web_sidebar");
        this.state = useState(this.sidebar.state);
    }

    onClick() {
        this.sidebar.toggle();
    }
}
registry.category("systray").add(
    "neon_web_sidebar.toggle",
    { Component: NeonSidebarToggle },
    { sequence: 15 }
);
