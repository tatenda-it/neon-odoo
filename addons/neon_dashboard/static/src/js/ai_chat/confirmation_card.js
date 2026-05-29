/** @odoo-module **/

/**
 * P12.M2 -- AI Copilot confirmation card.
 *
 * Renders an inline approval card for a write proposal returned by
 * a write-category tool. The user clicks Confirm to execute the
 * write (POST /neon/ai_chat/confirm) or Cancel to void the proposal
 * (POST /neon/ai_chat/cancel). After either action the card
 * collapses to the matching success / cancelled / error state.
 *
 * ⚠️ DECISION (M12.M2, D32): Confirm is NOT auto-focused. The keyboard
 * tab-order is Cancel-first so accidental Enter-to-commit cannot
 * silently confirm a write the user hadn't intended.
 */
import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class NeonAiConfirmationCard extends Component {
    static template = "neon_dashboard.NeonAiConfirmationCard";
    static props = {
        // The card payload received from /neon/ai_chat/send. Shape:
        //   { tool, tool_call_id, confirmation_token, write_log_id,
        //     action_type, target_model, human_summary,
        //     before_state, after_state, expires_at }
        card: { type: Object },
        // Called by the card with (newState) so the parent can
        // update its messages array (carrying the post-execute /
        // post-cancel render).
        onResolved: { type: Function, optional: true },
        activeVariant: { type: String, optional: true },
    };

    setup() {
        this.rpc = useService("rpc");
        this.action = useService("action");
        this.state = useState({
            // proposed | confirming | confirmed | cancelled | error
            status: "proposed",
            error: "",
            result: null,
            replay: false,
        });
    }

    get actionIcon() {
        const map = {
            log_lead: "fa-plus-circle",
            move_stage: "fa-arrow-right",
            update_deal_value: "fa-dollar",
            post_chatter_note: "fa-comment-o",
        };
        return map[this.props.card.action_type] || "fa-check-circle";
    }

    get actionTitle() {
        const map = {
            log_lead: "Create lead",
            move_stage: "Move stage",
            update_deal_value: "Update deal value",
            post_chatter_note: "Post chatter note",
        };
        return map[this.props.card.action_type] || "Confirm action";
    }

    get diffPairs() {
        // For move_stage and update_deal_value we render a single
        // before -> after row. log_lead and post_chatter_note skip
        // the diff block (after_state only).
        const before = this.props.card.before_state || {};
        const after = this.props.card.after_state || {};
        if (this.props.card.action_type === "move_stage") {
            return [{
                label: "Stage",
                before: before.stage || "—",
                after: after.stage || "—",
            }];
        }
        if (this.props.card.action_type === "update_deal_value") {
            const c = after.currency || before.currency || "USD";
            return [{
                label: "Deal value",
                before: `${c} ${this._fmtNum(before.expected_revenue)}`,
                after: `${c} ${this._fmtNum(after.expected_revenue)}`,
            }];
        }
        return [];
    }

    _fmtNum(v) {
        if (v === null || v === undefined) return "—";
        try {
            return Number(v).toLocaleString("en-US",
                { maximumFractionDigits: 2 });
        } catch (e) {
            return String(v);
        }
    }

    async onConfirmClick() {
        if (this.state.status !== "proposed") return;
        this.state.status = "confirming";
        this.state.error = "";
        try {
            const res = await this.rpc(
                "/neon/ai_chat/confirm",
                {
                    confirmation_token:
                        this.props.card.confirmation_token,
                    active_variant: this.props.activeVariant || "",
                });
            if (res && res.ok) {
                this.state.status = (
                    res.status === "executed" ? "confirmed"
                    : (res.status === "cancelled" ? "cancelled"
                    : (res.status || "confirmed")));
                this.state.result = res.result || null;
                this.state.replay = !!res.replay;
                if (this.props.onResolved) {
                    this.props.onResolved({
                        status: this.state.status,
                        result: this.state.result,
                    });
                }
            } else {
                this.state.status = (
                    res && res.error_code === "expired"
                        ? "expired" : "error");
                this.state.error = (
                    (res && res.error) || "Confirmation failed.");
            }
        } catch (e) {
            this.state.status = "error";
            this.state.error = (e && e.message) || String(e);
        }
    }

    async onCancelClick() {
        if (this.state.status !== "proposed") return;
        this.state.status = "confirming";
        try {
            const res = await this.rpc(
                "/neon/ai_chat/cancel",
                { confirmation_token:
                    this.props.card.confirmation_token });
            if (res && res.ok) {
                this.state.status = "cancelled";
                if (this.props.onResolved) {
                    this.props.onResolved({ status: "cancelled" });
                }
            } else {
                this.state.status = "error";
                this.state.error = (res && res.error) || "Cancel failed.";
            }
        } catch (e) {
            this.state.status = "error";
            this.state.error = (e && e.message) || String(e);
        }
    }

    openResult() {
        const res = this.state.result;
        if (!res) return;
        const id = res.created_target_id || res.target_id;
        if (!id || !res.target_model) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: res.target_model,
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}
