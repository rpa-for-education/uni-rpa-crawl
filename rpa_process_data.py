import requests
import pandas as pd
import re
from datetime import datetime, timedelta

with open(r"C:\Users\Administrator\Desktop\Crawl\log.txt", "a") as f:
    f.write(f"Script ran at {datetime.now()}\n")
    api_url = "http://api.rpa4edu.shop/api_bai_viet.php"

def process_data(text):
    # Initialize default values
    likes = None
    comments = None
    shares = None

    # Skip if the text is just headers
    if text in ['Thích', 'Bình luận', 'Sao chép', 'Chia sẻ']:
        return None, None, None

    # Extract likes
    likes_match = re.search(r'Tất cả cảm xúc:\s*(\d+)', text)
    if likes_match:
        likes = int(likes_match.group(1))

    # Extract comments
    comments_match = re.search(r'(\d+)\s*bình luận', text)
    if comments_match:
        comments = int(comments_match.group(1))

    # Extract shares
    shares_match = re.search(r'(\d+)\s*lượt chia sẻ', text)
    if shares_match:
        shares = int(shares_match.group(1))

    return likes, comments, shares


def parse_vietnamese_date(text, current_time=None):
    if current_time is None:
        current_time = datetime.now()

    # Kiểm tra đầu vào hợp lệ
    if not isinstance(text, str):
        return None

    text = text.lower().strip()

    # 1. Kiểu "11 giò" hoặc "9 giò"
    match = re.search(r'(\d+)\s*gi[òo]', text)
    if match:
        hours_ago = int(match.group(1))
        dt = current_time - timedelta(hours=hours_ago)
        return dt.strftime('%Y-%m-%d %H:%M:%S')

    # 2. Kiểu "5 tháng 6 lúc 15:37"
    match = re.search(r'(\d{1,2}) tháng (\d{1,2}) lúc (\d{1,2}):(\d{2})', text)
    if match:
        day, month, hour, minute = map(int, match.groups())
        year = current_time.year
        dt = datetime(year, month, day, hour, minute)
        return dt.strftime('%Y-%m-%d %H:%M:%S')

    # 3. Kiểu "19 tháng 11, 2024"
    match = re.search(r'(\d{1,2}) tháng (\d{1,2}),?\s*(\d{4})', text)
    if match:
        day, month, year = map(int, match.groups())
        dt = datetime(year, month, day)
        return dt.strftime('%Y-%m-%d %H:%M:%S')

    # ✅ 4. Kiểu "Nguòi tham gia án danh 5 tháng 1" → chỉ ngày & tháng
    match = re.search(r'(\d{1,2}) tháng (\d{1,2})', text)
    if match:
        day, month = map(int, match.groups())
        year = current_time.year
        try:
            dt = datetime(year, month, day)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            return None

    return None


def clean_nan_values(record):
    return {k: ("" if pd.isna(v) else v) for k, v in record.items()}


def main():
    # Read the Excel file
    try:
        df = pd.read_excel(r"C:\Users\Administrator\Desktop\Crawl\crawled.xlsx")
    except FileNotFoundError:
        print("Không tìm thấy file crawled.xlsx")
        return

    # Process data for likes, comments, and shares
    for index, text in enumerate(df.iloc[:, 6]):  # Process column 6
        likes, comments, shares = process_data(str(text))

        # Update the existing columns
        df.at[index, 'LIKE'] = likes
        df.at[index, 'SHARE'] = shares
        df.at[index, 'COMMENT'] = comments

    # Check and rename DATE column if needed
    if 'DATE' not in df.columns and df.shape[1] >= 8:
        column_name = df.columns[7]
        print(f"Không tìm thấy cột 'DATE', sử dụng cột '{column_name}' ở vị trí H")
        df.rename(columns={column_name: 'DATE'}, inplace=True)
    elif 'DATE' not in df.columns:
        print("Không tìm thấy cột DATE trong file Excel")
        return

    # Create DATE CONVERTED column if it doesn't exist
    if 'DATE CONVERTED' not in df.columns:
        df['DATE CONVERTED'] = None

    # Convert dates
    df['DATE CONVERTED'] = df['DATE'].apply(parse_vietnamese_date)

    # Save back to the same Excel file
    try:
        df.to_excel(r"C:\Users\Administrator\Desktop\Crawl\crawled_new.xlsx", index=False)
        print("Processing completed. Results updated in 'crawled.xlsx'")

        # Show some sample data
        print("\nSample of processed data:")
        sample = pd.DataFrame({
            'DATE_ORIGINAL': df['DATE'].head(),
            'DATE_CONVERTED': df['DATE CONVERTED'].head(),
            'LIKE': df['LIKE'].head(),
            'COMMENT': df['COMMENT'].head(),
            'SHARE': df['SHARE'].head()
        })
        print(sample)

    except Exception as e:
        print(f"Có lỗi khi lưu file: {str(e)}")
        print("Vui lòng đảm bảo file Excel không đang được mở bởi chương trình khác.")

    # Đọc Excel
    df = pd.read_excel(r"C:\Users\Administrator\Desktop\Crawl\crawled_new.xlsx")
    ## Cập nhật lên API
    for index, row in df.iterrows():
        if pd.isna(row.iloc[0]):  # Nếu ID bị NaN
            print(f"⚠️ Bỏ qua dòng {index} vì thiếu ID")
            continue
        data = {
            "id_bai_viet": int(row.iloc[0]),    # ID BÀI VIẾT
            "id_nguoi_dung": row.iloc[2],       # TÁC GIẢ
            "noi_dung_bai_viet": row.iloc[1],   # NỘI DUNG
            "like": row.iloc[3],                # LIKE
            "share": row.iloc[4],               # SHARE
            "comment": row.iloc[5],             # COMMENT
            "content": row.iloc[6],             # Tổng tương tác
            "created": row.iloc[7],             # DATE
            "created_time": row.iloc[9],        # DATE CONVERTED
            "inserted_time": row.iloc[8],       # TGIAN CHUẨN
            "modified_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),       # DATE CONVERTED
            "is_deleted": row.iloc[10]          # ĐÃ XÓA
        }
        ## print(data)

        # Loại bỏ NaN
        data = clean_nan_values(data)

        try:
            headers = {"Content-Type": "application/json"}
            response = requests.put(api_url, json=data, headers=headers, timeout=10)
            response.raise_for_status()
            if response.status_code == 200:
                print(f"✅ Đã cập nhật ID {row.iloc[0]}")
            else:
                print(f"❌ Lỗi cập nhật ID {row.iloc[0]}: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"⚠️ Lỗi kết nối cho ID {row.iloc[0]}: {e}")



if __name__ == "__main__":
    main() 