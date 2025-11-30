import psycopg2
from dotenv import load_dotenv
import os
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime
import time

load_dotenv()


class TVLUpdater:
    def __init__(self, debug=False):
        # 優先從環境變數讀取，其次從 .env 檔案
        self.db_config = {
            "user": os.getenv("user") or os.getenv("DB_USER"),
            "password": os.getenv("password") or os.getenv("DB_PASSWORD"),
            "host": os.getenv("host") or os.getenv("DB_HOST"),
            "port": os.getenv("port") or os.getenv("DB_PORT"),
            "dbname": os.getenv("dbname") or os.getenv("DB_NAME"),
        }

        self.base_url = "https://tvl.ctvba.org.tw"
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }

        self.connection = None
        self.cursor = None

        # 男生: 264–326
        self.male_range = (264, 326)
        # 女生: 228–278
        self.female_range = (228, 278)
        
        self.debug = debug

    # -------------------------------------------------------
    # 資料庫
    # -------------------------------------------------------
    def connect(self):
        try:
            params = self.db_config.copy()
            if "pooler.supabase.com" in params.get("host", ""):
                print("檢測到 Supabase Pooler，使用安全 timeout 設定…")
                params["options"] = "-c statement_timeout=60000"

            self.connection = psycopg2.connect(**params)
            self.cursor = self.connection.cursor()
            self.cursor.execute("SELECT 1")
            print("✅ 資料庫連線成功")
            return True
        except Exception as e:
            print(f"❌ 資料庫連線失敗: {e}")
            return False

    def close(self):
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()
        print("資料庫已關閉")

    # -------------------------------------------------------
    # 建立資料表（極簡版）
    # -------------------------------------------------------
    def create_tables(self):
        sql = """
        CREATE TABLE IF NOT EXISTS tvl_matches (
            id SERIAL PRIMARY KEY,
            match_id INTEGER NOT NULL,
            gender TEXT NOT NULL CHECK (gender IN ('male', 'female')),
            match_date DATE,
            match_time TEXT,
            home_team_name TEXT NOT NULL,
            away_team_name TEXT NOT NULL,
            status TEXT,
            home_score INTEGER,
            away_score INTEGER,
            set_scores TEXT,
            url TEXT NOT NULL,
            scraped_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(match_id, gender)
        );

        CREATE INDEX IF NOT EXISTS idx_tvl_matches_date ON tvl_matches(match_date);
        CREATE INDEX IF NOT EXISTS idx_tvl_matches_gender ON tvl_matches(gender);
        CREATE INDEX IF NOT EXISTS idx_tvl_matches_status ON tvl_matches(status);
        CREATE INDEX IF NOT EXISTS idx_tvl_matches_teams ON tvl_matches(home_team_name, away_team_name);
        """

        self.cursor.execute(sql)
        self.connection.commit()
        print("✅ 資料表建立完成")

    # -------------------------------------------------------
    # 抓取單一比賽頁面
    # -------------------------------------------------------
    def fetch_page(self, match_id, gender):
        if gender == "male":
            url = f"{self.base_url}/game/{match_id}"
        else:
            url = f"{self.base_url}/wgame/{match_id}"

        try:
            r = requests.get(url, headers=self.headers, timeout=20)

            if r.status_code != 200:
                if self.debug:
                    print(f"[{gender}] {match_id} 回傳 {r.status_code}，跳過")
                return None

            if len(r.content) < 10000:
                if self.debug:
                    print(f"[{gender}] {match_id} 頁面太小，跳過")
                return None

            soup = BeautifulSoup(r.text, "html.parser")
            return soup

        except Exception as e:
            print(f"[{gender}] {match_id} 抓取失敗: {e}")
            return None

    # -------------------------------------------------------
    # 解析球隊（直接從表格抓名稱）
    # -------------------------------------------------------
    def get_team_names(self, soup):
        """直接從比賽表格抓取球隊名稱"""
        try:
            match_table = soup.select_one(".match_table")
            if not match_table:
                return None, None
            
            tbody = match_table.find("tbody")
            if not tbody:
                return None, None
            
            rows = tbody.find_all("tr")
            if len(rows) < 2:
                return None, None
            
            # 第一列是主隊，第二列是客隊
            home_name = rows[0].find("td").text.strip()
            away_name = rows[1].find("td").text.strip()
            
            if self.debug:
                print(f"  📋 球隊: {home_name} vs {away_name}")
            
            return home_name, away_name
            
        except Exception as e:
            if self.debug:
                print(f"  ⚠️  球隊解析失敗: {e}")
            return None, None

    # -------------------------------------------------------
    # 解析日期和時間
    # -------------------------------------------------------
    def parse_datetime(self, soup):
        """從 HTML 中解析日期和時間"""
        try:
            game_header = soup.select_one(".game_header")
            if not game_header:
                return None, None
            
            text = game_header.get_text()
            datetime_match = re.search(r'(\d{4}[-/]\d{2}[-/]\d{2})\s+(\d{2}:\d{2})', text)
            
            if datetime_match:
                date_str = datetime_match.group(1).replace('/', '-')
                time_str = datetime_match.group(2)
                
                if self.debug:
                    print(f"  📅 日期: {date_str}, 時間: {time_str}")
                
                return date_str, time_str
            
            return None, None
            
        except Exception as e:
            if self.debug:
                print(f"  ⚠️  日期解析失敗: {e}")
            return None, None

    # -------------------------------------------------------
    # 解析比分和狀態
    # -------------------------------------------------------
    def parse_score_and_status(self, soup):
        """解析比分和比賽狀態"""
        try:
            # 找大比分
            home_score_tag = soup.select_one(".score_home.big_score")
            away_score_tag = soup.select_one(".score_away.big_score")
            
            # 找狀態
            status_badge = soup.select_one(".badge")
            status = "scheduled"
            
            if status_badge:
                status_text = status_badge.text.strip()
                if "已完賽" in status_text or "完賽" in status_text:
                    status = "finished"
                elif "進行中" in status_text or "LIVE" in status_text:
                    status = "live"
            
            # 解析大比分
            home_score = None
            away_score = None
            
            if home_score_tag and away_score_tag:
                try:
                    home_score = int(home_score_tag.text.strip())
                    away_score = int(away_score_tag.text.strip())
                except:
                    pass
            
            # 解析局數比分
            set_scores = []
            table = soup.select_one(".match_table")
            
            if table:
                rows = table.select("tbody tr")
                if len(rows) >= 2:
                    home_row = rows[0]
                    away_row = rows[1]
                    
                    for i in range(1, 6):
                        home_cell = home_row.select_one(f"#q{i}_home")
                        away_cell = away_row.select_one(f"#q{i}_away")
                        
                        if home_cell and away_cell:
                            home_set = home_cell.text.strip()
                            away_set = away_cell.text.strip()
                            
                            if home_set and away_set and home_set.isdigit() and away_set.isdigit():
                                set_scores.append(f"{home_set}-{away_set}")
            
            set_scores_str = ", ".join(set_scores) if set_scores else None
            
            if self.debug:
                print(f"  🏐 狀態: {status}, 比分: {home_score}-{away_score}")
            
            return (status, home_score, away_score, set_scores_str)
            
        except Exception as e:
            if self.debug:
                print(f"  ⚠️  比分解析失敗: {e}")
            return ("scheduled", None, None, None)

    # -------------------------------------------------------
    # 解析比賽
    # -------------------------------------------------------
    def parse_match(self, match_id, gender, soup):
        try:
            # 抓球隊名稱
            home_name, away_name = self.get_team_names(soup)
            if not home_name or not away_name:
                if self.debug:
                    print(f"[{gender}] {match_id} 找不到球隊")
                return None

            # 抓日期時間
            match_date, match_time = self.parse_datetime(soup)

            # 抓比分和狀態
            status, home_score, away_score, set_scores = self.parse_score_and_status(soup)

            return {
                "match_id": match_id,
                "gender": gender,
                "match_date": match_date,
                "match_time": match_time,
                "home_name": home_name,
                "away_name": away_name,
                "status": status,
                "home_score": home_score,
                "away_score": away_score,
                "set_scores": set_scores,
                "url": f"{self.base_url}/{'game' if gender=='male' else 'wgame'}/{match_id}",
            }
        
        except Exception as e:
            print(f"[{gender}] {match_id} 解析失敗: {e}")
            if self.debug:
                import traceback
                traceback.print_exc()
            return None

    # -------------------------------------------------------
    # 寫入資料庫
    # -------------------------------------------------------
    def insert_match(self, data):
        sql = """
        INSERT INTO tvl_matches
        (match_id, gender, match_date, match_time,
         home_team_name, away_team_name,
         status, home_score, away_score, set_scores, url)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (match_id, gender) DO UPDATE SET
            match_date = EXCLUDED.match_date,
            match_time = EXCLUDED.match_time,
            home_team_name = EXCLUDED.home_team_name,
            away_team_name = EXCLUDED.away_team_name,
            status = EXCLUDED.status,
            home_score = EXCLUDED.home_score,
            away_score = EXCLUDED.away_score,
            set_scores = EXCLUDED.set_scores,
            scraped_at = NOW();
        """

        self.cursor.execute(
            sql,
            (
                data["match_id"],
                data["gender"],
                data["match_date"],
                data["match_time"],
                data["home_name"],
                data["away_name"],
                data["status"],
                data["home_score"],
                data["away_score"],
                data["set_scores"],
                data["url"],
            ),
        )
        self.connection.commit()

    # -------------------------------------------------------
    # 主流程
    # -------------------------------------------------------
    def run(self):
        if not self.connect():
            return

        self.create_tables()

        total_success = 0
        total_failed = 0

        # 女子組
        print("\n" + "="*50)
        print("🏐 開始抓取女子組比賽")
        print("="*50)
        
        for match_id in range(self.female_range[0], self.female_range[1] + 1):
            soup = self.fetch_page(match_id, "female")
            if soup:
                data = self.parse_match(match_id, "female", soup)
                if data:
                    self.insert_match(data)
                    status_emoji = {"scheduled": "⏰", "live": "🔴", "finished": "✅"}.get(data["status"], "❓")
                    print(f"{status_emoji} 女 {match_id}: {data['home_name']} vs {data['away_name']}")
                    total_success += 1
                else:
                    total_failed += 1
            else:
                total_failed += 1
            
            time.sleep(0.5)

        # 男子組
        print("\n" + "="*50)
        print("🏐 開始抓取男子組比賽")
        print("="*50)
        
        for match_id in range(self.male_range[0], self.male_range[1] + 1):
            soup = self.fetch_page(match_id, "male")
            if soup:
                data = self.parse_match(match_id, "male", soup)
                if data:
                    self.insert_match(data)
                    status_emoji = {"scheduled": "⏰", "live": "🔴", "finished": "✅"}.get(data["status"], "❓")
                    print(f"{status_emoji} 男 {match_id}: {data['home_name']} vs {data['away_name']}")
                    total_success += 1
                else:
                    total_failed += 1
            else:
                total_failed += 1
            
            time.sleep(0.5)

        print("\n" + "="*50)
        print(f"✅ 抓取完成！成功: {total_success}, 失敗: {total_failed}")
        print("="*50)
        
        self.close()


if __name__ == "__main__":
    # 可以設定 debug=True 看詳細訊息
    updater = TVLUpdater(debug=False)
    updater.run()