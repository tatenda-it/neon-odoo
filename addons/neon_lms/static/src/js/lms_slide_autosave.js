/** @odoo-module **/
/*
 * Neon LMS slide autosave indicator.
 *
 * Picks up the data-name="neon_lms_autosave_indicator"
 * element injected by view_slide_slide_form_neon_lms and
 * flips it through idle -> saving -> saved as the form's
 * description field mutates and the form auto-commits.
 *
 * Designed lightweight on purpose: the actual save is the
 * stdlib form-view auto-save (Odoo 17 form views save on
 * blur / leave / discard). This JS only mirrors the save
 * lifecycle for visible feedback.
 */
import { registry } from "@web/core/registry";
import { formView } from "@web/views/form/form_view";
import { FormController } from "@web/views/form/form_controller";

class NeonLMSSlideFormController extends FormController {
    setup() {
        super.setup();
        this._neonLmsIdleHandle = null;
        this._neonLmsIndicator = null;
    }

    _neonLmsFindIndicator() {
        if (!this._neonLmsIndicator) {
            const root = this.rootRef?.el || document;
            this._neonLmsIndicator = root.querySelector(
                "[data-name='neon_lms_autosave_indicator']"
            );
        }
        return this._neonLmsIndicator;
    }

    _neonLmsSetIndicator(text) {
        const el = this._neonLmsFindIndicator();
        if (el) {
            el.textContent = "autosave: " + text;
        }
    }

    _neonLmsMarkSaving() {
        this._neonLmsSetIndicator("saving...");
        if (this._neonLmsIdleHandle) {
            clearTimeout(this._neonLmsIdleHandle);
            this._neonLmsIdleHandle = null;
        }
    }

    _neonLmsMarkSaved() {
        this._neonLmsSetIndicator("saved");
        if (this._neonLmsIdleHandle) {
            clearTimeout(this._neonLmsIdleHandle);
        }
        this._neonLmsIdleHandle = setTimeout(() => {
            this._neonLmsSetIndicator("idle");
            this._neonLmsIdleHandle = null;
        }, 2000);
    }

    async beforeUnload(ev) {
        // Cosmetic feedback only; do not block unload.
        this._neonLmsMarkSaving();
        return super.beforeUnload?.(ev);
    }

    async save(...args) {
        this._neonLmsMarkSaving();
        try {
            const out = await super.save(...args);
            this._neonLmsMarkSaved();
            return out;
        } catch (e) {
            this._neonLmsSetIndicator("error");
            throw e;
        }
    }
}

// Only swap the controller for slide.slide forms; other
// models keep the stock FormController untouched.
const neonLmsSlideFormView = {
    ...formView,
    Controller: NeonLMSSlideFormController,
};

registry.category("views").add(
    "neon_lms_slide_form",
    neonLmsSlideFormView
);
