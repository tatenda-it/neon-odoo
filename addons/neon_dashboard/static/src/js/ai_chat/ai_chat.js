/** @odoo-module **/

/**
 * P12.M1 -- AI Sales Copilot chat panel.
 *
 * Mounted by the dashboard root component when the current variant
 * is 'director' or 'sales' (D1) AND the current user holds the
 * sales-user or sales-manager group (D11, server-enforced too).
 *
 * Communicates with /neon/ai_chat/{send,history,toggle} via the
 * RPC service (type='json' Odoo controller routes).
 */
import {
    Component, onMounted, onWillUnmount, onWillUpdateProps,
    useRef, useState,
} from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { NeonAiConfirmationCard } from "./confirmation_card";

export class NeonAiChat extends Component {
    static template = "neon_dashboard.NeonAiChat";
    static components = { NeonAiConfirmationCard };
    static props = {
        expanded: { type: Boolean, optional: true },
        onToggle: { type: Function, optional: true },
        activeVariant: { type: String, optional: true },
    };

    setup() {
        this.rpc = useService("rpc");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            messages: [],
            input: "",
            sending: false,
            // D19 — thinking-dots placeholder bubble flag. True
            // while the /neon/ai_chat/send round-trip is in
            // flight (independent of `sending` so we keep the
            // send button disabled separately).
            pending: false,
            loadingHistory: true,
            error: null,
            // D33 — hold the active variant inside the chat's own
            // state. Parent re-renders (auto-refresh, layout edits)
            // don't reset this; only an EXPLICIT prop change does.
            // Send + confirm endpoints read state.activeVariant,
            // not props.activeVariant.
            activeVariant: this.props.activeVariant || "",
        });

        // D33 — when the user explicitly switches variant via the
        // dashboard's View-as dropdown, the parent's prop will
        // change; mirror it into state so the chat keeps up. When
        // the parent re-renders with the SAME prop (auto-refresh),
        // no-op.
        onWillUpdateProps((nextProps) => {
            const next = nextProps.activeVariant || "";
            const cur = this.props.activeVariant || "";
            if (next && next !== cur) {
                this.state.activeVariant = next;
            }
        });

        this.listRef = useRef("messageList");
        this.inputRef = useRef("inputBox");

        onMounted(async () => {
            await this._loadHistory();
            // P12.M2 -- expose the component on window for browser
            // smokes so they can inject test cards without needing
            // a live LLM round-trip. Production OWL bundles don't
            // expose component refs through DOM, so without this
            // the test surface is otherwise unreachable.
            try {
                window.__neonAiChat = this;
            } catch (e) { /* sandbox */ }
        });

        onWillUnmount(() => {});
    }

    async _loadHistory() {
        this.state.loadingHistory = true;
        try {
            const res = await this.rpc(
                "/neon/ai_chat/history", { limit: 60 });
            if (res && res.ok) {
                this.state.messages = res.messages || [];
            }
        } catch (e) {
            this.state.error = (e && e.message) || String(e);
        }
        this.state.loadingHistory = false;
        this._scrollToBottom();
    }

    _scrollToBottom() {
        // Wait for OWL re-render to flush.
        setTimeout(() => {
            const el = this.listRef.el;
            if (el) {
                el.scrollTop = el.scrollHeight;
            }
        }, 50);
    }

    onInputKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.onSend();
        }
    }

    onInputChange(ev) {
        this.state.input = ev.target.value;
    }

    async onSend() {
        const text = (this.state.input || "").trim();
        if (!text || this.state.sending) {
            return;
        }
        const userMsg = {
            id: `temp-${Date.now()}`,
            role: "user",
            content: text,
            created_at: new Date().toISOString(),
        };
        this.state.messages.push(userMsg);
        this.state.input = "";
        this.state.sending = true;
        this.state.pending = true;     // D19 thinking-dots bubble
        this._scrollToBottom();

        try {
            const res = await this.rpc(
                "/neon/ai_chat/send",
                {
                    message: text,
                    active_variant: this.state.activeVariant || "",
                });
            if (res) {
                for (const card of (res.tool_cards || [])) {
                    if (card.is_confirmation_card) {
                        // P12.M2 — write proposal lands as a
                        // dedicated confirmation card row.
                        this.state.messages.push({
                            id: `confirm-${card.write_log_id}`,
                            role: "confirmation",
                            confirmation_card: card,
                            created_at: new Date().toISOString(),
                        });
                    } else {
                        this.state.messages.push({
                            id: `tool-${Date.now()}-${Math.random()}`,
                            role: "tool",
                            tool_name: card.tool,
                            tool_result: card.result,
                            created_at: new Date().toISOString(),
                        });
                    }
                }
                if (res.assistant_message) {
                    this.state.messages.push({
                        id: `asst-${Date.now()}`,
                        role: "assistant",
                        content: res.assistant_message,
                        is_fallback: !!res.is_fallback,
                        created_at: new Date().toISOString(),
                    });
                }
            }
        } catch (e) {
            this.state.messages.push({
                id: `err-${Date.now()}`,
                role: "assistant",
                content: ("Sorry -- the chat service didn't "
                          + "respond. Please try again."),
                is_fallback: true,
                created_at: new Date().toISOString(),
            });
        } finally {
            this.state.sending = false;
            this.state.pending = false;
            this._scrollToBottom();
        }
    }

    onToggleClick() {
        if (this.props.onToggle) {
            this.props.onToggle(!this.props.expanded);
        }
    }

    openPartner(partnerId) {
        if (!partnerId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            res_id: partnerId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openQuote(quoteId) {
        if (!quoteId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "neon.finance.quote",
            res_id: quoteId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    // -- formatting helpers consumed by the template --

    formatMoney(amount, currency) {
        const symbol = (currency === "USD") ? "$" : (currency || "");
        try {
            const num = (Math.round(Number(amount || 0) * 100) / 100)
                .toLocaleString("en-US");
            return `${symbol}${num}`;
        } catch (e) {
            return `${symbol}${amount}`;
        }
    }

    // P12.M1.1.1 / D33 — header label derived from the chat's
    // OWN active variant (state.activeVariant), not props. Parent
    // re-renders don't reset the header label.
    get headerLabel() {
        const variant = (this.state.activeVariant || "").toLowerCase();
        const map = {
            director: "Director Copilot",
            sales: "Sales Copilot",
            bookkeeper: "Finance Copilot",
            lead_tech: "Operations Copilot",
        };
        return map[variant] || "Sales Copilot";
    }

    // P12.M2 — callback the confirmation card uses to tell us its
    // resolution. We don't need to remove the card from messages
    // (the card itself transitions to its terminal state); we just
    // scroll back to the bottom so the user sees any follow-up
    // assistant message lined up below.
    onCardResolved() {
        this._scrollToBottom();
    }

    badgeForState(state) {
        // Match the dashboard's existing badge colour vocabulary.
        const map = {
            draft: "grey", pending_approval: "amber",
            approved: "blue", sent: "blue",
            accepted: "green", rejected: "red",
            expired: "grey", cancelled: "grey",
        };
        return map[state] || "grey";
    }
}
