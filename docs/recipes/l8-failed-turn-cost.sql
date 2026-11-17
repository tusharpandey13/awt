-- question: Cost of turns that ended failed or canceled.
-- level: L8 usage
-- tables: usage, turns
-- status: partial
-- needs: a per-message price for Claude (its transcripts carry none): without a ccusage import a Claude turn has tokens but no cost, and the column says 'needs data'
-- notes: tokens come from the turn's message rows (usage_msg, each API message once). cost_usd is the cost the transcript itself carried (pi, opencode). ccusage_prorated_usd spreads the conversation's ccusage cost for that model over its message rows by token count, so it is approximate (cache and output tokens are priced differently); it is only given where a current ccusage row covers the conversation. Only turns a Paseo turn event matched have an outcome.
WITH cc AS (SELECT provider_name, conversation_id, response_model, sum(cost_usd) AS cost FROM usage_cc GROUP BY 1, 2, 3),
mt AS (SELECT provider_name, conversation_id, response_model, sum(coalesce(usage_input_tokens, 0) + coalesce(usage_output_tokens, 0) + coalesce(cache_read_tokens, 0) + coalesce(cache_write_tokens, 0)) AS tok FROM usage_msg GROUP BY 1, 2, 3),
tm AS (SELECT t.outcome, t.turn_id, u.provider_name, u.conversation_id, u.response_model, sum(u.usage_input_tokens) AS inp, sum(u.usage_output_tokens) AS outp, sum(u.cost_usd) AS own_cost,
              sum(coalesce(u.usage_input_tokens, 0) + coalesce(u.usage_output_tokens, 0) + coalesce(u.cache_read_tokens, 0) + coalesce(u.cache_write_tokens, 0)) AS tok
       FROM turns t JOIN usage_msg u ON u.turn_id = t.turn_id WHERE t.outcome IN ('failed', 'canceled') GROUP BY t.outcome, t.turn_id, u.provider_name, u.conversation_id, u.response_model)
SELECT tm.outcome, count(DISTINCT tm.turn_id) AS turns, sum(tm.inp) AS input_tokens, sum(tm.outp) AS output_tokens, round(sum(tm.own_cost), 4) AS cost_usd,
       round(sum(cc.cost * tm.tok / nullif(mt.tok, 0)), 4) AS ccusage_prorated_usd,
       CASE WHEN sum(tm.own_cost IS NULL AND cc.cost IS NULL) > 0 THEN 'needs data' END AS unpriced_models
FROM tm LEFT JOIN cc ON cc.provider_name = tm.provider_name AND cc.conversation_id = tm.conversation_id AND cc.response_model = tm.response_model
        LEFT JOIN mt ON mt.provider_name = tm.provider_name AND mt.conversation_id = tm.conversation_id AND mt.response_model = tm.response_model
GROUP BY tm.outcome ORDER BY tm.outcome;
