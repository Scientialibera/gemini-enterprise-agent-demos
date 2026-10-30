-- Kitchen attributes: one row per kitchen, latest values in the last 35 days.
CREATE OR REPLACE TABLE `${TARGET_PROJECT}.${TARGET_DATASET}.dim_kitchen` AS
SELECT
  kitchen_id,
  ARRAY_AGG(STRUCT(kitchen_code, kitchen_name, kitchen_type, kitchen_class, area_director,
                   regional_manager, city, state_code, population_type, is_currently_mature)
            ORDER BY service_date_et DESC LIMIT 1)[OFFSET(0)].*
FROM `${SOURCE_PROJECT}.ops_analytics.kitchen_compliance_items`
WHERE service_date_et >= DATE_SUB(CURRENT_DATE('America/New_York'), INTERVAL 35 DAY)
GROUP BY kitchen_id;
