import os
import re
import time
import json
import random
import logging
import tempfile
import requests
from datetime import datetime
from functools import wraps
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException, StaleElementReferenceException

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('facebook_scraper.log'), logging.StreamHandler()]
)

# Retry Decorator
def retry_on_failure(max_attempts=3, delay=2):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts:
                        logging.error(f"[{func.__name__}] Thất bại sau {max_attempts} lần: {e}")
                        raise
                    logging.warning(f"[{func.__name__}] Lần {attempt} thất bại: {e}. Đợi {delay}s...")
                    time.sleep(delay)
        return wrapper
    return decorator

# Chrome Setup
def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument(f"--user-data-dir={tempfile.mkdtemp()}")
    if os.getenv("CI") == "true":
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
    return webdriver.Chrome(service=Service(), options=chrome_options)

# Cookies
def parse_cookie_file(path):
    cookies = []
    with open(path, 'r', encoding='utf-8') as file:
        for line in file:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.strip().split('\t')
            if len(parts) >= 7:
                cookies.append({
                    'name': parts[5], 'value': parts[6], 'domain': parts[0],
                    'path': parts[2], 'secure': parts[3] in ['TRUE', 'true', '1'],
                    'expiry': int(parts[4]) if parts[4] != '0' else None
                })
            else:
                match = re.search(r'(\w+)=([^;]+)', line)
                if match:
                    cookies.append({
                        'name': match.group(1), 'value': match.group(2), 'domain': '.facebook.com'
                    })
    return cookies

@retry_on_failure()
def login_with_cookies(driver, cookie_file):
    if not os.path.exists(cookie_file):
        logging.error("Không tìm thấy file cookie.")
        return False
    cookies = parse_cookie_file(cookie_file)
    driver.get("https://www.facebook.com")
    time.sleep(2)
    driver.delete_all_cookies()
    for cookie in cookies:
        try:
            driver.add_cookie(cookie)
        except Exception:
            continue
    driver.get("https://www.facebook.com")
    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located(
            (By.XPATH, "//input[@placeholder='Tìm kiếm trên Facebook' or @placeholder='Search Facebook']")))
        logging.info("✅ Đăng nhập thành công!")
        return True
    except:
        logging.error("❌ Đăng nhập thất bại (cookie hết hạn?)")
        return False

# Link xử lý
def clean_post_url(url): return url.split("?")[0] if "?" in url else url

def load_sent_links(path="sent_links.txt"):
    return set(open(path, encoding='utf-8').read().splitlines()) if os.path.exists(path) else set()

def save_sent_link(link, path="sent_links.txt"):
    with open(path, 'a', encoding='utf-8') as f:
        f.write(f"{link}\n")

def scroll_down(driver, times=10, delay=1.2):
    last_height = driver.execute_script("return document.body.scrollHeight")
    for _ in range(times):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(delay)
        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height

@retry_on_failure()
def extract_post_links(driver, group_url, max_posts=50):
    sent_links = load_sent_links()
    processed = set()
    count = 0

    driver.get(group_url)
    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.XPATH, "//div[@role='main']")))

    scroll_down(driver, times=15, delay=1.2)  # Scroll để lấy bài cũ

    posts = driver.find_elements(By.XPATH, "//div[@role='article']") or \
            driver.find_elements(By.XPATH, "//div[contains(@data-pagelet, 'FeedUnit')]")

    for post in posts:
        if count >= max_posts:
            break
        try:
            link = post.find_element(By.XPATH, ".//a[contains(@href, '/groups/') and contains(@href, '/posts/')]").get_attribute("href")
            cleaned = clean_post_url(link)
            if cleaned not in processed and cleaned not in sent_links:
                payload = {"url": cleaned}
                resp = requests.post("https://api.rpa4edu.shop/api_bai_viet.php", json=payload)
                if resp.status_code == 200:
                    logging.info(f"Đã gửi ({count + 1}/{max_posts}): {cleaned}")
                    save_sent_link(cleaned)
                    processed.add(cleaned)
                    count += 1
                else:
                    logging.warning(f"API lỗi: {cleaned} - {resp.status_code}")
                time.sleep(random.uniform(0.5, 1.0))
        except (NoSuchElementException, StaleElementReferenceException):
            continue

    return count

# Main
def main():
    logging.info("===== BẮT ĐẦU TOOL LẤY BÀI VIẾT FB =====")
    cookie_file = "facebook_cookies.txt"
    group_url = "https://www.facebook.com/groups/tansinhvienneu"
    max_posts = int(os.getenv("MAX_POSTS", "50"))

    driver = None
    try:
        driver = setup_driver()
        if login_with_cookies(driver, cookie_file):
            collected = extract_post_links(driver, group_url, max_posts)
            if collected:
                logging.info(f"✅ Đã thu thập {collected} bài viết!")
            else:
                logging.warning("⚠️ Không thu thập được bài viết nào.")
    except Exception as e:
        logging.error(f"❌ Lỗi chính: {e}")
    finally:
        if driver:
            driver.quit()
            logging.info("Đã đóng trình duyệt.")

if __name__ == "__main__":
    main()
