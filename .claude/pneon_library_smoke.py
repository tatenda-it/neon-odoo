# -*- coding: utf-8 -*-
"""neon_library smoke. Run via:
    docker exec -i neon-odoo-app odoo shell -d <DB> --no-http < pneon_library_smoke.py

Covers: nested folders + doc_count + complete_name; document file round-trip
(upload bytes -> download intact); file-type icon; full-text content index
(attachment_indexation) + search by content/name/tag; the access matrix
(internal read-all + write-own; UNLINK + writing OTHERS restricted to the
manager group). Rolls back.
"""
import base64
import traceback

results = []


def check(name, cond, detail=""):
    ok = bool(cond)
    results.append((name, ok))
    print(("PASS" if ok else "FAIL") + " " + name
          + (("" if ok else " :: " + str(detail))))


def raises(fn):
    try:
        fn()
        return False
    except Exception:  # noqa: BLE001
        return True


try:
    env = env(context=dict(env.context, tracking_disable=True,
                           mail_create_nosubscribe=True, mail_create_nolog=True,
                           mail_notify_force_send=False))
    Folder = env["neon.library.folder"].sudo()
    Doc = env["neon.library.document"].sudo()
    Tag = env["neon.library.tag"].sudo()
    g_user = env.ref("base.group_user")
    g_su = env.ref("neon_core.group_neon_superuser")

    aix = env["ir.module.module"].sudo().search(
        [("name", "=", "attachment_indexation")])
    check("attachment_indexation installed", aix and aix.state == "installed",
          aix.state if aix else "missing")

    def mk_user(login, groups):
        return env["res.users"].sudo().create({
            "name": login, "login": login, "email": login + "@test.neon",
            "groups_id": [(6, 0, [g.id for g in groups])]})

    alice = mk_user("nl_alice", [g_user])      # regular internal
    bob = mk_user("nl_bob", [g_user])          # regular internal
    mgr = mk_user("nl_mgr", [g_user, g_su])    # manager (superuser)

    # nested folders
    root = Folder.create({"name": "NL Root"})
    sub = Folder.create({"name": "NL Sub", "parent_id": root.id})
    check("folder nesting + complete_name",
          root.complete_name == "NL Root"
          and sub.complete_name == "NL Root / NL Sub")

    tag = Tag.create({"name": "NL Important"})

    # document with a text file (so attachment_indexation full-text indexes it)
    raw = b"neon library full text searchable content MARKER42 and more words"
    doc = Doc.with_user(alice.id).create({
        "name": "NL Doc A", "folder_id": sub.id, "tag_ids": [(4, tag.id)],
        "file_data": base64.b64encode(raw), "file_name": "notesA.txt"})
    sub.invalidate_recordset()
    check("doc create + folder.document_count",
          doc.folder_id.id == sub.id and sub.document_count == 1)
    check("file-type icon + extension (txt)",
          doc.file_extension == "txt" and doc.file_icon == "fa-file-text-o")
    check("uploaded_by = create_uid (alice)", doc.uploaded_by.id == alice.id)

    # file round-trip: download bytes == uploaded bytes
    doc.invalidate_recordset()
    got = base64.b64decode(doc.file_data)
    check("file round-trip intact (download == upload)", got == raw,
          (got[:24], raw[:24]))

    # full-text content index + search
    check("index_content populated (attachment_indexation)",
          doc.index_content and "MARKER42" in doc.index_content,
          (doc.index_content or "")[:80])
    check("search by content (MARKER42)",
          doc in Doc.search([("index_content", "ilike", "MARKER42")]))
    check("search by name", doc in Doc.search([("name", "ilike", "NL Doc A")]))
    check("search by tag",
          doc in Doc.search([("tag_ids.name", "ilike", "Important")]))

    # ---- ACCESS MATRIX ----
    check("regular non-owner CANNOT write another's doc",
          raises(lambda: doc.with_user(bob.id).write({"name": "hacked"})))
    check("regular non-owner CANNOT MOVE another's doc (folder_id write)",
          raises(lambda: doc.with_user(bob.id).write({"folder_id": root.id})))
    check("regular CANNOT unlink another's doc",
          raises(lambda: doc.with_user(bob.id).unlink()) and doc.exists())
    # owner CAN write own
    doc.with_user(alice.id).write({"description": "mine"})
    doc.invalidate_recordset()
    check("owner CAN write own doc", doc.description == "mine")
    # owner CAN move own doc (folder_id write) -- complements the non-owner
    # move-block above; then move it back for the rest of the run
    doc.with_user(alice.id).write({"folder_id": root.id})
    doc.invalidate_recordset()
    check("owner CAN move own doc (folder_id write)",
          doc.folder_id.id == root.id)
    doc.with_user(alice.id).write({"folder_id": sub.id})
    # folder recursion guard (savepoint: the cyclic write can surface as a
    # txn-aborting error; isolate it so the next checks keep a clean cursor)
    rec_blocked = False
    try:
        with env.cr.savepoint():
            sub.write({"parent_id": sub.id})
    except Exception:  # noqa: BLE001
        rec_blocked = True
    check("folder recursion blocked (self as parent)", rec_blocked)
    # folder with children cannot be deleted (ondelete=restrict), even by a
    # manager -- enforces leaf-only delete. The restrict is a DB FK that
    # aborts the txn on violation, so run it inside a savepoint to keep the
    # rest of the smoke usable.
    blocked = False
    try:
        with env.cr.savepoint():
            root.with_user(mgr.id).unlink()
    except Exception:  # noqa: BLE001
        blocked = True
    check("folder with children cannot be deleted (restrict)",
          blocked and root.exists())
    # even the owner cannot unlink (manager-only delete)
    check("regular CANNOT unlink even OWN doc (manager-only delete)",
          raises(lambda: doc.with_user(alice.id).unlink()) and doc.exists())
    # all internal read all
    check("regular reads another's doc (read-all)",
          doc.with_user(bob.id).name == "NL Doc A")
    # manager CAN unlink
    did = doc.id
    doc.with_user(mgr.id).unlink()
    check("manager CAN unlink", not Doc.search([("id", "=", did)]))

except Exception:  # noqa: BLE001
    traceback.print_exc()
    results.append(("smoke crashed", False))
finally:
    try:
        env.cr.rollback()
    except Exception:  # noqa: BLE001
        pass

passed = sum(1 for _, ok in results if ok)
print("\nTotal: %d/%d passed" % (passed, len(results)))
