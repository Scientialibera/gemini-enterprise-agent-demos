-- Kitchen Compliance Scorecard: one row per kitchen per week (Monday start), with a
-- 100-point compliance score built from five 20-point pillars. Each pillar loses
-- points per percentage point past its target:
--   Scan rate        target >= 97% fully scanned   2 pts per pp under
--   Short cook       target <= 3% of cookable items 3 pts per pp over
--   Force complete   target <= 4% of orders         2 pts per pp over
--   Hot hold         target <= 2% of orders         3 pts per pp over
--   Pouch integrity  target <= 1.5% of orders       4 pts per pp over (surprise + missing)
-- Grades: A >= 90, B >= 80, C >= 70, D >= 60, F below.
CREATE OR REPLACE TABLE `${TARGET_PROJECT}.${TARGET_DATASET}.kitchen_compliance_scorecard_weekly`
PARTITION BY week_start
CLUSTER BY kitchen_id AS
WITH orders AS (
  SELECT *
  FROM `${SOURCE_PROJECT}.ops_analytics.order_compliance_daily`
  WHERE service_date_et >= DATE_SUB(DATE_TRUNC(CURRENT_DATE('America/New_York'), WEEK(MONDAY)), INTERVAL 12 WEEK)
    AND is_official_compliance_eligible
),
rates AS (
  SELECT
    DATE_TRUNC(o.service_date_et, WEEK(MONDAY)) AS week_start,
    o.kitchen_id,
    k.kitchen_code, k.kitchen_name, k.city, k.area_director, k.regional_manager, k.state_code,
    COUNT(*) AS orders,
    SUM(o.num_items) AS items,
    SAFE_DIVIDE(SUM(o.has_force_complete), COUNT(*)) AS force_complete_order_rate,
    SAFE_DIVIDE(SUM(o.has_premature_force_complete), COUNT(*)) AS premature_fc_order_rate,
    SAFE_DIVIDE(SUM(o.has_critical_force_complete), COUNT(*)) AS critical_fc_order_rate,
    SAFE_DIVIDE(SUM(o.num_items_short_cooked), SUM(o.num_cookable_items)) AS short_cook_item_rate,
    SAFE_DIVIDE(SUM(o.has_hot_hold_violation), COUNT(*)) AS hot_hold_violation_rate,
    SAFE_DIVIDE(SUM(o.has_surprise_pouch), COUNT(*)) AS surprise_pouch_rate,
    SAFE_DIVIDE(SUM(o.has_missing_pouch), COUNT(*)) AS missing_pouch_rate,
    SAFE_DIVIDE(SUM(o.raw_was_fully_scanned), COUNT(*)) AS full_scan_rate,
    SAFE_DIVIDE(SUM(o.has_quality_compliance_issue), COUNT(*)) AS quality_compliance_issue_rate,
    SAFE_DIVIDE(SUM(o.has_fq_complaint), COUNT(*)) AS food_quality_complaint_rate,
    SAFE_DIVIDE(SUM(o.has_4_wall_accuracy_issue), COUNT(*)) AS four_wall_accuracy_issue_rate,
    APPROX_TOP_COUNT(o.primary_compliance_driver, 3) AS top_compliance_drivers
  FROM orders o
  LEFT JOIN `${TARGET_PROJECT}.${TARGET_DATASET}.dim_kitchen` k USING (kitchen_id)
  GROUP BY week_start, o.kitchen_id, k.kitchen_code, k.kitchen_name, k.city, k.area_director,
           k.regional_manager, k.state_code
),
points AS (
  SELECT
    *,
    ROUND(GREATEST(0, 20 - 2 * GREATEST(0, (0.97 - full_scan_rate) * 100)), 1) AS scan_rate_points,
    ROUND(GREATEST(0, 20 - 3 * GREATEST(0, (short_cook_item_rate - 0.03) * 100)), 1) AS short_cook_points,
    ROUND(GREATEST(0, 20 - 2 * GREATEST(0, (force_complete_order_rate - 0.04) * 100)), 1) AS force_complete_points,
    ROUND(GREATEST(0, 20 - 3 * GREATEST(0, (hot_hold_violation_rate - 0.02) * 100)), 1) AS hot_hold_points,
    ROUND(GREATEST(0, 20 - 4 * GREATEST(0, (surprise_pouch_rate + missing_pouch_rate - 0.015) * 100)), 1) AS pouch_integrity_points
  FROM rates
)
SELECT
  *,
  ROUND(scan_rate_points + short_cook_points + force_complete_points + hot_hold_points
        + pouch_integrity_points, 1) AS compliance_score,
  CASE
    WHEN scan_rate_points + short_cook_points + force_complete_points + hot_hold_points + pouch_integrity_points >= 90 THEN 'A'
    WHEN scan_rate_points + short_cook_points + force_complete_points + hot_hold_points + pouch_integrity_points >= 80 THEN 'B'
    WHEN scan_rate_points + short_cook_points + force_complete_points + hot_hold_points + pouch_integrity_points >= 70 THEN 'C'
    WHEN scan_rate_points + short_cook_points + force_complete_points + hot_hold_points + pouch_integrity_points >= 60 THEN 'D'
    ELSE 'F'
  END AS compliance_grade,
  CURRENT_TIMESTAMP() AS refreshed_at
FROM points;
