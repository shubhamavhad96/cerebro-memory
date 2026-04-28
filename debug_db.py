import os
import sqlite3
import tempfile
import shutil

cursor_dir = os.path.expanduser(
    "~/Library/Application Support/Cursor/User/workspaceStorage")
# Paste your exact workspace ID that we found in the last step
workspace_id = "2828cf65adb1c19fbfd83d8340025ea1"

db_path = os.path.join(cursor_dir, workspace_id, "state.vscdb")
tmp = tempfile.mktemp(suffix=".sqlite")
shutil.copy2(db_path, tmp)

try:
    conn = sqlite3.connect(tmp)
    cursor = conn.cursor()
    # Grab just the AI generations
    cursor.execute(
        "SELECT value FROM ItemTable WHERE key = 'aiService.generations'")
    row = cursor.fetchone()
    if row:
        print("--- JSON SNIPPET ---")
        # Print just the first 1500 characters so we can see the schema
        print(row[0][:1500])
    else:
        print("Key not found.")
finally:
    conn.close()
    os.remove(tmp)
