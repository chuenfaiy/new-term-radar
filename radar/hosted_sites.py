"""Signal ③c: hosted subdomains whose estimated search traffic is growing.

DataForSEO Labs' subdomains endpoint lists ranking subdomains of a hosting
domain. Compare weekly snapshots instead of guessing a site's launch date.
The metric is estimated monthly *organic search* traffic, not Similarweb's
all-channel visits. A missing previous snapshot only establishes a baseline.
"""
from __future__ import annotations

from pathlib import Path

from . import aisa, snap
from .i18n import t
from .new_sites import name_terms

TOOL = "post_dataforseo_labs_google_subdomains_live"


def _calls(c: dict) -> list[dict]:
    return [{"call_id": host, "tool": TOOL, "arguments": {"body": [{
        "target": host, "language_code": "en", "location_code": c["location_code"],
        "item_types": ["organic"], "limit": c["limit"],
        "filters": [["metrics.organic.etv", ">=", c["min_etv"]], "and",
                    ["metrics.organic.count", ">=", c["min_keywords"]]],
        "order_by": ["metrics.organic.etv,desc"],
    }]}} for host in c["hosts"]]


def _items(answer: dict) -> list[dict]:
    tasks = answer.get("tasks") or []
    task = tasks[0] if tasks else {}
    if task.get("status_code") != 20000:
        raise ValueError(f"subdomains API: {task.get('status_message') or task.get('status_code') or 'no task'}")
    result = task.get("result") or []
    return ((result[0] or {}).get("items") or []) if result else []


def hosted_sites(cfg: dict, state: Path) -> dict:
    c = cfg["hosted_sites"]
    hosts = c["hosts"]
    if not hosts:
        return {"skipped": True}
    data, cost = aisa.call_all(_calls(c))
    if not data:
        raise ValueError("subdomains API returned no successful hosts")
    path = state / "hosted_sites.json.gz"
    before = snap.load(path) or {}
    current = dict(before)
    rows, errors, baselines = [], {}, []
    for host in hosts:
        if host not in data:
            errors[host] = "subdomains API call failed"
            continue
        try:
            items = _items(data[host])
        except ValueError as exc:
            errors[host] = str(exc)
            continue
        values = {}
        for item in items:
            domain = str(item.get("subdomain") or "").lower().rstrip(".")
            if not domain.endswith("." + host) or domain.count(".") != host.count(".") + 1:
                continue  # not the hosting domain itself or a nested preview subdomain
            organic = (item.get("metrics") or {}).get("organic") or {}
            etv, keywords = int(organic.get("etv") or 0), int(organic.get("count") or 0)
            if etv < c["min_etv"] or keywords < c["min_keywords"]:
                continue
            values[domain] = {"etv": etv, "keywords": keywords}
            previous = before.get(host, {}).get(domain)
            if host not in before:
                continue
            old = previous["etv"] if previous else 0
            delta = etv - old
            if delta < c["min_delta"] or (old and etv < old * c["min_ratio"]):
                continue
            rows.append({"domain": domain, "host": host, "etv": etv, "previous_etv": old,
                         "delta": delta, "keywords": keywords, "new": previous is None})
        current[host] = values
        if host not in before:
            baselines.append(host)
    if current != before:
        snap.save(path, current)
    rows.sort(key=lambda r: (-r["delta"], -r["etv"]))
    terms = [{"term": word, "recent": 1, "examples": [r["domain"]],
              "note": t("note_hosted", domain=r["domain"], etv=r["etv"], delta=r["delta"])}
             for r in rows for word in name_terms(r["domain"][:-(len(r["host"]) + 1)])]
    return {"hosts": len(hosts), "answered": len(data), "cost_micros": cost,
            "sites": rows, "terms": terms, "baselines": baselines, "errors": errors}
