import os
import sys
import argparse
import logging
import random
from datetime import datetime
from rich.console import Console
from dotenv import load_dotenv

# Ensure custom source path is registered
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

import config
from modules.whatsmyname.list_operations import checkUpdates
from modules.core.username import verifyUsername
from modules.core.email import verifyEmail
from modules.utils.userAgent import getRandomUserAgent
from modules.export.file_operations import createSaveDirectory
from modules.export.csv import saveToCsv
from modules.export.pdf import saveToPdf
from modules.export.json import saveToJson
from modules.utils.file_operations import isFile, getLinesFromFile
from modules.utils.permute import Permute

load_dotenv()

def parse_args():
    p = argparse.ArgumentParser(prog="whitebird", description="OSINT tool to search for accounts by username/email.")
    p.add_argument("-u", "--username", nargs="*", type=str, help="Usernames to search.")
    p.add_argument("-uf", "--username-file", help="File with usernames.")
    p.add_argument("--permute", action="store_true", help="Permute usernames (strict).")
    p.add_argument("--permuteall", action="store_true", help="Permute usernames (all).")
    p.add_argument("-e", "--email", nargs="*", type=str, help="Emails to search.")
    p.add_argument("-ef", "--email-file", help="File with emails.")
    
    for fmt in ["csv", "pdf", "json"]:
        p.add_argument(f"--{fmt}", action="store_true", help=f"Generate {fmt.upper()} report.")
        
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose output.")
    p.add_argument("-ai", "--ai", action="store_true", help="Use AI features.")
    p.add_argument("--setup-ai", action="store_true", help="Configure AI API key.")
    p.add_argument("--filter", help='Filter sites (e.g. "cat=social").')
    p.add_argument("--no-nsfw", action="store_true", help="Remove NSFW sites.")
    p.add_argument("--dump", action="store_true", help="Dump HTML content.")
    p.add_argument("--proxy", help="HTTP proxy.")
    p.add_argument("--timeout", type=int, default=30, help="Request timeout.")
    p.add_argument("--max-concurrent-requests", type=int, default=30, help="Max concurrent requests.")
    p.add_argument("--no-update", action="store_true", help="Skip site list updates.")
    p.add_argument("--about", action="store_true", help="Show about info.")
    return p.parse_args()

def main():
    os.makedirs("logs", exist_ok=True)
    
    # Initialize basic logging fallback if config path isn't established
    log_path = getattr(config, "LOG_PATH", "logs/whitebird.log")
    logging.basicConfig(filename=log_path, level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")
    
    args = parse_args()
    
    # Safely port arguments to the config workspace
    for k, v in vars(args).items():
        setattr(config, k, v)
        
    config.instagram_session_id = os.getenv("INSTAGRAM_SESSION_ID")
    config.api_url = os.getenv("API_URL")
    config.console = Console()
    config.userAgent = getRandomUserAgent(config)
    config.usernameFoundAccounts = config.emailFoundAccounts = config.currentUser = config.currentEmail = None

    lines = getLinesFromFile("assets/text/splash.txt")
    splash = random.choice(lines) if lines else ""
    
    # Minimalist status line instead of bulky ASCII
    config.console.print(f"[bold bright_blue][*] WHITEBIRD OSINT FRAMEWORK[/bold bright_blue] | [white]{splash}[/white] | [red]SUB TO RYEN STUFF ON YOUTUBE[/red]")
    
    if config.about:
        config.console.print("\nDescription: Whitebird is an OSINT tool that performs reverse searches on usernames and emails.\n")
        sys.exit(0)
        
    if not any([config.username, config.email, config.username_file, config.email_file, config.setup_ai]):
        config.console.print("[bold red] Error:[/bold red] Either --username, --email, or AI setup configuration options are required.")
        sys.exit(1)
        
    if (config.permute or config.permuteall) and not config.username:
        config.console.print("[bold red] Error:[/bold red] Permutations require tracking targeting elements via --username")
        sys.exit(1)
        
    if not config.no_update:
        checkUpdates(config)

    def handle_ai(flag, prompt_msg, fetch_func):
        if getattr(config, flag, False):
            config.console.print(f"[yellow1]:exclamation: {prompt_msg}[/yellow1] [Y/n]", end="")
            if input(" > ").strip().lower() not in ["", "y"]:
                config.console.print(":stop_sign: Cancelled by user.")
                sys.exit(0)
            if not fetch_func(config):
                sys.exit(1)

    handle_ai("ai", "By proceeding, you consent to share found site names with Whitebird AI.", 
              lambda c: __import__('modules.ai.key_manager', fromlist=['load_api_key_from_file']).load_api_key_from_file(c))
              
    handle_ai("setup_ai", "By continuing, your IP is registered for API key management.", 
              lambda c: __import__('modules.ai.key_manager', fromlist=['fetch_api_key_from_server']).fetch_api_key_from_server(c))

    def process(target_type):
        file_attr = f"{target_type}_file"
        items_attr = target_type
        found_attr = f"{target_type}FoundAccounts"
        current_attr = f"current{target_type.capitalize()}"
        
        file_path = getattr(config, file_attr, None)
        if file_path:
            if isFile(file_path):
                setattr(config, items_attr, getLinesFromFile(file_path))
                config.console.print(f':glasses: Successfully loaded {len(getattr(config, items_attr))} {target_type}s from "{file_path}"')
            else:
                config.console.print(f' Could not read file "{file_path}"')
                sys.exit(1)
                
        items = getattr(config, items_attr, None)
        if not items:
            return
            
        if target_type == "username" and (config.permute or config.permuteall) and len(items) > 1:
            items = Permute(items).gather("all" if config.permuteall else "strict")
            setattr(config, items_attr, items)
            config.console.print(f":glasses: Loaded {len(items)} permuted usernames.")
            
        for item in items:
            setattr(config, current_attr, item)
            if any([config.dump, config.csv, config.pdf, config.json]):
                createSaveDirectory(config)
                
            (verifyUsername if target_type == "username" else verifyEmail)(item, config)
            accounts = getattr(config, found_attr, None)
            
            if config.ai:
                if accounts and len(accounts) > 2:
                    from modules.ai.client import send_prompt
                    names = [a.get("name", "") for a in accounts]
                    if names and (data := send_prompt(", ".join(names), config)):
                        config.ai_analysis = data
                else:
                    config.console.print(":warning: Not enough accounts found for AI analysis.")
                    
            if accounts:
                if config.csv: saveToCsv(accounts, config)
                if config.pdf: saveToPdf(accounts, target_type, config)
                if config.json: saveToJson(accounts, config)
                
            setattr(config, current_attr, None)
            setattr(config, found_attr, None)

    process("username")
    process("email")

if __name__ == "__main__":
    main()
