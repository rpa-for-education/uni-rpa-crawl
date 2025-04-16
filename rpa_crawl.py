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
        # Cấu hình Chrome Options
        chrome_options = Options()
        chrome_options.add_argument("--disable-notifications")  # Tắt thông báo
        chrome_options.add_argument("--start-maximized")  # Mở cửa sổ tối đa
        
        # Khởi tạo trình điều khiển Chrome
        driver = webdriver.Chrome(options=chrome_options)
        return driver
    except Exception as e:
        logging.error(f"Error setting up driver: {str(e)}")
        raise

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
                    else:
                        cookie_match = re.search(r'(\w+)=([^;]+)', line)
                        if cookie_match:
                            name, value = cookie_match.groups()
                            cookie = {
                                'name': name,
                                'value': value,
                                'domain': '.facebook.com'
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
def login_to_facebook(driver, cookie_file_path):
    """Đăng nhập vào Facebook sử dụng file cookie.txt"""
    try:
        # Kiểm tra file cookie tồn tại
        if not os.path.exists(cookie_file_path):
            logging.error(f"Không tìm thấy file cookie: {cookie_file_path}")
            return False
        
        # Phân tích file cookie.txt
        cookies_list = parse_cookie_file(cookie_file_path)
        
        if not cookies_list:
            logging.error("Không thể trích xuất cookie từ file hoặc file không chứa cookie hợp lệ.")
            return False
        
        # Hiển thị các cookie quan trọng đã tìm thấy
        essential_cookies = extract_essential_cookies(cookies_list)
        logging.info(f"Đã tìm thấy {len(cookies_list)} cookie, bao gồm các cookie quan trọng")
        
        # Truy cập Facebook trước khi thêm cookie
        driver.get("https://www.facebook.com")
        time.sleep(2)
        
        # Xóa cookies hiện tại
        driver.delete_all_cookies()
        
        # Thêm cookies từ danh sách
        cookie_added_count = 0
        for cookie in cookies_list:
            try:
                driver.add_cookie(cookie)
                cookie_added_count += 1
            except Exception as e:
                logging.warning(f"Không thể thêm cookie {cookie['name']}: {e}")
        
        logging.info(f"Đã thêm {cookie_added_count}/{len(cookies_list)} cookie vào trình duyệt")
        
        # Refresh trang để áp dụng cookies
        driver.get("https://www.facebook.com")
        
        # Kiểm tra đăng nhập thành công
        try:
            wait = WebDriverWait(driver, 10)
            search_box = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@placeholder='Tìm kiếm trên Facebook' or @placeholder='Search Facebook']")))
            logging.info("Đăng nhập thành công!")
            return True
        except Exception as e:
            logging.error(f"Kiểm tra đăng nhập thất bại: {e}")
            logging.error("Cookie có thể không hợp lệ hoặc đã hết hạn")
            return False
            
    except Exception as e:
        logging.error(f"Lỗi trong quá trình đăng nhập: {e}")
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
        # Mở trang group
        driver.get(group_url)
        logging.info(f"Đang truy cập vào group: {group_url}")
        
        # Chờ cho đến khi trang group tải xong
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, "//div[@role='main']"))
        )
        
        # Danh sách lưu trữ các link bài viết đã xử lý
        processed_links = set()
        collected_count = 0
        
        # Cuộn trang để tải thêm bài viết
        last_height = driver.execute_script("return document.body.scrollHeight")
        scroll_attempts = 0
        max_scroll_attempts = 5

        while collected_count < max_posts and scroll_attempts < max_scroll_attempts:
            try:
                # Tìm các container bài viết
                post_containers = driver.find_elements(By.XPATH, "//div[@role='article']")
                if not post_containers:
                    post_containers = driver.find_elements(By.XPATH, "//div[contains(@data-pagelet, 'FeedUnit')]")

                logging.info(f"Tìm thấy {len(post_containers)} post containers trên màn hình.")

                for container in post_containers:
                    if collected_count >= max_posts:
                        break
                    try:
                        # Tìm link bài viết trong container
                        link_element = container.find_element(By.XPATH, ".//a[contains(@href, '/groups/') and contains(@href, '/posts/') and not(ancestor::div[contains(@class, 'text_exposed_root')])]")
                        link = link_element.get_attribute("href")
                        cleaned_link = clean_post_url(link)

                        # Kiểm tra xem link đã được xử lý chưa
                        if cleaned_link and cleaned_link not in processed_links:
                            processed_links.add(cleaned_link)
                            collected_count += 1

                            # Gửi link lên API ngay lập tức
                            payload = {"url": cleaned_link}
                            try:
                                response = requests.post("https://api.rpa4edu.shop/api_bai_viet.php", json=payload)
                                if response.status_code == 200:
                                    try:
                                        result = response.json()
                                        logging.info(f"Đã gửi link lên API thành công ({collected_count}/{max_posts}): {cleaned_link} | Phản hồi: {result}")
                                    except json.JSONDecodeError:
                                        logging.warning(f"Đã gửi link lên API thành công nhưng phản hồi không phải JSON ({collected_count}/{max_posts}): {cleaned_link}")
                                else:
                                    logging.error(f"Lỗi khi gửi API cho link {cleaned_link}: HTTP {response.status_code}, {response.text}")
                            except requests.exceptions.RequestException as e:
                                logging.error(f"Lỗi kết nối khi gửi API cho link {cleaned_link}: {str(e)}")

                            # Thêm delay ngẫu nhiên để tránh quá tải API
                            time.sleep(random.uniform(0.5, 1.5))

                    except NoSuchElementException:
                        continue
                    except Exception as e:
                        logging.warning(f"Lỗi khi xử lý một container bài viết: {str(e)}")
                        continue
                
                if collected_count >= max_posts:
                    logging.info(f"Đã thu thập đủ {max_posts} bài viết.")
                    break
                
                # Cuộn xuống để tải thêm bài viết
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                
                # Chờ động dựa trên số lượng bài viết đã thu thập
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
    
    # Đường dẫn đến file cookie
    cookie_file_path = "facebook_cookies.txt"
    
    # Nhập URL của group và số lượng bài viết cần lấy
    group_url = "https://www.facebook.com/groups/tansinhvienneu"
    max_posts = int(input("Nhập số lượng bài viết cần lấy (mặc định: 50): ") or "50")
    
    driver = None
    try:
        # Thiết lập trình duyệt
        driver = setup_driver()
        
        # Đăng nhập vào Facebook bằng cookie
        if login_to_facebook(driver, cookie_file_path):
            # Lấy link bài viết từ group và gửi lên API
            if get_post_links_from_group(driver, group_url, max_posts):
                logging.info(f"Đã hoàn thành thu thập và gửi {max_posts} bài viết lên API!")
            else:
                logging.warning("Không tìm thấy bài viết nào để gửi lên API hoặc gửi thất bại.")
        
    except Exception as e:
        logging.error(f"Lỗi chính trong chương trình: {str(e)}")
    finally:
        # Đóng trình duyệt
        if driver:
            try:
                driver.quit()
                logging.info("Đã đóng trình duyệt.")
            except Exception as e:
                logging.error(f"Lỗi khi đóng trình duyệt: {str(e)}")

if __name__ == "__main__":
    main()