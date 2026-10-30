"""Diagnostic report insights parser utilities.

Parses executive summary text from insights_agent using the default Gemini LLM
with structured JSON generation, backed by a deterministic regex parser fallback.
Synthesizes store metric evaluations into clean executive TL;DR bullets with stakeholder tags.
"""

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from gemini_shared.runtime import create_genai_client
from google.genai import types as genai_types

from growth_analysis_workflow.config import BOOTSTRAP
from growth_analysis_workflow.config_loader import (
    get_default_model,
    load_agent_config,
    load_tool_prompt,
)

logger = logging.getLogger(__name__)

FRIENDLY_METRIC_NAMES: Dict[str, str] = {
    "Households (Geolytix)": "Addressable Households",
    "Google Rating": "Google Rating",
    "3P GOV % of Total GOV": "3P GOV Share",
    "MP % of 1P App / Web": "Marketplace Mix",
    "App / Web Traffic (1P) - Overall": "1P Digital Traffic",
    "Conversion (1P)": "1P Conversion Rate",
    "New Brand Mix % (Kitchen)": "New Brand Mix",
    "In-Stock Rate %": "In-Stock Rate",
    "O2E": "Order-to-Delivery Time",
    "IOR % (Kitchen) Target = < 10%": "Order Issue Rate",
    "Order Accuracy": "Order Accuracy",
    "Taste Rating (Kitchen)": "Taste Rating",
    "Value Rating (Kitchen)": "Value Rating",
}


def _get_friendly_metric_names() -> Dict[str, str]:
    """Retrieves friendly metric names from config or falls back to defaults."""
    try:
        report_cfg = load_agent_config("report_generation_agent")
        return report_cfg.get("friendly_metric_names", FRIENDLY_METRIC_NAMES)
    except Exception:
        return FRIENDLY_METRIC_NAMES


def _clean_evaluations_for_llm(evaluations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cleans raw column header strings into plain executive English before sending to Gemini."""
    friendly_names = _get_friendly_metric_names()
    cleaned = []
    for store in evaluations:
        st_copy = store.copy()

        cleaned_core = []
        for m in store.get("core_performance_metrics") or store.get("must_have_metrics", []):
            m_name = m.get("metric", "")
            cleaned_core.append(
                {
                    "metric": friendly_names.get(m_name, m_name),
                    "value": m.get("value"),
                    "benchmark_value": m.get("benchmark_value"),
                    "is_deficit": m.get("is_deficit", False),
                    "owner_tag": m.get("owner_tag", ""),
                }
            )
        st_copy["core_performance_metrics"] = cleaned_core

        cleaned_deficits = []
        for d in store.get("operational_benchmark_deficits") or store.get(
            "failing_nice_to_have_metrics", []
        ):
            d_name = d.get("metric", "")
            cleaned_deficits.append(
                {
                    "metric": friendly_names.get(d_name, d_name),
                    "store_value": d.get("store_value"),
                    "benchmark_value": d.get("benchmark_value"),
                    "owner_tag": d.get("owner_tag", ""),
                }
            )
        st_copy["operational_benchmark_deficits"] = cleaned_deficits
        cleaned.append(st_copy)

    return cleaned


def _clean_tldr_post_llm(text: str) -> str:
    """Removes conversational filler, population tags, and excessive spacing."""
    text = re.sub(r"(?i)^Here is the.*?synthesis.*?\n", "", text)
    text = re.sub(r"^\s*---\s*\n", "", text, flags=re.MULTILINE)
    text = re.sub(
        r"### (.*?) \((Suburban|Urban|Exurban|18 Mo\.|15 Mo\.)\)",
        r"### \1",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\[@(.*?)\]", r"@\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def generate_tldr_executive_bullets(
    tldr_evaluations: List[Dict[str, Any]],
    macro_summary_data: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Synthesizes structured store metric evaluations into executive TL;DR bullets with owner tags."""
    if not tldr_evaluations:
        logger.warning("No TL;DR store evaluations provided for bullet generation.")
        return ""

    cleaned_evals = _clean_evaluations_for_llm(tldr_evaluations)

    # Merge external research (weather, QSR trends, labor, customer sentiment) per store
    macro_map = {}
    if macro_summary_data:
        for row in macro_summary_data:
            raw_sname = row.get("store_name", "")
            clean_sname = raw_sname.split(" (")[0].split(" ")[0].strip().lower()
            macro_map[clean_sname] = row

    for store in cleaned_evals:
        s_key = store.get("store_name", "").split(" (")[0].split(" ")[0].strip().lower()
        if s_key in macro_map:
            m_info = macro_map[s_key]
            store["external_research"] = {
                "qsr_trends": m_info.get("qsr_trends"),
                "weather_trends": m_info.get("weather_trends"),
                "unemployment_labor": m_info.get("unemployment"),
            }

    def _fallback_tldr_formatter(evals: List[Dict[str, Any]]) -> str:
        """Generates deterministic TL;DR bullet text if Gemini LLM call is unavailable."""
        lines = []
        for store_data in evals:
            s_name = store_data.get("store_name", "Store")
            lines.append(f"### {s_name}")

            # 1. Format Core Performance Metrics with dynamic tags
            core_m = store_data.get("core_performance_metrics", [])
            cm_parts = []
            core_tags = set()
            for m in core_m:
                if m.get("value"):
                    cm_parts.append(f"{m['metric']}: **{m['value']}**")
                if m.get("owner_tag"):
                    core_tags.add(m["owner_tag"].strip())

            core_tags_str = f" {' '.join(sorted(list(core_tags)))}" if core_tags else ""
            if cm_parts:
                lines.append(f"  • {', '.join(cm_parts)}{core_tags_str}")

            # 2. Format Operational Deficits with dynamic tags
            deficits = store_data.get("operational_benchmark_deficits", [])
            def_parts = []
            deficit_tags = set()
            for d in deficits:
                def_parts.append(
                    f"{d['metric']} soft at **{d['store_value']}** vs **{d['benchmark_value']}** target"
                )
                if d.get("owner_tag"):
                    deficit_tags.add(d["owner_tag"].strip())

            deficit_tags_str = f" {' '.join(sorted(list(deficit_tags)))}" if deficit_tags else ""
            if def_parts:
                lines.append(f"  • Operational Deficits: {', '.join(def_parts)}{deficit_tags_str}")

            lines.append(
                "  • **Recommendation:** Optimize local marketing and kitchen SLA execution to recover top-line SSS growth."
            )
            lines.append("")
        return _clean_tldr_post_llm("\n".join(lines))

    model_name = get_default_model()
    prompt_template = load_tool_prompt("tldr_executive_bullets_prompt_template")
    if not prompt_template:
        prompt_template = (
            "You are an executive business analyst writing a concise TL;DR summary for C-level leadership.\n"
            "Given the following JSON array of store metrics and external research, synthesize a clean summary for each store.\n\n"
            "STRICT FORMATTING RULES:\n"
            "1. STORE HEADINGS: Use strictly '### Store Name' without population types or cohort tags.\n"
            '2. NO CONVERSATIONAL FILLER OR BRACKETS: DO NOT include sentences like "Here is the executive performance synthesis..." or horizontal lines ("---"). DO NOT put parenthetical brackets around benchmark comparisons.\n'
            "3. STRUCTURE EACH STORE INTO EXACTLY 4 CONCISE BULLETS + 1  RECOMMENDATION:\n"
            "   • Bullet 1 (Catchment & Funnel): Addressable Households, 1P digital traffic, and conversion rate. For ANY metric where 'is_deficit' is true, state the benchmark comparison inline without brackets (e.g. 'Reaches **X** addressable households vs **Y** benchmark', 'generating **A** 1P digital traffic vs **B** benchmark', 'converting at **C%** vs **D%** benchmark'). @Owner @Owner\n"
            "   • Bullet 2 (Channel Mix): 3P GOV share, 1P marketplace mix, and new brand mix. For ANY metric where 'is_deficit' is true, state the benchmark comparison inline without brackets (e.g. '3P GOV share at **X%** vs **Y%** benchmark'). @Owner\n"
            "   • Bullet 3 (Sentiment & SLA Deficits): Google rating and explicitly named operational benchmark deficits inline without brackets (e.g. 'In-Stock Rate soft at **94.9%** vs **96.6%** benchmark'). @Owner @Owner @Owner\n"
            "   • Bullet 4 (External Research): Synthesize 1-2 key external headwinds from 'external_research' (e.g. severe storm days, local QSR price wars, or state labor market tightness).\n"
            "Line 5 (Recommendation): Actionable 1-line recommendation.\n"
            "4. CONCISE & PUNCHY TONE: Maximum 1 sentence per bullet point. Avoid florid adjectives or extra fluff.\n"
            "5. OWNER TAGS: Write tags simply as @owner_name at the end of bullet points 1-3 where applicable (e.g., @Owner @Owner). NEVER put square brackets or commas around tags.\n"
            "6. HIGHLIGHT ALL KEY NUMBERS IN BOLD (e.g., **29K**, **35.6%**, **4.2★**, **1.0K**, **29.0%**).\n\n"
            "NOW PROCESS THIS DATA:\n{evaluations_json}\n"
        )
    prompt = prompt_template.format(evaluations_json=json.dumps(cleaned_evals, indent=2))

    try:
        client = create_genai_client(BOOTSTRAP)
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.1,
            ),
        )

        bullet_text = response.text.strip() if response.text else ""
        if bullet_text:
            logger.info("Successfully generated TL;DR executive bullets using Gemini.")
            return _clean_tldr_post_llm(bullet_text)
        else:
            logger.warning("LLM returned empty TL;DR text. Using deterministic fallback.")
            return _fallback_tldr_formatter(cleaned_evals)

    except Exception as e:
        logger.warning(f"LLM TL;DR bullet generation failed ({e}). Using deterministic fallback.")
        return _fallback_tldr_formatter(cleaned_evals)


def parse_macro_insights_fallback(macro_insights_text: str) -> List[Dict[str, Any]]:
    """Deterministic fallback regex parser tailored to the Executive Summary format."""
    stores: List[Dict[str, Any]] = []

    if "Executive Summary (Concise Diagnosis)" in macro_insights_text:
        summary_block = macro_insights_text.split("Executive Summary (Concise Diagnosis)")[1]
        summary_block = re.split(r"\n##\s|\nDetailed", summary_block)[0]
    else:
        summary_block = macro_insights_text

    lines = summary_block.strip().split("\n")
    current_data: Dict[str, Any] = {}

    def _clean_val(text: str) -> str:
        """Normalizes bullet text prefix with a standard bullet point."""
        text = text.strip()
        if text.startswith("• "):
            return text
        return f"• {text}"

    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue

        if line_str.startswith("•") or line_str.startswith("*") or line_str.startswith("-"):
            if not current_data.get("store_name"):
                continue

            match = re.match(r"^[\•\*\-\s]+(.*?):\s*(.*)", line_str)
            if match:
                field = match.group(1).strip().lower()
                val = _clean_val(match.group(2).strip())

                if "qsr trends" in field:
                    current_data["qsr_trends"] = val
                elif "weather" in field:
                    current_data["weather_trends"] = val
                elif "unemployment" in field:
                    current_data["unemployment"] = val
                elif "reviews" in field or "customer" in field:
                    current_data["customer_sentiment"] = val
                elif "recommendations" in field:
                    current_data["recommendations"] = val
        else:
            if current_data.get("store_name"):
                for k in [
                    "qsr_trends",
                    "weather_trends",
                    "unemployment",
                    "customer_sentiment",
                    "recommendations",
                ]:
                    if k not in current_data:
                        current_data[k] = "• N/A"
                stores.append(current_data.copy())

            if "Executive Summary" not in line_str and len(line_str) < 50:
                current_data = {"store_name": line_str}

    if current_data.get("store_name"):
        for k in [
            "qsr_trends",
            "weather_trends",
            "unemployment",
            "customer_sentiment",
            "recommendations",
        ]:
            if k not in current_data:
                current_data[k] = "• N/A"
        stores.append(current_data)

    return stores


def generate_macro_insights_tabular_summary(
    macro_insights_text: str, max_retries: int = 3
) -> List[Dict[str, Any]]:
    """Extracts executive summary data into an 8-column tabular format using Gemini LLM."""
    if not macro_insights_text or not macro_insights_text.strip():
        logger.warning("No macro_insights_text provided for tabular summary.")
        return []

    prompt_template = load_tool_prompt("macro_insights_tabular_summary_prompt_template")
    prompt = prompt_template.replace("{macro_insights_text}", macro_insights_text)
    model_name = get_default_model()

    client = create_genai_client(BOOTSTRAP)

    report_cfg = load_agent_config("report_generation_agent")
    extraction_temp = report_cfg.get("model_settings", {}).get("extraction_temperature", 0.0)

    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=extraction_temp,
                    response_mime_type="application/json",
                ),
            )

            if response.text:
                raw_text = response.text.strip()

                # 1. Strip markdown code fence wrappers if present
                raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.IGNORECASE)
                raw_text = re.sub(r"\s*```$", "", raw_text).strip()

                # 2. Fix trailing commas before closing brackets/braces (e.g. [a, b,])
                raw_text = re.sub(r",\s*([\]}])", r"\1", raw_text)

                parsed_data = json.loads(raw_text)
                if isinstance(parsed_data, list) and len(parsed_data) > 0:
                    logger.info(
                        f"Successfully mapped tabular summary for {len(parsed_data)} stores using {model_name} (Attempt {attempt}/{max_retries})."
                    )
                    return parsed_data
                else:
                    logger.warning(
                        f"Attempt {attempt}/{max_retries}: LLM JSON list was empty or invalid."
                    )

        except Exception as e:
            logger.warning(f"LLM tabular extraction attempt {attempt}/{max_retries} failed ({e}).")

        # Sleep before next attempt (Exponential backoff: 2s, 4s)
        if attempt < max_retries:
            backoff_sec = 2**attempt
            logger.info(f"Retrying LLM tabular summary in {backoff_sec} seconds...")
            time.sleep(backoff_sec)

    logger.warning("All LLM retry attempts failed. Falling back to deterministic regex parser.")
    return parse_macro_insights_fallback(macro_insights_text)
