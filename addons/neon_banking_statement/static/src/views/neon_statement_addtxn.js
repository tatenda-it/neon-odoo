/** @odoo-module **/
/*
 * BUILD 1 / PART 1 -- "Add Transaction" dropdown for the statement ledgers.
 *
 * One labelled dropdown in the list control panel replaces the old row of
 * <header display="always"> buttons (which collided with the search box on wide
 * screens). It is scoped to the statement trees ONLY via js_class; every other
 * list is untouched. Each item opens the SAME existing wizard action with the
 * per-account default_cash_account_code (read off the statement action context),
 * so NO wizard/model/posting change -- only the launching surface.
 */
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { registry } from "@web/core/registry";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { useService } from "@web/core/utils/hooks";

export class NeonStatementAddTxnController extends ListController {
    static template = "neon_banking_statement.AddTxnListView";
    static components = { ...ListController.components, Dropdown, DropdownItem };

    setup() {
        super.setup();
        this.action = useService("action");
    }

    /** The cash account this statement is showing, from the action context. */
    get cashAccountCode() {
        return this.props.context.default_cash_account_code;
    }

    /** Open a wizard action, pre-pointed at this statement's cash account. */
    openWizard(actionXmlId) {
        this.action.doAction(actionXmlId, {
            additionalContext: {
                default_cash_account_code: this.cashAccountCode,
            },
        });
    }
}

export const NeonStatementAddTxnListView = {
    ...listView,
    Controller: NeonStatementAddTxnController,
};

registry.category("views").add("neon_statement_addtxn", NeonStatementAddTxnListView);
