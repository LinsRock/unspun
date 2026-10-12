-- Run against production using psql; never invoke the worker or an LLM.
BEGIN READ ONLY;

SELECT now() AS collected_at;

SELECT report_date, kind,
       generated_at AT TIME ZONE 'Asia/Shanghai' AS generated_at_beijing,
       jsonb_array_length(payload->'events') AS event_count
FROM digests
ORDER BY report_date, kind;

SELECT count(*) AS viewpoint_count,
       sum(jsonb_array_length(payload->'claims')) AS claim_count
FROM event_viewpoints;

-- A valid claim must resolve to an article belonging to its event.
SELECT v.event_id, claim->>'article_id' AS article_id, a.event_id AS article_event_id
FROM event_viewpoints v
CROSS JOIN LATERAL jsonb_array_elements(v.payload->'claims') claim
LEFT JOIN articles a ON a.id::text = claim->>'article_id'
WHERE a.id IS NULL OR a.event_id IS DISTINCT FROM v.event_id;

SELECT v.event_id, a.id, a.url
FROM event_viewpoints v
CROSS JOIN LATERAL jsonb_array_elements(v.payload->'claims') claim
JOIN articles a ON a.id::text = claim->>'article_id'
WHERE a.url !~* '^https?://';

SELECT v.event_id, disagreement->>'point' AS point, claim_index
FROM event_viewpoints v
CROSS JOIN LATERAL jsonb_array_elements(v.payload->'disagreements') disagreement
CROSS JOIN LATERAL jsonb_array_elements_text(disagreement->'claim_indexes') claim_index
WHERE claim_index::int < 0
   OR claim_index::int >= jsonb_array_length(v.payload->'claims');

SELECT source_id,
       count(*) FILTER (WHERE status = 'ok') AS successful_runs,
       count(*) FILTER (WHERE status = 'error') AS failed_runs,
       max(run_at) AS latest_run
FROM fetch_logs
WHERE run_at >= now() - interval '24 hours'
GROUP BY source_id
ORDER BY source_id;

SELECT source_id, run_at, error
FROM fetch_logs
WHERE status = 'error' AND run_at >= now() - interval '4 hours'
ORDER BY run_at DESC
LIMIT 20;

SELECT (created_at AT TIME ZONE 'Asia/Shanghai')::date AS day,
       purpose, count(*) AS calls, sum(cost_usd) AS cost_usd
FROM llm_usage
GROUP BY day, purpose
ORDER BY day, purpose;

-- Unmet dates do not count towards the consecutive scheduled-day streak.
WITH daily AS (
  SELECT report_date,
         generated_at AT TIME ZONE 'Asia/Shanghai' AS local_generated_at
  FROM digests WHERE kind = 'daily'
), eligible AS (
  SELECT report_date,
         report_date - (row_number() OVER (ORDER BY report_date))::int AS streak_group
  FROM daily
  WHERE local_generated_at >= report_date + time '08:00'
    AND local_generated_at <= report_date + time '08:30'
)
SELECT min(report_date) AS first_date, max(report_date) AS last_date,
       count(*) AS consecutive_on_time_days
FROM eligible
GROUP BY streak_group
ORDER BY last_date DESC;

ROLLBACK;
