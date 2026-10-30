-- Item-level evidence for drill-down questions: compliance issues in the last 7 days.
CREATE OR REPLACE TABLE `${TARGET_PROJECT}.${TARGET_DATASET}.kitchen_compliance_item_issues_7d`
PARTITION BY service_date
CLUSTER BY kitchen_id AS
SELECT
  service_date_et AS service_date,
  kitchen_id, kitchen_code, kitchen_name, regional_manager, area_director,
  order_number, menu_item_name, restaurant_brand_name, station_code, station_type,
  is_peak_hour,
  force_complete_severity_tier,
  is_scored_short_cook = 1 AS is_short_cook,
  has_quality_compliance_issue = 1 AS has_quality_issue,
  has_timing_compliance_issue = 1 AS has_timing_issue,
  has_scanned = 1 AS was_scanned,
  kitchen_on_time_issue,
  is_kitchen_fault
FROM `${SOURCE_PROJECT}.ops_analytics.kitchen_compliance_items`
WHERE service_date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 7 DAY)
  AND (has_quality_compliance_issue = 1 OR has_timing_compliance_issue = 1
       OR is_scored_short_cook = 1 OR has_scanned = 0 OR force_complete_severity_tier IS NOT NULL);
