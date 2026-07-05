import os
import re
import time

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

MODEL = "gemini-2.5-flash"

PROFILE_PROMPT = """\
You are a competitive-analysis assistant. You receive the extracted text of one
competitor's website (homepage and, if available, pricing/features pages).

Extract, using ONLY what the text supports:
- name: the product/company name
- usp: the core unique selling point, in one sentence
- target_audience: who the product is for
- key_features: 3-6 concrete features or capabilities
- pricing_model: how they charge (e.g. "free + paid tiers from $X/mo",
  "self-hosted free, cloud paid"). If pricing isn't in the text, use "not stated".

Do not invent details that aren't in the text."""

SYNTHESIS_PROMPT = """\
You are a market analyst. You receive structured profiles of several competitors
in the same market. Analyze them AS A GROUP and return:
- common_patterns: 3-5 things almost all of them do or claim (table stakes)
- differentiators: notable ways individual players stand apart
- market_gap: one specific, well-argued underserved segment or positioning a new
  entrant could take, grounded in what these competitors do and don't offer.

Base everything on the provided profiles; be concrete, not generic."""


class CompetitorProfile(BaseModel):
    name: str
    usp: str
    target_audience: str
    key_features: list[str] = Field(default_factory=list)
    pricing_model: str = "not stated"


class MarketInsight(BaseModel):
    common_patterns: list[str] = Field(default_factory=list)
    differentiators: list[str] = Field(default_factory=list)
    market_gap: str = ""


class QuotaExhaustedError(RuntimeError):
    pass


def make_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Get a free key at https://ai.google.dev "
            "and put it in .env (see .env.example) or in the environment."
        )
    return genai.Client(api_key=api_key)


def _is_rate_limit(err: Exception) -> bool:
    return "429" in str(err) or "RESOURCE_EXHAUSTED" in str(err)


def _is_daily_quota(err: Exception) -> bool:
    return "PerDay" in str(err) or "RequestsPerDay" in str(err)


def _retry_after(err: Exception) -> float | None:
    m = re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", str(err))
    return float(m.group(1)) if m else None


def _generate(client, prompt, system, schema, retries=2):
    config = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        response_schema=schema,
        temperature=0.2,
    )
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = client.models.generate_content(model=MODEL, contents=prompt, config=config)
            if isinstance(resp.parsed, schema):
                return resp.parsed
            return schema.model_validate_json(resp.text or "")
        except Exception as err:
            last = err
            if _is_rate_limit(err) and _is_daily_quota(err):
                raise QuotaExhaustedError(
                    "Gemini daily free-tier quota exhausted (requests-per-day). It resets "
                    "around midnight Pacific — try again later or use a higher tier / another key."
                ) from err
            if attempt >= retries:
                break
            time.sleep((_retry_after(err) or 1.5 * (attempt + 1)) + 0.5)
    raise RuntimeError(f"generation failed after {retries + 1} attempts: {last}")


def analyze_site(client: genai.Client, url: str, text: str) -> CompetitorProfile:
    prompt = f"Competitor URL: {url}\n\nWEBSITE TEXT:\n{text}"
    return _generate(client, prompt, PROFILE_PROMPT, CompetitorProfile)


def synthesize(client: genai.Client, profiles: list[CompetitorProfile]) -> MarketInsight:
    lines = []
    for p in profiles:
        lines.append(
            f"- {p.name}: USP={p.usp} | Audience={p.target_audience} | "
            f"Features={'; '.join(p.key_features)} | Pricing={p.pricing_model}"
        )
    prompt = "COMPETITOR PROFILES:\n" + "\n".join(lines)
    return _generate(client, prompt, SYNTHESIS_PROMPT, MarketInsight)
