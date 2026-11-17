-- question: Detected effects by rule; resends caught by PreToolUse vs. noticed after the fact.
-- level: L7 effect
-- tables: effects, permissions
-- status: partial
-- needs: the ask a PreToolUse hook gave for a resend and the person's answer; no table stores it
-- notes: a resend is a detected effect with of_key set (a repeat of an earlier send's key); it is recorded when the call is seen, and seen says whether that was in PreToolUse (before) or PostToolUse (after). denied_retries counts effects a person refused and the agent tried again (attempt above 1); those are not resends. The ask itself, and whether it was answered yes, is not stored: that column is 'needs data'.
SELECT coalesce(rule, '(declared)') AS rule, count(*) AS effects, sum(of_key IS NOT NULL) AS resent, sum(of_key IS NOT NULL AND seen = 'before') AS resent_seen_before,
       sum(of_key IS NOT NULL AND seen = 'after') AS resent_seen_after, sum(attempt > 1) AS denied_retries, 'needs data' AS pretooluse_ask_outcome
FROM effects GROUP BY 1 ORDER BY 1;
