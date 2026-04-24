# 🏠 AFR.com Property Scraper

A Python-based web automation and scraping tool specially built for **AFR.com** to automate login and extract useful data after authentication.

This scraper can:

* Automatically log into **AFR.com**
* Handle login forms and authentication flows
* Detect blockers such as CAPTCHA
* Extract emails and visible page information
* Save scraped data in CSV and JSON formats
* Append data without duplicates

---

## 🚀 Overview

The **AFR.com Property Scraper** is designed specifically for scraping content from **AFR.com** after successful login.

It automates the following process:

1. Opens the AFR target page

2. Detects login UI

3. Enters user credentials

4. Completes login process

5. Reopens target page after authentication

6. Scrapes visible data such as:

   * Site name
   * Current URL
   * Emails found on page

7. Saves results automatically

---

## ✨ Features

### 🔐 Automated Login

Supports:

* Email / username login
* Password submission
* Multi-step login handling

---

### 🛡️ Blocker Detection

Detects common blockers:

* CAPTCHA
* reCAPTCHA
* hCaptcha


---

### 📧 Email Extraction

Extracts emails from:

* Visible page content
* `mailto:` links

---

### 💾 Organized Output

Automatically creates:

```bash id="8d4f4k"
outputs/
  afr.com/
    afr.com_YYYY-MM-DD.csv
    afr.com_YYYY-MM-DD.json
```

---

### ♻️ Duplicate Removal

If run multiple times in one day:

* Appends new records
* Removes duplicate entries automatically

---

## 🛠️ Tech Stack

Built with:

* **Python**
* **Selenium**
* **Pandas**
* **WebDriver Manager**

---

## 📁 Project Structure

```bash id="rvhlyu"
AFR-Property-Scraper/
│
├── Property_Scraper.py
├── outputs/
│   └── afr.com/
│       ├── afr.com_2026-04-24.csv
│       └── afr.com_2026-04-24.json
└── README.md
```

---

Install dependencies:

```bash id="92kvlx"
pip install selenium webdriver-manager pandas
```

---

## ▶️ Usage

Run the script:

```bash id="ksg2b4"
python Property_Scraper.py
```

Provide:

```text id="cdhkp4"
Paste AFR target URL
Enter email/username
Enter password
```

---

## 📊 Output Example

CSV:

| site_name | current_url     | scraped_at | emails_found                        |
| --------- | --------------- | ---------- | ----------------------------------- |
| afr.com   | https://afr.com | 2026-04-24 | [info@afr.com](mailto:info@afr.com) |

---

## ⚠️ Notes

* Requires valid AFR.com credentials
* CAPTCHA solving is not included
* Website structure changes may require script updates

---

## 💡 Author

Developed by **Malki Aman**.
