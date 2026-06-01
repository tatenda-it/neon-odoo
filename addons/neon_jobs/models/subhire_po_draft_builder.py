# -*- coding: utf-8 -*-
"""P-B4 -- Sub-hire PO draft builder.

⚠️ DECISION (B4, D6): creates ONE purchase.order in state='draft'
referencing the supplier + per-line shortfalls. NEVER confirms or
sends. PO confirmation lives in Odoo's standard Purchase Orders
menu so the supplier-facing spend action stays explicit.

PO field mapping:
    partner_id         <- subhire.request.supplier_partner_id
    origin             <- subhire.request.name (e.g. SUBHIRE-...)
    order_line         <- one purchase.order.line per subhire line:
        product_id         <- product.template.product_variant_id
                              (PO uses variants, not templates)
        product_qty        <- subhire.request.line.qty_short
        product_uom        <- product's uom_id
        name               <- "<workshop_name> -- sub-hire for
                                <event_name>"
        price_unit         <- 0 (supplier fills on RFQ response)
        date_planned       <- event_job.effective_overlap_start
                              (fallback: event_date)

state stays 'draft' (Odoo's RFQ-not-yet-sent state). The user
clicks Confirm on the PO via Odoo's standard Purchase UI to walk
through draft -> sent -> purchase -> done.
"""
import logging


_logger = logging.getLogger(__name__)


class SubhirePoDraftBuilder:
    """One instance per build() call."""

    def __init__(self, env):
        self.env = env

    def build(self, request):
        """Create the purchase.order in state='draft' for the
        given subhire.request. Returns the created PO record.

        Raises UserError if the request isn't ready (no supplier,
        no lines, etc.) -- callers should validate before invoking.
        """
        request.ensure_one()
        if not request.supplier_partner_id:
            raise ValueError(
                "supplier_partner_id is required on the request")
        if not request.line_ids:
            raise ValueError(
                "subhire.request has no lines -- nothing to PO")

        PO = self.env["purchase.order"].sudo()
        POLine = self.env["purchase.order.line"].sudo()

        event_job = request.event_job_id
        date_planned = (event_job.effective_overlap_start
                          or (event_job.event_date and
                              self._date_as_datetime(
                                  event_job.event_date))
                          or False)

        # Build PO header
        po = PO.create({
            "partner_id": request.supplier_partner_id.id,
            "origin": request.name or "",
            # Leave state at default ('draft') -- explicit set
            # not required; standard Odoo default.
        })

        # Build PO lines
        for ln in request.line_ids:
            product = ln.product_template_id
            variant = (product.product_variant_id
                         if product and product.product_variant_id
                         else None)
            if not variant:
                # No variant available -- skip (defensive; product
                # without a variant is a misconfiguration we don't
                # solve here). Log + continue.
                _logger.warning(
                    "Sub-hire PO build: product %s has no variant; "
                    "PO line skipped.",
                    product.display_name if product else "?")
                continue
            po_line = POLine.create({
                "order_id": po.id,
                "product_id": variant.id,
                "product_qty": float(ln.qty_short or 0),
                "product_uom": variant.uom_po_id.id or variant.uom_id.id,
                "name": "{wn} -- sub-hire for {ev}".format(
                    wn=(product.workshop_name or product.name
                         or "?"),
                    ev=event_job.name or "?"),
                "price_unit": 0.0,
                "date_planned": date_planned or False,
            })
            ln.sudo().write({"po_line_id": po_line.id})

        return po

    @staticmethod
    def _date_as_datetime(d):
        """Combine a date with 00:00 so purchase.order.line's
        date_planned (Datetime) accepts it."""
        from datetime import datetime, time
        if not d:
            return False
        try:
            return datetime.combine(d, time(0, 0))
        except (TypeError, ValueError):
            return False
