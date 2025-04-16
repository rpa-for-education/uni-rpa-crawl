import os
import re
import csv
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
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('facebook_scraper.log'), logging.StreamHandler()]
)


def retry_on_failure(max_attempts=3, delay=2):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts:
                        logging.error(f"[{func.__name__}] Thất bại sau {max_attempts} lần thử: {e}")
                        raise
                    logging.warning(f"[{func.__name__}] Thử lần {attempt} thất bại: {e}. Đợi {delay}s rồi thử lại...")
                    time.sleep(delay)

        return wrapper

    return decorator


def setup_driver():
    """Thiết lập và cấu hình trình duyệt Chrome."""
    try:
        chrome_options = Options()
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument("--start-maximized")

        # Dùng profile tạm để tránh lỗi "user-data-dir"
        temp_profile = tempfile.mkdtemp()
        chrome_options.add_argument(f"--user-data-dir={temp_profile}")

        # Thêm tùy chọn headless nếu chạy trong CI/CD
        if os.getenv("CI") == "true":
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--no-sandbox")

        service = Service()
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver
    except Exception as e:
        logging.error(f"Không thể khởi tạo ChromeDriver: {e}")
        raise


def parse_cookie_file(cookie_file_path):
    cookies_list = []
    try:
        with open(cookie_file_path, 'r', encoding='utf-8') as file:
            for line in file:
                if not line.strip() or line.startswith("#"):
                    continue
                try:
                    parts = line.strip().split('\t')
                    if len(parts) >= 7:
                        domain, flag, path, secure, expiration, name, value = parts[:7]
                        cookie = {
                            'name': name,
                            'value': value,
                            'domain': domain,
                            'path': path,
                            'secure': secure.lower() == 'true' or secure == '1',
                            'expiry': int(expiration) if expiration != '0' else None
                        }
                        cookies_list.append(cookie)
                    else:
                        match = re.search(r'(\w+)=([^;]+)', line)
                        if match:
                            cookies_list.append({
                                'name': match.group(1),
                                'value': match.group(2),
                                'domain': '.facebook.com'
                            })
                except Exception as e:
                    logging.warning(f"Lỗi phân tích dòng cookie: {line} - {e}")
    except Exception as e:
        logging.error(f"Lỗi đọc file cookie: {e}")
    return cookies_list


def extract_essential_cookies(cookies_list):
    essential = {}
    names = ['c_user', 'xs', 'datr', 'fr', 'sb', 'dpr', 'wd', 'presence']
    for cookie in cookies_list:
        if cookie['name'] in names:
            essential[cookie['name']] = cookie['value']
    return essential


@retry_on_failure(max_attempts=3, delay=5)
def login_to_facebook(driver, cookie_file_path):
    if not os.path.exists(cookie_file_path):
        logging.error(f"Không tìm thấy file cookie: {cookie_file_path}")
        return False

    cookies_list = parse_cookie_file(cookie_file_path)
    if not cookies_list:
        logging.error("Không có cookie hợp lệ trong file.")
        return False

    driver.get("https://www.facebook.com")
    time.sleep(2)
    driver.delete_all_cookies()

    added = 0
    for cookie in cookies_list:
        try:
            driver.add_cookie(cookie)
            added += 1
        except Exception as e:
            logging.warning(f"Không thể thêm cookie {cookie.get('name')}: {e}")

    logging.info(f"Đã thêm {added}/{len(cookies_list)} cookie vào trình duyệt")

    driver.get("https://www.facebook.com")
    try:
        wait = WebDriverWait(driver, 10)
        wait.until(EC.presence_of_element_located(
            (By.XPATH, "//input[@placeholder='Tìm kiếm trên Facebook' or @placeholder='Search Facebook']")))
        logging.info("Đăng nhập thành công!")
        return True
    except Exception:
        logging.error("Không thể xác minh đăng nhập. Có thể cookie đã hết hạn.")
        return False


def clean_post_url(url):
    return url.split("?")[0] if "?" in url else url


@retry_on_failure(max_attempts=3, delay=5)
def get_post_links_from_group(driver, group_url, max_posts=50):
    try:
        driver.get(group_url)
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.XPATH, "//div[@role='main']")))

        collected, processed_links = 0, set()
        last_height = driver.execute_script("return document.body.scrollHeight")
        scroll_attempts = 0

        while collected < max_posts and scroll_attempts < 5:
            posts = driver.find_elements(By.XPATH, "//div[@role='article']") or \
                    driver.find_elements(By.XPATH, "//div[contains(@data-pagelet, 'FeedUnit')]")

            for post in posts:
                if collected >= max_posts:
                    break
                try:
                    link = post.find_element(By.XPATH,
                                             ".//a[contains(@href, '/groups/') and contains(@href, '/posts/')]").get_attribute(
                        "href")
                    cleaned = clean_post_url(link)
                    if cleaned and cleaned not in processed_links:
                        processed_links.add(cleaned)
                        collected += 1

                        payload = {"url": cleaned}
                        try:
                            resp = requests.post("https://api.rpa4edu.shop/api_bai_viet.php", json=payload)
                            if resp.status_code == 200:
                                logging.info(f"Đã gửi ({collected}/{max_posts}): {cleaned}")
                            else:
                                logging.warning(f"API lỗi với {cleaned}: {resp.status_code} - {resp.text}")
                        except Exception as e:
                            logging.error(f"Lỗi khi gửi API: {e}")

                        time.sleep(random.uniform(0.5, 1.5))
                except NoSuchElementException:
                    continue

            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                scroll_attempts += 1
                time.sleep(2)
            else:
                scroll_attempts = 0
                last_height = new_height

        return collected > 0
    except Exception as e:
        logging.error(f"Lỗi khi thu thập bài viết: {e}")
        return False


def main():
    logging.info("===== TOOL LẤY LINK BÀI VIẾT FACEBOOK =====")
    cookie_file_path = "facebook_cookies.txt"
    group_url = "https://www.facebook.com/groups/tansinhvienneu"
    max_posts = int(input("Nhập số lượng bài viết cần lấy (mặc định 50): ") or "50")

    driver = None
    try:
        driver = setup_driver()
        if login_to_facebook(driver, cookie_file_path):
            success = get_post_links_from_group(driver, group_url, max_posts)
            if success:
                logging.info(f"✅ Đã gửi đủ {max_posts} bài viết lên API!")
            else:
                logging.warning("⚠️ Không thu thập được bài viết nào.")
    except Exception as e:
        logging.error(f"Lỗi chính: {e}")
    finally:
        if driver:
            try:
                driver.quit()
                logging.info("Đã đóng trình duyệt.")
            except Exception as e:
                logging.error(f"Lỗi khi đóng trình duyệt: {e}")


if __name__ == "__main__":
    main()
