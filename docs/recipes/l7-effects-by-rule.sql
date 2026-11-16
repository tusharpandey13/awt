-- question: Detected effects by rule; resends caught by PreToolUse vs. noticed after the fact.
-- level: L7 effect
-- tables: effects, permissions
-- status: partial
-- needs: the hook phase of a detected resend (PreToolUse ask or after the fact); no table stores it
-- notes: effects and resent (attempt above 1, a repeat of the same effect key) per rule are real. Whether a resend was caught by PreToolUse or noticed afterwards is not stored: the permissions table has no ask outcome and an effect row carries no hook phase. That column is 'needs data'.
SELECT coalesce(rule, '(declared)') AS rule, count(*) AS effects, sum(attempt > 1) AS resent, 'needs data' AS caught_before_or_after
FROM effects GROUP BY 1 ORDER BY 1;
