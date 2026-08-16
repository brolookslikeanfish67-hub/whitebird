import os
import sys
import time
import asyncio
import logging
from pathlib import Path
import aiohttp
from rich.markup import escape
from rich.text import Text
from rich.live import Live

# Optimized path insertion using Path objects
sys.path.append(str(Path(__file__).resolve().parents[3] / "src"))

from ..utils.filter import filterFoundAccounts, applyFilters
from ..utils.parse import extractMetadata
from ..utils.http_client import do_async_request
from ..whatsmyname.list_operations import readList
from ..utils.input import processInput
from ..utils.log import logError
from ..export.dump import dumpContent
from ..utils.precheck import perform_pre_check

async def checkSite(site, method, url, session, semaphore, config, data=None, headers=None):
    """Verifies account existence based on target site definitions."""
    returnData = {
        "name": site["name"],
        "url": url,
        "category": site["cat"],
        "status": "NONE",
        "metadata": None,
    }
    
    async with semaphore:
        if site.get("pre_check"):
            headers = perform_pre_check(site["pre_check"], headers, config)
            if headers is False:
                returnData["status"] = "ERROR"
                return returnData

        response = await do_async_request(method, url, session, config, data, headers)
        if not response:
            returnData["status"] = "ERROR"
            return returnData

        try:
            # Explicit boolean evaluation for clarity
            is_error_string = site["e_string"] in response["content"]
            is_error_code = site["e_code"] == response["status_code"]
            is_misleading_string = site["m_string"] not in response["content"] if site.get("m_string") else True
            is_misleading_code = site["m_code"] != response["status_code"] if site.get("m_code") else True

            if is_error_string and is_error_code and is_misleading_string and is_misleading_code:
                returnData["status"] = "FOUND"
                # Fixed raw formatting and URL-encoded emoji bugs
                config.console.print(f" ✔️  [[cyan1]{escape(site['name'])}[/cyan1]] [bright_white]{response['url']}[/bright_white]")
                
                if site.get("metadata"):
                    extracted = extractMetadata(site["metadata"], response, site["name"], config)
                    extracted.sort(key=lambda x: x.get("name", ""))
                    returnData["metadata"] = extracted

                if config.dump:
                    path = os.path.join(config.saveDirectory, f"dump_{config.currentEmail}")
                    if dumpContent(path, site, response, config) and config.verbose:
                        config.console.print(" 💾 Saved HTML data from found account")
            else:
                returnData["status"] = "NOT-FOUND"
                if config.verbose:
                    config.console.print(f" ❌ [[blue]{escape(site['name'])}[/blue]] [bright_white]{response['url']}[/bright_white]")
                    
            return returnData
            
        except Exception as e:
            logError(e, f"Couldn't check {site['name']} {url}", config)
            returnData["status"] = "ERROR"
            return returnData

async def fetchResults(email, config):
    """Orchestrates concurrent async requests with live progress updating."""
    # Reuses config.email_sites directly to bypass unnecessary secondary list reads
    total_sites = len(config.email_sites)
    completed = 0
    results = []

    def render():
        percent = int((completed / total_sites) * 100) if total_sites else 100
        return Text.from_markup(
            f"🛰️  Enumerating accounts with email [cyan1]\"{escape(email)}\"[/cyan1] — [green1]{percent}%[/green1] ({completed}/{total_sites})"
        )

    # Use client connection pooling strategies
    timeout = aiohttp.ClientTimeout(total=config.timeout if hasattr(config, 'timeout') else 30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        semaphore = asyncio.Semaphore(config.max_concurrent_requests)

        async def wrappedCheck(site):
            nonlocal completed
            # Safe dict lookup verification
            input_op = site.get("input_operation")
            email_processed = processInput(email, input_op, config) if input_op else email
            
            url = site["uri_check"].replace("{account}", email_processed)
            data = site["data"].replace("{account}", email_processed) if site.get("data") else None
            headers = site.get("headers")

            res = await checkSite(
                site=site, method=site["method"], url=url, session=session,
                semaphore=semaphore, config=config, data=data, headers=headers
            )
            completed += 1
            return res

        tasks = [wrappedCheck(site) for site in config.email_sites]
        
        with Live(render(), refresh_per_second=10, console=config.console) as live:
            for coro in asyncio.as_completed(tasks):
                result = await coro
                results.append(result)
                live.update(render())

    return {"results": results, "email": email}

def verifyEmail(email, config):
    """Prepares targeting matrices and measures script metrics."""
    # Single read operation executed synchronously at setup entrypoint
    data = readList("email", config)
    config.email_sites = applyFilters(data.get("sites", []), config)
    
    if not config.email_sites:
        config.console.print("[yellow]⚠️  No operational target sites matched configuration filters.[/yellow]")
        return []

    start_time = time.time()
    
    # Safe asyncio loop execution guard
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        results = loop.run_until_complete(fetchResults(email, config))
    else:
        results = asyncio.run(fetchResults(email, config))
        
    end_time = time.time()
    elapsed = round(end_time - start_time, 1)

    config.console.print(f"🏁 Check completed in {elapsed} seconds ({len(results['results'])} sites)")
    
    if config.dump and getattr(config, 'dateRaw', None):
        config.console.print(f"💾 Dump content saved to '[cyan1]{email}_{config.dateRaw}_blackbird/dump_{email}'[/cyan1]")

    foundAccounts = list(filter(filterFoundAccounts, results["results"]))
    config.emailFoundAccounts = foundAccounts
    
    if not foundAccounts:
        config.console.print("⭕ No accounts were found for the given email")
        
    return foundAccounts
