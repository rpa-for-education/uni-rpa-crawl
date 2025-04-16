import pandas as pd
import re
from datetime import datetime

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

def convert_date_format(date_str):
    if pd.isna(date_str):
        return date_str
    
    try:
        # Phân tích chuỗi ngày tháng
        # Mẫu: 'Chủ Nhật, 13 Tháng 4, 2025 lúc 20:25'
        pattern = r'.*?,\s*(\d+)\s*Tháng\s*(\d+),\s*(\d+)\s*lúc\s*(\d+):(\d+)'
        match = re.search(pattern, date_str)
        
        if match:
            day = int(match.group(1))
            month = int(match.group(2))
            year = int(match.group(3))
            hour = int(match.group(4))
            minute = int(match.group(5))
            
            # Định dạng mới: 'năm-tháng-ngày giờ:phút'
            return f"{year}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}"
        else:
            return " "
    except Exception as e:
        print(f"Lỗi khi xử lý '{date_str}': {str(e)}")
        return "Lỗi định dạng"

def main():
    # Read the Excel file
    try:
        df = pd.read_excel('crawled.xlsx')
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
    df['DATE CONVERTED'] = df['DATE'].apply(convert_date_format)

    # Save back to the same Excel file
    try:
        df.to_excel('crawled.xlsx', index=False)
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

if __name__ == "__main__":
    main() 