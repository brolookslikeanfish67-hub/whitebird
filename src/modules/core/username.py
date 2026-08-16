import asyncio, os, sys, time, logging, aiohttp
from pathlib import Path
from rich.markup import escape
from rich.text import Text
from rich.live import Live

sys.path.append(str(Path(__file__).resolve().parents / "src"))
from ..whatsmyname.list_operations import readList
from ..utils.parse import extractMetadata, remove_duplicates
from ..utils.filter import filterFoundAccounts, applyFilters
from ..utils.http_client import do_async_request
from ..utils.log import logError
from ..export.dump import dumpContent
from ..sites.instagram import get_instagram_account_info

async def checkSite(site, url, session, sem, cfg, q):
    """Unified isolated fault-walled target validation network pipeline."""
    res = {"name": site["name"], "url": url, "category": site["cat"], "status": "NONE", "metadata": None}
    if not url: return {**res, "status": "MALFORMED"}
    
    async with sem:
        resp = await asyncio.shield(do_async_request("GET", url, session, cfg))
        if not resp: return {**res, "status": "NET-ERROR"}
        
        try:
            hit = (site["e_string"] in resp["content"]) and (site["e_code"] == resp["status_code"])
            m_str, m_code = site.get("m_string"), site.get("m_code")
            is_m = (m_str not in resp["content"]) and (m_code != resp["status_code"]) if (m_str and m_code) else True
            
            if hit and is_m:
                cfg.console.print(f" ✔️  [[cyan1]{escape(site['name'])}[/cyan1]] [bright_white]{resp.get('url', url)}[/]")
                meta = []
                
                # Multi-Source Metadata Unpacking Array Matrix
                reg = getattr(cfg, "metadata_params", {}).get("sites", {})
                if site["name"] in reg: meta.extend(extractMetadata(reg[site["name"]], resp, site["name"], cfg) or [])
                if getattr(cfg, "ai", 0) and getattr(cfg, "aiModel", 0):
                    try: meta.extend(__import__('..utils.ai_processing', fromlist=['ex']).ex(cfg, site, resp["content"], resp["json"]) or [])
                    except Exception: pass
                if site["name"] == "Instagram" and getattr(cfg, "instagram_session_id", None):
                    meta.extend(get_instagram_account_info(q, cfg.instagram_session_id, cfg) or [])
                    
                if meta:
                    meta = remove_duplicates(meta)
                    meta.sort(key=lambda x: x.get("name", "").lower())
                    res["metadata"] = meta
                
                if cfg.dump: dumpContent(os.path.join(getattr(cfg, "saveDirectory", "logs"), f"dump_{q}"), site, resp, cfg)
                return {**res, "status": "FOUND"}
            
            if cfg.verbose: cfg.console.print(f" ❌ [[blue]{escape(site['name'])}[/blue]] [bright_white]{resp.get('url', url)}[/]")
            return {**res, "status": "NOT-FOUND"}
        except Exception as e:
            logError(e, f"Crash: {site['name']}", cfg)
            return {**res, "status": "CRASH"}

async def search(q, cfg):
    """Highly optimized parallel target worker orchestration block."""
    sites, done, out = getattr(cfg, "username_sites", []), 0, []
    if not sites: return {"results": [], "username": q}
    
    sem = asyncio.Semaphore(cfg.max_concurrent_requests)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=getattr(cfg, "timeout", 30))) as sess:
        async def wrap(s):
            nonlocal done
            r = await checkSite(s, s["uri_check"].replace("{account}", q), sess, sem, cfg, q)
            done += 1
            live.update(Text.from_markup(f"  Scanning: [cyan1]\"{escape(q)}\"[/] — [green]{int((done/len(sites))*100)}%[/] ({done}/{len(sites)})"))
            return r
            
        with Live(Text("  Starting..."), refresh_per_second=10, console=cfg.console) as live:
            out = await asyncio.gather(*[wrap(s) for s in sites], return_exceptions=True)
    return {"results": [r for r in out if isinstance(r, dict)], "username": q}

def verifyUsername(username, config, sitesToSearch=None, metadata_params=None):
    """Device-agnostic operational entrypoint bridging execution layers."""
    if None in (sitesToSearch, metadata_params):
        raw = readList("username", config)
        sitesToSearch, config.metadata_params = raw.get("sites", []), readList("metadata", config)
    else: config.metadata_params = metadata_params
    
    config.username_sites = applyFilters(sitesToSearch, config)
    if not config.username_sites: return config.console.print("[p] No operational matches.[/]") or []
    
    config.currentUser, start = username, time.time()
    try: loop = asyncio.get_running_loop()
    except RuntimeError: loop = None
    
    res = loop.run_until_complete(search(username, config)) if loop and loop.is_running() else asyncio.run(search(username, config))
    config.console.print(f" Done in {round(time.time() - start, 1)}s.")
    
    config.usernameFoundAccounts = list(filter(filterFoundAccounts, res.get("results", [])))
    if not config.usernameFoundAccounts: config.console.print("⭕ No identity footprints found.")
    return config.usernameFoundAccounts
