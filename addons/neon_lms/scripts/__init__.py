# Marks scripts/ as a package so importlib + inspect can resolve the
# one-shot migration script. NOT imported by Odoo at module load -- the
# scripts in this dir are admin-run via odoo shell, not auto-triggered.
