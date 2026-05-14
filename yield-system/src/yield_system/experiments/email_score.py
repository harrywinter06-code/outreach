"""Experiment D — Email-domain compliance scoring (MX/SPF/DMARC/BIMI/DNSSEC)."""
from dataclasses import dataclass
from typing import Literal

import dns.exception
import dns.resolver
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from yield_system.auth import assert_within_daily_limit, require_api_key
from yield_system.log import post_log, pre_log

EXPERIMENT = "email"
router = APIRouter(prefix="/v1/domain", tags=[EXPERIMENT])

Grade = Literal["A", "B", "C", "D", "E", "F"]


class DomainScore(BaseModel):
    domain: str
    mx: list[str]
    spf: str | None
    dmarc: str | None
    bimi: str | None
    dnssec: bool
    score: Grade
    points: int
    recommendations: list[str]


@dataclass
class DnsLookup:
    mx: list[str]
    spf: str | None
    dmarc: str | None
    bimi: str | None
    dnssec: bool


_RESOLVER = dns.resolver.Resolver()
_RESOLVER.timeout = 3.0
_RESOLVER.lifetime = 5.0


def _txt(name: str, contains: str) -> str | None:
    try:
        answers = _RESOLVER.resolve(name, "TXT")
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.exception.DNSException):
        return None
    for rdata in answers:
        joined = "".join(s.decode() if isinstance(s, bytes) else s for s in rdata.strings)
        if contains.lower() in joined.lower():
            return joined
    return None


def _mx(domain: str) -> list[str]:
    try:
        answers = _RESOLVER.resolve(domain, "MX")
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.exception.DNSException):
        return []
    return sorted(str(r.exchange).rstrip(".") for r in answers)


def _has_dnssec(domain: str) -> bool:
    try:
        answers = _RESOLVER.resolve(domain, "DNSKEY")
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.exception.DNSException):
        return False
    return len(answers) > 0


def lookup(domain: str) -> DnsLookup:
    return DnsLookup(
        mx=_mx(domain),
        spf=_txt(domain, "v=spf1"),
        dmarc=_txt(f"_dmarc.{domain}", "v=DMARC1"),
        bimi=_txt(f"default._bimi.{domain}", "v=BIMI1"),
        dnssec=_has_dnssec(domain),
    )


def score(lookup_result: DnsLookup) -> tuple[Grade, int, list[str]]:
    points = 0
    recs: list[str] = []

    if lookup_result.mx:
        points += 20
    else:
        recs.append("no MX records — domain cannot receive mail")

    if lookup_result.spf:
        points += 20
        if " -all" in lookup_result.spf:
            points += 5
        elif " ~all" in lookup_result.spf:
            points += 3
        else:
            recs.append("SPF policy is too permissive — use -all or ~all")
    else:
        recs.append("missing SPF — add v=spf1 record")

    if lookup_result.dmarc:
        points += 20
        if "p=reject" in lookup_result.dmarc:
            points += 10
        elif "p=quarantine" in lookup_result.dmarc:
            points += 5
        else:
            recs.append("DMARC policy is p=none — upgrade to quarantine or reject")
    else:
        recs.append("missing DMARC — add _dmarc TXT record")

    if lookup_result.bimi:
        points += 10
    else:
        recs.append("missing BIMI — optional but improves deliverability with brand logo")

    if lookup_result.dnssec:
        points += 15
    else:
        recs.append("DNSSEC not enabled — ask DNS provider to sign the zone")

    grade: Grade = (
        "A" if points >= 90
        else "B" if points >= 75
        else "C" if points >= 55
        else "D" if points >= 35
        else "E" if points >= 20
        else "F"
    )
    return grade, points, recs


def _auth(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict:
    return require_api_key(EXPERIMENT, x_api_key)


@router.get("/{domain}")
def get_domain_score(domain: str, customer: dict = Depends(_auth)) -> DomainScore:
    domain = domain.lower().strip()
    if not domain or "." not in domain or len(domain) > 253:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid domain")
    assert_within_daily_limit(customer["customer_id"], customer["plan"])
    call_id = pre_log(
        experiment=f"customer:{customer['customer_id']}",
        action=f"domain_score:{domain}",
        expected_cost_gbp=0.0,
        expected_outcome="200_score",
    )
    result = lookup(domain)
    grade, points, recs = score(result)
    post_log(call_id, f"200_{grade}")
    return DomainScore(
        domain=domain,
        mx=result.mx,
        spf=result.spf,
        dmarc=result.dmarc,
        bimi=result.bimi,
        dnssec=result.dnssec,
        score=grade,
        points=points,
        recommendations=recs,
    )
