"""
Universal Login + Demo Scrape (Selenium + ChromeDriver)
Plus: auto output structure + append without duplicates (per website, per day)

What it does
- Opens any target URL
- Detects login UI (page or modal)
- Fills identifier (email/phone/username) and password
- Handles:
  1) Modal login on same URL (Daraz, Zameen-style)
  2) Login page with identifier+password on same page
  3) Two-step login (identifier -> Continue/Next -> password -> Submit)
- Detects common blockers (CAPTCHA/Cloudflare) and prints reason

Output behavior (your request)
- Automatically creates this structure:
  outputs/
    <site>/
      <site>_<YYYY-MM-DD>.csv
      <site>_<YYYY-MM-DD>.json
- If you run the script multiple times for the same website on the same date:
  - it APPENDS
  - it REMOVES duplicates using a stable hash (_record_hash)

Install:
  pip install selenium webdriver-manager pandas

Run:
  python universal_login_demo_scraper.py
"""

import os
import json
import re
import time
import hashlib
from dataclasses import dataclass
from datetime import datetime
from getpass import getpass
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    ElementClickInterceptedException,
    StaleElementReferenceException,
)

from webdriver_manager.chrome import ChromeDriverManager


# -----------------------------
# CONFIG
# -----------------------------
@dataclass
class ScraperConfig:
    headless: bool = False
    wait_timeout: int = 25
    page_load_timeout: int = 45
    keep_open_on_finish: bool = True

    # Output
    outputs_base_dir: str = "outputs"
    date_fmt: str = "%Y-%m-%d"
    scrape_emails: bool = True


LOGIN_KEYWORDS = [
    "log in", "login", "sign in", "signin", "account", "my account", "continue with email", "continue"
]
BTN_KEYWORDS_CONTINUE = ["continue", "next", "email", "send", "proceed"]
BTN_KEYWORDS_SUBMIT = ["log in", "login", "sign in", "signin", "submit"]


# -----------------------------
# UTIL
# -----------------------------
def norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def get_domain(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""


def wait_ready(driver: webdriver.Chrome, timeout: int):
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )


def click_with_fallback(driver: webdriver.Chrome, el) -> bool:
    try:
        el.click()
        return True
    except (ElementClickInterceptedException, WebDriverException):
        try:
            driver.execute_script("arguments[0].click();", el)
            return True
        except Exception:
            return False


def find_visible_input_in_scope(scope, css_list: List[str]):
    for css in css_list:
        try:
            el = scope.find_element(By.CSS_SELECTOR, css)
            if el.is_displayed() and el.is_enabled():
                return el
        except Exception:
            continue
    return None


def safe_filename(name: str) -> str:
    name = (name or "").strip().lower()
    name = re.sub(r"https?://", "", name)
    name = re.sub(r"^www\.", "", name)
    name = re.sub(r"[^a-z0-9._-]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "unknown_site"


def stable_record_hash(record: dict, ignore_keys: Optional[List[str]] = None) -> str:
    """
    Stable hash for dedupe across runs.
    - normalizes lists (like emails) so order doesn't matter
    """
    ignore_keys = set(ignore_keys or [])
    cleaned = {}
    for k, v in (record or {}).items():
        if k in ignore_keys:
            continue
        if isinstance(v, list):
            cleaned[k] = sorted([str(x).strip() for x in v if x is not None])
        else:
            cleaned[k] = str(v).strip() if v is not None else ""
    payload = json.dumps(cleaned, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def save_site_records(
    records: List[dict],
    base_dir: str,
    date_fmt: str,
    site_name_key: str = "site_name",
    ignore_hash_keys: Optional[List[str]] = None,
):
    """
    Creates structure automatically and appends without duplicates.

    Structure:
      outputs/
        <site>/
          <site>_<YYYY-MM-DD>.csv
          <site>_<YYYY-MM-DD>.json
    """
    if not records:
        print("No records to save.")
        return

    today = datetime.now().strftime(date_fmt)

    # Decide site name (prefer domain if possible)
    raw_site = records[0].get(site_name_key) or records[0].get("current_url") or "unknown_site"
    # If a URL is present, folder by domain for cleaner grouping
    if "current_url" in records[0] and records[0]["current_url"]:
        dom = get_domain(records[0]["current_url"])
        site = safe_filename(dom or raw_site)
    else:
        site = safe_filename(raw_site)

    site_dir = os.path.join(base_dir, site)
    ensure_dir(site_dir)

    csv_path = os.path.join(site_dir, f"{site}_{today}.csv")
    json_path = os.path.join(site_dir, f"{site}_{today}.json")

    # Add hash to new records
    for r in records:
        r["_record_hash"] = stable_record_hash(r, ignore_keys=ignore_hash_keys)

    new_df = pd.DataFrame(records)

    # First run today: create
    if not os.path.exists(csv_path):
        new_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(new_df.fillna("").to_dict(orient="records"), f, ensure_ascii=False, indent=2)

        print(f"Created: {csv_path} (rows: {len(new_df)})")
        print(f"Created: {json_path}")
        return

    # Subsequent runs: append then dedupe
    try:
        old_df = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig")
    except Exception:
        old_df = pd.read_csv(csv_path, dtype=str)

    old_df = old_df.fillna("")
    new_df = new_df.fillna("")

    # Backward compatible: if old file doesn't have hash column, generate it
    if "_record_hash" not in old_df.columns:
        old_records = old_df.to_dict(orient="records")
        old_df["_record_hash"] = [stable_record_hash(r, ignore_keys=ignore_hash_keys) for r in old_records]

    combined = pd.concat([old_df, new_df], ignore_index=True)

    before = len(combined)
    combined = combined.drop_duplicates(subset=["_record_hash"], keep="first")
    after = len(combined)
    removed = before - after

    combined.to_csv(csv_path, index=False, encoding="utf-8-sig")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(combined.to_dict(orient="records"), f, ensure_ascii=False, indent=2)

    print(f"Updated: {csv_path}")
    print(f"Updated: {json_path}")
    print(f"Appended: {len(new_df)} rows, removed duplicates: {removed}, total: {after}")


# -----------------------------
# LOGIN SCOPE + TYPING (Daraz/react-safe)
# -----------------------------
def get_active_login_scope(driver: webdriver.Chrome):
    """
    If a login modal/popup is open, return that element so we only search inside it.
    """
    selectors = [
        "[role='dialog']",
        "[aria-modal='true']",
        ".modal",
        ".Modal",
        ".dialog",
        ".Dialog",
        ".next-dialog",          # Alibaba/Daraz-like
        ".next-overlay-wrapper", # overlays
    ]
    for sel in selectors:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in els:
                try:
                    if el.is_displayed():
                        return el
                except Exception:
                    continue
        except Exception:
            continue
    return driver


def safe_type(driver: webdriver.Chrome, el, text: str) -> bool:
    """
    Reliable typing for controlled inputs (Daraz etc.)
    1) Normal send_keys
    2) Verify value changed
    3) JS set + dispatch input/change events
    """
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    except Exception:
        pass

    # Attempt 1: normal typing
    try:
        el.click()
        el.send_keys(Keys.CONTROL, "a")
        el.send_keys(Keys.BACKSPACE)
        el.send_keys(text)
        time.sleep(0.2)
    except Exception:
        pass

    # Verify
    try:
        v = (el.get_attribute("value") or "").strip()
        if v:
            return True
    except Exception:
        pass

    # Attempt 2: JS set + events
    try:
        driver.execute_script(
            """
            const el = arguments[0];
            const val = arguments[1];
            el.focus();
            el.value = val;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            """,
            el, text
        )
        time.sleep(0.2)
        v2 = (el.get_attribute("value") or "").strip()
        return bool(v2)
    except Exception:
        return False


# -----------------------------
# DRIVER
# -----------------------------
def build_driver(headless: bool) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")

    # Optional: disable Chrome password save popups
    options.add_experimental_option(
        "prefs",
        {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
        },
    )

    options.add_argument("--window-size=1400,900")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-infobars")

    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options,
    )

    # Small webdriver flag reduction (not bypassing security)
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"},
        )
    except Exception:
        pass

    driver.set_page_load_timeout(45)
    return driver


# -----------------------------
# BLOCKER DETECTION (CAPTCHA/CF)
# -----------------------------
def detect_blockers(driver: webdriver.Chrome) -> Optional[str]:
    src = (driver.page_source or "").lower()

    keywords = [
        "captcha",
        "recaptcha",
        "hcaptcha",
        "verify you are human",
        "human verification",
        "robot check",
        "security check",
        "cloudflare",
        "challenge required",
        "access denied",
        "unusual traffic",
    ]
    for kw in keywords:
        if kw in src:
            return f"Blocked: {kw}"

    if driver.find_elements(By.CSS_SELECTOR, "iframe[src*='recaptcha']"):
        return "Blocked: Google reCAPTCHA (iframe)"
    if driver.find_elements(By.CSS_SELECTOR, "iframe[src*='hcaptcha']"):
        return "Blocked: hCaptcha (iframe)"
    if driver.find_elements(By.CSS_SELECTOR, "iframe[src*='challenges.cloudflare']"):
        return "Blocked: Cloudflare challenge (iframe)"
    if driver.find_elements(By.CSS_SELECTOR, "#challenge-form, #cf-challenge, .cf-challenge"):
        return "Blocked: Cloudflare challenge page"

    return None


# -----------------------------
# LOGIN FIELD DETECTION (scoped)
# -----------------------------
def password_input(driver: webdriver.Chrome):
    scope = get_active_login_scope(driver)
    return find_visible_input_in_scope(scope, ["input[type='password']"])


def identifier_input(driver: webdriver.Chrome):
    scope = get_active_login_scope(driver)

    return find_visible_input_in_scope(scope, [
        "input[type='email']",

        # Daraz exact matches
        "input.iweb-input[placeholder*='Please enter your Phone or Email' i]",
        "input[placeholder*='Please enter your Phone or Email' i]",
        "input.iweb-input[placeholder*='Phone or Email' i]",
        "input[placeholder*='Phone or Email' i]",

        # Generic identifier hints
        "input[placeholder*='email' i]",
        "input[placeholder*='phone' i]",
        "input[placeholder*='mobile' i]",
        "input[placeholder*='username' i]",
        "input[aria-label*='email' i]",
        "input[aria-label*='phone' i]",
        "input[aria-label*='mobile' i]",
        "input[name*='email' i]",
        "input[name*='user' i]",
        "input[name*='login' i]",
        "input[id*='email' i]",
        "input[id*='user' i]",
        "input[id*='login' i]",

        # Last-resort: any visible text/tel input in modal
        "input[type='text']",
        "input[type='tel']",
    ])


def has_any_login_input(driver: webdriver.Chrome) -> bool:
    return identifier_input(driver) is not None or password_input(driver) is not None


# -----------------------------
# CLICK LOGIN ENTRY (opens modal or login page)
# -----------------------------
def click_login_entry(driver: webdriver.Chrome, timeout: int) -> bool:
    if has_any_login_input(driver):
        return True

    candidates = driver.find_elements(By.CSS_SELECTOR, "a, button")
    scored: List[Tuple[int, object]] = []

    for el in candidates:
        try:
            if not (el.is_displayed() and el.is_enabled()):
                continue

            text = norm_text(el.text)
            href = (el.get_attribute("href") or "").lower()
            aria = (el.get_attribute("aria-label") or "").lower()
            title = (el.get_attribute("title") or "").lower()

            score = 0
            if any(k in text for k in LOGIN_KEYWORDS):
                score += 4
            if any(k in aria for k in ["login", "log in", "sign in", "signin"]):
                score += 4
            if any(k in title for k in ["login", "log in", "sign in", "signin"]):
                score += 3
            if any(k in href for k in ["login", "signin", "sign-in", "account"]):
                score += 2

            if score > 0:
                scored.append((score, el))
        except Exception:
            continue

    scored.sort(key=lambda x: x[0], reverse=True)

    for _, el in scored[:12]:
        try:
            if click_with_fallback(driver, el):
                time.sleep(1.0)
                return True
        except (StaleElementReferenceException, WebDriverException):
            continue

    return False


# -----------------------------
# BUTTON CLICK HELPERS (scoped)
# -----------------------------
def click_button_by_keywords(driver: webdriver.Chrome, keywords: List[str]) -> bool:
    scope = get_active_login_scope(driver)
    for b in scope.find_elements(By.CSS_SELECTOR, "button, input[type='submit']"):
        try:
            if not b.is_displayed() or not b.is_enabled():
                continue
            txt = norm_text(b.text)
            val = norm_text(b.get_attribute("value") or "")
            combined = f"{txt} {val}"
            if any(k in combined for k in keywords):
                return click_with_fallback(driver, b)
        except Exception:
            continue
    return False


# -----------------------------
# UNIVERSAL LOGIN
# -----------------------------
def perform_universal_login(driver: webdriver.Chrome, username: str, password: str, timeout: int) -> Dict[str, str]:
    wait = WebDriverWait(driver, timeout)

    if not has_any_login_input(driver):
        opened = click_login_entry(driver, timeout)
        if not opened:
            return {"status": "skipped", "reason": "No login UI detected (no login link/icon and no inputs visible)."}

    for _ in range(12):
        time.sleep(0.35)

        blocker = detect_blockers(driver)
        if blocker:
            return {"status": "blocked", "reason": blocker}

        ident = identifier_input(driver)
        pw = password_input(driver)

        # Two-step step 1: identifier only
        if ident and not pw:
            ok = safe_type(driver, ident, username)
            if not ok:
                return {"status": "failed", "reason": "Could not set identifier value (controlled input)."}

            if not click_button_by_keywords(driver, BTN_KEYWORDS_CONTINUE):
                try:
                    ident.send_keys(Keys.ENTER)
                except Exception:
                    return {"status": "failed", "reason": "Identifier set but Continue/Next button not found."}

            try:
                wait.until(lambda d: password_input(d) is not None)
            except TimeoutException:
                blocker2 = detect_blockers(driver)
                if blocker2:
                    return {"status": "blocked", "reason": blocker2}
                return {"status": "failed", "reason": "Continue clicked but password did not appear (OTP/external auth?)"}

            continue

        # Password step (single-page OR second step)
        if pw:
            # Some sites show both fields, ensure identifier is filled too
            if ident:
                _ = safe_type(driver, ident, username)

            ok_pw = safe_type(driver, pw, password)
            if not ok_pw:
                return {"status": "failed", "reason": "Could not set password value."}

            if not click_button_by_keywords(driver, BTN_KEYWORDS_SUBMIT):
                try:
                    pw.send_keys(Keys.ENTER)
                except Exception:
                    pass

            time.sleep(1.2)

            blocker3 = detect_blockers(driver)
            if blocker3:
                return {"status": "blocked", "reason": blocker3}

            if not has_any_login_input(driver):
                return {"status": "success_or_done", "reason": "Submitted credentials, login inputs disappeared."}

            msg = detect_login_error_message(driver)
            if msg:
                return {"status": "failed", "reason": msg}

            return {"status": "attempted", "reason": "Submitted credentials, login inputs still visible (may need extra verification)."}

        if not ident and not pw:
            return {"status": "already_logged_in", "reason": "No login inputs visible."}

    return {"status": "failed", "reason": "Login loop exceeded safety limit."}


def detect_login_error_message(driver: webdriver.Chrome) -> Optional[str]:
    scope = get_active_login_scope(driver)
    candidates = scope.find_elements(By.CSS_SELECTOR, ".error, .alert, .toast, [role='alert']")
    for c in candidates:
        try:
            if c.is_displayed():
                txt = (c.text or "").strip()
                if txt:
                    return txt
        except Exception:
            continue

    src = (driver.page_source or "").lower()
    phrases = ["invalid", "incorrect", "wrong password", "try again", "failed"]
    for p in phrases:
        if p in src:
            return f"Possible login error detected (phrase: {p})"
    return None


# -----------------------------
# DEMO SCRAPE
# -----------------------------
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def get_site_name(driver: webdriver.Chrome) -> str:
    # Prefer domain for clean naming
    dom = get_domain(driver.current_url)
    if dom:
        return dom
    try:
        title = (driver.title or "").strip()
        if title:
            return title
    except Exception:
        pass
    return "unknown_site"


def extract_visible_emails(driver: webdriver.Chrome, limit: int = 20) -> List[str]:
    emails = set()

    for a in driver.find_elements(By.CSS_SELECTOR, "a[href^='mailto:']"):
        try:
            href = a.get_attribute("href") or ""
            m = href.split("mailto:", 1)[-1].split("?", 1)[0].strip()
            if m:
                emails.add(m)
        except Exception:
            continue

    try:
        body_text = driver.find_element(By.TAG_NAME, "body").text or ""
        for m in EMAIL_RE.findall(body_text):
            emails.add(m)
    except Exception:
        pass

    cleaned = []
    for e in sorted(emails):
        e2 = e.strip().strip(".,;:()[]{}<>")
        if e2:
            cleaned.append(e2)
        if len(cleaned) >= limit:
            break
    return cleaned


def demo_scrape(driver: webdriver.Chrome, scrape_emails: bool) -> Dict[str, object]:
    row = {
        "site_name": get_site_name(driver),
        "current_url": driver.current_url,
        "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    row["emails_found"] = extract_visible_emails(driver) if scrape_emails else []
    return row


# -----------------------------
# MAIN
# -----------------------------
def main():
    cfg = ScraperConfig(headless=False)

    print("=== Universal Login + Auto Output Structure + Append without duplicates ===")
    target_url = input("Paste target URL (any page): ").strip()
    username = input("Enter email/phone/username: ").strip()
    password = getpass("Enter password (hidden): ")

    if not (target_url and username and password):
        raise ValueError("target_url, username, password are required.")

    driver = None
    try:
        driver = build_driver(cfg.headless)
        driver.set_page_load_timeout(cfg.page_load_timeout)

        print("\nOpening target URL...")
        driver.get(target_url)
        wait_ready(driver, cfg.wait_timeout)

        print("Attempting universal login...")
        info = perform_universal_login(driver, username, password, cfg.wait_timeout)

        if info["status"] == "blocked":
            print(f"\n❌ {info['reason']}")
            input("Browser is open. Press ENTER after you inspect the page...")
        elif info["status"] == "failed":
            print(f"\n❌ Login failed: {info['reason']}")
            input("Browser is open. Press ENTER after you inspect the page...")
        elif info["status"] == "skipped":
            print(f"\nℹ️ Login skipped: {info['reason']}")
        else:
            print(f"\n✅ {info['status']}: {info['reason']}")

        # Re-open target (some sites redirect after login)
        print("\nRe-opening target URL...")
        driver.get(target_url)
        wait_ready(driver, cfg.wait_timeout)

        blocker = detect_blockers(driver)
        if blocker:
            print(f"\n❌ Blocked on target page: {blocker}")
            input("Browser is open. Press ENTER after you inspect the page...")
        else:
            print("\nRunning demo scrape (site name, url, emails)...")
            row = demo_scrape(driver, cfg.scrape_emails)

            # Save in site folder, append + dedupe
            save_site_records(
                records=[row],
                base_dir=cfg.outputs_base_dir,
                date_fmt=cfg.date_fmt,
                ignore_hash_keys=[],  # you can ignore 'scraped_at' if you want to dedupe purely by content
            )

        if cfg.keep_open_on_finish:
            input("\nDone. Press ENTER to close the browser...")

    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    main()
