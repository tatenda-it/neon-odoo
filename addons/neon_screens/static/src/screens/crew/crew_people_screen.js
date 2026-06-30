/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * Crew & People — design-deck screen #6, HONEST DIRECTORY v1.
 * Read-only over the real neon.crew.member roster (name, role, Lead-Tech flag,
 * active/former), read under the user's own ACL. Deliberately shows NO
 * performance score / metric bars / availability / timeline — those are absent
 * and would be fabricated; they're a scoped future (HR-policy-gated) milestone.
 */
export class CrewPeopleScreen extends Component {
    static template = "neon_screens.CrewPeopleScreen";
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ data: null, loading: true, error: null });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.error = null;
        try {
            this.state.data = await this.orm.call("neon.crew.people.screen", "get_data", []);
        } catch (e) {
            this.state.error = (e && e.message) || String(e);
        }
        this.state.loading = false;
    }

    get d() { return this.state.data || {}; }
    get counts() { return this.d.counts || {}; }
}

registry.category("actions").add("neon_crew_people_screen", CrewPeopleScreen);
