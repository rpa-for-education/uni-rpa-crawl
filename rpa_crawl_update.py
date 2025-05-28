import os
import re
import time
import random
import logging
import tempfile
import requests

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
)

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("facebook_scraper.log"), logging.StreamHandler()],
)


def retry_on_failure(max_attempts=3, delay=2):
    def decorator(func):
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
    chrome_options = Options()
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-popup-blocking")

    # Dùng profile tạm để tránh lỗi "user-data-dir"
    temp_profile = tempfile.mkdtemp()
    chrome_options.add_argument(f"--user-data-dir={temp_profile}")

    # Tùy chọn dành cho chạy CI/CD, headless Chrome mới và tăng ổn định
    if os.getenv("CI") == "true":
        chrome_options.add_argument("--headless=new")  # Chrome mới dùng --headless=new
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")  # Giảm lỗi bộ nhớ chia sẻ
        chrome_options.add_argument("--remote-debugging-port=9222")  # Hỗ trợ remote debugging

    service = Service()
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver


def parse_cookie_file(cookie_file_path):
    cookies_list = []
    try:
        with open(cookie_file_path, "r", encoding="utf-8") as file:
            for line in file:
                if not line.strip() or line.startswith("#"):
                    continue
                try:
                    parts = line.strip().split("\t")
                    if len(parts) >= 7:
                        domain, flag, path, secure, expiration, name, value = parts[:7]
                        cookie = {
                            "name": name,
                            "value": value,
                            "domain": domain,
                            "path": path,
                            "secure": secure.lower() == "true" or secure == "1",
                            "expiry": int(expiration) if expiration != "0" else None,
                        }
                        cookies_list.append(cookie)
                    else:
                        match = re.search(r"(\w+)=([^;]+)", line)
                        if match:
                            cookies_list.append(
                                {
                                    "name": match.group(1),
                                    "value": match.group(2),
                                    "domain": ".facebook.com",
                                }
                            )
                except Exception as e:
                    logging.warning(f"Lỗi phân tích dòng cookie: {line} - {e}")
    except Exception as e:
        logging.error(f"Lỗi đọc file cookie: {e}")
    return cookies_list


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
        wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//input[@placeholder='Tìm kiếm trên Facebook' or @placeholder='Search Facebook']",
                )
            )
        )
        logging.info("Đăng nhập thành công!")
        return True
    except Exception:
        logging.error("Không thể xác minh đăng nhập. Có thể cookie đã hết hạn.")
        return False


@retry_on_failure(max_attempts=3, delay=5)
def get_post_links_from_group(driver, group_url, max_posts=50):
    driver.get(group_url)
    try:
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
    except TimeoutException:
        logging.error("Không tải được trang nhóm Facebook.")
        return False

    collected_links = set()
    no_new_count = 0
    last_height = driver.execute_script("return document.body.scrollHeight")

    while len(collected_links) < max_posts and no_new_count < 10:
        # Cuộn chậm để facebook load nội dung
        driver.execute_script("window.scrollBy(0, 300);")
        time.sleep(random.uniform(1.5, 3.0))

        # Lấy lại thẻ <a> mới nhất sau cuộn
        anchors = driver.find_elements(By.TAG_NAME, "a")

        new_found = False
        for a in anchors:
            try:
                href = a.get_attribute("href")
                if href and "/groups/" in href and "/posts/" in href:
                    href_clean = href.split("?")[0]
                    if href_clean not in collected_links:
                        collected_links.add(href_clean)
                        logging.info(f"Đang thu thập link thứ {len(collected_links)} / {max_posts}: {href_clean}")

                        # Gửi lên API
                        payload = {"url": href_clean}
                        try:
                            resp = requests.post("https://api.rpa4edu.shop/api_bai_viet.php", json=payload)
                            if resp.status_code == 200:
                                logging.info(f"Đã gửi link lên API: {href_clean}")
                            else:
                                logging.warning(f"API lỗi với {href_clean}: {resp.status_code} - {resp.text}")
                        except Exception as e:
                            logging.error(f"Lỗi gửi API: {e}")

                        new_found = True
                        if len(collected_links) >= max_posts:
                            break
            except StaleElementReferenceException:
                continue

        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height and not new_found:
            no_new_count += 1
            logging.info(f"Không tìm được link mới lần thứ {no_new_count}, chiều cao trang không thay đổi")
        else:
            no_new_count = 0
            last_height = new_height

    if len(collected_links) == 0:
        logging.warning("Không thu thập được link bài viết nào.")
        return False
    else:
        logging.info(f"Thu thập được tổng cộng {len(collected_links)} link bài viết.")
        return True


def main():
    logging.info("===== TOOL LẤY LINK BÀI VIẾT FACEBOOK =====")

    cookie_file_path = "facebook_cookies.txt"
    group_url = "https://www.facebook.com/groups/tansinhvienneu"

    try:
        max_posts = int(os.getenv("MAX_POSTS", "50"))
    except ValueError:
        max_posts = 50

    driver = None
    try:
        driver = setup_driver()
        if login_to_facebook(driver, cookie_file_path):
            success = get_post_links_from_group(driver, group_url, max_posts)
            if success:
                logging.info(f"✅ Đã gửi đủ {max_posts} bài viết lên API!")
            else:
                logging.warning("⚠️ Không thu thập được bài viết nào.")
        else:
            logging.error("Đăng nhập Facebook thất bại, không thể thu thập bài viết.")
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
