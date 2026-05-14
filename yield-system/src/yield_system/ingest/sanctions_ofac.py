"""OFAC SDN ingester. Run daily via cron.

Uses iterparse to stream-parse the XML and clear processed elements,
keeping peak memory well under 512 MB even for the full SDN list.
Namespace is extracted from the root element at parse time — immune to
future URL migrations that change the namespace URI.
"""
import io

import httpx
from defusedxml.ElementTree import iterparse

from yield_system.experiments.sanctions import upsert_entry
from yield_system.log import post_log, pre_log

OFAC_URL = "https://sanctionslistservice.ofac.treas.gov/api/publicationpreview/exports/sdn.xml"


def _ns(root_tag: str) -> str:
    """Extract '{namespace}' prefix from a Clark-notation tag, or '' if none."""
    if root_tag.startswith("{"):
        return "{" + root_tag.split("}")[0][1:] + "}"
    return ""


def _text(elem, tag: str) -> str:
    child = elem.find(tag)
    return (child.text or "").strip() if child is not None else ""


def ingest(url: str = OFAC_URL, fetcher=None) -> int:
    """Returns count of newly-added entries."""
    call_id = pre_log(
        experiment="sanctions",
        action="ingest:ofac",
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

        added = 0
        total = 0
        context = iterparse(io.BytesIO(xml_bytes), events=("start", "end"))
        context_iter = iter(context)
        _, root = next(context_iter)  # root = sdnList

        ns = _ns(root.tag)
        entry_tag = f"{ns}sdnEntry"

        for event, elem in context_iter:
            if event != "end" or elem.tag != entry_tag:
                continue

            uid = _text(elem, f"{ns}uid")
            first = _text(elem, f"{ns}firstName")
            last = _text(elem, f"{ns}lastName")
            name = f"{first} {last}".strip() if (first or last) else ""

            program = None
            prog_list = elem.find(f"{ns}programList")
            if prog_list is not None:
                prog_el = prog_list.find(f"{ns}program")
                program = prog_el.text if prog_el is not None else None

            aliases: list[str] = []
            aka_list = elem.find(f"{ns}akaList")
            if aka_list is not None:
                for aka in aka_list.findall(f"{ns}aka"):
                    a_first = _text(aka, f"{ns}firstName")
                    a_last = _text(aka, f"{ns}lastName")
                    alias = f"{a_first} {a_last}".strip()
                    if alias:
                        aliases.append(alias)

            if uid and name:
                total += 1
                if upsert_entry(
                    source="ofac",
                    source_id=uid,
                    name=name,
                    aliases=aliases,
                    program=program,
                ):
                    added += 1

            root.clear()  # free parsed element, keep only root shell

        post_log(call_id, f"ingested_{total}_added_{added}")
        return added
    except httpx.HTTPError as ex:
        post_log(call_id, f"http_error:{type(ex).__name__}")
        raise
