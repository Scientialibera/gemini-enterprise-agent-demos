-- Kitchen Compliance - Manager & RCA: one row per kitchen, day and root-cause driver.
-- The agent filters to the last 7 days; the table keeps 35 for week-over-week context.
CREATE OR REPLACE TABLE `${TARGET_PROJECT}.${TARGET_DATASET}.kitchen_compliance_manager_rca_daily`
PARTITION BY service_date
CLUSTER BY regional_manager, kitchen_id AS
SELECT
  o.service_date_et AS service_date,
  o.kitchen_id,
  k.kitchen_code, k.kitchen_name, k.area_director, k.regional_manager,
  COALESCE(o.primary_compliance_driver, 'None') AS primary_compliance_driver,
  COALESCE(o.primary_delay_driver, 'None') AS primary_delay_driver,
  COUNT(*) AS orders,
  SUM(o.has_force_complete) AS orders_force_complete,
  SUM(o.has_premature_force_complete) AS orders_premature_fc,
  SUM(o.has_short_cook) AS orders_short_cook,
  SUM(o.has_hot_hold_violation) AS orders_hot_hold_violation,
  SUM(o.has_surprise_pouch) + SUM(o.has_missing_pouch) AS orders_pouch_issue,
  SUM(o.has_quality_compliance_issue) AS orders_quality_compliance_issue,
  COUNT(*) - SUM(o.raw_was_fully_scanned) AS orders_not_fully_scanned,
  CURRENT_TIMESTAMP() AS refreshed_at
FROM `${SOURCE_PROJECT}.ops_analytics.order_compliance_daily` o
LEFT JOIN `${TARGET_PROJECT}.${TARGET_DATASET}.dim_kitchen` k USING (kitchen_id)
WHERE o.service_date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 35 DAY)
  AND o.is_official_compliance_eligible
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8;
