"""System prompt templates for synthetic students.

Builds the system-level prompt (persona + KC memory rendering) and the
per-item user prompt (MCQ or FRQ with optional lesson text).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .memory import StudentMemory
    from .student import StudentPersona

from .memory import recall_probability


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

def build_student_system_prompt(
    persona: StudentPersona,
    memory: StudentMemory,
    now: float,
) -> str:
    """Build the system prompt for a synthetic student.

    The prompt encodes:
    - The student's ability tier
    - A rendered view of the student's current KC memory (only KCs with
      recall_probability > 0.3)
    - Behavioural constraints (carelessness, working memory, guessing style)
    """
    # Render known KCs -------------------------------------------------
    known = memory.get_known_kcs(now, threshold=0.3)
    if known:
        kc_lines: list[str] = []
        for kc in known:
            prob = recall_probability(kc, now)
            desc = _kc_description(kc.kc_id)
            kc_lines.append(f"- {kc.kc_id}: {desc} (confidence: {prob:.0%})")
        memory_block = "\n".join(kc_lines)
    else:
        memory_block = "You have not learned any statistics concepts yet."

    # Carelessness as an integer percentage ----------------------------
    carelessness_pct = f"{persona.carelessness * 100:.0f}"

    # Build final prompt -----------------------------------------------
    prompt = (
        f"You are a high school student in AP Statistics. "
        f"Your performance level is {persona.ability_tier}/5.\n"
        f"You may ONLY use knowledge from your MEMORY below. Do NOT use any facts, formulas,\n"
        f"or concepts not present in your memory.\n"
        f"\n"
        f"## YOUR MEMORY (what you currently know)\n"
        f"{memory_block}\n"
        f"\n"
        f"## INSTRUCTIONS\n"
        f"- For multiple choice: respond with ONLY a single letter (A/B/C/D/E). Nothing else.\n"
        f"- For free response: write a short answer. Use this format:\n"
        f"  Answer: [your answer]\n"
        f"  Work: [show your reasoning]\n"
        f"  Conclusion: [state your conclusion in context]\n"
        f"- If you don't know something, guess. Students often confuse:\n"
        f"  - correlation with causation\n"
        f"  - population parameters with sample statistics\n"
        f"  - conditional probability with joint probability\n"
        f"  - one-sided vs two-sided tests\n"
        f"- You sometimes make arithmetic mistakes (about {carelessness_pct}% of the time)\n"
        f"- You can only hold {persona.working_memory_slots} ideas in your head at once"
    )
    return prompt


# ---------------------------------------------------------------------------
# Item prompt builder
# ---------------------------------------------------------------------------

def build_item_prompt(
    item: dict,
    lesson_text: str | None = None,
) -> str:
    """Build the user message for a specific question.

    Parameters
    ----------
    item : dict
        Canonical item dict with at least keys ``prompt``, ``item_type``,
        and optionally ``choices`` (list of ``{"key": "A", "value": "..."}``).
    lesson_text : str | None
        Optional exposition the student just read. If provided it is
        prepended as a "TODAY'S LESSON" section.

    Returns
    -------
    str
        The formatted user message ready to be sent to the LLM.
    """
    parts: list[str] = []

    # Optional lesson context ------------------------------------------
    if lesson_text:
        parts.append(f"## TODAY'S LESSON\n{lesson_text}")
        parts.append("")  # blank line separator

    # Item body --------------------------------------------------------
    item_type = item.get("item_type", "mcq")
    prompt_text = item.get("prompt", "")

    if item_type == "mcq":
        parts.append(prompt_text)
        parts.append("")
        choices = item.get("choices") or []
        for choice in choices:
            key = choice.get("key", "?")
            value = choice.get("value", "")
            parts.append(f"{key}. {value}")
        parts.append("")
        parts.append("Your answer (single letter):")
    else:
        # FRQ or frq_multipart
        parts.append(prompt_text)
        parts.append("")
        parts.append("Your response:")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# KC description helper
# ---------------------------------------------------------------------------

# Minimal human-readable descriptions for common AP Stats KC codes.
# In production these would be loaded from frameworks.js; for now we use
# a compact mapping so prompts are informative rather than opaque codes.

_KC_DESCRIPTIONS: dict[str, str] = {
    # Unit 1: Exploring One-Variable Data
    "VAR-1.A": "Distinguish types of variables (categorical vs quantitative)",
    "VAR-1.B": "Represent categorical data with frequency tables and bar charts",
    "UNC-1.A": "Describe distributions of quantitative data (shape, center, spread, outliers)",
    "UNC-1.B": "Compare distributions using back-to-back stemplots or parallel dotplots",
    "UNC-1.C": "Calculate and interpret measures of center (mean, median)",
    "UNC-1.D": "Calculate and interpret measures of spread (range, IQR, std dev)",
    "UNC-1.E": "Identify outliers using the 1.5*IQR rule",
    "UNC-1.F": "Describe the effect of changing units on summary statistics",

    # Unit 2: Exploring Two-Variable Data
    "UNC-2.A": "Describe scatterplot patterns (direction, form, strength, outliers)",
    "UNC-2.B": "Interpret correlation coefficient r",
    "UNC-2.C": "Interpret the slope and y-intercept of a LSRL",
    "UNC-2.D": "Use residual plots to assess linearity",
    "UNC-2.E": "Interpret r-squared as the proportion of variation explained",

    # Unit 3: Collecting Data
    "DAT-1.A": "Distinguish observational studies from experiments",
    "DAT-1.B": "Describe sampling methods (SRS, stratified, cluster, systematic)",
    "DAT-1.C": "Identify sources of bias in sampling",
    "DAT-1.D": "Describe principles of experimental design (control, randomization, replication)",
    "DAT-1.E": "Identify confounding variables",

    # Unit 4: Probability, Random Variables, and Probability Distributions
    "VAR-4.A": "Interpret probability as long-run relative frequency",
    "VAR-4.B": "Apply addition and multiplication rules",
    "VAR-4.C": "Calculate conditional probability",
    "VAR-4.D": "Determine independence of events",
    "UNC-3.A": "Calculate mean and standard deviation of a discrete random variable",
    "UNC-3.B": "Apply linear transformations to random variables",
    "UNC-3.C": "Combine independent random variables",

    # Unit 5: Sampling Distributions
    "UNC-4.A": "Describe the sampling distribution of a sample proportion",
    "UNC-4.B": "Describe the sampling distribution of a sample mean (CLT)",
    "UNC-4.C": "Determine whether a Normal approximation is appropriate",

    # Unit 6: Inference for Categorical Data: Proportions
    "UNC-5.A": "Construct and interpret a confidence interval for a proportion",
    "UNC-5.B": "Determine the margin of error and required sample size",
    "VAR-6.A": "State hypotheses for a test about a proportion",
    "VAR-6.B": "Calculate a test statistic for a proportion",
    "VAR-6.C": "Interpret a p-value in context",
    "VAR-6.D": "Make a conclusion based on a significance test",
    "VAR-6.E": "Interpret Type I and Type II errors in context",

    # Unit 7: Inference for Quantitative Data: Means
    "UNC-6.A": "Construct and interpret a confidence interval for a mean",
    "UNC-6.B": "Perform a significance test for a mean",
    "UNC-6.C": "Construct and interpret a confidence interval for a difference of means",
    "UNC-6.D": "Perform a significance test for a difference of means",

    # Unit 8: Inference for Categorical Data: Chi-Square
    "VAR-8.A": "Perform a chi-square goodness-of-fit test",
    "VAR-8.B": "Perform a chi-square test for independence/homogeneity",

    # Unit 9: Inference for Quantitative Data: Slopes
    "UNC-9.A": "Construct and interpret a confidence interval for a slope",
    "UNC-9.B": "Perform a significance test for a slope",
}


def _kc_description(kc_id: str) -> str:
    """Return a human-readable description for a KC id, with fallback."""
    return _KC_DESCRIPTIONS.get(kc_id, f"Knowledge component {kc_id}")
