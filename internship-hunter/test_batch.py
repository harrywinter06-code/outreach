"""Smoke-test script — research 5 real companies and print results.

This makes live network calls (Hunter.io, Jina Reader, Anthropic) and is
deliberately separate from the pytest suite. Run with `python test_batch.py`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from generate import estimate_cost, generate_cold_email, parse_cold_email  # noqa: E402
from research import research_batch  # noqa: E402

TEST_COMPANIES = [
    {"name": "Attest",          "website": "attest.com",          "sector": "Data/Research",     "notes": "", "has_ucl_alumni": False},
    {"name": "Faculty AI",      "website": "faculty.ai",          "sector": "AI Consulting",      "notes": "", "has_ucl_alumni": False},
    {"name": "Cytora",          "website": "cytora.com",          "sector": "AI/Insurance",       "notes": "", "has_ucl_alumni": False},
    {"name": "Conjura",         "website": "conjura.com",         "sector": "Data/Ecommerce",     "notes": "", "has_ucl_alumni": False},
    {"name": "ComplyAdvantage", "website": "complyadvantage.com", "sector": "Data/Compliance",    "notes": "", "has_ucl_alumni": False},
]

SEP = "-" * 70

def on_progress(i, total, name, result):
    print(f"  [{i}/{total}] {name} -> {result.success}")

print(f"\n{SEP}")
print("BATCH RESEARCH TEST")
print(f"{SEP}\n")

results, credits_exhausted = research_batch(TEST_COMPANIES, on_progress=on_progress)

if credits_exhausted:
    print("\n⚠  Hunter credits exhausted mid-batch\n")

total_cost = 0.0

for r in results:
    print(f"\n{SEP}")
    print(f"  {r.company.upper()}  [{r.success}]")
    print(SEP)
    print(f"  Contact : {r.contact_first} {r.contact_last}".strip())
    print(f"  Email   : {r.contact_email or '(none)'} [{r.email_method or '—'}] confidence={r.email_confidence or '—'}")
    print(f"  Notes   : {r.notes or '—'}")
    print()
    if r.context:
        print("  CONTEXT:")
        for line in r.context.split("\n"):
            print(f"    {line}")
    print()

    if r.success == "full":
        print("  GENERATING EMAIL...")
        try:
            raw, usage = generate_cold_email(
                r.company,
                "data / analyst / ML internship",
                r.context,
                r.contact_first,
            )
            subject, body = parse_cold_email(raw)
            cost = estimate_cost(usage)
            total_cost += cost
            print(f"  Subject : {subject}")
            print()
            print("  Body:")
            for line in body.split("\n"):
                print(f"    {line}")
            print(f"\n  Cost: ${cost:.5f}  |  tokens in={usage['input_tokens']} out={usage['output_tokens']} cache_read={usage['cache_read']} cache_write={usage['cache_write']}")
        except Exception as e:
            print(f"  ❌ Email generation failed: {e}")
    else:
        print(f"  (skipping email — success={r.success})")

print(f"\n{SEP}")
print(f"TOTAL EMAIL GENERATION COST: ${total_cost:.5f}")
print(f"{SEP}\n")
