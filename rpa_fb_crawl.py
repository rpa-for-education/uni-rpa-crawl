from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException
import time
import csv
import os
import random
from functools import wraps
import logging
import requests
from datetime import datetime
import json
import re

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('facebook_scraper.log'),
        logging.StreamHandler()
    ]
)


def retry_on_failure(max_attempts=3, delay=2):
    """Decorator to retry functions on failure."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempts = 0
            while attempts < max_attempts:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    attempts += 1
                    if attempts == max_attempts:
                        logging.error(f"Failed after {max_attempts} attempts: {str(e)}")
                        raise
                    logging.warning(f"Attempt {attempts} failed: {str(e)}. Retrying in {delay} seconds...")
                    time.sleep(delay)
            return None

        return wrapper

    return decorator


def setup_driver():
    """Thiết lập và cấu hình trình duyệt Chrome."""
    try:
        chrome_options = Options()
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument("--start-maximized")
        driver = webdriver.Chrome(options=chrome_options)
        return driver
    except Exception as e:
        logging.error(f"Error setting up driver: {str(e)}")
        raise


def save_cookies(driver, cookie_file_path):
    """Lưu cookies từ trình duyệt vào file."""
    try:
        cookies = driver.get_cookies()
        with open(cookie_file_path, 'w', encoding='utf-8') as f:
            for cookie in cookies:
                f.write(f"{cookie['domain']}\tTRUE\t{cookie['path']}\t"
                        f"{cookie['secure']}\t{cookie.get('expiry', 0)}\t"
                        f"{cookie['name']}\t{cookie['value']}\n")
        logging.info(f"Đã lưu cookies vào {cookie_file_path}")
    except Exception as e:
        logging.error(f"Lỗi khi lưu cookies: {str(e)}")


def parse_cookie_file(cookie_file_path):
    """Phân tích file cookie.txt và chuyển đổi thành danh sách cookies cho Selenium"""
    cookies_list = []
    try:
        with open(cookie_file_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()
            for line in lines:
                if not line.strip() or line.strip().startswith('#'):
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
                except Exception as e:
                    logging.warning(f"Không thể phân tích dòng cookie: {line} - Lỗi: {e}")
    except Exception as e:
        logging.error(f"Lỗi khi đọc file cookie: {e}")
    return cookies_list


def extract_essential_cookies(cookies_list):
    """Trích xuất các cookie quan trọng từ danh sách cookies"""
    essential_cookies = {}
    important_names = ['c_user', 'xs', 'datr', 'fr', 'sb', 'dpr', 'wd', 'presence']
    for cookie in cookies_list:
        if cookie['name'] in important_names:
            essential_cookies[cookie['name']] = cookie['value']
    return essential_cookies


@retry_on_failure(max_attempts=3, delay=5)
def manual_login(driver, email, password):
    """Đăng nhập thủ công bằng email và password"""
    try:
        driver.get("https://www.facebook.com")
        time.sleep(2)

        # Điền email
        email_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "email"))
        )
        email_field.send_keys(email)

        # Điền password
        password_field = driver.find_element(By.ID, "pass")
        password_field.send_keys(password)

        # Nhấn nút đăng nhập
        login_button = driver.find_element(By.NAME, "login")
        login_button.click()

        # Chờ đăng nhập thành công
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located(
                (By.XPATH, "//input[@placeholder='Tìm kiếm trên Facebook' or @placeholder='Search Facebook']"))
        )
        logging.info("Đăng nhập thủ công thành công!")
        return True
    except Exception as e:
        logging.error(f"Lỗi khi đăng nhập thủ công: {str(e)}")
        return False


@retry_on_failure(max_attempts=3, delay=5)
def login_to_facebook(driver, cookie_file_path, email=None, password=None):
    """Đăng nhập vào Facebook sử dụng file cookie hoặc đăng nhập thủ công"""
    try:
        driver.get("https://www.facebook.com")
        time.sleep(2)

        # Thử sử dụng cookies nếu file tồn tại
        if os.path.exists(cookie_file_path):
            cookies_list = parse_cookie_file(cookie_file_path)
            if cookies_list:
                driver.delete_all_cookies()
                cookie_added_count = 0
                for cookie in cookies_list:
                    try:
                        driver.add_cookie(cookie)
                        cookie_added_count += 1
                    except Exception as e:
                        logging.warning(f"Không thể thêm cookie {cookie['name']}: {e}")

                logging.info(f"Đã thêm {cookie_added_count}/{len(cookies_list)} cookie vào trình duyệt")
                driver.refresh()

                # Kiểm tra đăng nhập
                try:
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.XPATH,
                                                        "//input[@placeholder='Tìm kiếm trên Facebook' or @placeholder='Search Facebook']"))
                    )
                    logging.info("Đăng nhập bằng cookies thành công!")
                    return True
                except:
                    logging.warning("Cookies không hợp lệ, thử đăng nhập thủ công...")

        # Nếu không có cookies hoặc cookies không hợp lệ, đăng nhập thủ công
        if email and password:
            if manual_login(driver, email, password):
                save_cookies(driver, cookie_file_path)
                return True
            else:
                logging.error("Đăng nhập thủ công thất bại")
                return False
        else:
            logging.error("Không có thông tin đăng nhập thủ công")
            return False

    except Exception as e:
        logging.error(f"Lỗi trong quá trình đăng nhập: {str(e)}")
        return False


def clean_post_url(url):
    """Làm sạch URL bài viết từ Facebook, loại bỏ tham số query."""
    if '?' in url:
        base_url = url.split('?')[0]
        return base_url
    return url


@retry_on_failure(max_attempts=3, delay=5)
def get_post_links_from_group(driver, group_url, max_posts=50):
    """Lấy link bài viết từ group Facebook và gửi lên API ngay sau khi tìm thấy."""
    try:
        driver.get(group_url)
        logging.info(f"Đang truy cập vào group: {group_url}")

        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, "//div[@role='main']"))
        )

        processed_links = set()
        collected_count = 0
        last_height = driver.execute_script("return document.body.scrollHeight")
        scroll_attempts = 0
        max_scroll_attempts = 5

        while collected_count < max_posts and scroll_attempts < max_scroll_attempts:
            try:
                post_containers = driver.find_elements(By.XPATH, "//div[@role='article']")
                if not post_containers:
                    post_containers = driver.find_elements(By.XPATH, "//div[contains(@data-pagelet, 'FeedUnit')]")

                logging.info(f"Tìm thấy {len(post_containers)} post containers trên màn hình.")

                for container in post_containers:
                    if collected_count >= max_posts:
                        break
                    try:
                        link_element = container.find_element(By.XPATH,
                                                              ".//a[contains(@href, '/groups/') and contains(@href, '/posts/') and not(ancestor::div[contains(@class, 'text_exposed_root')])]")
                        link = link_element.get_attribute("href")
                        cleaned_link = clean_post_url(link)

                        if cleaned_link and cleaned_link not in processed_links:
                            processed_links.add(cleaned_link)
                            collected_count += 1

                            payload = {"url": cleaned_link}
                            try:
                                response = requests.post("https://api.rpa4edu.shop/api_bai_viet.php", json=payload)
                                if response.status_code == 200:
                                    try:
                                        result = response.json()
                                        logging.info(
                                            f"Đã gửi link lên API thành công ({collected_count}/{max_posts}): {cleaned_link} | Phản hồi: {result}")
                                    except json.JSONDecodeError:
                                        logging.warning(
                                            f"Đã gửi link lên API thành công nhưng phản hồi không phải JSON ({collected_count}/{max_posts}): {cleaned_link}")
                                else:
                                    logging.error(
                                        f"Lỗi khi gửi API cho link {cleaned_link}: HTTP {response.status_code}, {response.text}")
                            except requests.exceptions.RequestException as e:
                                logging.error(f"Lỗi kết nối khi gửi API cho link {cleaned_link}: {str(e)}")

                            time.sleep(random.uniform(0.5, 1.5))

                    except NoSuchElementException:
                        continue
                    except Exception as e:
                        logging.warning(f"Lỗi khi xử lý một container bài viết: {str(e)}")
                        continue

                if collected_count >= max_posts:
                    logging.info(f"Đã thu thập đủ {max_posts} bài viết.")
                    break

                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                wait_time = max(1, 3 - (collected_count / 20))
                time.sleep(wait_time)

                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    scroll_attempts += 1
                    logging.info(f"Không có nội dung mới sau lần cuộn thứ {scroll_attempts}")
                    time.sleep(2)
                else:
                    scroll_attempts = 0
                    last_height = new_height

            except WebDriverException as e:
                logging.warning(f"Lỗi WebDriver trong quá trình cuộn/tìm kiếm: {str(e)}. Đang thử tải lại trang...")
                driver.refresh()
                time.sleep(5)
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.XPATH, "//div[@role='main']"))
                )
                last_height = driver.execute_script("return document.body.scrollHeight")
                continue
            except Exception as e:
                logging.warning(f"Lỗi không xác định trong vòng lặp chính: {str(e)}")
                time.sleep(2)
                continue

        return collected_count > 0

    except Exception as e:
        logging.error(f"Lỗi nghiêm trọng khi lấy link bài viết: {str(e)}")
        raise


def main():
    logging.info("===== CÔNG CỤ LẤY LINK BÀI VIẾT FACEBOOK VÀ GỬI LÊN API =====")

    cookie_file_path = "facebook_cookies.txt"

    # Nhập thông tin đăng nhập
    email = input("Nhập email Facebook: ")
    password = input("Nhập password Facebook: ")

    group_url = "https://www.facebook.com/groups/tansinhvienneu"
    max_posts = int(input("Nhập số lượng bài viết cần lấy (mặc định: 50): ") or "50")

    driver = None
    try:
        driver = setup_driver()
        if login_to_facebook(driver, cookie_file_path, email, password):
            if get_post_links_from_group(driver, group_url, max_posts):
                logging.info(f"Đã hoàn thành thu thập và gửi {max_posts} bài viết lên API!")
            else:
                logging.warning("Không tìm thấy bài viết nào để gửi lên API hoặc gửi thất bại.")

    except Exception as e:
        logging.error(f"Lỗi chính trong chương trình: {str(e)}")
    finally:
        if driver:
            try:
                driver.quit()
                logging.info("Đã đóng trình duyệt.")
            except Exception as e:
                logging.error(f"Lỗi khi đóng trình duyệt: {str(e)}")


if __name__ == "__main__":
    main()