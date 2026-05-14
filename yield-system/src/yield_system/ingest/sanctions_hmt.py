"""UK HMT OFSI ConList XML ingester (2022format). Run daily alongside OFAC.

The 2022format XML lists each name variation as a separate FinancialSanctionsTarget
row sharing the same UKSanctionsListRef. We group by ref, pick the first name as
canonical, and store the rest as aliases.
"""
import io
from collections import defaultdict

import httpx
from defusedxml.ElementTree import iterparse

from yield_system.experiments.sanctions import upsert_entry
from yield_system.log import post_log, pre_log

HMT_URL = "https://ofsistorage.blob.core.windows.net/publishlive/2022format/ConList.xml"


def _ns(root_tag: str) -> str:
    if root_tag.startswith("{"):
        return "{" + root_tag.split("}")[0][1:] + "}"
    return ""


def _text(elem, tag: str) -> str:
    child = elem.find(tag)
    return (child.text or "").strip() if child is not None else ""


def ingest(url: str = HMT_URL, fetcher=None) -> int:
    """Returns count of newly-added entries."""
    call_id = pre_log(
        experiment="sanctions",
        action="ingest:hmt",
        expected_cost_gbp=0.0,
        expected_outcome="list_refreshed",
    )
    try:
        if fetcher is None:
            r = httpx.get(url, timeout=60.0, follow_redirects=True)
            r.raise_for_status()
            xml_bytes = r.content
        else:
            xml_bytes = fetcher()

        # Collect all name variants per UKSanctionsListRef before upserting,
        # because multiple FinancialSanctionsTarget rows share the same ref.
        entries: dict[str, list[tuple[str, str | None]]] = defaultdict(list)

        context = iterparse(io.BytesIO(xml_bytes), events=("start", "end"))
        context_iter = iter(context)
        _, root = next(context_iter)

        ns = _ns(root.tag)
        entry_tag = f"{ns}FinancialSanctionsTarget"

        for event, elem in context_iter:
            if event != "end" or elem.tag != entry_tag:
                continue

            uid = _text(elem, f"{ns}UKSanctionsListRef")
            org = _text(elem, f"{ns}Name6")
            if org:
                name = org
            else:
                parts = [_text(elem, f"{ns}name{i}") for i in range(1, 6)]
                name = " ".join(p for p in parts if p)

            program = _text(elem, f"{ns}RegimeName") or None

            if uid and name:
                entries[uid].append((name, program))

            root.clear()

        added = 0
        for uid, variants in entries.items():
            canonical_name = variants[0][0]
            program = variants[0][1]
            seen: set[str] = {canonical_name}
            aliases: list[str] = []
            for v_name, _ in variants[1:]:
                if v_name not in seen:
                    aliases.append(v_name)
                    seen.add(v_name)
            if upsert_entry(
                source="hmt",
                source_id=uid,
                name=canonical_name,
                aliases=aliases,
                program=program,
            ):
                added += 1

        total = len(entries)
        post_log(call_id, f"ingested_{total}_added_{added}")
        return added
    except httpx.HTTPError as ex:
        post_log(call_id, f"http_error:{type(ex).__name__}")
        raise
