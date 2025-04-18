from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time
import os
import logging

def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--start-maximized")
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def save_cookies(driver, cookie_file_path):
    try:
        cookies = driver.get_cookies()
        with open(cookie_file_path, 'w', encoding='utf-8') as f:
            for cookie in cookies:
                f.write(f"{cookie['domain']}\tTRUE\t{cookie['path']}\t"
                        f"{cookie['secure']}\t{cookie.get('expiry', 0)}\t"
                        f"{cookie['name']}\t{cookie['value']}\n")
        print(f"✅ Đã lưu cookies vào {cookie_file_path}")
    except Exception as e:
        print(f"❌ Lỗi khi lưu cookies: {str(e)}")

def main():
    cookie_file_path = "facebook_cookies.txt"
    driver = setup_driver()

    print("➡️ Trình duyệt đã mở. Hãy đăng nhập Facebook và xác thực 2 bước nếu cần.")
    input("✅ Sau khi đăng nhập thành công, nhấn Enter để lưu cookies...")

    save_cookies(driver, cookie_file_path)

    driver.quit()
    print("✅ Đã đóng trình duyệt.")

if __name__ == "__main__":
    main()
