"""UK HMT OFSI ConList XML ingester. Run daily alongside OFAC.

Uses iterparse to stream-parse to avoid loading the full tree.
"""
import io

import httpx
from defusedxml.ElementTree import iterparse

from yield_system.experiments.sanctions import upsert_entry
from yield_system.log import post_log, pre_log

HMT_URL = "https://ofsistorage.blob.core.windows.net/publishlive/2022format/ConList.xml"
_ENTRY_TAG = "Designation"


def _text(elem, *tags: str) -> str:
    for tag in tags:
        child = elem.find(tag)
        if child is not None and child.text:
            return child.text.strip()
    return ""


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
            r = httpx.get(url, timeout=60.0)
            r.raise_for_status()
            xml_bytes = r.content
        else:
            xml_bytes = fetcher()

        added = 0
        total = 0
        context = iterparse(io.BytesIO(xml_bytes), events=("start", "end"))
        context_iter = iter(context)
        _, root = next(context_iter)  # root = ArrayOfDesignation

        for event, elem in context_iter:
            if event != "end" or elem.tag != _ENTRY_TAG:
                continue

            uid = _text(elem, "UniqueID", "UniquID")
            names_el = elem.find("Names")
            if names_el is None:
                root.clear()
                continue

            org = _text(names_el, "Name6")
            if org:
                name = org
            else:
                parts = [
                    _text(names_el, "Name2"),  # first
                    _text(names_el, "Name3"),  # middle
                    _text(names_el, "Name4"),  # last
                ]
                name = " ".join(p for p in parts if p)

            if not name or not uid:
                root.clear()
                continue

            program = _text(elem, "Regime")

            aliases: list[str] = []
            aliases_el = elem.find("Aliases")
            if aliases_el is not None:
                for alias in aliases_el.findall("Alias"):
                    a = _text(alias, "AliasName")
                    if a and a != name:
                        aliases.append(a)

            total += 1
            if upsert_entry(
                source="hmt",
                source_id=uid,
                name=name,
                aliases=aliases,
                program=program,
            ):
                added += 1

            root.clear()

        post_log(call_id, f"ingested_{total}_added_{added}")
        return added
    except httpx.HTTPError as ex:
        post_log(call_id, f"http_error:{type(ex).__name__}")
        raise
