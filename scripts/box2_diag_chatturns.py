"""Diagnostic: per-turn prompt component sizes from chat_turns (run in the agent container)."""
from data_layer.db import fetch_all

rows = fetch_all("""
    SELECT char_length(user_message)                      AS umsg,
           char_length(coalesce(system_prompt,''))        AS sys_chars,
           jsonb_array_length(selected_tools)             AS n_tools,
           jsonb_array_length(matched_guides)            AS n_guides,
           char_length(coalesce(matched_guides::text,'')) AS guides_chars,
           char_length(coalesce(assistant_message,''))    AS reply_chars
    FROM chat_turns
    ORDER BY created_at
""")

print("%-5s%9s%11s%8s%9s%14s%8s" % ("turn", "usermsg", "sysprompt", "ntools", "nguides", "guideschars", "reply"))
for i, r in enumerate(rows, 1):
    print("%-5d%9s%11s%8s%9s%14s%8s" % (
        i, r["umsg"], r["sys_chars"], r["n_tools"] or 0, r["n_guides"] or 0,
        r["guides_chars"] or 0, r["reply_chars"]))
print("\n(chars; ~4 chars/token. 'sysprompt' = stored system_prompt column; tool schemas + chat history add on top of it.)")
